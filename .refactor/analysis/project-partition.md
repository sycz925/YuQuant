# Phase 0: 项目分区与资源盘点

**分析日期**: 2026-07-25（重新全量分析）
**项目**: A股量化仿真与前端看板系统
**技术栈**: React 18 + FastAPI + MongoDB + Pydantic

---

## 1. 目录结构概览

```
app/
├── client/                    # 前端 React 应用
│   └── src/
│       ├── App.jsx            # 主入口
│       ├── api.js             # API 封装（184行）
│       ├── components/        # 通用组件（12个）
│       │   ├── AiAnalysis.jsx
│       │   ├── ErrorBoundary.jsx
│       │   ├── MaBreadthChart.jsx
│       │   ├── ManagementDialog.jsx
│       │   ├── MarketOverview.jsx
│       │   ├── MarketReview.jsx
│       │   ├── MarketSignals.jsx
│       │   ├── NhNlOverlayChart.jsx
│       │   ├── TacticalAllocationCard.jsx
│       │   └── TradingViewChart.jsx
│       ├── hooks/             # 自定义 hooks（4个）✅ 已建立
│       │   ├── index.js
│       │   ├── useOneClickUpdate.js
│       │   ├── usePolling.js
│       │   ├── useScreenshot.js
│       │   └── useTaskPolling.js
│       └── pages/             # 页面组件（8个）
│           ├── CalendarReview.jsx  ⚠️ 1331行
│           ├── MarketAnalysis.jsx
│           ├── MarketMonitor.jsx
│           ├── ReviewDetail.jsx
│           ├── SearchPage.jsx
│           ├── Settings.jsx        ⚠️ 657行
│           ├── StockAnalysis.jsx
│           └── TestIndexChart.jsx
│
├── data/                     # 数据层
│   ├── db.py                 # MongoDB 连接（496行）
│   ├── manager.py            # 数据管理器（716行）
│   ├── task_manager.py       # 任务管理器（341行）
│   ├── holidays.py           # 节假日判断（162行）
│   └── sources/              # 数据源（7个）
│       ├── pytdx_source.py   # 通达信（1388行）
│       ├── tqcenter_source.py # 天勤（598行）
│       ├── akshare_source.py
│       ├── baostock_source.py
│       ├── tushare_source.py
│       ├── yfinance_source.py
│       └── tencent_mv.py
│
├── engine/                   # 计算引擎
│   ├── factor_engine.py      # 因子引擎（602行）
│   └── rps_calculator.py     # RPS 计算器（523行）
│
└── server/                    # 后端 FastAPI 应用
    ├── main.py               # 入口（125行）
    ├── config.py             # 配置中心 ✅
    ├── models.py             # Pydantic 模型
    ├── cache.py              # 内存缓存（59行）
    ├── api/                  # 路由层（10个文件）
    │   ├── market_review.py  # 市场复盘（3095行）⚠️ 过大
    │   ├── calendar.py       # 日历复盘（1584行）⚠️ 过大
    │   ├── factors.py        # 因子 API（1428行）⚠️ 过大
    │   ├── deepseek_analyst.py # AI分析（654行）⚠️ 在api层
    │   ├── market_analysis.py  # 市场分析（498行）
    │   ├── one_click_update_v2.py # 一键更新（64行）✅ 已瘦身
    │   ├── settings_tasks.py    # 设置任务（148行）
    │   ├── stocks.py            # 个股（304行）
    │   ├── sync.py              # 同步（335行）
    │   ├── screenshot.py
    │   ├── search.py
    │   └── constants.py
    ├── factories/            # 工厂层 ✅ 已建立（6个文件）
    │   ├── base.py
    │   ├── index_factory.py  # 446行
    │   ├── stock_factory.py  # 324行
    │   ├── sector_factory.py # 285行
    │   └── market_aggregator.py # 166行
    ├── orchestrators/        # 编排层 ✅ 已建立（5个文件）
    │   ├── base.py
    │   ├── one_click_orchestrator.py # 364行
    │   ├── daily_recalc_orchestrator.py
    │   ├── monthly_recalc_orchestrator.py
    │   └── settings_orchestrator.py # 196行
    ├── repositories/         # 数据访问层 ✅ 已建立（7个文件）
    │   ├── base.py
    │   ├── stock_repository.py
    │   ├── index_repository.py
    │   ├── sector_repository.py
    │   ├── market_repository.py
    │   ├── summary_repository.py
    │   └── task_repository.py
    ├── services/             # 服务层 ✅ 已建立（5个文件）
    │   ├── base.py
    │   ├── data_service.py   # 331行
    │   ├── sync_service.py
    │   ├── market_service.py # 161行
    │   ├── market_data.py
    │   └── calendar_service.py
    └── utils/                # 工具函数
        └── sync_window.py
```

**代码量统计**:
- 后端 server: 12,462 行
- 前端 client/src: 8,393 行
- 数据层 data: 4,156 行
- 引擎 engine: 1,125 行
- 脚本 scripts: 2,574 行
- **总计: ~26,170 行**

---

## 2. 领域划分

```
项目领域划分
├── 前端域 (Frontend Domain)
│   ├── 页面层 (pages/)        - 8个页面组件
│   ├── 组件层 (components/)   - 12个业务组件
│   ├── Hooks层 (hooks/)       - 4个自定义 hooks ✅ 新增
│   ├── 基础设施 (api.js)      - API 封装与拦截器
│   └── 样式 (index.css)       - Tailwind CSS
│
├── 后端域 (Backend Domain)
│   ├── 路由层 (api/)          - 10个路由文件
│   ├── 编排层 (orchestrators/) - 5个编排器 ✅ 新增
│   ├── 工厂层 (factories/)    - 4个工厂 ✅ 新增
│   ├── 数据访问层 (repositories/) - 7个仓库 ✅ 新增
│   ├── 服务层 (services/)     - 5个服务 ✅ 新增
│   ├── 引擎层 (engine/)       - 2个计算引擎
│   └── 数据层 (data/)         - db, manager, sources
│
└── 公共域 (Common Domain)
    ├── 配置 (config.py, .env)
    ├── 模型 (models.py)
    └── 工具 (utils/)
```

---

## 3. 资源盘点

### 3.1 前端资源

#### UI 组件库 (Ant Design 6.x)
| 组件 | 使用文件数 | 使用位置 |
|------|-----------|----------|
| Button | 12 | 全局 |
| Spin | 6 | 全局加载状态 |
| Modal | 5 | 弹窗 |
| message | 5 | 全局提示 |
| notification | 3 | 通知 |
| Tag | 5 | 标签 |
| Select | 5 | 下拉选择 |
| Table | 3 | 表格 |
| Tooltip | 4 | 提示 |
| ConfigProvider | 3 | 国际化 |
| Segmented | 3 | 分段控制器 |
| DatePicker | 3 | 日期选择 |
| 其他 | - | Input, Form, Switch, Empty, Result, List, Typography, Space |

#### 图表库
| 库 | 使用文件 | 用途 |
|----|---------|------|
| **lightweight-charts** | TradingViewChart.jsx | K线图 |
| **recharts** | MarketOverview, MaBreadthChart, MarketMonitor, TestIndexChart | 统计图表 |
| **echarts** + **echarts-for-react** | NhNlOverlayChart, MarketAnalysis, MarketReview | 高级图表 ✅ 已使用 |

#### 自定义 Hooks（✅ 已建立）
| Hook | 文件 | 用途 |
|------|------|------|
| usePolling | usePolling.js | 通用轮询逻辑（支持页面隐藏暂停） |
| useTaskPolling | useTaskPolling.js | 任务状态轮询 |
| useOneClickUpdate | useOneClickUpdate.js | 一键更新流程 |
| useScreenshot | useScreenshot.js | 页面截图导出 |

#### 自定义组件
| 组件 | 行数 | 用途 |
|------|------|------|
| TradingViewChart | 679 | K线图（lightweight-charts） |
| MarketSignals | 598 | 市场信号展示 |
| AiAnalysis | 480 | AI 分析展示 |
| MarketReview | 368 | 市场复盘 |
| ManagementDialog | 280 | 管理弹窗 |
| NhNlOverlayChart | 212 | NH-NL 图表（echarts） |
| MarketOverview | 163 | 市场概览 |
| MaBreadthChart | 155 | MA 广度图（recharts） |
| TacticalAllocationCard | 125 | 战术配置卡片 |
| ErrorBoundary | - | 错误边界 |

#### 基础设施
| 基础设施 | 状态 | 说明 |
|----------|------|------|
| 日志系统 | ⚠️ console.log/error 55处 | 无统一日志 |
| 错误处理 | ✅ ErrorBoundary | 仅1个 |
| 路由系统 | ✅ React Router v6 | - |
| 请求拦截 | ✅ Axios 拦截器 | 含错误防抖 |
| 类型系统 | ❌ 无 | 全部 JSX，无 TypeScript |
| 状态管理 | ❌ 无 | 全部 useState |

---

### 3.2 后端资源

#### 新增架构层（vs 上次分析）

| 层 | 文件数 | 说明 |
|----|--------|------|
| **Repository 层** | 7个 | StockRepository, IndexRepository, SectorRepository, MarketRepository, TaskRepository, WeeklySummaryRepository, MonthlySummaryRepository |
| **Factory 层** | 4个 | IndexFactory, StockFactory, SectorFactory, MarketAggregator |
| **Orchestrator 层** | 4个 | OneClickUpdateOrchestrator, DailyRecalcOrchestrator, MonthlyRecalcOrchestrator, SettingsOrchestrator |
| **Service 层** | 5个 | DataService, SyncService, MarketService, CalendarService, MarketData |

#### 数据源 (data/sources/)
| 数据源 | 行数 | 用途 |
|--------|------|------|
| pytdx_source | 1388 | 通达信数据 |
| tqcenter_source | 598 | 天勤数据 |
| akshare_source | ~200 | AkShare 数据 |
| baostock_source | ~100 | BaoStock 数据 |
| tushare_source | ~100 | Tushare 数据 |
| yfinance_source | ~50 | Yahoo Finance |
| tencent_mv | ~50 | 腾讯市值 |

#### 基础设施
| 基础设施 | 位置 | 状态 |
|----------|------|------|
| 日志系统 | 全局 | Python logging ✅ |
| 配置系统 | config.py | pydantic-settings ✅ |
| 缓存系统 | cache.py | 内存缓存（threading.Lock）⚠️ 简单 |
| 任务管理 | task_manager.py | MongoDB 持久化 ✅ |
| 节假日 | holidays.py | 交易日判断 ✅ |
| 时间窗口 | utils/sync_window.py | 同步时间窗口 ✅ |
| 错误处理 | 全局 | 混合 HTTPException/return dict ⚠️ |
| 测试 | 几乎无 | scripts/ 下仅2个测试文件 ❌ |
| CI/CD | 无 | 无自动化流水线 ❌ |
| 容器化 | 无 | 无 Docker ❌ |

---

## 4. 关键数据统计

| 指标 | 当前值 | 上次分析 | 变化 |
|------|--------|----------|------|
| get_db() 总调用 | 104次 | 142次 | ↓ 27% |
| API层 get_db() | 72次 | 142次 | ↓ 49% |
| threading.Thread | 9次 | 23次 | ↓ 61% |
| except Exception | 168次 | - | - |
| console.log/error | 55次 | 40+次 | ↑ |
| useState/useEffect | 271次 | - | - |
| 前端 hooks | 4个 | 0个 | ✅ 新增 |
| 新架构层 | 22个文件 | 0个 | ✅ 新增 |

---

## 5. Phase 0 关键发现

### 已改善
1. ✅ Repository/Factory/Orchestrator/Service 四层架构已建立
2. ✅ 前端 hooks 已建立（4个）
3. ✅ get_db() 调用减少 27%
4. ✅ threading.Thread 减少 61%
5. ✅ one_click_update_v2.py 瘦身至 64 行（从 466 行）
6. ✅ echarts 已实际使用（之前是未使用）

### 仍存在的问题
1. ⚠️ **API 层仍有 72 处 get_db() 直接调用** - calendar.py(17), market_review.py(28), factors.py(13)
2. ⚠️ **3 个路由文件超过 1000 行** - market_review.py(3095), calendar.py(1584), factors.py(1428)
3. ⚠️ **deepseek_analyst.py(654行) 类放在 api 层** - 应迁移到 services
4. ⚠️ **168 处 bare except Exception** - 错误处理不统一
5. ⚠️ **55 处 console.log/error** - 前端无统一日志
6. ⚠️ **前端无 TypeScript** - 全部 JSX
7. ⚠️ **无测试覆盖** - 仅 scripts 下 2 个测试文件
8. ⚠️ **CalendarReview.jsx 1331 行** - 前端组件过大
9. ⚠️ **scripts 目录 20 个脚本文件** - 大量一次性脚本残留