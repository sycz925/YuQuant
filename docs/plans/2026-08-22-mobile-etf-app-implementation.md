# Mobile ETF App Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a standalone Flutter mobile app for A-share ETF quantitative analysis with pure Dart pytdx protocol implementation, SQLite local storage, and dark/light theme toggle.

**Architecture:** Simple layered architecture under lib/ with data/services/screens/widgets separation. Data flows from pytdx socket -> SQLite -> UI. Sync via 4-step dialog.

**Tech Stack:** Flutter, Dart, sqflite, provider, k_chart_widget, shared_preferences

---

## Task 1: Flutter Project Scaffolding

**Files:**
- Create: app/mobile/ (Flutter project root)
- Create: app/mobile/pubspec.yaml
- Create: app/mobile/lib/main.dart
- Create: app/mobile/lib/app.dart
- Create: app/mobile/lib/config/theme.dart

**Step 1:** Create Flutter project


**Step 2:** Update pubspec.yaml with dependencies: sqflite ^2.3.0, provider ^6.0.0, k_chart_widget ^3.0.0, path ^1.8.0, shared_preferences ^2.2.0

**Step 3:** Create theme.dart - dark theme (primary=#1E1E2E, surface=#2A2A3E, accent=#7C3AED, rise=#EF4444, fall=#22C55E) + light theme (primary=#F8FAFC, surface=#FFFFFF, textPrimary=#1E293B, textSecondary=#64748B) + AppTheme class with getTheme(mode) method

**Step 4:** Create app.dart - MaterialApp with themeMode switching support

**Step 5:** Update main.dart - runApp

**Step 6:** Verify: flutter pub get && flutter build apk --debug

**Step 7:** Commit: feat(mobile): scaffold Flutter project with dark theme

---

## Task 2: Data Models

**Files:**
- Create: app/mobile/lib/models/etf_basic.dart
- Create: app/mobile/lib/models/daily_bar.dart
- Create: app/mobile/lib/models/index_basic.dart
- Create: app/mobile/lib/models/etf_alert.dart
- Create: app/mobile/lib/models/watchlist_item.dart

Each model has fromMap/toMap constructors matching MongoDB field names exactly.

**Step 1:** Create all 5 model files
**Step 2:** Verify: flutter analyze
**Step 3:** Commit: feat(mobile): add data models aligned with MongoDB schema

---

## Task 3: SQLite Database Layer

**Files:**
- Create: app/mobile/lib/services/database.dart

**Step 1:** Implement DatabaseHelper singleton with 7 CREATE TABLE statements

**Step 2:** Implement CRUD: bulkUpsertEtfBasics, getEtfBasics, upsertDailyBars, getDailyBars, getLatestDailyBar, upsertIndexBasics, getIndexBasics, addWatchlist, removeWatchlist, getWatchlist, upsertAlerts, getAlerts, getSyncTask, upsertSyncTask

**Step 3:** Verify: flutter analyze
**Step 4:** Commit: feat(mobile): implement SQLite database layer

---

## Task 4: pytdx Protocol - Binary Protocol

**Files:**
- Create: app/mobile/lib/services/pytdx/protocol.dart

**Step 1:** Implement TdxPacket class (header + body serialization)
**Step 2:** Implement request builders: makeLoginRequest, makeSecurityListRequest, makeSecurityQuotesRequest, makeSecurityBarsRequest, makeXdXrInfoRequest
**Step 3:** Implement response parsers: parseHeader, parseSecurityList, parseSecurityQuotes, parseSecurityBars, parseXdXrInfo
**Step 4:** Verify: flutter analyze
**Step 5:** Commit: feat(mobile): implement pytdx binary protocol

---

## Task 5: pytdx Protocol - Data Parser

**Files:**
- Create: app/mobile/lib/services/pytdx/parser.dart

**Step 1:** Implement TdxParser: parseStockList, parseQuotes, parseKlineBars, parseXdXrEvents
**Step 2:** Handle fixed-point integer to double conversion
**Step 3:** Handle date format YYYYMMDD int to string
**Step 4:** Verify: flutter analyze
**Step 5:** Commit: feat(mobile): implement pytdx data parser

---

## Task 6: pytdx Protocol - Server List & Connection Pool

**Files:**
- Create: app/mobile/lib/services/pytdx/servers.dart
- Create: app/mobile/lib/services/pytdx/client.dart

**Step 1:** Create servers.dart with 6 TDX server IPs
**Step 2:** Implement TdxClient: connect, disconnect, reconnect
**Step 3:** Implement connection pool (max 8, round-robin)
**Step 4:** Implement auto-retry with server failover
**Step 5:** Implement 5s timeout per request
**Step 6:** Add public methods: getSecurityList, getSecurityQuotes, getSecurityBars, getXdXrInfo
**Step 7:** Verify: flutter analyze
**Step 8:** Commit: feat(mobile): implement pytdx client with connection pool

---

## Task 7: RPS Calculator & Technical Indicators

**Files:**
- Create: app/mobile/lib/services/rps_calculator.dart

**Step 1:** Implement calculateRps(code, periodReturn, allReturns) -> double
**Step 2:** Implement calculateAllRps(dailyBars, period) -> Map<String, double>
**Step 3:** Implement calculateMa(prices, period) -> List<double?> (MA10/20/50/120)
**Step 4:** Implement calculateVolMa(volumes, period) -> List<double?> (VOL_MA5/10/20/50)
**Step 5:** Implement threeLineRed(rps10, rps50, rps120) -> bool
**Step 6:** Verify: flutter analyze
**Step 7:** Commit: feat(mobile): implement RPS calculator and technical indicators

---

## Task 8: Data Sync Service

**Files:**
- Create: app/mobile/lib/services/data_sync.dart

**Step 1:** Implement DataSyncService with syncAll(onStepProgress) callback
**Step 2:** Step 1 - syncBasics(): fetch etf_basics + index_basics from pytdx, write to DB
**Step 3:** Step 2 - syncIndexDaily(): fetch bars for enabled indices, write to index_daily
**Step 4:** Step 3 - syncEtfDaily(): fetch bars for all 336 ETFs, write to etf_daily
**Step 5:** Step 4 - calculateIndicators(): calculate RPS, MA, VOL_MA for etf_daily
**Step 6:** Implement progress tracking: onStepProgress(stepIndex, current, total, status)
**Step 7:** Verify: flutter analyze
**Step 8:** Commit: feat(mobile): implement 4-step data sync service

---

## Task 9: ETF List Screen

**Files:**
- Create: app/mobile/lib/screens/etf_list_screen.dart
- Create: app/mobile/lib/widgets/etf_card.dart
- Create: app/mobile/lib/widgets/search_bar.dart
- Create: app/mobile/lib/widgets/sort_header.dart

**Step 1:** Create EtfCard widget - shows code, name, price, changePct, rps10/50/120
**Step 2:** Create SearchBar widget - text input with debounce filtering
**Step 3:** Create SortHeader widget - tap to sort by column
**Step 4:** Create EtfListScreen - ListView with search + sort + pull-to-refresh
**Step 5:** Add red-line filter: threeLineRed, twoLineRed, oneLineRed
**Step 6:** Wire up navigation to EtfDetailScreen
**Step 7:** Verify: flutter analyze
**Step 8:** Commit: feat(mobile): implement ETF list screen

---

## Task 10: ETF Detail Screen with K-line Chart

**Files:**
- Create: app/mobile/lib/screens/etf_detail_screen.dart
- Create: app/mobile/lib/widgets/kline_chart.dart

**Step 1:** Create KlineChart wrapper around k_chart_widget
**Step 2:** Map DailyBar to CandleEntity for k_chart_widget
**Step 3:** Add MA overlay lines (MA10 yellow, MA20 purple, MA50 blue, MA120 green)
**Step 4:** Create EtfDetailScreen with price header + K-line chart + OHLCV data
**Step 5:** Add pull-to-refresh
**Step 6:** Verify: flutter analyze
**Step 7:** Commit: feat(mobile): implement ETF detail screen with K-line chart

---

## Task 11: Watchlist Screen

**Files:**
- Create: app/mobile/lib/screens/watchlist_screen.dart

**Step 1:** Create WatchlistScreen - reads from watchlist table
**Step 2:** Add long-press on ETF card to add/remove from watchlist
**Step 3:** Add left-swipe to delete
**Step 4:** Wire up navigation to EtfDetailScreen
**Step 5:** Verify: flutter analyze
**Step 6:** Commit: feat(mobile): implement watchlist screen

---

## Task 12: Index List Screen (Reserved)

**Files:**
- Create: app/mobile/lib/screens/index_list_screen.dart

**Step 1:** Create IndexListScreen - reads enabled indices from index_basics
**Step 2:** Show basic info (code, name, latest price)
**Step 3:** Placeholder for future analysis features
**Step 4:** Verify: flutter analyze
**Step 5:** Commit: feat(mobile): implement index list screen (reserved)

---

## Task 13: Sync Dialog Widget

**Files:**
- Create: app/mobile/lib/widgets/sync_dialog.dart

**Step 1:** Create SyncDialog StatefulWidget - shows 4 steps with status icons
**Step 2:** Implement step display: ⏳ / ✅ / ❌ with step name and progress
**Step 3:** Wire up DataSyncService callbacks to update dialog state
**Step 4:** Add cancel button that interrupts sync
**Step 5:** Add auto-close on completion
**Step 6:** Verify: flutter analyze
**Step 7:** Commit: feat(mobile): implement sync progress dialog

---

## Task 14: Home Screen with Bottom Navigation + Sync Button

**Files:**
- Create: app/mobile/lib/screens/home_screen.dart

**Step 1:** Create HomeScreen with BottomNavigationBar (4 tabs: ETF, Watchlist, Index, Settings)
**Step 2:** Add sync button in AppBar actions - opens SyncDialog on tap
**Step 3:** Wire up page switching
**Step 4:** Update app.dart to use HomeScreen as home
**Step 5:** Verify: flutter build apk --debug
**Step 6:** Commit: feat(mobile): implement home screen with sync button

---

## Task 15: Provider State Management

**Files:**
- Create: app/mobile/lib/providers/theme_provider.dart
- Create: app/mobile/lib/providers/etf_provider.dart
- Create: app/mobile/lib/providers/watchlist_provider.dart

**Step 1:** Create ThemeProvider - manages dark/light mode, persists to SharedPreferences
**Step 2:** Create EtfProvider - manages ETF list state, search, sort, filter
**Step 3:** Create WatchlistProvider - manages watchlist state
**Step 4:** Wrap app with MultiProvider in main.dart (Theme + Etf + Watchlist)
**Step 5:** Wire screens to use ChangeNotifierProvider
**Step 6:** Add theme toggle button in Settings screen
**Step 7:** Verify: flutter analyze
**Step 8:** Commit: feat(mobile): add provider state management with theme toggle

---

## Task 16: Final Integration & Polish

**Step 1:** Full integration test - manual verification on Android
**Step 2:** Fix any issues found
**Step 3:** Verify all screens work end-to-end
**Step 4:** Final commit: feat(mobile): final integration and polish
