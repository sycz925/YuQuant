# calendar 域收口里程碑（48 处直连）

日期：2026-08-16

- **[负责代理]**：BackendAgent
- **[可用技能]**：@skills/vibecoding-refactor、@skills/VibeSec-Skill、@skills/autoproject

## 背景

`app/server/api/calendar.py`（1325 行）是最大的「巨型控制器」，有 **48 处 `db[...]` 直连**，路由内夹带周/月总结缓存读写、快照生成、AI 补全、重算编排等大量业务逻辑。

主要直连函数（以 grep 核实）：

| 函数 | 直连点 |
| :--- | :--- |
| `get_daily_summary` / `get_week_status` | `base_data_daily`、`market_daily`、`sector_daily`、`index_daily` 多集合 |
| `get_weekly_summary` / `get_monthly_summary` | `weekly_summary`/`monthly_summary` 缓存 + 后台任务 |
| `recalculate_month` / `fill_ai_analysis` | `sync_tasks` 任务 + 聚合 |
| `get_running_tasks` / `get_task_status` | `sync_tasks` |

## 进度追踪（2026-08-16 更新）

已完成（48 → 0 处）：
- ✅ 任务状态/最新交易日/交易日（`get_latest_trade_date_api`/`get_task_status`/`get_running_tasks`/`get_trading_days`）
- ✅ 周/月总结缓存（修正 `SummaryRepository` key 格式为 dict，复用 `get_weekly_summary_repo`/`get_monthly_summary_repo`）
- ✅ AI 补全任务检查（`fill_ai_analysis_api`）
- ✅ 快照生成（`generate_calendar_snapshot` / `generate_month_snapshots` / `save_calendar_snapshot`，约 9 处）→ 下沉 `calendar_service.py`
- ✅ 快照清理（`clear_snapshots_api`，1 处）→ 下沉为 `clear_calendar_snapshots`
- ✅ 每日总结（`get_calendar_daily_summary`，约 8 处）→ 下沉为 `get_calendar_daily_summary`，路由薄化

> 核心「读多集合 → 组装快照/总结」已下沉 `calendar_service.py`，api 层 `db[...]`/`get_db` 直连清零（18 处）。

## 前置检查（已补表征测试）

在 `tests/` 下新增（`unittest.mock`）：

1. ✅ `tests/test_calendar_service.py`：锁定 `generate_calendar_snapshot`（8 字段）+ `/calendar/daily-summary` 返回结构（顶层 5 键 / 每日条目 16 字段），5 条全绿。
2. `tests/test_calendar_week_status.py`：锁定 `/calendar/week-status` 返回结构（本里程碑未涉及，沿用既有契约）。
3. `tests/test_calendar_task_status.py`：锁定 `/calendar/task/{id}` 返回结构（本里程碑未涉及，沿用既有契约）。

## 执行步骤

### 1. 数据访问下移（建 `CalendarRepository` / 复用 `SummaryRepository`）—— 已完成

- 周/月总结缓存：复用已有的 `WeeklySummaryRepository` / `MonthlySummaryRepository`（`repositories/summary_repository.py`）。
- 基础数据/快照：新建 `CalendarRepository`（`repositories/calendar_repository.py`）封装 `base_data_daily`、`market_daily`、`index_daily`、`stock_daily`、`sector_basics`、`sector_daily`、`index_basics` 的查询。
- 任务：复用 `TaskRepository`。

> `calendar_service.py` 全程零 `db[...]`/`get_db` 直连：快照生成/清理/每日总结 + 周/月总结输入构建（`_build_weekly_input_text`/`_build_monthly_input_text`）+ AI 补全任务（`_run_fill_ai_task`）均已通过 `CalendarRepository`。

### 2. 业务逻辑下沉（拆 `services/calendar_service.py`）—— 已完成

`app/server/services/calendar_service.py` 已把路由里的快照生成、快照清理、每日总结组装下沉到 service，路由只做「参数解析 → 调 service → 组装响应」。api 层 `db[...]`/`get_db` 直连清零（18 处），service 层 `db[...]`/`get_db` 直连清零。

## 验证

- 后端测试全绿（`python -m unittest discover -s tests` → 50 测试 OK，含新增 `tests/test_calendar_service.py` 5 条表征测试）。
- 手动：curl 日历各接口，与重构前返回一致（快照/每日总结返回结构未变）。

## 明确不做（YAGNI）

- 不动 `market_review`/`factors`（独立里程碑）。
- 不改前端（返回结构不变）。
- 不在本里程碑内拆分前端页面。
