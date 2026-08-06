# 重点关注列表（Watchlist）设计文档

日期：2026-08-05

## 背景与目标

用户需要一个"重点关注列表"，可同时跟踪个股和 ETF：
- 通过输入 code 将个股 / ETF 加入列表（后端校验有效性）
- 支持删除
- 列表头参考 /etf 页面字段，保留 RPS 红筛选

## 技术方案（方案 A：后端 MongoDB）

新建 MongoDB 集合 `watchlist` + 独立 API + 独立前端页面 `/watchlist`，顶部导航加入口。

## 数据模型

`watchlist` 集合：

```
{ code: '510300', type: 'etf',  created_at: <datetime> }
{ code: '600519', type: 'stock', created_at: <datetime> }
```

- 建 `(code, type)` 复合唯一索引，防止重复添加。
- `type` 由后端在添加时自动识别：查 `etf_basics`（code 字段）→ etf；否则查 `stock_basics`（stock_code 字段）→ stock。
- 名称不冗余存储，展示时从 basics 实时读取，避免与同步流程产生不一致。

## 后端 API（app/server/api/watchlist.py, prefix=/api/watchlist）

| 方法 | 路径 | 说明 |
| :--- | :--- | :--- |
| GET | `/api/watchlist` | 列表 + 最新行情；支持 keyword / sort_by / sort_order / rps_red |
| POST | `/api/watchlist` | body `{code}`；校验存在性，自动识别 type；重复返回 409 |
| DELETE | `/api/watchlist/{code}` | 删除（按 code + type） |

### GET 列表行情拼装

遍历 watchlist 条目，按 type 从对应集合取最新一条（字段对齐）：

- etf  → `etf_daily`（stock_code）+ `etf_basics`（code/name）
- stock → `stock_daily`（stock_code）+ `stock_basics`（stock_code/stock_name）

统一返回字段：code, name, type, close, change_pct, chg_5d, chg_10d, chg_20d, chg_50d, chg_120d, rps_10, rps_20, rps_50。

### RPS 红筛选

复用 /etf 逻辑：`rps_red` ∈ {one, two, three}，阈值 87，对 rps_10/20/50 计数。

### 错误处理

- code 无效（两表都查不到）→ 400 "未找到该代码"
- 已存在 → 409 "已在列表中"

## 前端

### WatchlistPage.jsx（参考 ETFPage.jsx）

- 顶部操作栏：标题 + 数量 Tag、code 输入框（回车添加）、RPS红筛选下拉、刷新按钮
- 表格列：
  - 代码（mono）
  - 名称（蓝字，点击跳转 `/search?code=..` 或 `/search?etf=..`）
  - 类型 Tag（个股蓝色 / ETF 青色）
  - 最新价 / 日涨幅 / 5日 / 10日 / 20日 / 50日 / 120日涨幅
  - RPS10 / RPS20 / RPS50（≥90 红加粗、≥80 橙、≤20 绿）
  - 操作：删除按钮
- 列头排序（sorter）保留，排序参数走 URL（复用 updateParam 模式）

### App.jsx

- 注册路由 `<Route path="/watchlist" element={<WatchlistPage />} />`
- 导航栏加"关注"入口（StarOutlined 图标）

### api.js

```
export const watchlistApi = {
  getList: (params = {}) => api.get('/watchlist', { params }),
  add: (code) => api.post('/watchlist', { code }),
  remove: (code) => api.delete(`/watchlist/${code}`),
}
```

## 验证

- 后端：curl 全链路（添加有效/无效 code、重复添加、列表含行情与红筛选、删除）
- 前端：构建 + 浏览器实测添加/删除/红筛选/跳转

## 明确不做（YAGNI）

- 不做多用户/鉴权（个人系统单用户）
- 不做分组/排序持久化（默认按添加时间展示，列头可排序）
- 不做批量导入
