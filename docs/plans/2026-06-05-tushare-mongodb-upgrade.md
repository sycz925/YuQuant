# Tushare + MongoDB 数据层升级计划

**日期**：2026-06-05  
**负责代理**：ProjectManagerAgent  
**项目状态**：多模块大项目模式

---

## 📋 升级目标

将数据层从 SQLite + HDF5 升级到 MongoDB，数据源优先级调整为：
1. **Tushare**（主，最稳定、数据最全）
2. **AkShare**（备）
3. **baostock**（补）

**关键约束**：
- ✅ 完全重写数据层
- ✅ 前端和 API 接口保持不变
- ✅ 迁移现有数据到 MongoDB

---

## 🎯 里程碑 1：架构设计与准备
**负责代理**：ArchitectAgent  
**可用技能**：autoproject, VibeSec-Skill  
**状态**：待执行

### 任务清单
- [ ] 设计 MongoDB 数据模型 Schema
- [ ] 设计数据源调度策略（Tushare > AkShare > baostock）
- [ ] 设计数据迁移方案（从 SQLite + HDF5 到 MongoDB）
- [ ] 更新 `requirements.txt` - 添加 tushare, pymongo, python-dotenv
- [ ] 创建环境变量配置文件（.env）用于存放 Tushare Token

### 交付物
- `docs/database/mongodb-schema.md` - MongoDB 数据模型设计
- `docs/architecture/data-source-strategy.md` - 数据源调度策略
- 更新的 `requirements.txt`
- `.env.example` 配置文件模板

---

## 🎯 里程碑 2：数据层重构
**负责代理**：BackendAgent  
**可用技能**：autoproject, VibeSec-Skill  
**状态**：待执行

### 任务清单
- [ ] 创建 `app/data/db.py` - MongoDB 连接和基础操作封装
- [ ] 重构 `app/data_manager.py` - 完全重写
  - [ ] Tushare 数据源集成（使用提供的 Token）
  - [ ] AkShare 数据源集成（作为备选）
  - [ ] baostock 数据源集成（作为补充）
  - [ ] 数据源优先级调度逻辑
  - [ ] MongoDB 存储实现（替代 SQLite + HDF5）
  - [ ] 完全移除假数据生成逻辑
- [ ] 创建 `app/data/migration.py` - 数据迁移脚本
  - [ ] 从 SQLite 迁移股票基础信息
  - [ ] 从 HDF5 迁移日线数据
  - [ ] 数据一致性校验

### 交付物
- `app/data/db.py`
- 完全重构的 `app/data_manager.py`
- `app/data/migration.py`
- 更新的 `app/server/api/sync.py` 适配新 DataManager

---

## 🎯 里程碑 3：数据迁移与验证
**负责代理**：BackendAgent  
**可用技能**：autoproject  
**状态**：待执行

### 任务清单
- [ ] 本地安装和配置 MongoDB（或使用 Docker）
- [ ] 执行数据迁移脚本
- [ ] 验证迁移后的数据完整性
- [ ] 测试 Tushare 数据获取
- [ ] 测试 AkShare/baostock 降级逻辑
- [ ] 验证 API 接口返回数据格式不变

### 交付物
- 数据迁移验证报告
- 测试报告

---

## 🎯 里程碑 4：系统集成与测试
**负责代理**：ProjectManagerAgent + 各代理  
**可用技能**：autoproject  
**状态**：待执行

### 任务清单
- [ ] 前端完整功能测试（确保 API 接口兼容）
- [ ] 市场监控页面测试
- [ ] 个股技术分析页面测试
- [ ] 策略回测页面测试
- [ ] 更新 `README.md` - 反映新的架构和数据层
- [ ] 更新 `docs/` 相关文档

### 交付物
- 更新的 `README.md`
- 更新的 `docs/` 文档
- 系统测试报告

---

## 🏗️ MongoDB 数据模型设计（预览）

### Collection 1: `stock_basics` - 股票基础信息
```javascript
{
  "_id": ObjectId,
  "stock_code": "600519",
  "stock_name": "贵州茅台",
  "market": "SH",
  "list_date": "20010827",
  "delist_date": null,
  "is_st": false,
  "suspend": false,
  "update_time": ISODate("2026-06-05T...")
}
```
**索引**：`{ stock_code: 1 }` (唯一), `{ market: 1 }`

---

### Collection 2: `daily_data` - 日线数据
```javascript
{
  "_id": ObjectId,
  "stock_code": "600519",
  "trade_date": "20260605",
  "open": 1800.00,
  "high": 1850.00,
  "low": 1790.00,
  "close": 1840.00,
  "volume": 1234567,
  "amount": 2234567890.12,
  "change_pct": 2.23,
  "change": 40.00,
  "amplitude": 3.35,
  "turnover": 0.85,
  "data_source": "tushare",
  "update_time": ISODate("2026-06-05T...")
}
```
**索引**：
- `{ stock_code: 1, trade_date: -1 }` (复合唯一索引)
- `{ trade_date: -1 }`

---

### Collection 3: `index_basics` - 指数基础信息
```javascript
{
  "_id": ObjectId,
  "index_code": "000001",
  "index_name": "上证指数",
  "market": "SH",
  "update_time": ISODate("2026-06-05T...")
}
```
**索引**：`{ index_code: 1 }` (唯一)

---

### Collection 4: `stock_universe` - 股票池
```javascript
{
  "_id": ObjectId,
  "trade_date": "20260605",
  "stock_code": "600519",
  "in_universe": true,
  "reason": null,
  "update_time": ISODate("2026-06-05T...")
}
```
**索引**：`{ trade_date: 1, stock_code: 1 }` (唯一), `{ trade_date: 1 }`

---

### Collection 5: `factor_results` - 因子计算结果
```javascript
{
  "_id": ObjectId,
  "trade_date": "20260605",
  "factor_name": "cr5_percent",
  "stock_code": null,
  "factor_value": 38.5,
  "update_time": ISODate("2026-06-05T...")
}
```
**索引**：`{ trade_date: 1, factor_name: 1, stock_code: 1 }` (唯一)

---

### Collection 6: `backtest_results` - 回测结果
```javascript
{
  "_id": ObjectId,
  "strategy_name": "MA策略",
  "start_date": "20250101",
  "end_date": "20260605",
  "initial_capital": 1000000.0,
  "final_capital": 1234567.89,
  "total_return": 0.2345,
  "annual_return": 0.18,
  "max_drawdown": 0.12,
  "sharpe_ratio": 1.5,
  "win_rate": 0.55,
  "total_trades": 45,
  "equity_curve": [...],
  "trade_logs": [...],
  "create_time": ISODate("2026-06-05T...")
}
```
**索引**：`{ create_time: -1 }`

---

## 📚 数据源调度策略

### 优先级说明
1. **Tushare**（首选）：数据质量最高，API 最稳定
2. **AkShare**（备选）：Tushare 不可用时使用
3. **baostock**（补充）：前两者都不可用时使用

### 降级逻辑
```
尝试 Tushare → 成功 → 返回数据
         ↓ 失败
尝试 AkShare → 成功 → 返回数据
         ↓ 失败
尝试 baostock → 成功 → 返回数据
         ↓ 失败
返回错误（绝不生成假数据）
```

---

## 📦 更新的依赖（requirements.txt）

**新增**：
```
tushare>=1.2.0
pymongo>=4.0.0
python-dotenv>=1.0.0
```

**保留现有**：
```
akshare>=1.12.0
baostock>=0.9.0
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
... (其他现有依赖)
```

---

## 🔒 环境变量配置（.env）

```env
# Tushare 配置
TUSHARE_TOKEN=fc1a8187d58a712945ebe9d190c6c83b1b369daf975efdcc052ed841

# MongoDB 配置
MONGODB_URI=mongodb://localhost:27017/
MONGODB_DB_NAME=yuquant
```

---

## 📁 新架构目录结构（变更部分）

```
YuQuant/
├── app/
│   ├── data/                    # ✨ 新增：数据层模块
│   │   ├── __init__.py
│   │   ├── db.py               # MongoDB 连接与操作封装
│   │   ├── sources/            # 数据源模块
│   │   │   ├── __init__.py
│   │   │   ├── tushare_source.py
│   │   │   ├── akshare_source.py
│   │   │   └── baostock_source.py
│   │   ├── manager.py          # ✨ 新 DataManager（替代旧版）
│   │   └── migration.py        # 数据迁移脚本
│   │
│   ├── data_manager.py         # ❌ 旧版将重写/移除
│   ├── factor_engine.py        # 保留，适配新 DataManager
│   ├── backtest_engine.py      # 保留，适配新 DataManager
│   │
│   └── server/
│       └── api/
│           └── sync.py         # 更新，适配新 DataManager
│
├── data/                       # SQLite + HDF5 保留（用于迁移）
├── .env                        # ✨ 新增：环境变量
├── .env.example               # ✨ 新增：配置模板
├── requirements.txt            # 更新：添加新依赖
└── docker-compose.yml          # 可选：MongoDB 容器配置（如需要）
```

---

## 🚨 影响仪表盘

### 受影响的代理
| 代理 | 影响程度 | 说明 |
|------|---------|------|
| **ArchitectAgent** | 高 | 需要设计新的 MongoDB Schema |
| **BackendAgent** | 极高 | 完全重写数据层 |
| **FrontendAgent** | 无 | API 接口保持不变 |
| **DeployAgent** | 中 | 可能需要 MongoDB 部署配置 |

### 受影响的文件
- `app/data_manager.py` - 完全重写
- `app/server/api/sync.py` - 适配新 DataManager
- `requirements.txt` - 添加新依赖
- 新增：`app/data/` 目录及文件
- 新增：`.env` 和 `.env.example`

### 潜在副作用
- MongoDB 需要本地安装或 Docker 运行
- 数据迁移期间可能需要停机
- 旧的 HDF5/SQLite 数据文件需要保留作为备份

---

## 🔄 下一步

**确认开始执行里程碑 1 吗？**
