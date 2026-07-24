# A股量化系统 — 功能规格说明书 (Feature Spec)

**文档版本**: 1.0 (2026-07-24)
**状态**: 初始草案
**上游**: US-001 ~ US-026

---

## 1. 市场监控模块

### 1.1 CR5%/CR10% 拥挤度趋势

**上游**: US-001

#### I/O 边界矩阵

| 项目 | 说明 |
|------|------|
| **端点** | `GET /api/market-review/base-data` |
| **输入参数** | `period`(day/week/month/quarter/year), `include_index`(bool), `start_date`, `end_date` |
| **输出结构** | `{dates[], cr5_pct[], cr10_pct[], ma50_pct[], ma20_pct[], nh[], nl[], index_close[]}` |
| **数据源** | `base_data_daily` (按 `date` 字段查询) |
| **聚合逻辑** | 后端IndexFactory.aggregate_by_period()实现日/周/月/季/年聚合 |
| **状态码** | 200(成功), 500(数据库错误) |

#### 边缘用例矩阵

| 场景 | 行为 |
|------|------|
| 数据库为空 | 返回空数组 `{ dates: [], cr5_pct: [] }` |
| 某天数据is_final=false | 跳过该天(不展示未完成数据) |
| 聚合周期无数据 | 该周期点返回null |
| 叠加的指数代码不存在 | 跳过指数叠加，返回无指数数据的基础指标 |

---

### 1.2 大盘指数涨跌幅

**上游**: US-004

#### I/O 边界矩阵

| 项目 | 说明 |
|------|------|
| **端点** | `GET /api/market-review/overview?date=YYYYMMDD` |
| **输出** | `{ indices: [{code, name, chg_pct, close, pe_ttm}], update_time }` |
| **数据源** | `index_daily` + `market_daily.overview` 缓存 |
| **状态码** | 200(成功) |

#### 错误处理

| 错误 | 响应 |
|------|------|
| date参数缺失 | 使用最新交易日 |
| 指定日期无数据 | 返回 `{ indices: [], message: "无数据" }` |

---

### 1.3 AI综合研判

**上游**: US-005

#### I/O 边界矩阵

| 项目 | 说明 |
|------|------|
| **端点** | `GET /api/market-review/ai-analysis?date=YYYYMMDD` |
| **触发生成** | `POST /api/market-review/ai-analysis/generate` (body: `{date}`) |
| **查询状态** | `GET /api/market-review/ai-analysis/task/{task_id}` |
| **AI模型** | deepseek-v4-pro + reasoning_effort=high |
| **输入数据** | 从 `market_daily` + `base_data_daily` 读取 |
| **缓存策略** | 盘后永久缓存(`market_daily.ai_analysis`)，盘中30分钟内缓存 |
| **状态码** | 200(有缓存)、202(生成中)、404(无缓存且未生成) |

#### 状态机

```
[无缓存] → POST /generate → [生成中] → 轮询task_id → [完成: 缓存到market_daily]
                                                      → [失败: 返回错误信息]
```

#### 边缘用例

| 场景 | 行为 |
|------|------|
| 盘后首次请求无缓存 | 自动触发生成(无需用户点击) |
| 盘中请求 | 返回最近一次缓存(最旧不超过30分钟) |
| DeepSeek API超时 | 重试2次，仍失败则返回"AI服务暂时不可用" |
| 不在允许时间窗口(`config/deepseek-time-limit`) | 返回 `need_generate: true` 但不自动触发 |
| 同一天多次触发生成 | 返回已有task_id，不重复创建 |

---

## 2. 复盘报告模块

### 2.1 新高板块效应聚类

**上游**: US-006

#### I/O 边界矩阵

| 项目 | 说明 |
|------|------|
| **端点** | `GET /api/market-review/new-high-blocks?date=YYYYMMDD` |
| **输出** | `{ sectors: [{ name, chg_pct, pioneer: [3 stocks], main_force: [3 stocks], followers: [2 stocks] }], update_time }` |
| **数据源** | `market_daily.new_high` 缓存优先，无缓存则实时从 `stock_daily` + `sector_basics` 计算 |
| **缓存** | 写入 `market_daily.new_high` |

#### 状态机

```
请求到来 → 查询market_daily缓存有数据? → 是 → 返回缓存
                                         → 否 → 实时计算:
                                               1. 找当日NH>0的股票
                                               2. 从sector_basics反向查询板块归属
                                               3. 按板块聚合，Top10
                                               4. 每个板块选先锋/中军/后排
                                               5. 返回结果并写入缓存
```

#### 梯队选择规则

| 梯队 | 数量 | 选取逻辑 |
|------|------|----------|
| pioneer | 3 | 按chg_50d降序取前3 |
| main_force | 3 | 成交额Top10内按chg_50d降序取前3 |
| followers | 2 | 成交额升序Top20(排除ST)按当日涨幅降序取前2 |

#### 边缘用例

| 场景 | 行为 |
|------|------|
| 某板块新高股票不足8只 | 按实际数量返回，不填充 |
| 排除板块 | 在sector_basics中标记exclude_display=true的板块跳过 |
| 当日无新高股票 | 返回空列表 `{ sectors: [] }` |

---

### 2.2 低位潜力板块

**上游**: US-007

#### I/O 边界矩阵

| 项目 | 说明 |
|------|------|
| **端点** | `GET /api/market-review/low-position-sectors?date=YYYYMMDD` |
| **输出** | `{ sectors: [{ name, rps10, rps50, pioneer/main_force/followers }] }` (最多5个) |
| **数据源** | 仅从 `market_daily.low_position_sectors` 缓存读取 |

#### 筛选条件矩阵

| 条件 | 说明 |
|------|------|
| MA10 > MA20 | 板块指数短期均线在长期均线上方 |
| RPS10 > 85 | 短线爆发力强 |
| RPS50 < 70 | 长线尚未走强，处于低位 |
| 近3天≥1天有≥15%股票创20日新高 | 板块内有资金活跃迹象 |
| 近5天有4天净新高(20日新高-20日新低) > -10 | 板块持续有赚钱效应 |

#### 边缘用例

| 场景 | 行为 |
|------|------|
| 符合条件的板块为0 | 返回空列表 |
| 缓存不存在 | 返回 `{ need_generate: true }` |
| 排除板块 | 自动过滤 |

---

## 3. 日历复盘模块

### 3.1 每日摘要日历

**上游**: US-008

#### I/O 边界矩阵

| 项目 | 说明 |
|------|------|
| **端点** | `GET /api/calendar/daily-summary?year=YYYY&month=MM` |
| **输出** | `{ days: [{ trade_date, up_count, down_count, amount, market_chg, top_sector, ai_position }] }` |
| **生成快照** | `POST /api/calendar/generate-snapshots` (body: `{year, month}`) |

#### 状态机

```
请求每日摘要 → 快照已生成? → 是 → 返回快照
                            → 否 → POST generate-snapshots → 后台逐天预计算
                                   → 前端显示"正在生成" → 完成后自动刷新
```

---

### 3.2 AI周总结

**上游**: US-024

#### I/O 边界矩阵

| 项目 | 说明 |
|------|------|
| **端点** | `POST /api/calendar/weekly-summary` |
| **输入** | `{year, month, weekIndex}` |
| **查询** | `GET /api/calendar/weekly-cached?year=&month=&weekIndex=` |
| **任务查询** | `GET /api/calendar/weekly-task/{task_id}` |
| **输入数据预览** | `GET /api/calendar/weekly-input-data?year=&month=&weekIndex=` |

#### 缓存策略

```
请求周总结 → 已缓存? → 是 → 返回缓存
                     → 否 → 启动后台DeepSeek任务 → 返回task_id
                                                     → 前端轮询 → 完成时自动展示
```

---

### 3.3 AI月总结

**上游**: US-026

与周总结相同模式，依赖周总结数据聚合。

---

## 4. 市场分析模块

### 4.1 四维动量气泡图

**上游**: US-017

#### I/O 边界矩阵

| 项目 | 说明 |
|------|------|
| **端点** | `GET /api/market_analysis/bubble` |
| **参数** | `mode`(sector/stock), `trade_date` |
| **输出** | `{ items: [{ code, name, rps, chg_pct, amount, group }] }` |
| **数据源** | `stock_daily` / `sector_daily` |

#### 边缘用例

| 场景 | 行为 |
|------|------|
| trade_date参数缺失 | 使用最新交易日 |
| 该日数据is_final=false | 返回数据但标记is_final=false |
| 无数据 | 返回空数组 |

---

### 4.2 活跃股池

**上游**: US-019

#### I/O 边界矩阵

| 项目 | 说明 |
|------|------|
| **端点** | `GET /api/market_analysis/active_pool?date=YYYYMMDD` |
| **筛选条件** | `rps_sum = rps_20+rps_50+max(rps_120,rps_250) > 270` 且 `chg_pct > 5%` |
| **数据源** | `stock_daily.is_active` 预计算字段 |
| **输出** | `{ stocks: [{ code, name, rps_sum, chg_pct, amount }] }` |

---

## 5. 个股分析模块

### 5.1 K线 + RPS历史

**上游**: US-020, US-025

#### I/O 边界矩阵

| 项目 | 说明 |
|------|------|
| **端点** | `GET /api/stocks/{code}/daily?start_date=&end_date=&limit=` |
| **RPS端点** | `GET /api/factors/rps/{code}?start_date=&end_date=&period=` |
| **输出(K线)** | `{ data: [{ trade_date, open, high, low, close, vol, ma10, ma20, ma50, ma120 }] }` |
| **输出(RPS)** | `{ data: [{ trade_date, rps_20, rps_50, rps_120, rps_250 }] }` |
| **搜索** | `GET /api/stocks/search?q=` (前缀/拼音/代码模糊匹配) |

#### 边缘用例

| 场景 | 行为 |
|------|------|
| 股票代码不存在 | 返回404 |
| 日线数据不足 | 返回已有数据，均线字段可能为null |
| 搜索关键字过短(<1字符) | 返回400 |
| 搜索无结果 | 返回空数组 |

---

## 6. 数据管理模块

### 6.1 数据同步

**上游**: US-009, US-010, US-011

#### 数据源瀑布

```
个股日线: PyTdX → AkShare → BaoStock → yfinance
板块日线: PyTdX (block_*.dat + 880/881指数)
指数日线: PyTdX
指数PE: 乐咕乐股(legulegu.com)
```

#### I/O 边界矩阵

| 端点 | 方法 | 说明 |
|------|------|------|
| `POST /api/settings-tasks/sync-indices` | POST | 同步指数日线(steps模式) |
| `POST /api/settings-tasks/sync-daily` | POST | 同步个股日线(steps模式) |
| `POST /api/settings-tasks/sync-sectors` | POST | 同步板块(steps模式) |
| `POST /api/settings-tasks/sync-index-pe` | POST | 同步PE(steps模式) |
| `POST /api/one-click-update/start` | POST | Orchestrator 7步骤全量执行 |

#### 同步边界条件

| 条件 | 行为 |
|------|------|
| 同步时间窗口外(不在11:30-13:00且不在15:30-23:59) | 拒绝执行，返回"不在同步时间窗口" |
| 个股最小上市天数 < 120 | 跳过RPS计算但不跳过数据同步 |
| 某数据源全部连接失败 | 自动降级到下一数据源 |
| 所有数据源均失败 | 记录该股票/板块到失败列表，继续处理下一个 |

---

### 6.2 RPS计算

**上游**: US-012

#### 计算参数

| 参数 | 个股 | 板块 |
|------|------|------|
| RPS周期 | 20/50/120/250 | 10/20/50 |
| 最小存续天数 | ≥120个交易日 | ≥20个交易日 |
| 计算引擎 | FactorEngine | FactorEngine |
| 写入目标 | `stock_daily.rps_*` | `sector_daily.rps_*` |

#### 端点

| 端点 | 说明 |
|------|------|
| `POST /api/settings-tasks/calculate-rps` | steps模式触发计算 |
| `GET /api/factors/rps/{code}` | 查询个股RPS |
| `GET /api/factors/rps?date=&min_rps=` | 查询某日全部RPS(支持阈值过滤) |
| `DELETE /api/factors/rps` | 清除RPS数据 |

---

### 6.3 基础预计算

**上游**: US-013

#### 预计算步骤

| 步骤 | 计算内容 | 写入目标 |
|------|----------|----------|
| 1 | CR5%(个股成交额前5%拥挤度) | `base_data_daily.cr5_pct` |
| 2 | CR10%(板块成交额前10%拥挤度) | `base_data_daily.cr10_pct` |
| 3 | MA50占比(站上MA50的股票比例) | `base_data_daily.ma50_pct` |
| 4 | MA20占比(站上MA20的股票比例) | `base_data_daily.ma20_pct` |
| 5 | NH(250日新高股票数) + NL(250日新低股票数) | `base_data_daily.nh`, `base_data_daily.nl` |
| 6 | 大盘总览(指数涨跌幅+PE_TTM) | `market_daily.overview` |
| 7 | 新高板块聚类 | `market_daily.new_high` |
| 8 | 低位潜力板块 | `market_daily.low_position_sectors` |
| 9 | 异动活跃板块 | `market_daily.active_sectors` |
| 10 | 分组统计 | `market_daily.group_stats` |

#### 端点

| 端点 | 说明 |
|------|------|
| `POST /api/settings-tasks/precompute-base` | steps模式触发预计算 |
| `POST /api/factors/precompute-base` | 后台任务触发预计算 |

---

### 6.4 排除管理

**上游**: US-022

#### I/O 边界矩阵

| 项目 | 说明 |
|------|------|
| **集合** | `exclusions` |
| **排除类型** | `exclude_display`(展示排除), `exclude_sync`(同步排除), `exclude_rps`(RPS排除) |
| **类别** | `sector`(板块), `index`(指数), `stock`(个股) |
| **端点** | `POST /api/factors/disable` (批量更新禁用状态) |
| **端点** | `POST /api/factors/create` (新增板块/指数) |

---

### 6.5 一键全量更新 (Orchestrator)

**上游**: US-014

#### 执行步骤 (OneClickUpdateOrchestrator)

```
Step 1: sync_index   → IndexFactory.sync_kline()
Step 2: sync_stocks  → StockFactory.sync_daily()
Step 3: sync_sectors → SectorFactory.sync_daily()
Step 4: rps_stock    → StockFactory.compute_rps()
Step 5: rps_sector   → SectorFactory.compute_rps()
Step 6: sync_pe      → IndexFactory.sync_pe()
Step 7: precompute   → MarketAggregator.precompute_base_data()
```

#### 边缘用例

| 场景 | 行为 |
|------|------|
| 步骤失败率 > 5% | 停止执行，返回失败摘要 |
| 已有任务在运行 | 取消旧任务后启动新任务 |
| 无新增交易日 | 跳过已完成的步骤，提示"数据已最新" |
| 网络中断 | 当前步骤标记为failed，提供重试入口 |

---

## 7. 全局搜索

**上游**: US-023

#### I/O 边界矩阵

| 项目 | 说明 |
|------|------|
| **端点** | `GET /api/search?q={keyword}` |
| **输出** | `{ stocks: [{code, name}], sectors: [{code, name}] }` |
| **搜索范围** | 股票(代码+名称+拼音首字母)、板块(名称) |
| **限制** | 股票最多50条，板块最多20条 |
| **状态码** | 200(成功), 400(参数缺失) |

---

## 8. 错误处理拓扑

### 全局错误码

| 错误码 | HTTP状态码 | 说明 |
|--------|-----------|------|
| `INVALID_PARAMS` | 400 | 请求参数校验失败 |
| `NOT_FOUND` | 404 | 资源不存在 |
| `TASK_NOT_FOUND` | 404 | 任务ID不存在 |
| `SYNC_TIME_WINDOW` | 403 | 不在同步时间窗口内 |
| `TASK_RUNNING` | 409 | 任务正在运行中 |
| `DATA_SOURCE_FAILURE` | 502 | 所有数据源均连接失败 |
| `AI_SERVICE_UNAVAILABLE` | 503 | DeepSeek API不可用 |
| `INTERNAL_ERROR` | 500 | 未预期的服务端错误 |

### 错误响应格式

```json
{
  "success": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "人类可读的错误描述",
    "details": {}  // 可选，补充信息
  }
}
```

### 重试语义

| 操作类型 | 重试策略 |
|----------|----------|
| 数据源查询 | 每个数据源重试2次，间隔1秒 |
| DeepSeek API | 重试2次，间隔3秒 |
| 后台同步任务 | 失败步骤可单独重试，整体任务需重新启动 |
| 数据库写入 | 无重试(upsert幂等) |

### 断路器阈值

| 组件 | 阈值 | 恢复策略 |
|------|------|----------|
| DeepSeek API | 连续5次失败 → 断开1分钟 | 1分钟后自动半开，1次成功即恢复 |
| PyTdX连接 | 连续3次失败 → 跳过当前批次 | 下一批次自动重试 |
| 乐咕乐股 | 连续2次失败 → 跳过PE同步 | 下次手动触发时重试 |
