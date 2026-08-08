# Watchlist 均线预警功能设计文档

日期：2026-08-08

## 背景与目标

`/watchlist` 重点关注列表页新增均线预警能力：

- 移除"刷新"按钮（RPS 红筛选参数变化已触发数据重查，刷新按钮冗余）
- 新增"预警检查"按钮：点击后扫描关注列表全部标的（股票 + ETF）的最新交易日数据，按均线规则产生预警记录
- 新增"预警"按钮：跳转 `/watchlist/alerts` 新页面，参考 `/etf/alerts` 页面

## 预警规则

仅检查**最新一个交易日**（每次点击幂等，同一天不重复产生相同预警）。触发条件为"首次跌破/穿越"（前一日在均线之上，当日跌破/穿越），避免连续阴跌导致每日重复报警：

| 原因 | 触发条件 |
| :--- | :--- |
| 跌破5日均线 | close < ma5 且 前一日 close ≥ 前一日 ma5 |
| 跌破10日均线 | close < ma10 且 前一日 close ≥ 前一日 ma10 |
| 跌破20日均线 | close < ma20 且 前一日 close ≥ 前一日 ma20 |
| 5日均线上穿10日均线 | ma5 > ma10 且 前一日 ma5 ≤ 前一日 ma10 |

- 同一标的一天可产生多条预警（不同原因）
- `stock_daily`/`etf_daily` 仅冗余了 ma10/20/50/120，**无 ma5** → 引擎内现场取最近 20+ 条 close 计算 ma5

## 数据模型

新建集合 `watchlist_alerts`：

```
{ code: '600299', name: 'XX', trade_date: '20260807', close: 8.45,
  reason: '跌破5日均线', created_at: <datetime> }
```

- 建 `(code, trade_date, reason)` 复合唯一索引（去重，防重复插入）
- 参考 `etf_alerts` 的 `code_1_trade_date_1` 索引模式

## 后端

### 引擎 `app/engine/watchlist_alert.py`（参考 `ene_alert.py` 结构）

- `check_latest() -> int`：遍历 `watchlist` 集合，对每个标的（type=stock/etf）取最近 21 条日线
  - 计算 ma5（现场算）+ 读取 ma10/ma20
  - 比较最新与前一日收盘价/均线，按规则生成预警
  - 插入 `watchlist_alerts`（DuplicateKeyError 跳过），返回新增总数
- `get_alerts(start_date, end_date, page, page_size)`：分页查询（排序 trade_date desc）

### API `app/server/api/watchlist.py` 扩展（prefix=/api/watchlist）

| 方法 | 路径 | 说明 |
| :--- | :--- | :--- |
| POST | `/api/watchlist/alerts/check` | 触发扫描，返回 `{new_alerts: N}` |
| GET | `/api/watchlist/alerts` | 分页查询：start_date/end_date/page/page_size |

### 索引

`watchlist_alerts` 集合建 `(code, trade_date, reason)` 唯一索引。

## 前端

### WatchlistPage.jsx

- 移除"刷新"按钮（`ReloadOutlined`）
- 新增"预警检查"按钮：调 `watchlistApi.checkAlerts()`，成功 message 提示新增条数
- 新增"预警"按钮（`AlertOutlined`）：navigate `/watchlist/alerts`

### 新页面 WatchlistAlertPage.jsx（参考 ETFAlertPage.jsx）

- 分页表格：代码 / 名称 / 日期 / 收盘价 / 原因(Tag) / 触发时间
- 日期范围筛选 RangePicker
- 返回按钮 navigate(-1)
- 行跳转：股票 → `/search?code=..`，ETF → `/search?etf=..`

### App.jsx

- 注册路由 `<Route path="/watchlist/alerts" element={<WatchlistAlertPage />} />`

### api.js

```
export const watchlistApi = {
  ...,
  checkAlerts: () => api.post('/watchlist/alerts/check'),
  getAlerts: (params = {}) => api.get('/watchlist/alerts', { params }),
}
```

## 验证

- 后端：直接调用 `check_latest()` 扫 watchlist，验证 21 条标的产生结果；curl POST/GET 接口
- 前端：构建 + 浏览器实测预警检查按钮、/watchlist/alerts 页面展示、日期筛选、行跳转
- 幂等：连续两次 check 第二次 new_alerts=0

## 明确不做（YAGNI）

- 不做前端轮询推送（与 ETF 预警通知不同，此处为手动按钮触发）
- 不做历史回刷 backfill（仅最新交易日，天然增量）
- 不做 /recent 接口（无轮询需求）
