# A股量化系统 - 文档索引

## 项目概述

一套专业的 A 股量化分析系统，基于 **React + FastAPI 分离架构**。

### 核心特性
- ✅ 防幸存者偏差的历史截面成分股逻辑
- ✅ 成交额前 5% 拥挤度因子（CR5%）
- ✅ 250日 NH-NL 新高新低指数（Elder）
- ✅ 多周期 RPS 相对强度（10/20/50/120/250）
- ✅ 新高板块效应聚类 + 低位潜力板块
- ✅ DeepSeek AI 综合研判
- ✅ 日历快照 + 周/月 AI 总结
- ✅ Factory + Orchestrator 两层架构

---

## 文档拓扑树

### 架构设计 (architecture/)
- [系统架构概览](architecture/overview.md) - 整体架构、技术栈、Factory+Orchestrator 模式
- [数据源调度策略](architecture/data-source-strategy.md) - 多源优先级、降级逻辑、代码格式转换

### 数据模型 (database/)
- [MongoDB 集合定义](database/SCHEMA.md) - 10个集合的结构、字段、索引
- [MongoDB Schema 详细设计](database/mongodb-schema.md) - 各文档字段类型与约束
- ~~数据迁移方案~~（已归档 - 迁移已完成）

### API 接口 (api/)
- [模块接口规范](api/modules.md) - 10个路由模块 76+ 端点定义

### 业务功能 (features/)
- [数据更新系统](features/data-update-system.md) - 通达信 pytdx 数据源：板块文件解析、指数日线、数据同步编排
- [数据管理器](features/data-manager.md) - 多源同步、RPS 计算、字段计算
- [因子引擎](features/factor-engine.md) - 技术指标和因子计算
- [前端应用](features/frontend-app.md) - React 前端应用

### 开发计划 (plans/)
- [2026-06-04 开发计划](plans/2026-06-04-development-plan.md) - 原始单模块架构计划
- [2026-06-05 React+FastAPI 架构升级](plans/2026-06-05-react-fastapi-migration.md)
- [2026-06-05 后续开发计划](plans/2026-06-05-next-steps.md)

### 快速开始 (getting-started/)
- [环境配置](getting-started/setup.md) - 环境依赖安装与启动

---

## 代码结构

```
A股量化系统/
├── app/
│   ├── data/                    # 数据层
│   │   ├── db.py               # MongoDB 连接 + DAO（COLLECTION_MAP 映射）
│   │   ├── manager.py          # DataManager 多源同步编排
│   │   ├── task_manager.py     # 后台任务管理
│   │   └── sources/            # 7 个数据源驱动
│   │
│   ├── server/                  # FastAPI 后端
│   │   ├── main.py             # 应用入口
│   │   ├── cache.py            # 交易日缓存
│   │   ├── api/                # 10 个路由模块
│   │   ├── factories/          # 4 个 Factory
│   │   └── orchestrators/      # 4 个 Orchestrator
│   │
│   ├── client/                  # React 前端
│   │   └── src/
│   │       ├── pages/          # 页面组件
│   │       ├── components/     # 通用组件
│   │       ├── App.jsx         # 主应用
│   │       └── api.js          # API 封装
│   │
│   └── engine/                  # 因子计算引擎
│       └── factor_engine.py    # CR5/CR10/RPS/均线
│
├── docs/                        # 项目文档
├── scripts/                     # 数据修复脚本
├── start.sh / stop.sh           # 启停脚本
├── requirements.txt
└── AGENTS.md                    # 代理配置
```

---

## 技术栈

| 层级 | 技术选型 |
|------|----------|
| **前端框架** | React 18 + Vite |
| **后端框架** | FastAPI + Uvicorn |
| **主数据源** | PyTdX（通达信协议直连） |
| **回退数据源** | AkShare → BaoStock → yfinance |
| **数据存储** | MongoDB（10个集合） |
| **数据处理** | NumPy + Pandas |
| **AI 引擎** | DeepSeek API |
| **图表库** | Recharts / ECharts |
| **HTTP 客户端** | Axios |

---

## 相关链接

- [项目根目录 README](../README.md)
- [代理配置](../AGENTS.md)
