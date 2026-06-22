# 📊 YuQuant - A股量化仿真与前端看板系统

基于 **React + FastAPI** 分离架构的A股量化回测系统，提供专业的市场监控、个股分析、RPS强度分析和策略回测功能。

## ✨ 功能特性

### 🔍 市场监控与分析
- **CR5%拥挤度指标**：实时监测成交额前5%的拥挤状态，支持多周期（日/周/月/季/年）聚合
- **RPS 强度分析**：基于欧奈尔强度的个股及板块 RPS 计算与展示
- **板块分析**：支持同步通达信板块概念，并自动聚合板块日线数据
- **历史趋势图**：查看各项指标与指数（上证、科创50等）的对比趋势

### 📈 个股技术分析
- **K线图展示**：支持均线叠加（MA10/MA20/MA60）
- **成交量分析**：同步展示成交量柱形图
- **数据同步**：多源数据同步（TqCenter/PyTdX/AkShare/BaoStock）

### 🤖 策略回测
- **灵活配置**：自定义初始资金和回测区间
- **详细指标**：总收益、年化收益、最大回撤、夏普比率
- **可视化报告**：资金曲线图和交易记录

## 🏗️ 技术架构

```
YuQuant/
├── app/
│   ├── data/                 # ✨ 新增：MongoDB 数据层
│   │   ├── db.py             # 数据库操作封装
│   │   ├── manager.py        # 多源数据同步管理器
│   │   ├── sources/          # 各数据源驱动（Pytdx, AkShare等）
│   │   └── task_manager.py   # 后台任务管理
│   │
│   ├── server/               # FastAPI 后端
│   │   ├── main.py           # 应用入口
│   │   ├── models.py         # Pydantic 模型
│   │   └── api/              # API 路由
│   │       ├── stocks.py     # 股票基础数据
│   │       ├── factors.py    # CR5/RPS 因子与板块同步
│   │       ├── backtest.py   # 回测引擎接口
│   │       ├── sync.py       # 数据同步任务
│   │       └── market_analysis.py # 市场分析接口
│   │
│   ├── client/               # React 前端
│   │   └── src/
│   │       ├── pages/        # 市场监控、个股分析、RPS分析、回测、设置
│   │       └── components/   # 可复用组件
│   │
│   ├── factor_engine.py      # 因子计算引擎
│   └── app.py                # Streamlit 遗留版本（维护中）
│
├── data/                     # 历史数据存放目录
├── requirements.txt          # Python 依赖
└── start.sh                  # 一键启动脚本
```

## 🚀 快速开始

### 前置条件
- Python 3.8+
- Node.js 16+
- **MongoDB 5.0+**
- npm 或 yarn

### 1. 安装后端依赖
```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 环境配置
复制 `.env.example` 为 `.env` 并配置 MongoDB 连接字符串及其他 API 密钥。

### 3. 安装前端依赖
```bash
cd app/client
npm install
```

### 4. 启动服务
```bash
./start.sh
```

## 📚 API 文档

### 主要API端点
- `GET /api/stocks` - 获取股票列表
- `GET /api/factors/cr5` - 获取CR5因子数据（支持 `period` 参数）
- `POST /api/factors/rps/calculate` - 后台计算RPS指标
- `POST /api/factors/sync-sectors` - 同步板块概念与聚合数据
- `POST /api/sync/daily` - 同步单只股票数据
- `POST /api/sync/daily/all` - 后台全量同步股票数据

## 🎯 为什么升级？

### 原 Streamlit 架构问题
- 组件库有限，难以实现复杂UI
- 前后端耦合，难以独立扩展
- 性能瓶颈（大数据量下的渲染开销）

### 新 React + FastAPI 优势
- ✅ **异步任务处理**：基于 FastAPI + 线程池的长时间任务管理
- ✅ **高性能存储**：从 SQLite/HDF5 升级到 MongoDB，支持更灵活的非结构化查询
- ✅ **专业的 UI 组件**：Ant Design + ECharts/Recharts 提供更好的可视化体验
- ✅ **清晰的架构分离**：前后端独立开发和部署

## 📄 许可证

MIT License
