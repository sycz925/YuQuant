# 2026-08-22 Mobile ETF App Design

## 1. 概述

独立 Flutter 移动端 App，专注 A 股 ETF 量化分析。无后端，直连通达信服务器获取数据，SQLite 本地持久化。仅 Android 平台。

### 1.1 技术选型

| 组件 | 方案 |
|------|------|
| 框架 | Flutter (Dart) |
| 平台 | Android（后续可扩展 iOS） |
| 数据库 | SQLite (`sqflite`) |
| 行情数据 | pytdx 通达信协议（纯 Dart 实现） |
| K线图表 | `k_chart_widget` |
| 状态管理 | `provider` |
| UI 主题 | 暗色/浅色可切换 |

### 1.2 功能范围

| 功能 | 优先级 | 说明 |
|------|--------|------|
| ETF 列表 | P0 | 336只 ETF，搜索/排序，实时行情 |
| K线图表 | P0 | 日K蜡烛图 + MA10/20/50/120 叠加 |
| RPS 排名 | P0 | RPS 10/50/120 排序 + 红三线筛选 |
| 自选股 | P0 | 添加/删除自选 ETF，快速访问 |
| 指数数据 | P1 | 从 `index_basics` 读取启用指数，预留分析页 |

## 2. 架构设计

### 2.1 整体数据流

```
用户操作 → Flutter UI (Screens/Widgets)
                ↓
           Services (业务逻辑层)
          ↙          ↘
   PytdxDartClient   Database
   (通达信协议)      (SQLite)
```

- **同步按钮**：点击弹出4步骤进度对话框，一键执行全量同步
- **数据流**：pytdx 拉取 → 写入 SQLite → UI 读 SQLite 展示

### 2.2 项目结构

```
app/mobile/
├── lib/
│   ├── main.dart
│   ├── app.dart                        # MaterialApp + 路由 + 主题切换
│   ├── config/
│   │   └── theme.dart                  # 深色/浅色主题配置
│   ├── providers/
│   │   ├── theme_provider.dart         # 主题切换状态管理
│   │   ├── etf_provider.dart           # ETF 列表状态管理
│   │   └── watchlist_provider.dart     # 自选股状态管理
│   ├── models/
│   │   ├── etf_basic.dart
│   │   ├── daily_bar.dart
│   │   ├── index_basic.dart
│   │   ├── etf_alert.dart
│   │   └── watchlist_item.dart
│   ├── services/
│   │   ├── pytdx/
│   │   │   ├── client.dart             # 连接池 + socket 管理
│   │   │   ├── protocol.dart           # 二进制协议编解码
│   │   │   ├── parser.dart             # 数据解析器
│   │   │   └── servers.dart            # 通达信服务器列表
│   │   ├── database.dart               # SQLite CRUD
│   │   ├── data_sync.dart              # 数据同步编排
│   │   └── rps_calculator.dart         # RPS 计算引擎
│   ├── screens/
│   │   ├── home_screen.dart            # 主页（底部导航）
│   │   ├── etf_list_screen.dart        # ETF 列表页
│   │   ├── etf_detail_screen.dart      # ETF 详情页（K线图）
│   │   ├── index_list_screen.dart      # 指数列表页（预留）
│   │   └── watchlist_screen.dart       # 自选股页
│   └── widgets/
│       ├── kline_chart.dart            # K线图表封装
│       ├── etf_card.dart               # ETF 卡片组件
│       ├── search_bar.dart             # 搜索栏组件
│       ├── sort_header.dart            # 排序表头组件
│       └── sync_dialog.dart            # 同步进度对话框
├── android/
├── pubspec.yaml
└── README.md
```

## 3. SQLite 表设计（对齐 MongoDB Schema）

### 3.1 etf_basics

```sql
CREATE TABLE etf_basics (
  code        TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  update_time TEXT
);
```

### 3.2 etf_daily

```sql
CREATE TABLE etf_daily (
  stock_code  TEXT NOT NULL,
  trade_date  TEXT NOT NULL,
  open        REAL,
  high        REAL,
  low         REAL,
  close       REAL,
  vol         REAL,
  amount      REAL,
  chg_pct     REAL,
  data_source TEXT,
  is_final    INTEGER DEFAULT 0,
  ma10        REAL,
  ma20        REAL,
  ma50        REAL,
  ma120       REAL,
  vol_ma5     REAL,
  vol_ma10    REAL,
  vol_ma20    REAL,
  vol_ma50    REAL,
  chg_5d      REAL,
  chg_10d     REAL,
  chg_20d     REAL,
  chg_50d     REAL,
  chg_120d    REAL,
  chg_250d    REAL,
  rps_10      REAL,
  rps_20      REAL,
  rps_50      REAL,
  rps_120     REAL,
  close_raw   REAL,
  update_time TEXT,
  PRIMARY KEY (stock_code, trade_date)
);
CREATE INDEX idx_etf_daily_date ON etf_daily(trade_date);
```

### 3.3 index_basics

```sql
CREATE TABLE index_basics (
  code        TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  market      INTEGER,
  tdx_code    TEXT,
  is_disable  INTEGER DEFAULT 0,
  pe_ttm      REAL,
  update_time TEXT
);
```

### 3.4 index_daily

```sql
CREATE TABLE index_daily (
  stock_code  TEXT NOT NULL,
  trade_date  TEXT NOT NULL,
  open        REAL,
  high        REAL,
  low         REAL,
  close       REAL,
  volume      REAL,
  amount      REAL,
  chg_pct     REAL,
  pe_ttm      REAL,
  data_source TEXT,
  is_final    INTEGER DEFAULT 0,
  update_time TEXT,
  PRIMARY KEY (stock_code, trade_date)
);
CREATE INDEX idx_index_daily_date ON index_daily(trade_date);
```

### 3.5 etf_alerts

```sql
CREATE TABLE etf_alerts (
  code       TEXT NOT NULL,
  name       TEXT,
  trade_date TEXT NOT NULL,
  close      REAL,
  close_raw  REAL,
  amount     REAL,
  chg_pct    REAL,
  ene_ma     REAL,
  ene_upper  REAL,
  ene_lower  REAL,
  reason     TEXT NOT NULL,
  created_at TEXT,
  PRIMARY KEY (code, trade_date, reason)
);
```

### 3.6 watchlist

```sql
CREATE TABLE watchlist (
  code       TEXT PRIMARY KEY,
  type       TEXT NOT NULL,
  created_at TEXT NOT NULL,
  tdx_status TEXT
);
```

### 3.7 sync_tasks

```sql
CREATE TABLE sync_tasks (
  task_id    TEXT PRIMARY KEY,
  status     TEXT NOT NULL,
  sources    TEXT,
  message    TEXT,
  error      TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

## 4. pytdx Dart 实现

### 4.1 通达信协议要点

pytdx 使用自定义二进制 TCP 协议，核心流程：

1. **Socket 连接**：TCP 连接通达信服务器（端口 7709）
2. **握手认证**：发送认证包获取会话 ID
3. **请求打包**：按协议格式组装请求包（命令码 + 参数）
4. **响应解包**：解析二进制响应流（头部 + 数据体）

### 4.2 服务器列表

```dart
const tdxServers = [
  ('180.153.18.170', 7709),  // 上海主站
  ('119.147.212.81', 7709),  // 深圳主站
  ('112.74.214.43', 7709),
  ('121.14.110.194', 7709),
  ('218.108.98.244', 7709),
  ('60.12.136.250', 7709),
];
```

### 4.3 连接池设计

- 线程安全连接池，最大 8 个连接（移动端资源有限）
- 自动重试：单个服务器失败自动切换下一个
- 超时机制：单次请求 5 秒超时

### 4.4 数据接口

| 方法 | 说明 | 用途 |
|------|------|------|
| `getSecurityList()` | 获取证券列表 | ETF/指数代码发现 |
| `getSecurityQuotes()` | 实时行情快照 | 行情列表展示 |
| `getSecurityBars()` | 日K线数据 | K线图表 + RPS 计算 |
| `getXdXrInfo()` | 除权除息事件 | 前复权计算 |

### 4.5 数据同步流程

点击同步按钮 → 弹出 SyncDialog，显示4个步骤进度：

```
Step 1: 同步基础数据
  → 获取证券列表 → 写入 etf_basics / index_basics
  → 获取每只 ETF/指数的日K线 → 写入 etf_daily / index_daily

Step 2: 同步指数日线
  → 获取 index_basics 中 is_disable=0 的指数
  → 拉取日K线数据 → 写入 index_daily

Step 3: 同步ETF日线
  → 遍历 336 只 ETF
  → 拉取日K线数据 → 写入 etf_daily

Step 4: 计算ETF的RPS
  → 从 etf_daily 读取各周期涨幅
  → 计算 RPS 10/20/50/120 排名
  → 更新 etf_daily 的 rps 字段
  → 计算 MA 均线 → 更新 ma 字段
  → 计算 VOL_MA → 更新 vol_ma 字段
```

对话框实时显示当前步骤和进度（步骤名 + 状态图标：⏳进行中 / ✅完成 / ❌失败）。

## 5. UI 设计

### 5.1 主题配置（深色/浅色切换）

#### 深色主题

```dart
// 主色调
primary: Color(0xFF1E1E2E),    // 深紫灰背景
surface: Color(0xFF2A2A3E),    // 卡片背景
accent: Color(0xFF7C3AED),     // 紫色强调

// 涨跌色
rise: Color(0xFFEF4444),       // 红色（涨）
fall: Color(0xFF22C55E),       // 绿色（跌）
flat: Color(0xFF9CA3AF),       // 灰色（平）

// 文字
textPrimary: Color(0xFFE5E7EB),
textSecondary: Color(0xFF9CA3AF),
```

#### 浅色主题

```dart
// 主色调
primary: Color(0xFFF8FAFC),    // 浅灰白背景
surface: Color(0xFFFFFFFF),    // 卡片背景
accent: Color(0xFF7C3AED),     // 紫色强调（不变）

// 涨跌色（不变）
rise: Color(0xFFEF4444),
fall: Color(0xFF22C55E),
flat: Color(0xFF9CA3AF),

// 文字
textPrimary: Color(0xFF1E293B),
textSecondary: Color(0xFF64748B),
```

#### 切换机制

- 使用 `provider` + `ThemeNotifier` 管理主题状态
- 持久化到 SharedPreferences（用户选择跨会话保持）
- 设置页切换按钮 + 首次启动跟随系统

### 5.2 页面结构

#### 主页（底部导航）

| Tab | 图标 | 页面 |
|-----|------|------|
| ETF | bar_chart | ETF 列表 |
| 自选 | star | 自选股 |
| 指数 | show_chart | 指数列表（预留） |
| 设置 | settings | 设置（预留） |

#### ETF 列表页

- 顶部搜索栏：支持代码/名称模糊搜索
- 排序表头：代码 | 名称 | 现价 | 涨跌幅 | RPS10 | RPS50 | RPS120 | 5日涨幅 | 10日涨幅
- 筛选按钮：红三线 / 二线红 / 一线红
- 列表项点击跳转 ETF 详情页
- 长按添加自选

#### ETF 详情页

- 顶部：代码 + 名称 + 现价 + 涨跌幅
- 中部：K线蜡烛图（`k_chart_widget`）
  - 支持缩放/拖动
  - MA 叠加：MA10（黄）/ MA20（紫）/ MA50（蓝）/ MA120（绿）
- 底部：行情数据（开高低收 / 成交量 / 成交额）

#### 自选股页

- 已添加的自选列表，支持拖拽排序
- 删除：左滑删除
- 点击跳转详情页

#### 指数列表页（预留）

- 展示 `index_basics` 中 `is_disable=0` 的指数
- 功能预留，后续扩展分析用

#### 设置页（预留）

- 主题切换：深色/浅色单选按钮
- 关于信息

### 5.3 同步对话框（SyncDialog）

点击右上角同步按钮弹出，全屏遮罩，不可关闭（除非完成或取消）。

```
┌─────────────────────────────┐
│        数据同步              │
│                             │
│  ✅ Step 1: 同步基础数据     │
│     ETF: 336条 / 指数: 12条  │
│                             │
│  ⏳ Step 2: 同步指数日线     │
│     进度: 8/12              │
│                             │
│  ⏳ Step 3: 同步ETF日线      │
│     进度: 120/336           │
│                             │
│  ⏳ Step 4: 计算ETF的RPS     │
│     等待中...               │
│                             │
│  ━━━━━━━━━━━━━━━━━━━━━━━━  │
│  总进度: 128/356            │
│                             │
│       [取消]                │
└─────────────────────────────┘
```

每个步骤状态图标：⏳ 进行中 / ✅ 完成 / ❌ 失败（显示错误信息）

## 6. RPS 计算

RPS（Relative Price Strength）相对价格强度，计算方法：

1. 取最近 N 个交易日（10/50/120）的区间涨幅
2. 对所有 ETF 按涨幅排名
3. RPS = (排名 / 总数) x 100

```dart
// RPS 计算伪代码
double calculateRps(List<double> returns, int rank) {
  return (rank / returns.length) * 100;
}

// 红三线判定
bool isThreeLineRed(Map<String, dynamic> etf) {
  return etf['rps_10'] > 87 && etf['rps_50'] > 87 && etf['rps_120'] > 87;
}
```

## 7. 关键依赖包

```yaml
dependencies:
  flutter:
    sdk: flutter
  sqflite: ^2.3.0          # SQLite
  provider: ^6.0.0          # 状态管理
  k_chart_widget: ^3.0.0    # K线图表
  path: ^1.8.0              # 路径处理
  shared_preferences: ^2.2.0 # 主题持久化
```

## 8. 风险与注意事项

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 通达信协议逆向不完整 | 数据获取失败 | 参考 pytdx 开源实现，逐步验证 |
| 服务器连接不稳定 | 数据同步中断 | 连接池 + 自动重试 + 多服务器切换 |
| 336只ETF全量同步耗时长 | 用户等待时间久 | 增量同步 + 进度提示 + 后台执行 |
| k_chart_widget 维护停滞 | 图表功能受限 | 保留替换为 fl_chart 的扩展能力 |
