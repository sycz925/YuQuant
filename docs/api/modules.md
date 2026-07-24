# 模块接口规范

审计日期：2026-07-24

> 共 **10 个路由模块**，**76+ 端点**。前缀统一为 `/api/`。

---

## 路由总览

| 模块 | 文件 | 前缀 | 端点数 | 说明 |
|------|------|------|--------|------|
| 市场监控 | `market_review.py` | `/api/market-review` | 12 | 基础数据、大盘总览、信号、聚类、AI分析 |
| 市场分析 | `market_analysis.py` | `/api/market_analysis` | 3 | 多维统计、气泡图、活跃股池 |
| 因子管理 | `factors.py` | `/api/factors` | 26 | 最大模块：CR5、指数、板块、RPS、预计算、排除管理 |
| 股票管理 | `stocks.py` | `/api/stocks` | 5 | 股票列表、搜索、详情、日线 |
| 数据同步 | `sync.py` | `/api/sync` | 7 | 基础信息同步、日线同步、冗余字段计算 |
| 日历复盘 | `calendar.py` | `/api/calendar` | 16 | 日摘要、周总结、月总结、快照、重算 |
| 搜索 | `search.py` | `/api/search` | 1 | 统一搜索（股票+板块） |
| 截图 | `screenshot.py` | `/api/screenshot` | 1 | 截图压缩 |
| 一键更新 | `one_click_update.py` / `v2` | `/api/one-click-update` | 4 | 全量同步编排 |
| 设置任务 | `settings_tasks.py` | `/api/settings-tasks` | 6 | 分步设置任务 |

---

## 1. market_review.py - 市场监控

前缀：`/api/market-review`

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/market-review/base-data` | 统一基础数据：CR5/MA/NH-NL，支持日/周/月/季/年聚合，可叠加指数 |
| GET | `/api/market-review/overview` | 大盘指数涨跌幅 + PE_TTM + 自动点评 |
| GET | `/api/market-review/signals` | A股运行状态指标（MA50广度、强势股、历史新高） |
| GET | `/api/market-review/new-high-blocks` | 新高板块聚类 Top10（从 market_daily 缓存读取） |
| GET | `/api/market-review/low-position-sectors` | 低位潜力板块 Top5（只读缓存） |
| GET | `/api/market-review/active-sectors` | 异动活跃板块（只读缓存） |
| GET | `/api/market-review/group-stats` | 分组统计数据 |
| GET | `/api/market-review/ai-analysis` | DeepSeek AI 分析结果 |
| POST | `/api/market-review/ai-analysis/generate` | 启动 AI 分析后台任务 |
| GET | `/api/market-review/ai-analysis/task/{task_id}` | 查询 AI 分析任务状态 |
| GET | `/api/market-review/ai-analysis/input-data` | 获取 AI 分析输入数据 |
| GET | `/api/market-review/sector-detail` | 板块详情：先锋/中军/后排个股 |

---

## 2. market_analysis.py - 市场分析

前缀：`/api/market_analysis`

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/market_analysis` | 多维统计分析（RPS/成交额/股价分组 + 气泡图） |
| GET | `/api/market_analysis/bubble` | 四维动量气泡图（RPS×涨跌幅×成交额） |
| GET | `/api/market_analysis/active_pool` | 活跃股池（高RPS+高涨幅） |

---

## 3. factors.py - 因子管理

前缀：`/api/factors`

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/factors/cr5` | CR5% 因子数据，支持周期聚合 |
| GET | `/api/factors/indices` | 指数列表（分页/搜索/状态筛选） |
| GET | `/api/factors/indices/search` | 搜索指数 |
| POST | `/api/factors/sync-indices` | 同步所有启用指数的日线数据 |
| POST | `/api/factors/precompute-base` | 一键预计算 base_data_daily + market_daily |
| POST | `/api/factors/sync-index-pe` | 同步指数 PE（乐咕乐股） |
| POST | `/api/factors/rps/calculate` | 计算并保存 RPS |
| POST | `/api/factors/tasks/clear` | 清除所有后台任务状态 |
| DELETE | `/api/factors/rps` | 清除 RPS 数据 |
| GET | `/api/factors/rps/{code}` | 获取指定股票 RPS 数据 |
| GET | `/api/factors/rps` | 获取指定交易日全部 RPS |
| POST | `/api/factors/sync-sectors` | 同步板块日线数据 |
| GET | `/api/factors/sectors` | 板块列表（分页/搜索/筛选） |
| GET | `/api/factors/sectors/{code}/daily` | 板块日线数据 |
| POST | `/api/factors/sectors/import-codes` | 导入板块代码映射 |
| POST | `/api/factors/sectors/import-eastmoney` | 导入东方财富行业板块 |
| POST | `/api/factors/disable` | 批量更新禁用状态 |
| POST | `/api/factors/create` | 新增板块或指数 |
| POST | `/api/factors/compare-stocks` | 对比 pytdx 与本地 stock_basics |
| POST | `/api/factors/compare-sectors` | 对比 pytdx 与本地 sector_basics |
| POST | `/api/factors/sectors/import-excel` | 从 Excel 导入板块代码（含 pytdx 校验） |
| GET | `/api/factors/compare-status/{task_id}` | 获取对比任务状态 |
| GET | `/api/factors/config/deepseek-time-limit` | 获取 DeepSeek 时间窗口配置 |
| POST | `/api/factors/config/deepseek-time-limit` | 设置 DeepSeek 时间窗口 |
| POST | `/api/factors/import-stocks` | 导入新增个股 |
| POST | `/api/factors/import-sectors` | 导入新增板块 |
| POST | `/api/factors/clear-sync-tasks` | 清除 sync_tasks 表 |

---

## 4. stocks.py - 股票管理

前缀：`/api/stocks`

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/stocks/search?q=` | 模糊搜索股票（代码/名称/拼音首字母） |
| GET | `/api/stocks` | 股票列表（分页/关键词/状态筛选） |
| POST | `/api/stocks/scan` | 扫描 TDX 新增股票 |
| GET | `/api/stocks/{code}` | 股票详情 |
| GET | `/api/stocks/{code}/daily` | 股票日线数据 |

---

## 5. sync.py - 数据同步

前缀：`/api/sync`

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/sync/basics` | 同步股票基础信息 |
| POST | `/api/sync/daily` | 同步指定股票日线数据 |
| POST | `/api/sync/daily/all` | 同步所有启用股票日线（全量后台） |
| GET | `/api/sync/task/{task_id}` | 获取后台任务状态 |
| DELETE | `/api/sync/task/{task_id}` | 取消运行中的后台任务 |
| POST | `/api/sync/patch_is_final` | 批量修复 is_final 字段 |
| POST | `/api/sync/derived_fields` | 计算冗余字段（MA/VOL_MA/涨跌幅/百分位） |

---

## 6. calendar.py - 日历复盘

前缀：`/api/calendar`

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/calendar/daily-summary` | 日历每日摘要 |
| GET | `/api/calendar/latest-trade-date` | 最新交易日 |
| POST | `/api/calendar/generate-snapshots` | 生成月度日历快照 |
| POST | `/api/calendar/weekly-summary` | 生成周总结（DeepSeek） |
| GET | `/api/calendar/weekly-cached` | 获取已缓存周总结 |
| GET | `/api/calendar/weekly-task/{task_id}` | 查询周总结任务状态 |
| GET | `/api/calendar/weekly-input-data` | 获取周总结输入数据 |
| GET | `/api/calendar/week-status` | 获取月份每周完成状态 |
| GET | `/api/calendar/trading-days` | 获取交易日列表 |
| POST | `/api/calendar/monthly-summary` | 生成月总结（DeepSeek） |
| GET | `/api/calendar/monthly-cached` | 获取已缓存月总结 |
| GET | `/api/calendar/monthly-task/{task_id}` | 查询月总结任务状态 |
| GET | `/api/calendar/monthly-input-data` | 获取月总结输入数据 |
| POST | `/api/calendar/recalculate-month` | 启动月度重算 |
| GET | `/api/calendar/task/{task_id}` | 通用任务状态查询 |
| POST | `/api/calendar/fill-ai-analysis` | AI 分析补全任务 |

---

## 7. search.py - 统一搜索

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/search?q=` | 统一搜索股票 + 板块 |

---

## 8. screenshot.py - 截图

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/screenshot/compress` | 压缩 base64 截图 |

---

## 9. one_click_update.py / v2 - 一键更新

前缀：`/api/one-click-update`

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/one-click-update/start` | 启动一键更新（v1/v2 均存在此路由） |
| GET | `/api/one-click-update/status` | 获取一键更新状态（仅 v1） |
| POST | `/api/one-click-update/recalculate-date` | 按日期重算（v1/v2 均存在） |
| GET | `/api/one-click-update/sync-time-check` | 检查同步时间窗口 |

> v1 = 顺序执行 7 步骤；v2 = Orchestrator 编排执行

## 10. settings_tasks.py - 设置任务

前缀：`/api/settings-tasks`

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/settings-tasks/sync-indices` | 同步指数数据 |
| POST | `/api/settings-tasks/sync-daily` | 同步个股日线 |
| POST | `/api/settings-tasks/calculate-rps` | 计算 RPS |
| POST | `/api/settings-tasks/sync-sectors` | 同步板块数据 |
| POST | `/api/settings-tasks/sync-index-pe` | 同步指数 PE |
| POST | `/api/settings-tasks/precompute-base` | 预计算基础数据 |

---

## 内部模块（无路由）

| 模块 | 说明 |
|------|------|
| `deepseek_analyst.py` | DeepSeek API 桥接服务类 |
| `constants.py` | 硬编码配置常量（指数种子、TDX 指数映射） |
