# 模块分析: 日历复盘（calendar.py）

**文件**: `app/server/api/calendar.py` (1584行)
**路由数**: 15 | **函数数**: 20+

---

## 基本信息
- 入口: `router = APIRouter(prefix="/api/calendar")`
- 调用链: 路由 → 直接函数调用 → `get_db()`
- 架构状态: ⚠️ 完全未使用新架构

---

## Vibe Coding 问题检测

### 1. 架构违规
- **17 处 `get_db()` 直接调用** - 分散在多个函数中
- `generate_calendar_snapshot()` 函数内访问 4 个不同集合（base_data_daily, market_daily, sector_basics, sector_daily, index_daily, stock_daily）
- 本应使用 CalendarRepository + MarketRepository

### 2. 职责混乱
| 函数类别 | 函数 | 应归属 |
|----------|------|--------|
| 日历快照 | `generate_calendar_snapshot()` | CalendarService |
| 日历快照 | `save_calendar_snapshot()` | CalendarService |
| 周总结 | `_get_month_weeks()` | CalendarService |
| 周总结 | `_build_weekly_input_text()` | CalendarService |
| 月总结 | `_build_monthly_input_text()` | CalendarService |
| 后台任务 | `_run_fill_ai_task()` | 应在 orchestrator |
| 路由端点 | 15个路由函数 | api/calendar.py |

### 3. 重复实现
- `_build_weekly_input_text()` 和 `_build_monthly_input_text()` 逻辑高度相似
- 周总结和月总结的错误处理模式重复

### 4. 错误处理
- 23 处 `except Exception` - 裸异常捕获
- 部分函数返回 None 而不是抛异常

### 5. 代码质量问题
- `generate_calendar_snapshot()` 函数过长（~100行），职责过多
- 同时访问 6 个不同的 MongoDB 集合

---

## 拆分方案

| 新文件 | 职责 | 预估行数 |
|--------|------|----------|
| `api/calendar.py` | 瘦路由（15个端点） | ~200 |
| `services/calendar_snapshot.py` | 日历快照生成 | ~300 |
| `services/calendar_summary.py` | 周/月总结生成 | ~500 |
| `services/calendar_recalc.py` | 重算逻辑 | ~300 |

---

## 重构任务
| 编号 | 任务 | 优先级 |
|------|------|--------|
| M-CAL-01 | 拆分 calendar.py 为 4 个文件 | P0 |
| M-CAL-02 | 17处 get_db() 替换为 CalendarRepository | P0 |
| M-CAL-03 | 合并周/月总结构建逻辑 | P1 |
| M-CAL-04 | 统一异常处理 | P1 |