# 数据迁移方案

**日期**：2026-06-05  
**项目**：YuQuant - A股量化仿真与前端看板系统

---

## 概述

本文档定义从旧存储系统（SQLite + HDF5）迁移到新存储系统（MongoDB）的详细方案。

---

## 迁移前准备

### 1. 备份原始数据位置

| 数据类型 | 原始位置 | 目标 Collection |
|---------|---------|---------------|
| 股票基础信息 | `data/sqlite/quant.db` → `stock_basics` | `stock_basics` |
| 指数基础信息 | `data/sqlite/quant.db` → `index_basics` | `index_basics` |
| 股票池 | `data/sqlite/quant.db` → `stock_universe` | `stock_universe` |
| 日线行情数据 | `data/hdf5/daily_data.h5` | `daily_data` |

### 2. 迁移步骤

1. **备份旧数据
2. **安装并启动 MongoDB
3. **创建数据库和索引
4. **迁移股票基础信息
5. **迁移指数基础信息
6. **迁移股票池数据
7. **迁移日线行情数据
8. **验证数据完整性
9. **切换系统到 MongoDB

---

## 迁移脚本设计

### 脚本结构

```python
# app/data/migration.py
├── migrate_stock_basics()   # 迁移股票基础信息
├── migrate_index_basics()  # 迁移指数基础信息
├── migrate_stock_universe()  # 迁移股票池
├── migrate_daily_data()     # 迁移日线数据
└── verify_migration()          # 验证迁移验证
```

---

## 迁移步骤详解

### 步骤1：备份旧数据

```bash
# 备份 SQLite 数据库
cp data/sqlite/quant.db data/sqlite/quant.db.backup

# 备份 HDF5 文件
cp data/hdf5/daily_data.h5 data/hdf5/daily_data.h5.backup
```

### 步骤2：启动 MongoDB

**选项A：本地安装 MongoDB

1. 下载并安装 MongoDB Community Server
2. 启动 MongoDB 服务

**选项B：使用 Docker（推荐）

```bash
docker run -d -p 27017:27017 --name mongodb-yuquant mongo:latest
```

### 步骤3：创建数据库和索引

```python
from pymongo import MongoClient, ASCENDING, DESCENDING

# 连接
client = MongoClient('mongodb://localhost:27017/')
db = client['yuquant']

# 创建索引
db['stock_basics'].create_index([('stock_code', ASCENDING)], unique=True)
db['stock_basics'].create_index([('market', ASCENDING)])

db['daily_data'].create_index(
    [('stock_code', ASCENDING), ('trade_date', DESCENDING)],
    unique=True
)
db['daily_data'].create_index([('trade_date', DESCENDING)])

db['index_basics'].create_index([('index_code', ASCENDING)], unique=True)

db['stock_universe'].create_index(
    [('trade_date', ASCENDING), ('stock_code', ASCENDING)],
    unique=True
)
db['stock_universe'].create_index([('trade_date', ASCENDING)])

db['factor_results'].create_index(
    [('trade_date', ASCENDING), ('factor_name', ASCENDING), ('stock_code', ASCENDING)],
    unique=True
)
db['factor_results'].create_index([('trade_date', ASCENDING)])
db['factor_results'].create_index([('factor_name', ASCENDING)])

db['backtest_results'].create_index([('create_time', DESCENDING)])
```

---

### 步骤4：迁移股票基础信息

```python
def migrate_stock_basics():
    import sqlite3
    from datetime import datetime

    # 读取 SQLite
    conn = sqlite3.connect('data/sqlite/quant.db')
    cursor = conn.cursor()

    # 查询所有数据
    cursor.execute('SELECT stock_code, stock_name, market, list_date, delist_date, is_st, suspend FROM stock_basics')
    rows = cursor.fetchall()

    # 转换并插入 MongoDB
    docs = []
    for row in rows:
        doc = {
            'stock_code': row[0],
            'stock_name': row[1],
            'market': row[2],
            'list_date': row[3],
            'delist_date': row[4],
            'is_st': bool(row[5]) if row[5] is not None else False,
            'suspend': bool(row[6]) if row[6] is not None else False,
            'update_time': datetime.utcnow()
        }
        docs.append(doc)

    if docs:
        db['stock_basics'].insert_many(docs)

    conn.close()
    print(f"迁移股票基础信息: {len(docs)} 条")
```

---

### 步骤5：迁移指数基础信息

```python
def migrate_index_basics():
    import sqlite3
    from datetime import datetime

    conn = sqlite3.connect('data/sqlite/quant.db')
    cursor = conn.cursor()

    cursor.execute('SELECT index_code, index_name, market FROM index_basics')
    rows = cursor.fetchall()

    docs = []
    for row in rows:
        doc = {
            'index_code': row[0],
            'index_name': row[1],
            'market': row[2],
            'update_time': datetime.utcnow()
        }
        docs.append(doc)

    if docs:
        db['index_basics'].insert_many(docs)

    conn.close()
    print(f"迁移指数基础信息: {len(docs)} 条")
```

---

### 步骤6：迁移股票池

```python
def migrate_stock_universe():
    import sqlite3
    from datetime import datetime

    conn = sqlite3.connect('data/sqlite/quant.db')
    cursor = conn.cursor()

    cursor.execute('SELECT trade_date, stock_code, in_universe, reason FROM stock_universe')
    rows = cursor.fetchall()

    docs = []
    for row in rows:
        doc = {
            'trade_date': row[0],
            'stock_code': row[1],
            'in_universe': bool(row[2]) if row[2] is not None else True,
            'reason': row[3],
            'update_time': datetime.utcnow()
        }
        docs.append(doc)

    if docs:
        # 分批插入，避免内存溢出
        batch_size = 1000
        for i in range(0, len(docs), batch_size):
            batch = docs[i:i+batch_size]
            db['stock_universe'].insert_many(batch)

    conn.close()
    print(f"迁移股票池: {len(docs)} 条")
```

---

### 步骤7：迁移日线数据

```python
def migrate_daily_data():
    import h5py
    import pandas as pd
    from datetime import datetime

    # 打开 HDF5 文件
    with h5py.File('data/hdf5/daily_data.h5', 'r') as f:
        if '/daily' not in f:
            print("没有日线数据")
            return

        daily_group = f['/daily']
        total_count = 0

        # 遍历每只股票
        for stock_code in daily_group.keys():
            subgroup = daily_group[stock_code]

            # 读取数据
            data = {}
            for col in subgroup.keys():
                data[col] = subgroup[col][:]
            df = pd.DataFrame(data)

            if 'index' in df.columns:
                df['trade_date'] = df['index'].astype(str)
                df = df.set_index('trade_date')
            else:
                continue

            # 构建文档列表
            docs = []
            for trade_date, row in df.iterrows():
                doc = {
                    'stock_code': stock_code,
                    'trade_date': str(trade_date),
                    'open': float(row['open']) if pd.notna(row['open']) else None,
                    'high': float(row['high']) if pd.notna(row['high']) else None,
                    'low': float(row['low']) if pd.notna(row['low']) else None,
                    'close': float(row['close']) if pd.notna(row['close']) else None,
                    'volume': float(row['volume']) if pd.notna(row['volume']) else None,
                    'amount': float(row['amount']) if pd.notna(row['amount']) else None,
                    'change_pct': float(row['change_pct']) if 'change_pct' in row and pd.notna(row['change_pct']) else None,
                    'change': float(row['change']) if 'change' in row and pd.notna(row['change']) else None,
                    'amplitude': float(row['amplitude']) if 'amplitude' in row and pd.notna(row['amplitude']) else None,
                    'turnover': float(row['turnover']) if 'turnover' in row and pd.notna(row['turnover']) else None,
                    'data_source': 'migrated',  # 标记为迁移数据
                    'update_time': datetime.utcnow()
                }
                docs.append(doc)

            if docs:
                # 批量插入
                db['daily_data'].insert_many(docs)
                total_count += len(docs)

        print(f"迁移日线数据: {total_count} 条")
```

---

### 步骤8：验证数据完整性

```python
def verify_migration():
    """验证迁移是否成功"""
    # 检查计数
    print("=== 验证迁移结果 ===")

    # 股票基础信息：", db['stock_basics'].count_documents({}), "条")
    print("指数基础信息：", db['index_basics'].count_documents({}), "条")
    print("股票池：", db['stock_universe'].count_documents({}), "条")
    print("日线数据：", db['daily_data'].count_documents({}), "条")

    # 检查峰岹科技是否有数据
    fengtiao_count = db['daily_data'].count_documents({'stock_code': '688279'})
    print(f"峰岹科技日线数据：{fengtiao_count} 条")

    if fengtiao_count > 0:
        sample = db['daily_data'].find_one({'stock_code': '688279'}, sort=[('trade_date', -1)])
        print("最新一条数据：", sample)
```

---

## 回滚方案

如果迁移失败，可以通过备份恢复：

1. 停止系统回滚到使用旧数据
2. 从备份恢复旧数据
3. 检查问题
4. 重新迁移

---

## 迁移检查清单

- [ ] 备份旧数据
- [ ] MongoDB 运行正常
- [ ] 索引创建完成
- [ ] 股票基础信息迁移完成
- [ ] 指数基础信息迁移完成
- [ ] 股票池数据迁移完成
- [ ] 日线数据迁移完成
- [ ] 数据验证通过
- [ ] 系统切换到 MongoDB
