# Phase 1: 关键识别 - 核心功能列表

**分析日期**: 2026-07-22

---

## 1. 核心功能列表

### 功能 1: 一键更新
- **用户故事**: 用户点击"一键更新"按钮，自动完成数据同步、RPS计算、PE更新、预计算
- **入口**: `app/client/src/App.jsx:65` (handleOneClickUpdate)
- **涉及模块**:
  - 前端: App.jsx → api.js → one_click_update API
  - 后端: one_click_update.py → factor_service → data_manager → factor_engine
- **复杂度**: 高
- **调用链**: 
  ```
  App.handleOneClickUpdate() 
  → oneClickUpdateApi.start()
  → one_click_update._run_update_task()
  → factor_service._run_sync_indices()
  → data_manager.sync_daily_data()
  → factor_engine.calculate_rps()
  → _run_precompute_base_for_date()
  ```

### 功能 2: 日历复盘
- **用户故事**: 用户查看日历视图，查看每日市场概况、周总结、月总结
- **入口**: `app/client/src/pages/CalendarReview.jsx`
- **涉及模块**:
  - 前端: CalendarReview.jsx, ReviewDetail.jsx
  - 后端: calendar.py, market_review.py
- **复杂度**: 高
- **调用链**:
  ```
  CalendarReview → calendarApi.getDailySummary()
  → calendar.generate_calendar_snapshot()
  → db.base_data_daily / db.market_daily
  ```

### 功能 3: 市场分析
- **用户故事**: 用户查看市场信号、板块轮动、活跃池
- **入口**: `app/client/src/pages/MarketAnalysis.jsx`
- **涉及模块**:
  - 前端: MarketAnalysis.jsx, MarketSignals.jsx, MarketOverview.jsx
  - 后端: market_analysis.py, market_review.py
- **复杂度**: 中
- **调用链**:
  ```
  MarketAnalysis → marketAnalysisApi.getAnalysis()
  → market_analysis.generate_market_signals()
  → db.stock_daily / db.sector_daily
  ```

### 功能 4: 个股分析
- **用户故事**: 用户搜索个股，查看K线、RPS、指标
- **入口**: `app/client/src/pages/StockAnalysis.jsx`
- **涉及模块**:
  - 前端: StockAnalysis.jsx, TradingViewChart.jsx
  - 后端: stocks.py, factors.py
- **复杂度**: 中
- **调用链**:
  ```
  StockAnalysis → stockApi.getStockDetail()
  → stocks.get_stock_detail()
  → db.stock_daily
  ```

### 功能 5: 数据同步
- **用户故事**: 用户手动触发个股/板块数据同步
- **入口**: `app/client/src/pages/Settings.jsx`
- **涉及模块**:
  - 前端: Settings.jsx, ManagementDialog.jsx
  - 后端: sync.py, one_click_update.py
- **复杂度**: 中
- **调用链**:
  ```
  Settings → syncApi.syncAllDaily()
  → sync._run_sync_task()
  → data_manager.sync_daily_data()
  ```

### 功能 6: 按日期重算
- **用户故事**: 用户指定日期重新计算 RPS 和预计算数据
- **入口**: `app/client/src/pages/ReviewDetail.jsx`
- **涉及模块**:
  - 前端: ReviewDetail.jsx
  - 后端: one_click_update.py
- **复杂度**: 中
- **调用链**:
  ```
  ReviewDetail → oneClickUpdateApi.recalculateDate()
  → one_click_update._run_recalc_task()
  → factor_engine.calculate_rps()
  ```

---

## 2. 高频代码识别

### 最常被引用的模块
| 模块 | 引用次数 | 说明 |
|------|---------|------|
| app.data.db.get_db | 142次 | 数据库连接，分散在所有路由文件 |
| threading.Thread | 23次 | 后台任务启动 |
| threading.Lock | 6次 | 线程锁 |
| console.error | 40+次 | 前端错误日志 |

---

## 3. 关键路径追踪

### 一键更新完整调用链
```
[前端]
App.jsx:65 handleOneClickUpdate()
  → api.js:174 oneClickUpdateApi.start()
  → POST /api/one-click-update/start

[后端]
one_click_update.py:239 start_update()
  → tm.create_task_with_steps()
  → threading.Thread(_run_update_task)

one_click_update.py:59 _run_update_task()
  → Step 1: factor_service._run_sync_indices()     # 同步指数
  → Step 2: sync._run_sync_task()                   # 同步个股
  → Step 3: data_manager.sync_sector_indices()       # 同步板块
  → Step 4: factor_engine.calculate_rps('stock')     # 个股RPS
  → Step 5: factor_engine.calculate_rps('sector')    # 板块RPS
  → Step 6: factors._run_sync_pe()                   # PE同步
  → Step 7: factors._run_precompute_base_for_date()  # 预计算
```

---

## 4. Phase 1 输出

**关键识别完成**。6个核心功能已识别，其中：
- 一键更新和日历复盘复杂度最高
- get_db() 是最高频调用（142次）
- threading.Thread 是主要的任务启动方式（23次）
