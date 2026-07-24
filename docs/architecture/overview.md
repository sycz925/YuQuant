# 系统架构概览

审计日期: 2026-07-24

## 整体架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          用户交互层                                      │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    React Web UI (Vite)                           │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │  │
│  │  │市场监控  │  │市场分析  │  │个股分析  │  │日历复盘  │       │  │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
                              │ HTTP / JSON
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    FastAPI 后端 (端口 8000)                              │
│                                                                         │
│  ┌─────────────────────┐   ┌─────────────────────┐                     │
│  │   Orchestrators     │   │     Factories        │                     │
│  │  - OneClickUpdate   │   │  - IndexFactory      │                     │
│  │  - DailyRecalc      │   │  - StockFactory      │                     │
│  │  - MonthlyRecalc    │   │  - SectorFactory     │                     │
│  │  - SettingsTask     │   │  - MarketAggregator  │                     │
│  └─────────────────────┘   └─────────────────────┘                     │
│                              │                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │               API 路由层 (10个模块, 76+端点)                      │  │
│  │  market_review / market_analysis / factors / stocks / sync       │  │
│  │  calendar / search / screenshot / one_click_update / settings    │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │               DataManager (数据同步编排)                           │  │
│  │               DataManager 单例 + TaskManager                       │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│     MongoDB      │  │   PyTdX (首选)   │  │  AkShare (回退)  │
│  10 个集合        │  │   通达信协议直连  │  │   Web API        │
│  stock_daily     │  │   板块dat解析     │  │   基础信息        │
│  sector_daily    │  └──────────────────┘  └──────────────────┘
│  index_daily     │         │                       │
│  base_data_daily │         ▼                       ▼
│  market_daily    │  ┌──────────────────┐  ┌──────────────────┐
│  ...             │  │   BaoStock       │  │   yfinance       │
└──────────────────┘  │   个股日线回退    │  │   最后备用        │
                      └──────────────────┘  └──────────────────┘
```

## 技术栈选型

| 层级 | 技术 |
|------|------|
| **前端框架** | React 18 + Vite |
| **前端样式** | Tailwind CSS |
| **图表** | ECharts / Recharts |
| **后端框架** | FastAPI + Uvicorn |
| **数据存储** | MongoDB（10个集合） |
| **数据源** | PyTdX → AkShare → BaoStock → yfinance |
| **AI 引擎** | DeepSeek API |

## 核心模块关系

### 数据流向
```
数据源 → DataManager → MongoDB → Factories → Orchestrators → API → React UI
```

### Factory + Orchestrator 模式

系统采用两层设计：

**Orchestrator 层**（`app/server/orchestrators/`）：负责多步骤的编排调度
- `OneClickUpdateOrchestrator` — 7步骤全量同步（指数→个股→板块→个股RPS→板块RPS→PE→预计算）
- `DailyRecalcOrchestrator` — 单日重算3步骤（个股RPS→板块RPS→预计算）
- `MonthlyRecalcOrchestrator` — 月度重算，对月份内每个交易日执行 DailyRecalcOrchestrator
- `SettingsOrchestrator` — 设置页单步任务（同步指数/日线/板块/PE、计算RPS、预计算）

**Factory 层**（`app/server/factories/`）：负责单一领域的数据同步与计算
- `IndexFactory` — 指数K线同步、PE同步、涨幅计算、按周期聚合
- `StockFactory` — 个股日线同步、RPS计算、涨幅计算、均线计算
- `SectorFactory` — 板块日线同步、RPS计算、涨幅计算、均线计算
- `MarketAggregator` — 跨域聚合：基础预计算（CR5/CR10/MA/NH-NL）、新高分析、市场总览

### 模块依赖
- **DataManager**：基础模块，依赖各数据源驱动
- **Factories**：依赖 DataManager + MongoDB DAO
- **Orchestrators**：依赖 Factories
- **API 路由**：调用 Orchestrators / Factories

## 目录结构

```
A股量化系统/
├── app/
│   ├── data/                    # 数据层
│   │   ├── db.py               # MongoDB DAO
│   │   ├── manager.py          # DataManager
│   │   ├── task_manager.py     # 后台任务管理
│   │   └── sources/            # 7个数据源驱动
│   │
│   ├── server/                  # FastAPI 后端
│   │   ├── main.py             # 应用入口
│   │   ├── cache.py            # 交易日缓存
│   │   ├── api/                # 10个路由模块
│   │   ├── factories/          # 4个Factory
│   │   └── orchestrators/      # 4个Orchestrator
│   │
│   ├── client/                  # React 前端
│   │   └── src/
│   │       ├── pages/          # 页面组件
│   │       └── components/     # 通用组件
│   │
│   └── engine/                  # 因子计算引擎
│       └── factor_engine.py    # CR5/CR10/RPS/均线
│
├── docs/                        # 项目文档
├── scripts/                     # 数据修复脚本
├── start.sh / stop.sh           # 启停脚本
└── requirements.txt
```

## 安全设计原则

1. **输入验证**：所有 API 调用都有超时和重试机制
2. **CORS 配置**：仅允许前端域名访问
3. **防未来函数**：所有时间序列操作严格检查数据时效性
4. **错误处理**：模块间有清晰的异常传递和恢复机制
5. **is_final 标记**：区分盘中数据与收盘后最终数据，避免预计算使用未完成数据
