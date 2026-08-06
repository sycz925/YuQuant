# Phase 1: 关键识别 - 核心功能列表

**分析日期**: 2026-07-25（重新全量分析）

---

## 1. 核心功能列表

### 功能 1: 一键更新
- **用户故事**: 用户点击"一键更新"按钮，自动完成数据同步、RPS计算、PE更新、预计算
- **入口**: `app/client/src/hooks/useOneClickUpdate.js` | `app/server/api/one_click_update_v2.py:16`
- **涉及模块**:
  - 前端: useOneClickUpdate hook → api.js → one_click_update API
  - 后端: one_click_update_v2.py → OneClickUpdateOrchestrator → IndexFactory/StockFactory/SectorFactory → repositories
- **复杂度**: 高
- **调用链**: 
  ```
  useOneClickUpdate.handleStart()
  → oneClickUpdateApi.start()
  → POST /api/one-click-update/start
  → OneClickUpdateOrchestrator.execute()
  → IndexFactory.sync_kline() → StockFactory.sync_kline() → ...
  → task_repo.update_progress()
  ```
- **架构状态**: ✅ 已迁移到 Orchestrator 编排层

### 功能 2: 日历复盘
- **用户故事**: 用户查看日历视图，查看每日市场概况、周总结、月总结
- **入口**: `app/client/src/pages/CalendarReview.jsx`
- **涉及模块**:
  - 前端: CalendarReview.jsx (1331行), ReviewDetail.jsx (387行)
  - 后端: calendar.py (1584行), market_review.py (3095行)
- **复杂度**: 高
- **调用链**:
  ```
  CalendarReview → calendarApi.getDailySummary()
  → calendar.get_calendar_daily_summary()
  → db.base_data_daily / db.market_daily (直接 get_db())
  ```
- **架构状态**: ⚠️ calendar.py 仍有 17 处 get_db() 直接调用

### 功能 3: 市场分析
- **用户故事**: 用户查看市场信号、板块轮动、活跃池
- **入口**: `app/client/src/pages/MarketAnalysis.jsx` (526行)
- **涉及模块**:
  - 前端: MarketAnalysis.jsx, MarketSignals.jsx (598行), MarketOverview.jsx (163行)
  - 后端: market_analysis.py (498行), market_review.py (3095行)
- **复杂度**: 中
- **调用链**:
  ```
  MarketAnalysis → marketAnalysisApi.getAnalysis()
  → market_analysis.get_analysis()
  → market_review.calc_market_signals() → get_db()
  ```
- **架构状态**: ⚠️ 直接调用 market_review 中的函数，未通过 repository

### 功能 4: 个股分析
- **用户故事**: 用户搜索个股，查看K线、RPS、指标
- **入口**: `app/client/src/pages/StockAnalysis.jsx` (632行)
- **涉及模块**:
  - 前端: StockAnalysis.jsx, TradingViewChart.jsx (679行)
  - 后端: stocks.py (304行), factors.py (1428行)
- **复杂度**: 中
- **调用链**:
  ```
  StockAnalysis → stockApi.getStockDetail()
  → stocks.get_stock_detail() → get_db()
  → stockApi.getDailyData() → stocks.get_daily_data() → get_db()
  ```
- **架构状态**: ⚠️ stocks.py 仍有 3 处 get_db()

### 功能 5: 数据同步
- **用户故事**: 用户手动触发个股/板块数据同步
- **入口**: `app/client/src/pages/Settings.jsx` (657行)
- **涉及模块**:
  - 前端: Settings.jsx, ManagementDialog.jsx (280行)
  - 后端: sync.py (335行), settings_tasks.py (148行), SettingsOrchestrator (196行)
- **复杂度**: 中
- **调用链**:
  ```
  Settings → syncApi.syncAllDaily()
  → settings_tasks.sync_daily() → SettingsOrchestrator
  → StockFactory.sync_kline() → StockRepository
  ```
- **架构状态**: ⚠️ 部分已迁移到 SettingsOrchestrator，但 sync.py 仍有直接调用

### 功能 6: 按日期重算
- **用户故事**: 用户指定日期重新计算 RPS 和预计算数据
- **入口**: `app/client/src/pages/ReviewDetail.jsx` (387行)
- **涉及模块**:
  - 前端: ReviewDetail.jsx
  - 后端: one_click_update_v2.py (64行), DailyRecalcOrchestrator
- **复杂度**: 中
- **调用链**:
  ```
  ReviewDetail → oneClickUpdateApi.recalculateDate()
  → POST /api/one-click-update/recalculate-date
  → DailyRecalcOrchestrator.execute(target_date)
  → StockFactory.calculate_rps() → MarketAggregator.precompute()
  ```
- **架构状态**: ✅ 已迁移到 Orchestrator 编排层

---

## 2. 高频代码识别

### 最常被引用的模块
| 模块 | 引用次数 | 说明 |
|------|---------|------|
| `app.data.db.get_db` | 104次 | 数据库连接，分散在 API 层(72)和新架构层(32) |
| `threading.Thread` | 9次 | 后台任务启动（从23次减少） |
| `logging.getLogger` | 全局 | Python 日志 |
| `console.error/log` | 55次 | 前端错误日志 |
| `useState/useEffect` | 271次 | React hooks |

### 高频 API 端点
| 端点 | 文件 | 调用频率 |
|------|------|----------|
| `/calendar/daily-summary` | calendar.py | 高 |
| `/market-review/overview` | market_review.py | 高 |
| `/market-review/signals` | market_review.py | 高 |
| `/one-click-update/start` | one_click_update_v2.py | 中 |
| `/stocks/{code}` | stocks.py | 中 |

---

## 3. 关键路径追踪

### 一键更新（已重构）
```
[前端]
useOneClickUpdate.handleStart()
  → oneClickUpdateApi.start()
  → POST /api/one-click-update/start

[后端 - 新架构]
one_click_update_v2.py:16 start_update()
  → check_sync_time()
  → OneClickUpdateOrchestrator.execute()
  → ThreadPoolExecutor (在 BaseOrchestrator 中)
  → IndexFactory.sync_kline()
  → StockFactory.sync_kline()
  → SectorFactory.sync_sectors()
  → StockFactory.calculate_rps()
  → SectorFactory.calculate_rps()
  → IndexFactory.sync_pe()
  → MarketAggregator.precompute_base()
  → TaskRepository.update_progress()
```

### 日历复盘（未重构）
```
[前端]
CalendarReview.jsx → calendarApi.getDailySummary()
  → GET /api/calendar/daily-summary?year=&month=

[后端 - 旧架构]
calendar.py:134 get_calendar_daily_summary()
  → get_db() → base_data_daily.find()
  → get_db() → market_daily.find()
  → generate_calendar_snapshot() → get_db() × N
  → save_calendar_snapshot() → get_db()
```

---

## 4. Phase 1 输出

**关键识别完成**。6个核心功能中：
- **一键更新** ✅ 已重构为四层架构
- **按日期重算** ✅ 已重构为四层架构
- **日历复盘** ⚠️ 仍使用旧架构，大量 get_db()
- **市场分析** ⚠️ 仍使用旧架构
- **个股分析** ⚠️ 仍使用旧架构
- **数据同步** ⚠️ 部分重构