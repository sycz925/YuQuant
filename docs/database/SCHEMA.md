# 数据库 Schema

## MongoDB 数据库结构

### 1. stock_basics - 股票基础信息表

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `stock_code` | String | 股票代码（如 600519） |
| `stock_name` | String | 股票名称 |
| `market` | String | 市场（SH/SZ） |
| `list_date` | String | 上市日期 |
| `delist_date` | String | 退市日期（如仍在市则为空） |
| `is_st` | Boolean | 是否 ST |
| `suspend` | Boolean | 是否停牌 |
| `update_time` | ISODate | 更新时间 |

### 2. daily_data - 日线行情数据（含RPS）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `stock_code` | String | 股票/板块代码 |
| `trade_date` | String | 交易日（YYYYMMDD） |
| `open` | Number | 开盘价 |
| `high` | Number | 最高价 |
| `low` | Number | 最低价 |
| `close` | Number | 收盘价 |
| `vol` | Number | 成交量（股票用） |
| `volume` | Number | 成交量（板块用） |
| `amount` | Number | 成交额 |
| `data_type` | String | 数据类型：stock/sector |
| `data_source` | String | 数据来源 |
| `is_final` | Boolean | 是否已收盘 |
| `rps_10` | Number | RPS 10日（板块） |
| `rps_20` | Number | RPS 20日（个股） |
| `rps_50` | Number | RPS 50日 |
| `rps_120` | Number | RPS 120日（个股） |
| `rps_250` | Number | RPS 250日（个股） |
| `update_time` | ISODate | 更新时间 |

### 3. sector_basics - 板块基础信息表

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `code` | String | 板块代码（如 880301） |
| `name` | String | 板块名称 |
| `source` | String | 来源（tdx_880/tdx_881） |
| `stock_count` | Number | 成分股数量 |
| `tdx_code` | String | 通达信代码 |
| `update_time` | ISODate | 更新时间 |

### 4. index_basics - 指数基础信息表

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `code` | String | 指数代码（如 000001） |
| `name` | String | 指数名称 |
| `market` | Number | 市场（1=沪，0=深） |
| `tdx_code` | String | 通达信代码 |
| `update_time` | ISODate | 更新时间 |

### 5. exclusions - 排除设置表

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `code` | String | 代码 |
| `code_type` | String | 类型（stock/sector/index） |
| `exclude_type` | String | 排除类型（sync/rps） |
| `reason` | String | 排除原因 |
| `update_time` | ISODate | 更新时间 |

### 6. sync_tasks - 同步任务状态表

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `task_id` | String | 任务ID |
| `status` | String | 状态 |
| `progress` | Object | 进度信息 |
| `create_time` | ISODate | 创建时间 |
| `update_time` | ISODate | 更新时间 |

---

## 索引设计

### daily_data 索引
```javascript
// 复合唯一索引：按类型、代码、日期查询
{ data_type: 1, stock_code: 1, trade_date: -1 }

// 普通索引：按日期查询
{ trade_date: -1 }
```

### stock_basics 索引
```javascript
// 唯一索引：股票代码唯一
{ stock_code: 1 }
```

### sector_basics 索引
```javascript
// 唯一索引：板块代码唯一
{ code: 1 }
```

### index_basics 索引
```javascript
// 唯一索引：指数代码唯一
{ code: 1 }
```

### exclusions 索引
```javascript
// 复合唯一索引：防止重复排除
{ code: 1, code_type: 1, exclude_type: 1 }
```

---

## 数据类型规范

### 日期格式
所有日期字段统一使用 **"YYYYMMDD"** 字符串格式（如 "20260615"），不使用 Date 类型，以保持跨数据源一致性。

### 数值类型
- 价格：Number（浮点数）
- 成交量、成交额：Number（整数或浮点数均可）
- RPS值：Number（整数，1-100，-1表示数据不足）

### 空值处理
- 字符串类型：使用 `null` 表示缺失值
- 数值类型：使用 `null` 表示缺失值
- RPS字段：使用 `-1` 表示数据不足无法计算
