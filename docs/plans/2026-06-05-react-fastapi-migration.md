# React + FastAPI 架构升级开发计划

**日期**：2026-06-05  
**负责代理**：ProjectManagerAgent  
**项目状态**：多模块大项目模式

---

## 📋 目标
将Streamlit全栈架构升级为React前端 + FastAPI后端的分离架构，提供更好的用户体验和开发体验。

---

## 🎯 里程碑 1：FastAPI后端构建
**负责代理**：BackendAgent  
**可用技能**：autoproject, VibeSec-Skill  
**状态**：待执行

### 任务清单
- [ ] 创建 `app/server/` 目录结构
- [ ] 创建 `app/server/main.py` - FastAPI应用入口
- [ ] 创建 `app/server/api/` - API路由模块
  - [ ] `stocks.py` - 股票数据API
  - [ ] `factors.py` - 因子API
  - [ ] `backtest.py` - 回测API
  - [ ] `sync.py` - 数据同步API
- [ ] 创建 `app/server/models.py` - Pydantic模型定义
- [ ] 更新 `requirements.txt` - 添加FastAPI等依赖
- [ ] 创建后端健康检查和API文档
- [ ] 测试现有DataManager/FactorEngine集成

### 交付物
- `app/server/main.py`
- `app/server/api/*.py`
- `app/server/models.py`
- 更新的 `requirements.txt`

---

## 🎯 里程碑 2：React前端构建
**负责代理**：FrontendAgent  
**可用技能**：autoproject, ui-ux-pro-max  
**状态**：待执行

### 任务清单
- [ ] 创建 `app/client/` 目录结构
- [ ] 初始化Vite + React + TypeScript项目
- [ ] 配置Tailwind CSS
- [ ] 创建路由配置（React Router）
- [ ] 创建API客户端封装
- [ ] 实现市场监控页面
- [ ] 实现个股技术分析页面（含Recharts K线图）
- [ ] 实现策略回测页面
- [ ] 创建公共组件库

### 交付物
- `app/client/` 完整项目结构
- `app/client/package.json`
- 所有页面和组件

---

## 🎯 里程碑 3：系统集成与测试
**负责代理**：ProjectManagerAgent + 各代理  
**可用技能**：autoproject  
**状态**：待执行

### 任务清单
- [ ] 前后端联调测试
- [ ] 创建开发环境配置
- [ ] 创建生产环境配置
- [ ] 更新README文档

---

## 📁 新架构目录结构

```
YuQuant/
├── app/
│   ├── data_manager.py      # 保留
│   ├── factor_engine.py     # 保留
│   ├── backtest_engine.py   # 保留
│   ├── sentiment_engine.py  # 保留
│   ├── app.py              # Streamlit（保留，可选使用）
│   │
│   ├── server/             # 新增：FastAPI后端
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── models.py
│   │   └── api/
│   │       ├── __init__.py
│   │       ├── stocks.py
│   │       ├── factors.py
│   │       ├── backtest.py
│   │       └── sync.py
│   │
│   └── client/             # 新增：React前端
│       ├── public/
│       ├── src/
│       │   ├── components/
│       │   ├── pages/
│       │   ├── api/
│       │   ├── App.tsx
│       │   └── main.tsx
│       ├── package.json
│       └── vite.config.ts
│
├── data/                   # 不变
├── docs/                   # 不变
├── requirements.txt        # 更新
└── README.md              # 更新
```

---

## 📚 技术栈

### 后端
- **Web框架**：FastAPI 0.104+
- **ASGI服务器**：Uvicorn
- **数据验证**：Pydantic
- **CORS**：fastapi.middleware.cors

### 前端
- **框架**：React 18
- **语言**：TypeScript
- **构建工具**：Vite
- **路由**：React Router v6
- **样式**：Tailwind CSS
- **图表**：Recharts
- **HTTP客户端**：Axios

---

## 📊 API设计概览

### 股票API
- `GET /api/stocks` - 获取股票列表
- `GET /api/stocks/{code}` - 获取股票详情
- `GET /api/stocks/{code}/daily` - 获取日线数据

### 因子API
- `GET /api/factors/cr5` - 获取CR5%因子数据

### 回测API
- `POST /api/backtest/run` - 运行回测
- `GET /api/backtest/result/{id}` - 获取回测结果

### 数据同步API
- `POST /api/sync/basics` - 同步股票基础信息
- `POST /api/sync/daily` - 同步日线数据

---

## 🔄 下一步
确认里程碑1开始执行？
