# A 股量化仿真与前端看板系统 - 文档索引

## 📚 项目概述

一套专业的 A 股量化回测与分析系统，已升级为 **React + FastAPI 分离架构，提供更优秀的用户体验！

### 核心特性
- ✅ 防幸存者偏差的历史截面成分股逻辑
- ✅ 后复权价格处理，消除分红送转导致的价格断层
- ✅ 成交额前 5% 拥挤度因子（CR5%）
- ✅ 真实交易摩擦模拟（佣金、过户费、印花税）
- ✅ T+1 制度、涨跌停限制、滑点模拟
- ✅ 双向动态风控与全局择时

---

## 📂 文档拓扑树

### 🏗️ 架构设计 (architecture/)
- [系统架构概览](architecture/overview.md) - 整体系统架构、技术栈、模块关系

### 🗄️ 数据模型 (database/)
- [数据库 Schema](database/SCHEMA.md) - 数据表结构、字段定义、索引设计

### 🔌 API 接口 (api/)
- [模块接口规范](api/modules.md) - 各核心模块的公共接口定义
- [REST API 规范](api/rest-api.md) - （待创建

### 🎯 业务功能 (features/)
- [数据更新系统](features/data-update-system.md) - **通达信 pytdx 数据源**：板块文件解析、指数日线、数据同步编排（核心文档）
- [数据管理器](features/data-manager.md) - 数据获取、缓存、清洗逻辑
- [因子引擎](features/factor-engine.md) - 技术指标和因子计算
- [舆情分析引擎](features/sentiment-engine.md) - 舆情文本数据处理
- [回测引擎](features/backtest-engine.md) - 仿真回测核心逻辑
- [前端应用](features/frontend-app.md) - React 前端应用

### 📅 开发计划 (plans/)
- [2026-06-04 开发计划](plans/2026-06-04-development-plan.md) - 原始单模块架构计划
- [2026-06-05 React+FastAPI 架构升级](plans/2026-06-05-react-fastapi-migration.md) - 架构升级完成的计划
- [2026-06-05 后续开发计划](plans/2026-06-05-next-steps.md) - （待创建

### 🚀 部署运维 (deployment/)
- [本地开发环境](deployment/local.md) - 开发环境配置指南

### 🛠️ 快速开始 (getting-started/)
- [环境配置](getting-started/setup.md) - 环境依赖安装
- [项目运行](getting-started/run.md) - 项目启动和调试

---

## 🏗️ 代码结构

```
YuQuant/
├── app/
│   ├── data_manager.py       # 数据管理器
│   ├── factor_engine.py      # 因子引擎
│   ├── sentiment_engine.py  # 舆情分析引擎
│   ├── backtest_engine.py    # 回测引擎
│   ├── app.py              # Streamlit 前端（保留，可选使用
│   │
│   ├── server/             # ✨ FastAPI 后端
│   │   ├── __init__.py
│   │   ├── main.py         # FastAPI 入口
│   │   ├── models.py       # Pydantic 模型
│   │   └── api/            # API 路由
│   │       ├── stocks.py
│   │       ├── factors.py
│   │       ├── backtest.py
│   │       └── sync.py
│   │
│   └── client/             # ✨ React 前端
│       ├── package.json
│       ├── vite.config.js
│       ├── tailwind.config.js
│       └── src/
│           ├── components/    # 组件
│           ├── pages/       # 页面
│           │   ├── MarketMonitor.jsx
│           │   ├── StockAnalysis.jsx
│           │   └── Backtest.jsx
│           ├── App.jsx
│           ├── api.js
│           └── main.jsx
│
├── data/                     # 本地数据存储
│   ├── sqlite/              # SQLite 数据库
│   └── hdf5/               # HDF5 数据缓存
│
├── docs/                     # 项目文档
│   ├── architecture/        # 架构设计
│   ├── database/          # 数据模型
│   ├── api/              # API 接口
│   ├── features/         # 功能说明
│   ├── plans/            # 开发计划
│   ├── deployment/      # 部署文档
│   └── getting-started/ # 快速开始
│
├── agents/                  # AI 代理配置
│   ├── ProjectManagerAgent.md
│   ├── ArchitectAgent.md
│   ├── FrontendAgent.md
│   ├── BackendAgent.md
│   └── DeployAgent.md
│
├── tests/                   # 测试用例
│   ├── test_data_manager.py
│   ├── test_factor_engine.py
│   └── ...
│
├── requirements.txt         # Python 依赖
├── start.sh                # 一键启动脚本
├── README.md              # 项目说明
└── AGENTS.md              # 代理配置
```

---

## 🧰 技术栈

| 层级 | 技术选型 |
|------|----------|
| **前端框架** | React 18 + Vite |
| **后端框架** | FastAPI + Uvicorn |
| **主数据源** | pytdx（通达信协议直连）— 板块文件 `block_gn.dat`/`block_zs.dat` + `880XXX/881XXX` 指数日线 |
| **回退数据源** | TqCenter（Windows DLL） > AkShare（Web API） > BaoStock > yfinance |
| **数据存储** | MongoDB（`stock_basics` / `sector_basics` / `daily_data` / `factor_results`） |
| **数据处理** | NumPy + Pandas |
| **样式方案** | Tailwind CSS |
| **图表库** | Recharts / ECharts |
| **HTTP 客户端** | Axios |

---

## 📞 相关链接

- [项目根目录 README](../README.md)
- [代理配置](../AGENTS.md)
