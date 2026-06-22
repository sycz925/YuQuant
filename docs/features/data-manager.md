# 数据管理器功能文档

## 概述

数据管理器（DataManager）负责数据获取、缓存、清洗和复权处理，是整个量化系统的基础模块。

## 版本说明

- **新版 (推荐)**: `app.data.manager.DataManager` - 基于 MongoDB
- **旧版 (已废弃)**: `app.data_manager.DataManager` - 基于 SQLite + HDF5

---

## 新版数据管理器 (MongoDB)

### 核心功能

#### 1. 数据同步

##### 股票基础信息同步
```python
from app.data.manager import DataManager

dm = DataManager()
dm.sync_stock_basics()
```

##### 日线数据同步
```python
dm.sync_daily_data(
    stock_codes=["000001", "000002"],
    start_date="20240101",
    end_date="20241231"
)
```

##### 板块数据同步
```python
dm.sync_sector_indices(
    start_date="20240101",
    end_date="20241231"
)
```

#### 2. 数据获取

##### 获取股票列表
```python
stock_df = dm.get_stock_list()
```

##### 获取日线数据
```python
df = dm.get_stock_daily_data(
    stock_code="000001",
    start_date="20240101",
    end_date="20241231"
)
```

##### 获取指数列表
```python
index_df = dm.get_index_list()
```

#### 3. RPS 计算

```python
# 计算个股RPS
result = dm.calculate_rps(target='stock')

# 计算板块RPS
result = dm.calculate_rps(target='sector')

# 计算全部RPS
result = dm.calculate_rps(target='all')
```

### 数据存储

#### MongoDB 集合

| 集合 | 用途 |
|------|------|
| `stock_basics` | 股票基础信息 |
| `daily_data` | 日线行情数据（含RPS） |
| `sector_basics` | 板块基础信息 |
| `index_basics` | 指数基础信息 |
| `exclusions` | 排除设置 |
| `sync_tasks` | 同步任务状态 |

---

## 旧版数据管理器 (已废弃)

⚠️ **注意**: 以下内容仅用于兼容旧代码，新项目请使用 MongoDB 版本。

### 数据存储

#### SQLite 数据库
- `stock_basics`: 股票基础信息
- `index_basics`: 指数基础信息

#### HDF5 文件
- `daily_data.h5`: 存储所有股票的日线数据（后复权）

### 基本用法
```python
from app.data_manager import DataManager

dm = DataManager("data/sqlite/quant.db", "data/hdf5")
dm.sync_stock_basics()
```
