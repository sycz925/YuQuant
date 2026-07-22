# Phase 3: 模块层分析报告

**分析日期**: 2026-07-22

---

## 分析覆盖

| 功能 | 分析状态 | 问题数 | 报告位置 |
|------|----------|--------|----------|
| 一键更新 | ✅ 完成 | 4 | modules/one-click-update.md |
| 日历复盘 | ✅ 完成 | 5 | modules/calendar-review.md |
| 数据同步 | ✅ 完成 | 3 | modules/data-sync.md |
| 市场分析 | ⏳ 待分析 | - | - |
| 个股分析 | ⏳ 待分析 | - | - |
| 按日期重算 | ⏳ 待分析 | - | - |

---

## 问题汇总（按类型）

### 资源未复用 (P1)

| 模块 | 问题 | 位置 | 应使用 |
|------|------|------|--------|
| 一键更新 | 逻辑内联，未抽取 hook | App.jsx:65-166 | useOneClickUpdate |
| 日历复盘 | 轮询逻辑重复 3 次 | CalendarReview, ReviewDetail | usePolling |
| 日历复盘 | 截图功能重复 2 次 | CalendarReview, ReviewDetail | useScreenshot |
| 数据同步 | 启用代码查询重复 | sync.py, one_click_update.py | stock_repository |

**统计**: 前端自定义 hooks 使用率 0%，后端 repository 使用率 0%

### 架构违规 (P0)

| 模块 | 问题 | 位置 | 建议 |
|------|------|------|------|
| 全局 | 142 次 get_db() 直接调用 | 所有路由文件 | 建立 repository 层 |
| 一键更新 | _run_update_task 在路由层 | one_click_update.py:59 | 迁移到 service 层 |
| 日历复盘 | 30+ 次 get_db() 直接调用 | calendar.py | 使用 repository 层 |
| 数据同步 | _run_sync_task 在路由层 | sync.py:111 | 迁移到 service 层 |

### 重复实现 (P1)

| 功能 | 重复位置 | 建议 |
|------|----------|------|
| 步骤执行模式 | one_click_update.py 7 次 | 抽取通用步骤执行器 |
| 任务启动模式 | calendar.py 4 次 | 抽取通用任务启动函数 |
| 轮询逻辑 | 前端 3 处 | 统一到 useTaskPolling |

### 代码过大 (P1)

| 文件 | 行数 | 建议 |
|------|------|------|
| market_review.py | 3115 | 拆分为多个路由文件 |
| factors.py | 1915 | 按业务域拆分 |
| calendar.py | 1546 | 拆分为多个路由文件 |
| factor_service.py | 1295 | 拆分为多个 service |
| CalendarReview.jsx | 1312 | 拆分为多个子组件 |
| Settings.jsx | 837 | 拆分为多个子组件 |

---

## 模块层重构任务

### 架构层任务 (优先)
- [A-001] 建立 repository 层，封装 142 处 get_db() 调用
- [A-002] 拆分过大路由文件（market_review, factors, calendar）
- [A-003] 建立工厂层，按数据域内聚
- [A-004] 建立编排层，统一任务启动方式

### 资源复用迁移
- [M-001] 抽取 useOneClickUpdate hook
- [M-005] 抽取 usePolling hook（支持页面隐藏暂停）
- [M-006] 抽取 useTaskPolling hook
- [M-007] 抽取 useScreenshot hook
- [M-011] 建立 stock_repository

### 合并重复实现
- [M-002] 抽取通用步骤执行器
- [M-003] 业务逻辑迁移到工厂层/编排层

### 代码拆分
- [M-009] 拆分 CalendarReview.jsx 为多个子组件
- [M-012] 拆分 Settings.jsx 为多个子组件
