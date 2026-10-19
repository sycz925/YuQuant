# 持仓风控管理模块 —— 需求分析与落地设计

> 来源需求：根目录 `需求.txt`（ATR 止损止盈 + MTR 波动过滤，v3.0）
> 状态：**待确认**（确认后进入开发）
> 负责代理：ProjectManagerAgent → BackendAgent + FrontendAgent（跨层变更，已输出影响仪表盘）

---

## 一、需求落位：映射到 YuQuant 现有架构

| 需求概念 | 落位位置 | 说明 |
| :--- | :--- | :--- |
| 账户 / 持仓 CRUD | `app/server/api/position.py` + `services/position_service.py` + `repositories/position_repository.py` | 严格遵守 AGENTS.md §7：api 不直连 `get_db()` |
| ATR / MTR / 移动止损算法 | `app/engine/position_risk.py`（新，纯函数） | 与 `ene_alert.py`、`rps_calculator.py` 同级 |
| 日线行情输入 | 复用 `stock_daily`（**已前复权**） | 已有 2016-08-10 ~ 最新，950 万条，无需新建行情 |
| 风控参数配置 | `system_config` 集合 `key='position_risk_params'` | 复用 `SystemConfigRepository`，不新建表 |
| K 线标注（买/卖/止损/止盈） | 扩展 `app/client/src/components/TradingViewChart.jsx` | 新增 `markers` / `priceLines` / `overlaySeries` 三个可选 prop，默认空 → 旧页面零影响 |
| 导航入口 | `app/client/src/App.jsx`，`关注` 之后插入 `持仓` | `WalletOutlined`，路由 `/positions` |

**结论：不需要新建行情/因子表，不需要改动一键更新的 7 步结构。**

---

## 二、数据模型（新增 2 个集合）

### 2.1 `accounts`（账户）

```jsonc
{
  "account_id": "a3f2c1d8",          // uuid4 hex[:8]，唯一索引
  "account_name": "主账户",
  "initial_capital": 200000.0,
  "current_cash": 156000.0,          // 建仓扣减 / 平仓加回
  "risk_ratio_per_trade": 0.005,
  "created_at": ISODate,
  "update_time": ISODate
}
```

`current_equity` **不落库**，由 `current_cash + Σ(最新收盘 × 股数)` 实时算（避免同步时机导致权益失真）。

索引：`{account_id: 1}` unique。

### 2.2 `positions`（持仓，一笔买入 = 一条）

```jsonc
{
  "position_id": "p7b21e40",
  "account_id": "a3f2c1d8",
  "stock_code": "300308",
  "stock_name": "中际旭创",           // 冗余，列表免联查

  "buy_date": "20260715",
  "buy_price": 128.50,                // 用户输入的真实成交价（不复权口径）
  "buy_shares": 700,

  "status": "OPEN",                   // OPEN | CLOSED
  "sell_date": null,
  "sell_price": null,
  "realized_pnl": null,
  "holding_days": null,

  // ---- 建仓时冻结 ----
  "atr_entry": 6.82,
  "initial_stop_loss_price": 114.86,
  "take_profit_reference_price": 148.96,
  "suggested_max_shares": 1100,
  "risk_check_status": "PASS",        // PASS | WARN_OVER_RISK | REJECT
  "anchor_close": 127.8,              // 见 §3.5 除权锚点

  // ---- 最新快照（每次刷新/监控写回，供列表排序与预警）----
  "snapshot": {
    "trade_date": "20261016",
    "current_price": 141.20,
    "atr_current": 7.15,
    "highest_since_entry": 143.00,
    "current_stop_loss_price": 125.45,
    "mtr_current": 0.82,
    "mtr_mean": 0.51,
    "mtr_std": 0.19,
    "mtr_filter_status": "VALID_EXPANSION",
    "action_suggestion": "持仓",
    "unrealized_pnl": 8890.0,
    "risk_amount": 455.0,
    "risk_ratio": 0.0021,
    "current_rr": 3.10,
    "update_time": ISODate
  },
  "last_updated": ISODate
}
```

索引：`{position_id: 1}` unique、`{account_id: 1, status: 1}`、`{stock_code: 1}`。

### 2.3 不新增 `position_daily` 快照表（见决策点 Q1）

止损轨迹按需回算（一次 ≤ 400 根日线，纯内存计算 < 10ms），避免一份可能失真的冗余数据。

---

## 三、核心算法：`app/engine/position_risk.py`（纯函数）

### 3.1 ATR

```python
TR[i]  = max(high[i]-low[i], |high[i]-prev_close|, |low[i]-prev_close|)
ATR(N) = SMA(TR, N)        # 默认 N=14
```

### 3.2 MTR（Chris Lindgren Modified True Range）

```python
MTR[i]     = max(|high[i]-prev_close[i]|, |low[i]-prev_close[i]|)
MTR_mean   = SMA(MTR, 20)
MTR_std    = STDEV(MTR, 20)
VALID_EXPANSION  ⇔  MTR[i] > MTR_mean + 2.0 × MTR_std
```

### 3.3 逐日回算（`simulate(bars, position, params) -> List[DayState]`）

对 `buy_date` 之后的每根日线依次执行：

```
1. stop_in_effect = 上一日收盘后确定的 current_stop_loss_price   ← 时间顺序正确，见 Q4
2. 触发检查（用 stop_in_effect，MTR 不过滤）：
     open  <= stop → 跳空止损      (gap_stop)
     low   <= stop → 盘中止损      (intraday_stop)
     close <= stop → 收盘止损      (close_stop)
     close >= tp   → 利润保护参考  (take_profit_ref)
3. atr_current = ATR(14) 至当日
4. highest_since_entry = max(prev_high, close 或 high)      # 由 trailing_high_source 决定
5. mtr_filter_status = 判定
6. trailing_stop = highest_since_entry - k_trail × atr_current
   current_stop  = max(prev_stop, trailing_stop)            # 只上移
   若 INVALID_NOISE → current_stop = prev_stop              # 过滤上移
   兜底 current_stop = max(current_stop, initial_stop)
```

产出每一天的 `DayState`，用于：
- K 线止损阶梯线（`overlaySeries`）
- 每日明细表（抽屉里）
- 最新一天写回 `positions.snapshot`

### 3.4 建仓风控（`preview_entry()`）

```
initial_stop = buy_price - k_initial × atr_entry
risk_per_share = buy_price - initial_stop
max_loss = current_equity × risk_ratio_per_trade
suggested_max_shares = floor(max_loss / risk_per_share / 100) × 100   ← A 股整手，见 Q7
PASS            : buy_shares <= suggested
WARN_OVER_RISK  : buy_shares >  suggested（提示但允许，需二次确认）
REJECT          : risk_per_share <= 0 或 suggested <= 0
take_profit     = buy_price + k_take_profit × atr_entry
```

### 3.5 除权处理（关键风险点，见 Q5）

`stock_daily` 是**前复权**序列，除权后历史价格整体下移；而 `buy_price` 是用户输入的真实成交价。
若直接用 `前复权 close(buy_date)` 与 `buy_price` 混算，止损线与 K 线会错位。

**推荐方案（锚点比例法，用户无感）：**
- 建仓时冻结 `anchor_close = 当时读到的 前复权 close(buy_date)`
- 每次回算时读当前 `c_now = 前复权 close(buy_date)`
- 换算系数 `r = c_now / anchor_close`
- 全程用 `buy_price_adj = buy_price × r` 参与计算，K 线/止损/盈亏统一到「当前前复权口径」，图上线与蜡烛完全对齐
- UI 同时展示「实际成本 128.50」与「复权成本 127.98」，透明可查

### 3.6 账户级

```
current_equity      = current_cash + Σ(最新收盘 × buy_shares)
total_unrealized    = Σ((最新收盘 - buy_price_adj) × buy_shares)
total_realized      = Σ(CLOSED.realized_pnl)
total_risk_amount   = Σ((buy_price_adj - current_stop) × buy_shares)
total_risk_ratio    = total_risk_amount / current_equity
```

---

## 四、后端 API 契约（`/api/positions`）

| 方法 | 路径 | 用途 |
| :--- | :--- | :--- |
| GET | `/api/positions/settings` | 读取风控参数（含默认值兜底） |
| PUT | `/api/positions/settings` | 保存风控参数 |
| POST | `/api/positions/accounts` | 创建账户 |
| GET | `/api/positions/accounts` | 账户列表（含实时权益、盈亏） |
| PUT | `/api/positions/accounts/{id}` | 改名 / 改风险比例 / 出入金 |
| DELETE | `/api/positions/accounts/{id}` | 删除账户（有持仓则拒绝） |
| GET | `/api/positions/accounts/{id}/dashboard` | 账户级风控看板 |
| POST | `/api/positions/preview` | **建仓预览**（不落库，实时返回 ATR/止损/建议股数/风险校验） |
| POST | `/api/positions` | 建仓（`force=true` 用于 WARN 二次确认） |
| GET | `/api/positions` | 列表（`account_id` / `status` / `keyword` / 排序） |
| GET | `/api/positions/{id}` | 详情 |
| GET | `/api/positions/{id}/trajectory` | 每日轨迹（K 线标注 + 明细表数据源） |
| POST | `/api/positions/{id}/close` | 平仓 |
| POST | `/api/positions/{id}/refresh` | 重算单笔快照 |
| POST | `/api/positions/refresh` | 重算全账户 |
| DELETE | `/api/positions/{id}` | 删除已平仓记录 |

**顺带修复的既存 Bug**：`app/client/src/api.js:48` 传的是 `startDate/endDate`，而后端 `/stocks/{code}/daily` 收的是 `start_date/end_date`（FastAPI 静默忽略）——目前所有调用都退化成「默认 365 天窗口」。持仓 K 线要按买入日回溯，必须修正为 `start_date/end_date`。

---

## 五、前端设计

### 5.1 导航

`板块 · ETF · 关注 · **持仓** · 解禁 · 产业地图`（`WalletOutlined`，路由 `/positions`）

### 5.2 页面 `/positions`（`app/client/src/pages/PositionPage.jsx`）

```
┌─ 账户切换 Select ────────────── [参数设置] [+ 新建账户] [+ 建仓] ─┐
├─ 账户看板 8 张卡 ──────────────────────────────────────────────┤
│  总权益 | 可用现金 | 浮动盈亏 | 已实现盈亏                      │
│  活跃持仓 | 总风险金额 | 总风险占比 | 账户收益率                │
├─ Tabs: 活跃持仓 (N) | 历史持仓 (M) ────────────────────────────┤
│  活跃表: 代码/名称 买入日 买入价 股数 现价 浮盈% ATR             │
│          初始止损 当前止损 止盈参考 风险额 风险比 RR             │
│          MTR状态 动作建议 操作(详情/平仓)                       │
│  历史表: 代码/名称 买入日 卖出日 买价 卖价 股数 已实现盈亏       │
│          收益率 持仓天数 操作(详情/删除)                        │
└────────────────────────────────────────────────────────────────┘
```

浮动盈亏红涨绿跌、当前止损低于现价显示绿色、`WARN_OVER_RISK`/止损触发用红色 Tag 高亮。

### 5.3 持仓详情抽屉（`PositionDetailDrawer.jsx`）— **核心需求：K 线看买点/止损/卖点**

- 顶部：持仓概要（成本、股数、现价、浮盈、ATR、RR、动作建议）
- 中部：`<TradingViewChart>` 复用现有 K 线（含 MAXX/成交量/MACD/RPS），额外叠加
  1. **买入点** `arrowUp` 红色箭标，文字 `买入 128.50`
  2. **实际卖出点**（CLOSED）`arrowDown` 绿色箭标，文字 `卖出 141.20 +9.9%`
  3. **止损触发点**（历史曾触发但未平仓）`circle` 黄色圆标
  4. **止损阶梯线**：虚线折线序列，逐日上移（一眼看出移动止损轨迹）
  5. **止盈参考线**：水平价格线（灰色虚线，标注 `止盈参考 148.96`）
  6. **当前止损线**：水平价格线（红虚线）
- 底部：Tab「每日轨迹」表格（日期/收盘/ATR/最高价/MTR/过滤/止损价/动作）

通过 `TradingViewChart` 新增 3 个可选 prop 实现：
```jsx
<TradingViewChart
  data={bars} stockCode="300308"
  markers={[...]}          // candleSeries.setMarkers()
  priceLines={[...]}       // candleSeries.createPriceLine()
  overlaySeries={[{ id:'stop', color:'#ef5350', lineStyle:2, data:[...] }]}
/>
```
默认全部空数组 → `StockAnalysis` / `SectorDetail` / `ETFPage` 等既有页面行为完全不变。

### 5.4 建仓弹窗（`PositionDialog.jsx`）

输入 `股票代码` / `买入日期` / `买入价` / `股数` → 防抖调 `POST /preview` 实时回显：
```
ATR(14)        6.82
初始止损       114.86   (-10.6%)
止盈参考       148.96   (+15.9%)
每股风险       13.64
建议最大股数   1,100 股
风险校验       ⚠ 超标：当前 1,500 股，建议减至 1,100 股    [仍按原股数建仓]
```
`REJECT` / `WARN` 时按钮二次确认（`force=true`）。

### 5.5 平仓弹窗（`ClosePositionDialog.jsx`）

输入 `卖出日期` / `卖出价` → 实时回显 `已实现盈亏`、`收益率`、`持仓天数`，确认后落库并加回现金。

---

## 六、与现有模块的集成点

| 集成点 | 做法 | 风险 |
| :--- | :--- | :--- |
| 一键更新 | **不改 7 步结构**；持仓快照在页面加载/手动刷新时回算 | 无 |
| `stockApi.getDailyData` | 修正 `startDate` → `start_date` 参数名 | 低（修正后 `StockAnalysis` 的日期范围才真正生效） |
| `TradingViewChart` | 新增 3 个可选 prop，默认空 | 低（向后兼容） |
| `watchlist` | 独立（见 Q8）：建仓时不自动加入关注 | 无 |
| 顶部预警红点 | 见 Q9：可选接入「止损触发」提醒 | 低 |

---

## 七、影响仪表盘（跨层变更上报，AGENTS.md §3.2）

| 层 | 代理 | 文件 | 变更类型 |
| :--- | :--- | :--- | :--- |
| 数据层 | BackendAgent | `app/server/repositories/position_repository.py` | 新增 |
| 算法层 | BackendAgent | `app/engine/position_risk.py` | 新增 |
| 服务层 | BackendAgent | `app/server/services/position_service.py` | 新增 |
| 接口层 | BackendAgent | `app/server/api/position.py`、`main.py`、`models.py` | 新增 + 注册 |
| 展示层 | FrontendAgent | `pages/PositionPage.jsx`、`components/Position*`、`App.jsx`、`api.js` | 新增 + 改动 |
| 共享组件 | FrontendAgent | `components/TradingViewChart.jsx` | 增强（向后兼容） |
| 数据库 | BackendAgent | 新增集合 `accounts`、`positions` + 索引 | 新增 |

**副作用评估**
- 新增集合，不影响既有 11 个集合
- `TradingViewChart` 改动需回归 `/analysis`、`/sector/:code`、`/etf` 三个既有使用点
- 一键更新链路零改动
- 无破坏性 Schema 变更

---

## 八、已确认决策（2026-10-16）

| # | 决策点 | 结论 |
| :--- | :--- | :--- |
| D1 | 每日监控落库 | **页面打开时实时回算 + 最新快照写回 `positions.snapshot`**；不新建轨迹表，不改一键更新 7 步结构；另提供「刷新监控」按钮 |
| D2 | K 线标注范围 | **全部 6 项**：买入点、实际卖出点、止损触发点、止损阶梯线、止盈参考线、当前止损线 |
| D3 | `ATR_entry` 取数口径 | **只用买入日之前**的 14 个交易日 TR（无未来函数） |
| D4 | 除权处理 | **锚点比例法**（建仓冻结 `anchor_close`，回算按 `r = c_now/anchor_close` 折算），UI 同时显示实际成本与复权成本 |
| D5 | 交易规则 | **校验整手 100 股 + T+1**（T+1 仅个股，ETF 为 T+0）；**不计手续费**，`realized_pnl=(卖价-买价)×股数` 严格按需求公式 |
| D6 | 预警接入 | **要**：止损触发/跳空止损/达到止盈参考 → 顶部红点（复用 App.jsx 轮询机制）+ 列表高亮 |
| D7 | 关注联动 | **不自动加入**，关注与持仓功能独立 |
| D8 | 标的范围 | **个股 + ETF**（数据源分别 `stock_daily` / `etf_daily`） |

### 8.1 个股 vs ETF 差异（D8 带来的分支）

| 项 | 个股 | ETF |
| :--- | :--- | :--- |
| 日线集合 | `stock_daily` | `etf_daily` |
| 名称来源 | `stock_basics.stock_name` | `etf_basics.name` |
| T+1 | 强制（卖出日 > 买入日） | 不限制（T+0） |
| 整手 | 100 股 | 100 份 |
| 价格小数 | 2 位 | 3 位 |
| 前复权 | 已前复权（`pytdx_source` 内置 xdxr） | 已前复权（`akshare qfq`） |
| 数据起点 | 2016-08-10 | 2020-07-30（更早买入会因缺 bar 报错提示） |

`positions` 增加字段 `asset_type: "stock" | "etf"`。

---

## 九、里程碑拆解

- **M1 数据层 + 算法层**：`position_repository.py`、`position_risk.py`（ATR/MTR/回算/preview/账户汇总）+ 单测
- **M2 服务层 + API**：`position_service.py`、`api/position.py`、`models.py`、`main.py` 注册
- **M3 前端**：`PositionPage.jsx`、建仓/平仓弹窗、详情抽屉、`TradingViewChart` 增强、导航 + `api.js`
- **M4 联调 + 回归**：既有 `/analysis`、`/sector/:code`、`/etf` 三处图表回归；预警红点联调

---

## 十、实施结果（2026-10-17 完成）

### 10.1 交付清单

| 层 | 文件 | 说明 |
| :--- | :--- | :--- |
| 算法 | `app/engine/position_risk.py` | ATR / MTR / 逐日回算 / 建仓预览 / 账户汇总，纯函数无 DB 依赖 |
| 数据 | `app/server/repositories/position_repository.py` | `accounts` + `positions` + 风控参数 + 行情读取，`ensure_indexes()` 幂等建索引 |
| 服务 | `app/server/services/position_service.py` | 锚点折算、建仓/平仓/快照/预警 |
| 接口 | `app/server/api/position.py` | 22 个路由，`PositionError → HTTP 400/404/409` |
| 注册 | `app/server/main.py` | 挂载 `/api/positions`，启动时建索引 |
| 组件 | `app/client/src/components/position/*` | 建仓、平仓、详情抽屉、风控参数、账户 5 个弹窗 + `utils.js` |
| 页面 | `app/client/src/pages/PositionPage.jsx` | 账户看板 + 活跃/历史双表 |
| 图表 | `app/client/src/components/TradingViewChart.jsx` | 新增 `markers` / `priceLines` / `overlaySeries` 三个可选 prop（默认空→旧页面零影响） |
| 导航 | `app/client/src/App.jsx` | 「关注」后插入「持仓」，含预警红点数字 + 60s 轮询 |
| 修复 | `app/client/src/api.js` | `stockApi.getDailyData` 的 `startDate/endDate` → `start_date/end_date` |

### 10.2 新增集合

- `accounts`：`account_id`(unique) / `account_name` / `initial_capital` / `current_cash` / `risk_ratio_per_trade` / `created_at`
- `positions`：`position_id`(unique) / `account_id+status` / `stock_code` 索引；含建仓冻结参数、`anchor_close`、`snapshot` 最新风控快照

### 10.3 关键实现细节

1. **时间顺序正确的止损检查**：当日 open/low/close 对照「前一交易日收盘后确定的止损价」，
   当日收盘后再按 `highest − k_trail×ATR` 上移，避免未来函数。
2. **个股 T+1**：建仓当日不做触发判定、禁止当日平仓；ETF 为 T+0 不受限。
3. **MTR 过滤只作用于移动止损上移**，硬性止损触发不受影响（动作建议优先级：
   跳空 > 盘中 > 收盘 > 止盈参考 > MTR过滤 > 持仓）。
4. **除权锚点**：`r = 当前前复权 close(buy_date) / anchor_close`，买入价/初始止损/止盈参考同比例折算，
   `adjust_ratio ≠ 1` 时 UI 显示「复权成本」提示。
5. **预警缓存**：TTL 120s，但**空结果不缓存**，且建仓/平仓/刷新时主动失效缓存。

### 10.4 验证记录

- 引擎单测：止损单调性（0 次下移）、不低于初始止损、建仓日不触发、MTR 开/关对比（8 次 vs 53 次上移）
- 服务层全链路：建账户 → 预览 → 建仓(409 拦截) → force 建仓 → 列表 → 详情 → 轨迹 → 平仓(T+1 拦截) → 看板 → 预警
- API 层 TestClient：22 个路由 + 400/404/409 错误码
- 真机 HTTP：`300308` 强趋势案例止损从 478.19 上移至 1274.27（8 次上移，K 线阶梯线 160 点）
- 前端：`vite build` 通过（5477 modules）

---

## 十一、追加需求（2026-10-17 第二轮）

### 11.1 刷新监控时按需补齐日线（D9）

**需求**：刷新监控时判断持仓个股在 `stock_daily` / `etf_daily` 有没有日线基础数据，
有则不更新，没有则补齐该股日线；最新交易日的数据仍由一键更新统一覆盖。

**实现**：
- `PositionRepository.get_bar_ranges(codes, asset_type)`：一次 `$group` 聚合拿到
  `{code: {first, last, count}}`，避免逐只查询。
- `PositionService.ensure_position_data(positions)`：判定规则

  | 情况 | 动作 |
  | :--- | :--- |
  | 完全没有日线 | 全量拉取（回溯 10 年） |
  | 有数据但不足 40 根（ATR14+MTR20 需要） | 全量拉取 |
  | 有数据但最后一根 < 买入日 | 增量拉取到「市场已有数据的最后一天」 |
  | 其余 | 跳过 |

- `DataManager.sync_codes_daily(codes, asset_type, full)`：**不做全市场边界回溯**，
  只针对传入代码补数据。个股走 `_sync_single_stock` / `_full_reload_stock` 多源瀑布；
  ETF 走新增的 `_sync_code_history`（原 `sync_etf_daily` 只按单日补，拿不到足够历史）。
- 挂载点：`POST /positions/refresh`（全部）、`POST /positions/{id}/refresh`（单笔），
  返回体新增 `data: {checked, synced, failed, skipped, full, incremental}`。

**边界约定（与用户确认）**：补齐只负责"把 K 线拿回来让 ATR 能算"，
**RPS 等市场级派生指标一律留给一键更新**，持仓模块不反向依赖 RPS 体系。

**测试记录**：删除 `600000` 的 2128 行日线模拟"无数据"→ 补齐成功拉回 2427 行
（2016-10-19~2026-10-16），`|chg_pct|>21%` 异常日 0 天。测试导致的 RPS 派生字段丢失
已用定向脚本（`tmp/fix_rps_600000_tmp.py`）回补 2417 天。

### 11.2 持仓详情面板 K 线重做（D10）

**需求**：详情弹窗只显示 K 线，不要成交量 / MACD / RPS 等子图；K 线独立重做，不复用旧组件。

**实现**：新增 `app/client/src/components/position/PositionKlineChart.jsx`（完全独立实现，与
`TradingViewChart` 无任何耦合）：

| 项 | 旧图（TradingViewChart） | 新图（PositionKlineChart） |
| :--- | :--- | :--- |
| 面板 | K线40% + 成交量15% + MACD20% + RPS20% | **仅 K 线**，高度 620（移动端 440） |
| 价格轴 | 隐藏 | **显示**，按 2/3 位小数格式化 |
| 时间轴 | 隐藏 | **显示**，MM/DD，滚轮缩放 + 拖动平移 |
| 顶部信息 | 4 条子图标签 | 单条固定图例（日期/OHLC/涨跌幅/当日止损/ATR/动作），随十字光标联动 |
| 止损阶梯 | — | `lineType=WithSteps` 真阶梯，琥珀色实线 |
| 初始视野 | 全量 | 买入日前 60 根 → 最新 |

保留的标注：买入点 ▲、实际卖出点 ▼、止损触发点 ●、止损阶梯线、当前止损线、
止盈参考线、成本线。

**副作用**：详情抽屉不再需要额外拉 `stock_daily`/`etf_daily` 全量日线，
改为直接用 `/trajectory` 返回的 `bars`（后端已裁剪为「买入日前 120 根 + 持仓期间」），
一次请求即可，加载更快。

### 11.3 验证

- `DataManager.sync_codes_daily`：全量/增量/跳过/失败四条分支 + ETF 分支全部实测通过
- `ensure_position_data`：无数据 → `full` 分支实际拉回 2427 行并写库
- `POST /positions/refresh` 返回 `data` 报告；`POST /positions/{id}/refresh` 返回 `data_report`
- `PositionKlineChart`：`vite build` 通过（5478 modules），trajectory 载荷含
  `bars 282 根 / daily 162 天 / markers 2 个 / price_lines 3 条 / stop_series 162 点`

---

## 十二、Bug 修复：止盈参考被误判为「止损触发」（2026-10-17）

### 现象
`300308` 演示持仓买入日 `2026-02-10`，但 K 线上在 `2026-04-08` 出现了黄色的「止损触发点」。
实际 `2026-04-08` 收盘 687.33 **高于**止盈参考 670.33，属于 `take_profit_ref`（达到利润保护参考位），
是**正面信号**，不是止损。

### 根因
`_enrich` 与 `_build_chart_payload` 都用了同一句：
```python
next((s for s in states if s.get('events')), None)   # ← 第一个「任何事件」
```
`events` 里同时混有 `gap_stop / intraday_stop / close_stop`（风险）与
`take_profit_ref`（正面），取第一个即等于把止盈参考命中当成止损触发。

### 修复
1. 新增常量 `STOP_EVENTS = {'gap_stop','intraday_stop','close_stop'}`，与止盈事件严格分离。
2. `_enrich` 拆成两组字段：
   - `stop_trigger_date` / `stop_trigger_action` / `stop_trigger_price` / `stop_trigger_count`
   - `take_profit_hit_date` / `take_profit_hit_price` / `take_profit_hit_count`
   - `latest_events`（替换语义含混的 `stop_events`）
3. `_build_chart_payload` 画两个独立标注：止损触发点（`aboveBar` 琥珀 `#f59e0b`）、
   止盈参考触发点（`belowBar` 绿 `#22c55e`）；同一日两者并存时止损优先（数组顺序保证）。
4. 已平仓持仓也标注持仓期内的事件（不再只在 `OPEN` 时标注）。
5. 前端详情面板：「止损触发」显示动作 Tag + 日��� + 累计天数；新增「止盈参考触发」列。

### 修复后 300308 的正确结果

| 项 | 值 |
| :--- | :--- |
| 买入 | 2026-02-10 @ 555.05 × 300 |
| **止损触发** | **2026-06-11 盘中止损**，当日止损价 1105.98，累计 67 天 |
| **止盈参考触发** | **2026-04-08**，止盈参考 670.33，累计 126 天 |

「累计 67 天」是因为止损触发后系统不会自动平仓（需求 §7 明确不平仓），
价格在止损位附近反复穿越导致多次触发——这正是"该离场却没离场"的量化呈现。

---

## 十三、三条线不变量审计（2026-10-17）

针对「止损阶梯线 / 当前止损线 / 止盈参考线」做 15 项不变量审计，
脚本 `tmp/audit_stop_lines_tmp.py`（指定持仓）+ `tmp/audit_random_tmp.py`（随机抽样）。

### 15 项不变量

| # | 不变量 | 结论 |
| :--- | :--- | :--- |
| 1 | 止损阶梯单调不减（只上移不下移） | ✅ |
| 2 | 阶梯首点 == 初始止损 | ✅ |
| 3 | 阶梯末点 == 当前止损横线 | ✅ |
| 4 | 任何一天止损 ≥ 初始止损 | ✅ |
| 5 | 上移只发生在 MTR 判定 `VALID_EXPANSION` 的日子 | ✅ |
| 6 | `stop_move_filtered` 标记与"本可上移/实际上移"自洽 | ✅ |
| 7 | `events` 与当日 O/H/L/C 真实穿越一致 | ✅ |
| 8 | 当日 `stop_loss_in_effect` == 前一交易日收盘后确定的止损 | ✅ |
| 9 | 止盈参考全期恒定且等于冻结值×复权比例 | ✅ |
| 10 | 与独立重写的止损轨迹逐日对拍一致 | ✅ |
| 11-15 | 建仓日不触发 / 事件语义分离 / 复权折算一致 / 阶梯与K线同一口径 / ETF T+0 分支 | ✅ |

**规模**：3 只指定持仓 + 120 组随机抽样（90 个股 + 30 ETF，随机买入日），
有效样本 **116/116 全部通过**，4 组因所选日期非交易日（停牌/未上市）合理跳过。

### 审计过程中发现的真实小缺陷（已修）

**止损/止盈价未对齐 tick，导致"展示值"与"判定值"不是同一个数。**

原代码：
```python
stop_in_effect = round(stop, price_dec)   # 对外展示/审计用的值（已取整）
...
if bar['open'] <= stop:                   # 实际判定用的值（未取整）
```
`stock_daily` 是**前复权**序列，价格有 3 位小数（如 `11.341`），而个股止损按 2 位取整。
于是"表格里看到的止损价"与"触发判断用的阈值"最多可能差半个 tick，在开盘价恰好落在
止损价上时会出现"看着已跌破、事件里却没有跳空止损"的矛盾。

**修复**：`simulate()` 中把 `initial_stop / take_profit / highest / trailing / stop`
全部对齐到 tick（`price_dec`），使**对外展示值 == 实际判定阈值**。
代价是止损被量化到 2 位小数（最多偏松半个 tick ≈ 个股 0.005 元），换来"所见即所触发"。

### 审计口径的坑（记录备查）

初版审计把 `events` 与 **展示用取整后的 OHLC/ATR** 做比较，误报了一批问题。
正确做法必须用**原始价格与原始 ATR**：
- 前复权股价有 3 位小数，`state['open']` 是取整到 2 位的展示值；
- `state['atr']` 是取整后的展示值，用它复算 `highest - k_trail × ATR` 会偏差一个 tick。

---

## 十四、K 线 ATR 通道 + 风控参数默认值可见（2026-10-17）

### 14.1 ATR 通道（D11）

**需求修正**：ATR 应表现为**围绕 K 线的上下通道**，而非独立的曲线副图。

**实现**（`PositionKlineChart`）：
- 开关命名为「ATR 通道」，开启后在主图上下各画一条虚线：
  - `上轨 = close + k_initial × ATR`
  - `下轨 = close − k_initial × ATR`
- 倍数取风控参数 `k_initial`（默认 2.0），即「初始止损距离」的带宽，
  用途是判断**止损是否被放进了正常噪声带里**（止损应落在通道之外）。
- 通道线 `lineStyle=2`（虚线）、`lineWidth=1`、`#38bdf8`，且**先于 K 线创建**
  以保证绘制在蜡烛下方，不遮挡主图。
- 顶部图例随光标联动显示：`ATR(14) 45.16　上轨 757.60　下轨 582.40`。

**数据**：`GET /positions/{id}/trajectory` 新增顶层 `atr_series`（与 `bars` **同日期、
同长度**，全精度 4 位小数），原 `chart.atr_series` 移除。
用全精度是因为 `daily[].atr` 是展示用取整值，画通道会抖成台阶。
`params` 也一并回传（前端取 `atr_period` 与 `k_initial`）。

**验证**：`300308` bars 282 / atr_series 282 日期完全对齐；
K 线完全落在 ±2×ATR 通道内的比例：`688041` 100%、`510300` 100%、`300308` 99%。

### 14.2 风控参数默认值可见（D12）

**需求**：打开风控参数对话框要能看到默认值。

**实现**（`RiskParamsDialog`）：
- 每个数值输入框内用 `InputNumber.suffix` 显示 `默认 X`（框内、附在右侧），
  并以默认值作为 `placeholder`；参数名不再重复标注。
- `Select` / `Switch` 无输入框，默认值写在 `extra` 提示行首。
- 与默认值不同的参数，标签后出现橙色「已改」徽标；标题栏显示
  「当前全部为默认值」/「已修改 N 项」。
- 底部新增「恢复默认值」按钮，一键回填出厂默认（需保存后生效）。
- 补上原先漏掉的可配置项：`新建账户默认单笔风险比例`（`risk_ratio_per_trade`），
  以百分比输入，落库时换算回比例。

**验证**：`GET /settings` 返回 `params / defaults / bounds / choices`；
`PUT /settings` 修改 `k_trail=3.0` + `risk_ratio_per_trade=0.01` 后回读生效，
再恢复默认回 2.5 / 0.005。三条线 15 项不变量在 4 笔持仓（含用户新增的 `688041`）上全部通过。

---

## 十五、分批卖出 / 部分平仓（2026-10-17）

### 15.1 需求与决策

原实现只支持一次全平，但需求文档 §4 的原文就写了「已达利润保护参考位，**可考虑部分止盈**」——
数据模型与文档自相矛盾。本次补齐分批离场能力。

| 决策点 | 结论 |
| :--- | :--- |
| 保本止损 | **不做**，止损完全交给 ATR。部分卖出只减股数，价格层面风控不变 |
| 卖出理由 | `take_profit`（主动减仓）/ `stop_loss`（被动止损）/ `manual`（手动） |
| 历史表展示 | 一行汇总（加权均价 + 「分 N 笔」），明细进详情抽屉 |
| 加仓 | **不支持**，加仓另建一笔持仓（保持「一笔建仓 = 一个风控单位」） |

### 15.2 数据模型

`positions` 新增/变更：

```jsonc
{
  "buy_shares": 200,          // 原始建仓股数，不可变（审计口径）
  "sells": [
    { "sell_id":"s1", "sell_date":"20261015", "sell_price":241.5, "shares":100,
      "realized_pnl":-1950.0, "return_ratio":-0.0747,
      "reason":"take_profit", "note":"...", "created_at": ISODate }
  ],
  "sold_shares": 100,
  "remaining_shares": 100,     // 风控计算与市值都以它为准
  "realized_pnl": -1950.0,     // 累计已实现（Σ每笔）
  "realized_cost": 26100.0,    // 已卖出部分的成本
  "return_ratio": -0.0747,     // 已实现收益率
  "avg_sell_price": 241.5,
  "last_sell_date": "20261015",
  "last_sell_price": 241.5,
  "status": "OPEN",            // 由 remaining_shares 派生：0 → CLOSED
  "sell_date": "20261015",     // 兼容旧读取（= 最后一笔）
  "sell_price": 241.5
}
```

**向后兼容**：旧的全平记录没有 `sells` 字段，`_normalize_sells()` 会用
`buy_shares + sell_date + sell_price + realized_pnl` 合成一条 `legacy` 流水，
`_remaining_shares()` 相应返回 0。无需数据迁移即可读；另写了幂等回填脚本
`tmp/backfill_sells_tmp.py` 把 4 条历史记录补齐物化字段。

### 15.3 关键实现

1. **引擎 `simulate(..., sells=None)`**：逐日推进 `held`（当日实际持有股数）与
   `realized_cum`（累计已实现），每日状态新增 `held_shares` / `realized_pnl_cum`。
   `unrealized_pnl`、`position_risk_amount` 全部改用 `held`。
2. **`aggregate_account()`** 优先取 `remaining_shares`，回退 `buy_shares`。
3. **`_account_equity()` 收口到看板口径**（直接复用 `_decorate_account`）。
   顺带修掉两个旧缺陷：它用的是 `buy_shares`（未扣减已卖股数），且多乘了一个
   复权比例 `ratio` —— 分红或分批卖出后都会偏离看板权益。
4. **`sell_position(position_id, sell_date, sell_price, shares, reason, note)`**：
   - `shares=None` → 把剩余全部卖出
   - 卖出**不要求 100 整数倍**（与买入不同）；剩余不足 100 股提示零股
   - 每笔都校验 T+1、交易日、`sell_date >= 上一笔卖出日`
   - `remaining == 0` 才置 `CLOSED`，否则保持 `OPEN` 继续监控
   - `close_position()` 保留为全平别名，旧接口不受影响
5. **API**：新增 `POST /positions/{id}/sell`（`shares` 可选、`reason` 可选）；
   `POST /positions/{id}/close` 语义不变。
6. **K 线**：每笔卖出画一个 ▼，同日多笔合并；
   理由为 `stop_loss` 用琥珀色、`take_profit` 用绿色、`manual` 用青色。
7. **前端**：`ClosePositionDialog` → `SellPositionDialog`，含股数输入、1/3·1/2·2/3·全部
   快捷按钮、卖出理由、实时预览（本笔盈亏 / 卖出后剩余股数 / 剩余浮盈 / 累计已实现）；
   活跃表「股数」列改为「持仓（剩余 + 已卖）」并新增「已实现」列；
   历史表卖出价显示加权均价 + 「分 N 笔」；详情抽屉新增「卖出记录」Tab。

### 15.4 验证记录

- **端到端（服务层）**：建仓 10000 股 → 卖 4000（主动减仓）→ 卖 6000（被动止损），
  现金 `500000 → 380800 → 427200 → 495600` 与期望完全一致；
  累计已实现 `-1280 + -3120 = -4400`；账户权益守恒 `495600`。
- **边界**：已全平再卖 / 卖出超剩余 / T+1 当日卖 / 非交易日 / 卖出 0 股 /
  卖出日期倒序 —— 全部正确拦截。
- **零股规则**：建仓 300 股 → 卖 250 剩 50，返回零股提示；再卖 50 转 CLOSED。
- **交易日轨迹**：`held_shares` 在卖出日正确递减（300 → 300 → 50 → 50 → 0），
  `realized_pnl_cum` 同步累积。
- **HTTP 层**：`POST /sell` 部分卖出返回 `status=OPEN`、`remaining_shares` 正确；
  卖完转 `CLOSED`；已全平再卖返回 409。
- **回归**：15 项不变量在 4 笔持仓上全部通过；随机抽样 120 组全部通过。
- **真实持仓未受影响**：`688041` 详情各项数值与改造前完全一致
  （剩余 200 股、止损 242.16、浮亏 -13692、止损触发 20260928）。

---

## 十六、Bug 修复：弹窗表单初始值全部失效（2026-10-17）

### 现象
建仓弹窗打开后「账户」和「买入日期」都是空的，用户必须重新选一遍；
风控参数弹窗打开也是空的。

### 根因（antd Modal 的挂载时序）
`@rc-component/dialog/lib/DialogWrap.js`：

```js
const [animatedVisible, setAnimatedVisible] = React.useState(visible);   // 首次 = false
React.useEffect(() => { if (visible) setAnimatedVisible(true) }, [visible]);

if (!forceRender && destroyOnHidden && !animatedVisible) {
  return null;        // ← 第一帧直接不渲染内容
}
```

即：`open` 变 true 的**第一帧**，弹窗内容（含 `<Form>`）根本没挂载；
父组件里 `useEffect(() => form.setFieldsValue(...))` 在那一帧就执行完了，
此时 Form 尚未连接 —— rc-field-form 会静默丢弃这次赋值。

`antd` 的 `destroyOnClose` 在 v6 已映射到 `destroyOnHidden`（`Modal.js:239`），
所以四个弹窗全部中招：

| 弹窗 | 受影响字段 |
| :--- | :--- |
| `PositionEntryDialog` | `account_id`、`buy_date`、`buy_shares` |
| `SellPositionDialog` | `sell_date`、`sell_price`、`shares`、`reason` |
| `RiskParamsDialog` | 全部 11 个参数 |
| `AccountDialog` | `risk_ratio_percent` 默认值 |

### 修复
四个弹窗统一改为 **`Form.initialValues` + `destroyOnHidden`**：

- `initialValues` 在 `<Form>` **挂载那一刻**生效，不受父组件 effect 时序影响
- `destroyOnHidden` 保证每次打开都重新挂载 → `initialValues` 每次重新应用
- 移除所有 `useEffect(() => form.setFieldsValue(...))` 的初始化写法
- `RiskParamsDialog` 改为「`meta` 就绪后才渲染 Form」，这样 `initialValues` 一定取到数据
- 两个含 `dayjs()` 的 `initialValues` **不做 useMemo**，否则跨天后再打开会带出上次的日期

### 顺带优化的交互
建仓弹窗在**只有一个账户**时不再渲染 Select，直接显示「账户：演示账户（权益 …）」，
彻底去掉"只有一个账户还要再选一次"的摩擦；多账户时默认选中当前页面账户，可切换。
买入日期默认今天、可改任意历史交易日（禁选未来），并加了 `extra` 说明。

### 附带修复
原先 `useEffect` 的依赖里含 `accounts`，账户列表每次重取都会把用户已填的
买入日期 / 股数重置回默认值；改为只按 `open` 与 `initialAccount` 处理。

---

## 十七、「重算轨迹」无反馈 + 逐日回放（2026-10-17）

### 现象
点「重算轨迹」看不出任何变化；用户期望轨迹「从买入那天一天天变化」。

### 原因：不是 bug，是设计导致的"无差异"
持仓的止损轨迹是**每次读取时实时回算**的（`_replay` → `simulate`），
不是预先落库的快照。所以「重算」得到的必然是同一个结果 —— 视觉上没有任何变化。

接口实测正常：`POST /positions/{id}/refresh` → 200，62ms，
返回 `chart.daily` 13 天 + `data_report`。

### 改进

**1）重算给出可见摘要**
按钮点击后弹出 6 秒提示，包含重算出的具体数字：

```
重算完成：13 个交易日 · 止损上移 0 次 · 当前止损 242.16
重算完成：162 个交易日 · 止损上移 8 次 · MTR 过滤 26 次 · 当前止损 1274.27
```

抽屉右上角同时显示「重算于 HH:mm:ss」，让动作可追溯。

**2）新增「逐日回放」**
`PositionKlineChart` 增加 `playKey` 令牌 + 回放逻辑：

- 从**买入日**开始，逐日推进 K 线可视窗口（`setVisibleLogicalRange`）
- 同步逐日揭示**止损阶梯线**上的点（`stopSeries.setData(逐步切片)`）与买卖/触发标记
- 总时长固定约 2.4 秒（`stepMs = clamp(2400 / 天数, 25, 150)`），162 天与 13 天都是这个节奏
- 回放结束自动恢复完整数据与默认视野；`dailyStates < 3` 时按钮禁用
- 回放前自动切到「K线标注」Tab

这样能直观看到 300308 的止损如何从 478.19 一路抬到 1274.27（8 级台阶），
而 688041 因为买入后从未创新高，止损阶梯始终是一条水平线（这是正确结果，不是 bug）。

---

## 十八、账户禁用 / 列精简 / 列头说明（2026-10-17）

### 18.1 账户可禁用（D13）

`accounts` 新增 `is_disable`（默认 `False`），入口在「编辑账户」里的「启用该账户」开关。

**语义**：禁用 = 不想被打扰，但数据仍在。
- 该账户的持仓**不再产生顶部预警红点**（`get_risk_alerts` 未指定账户时过滤掉禁用账户）
- **不参与「刷新监控」的批量重算**（`refresh_all(account_id=None)` 同样过滤）
- 仍可正常查看、管理、建仓、卖出

前端：账户下拉里禁用账户前缀 `⏸`，页面头部显示「已禁用」Tag（带 Tooltip 说明）。

**坑**：预警结果有 120s TTL 缓存，`update_account` 原先不清缓存 → 禁用后要等 2 分钟才生效。
已在 `update_account`（当 `is_disable` 变化时）与 `delete_account` 中主动 `invalidate_alert_cache()`。
实测：禁用 → 预警 6 → 3；恢复启用 → 6。

### 18.2 「已实现」列改为按需显示

活跃持仓表的「已实现」列原本对未减仓的持仓全显示 `-`，没有信息量。
改为 **动态列**：只有当活跃持仓中存在 `sold_shares > 0`（发生过部分卖出）时才渲染该列，
否则整列不出现。实现上用 `hasRealized` 计算后做数组展开：

```jsx
...(hasRealized ? [realizedColumn] : [])
```

### 18.3 ATR / MTR 列头加说明

新增 `ColTitle` 组件（列名 + 问号 + Tooltip）：

- **ATR**：每日真实波幅 `max(高−低, |高−前收|, |低−前收|)` 的 14 日均值，衡量该股当前波动幅度。
  止损 = 买入价 − 2×ATR；移动止损 = 买入以来最高价 − 2.5×ATR。ATR 越大止损越宽。
- **MTR**：只看跳空幅度 `max(|高−前收|, |低−前收|)`。今日 MTR > 20日均值 + 2×标准差 才算「有效放大」，
  此时才允许移动止损上移；否则当天止损不动（**硬性止损触发不受影响**）。

---

## 十九、主账户（D14）

**需求调整**：去掉账户下拉旁的快捷启用/禁用开关，改为在「编辑账户」里设置**主账户**，
进入 `/positions` 页面时默认展示主账户。

### 实现

- `accounts` 新增 `is_primary`（默认 `False`），**全局唯一**
- `PositionRepository.set_primary(account_id)`：先把所有 `is_primary=True` 的账户清零，
  再把目标账户置 True（保证唯一性，实测不会出现两个主账户）
- `create_account`：**首个账户自动设为主账户**
- `update_account(..., is_primary=True/False)`：设为主账户自动取消原主账户；设为 False 则取消（允许 0 个主账户）
- 前端账户选择逻辑（`PositionPage` 初始化 effect）：

```
优先：is_primary 的账户
其次：localStorage 上次选中的账户
最后：第一个账户
```

  effect 有「当前 accountId 仍有效则直接返回」的守卫，所以**手动切换账户后不会被打回主账户**，
  只在「重新进入页面」时才按主账户定位。

- 下拉列表里主账户前缀 `★`，禁用账户前缀 `⏸`
- 「编辑账户」弹窗新增「设为主账户」开关，文案说明全局唯一 + 自动取消原主账户

### 实测

| 操作 | 结果 |
| :--- | :--- |
| 把「启研」设为主账户 | 启研=True，演示账户=False，主账户数=1 ✅ |
| 再把「演示账户」设为主账户 | 演示账户=True，启研=False，主账户数=1 ✅ |
| 取消主账户 | 主账户数=0（允许）✅ |

---

## 二十、持仓详情 K 线：禁止缩放 + 最新日固定右边界（D15）

**需求**：K 线禁止缩放；当期最新交易日不能往左（未来方向）拖走。

### 实现（`PositionKlineChart`）

```js
handleScale: false,                       // 滚轮/捏合/拖价格轴 全部不缩放
handleScroll: { mouseWheel: false, pressedMouseMove: true, vertTouchDrag: false },
timeScale: {
  rightOffset: 0,        // 右侧不留白
  fixRightEdge: true,    // 最新一根固定在最右，无法往未来拖
  fixLeftEdge: false,    // 左侧仍可无限回看历史
}
```

配套调整：
- 初始视野右端由 `candles.length - 1 + 3` 改为 `candles.length - 1`（右端正好落在最新一根）
- 逐日回放的 `to` 由 `idx + 3` 改为 `min(idx, dates.length - 1)`，避免与 `fixRightEdge` 冲突
- **不加 `minBarSpacing/maxBarSpacing` 钳制**：否则 `setVisibleLogicalRange` 想要的区间
  在容器内放不下时会被压缩，初始视野（买入日前 60 根）就展不全。缩放已由 `handleScale=false` 关闭。
- 抽屉图例说明改为「拖动平移（已禁止缩放，最新交易日固定在最右侧）」

---

## 二十一、去掉逐日回放，改为手动前后翻页（D16）

### 为什么删掉回放

原实现固定左边界、每步只增大右边界：

```js
setVisibleLogicalRange({ from: buyIdx - 30, to: idx })   // from 不变，to 递增
```

跨度（`to - from`）越来越大 → 同样宽度里要塞更多 K 线 → **barSpacing 被不断压缩**，
观感是"数据变多、整体缩小"，而不是等量平移。这与「一天天往前推」的预期不符。

### 新方案：手动「前 / 后」翻页

`PositionKlineChart` 改为 `forwardRef` + `useImperativeHandle`，对外暴露：

```js
shift(dir = 1, stepBars?)   // dir: -1 往前（更早）/ +1 往后（更新）
reset()                     // 回到默认视野
```

核心是**保持可视跨度不变**，整体平移：

```js
const span = r.to - r.from
const step = stepBars || Math.max(1, Math.round(span / 4))   // 一次翻 1/4 屏
let from = r.from + dir * step
let to = from + span
if (from < 0)   { from = 0; to = span }                      // 左边界夹紧
if (to > last)  { to = last; from = Math.max(0, last - span) } // 右边界夹紧
```

因为跨度恒定，`barSpacing` 恒定 → **每次点击都是等量平移，不会缩放**。

UI：图表左右两侧各一个半透明圆形按钮（鼠标悬停加深），
左侧 `◀` 往前翻更早的交易日，右侧 `▶` 往后翻更新的交易日；
`title` 有中文说明。右按钮偏移 `right-16` 以避开价格轴。

同时移除了 `playKey` 令牌、回放 effect 与「逐日回放」按钮。

### 21.1 改为「逐日平移 + 长按连发」（D16 修订）

**需求变更**：不要翻页（1/4 屏），而是**一次平移 1 个交易日**，并支持长按连续平移。

- `shift()` 默认步长从 `span/4` 改为 **1 根 K 线**
- 抽屉里的左右按钮改为 `onMouseDown` / `onMouseUp` / `onMouseLeave`
  （+ `onTouchStart` / `onTouchEnd` / `onTouchCancel`）驱动，不再用 `onClick`：
  - 按下立即平移 1 格
  - 按住 **300ms** 后进入连发，每 **60ms** 平移 1 格
  - 松开 / 移出 / 触摸结束 → 清理 `setTimeout` + `setInterval`
  - 弹窗关闭与组件卸载时也会清理，避免定时器泄漏
- 平移后仍会做边界夹紧：`from >= 0`、`to <= last`，所以长按到最新一天会自动停住
- 因跨度恒定，长按连发全程都是等量平移，不会出现缩放变化

> 实测敲定：一次 1 根 + 300ms 延迟 + 60ms 间隔，长按 1 秒约平移十几根，手感接近通达信的方向键。

---

## 二十二、动态止盈（D17）

**动机**：300223 实测——固定止盈只能吃到 10~24% 的行情，ATR 移动止损 22.5%，
而「以最高价为锚回撤 30% 离场」能吃到 44.5%。核心差异是**离场线是否随盈利放大而变宽**。

### 规则

```
浮盈 < tp_arm_r × R   →  ATR 移动止损（2.5×ATR）照常工作（控回撤、保本金）
浮盈 ≥ tp_arm_r × R   →  动态止盈接管：离场线 = 最高价 × (1 − tp_trail_pct%)
                          收盘跌破该线 → 触发「动态止盈」
```

**关键：是「接管」不是「取 max」**。ATR 止损线通常高于回撤止盈线，取 max 等于没切换
（实测捕获率仍是 22.5%）。接管后 ATR 止损不再作为离场依据，只保留展示。

`R = 买入价 − 初始止损`（每股初始风险），`arme` 单调（最高价只增），一旦启用不会退回。

### 新增参数

| 参数 | 默认 | 说明 |
| :--- | ---: | :--- |
| `tp_dynamic_enabled` | `True` | 动态止盈总开关 |
| `tp_trail_pct` | `30.0` | 从最高价回撤多少比例触发（%） |
| `tp_arm_r` | `2.0` | 浮盈达到几倍 R 后由动态止盈接管 |

### 300223 实测（4 个入场点）

| 入场 | 买入 | 捕获率（旧 → 新） | 动作 |
| :--- | ---: | :--- | :--- |
| 20251125 | 79.07 | 23.5% → **56.9%** | 动态止盈 @181.69 |
| 20251215 | 93.24 | 17.0% → **53.2%** | 动态止盈 @181.69 |
| 20260105 | 115.69 | 4.0% → **45.9%** | 动态止盈 @181.69 |
| 20260302 | 128.80 | -12.0% → **-12.0%** | 盘中止损（从未达 2R，不启用）✅ |

**亏损的票不会误用动态止盈**——0302 那笔买入即下跌，浮盈从未到 2R，仍由 ATR 止损兜住。

### 落地

- 引擎：`simulate()` 逐日算 `dynamic_tp_price` / `gain_r` / `exit_line_price`，
  触发时置 `dynamic_tp_hit`；动作优先级插入 `动态止盈`（低于硬性止损，高于止盈参考）
- 服务：`ALERT_ACTIONS` 纳入 `动态止盈`（会出顶部红点）；
  `_build_chart_payload` 输出 `dynamic_tp_series` + 紫色方块标记
- K 线：紫色阶梯线（`lineType: WithSteps`），与琥珀色止损阶梯并存
- 详情抽屉：新增「浮盈 (R)」「动态止盈线」两项；未达标时显示「未启用（需 ≥ 2R）」
- 风控参数：新增 2 个数值 + 1 个开关
- 审计脚本同步新规则后，11 笔持仓的 15 项不变量**全部通过**

### 参数调优建议

`tp_trail_pct` 越小越保守（回吐少、也容易错过后续）：
- 25% → 更稳，均捕获 31.4%
- **30% → 默认，均捕获 44.5%**
- 35% → 更激进，回吐更多


### 22.1 上线后回退（2026-10-17）

**结论：动态止盈默认关闭**（`tp_dynamic_enabled = False`），行为完全回到 ATR 移动止损。

原因：`300223` 这笔记账暴露了"接管"的副作用——它的 ATR 只有 6（相对 259 的股价极紧），
`最高价 − 2.5×ATR = 244.57`，只回吐 5.8%；而 `最高价 × 0.7 = 181.69`，要回吐 30%。
接管后离场线反而变差，白丢 63 个点。

本质问题：**「接管」是否更优取决于 ATR 相对于价格的大小**——
ATR 很紧时 ATR 止损更好（少回吐），ATR 很松时回撤止盈更好（不被中途洗掉）。
单一规则无法两全，因此不设为默认。

实现层面保留（开关 + 参数 + 紫色阶梯线 + 触发标记），默认关闭时：
- `dynamic_tp_series` 为空 → 图上不出现紫线
- 不产生 `动态止盈` 动作与标记
- 详情抽屉的「动态止盈线」与图例项均为条件渲染，不显示
- `浮盈 (R)` 仍保留（与止盈无关，本身有参考价值）

需要时可在「风控参数」里打开 `启用动态止盈`，并配合调小 `tp_trail_pct`（如 20~25%）。

---

## 二十三、卖出记录撤回 + 盈亏比空值隐藏（2026-10-17）

### 23.1 撤回卖出

**入口**：详情抽屉 →「卖出记录」Tab → 每行「撤回」按钮（Popconfirm 二次确认）

**接口**：`POST /positions/{id}/sells/{sell_id}/revoke`

**行为**：
1. 从 `sells` 中移除该笔
2. 现金反向回滚：`current_cash -= sell_price × shares`
3. 重算 `sold_shares / remaining_shares / realized_pnl / realized_cost / return_ratio / avg_sell_price / last_sell_*`
4. 若仍有剩余股数 → `status` 恢复 `OPEN`，清空 `closed_at / holding_calendar_days / close_note`，重新纳入风控监控
5. 刷新快照并失效预警缓存
6. 若回滚后账户现金为负，返回 `warnings` 提示核对出入金记录（不拦截）

**实测**（临时账户）：
```
建仓 2000 股 @11.92        剩余 2000  现金 276160
卖 800 @11.60             剩余 1200  已实现 -256   现金 285440
卖 1200 @11.70            剩余 0     已实现 -520   现金 299480（CLOSED）
撤回第 1 笔 →              剩余 800   已实现 -264   现金 290200（OPEN）✅
撤回不存在的 sell_id →  404「卖出记录不存在」✅
```

### 23.2 「当前盈亏比」空值隐藏

`current_rr = (现价 − 买入价) / (买入价 − 当前止损)`，当移动止损已上移到成本价之上时
分母 ≤ 0，按定义返回 `None`——但界面上仍显示 `-`，属于噪音。

改为 **`{pos.current_rr != null && (...)}` 条件渲染**：没有数据时整项不出现。

当前持仓里 `688131 / 688179 / 300223 / 300308` 这 4 笔（止损已在成本之上）会隐藏该项，
其余有值的正常显示。「浮盈 (R)」不受影响，始终展示。

---

## 二十四、卖出弹窗自动带出当日价格（2026-10-17）

**需求**：选完卖出日期后，卖出价应显示当前最新价。

**实现**（`SellPositionDialog`）：与建仓弹窗同一套交互——日期变化 → 防抖 250ms →
`GET /positions/bar?code=&date=` 取该交易日 OHLC → **自动把卖出价填成当日收盘价**。

- 选「最新交易日」时，拿到的就是**当前最新价**
- 日期下方展示当日行情：`开 x · 高 x · 低 x · 收 x`，并提供两个快捷按钮：
  - 「用收盘价」
  - 「用最新价 x」（回退到 `position.current_price`）
- 拿不到当日行情（停牌/未同步）时，**自动退回最新价**并在字段下方提示原因
- 用 `lastAutoDateRef` 记住已自动带出过的日期，避免列表刷新时把手填的价格覆盖掉
- 关闭弹窗时重置该 ref，下次打开重新带出

实测 `000001`：
```
20261016 → 开11.41 高11.63 低11.36 收11.50   ← 最新交易日 = 最新价
20261015 → 开11.50 高11.52 低11.26 收11.41
20260910 → 开11.43 高11.61 低11.41 收11.60
```

---

## 二十五、历史持仓新增「清仓时长」与「清仓后收益」（2026-10-17）

### 清仓时长

把原「持仓天数」升级为双行显示，并加问号说明：

```
清仓时长
 53 交易日
 79 自然日
```

- 上行 `holding_days`（买入日 → 最后卖出日的交易日数，含首尾）
- 下行 `holding_calendar_days`（自然日数）
- 支持排序

### 清仓后收益（卖飞/卖对判断）

`_enrich()` 对 CLOSED 持仓额外计算清仓后的表现：

| 字段 | 含义 |
| :--- | :--- |
| `post_exit_date` | 最新交易日 |
| `post_exit_price` | 最新价 |
| `post_exit_change_pct` | `(最新价 / 清仓均价 − 1) × 100` |
| `post_exit_pnl` | `(最新价 − 清仓均价) × 卖出股数` |
| `post_exit_days` | 清仓后经过的交易日数 |

**读法**：正数 = 卖出后还在涨（卖飞了）；负数 = 卖出后下跌（卖对了）。
列头带 Tooltip 说明，按 A 股习惯红涨绿跌着色。

实测：

| 代码 | 清仓均价 | 已实现 | 清仓时长 | 清仓后 |
| :--- | ---: | ---: | :--- | :--- |
| 688131 皓元医药 | 80.40 | -1,724 (-9.68%) | 24 交易日 / 40 天 | **+1.28%**（+206 元，卖飞一点） |
| 000001 平安银行 | 11.60 | -6,400 (-2.68%) | 8 交易日 / 10 天 | **-0.86%**（-2,000 元，卖对了） |
| 300223 君正股份 | 201.68 | **+33,726 (+71.84%)** | 53 交易日 / 79 天 | **-50.16%**（-40,464 元，**卖得非常对**） |

300223 这笔尤其说明问题：+71.84% 清仓后，该股又跌了 50%，等于避开了 4 万多的回撤。

---

## 二十六、风控参数逐项说明（2026-10-17）

每个参数名后加灰色 `?`（`QuestionCircleOutlined`，hover / click 均可触发 Tooltip），
内容包含**定义、计算公式、参数调大/调小的后果**，并保留原有的一行 `extra` 简short 提示。

覆盖全部 14 项：

| 参数 | 说明要点 |
| :--- | :--- |
| `atr_period` | ATR 定义 + 周期越长越平滑；止损距离完全由它决定 |
| `k_initial` | 公式 `止损 = 买入价 − k×ATR`；越大越宽、单笔亏损越大 |
| `k_trail` | 公式 `最高价 − k×ATR`、只上移；大=回吐多但吃得住趋势，小=紧但易早退 |
| `k_take_profit` | **建仓后固定**，只是提醒位不强制卖，实际出场看移动止损 |
| `mtr_period` | MTR 只看跳空幅度，均值/标准差窗口 |
| `mtr_std_mult` | `MTR > 均值 + k×标准差` 才算有效放大；调到 0≈关闭 |
| `trend_ma_period` | 仅趋势过滤启用时生效 |
| `trailing_high_source` | 收盘价（平滑/推荐）vs 日内最高价（紧/易被噪音触发） |
| `risk_ratio_percent` | 完整倒推公式：可承受亏损 ÷ 每股风险 = 建议股数；权益动态调整 |
| `mtr_filter_enabled` | 关闭后每日都上移；**硬性止损触发不受影响** |
| `trend_filter_enabled` | 震荡市避免止损被反复抬高后被扫 |
| `tp_dynamic_enabled` | 接管语义 + ⚠ 会明显放松止损；默认关闭 |
| `tp_trail_pct` | 越小越保守，实测 25%~30% 平衡 |
| `tp_arm_r` | 设高一些避免"刚赚一点就放宽" |

Tooltip 用 `trigger={['hover','click']}`（触屏也能点开），`maxWidth: 380`，
内容用 `whiteSpace: 'pre-wrap'` 保留换行分段。

---

## 二十七、修正 K 线灰白虚线无标识（2026-10-17）

**问题**：抽屉 K 线上有两条灰白虚线，图上没有任何文字说明。经排查是：

| 线 | 画在 | 原样式 | 原标签 |
| :--- | :--- | :--- | :--- |
| **成本线**（`buy_price_adj`） | 前端 `priceLines` memo | `#9ca3af` lineStyle 3（长虚线） | ❌ `axisLabelVisible: false` |
| **初始止损线**（`initial_stop_loss_price_adj`） | 后端 `_build_chart_payload` | `#9ca3af` lineStyle 1（点线） | ❌ `axisLabelVisible: false` |

两条颜色相同、又都没有轴标签，用户完全无法分辨 —— 是排版疏漏。

**修复**：
1. 两条线都改为 `axisLabelVisible: true`，轴上直接显示 `成本 555.05` / `初始止损 478.19`
2. 成本线样式从 `lineStyle 3`（长虚线）改为 `lineStyle 2`（普通虚线），
   与初始止损的 `lineStyle 1`（点线）在视觉上区分开
3. 抽屉图例补充两项：`╌╌ 成本价`、`┈┈ 初始止损`

**现状**：四条水平线全部带轴标签，含义一目了然。

---

## 二十八、编辑账户支持删除账户（2026-10-17）

### 后端

`delete_account(account_id, force=False)`：

- `force=False`（默认）：账户下有持仓 → **409** 拒绝，提示改用「删除账户」并确认
- `force=True`：**先级联删除该账户下全部持仓记录**（含已平仓），再删账户，并失效预警缓存

接口：`DELETE /positions/accounts/{account_id}?force=true`

### 前端

「编辑账户」弹窗底部自定义 footer：

```
[🗑 删除账户]                                     [取消] [保存]
```
（左侧红色文字按钮，右侧常规操作；新建账户模式下不显示删除）

点「删除账户」→ Popconfirm 二次确认，明确告知影响面：

> 删除整个账户？
> 将同时删除该账户下的 **N** 笔持仓记录（含已平仓），以及其现金与权益数据。
> **此操作不可撤销。**

`N` 由 `PositionPage` 传入的 `positionCount={positions.length}` 提供。

删除成功后 `onDeleted` 回调会：关闭弹窗 → `setAccountId(null)` → 清 localStorage →
失效 `position-accounts / positions / position-alerts` 三个查询 →
账户选择逻辑自动回落到主账户或第一个账户。

### 实测

```
建账户 + 2 笔持仓（1 活跃 + 1 已平仓）
DELETE 不带 force → 409「该账户下仍有 2 笔持仓（含已平仓记录）…」
DELETE ?force=true → 200，账户已删、残留持仓 0 笔 ✅
```

---

## 二十九、刷新监控补齐日线 + 建仓不依赖当日行情（2026-10-17）

### 29.1 刷新监控必须保证数据到最新

原 `ensure_position_data()` 只在「最后一根 < 买入日」时补数据，**忽略了"数据过旧"**：
某只票的日线停在 3 天前，快照就会用 3 天前的价格算止损，风控失真。

判定规则改为：

| 情况 | 动作 |
| :--- | :--- |
| 无数据 / 不足 `MIN_BARS_FOR_RISK`(40) 根 | 全量拉取（回溯 10 年） |
| 最后一根 < 买入日 | 增量拉取（建仓日行情还没同步） |
| **最后一根 < 基准交易日** | **增量拉取（数据过旧，快照会失真）** ← 新增 |
| 其余 | 跳过 |

**基准交易日 = `min(集合内最新日期, 截至今天的最近交易日)`**。
新增 `_latest_trade_day()` 从今天向前回退到最近的工作日。

> 为什么不能直接用「集合内最新日期」：该日期可能落在未来（数据源/环境时区问题），
> 或今天本身不是交易日。直接用会导致**每次刷新都做无谓的网络同步**。
> 实测：系统日期为 2026-10-19（周一）时基准日=20261019，持仓有 1016 数据的会被
> 正确判为过旧并补到 1019；而 1019 已是周末时基准日=1016，不会重复拉。

新增 Repository 方法：`get_market_latest_date(asset_type)`、`get_latest_bar_before(code, type, date)`。

### 29.2 建仓不再依赖买入日行情

原逻辑：买入日没有日线 → 直接 400「不是交易日（或该日停牌无行情）」。
这导致**当天刚买、一键更新还没跑时无法建仓**。

新逻辑（`preview_entry`）：

```
买入日有行情            → 正常
买入日无行情 且 非交易日 → 400「不是交易日，请重新选择买入日期」
买入日无行情 且 是交易日 → ✅ 允许建仓，data_pending = true
    · ATR_entry 仍用「买入日之前」的日线算（本来就不依赖当天数据）
    · 复权锚点 anchor_close 退回「买入日之前最后一根收盘价」
    · 若买入日之前一根都没有 → 400（无法算 ATR）
```

建仓后：
- 止损轨迹暂不可用，`_enrich` 返回明确提示：
  「买入日 X 之后还没有日线数据（行情可能尚未同步），执行「刷新监控」可自动补齐后再回算」
- 列表显示动作「数据缺失」
- 点「刷新监控」→ `ensure_position_data` 判定「最后一根 < 买入日」→ 增量拉取 → 补齐后自动恢复

前端：建仓弹窗在 `data_pending` 时显示蓝色提示条说明「不影响建仓，刷新监控会补齐」；
`get_bar` 的报错也区分「不是交易日」与「行情尚未同步，请手动填写价格」。

### 29.3 实测

用一只停牌股 `600636`（最新只到 20260617）在 `20260803` 建仓：

```
预览   HTTP 200  data_pending=true  anchor_close=1.85(前收)  ATR=0.31
       messages: ['...', '20260803 的行情尚未同步（不影响建仓）...']
建仓   HTTP 201  剩余 1000 股  快照日期 null
       error: 「买入日 20260803 之后还没有日线数据（行情可能尚未同步），执行「刷新监控」可自动补齐后再回算」
刷新   HTTP 200  data = {incremental: {stock: ['600636']}, skipped: ['600636']}
       （该股确实停牌，无新数据 → 正确跳过）
```

---

## 三十、活跃持仓加「持股时间」列（2026-10-17）

位置：活跃持仓表，「买入日」之后。

```
持股时间
 29 交易日
 7.0 周 · 49 天
```

- **上行**：`holding_days`（交易日数，即实际有行情的天数）
- **下行**：自然日数 + 友好单位，由 `fmtHoldingSpan()` 按量级自动换算：
  - `< 7 天` → `x 天`
  - `< 60 天` → `x.x 周`
  - `< 365 天` → `x.x 个月`
  - `≥ 365 天` → `x.x 年`
- 列头带 Tooltip 说明两者区别；支持排序

后端：`_enrich()` 为 **OPEN 持仓也补上 `holding_calendar_days`**
（原实现只有 CLOSED 才落库该字段）。用新增的 `_calendar_days(start, end)` 计算
「买入日 → 最新交易日（含首尾）」的自然日数，安全性用 try/except 兜底。

实测：

| 代码 | 买入日 | 快照日 | 交易日 | 自然日 |
| :--- | :--- | :--- | ---: | ---: |
| 688222 | 2026-10-19 | 2026-10-19 | 1 | 1 天 |
| 603259 | 2026-10-16 | 2026-10-19 | 2 | 4 天 |
| 513120 | 2026-10-13 | 2026-10-19 | 5 | 1.0 周 · 7 天 |
| 688179 | 2026-09-01 | 2026-10-19 | 29 | 7.0 周 · 49 天 |

### 30.1 文案精简：去掉「交易」二字（2026-10-19）

用户反馈「知道是交易日」，数值后面不必重复写「交易日」。

| 位置 | 原 | 现 |
| :--- | :--- | :--- |
| 活跃持仓 · 持股时间 | `29 交易日` | `29 天` |
| 历史持仓 · 清仓时长 | `53 交易日` | `53 天` |
| 抽屉 · 字段名 | `持仓交易日` | `持股天数` |
| 抽屉 · 字段值 | `29` | `29 / 49 自然日`（补上自然日对照） |
| 抽屉 · 重算提示 | `29 个交易日` | `29 天` |

Tooltip 说明里仍保留「最新交易日」的表述（那是解释口径，不是数值标签）。

### 30.2 去掉自然日对照（2026-10-19）

用户反馈不需要「自然日」对照，改为**单值友好显示**：

| 位置 | 原 | 现 |
| :--- | :--- | :--- |
| 活跃持仓 · 持股时间 | `29 交易日`<br>`7.0 周 · 49 天` | `7.0 周` |
| 历史持仓 · 清仓时长 | `53 交易日`<br>`79 自然日` | `2.6 个月` |
| 抽屉 · 字段 | `持股天数 29 / 49 自然日` | `持股时间 7.0 周` |

- 统一按 **自然日** 折算：`<7 天`→天、`<60`→周、`<365`→月、`≥365`→年
- 列宽从 108 收窄到 88，排序改为按 `holding_calendar_days`
- 抽屉改名为「持股时间」并复用 `fmtHoldingSpan`（需补 import）

