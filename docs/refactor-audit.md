# 项目精细化与重构 Task 清单

> 审计对象：YuQuant（React 18 + Vite + antd 6 + FastAPI + MongoDB + pydantic 2.13）
> 前端根：`app/client/src`　后端根：`app/server`（另 `app/data` 数据源、`app/engine` 因子引擎）
> 规模：约 2.2 万行 Python + 20+ 前端页面。本文档所有定位均为已核实的具体文件/行号。

---

## 执行进度追踪（2026-08-16 更新）

### ✅ 已完成并验证

**P0（阻断/严重）**
- 后端：`main.py` 异常处理器脱敏 + `RequestValidationError` 422 + `config.DEBUG` 开关（红测试转绿）
- 后端：删除 `services/market_service.py`、`services/sync_service.py` 假实现死代码
- 前端：`usePolling` `isPaused` 改响应式；`useTaskPolling` 删冗余竞态 effect
- 前端：`App.jsx` ETF 预警轮询改用 `usePolling`

**P1（DRY/死代码）**
- 后端：`db.py` 提取 `_get_sync_start_date`；`db.py`/`cache.py` 9 处 `print → logging`
- 前端：`api.js` 去重；`/calendar/task/:id` 收敛为 `taskApi.getStatus`（9 调用点 + 2 import）
- 前端：`useOneClickUpdate` 复用 `useTaskPolling`；`App.jsx` checkSyncTime/checkHealth 改用 `usePolling`；清理 `TestIndexChart.jsx` 调试块

**P2 低风险（a/b/c）**
- `models.py` `SyncRequest` 迁移 `ConfigDict`；删除 `config.TDX_SERVERS` 死配置
- `repositories/base.py` `update_one` 加 docstring + 新增 `update_one_result`
- `db.py` `bulk_upsert_stock_basics`/`bulk_upsert_etf_basics` 改 `bulk_write`

**P2-d（架构收口，api 层直连 146 → 87 处）**
- 新建 repository：`WatchlistRepository`、`SearchRepository`、`EtfRepository`、`MarketAnalysisRepository`(12 方法)、`SystemConfigRepository`
- 补方法：`StockRepository`(get_disabled_codes/get_all_codes)、`IndexRepository`(update_disable_status)、`TaskRepository`(find_running_by_stock_name)
- 收口 api 文件（`db[...]` 直连 = 0）：watchlist / search / etf / stocks / market_analysis / settings_tasks / sync
- `factors.py` 部分收口（6 处 CRUD：禁用/创建/配置/导入简单 CRUD/清任务，21→10 处）

**一键更新修复（测试反馈）**
- `one_click_orchestrator`：`_get_last_update_date` 加 `is_final=True` 过滤；数据完整时兜底 `dates=[last_date]` 执行单日重算；提交改 `_run_wrapper`

### 📌 本次额外发现（原始审计之上新增）

1. **`config.TDX_SERVERS` 是死配置**：真实使用 `pytdx_source.py` 与 `data_service.py` 各自维护一份，IP 硬编码散落 3 处，待收敛。
2. **repository 层 `update_disable_status` 是死代码**：`factors.py` 的 `/disable` 路由直接操作 `db`，未走 repository（已收口）。
3. **`_norm_date` 原 `.zfill(8)` 有缺陷**：对非零填充输入会错，已改 `strptime` 严格解析（`AGENTS.md` 第 6 节同步修正）。
4. **注释-代码不一致**：`_get_sync_start_date` 注释写"旧数据默认为已收盘"，但 `get('is_final', False)` 缺省为 False，`test_missing_is_final_defaults_to_false` 已锁定现状待决策。
5. **一键更新日期范围缺陷**：`_get_last_update_date` 未过滤 `is_final`，且数据完整时 RPS/PE/预计算被 `for date in []` 跳过（已修复）。
6. **`import_sector_codes_from_excel` 均线计算重复**：手算 MA5~MA250 与 `db.bulk_upsert_daily_data` 重复，待下沉复用（见 factors 里程碑）。

### 验证基线

- 后端：`python -m unittest discover -s tests` → 50 测试全绿
- 前端：`npm run build`（vite）→ 通过（5466 模块）
- 新增测试：`tests/test_date_range_query.py`、`tests/test_sync_start_date.py`、`tests/test_exception_handler.py`、`tests/test_calendar_service.py`

### ⏳ 待执行（P2 结构性大工程）

**P2-d 已收口 16/16 个 api 文件**（api 层直连 146 → 0 处）。三个里程碑进展：
- ✅ `factors`：21 → 0 处（含 2 个表征测试文件）
- ✅ `market_review`：29 → 0 处（新建 `MarketReviewRepository` 11 方法）
- ✅ `calendar`：48 → 0 处（任务状态/最新交易日/交易日/周月总结缓存/AI 补全已收口；快照生成 + 每日总结的 18 处模块级业务函数下沉 `calendar_service.py`，数据访问下沉 `CalendarRepository`，service 全程零 `get_db` 直连，路由薄化）

`calendar` 收口已闭环（见 `docs/plans/2026-08-16-calendar-refactor.md`）：快照生成（`generate_calendar_snapshot`/`generate_month_snapshots`/`save_calendar_snapshot`）+ 每日总结（`get_calendar_daily_summary`）已下沉 `calendar_service.py`，并补 `tests/test_calendar_service.py` 表征测试锁定返回结构。

- P2-e（拆巨型控制器）已并入上述 3 个里程碑（数据访问下移 + 业务逻辑下沉 services）。
- P2-f（前端图库收敛 / react-query 二选一）待立项。

---

## 第一部分：按优先级排列的任务清单表

### 优先级 P0（阻断/严重 —— 健壮性 / Bug / 安全隐患）

| 优先级 | 模块 | 坏味道/问题类型 | 问题描述与定位文件 | 修改方案概要 |
| :--- | :--- | :--- | :--- | :--- |
| **P0** | 后端 | 安全/信息泄露 | `app/server/main.py:119-130` 全局异常处理器把 `detail: str(exc)` 原样回给前端，内部堆栈/表结构/路径泄露 | 生产环境统一返回 `{"code":500,"message":"服务器内部错误"}`，完整堆栈仅 `logger.error(..., exc_info=True)` 写入日志；区分 `RequestValidationError` 单独处理 |
| **P0** | 前端 | Bug/非响应式状态 | `app/client/src/hooks/usePolling.js:105` 返回 `isPaused: isPausedRef.current`，ref 的当前值快照不会触发重渲染，消费方永远拿到初始值 `false` | 用 `useState` 驱动 `isPaused`，或在 `visibilitychange` 回调里 `setState`，返回响应式状态 |
| **P0** | 前端 | Bug/竞态与依赖缺失 | `app/client/src/hooks/useTaskPolling.js:89-103` 两个 `useEffect` 同时操作 `start/stop`，第二个 effect 依赖数组仅 `[taskId]`（缺 `stop/start/isPolling`），taskId 变化时可能重复挂定时器或清理后残留 | 合并为单一 effect，依赖补全 `[taskId, autoStart, start, stop]`，删除 98-103 的重启 effect |
| **P0** | 后端 | 数据正确性/假实现 | `app/server/services/sync_service.py:45/76/106/127/133` 与 `market_service.py:40/59/78/97/143` 均为 `# TODO` 桩函数，`sync_*` 直接 `return SyncResult(success=True, synced=total)` 但**什么都没同步**、`market_*` 直接 `return {}`；当前虽无调用点（仅 `services/__init__.py` 导出），一旦误接线会"静默成功" | 删除未接线死代码，或改为 `raise NotImplementedError`；真正同步逻辑以 `app/server/api/sync.py` 为准 |
| **P0** | 前端 | 轮询缺陷 | `app/client/src/App.jsx:77-102` ETF 预警轮询 `useEffect` 依赖 `[lastAlertCheck]`，而回调内部 `setLastAlertCheck`，导致**每个 tick 都销毁并重建定时器**，且依赖闭包易漂移 | 改用统一 `usePolling` Hook（见第二部分 Diff 2），依赖改为 `[]` |

### 优先级 P1（推荐优化 —— DRY / 死代码清理）

| 优先级 | 模块 | 坏味道/问题类型 | 问题描述与定位文件 | 修改方案概要 |
| :--- | :--- | :--- | :--- | :--- |
| **P1** | 前端 | DRY/重复声明 | `app/client/src/api.js:72-75` 与 `106-109` 同名 `factorApi.importSectorCodes` 定义两次（后者覆盖前者）；`90-91` `factorApi.getStockList` 与 `43` `stockApi.getStockList` 重复 | 删除重复 key，同一资源只归属一个命名空间对象 |
| **P1** | 前端 | DRY/重复端点 | `api.js:117`(`syncApi.getTaskStatus`)、`141`(`marketReviewApi.getAiAnalysisTask`)、`168`(`calendarApi.getTaskStatus`)、`185`(`taskApi.getTaskStatus`) 指向同一 `/calendar/task/:id`，声明 4 次 | 收敛为单一 `taskApi.getTaskStatus`（见第二部分 Diff 1） |
| **P1** | 前端 | DRY/逻辑重复 | `usePolling.js`、`useTaskPolling.js`、`useOneClickUpdate.js:77-139` 各自手写 `setInterval + clearInterval + ref` 轮询模板；`App.jsx:45-67` 又手写 `checkSyncTime/checkHealth` 两个 `setInterval` | 统一轮询底座，业务钩子只传回调与间隔（见 Diff 2）；`useOneClickUpdate` 复用 `useTaskPolling` |
| **P1** | 后端 | DRY/逐行重复 | `app/data/db.py:383-418` `get_stock_sync_start_date` 与 `421-456` `get_sector_sync_start_date` 逻辑完全一致仅集合/键名不同；`346-363` `get_daily_data` 与 `366-380` `has_daily_data` 的查询构建重复 | 提取 `_get_sync_start_date(coll_name)` 与 `_build_date_query`（见 Diff 3） |
| **P1** | 后端 | 日志规范 | `app/server/cache.py:40,42` 与 `app/data/db.py:111,126,173,194,343,542,557` 用 `print()` 打错误/状态，不进日志系统，无级别、无文件 | 统一 `logging.getLogger(__name__)`，`db.py` 顶层模块 logger |
| **P1** | 前端 | 死代码/调试残留 | `app/client/src/pages/TestIndexChart.jsx:45-66` 遗留 `console.log` 调试块（CR5 数据/合并后数据/前3条） | 删除调试块；该页面若仅供自测，考虑移出主路由或加 `VITE_` 开关 |
| **P1** | 后端 | 死代码 | `app/server/services/market_service.py` 全文 161 行与 `sync_service.py` 全文 146 行（`get_stock_list` 之外的 `get_sector_list/get_index_list` 也返回空）无任何调用点 | 整体删除并从 `services/__init__.py:6-7` 移除导出 |
| **P1** | 后端 | 静默吞异常 | `app/data/db.py:237` `except Exception: pass` 吞掉 RPS 清除日期探测失败，`app/engine/watchlist_alert.py:33`、`app/server/services/market_sectors.py:48` 等裸 `except Exception:`（grep 全量 202 处 `except Exception`） | 关键路径改为 `logger.exception` + 显式降级；区分可恢复/不可恢复 |

### 优先级 P2（代码优雅 —— 架构规范 / 性能）

| 优先级 | 模块 | 坏味道/问题类型 | 问题描述与定位文件 | 修改方案概要 |
| :--- | :--- | :--- | :--- | :--- |
| **P2** | 后端 | 架构架空/SRP | 10 个 API 路由共 **146 处** `from app.data.db import get_db` + `db['xxx']` 直接访问（`stocks/factors/sync/watchlist/etf/market_analysis/calendar/market_review/search/settings_tasks`），`repositories/`+`factories/` 分层形同虚设（仅 `one_click_update_v2.py`、`calendar.py:1196` 用到 TaskRepository） | 按域补 Repository（如 `WatchlistRepository`，见 Diff 5），路由只调 Service/Repository；`db['...']` 收口到 `repositories/` |
| **P2** | 后端 | 巨型控制器 | `api/calendar.py` 1325 行、`api/factors.py` 910 行、`api/market_review.py` 712 行——路由内夹带大量聚合、缓存、重算业务逻辑 | 拆分：路由薄化 + 业务下沉 `services/`，缓存读写下沉 `summary_repository` |
| **P2** | 后端 | 规范/类型 | `app/server/models.py:82-83` 仍用 Pydantic v1 的 `class Config: populate_by_name`，而项目实际 pydantic **2.13.4**；`config.py:25` `TDX_SERVERS: List[tuple]` 硬编码 IP 且 tuple 无字段语义 | 迁移 `model_config = ConfigDict(populate_by_name=True)`；TDX 列表改 `List[TdxServer]` 模型 + `.env` 可配 |
| **P2** | 后端 | 性能 | `app/data/db.py:114-126` `bulk_upsert_stock_basics`、`545-557` `bulk_upsert_etf_basics` 逐条 `update_one` 循环（N 次网络往返） | 改 `bulk_write([UpdateOne(...)], ordered=False)`，与 `bulk_upsert_daily_data` 一致 |
| **P2** | 后端 | API 语义误导 | `app/server/repositories/base.py:68-71` `update_one` 返回 `modified_count`，`upsert=True` 时新插入文档 `modified_count=0`，调用方误判"未更新" | 返回 `UpdateResult` 或 `(matched, modified, upserted_id)` 三元组 |
| **P2** | 前端 | 依赖冗余 | `package.json` 同时引入 **echarts + echarts-for-react + recharts + lightweight-charts** 三套图表库；`main.jsx` 配好 `@tanstack/react-query` 但全项目仅 4 页用 `useQuery`，其余裸 axios + 手写 state | 图库收敛到 1~2 套；数据层二选一（react-query 全覆盖 或 移除依赖），消除双轨 |
| **P2** | 前端 | 类型/契约不一致 | `api.js:23-39` 响应拦截器成功返回 `res.data`、失败 `Promise.reject(err)`（完整 AxiosError），成功/失败返回结构不一致；且每个非 health 错误都全局 toast，调用方又各自 catch 打日志，双重复处理 | 失败也 reject 标准化错误对象；toast 与业务提示职责分离 |
| **P2** | 后端 | 硬编码/魔数 | `main.py:73` 交易时段 `if 9 <= hour <= 15`、`79` `time.sleep(300)`、日志 `26-45` handler 无"已添加"守卫（`reload=True` 下可能重复 add）；`db.py:19-24` `COLLECTION_MAP` 等散落魔数 | 时段/间隔进 `Settings`；日志用 `dictConfig` 一次性配置；集合名/字段名集中到常量模块 |
| **P2** | 后端 | 重复字段投影 | `api/watchlist.py:19-22` `_QUOTE_FIELDS` 与 `api/etf.py` 的行情投影字段重复（跨文件魔数字段） | 提取到 `app/server/constants.py` 或 Repository 常量 |

---

## 第二部分：核心重构代码示例（Code Diffs）

> 挑选最高优先级的 5 个重点项：2 个前端 DRY/Bug、2 个后端 DRY/健壮性、1 个后端架构收口。

### Diff 1　前端｜统一任务状态查询 API，消除 4 次重复声明

**痛点**：同一 `/calendar/task/:id` 在 `api.js` 里以 4 个不同名字声明（`syncApi.getTaskStatus`、`marketReviewApi.getAiAnalysisTask`、`calendarApi.getTaskStatus`、`taskApi.getTaskStatus`），调用点各写各的，改端点要改 4 处。

**修改前（Before）** —— `app/client/src/api.js`

```js
export const syncApi = {
  syncBasics: () => api.post('/sync/basics'),
  // ...
  getTaskStatus: (taskId) => api.get(`/calendar/task/${taskId}`),   // 重复 1
  // ...
}

export const marketReviewApi = {
  // ...
  getAiAnalysisTask: (taskId) => api.get(`/calendar/task/${taskId}`), // 重复 2
  // ...
}

export const calendarApi = {
  // ...
  getTaskStatus: (taskId) => api.get(`/calendar/task/${taskId}`),     // 重复 3
}

export const taskApi = {
  getTaskStatus: (taskId) => api.get(`/calendar/task/${taskId}`)      // 重复 4
}
```

**封装后（After）**

```js
// 单一任务查询命名空间，全项目唯一入口
export const taskApi = {
  getStatus: (taskId) => api.get(`/calendar/task/${taskId}`),
  cancel: (taskId) => api.delete(`/sync/task/${taskId}`),
}
// 删除 syncApi.getTaskStatus / marketReviewApi.getAiAnalysisTask / calendarApi.getTaskStatus
```

**调用方式（Usage）**

```js
// useOneClickUpdate.js / useTaskPolling.js / 各页面统一改为：
import { taskApi } from '../api'
const status = await taskApi.getStatus(taskId)
```

---

### Diff 2　前端｜统一轮询底座 + 修复 `usePolling` 非响应式 Bug，替换 `App.jsx` 手写定时器

**痛点**：`usePolling` 返回的 `isPaused` 是 ref 快照（非响应式）；`App.jsx` 的 ETF 预警轮询手写 `setInterval`，且依赖 `[lastAlertCheck]` 导致每个 tick 重建定时器。

**修改前（Before）** —— `usePolling.js:105` 与 `App.jsx:77-102`

```js
// usePolling.js —— isPaused 是 ref 值，消费方永不刷新
return { start, stop, resetRetries, isPaused: isPausedRef.current }

// App.jsx —— 手写轮询 + 依赖陷阱
useEffect(() => {
  const checkAlerts = async () => { /* ...getRecent... */ }
  const timer = setInterval(checkAlerts, 30000)
  return () => clearInterval(timer)
}, [lastAlertCheck])   // 每次 tick 都重建定时器
```

**封装后（After）**

```js
// usePolling.js —— 状态改由 useState 驱动，回调通过 ref 保持最新
export function usePolling(callback, interval, enabled = true, options = {}) {
  const { pauseOnHidden = true, maxRetries = 3, backoffMultiplier = 2 } = options
  const [isPaused, setIsPaused] = useState(false)
  const callbackRef = useRef(callback)
  const intervalRef = useRef(null)
  const retryCountRef = useRef(0)

  useEffect(() => { callbackRef.current = callback }, [callback])

  useEffect(() => {
    if (!pauseOnHidden) return
    const onVis = () => setIsPaused(document.hidden)
    document.addEventListener('visibilitychange', onVis)
    return () => document.removeEventListener('visibilitychange', onVis)
  }, [pauseOnHidden])

  const poll = useCallback(async () => {
    try { await callbackRef.current(); retryCountRef.current = 0 }
    catch (err) {
      if (++retryCountRef.current >= maxRetries) stop()
    }
  }, [maxRetries])

  const start = useCallback(() => {
    if (intervalRef.current) return
    intervalRef.current = setInterval(() => { if (!isPaused) poll() }, interval)
  }, [interval, poll, isPaused])

  const stop = useCallback(() => {
    if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null }
  }, [])

  useEffect(() => {
    if (enabled) start(); else stop()
    return () => stop()
  }, [enabled, start, stop])

  return { start, stop, isPaused }
}
```

**调用方式（Usage）** —— 重写 `App.jsx` 预警轮询

```js
const checkAlerts = useCallback(async () => {
  const params = lastAlertCheckRef.current ? { since: lastAlertCheckRef.current } : {}
  const items = (await alertApi.getRecent(params)) || []
  if (items.length > 0) { /* notification.warning(...) */ }
  lastAlertCheckRef.current = new Date().toISOString()
}, [])   // 依赖稳定，不再重建定时器

usePolling(checkAlerts, 30000)
```

---

### Diff 3　后端｜提取同步起始日期公共函数，消除逐行重复

**痛点**：`get_stock_sync_start_date` 与 `get_sector_sync_start_date` 逻辑完全相同（查最新、判 `is_final`、算下一天），仅集合与键名不同，共约 60 行重复。

**修改前（Before）** —— `app/data/db.py:383-456`

```python
def get_stock_sync_start_date(stock_code: str) -> Optional[str]:
    coll = get_collection('stock')
    latest = coll.find_one({'stock_code': stock_code}, sort=[('trade_date', -1)],
                           projection={'trade_date': 1, 'is_final': 1, '_id': 0})
    if not latest: return None
    if latest.get('is_final', False):
        try:
            dt_obj = dt.strptime(latest['trade_date'], '%Y%m%d')
            return (dt_obj + timedelta(days=1)).strftime('%Y%m%d')
        except Exception: return None
    return latest['trade_date']

def get_sector_sync_start_date(sector_code: str) -> Optional[str]:
    # ...完全相同的逻辑，仅 coll=get_collection('sector')...
```

**封装后（After）**

```python
def _get_sync_start_date(data_type: str, code: str) -> Optional[str]:
    """查询某类型标的最新同步起始日（stock/sector/index/etf 通用）。"""
    coll = get_collection(data_type)
    latest = coll.find_one({'stock_code': code}, sort=[('trade_date', -1)],
                           projection={'trade_date': 1, 'is_final': 1, '_id': 0})
    if not latest:
        return None
    if latest.get('is_final', False):
        try:
            return (datetime.strptime(latest['trade_date'], '%Y%m%d')
                    + timedelta(days=1)).strftime('%Y%m%d')
        except ValueError:
            return None
    return latest['trade_date']


def get_stock_sync_start_date(stock_code: str) -> Optional[str]:
    return _get_sync_start_date('stock', stock_code)

def get_sector_sync_start_date(sector_code: str) -> Optional[str]:
    return _get_sync_start_date('sector', sector_code)
```

**调用方式（Usage）**：既有调用点 `get_stock_sync_start_date(code)` / `get_sector_sync_start_date(code)` 签名不变，无需改动上游。

---

### Diff 4　后端｜全局异常处理器：结构化响应 + 生产脱敏

**痛点**：`main.py` 的全局处理器把 `str(exc)` 直接放进响应 `detail`，向客户端泄露内部实现与堆栈片段。

**修改前（Before）** —— `app/server/main.py:119-130`

```python
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"未处理的异常: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={
        "code": 500, "message": "服务器内部错误", "detail": str(exc)  # 泄露内部信息
    })
```

**封装后（After）**

```python
from fastapi.exceptions import RequestValidationError
from app.server.config import get_settings

@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    """参数校验错误 → 422，回传可读的字段错误（不泄露内部信息）"""
    return JSONResponse(status_code=422, content={
        "code": 422, "message": "参数校验失败", "detail": exc.errors()
    })

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("未处理的异常", exc_info=True)   # 堆栈只进日志
    detail = str(exc) if get_settings().DEBUG else "服务器内部错误"
    return JSONResponse(status_code=500, content={
        "code": 500, "message": "服务器内部错误", "detail": detail
    })
```

> 配套：`config.py` 增加 `DEBUG: bool = Field(default=False)`；统一 `{code, message, detail}` 三件套，前端拦截器可只解析 `detail` 作为 toast 文案。

---

### Diff 5　后端｜把 `watchlist` 路由的直连 `get_db()` 收口到 Repository

**痛点**：项目已建好 `repositories/` 层但路由层仍在 146 处直连 `db['xxx']`，`watchlist.py` 即典型——业务路由内既有集合访问又有解析逻辑，违反 SRP 且无法复用。

**修改前（Before）** —— `app/server/api/watchlist.py:25-46`

```python
def _resolve(entry: dict) -> WatchlistItem:
    code = entry['code']
    typ = entry.get('type', 'etf')
    if typ == 'etf':
        basic = get_db()['etf_basics'].find_one({'code': code}, {'_id': 0, 'name': 1})
        name = basic['name'] if basic else code
        coll = get_collection('etf')
    else:
        basic = get_db()['stock_basics'].find_one({'stock_code': code}, {'_id': 0, 'stock_name': 1})
        name = basic['stock_name'] if basic else code
        coll = get_collection('stock')
    latest = coll.find_one({'stock_code': code, 'close': {'$gt': 0}}, ...)
    ...
```

**封装后（After）** —— 新增 `app/server/repositories/watchlist_repository.py`

```python
class WatchlistRepository(BaseRepository):
    def __init__(self):
        super().__init__('watchlist')
        self._quote_fields = { ... _QUOTE_FIELDS ... }

    def list_entries(self):
        return list(self.collection.find({}, {'_id': 0}).sort('created_at', 1))

    def resolve_quote(self, entry: dict) -> dict:
        """按类型取基础信息 + 最新行情（封装 etf_basics/stock_basics/daily 三集合访问）"""
        code, typ = entry['code'], entry.get('type', 'etf')
        coll_name, key, name_key = ('etf', 'code', 'name') if typ == 'etf' else ('stock', 'stock_code', 'stock_name')
        basic = get_db()[f'{coll_name}_basics'].find_one({key: code}, {'_id': 0, name_key: 1})
        latest = get_collection(coll_name).find_one(
            {'stock_code': code, 'close': {'$gt': 0}},
            sort=[('trade_date', -1)], projection=self._quote_fields)
        return {'code': code, 'name': (basic or {}).get(name_key, code), 'type': typ, **latest}
```

**调用方式（Usage）** —— 路由层只剩编排

```python
@router.get("", response_model=WatchlistResponse)
def get_watchlist(keyword: Optional[str] = Query(None), ...):
    repo = get_watchlist_repo()
    items = [WatchlistItem(**repo.resolve_quote(e)) for e in repo.list_entries()]
    # ...筛选/排序逻辑可进一步下沉到 repo.query()
    return WatchlistResponse(total=len(items), data=items)
```

---

## 附：执行顺序建议

1. **第一批（止血，1~2 个迭代）**：P0 全部 —— 异常脱敏、`usePolling`/`useTaskPolling` 两个 Bug、删除 `sync_service`/`market_service` 假实现、`App.jsx` 轮询改造。
2. **第二批（消重，2~3 个迭代）**：P1 全部 —— API 命名空间收敛、轮询统一、`db.py` 公共函数、`print→logging`、清理调试残留。
3. **第三批（架构，持续演进）**：P2 —— 按域补 Repository 并逐步把 146 处 `db['xxx']` 收口、拆分巨型控制器、pydantic v2 迁移、图库收敛与 react-query 二选一、`bulk_write` 与常量集中。

> 验证基线：每次改动后跑 `pnpm build`（前端）与后端既有脚本回归（`tests/`、`scripts/`），并以 `count_documents`/`distinct` 复核涉 `trade_date` 的 `$lte/$gte` 查询（`YYYYMMDD` 定宽串字典序等价日期序，但需确认写入侧零填充）。
