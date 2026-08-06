# Phase 3: 模块层分析报告

**分析日期**: 2026-07-25（重新全量分析）

---

## 分析覆盖

| 功能 | 分析状态 | 问题数 | 报告位置 |
|------|----------|--------|----------|
| 日历复盘（calendar.py） | ✅ 完成 | 6 | modules/calendar-review.md |
| 市场复盘（market_review.py） | ✅ 完成 | 7 | modules/market-review.md |
| 因子管理（factors.py） | ✅ 完成 | 5 | modules/factors.md |
| 一键更新（one_click_update_v2.py） | ✅ 完成 | 1 | modules/one-click-update.md |
| DeepSeek AI 分析 | ✅ 完成 | 3 | modules/deepseek-analyst.md |
| 前端日历复盘（CalendarReview.jsx） | ✅ 完成 | 4 | modules/frontend-calendar.md |

---

## 问题汇总（按类型）

### 架构违规 - 沿用旧架构 (P0)

| 模块 | 问题 | 位置 | 建议 |
|------|------|------|------|
| calendar.py | 全部函数直接 `get_db()`，共17处 | 全文件 | 迁移到 CalendarService → repository |
| market_review.py | 全部函数直接 `get_db()`，共28处 | 全文件 | 迁移到 MarketService → repository |
| market_review.py | 40+ 个函数混在路由文件中 | 全文件 | 拆分到 services/market_data.py |
| factors.py | 混合使用 factory 和 get_db()，共13处 | 全文件 | 统一使用 factory |
| deepseek_analyst.py | 类定义在 api/ 层，6处 get_db() | 全文件 | 迁移到 services/ |
| stocks.py | 3处 get_db() | 全文件 | 迁移到 StockRepository |

**统计**: 6个模块中，仅 2 个（one_click_update_v2.py, settings_tasks.py）已迁移到新架构

### 代码过大 (P1)

| 文件 | 行数 | 函数数 | 路由数 | 建议 |
|------|------|--------|--------|------|
| market_review.py | 3095 | 40+ | 10 | 拆分为 market_data + market_signals + market_ai + 路由 |
| calendar.py | 1584 | 20+ | 15 | 拆分为 calendar_snapshot + calendar_summary + calendar_recalc + 路由 |
| factors.py | 1428 | 30+ | 20 | 拆分 CR5/指数/板块/RPS/对比 到独立工厂 |
| CalendarReview.jsx | 1331 | - | - | 拆分为子组件 |
| deepseek_analyst.py | 654 | 10+ | 0 | 迁移到 services/，拆分 prompt 和逻辑 |

### 错误处理不统一 (P1)

| 模块 | 问题 | 数量 |
|------|------|------|
| calendar.py | `except Exception` | 23 |
| market_review.py | `except Exception` | 34 |
| factors.py | `except Exception` | 37 |
| deepseek_analyst.py | `except Exception` | 6 |

### 日志不统一 (P2)

| 模块 | 问题 |
|------|------|
| 前端 20个文件 | 55处 `console.log/error/warn`，无统一日志工具 |

### 资源复用问题 (P1)

| 模块 | 问题 | 应使用 |
|------|------|--------|
| CalendarReview.jsx | 内联截图逻辑（toPng） | useScreenshot hook |
| CalendarReview.jsx | 内联任务轮询 | useTaskPolling hook |
| Settings.jsx | 内联管理逻辑 | 拆分子组件 |

---

## 模块层重构任务

### 架构层（优先 - P0）
- **[A-001]** API 层 get_db() 迁移到 repository：calendar.py(17) + market_review.py(28) + factors.py(13) + deepseek_analyst.py(6) + stocks.py(3) + 其他(5)
- **[A-002]** 拆分 market_review.py (3095行) → 4个文件
- **[A-003]** 拆分 calendar.py (1584行) → 4个文件
- **[A-004]** 拆分 factors.py (1428行) → 部分迁移到工厂

### 代码整理（P1）
- **[M-001]** deepseek_analyst.py 迁移到 services/，拆分 SYSTEM_PROMPT
- **[M-002]** 拆分 CalendarReview.jsx (1331行) → 子组件
- **[M-003]** 拆分 Settings.jsx (657行) → 子组件
- **[M-004]** 统一后端异常处理模式
- **[M-005]** 清理 scripts 目录一次性脚本

### 长期改进（P2）
- **[M-006]** 前端统一日志方案
- **[M-007]** 前端引入 TypeScript
- **[M-008]** 添加后端测试覆盖