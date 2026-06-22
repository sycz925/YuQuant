# MongoDB 数据模型设计

**日期**：2026-06-18 (更新)  
**项目**：YuQuant - A股量化仿真与前端看板系统

---

## 概述

本文档定义 YuQuant 系统在 MongoDB 中的数据模型。

---

## Collection 1: `stock_basics` - 股票基础信息

### 用途
存储所有 A 股股票的基础信息，包括股票代码、名称、市场、上市日期等。

### Schema
```javascript
{
  _id: ObjectId,
  stock_code: String,        // 股票代码，如 "600519"
  stock_name: String,        // 股票名称，如 "贵州茅台"
  market: String,            // 市场："SH"（上交所）或 "SZ"（深交所）
  list_date: String | null,  // 上市日期，格式 "YYYYMMDD"
  delist_date: String | null,// 退市日期，如仍在市则为 null
  is_st: Boolean,            // 是否为 ST 股票
  suspend: Boolean,          // 是否停牌
  update_time: ISODate       // 最后更新时间
}
```

### 索引设计
| 索引 | 类型 | 说明 |
|------|------|------|
| `{ stock_code: 1 }` | 唯一索引 | 股票代码唯一 |
| `{ market: 1 }` | 普通索引 | 按市场查询 |

---

## Collection 2: `stock_daily` - 个股日线行情数据（含RPS+冗余字段）

### 用途
存储股票的日线行情数据，包括 OHLCV、RPS指标、以及预计算的冗余字段。

### Schema
```javascript
{
  _id: ObjectId,
  stock_code: String,            // 股票代码
  trade_date: String,            // 交易日，格式 "YYYYMMDD"
  open: Number,                  // 开盘价
  high: Number,                  // 最高价
  low: Number,                   // 最低价
  close: Number,                 // 收盘价
  vol: Number,                   // 成交量（股）
  amount: Number,                // 成交额（元）
  data_source: String,           // 数据来源："pytdx" / "akshare" / "baostock"
  is_final: Boolean,             // 是否已收盘数据

  // RPS指标
  rps_20: Number | null,         // RPS 20日周期
  rps_50: Number | null,         // RPS 50日周期
  rps_120: Number | null,        // RPS 120日周期
  rps_250: Number | null,        // RPS 250日周期

  // 涨跌幅（预计算）
  chg_pct: Number | null,        // 日涨跌幅(%) = (close-prev_close)/prev_close*100

  // RPS衍生指标
  rps_sum: Number | null,        // RPS总分 = rps_20+rps_50+max(rps_120,rps_250)
  is_active: Boolean | null,     // 是否活跃股 = rps_sum>270 && chg_pct>5%

  // 百分位指标
  close_pct: Number | null,      // 股价百分位(1-100)
  amount_pct: Number | null,     // 成交额百分位(1-100)

  // 均线指标
  ma10: Number | null,           // 10日移动平均线
  ma20: Number | null,           // 20日移动平均线
  ma50: Number | null,           // 50日移动平均线
  ma120: Number | null,          // 120日移动平均线

  // 成交量均线
  vol_ma5: Number | null,        // 5日成交量均线
  vol_ma10: Number | null,       // 10日成交量均线
  vol_ma20: Number | null,       // 20日成交量均线
  vol_ma50: Number | null,       // 50日成交量均线

  // 区间涨幅
  chg_5d: Number | null,         // 5日涨幅(%)
  chg_10d: Number | null,        // 10日涨幅(%)
  chg_20d: Number | null,        // 20日涨幅(%)
  chg_50d: Number | null,        // 50日涨幅(%)
  chg_120d: Number | null,       // 120日涨幅(%)
  chg_250d: Number | null,       // 250日涨幅(%)

  update_time: ISODate           // 最后更新时间
}
```

### 索引设计
| 索引 | 类型 | 说明 |
|------|------|------|
| `{ stock_code: 1, trade_date: -1 }` | 复合索引 | 按代码、日期查询 |
| `{ trade_date: -1 }` | 普通索引 | 按日期查询 |
| `{ trade_date: 1, is_active: 1 }` | 普通索引 | 活跃股快速查询 |
| `{ trade_date: 1, rps_sum: -1 }` | 普通索引 | 按RPS总分排序 |

---

## Collection 3: `sector_daily` - 板块日线行情数据（含RPS+冗余字段）

### 用途
存储板块的日线行情数据，包括 OHLCV、RPS指标、以及预计算的冗余字段。

### Schema
```javascript
{
  _id: ObjectId,
  stock_code: String,            // 板块代码
  trade_date: String,            // 交易日，格式 "YYYYMMDD"
  open: Number,                  // 开盘价
  high: Number,                  // 最高价
  low: Number,                   // 最低价
  close: Number,                 // 收盘价
  volume: Number,                // 成交量（股）
  amount: Number,                // 成交额（元）
  data_source: String,           // 数据来源
  is_final: Boolean,             // 是否已收盘数据

  // RPS指标
  rps_10: Number | null,         // RPS 10日周期
  rps_20: Number | null,         // RPS 20日周期
  rps_50: Number | null,         // RPS 50日周期

  // 涨跌幅（预计算）
  chg_pct: Number | null,        // 日涨跌幅(%)

  // 均线指标
  ma10: Number | null,           // 10日移动平均线
  ma20: Number | null,           // 20日移动平均线
  ma50: Number | null,           // 50日移动平均线

  // 成交量均线
  vol_ma5: Number | null,        // 5日成交量均线
  vol_ma10: Number | null,       // 10日成交量均线
  vol_ma20: Number | null,       // 20日成交量均线

  // 区间涨幅
  chg_5d: Number | null,         // 5日涨幅(%)
  chg_10d: Number | null,        // 10日涨幅(%)
  chg_20d: Number | null,        // 20日涨幅(%)
  chg_50d: Number | null,        // 50日涨幅(%)
  chg_120d: Number | null,       // 120日涨幅(%)
  chg_250d: Number | null,       // 250日涨幅(%)

  update_time: ISODate           // 最后更新时间
}
```

### 索引设计
| 索引 | 类型 | 说明 |
|------|------|------|
| `{ stock_code: 1, trade_date: -1 }` | 复合索引 | 按代码、日期查询 |
| `{ trade_date: -1 }` | 普通索引 | 按日期查询 |

---

## Collection 4: `sector_basics` - 板块基础信息

### 用途
存储行业板块和概念板块的基础信息。

### Schema
```javascript
{
  _id: ObjectId,
  code: String,                  // 板块代码，如 "880301"
  name: String,                  // 板块名称
  source: String,                // 来源："tdx_880" / "tdx_881"
  stock_count: Number,           // 成分股数量
  tdx_code: String,              // 通达信代码
  update_time: ISODate           // 最后更新时间
}
```

### 索引设计
| 索引 | 类型 | 说明 |
|------|------|------|
| `{ code: 1 }` | 唯一索引 | 板块代码唯一 |

---

## Collection 5: `index_basics` - 指数基础信息

### 用途
存储常用指数的基础信息。

### Schema
```javascript
{
  _id: ObjectId,
  code: String,                  // 指数代码，如 "000001"
  name: String,                  // 指数名称，如 "上证指数"
  market: Number,                // 市场：1=沪市，0=深市
  tdx_code: String,              // 通达信代码
  update_time: ISODate           // 最后更新时间
}
```

### 索引设计
| 索引 | 类型 | 说明 |
|------|------|------|
| `{ code: 1 }` | 唯一索引 | 指数代码唯一 |

---

## Collection 6: `exclusions` - 排除设置

### 用途
存储用户配置的排除规则，用于同步和RPS计算时过滤特定代码。

### Schema
```javascript
{
  _id: ObjectId,
  code: String,                  // 代码（股票/板块/指数）
  code_type: String,             // 类型："stock" / "sector" / "index"
  exclude_type: String,          // 排除类型："sync" / "rps"
  reason: String | null,         // 排除原因
  update_time: ISODate           // 最后更新时间
}
```

### 索引设计
| 索引 | 类型 | 说明 |
|------|------|------|
| `{ code: 1, code_type: 1, exclude_type: 1 }` | 复合唯一索引 | 防止重复排除 |

---

## Collection 7: `sync_tasks` - 同步任务状态

### 用途
存储后台同步任务的状态和进度。

### Schema
```javascript
{
  _id: ObjectId,
  task_id: String,               // 任务ID
  status: String,                // 状态："pending" / "running" / "completed" / "failed"
  progress: {
    total_count: Number,         // 总数
    completed_count: Number,     // 已完成数
    failed_count: Number,        // 失败数
    skipped_count: Number,       // 跳过数
    current_stock: String,       // 当前处理的代码
    current_stock_name: String,  // 当前处理的名称
    sources: Object              // 数据源统计
  },
  create_time: ISODate,          // 创建时间
  update_time: ISODate           // 更新时间
}
```

---

## 数据库配置

### 连接信息
```
MONGODB_URI=mongodb://localhost:27017/
MONGODB_DB_NAME=yuquant
```

### 数据库命名
- **数据库名**：`yuquant`
- **所有 collection 名称**：小写加下划线（snake_case）

---

## 数据类型规范

### 日期格式
所有日期字段统一使用 **"YYYYMMDD"** 字符串格式（如 "20260615"），不使用 Date 类型，以保持跨数据源一致性。

### 数值类型
- 价格：Number（浮点数）
- 成交量、成交额：Number（整数或浮点数均可）
- RPS值：Number（整数，1-100，-1表示数据不足）
- 百分位：Number（整数，1-100）
- 均线：Number（浮点数，保留2位小数）

### 空值处理
- 字符串类型：使用 `null` 表示缺失值
- 数值类型：使用 `null` 表示缺失值（注意：MongoDB 对 null 可以正常索引）
- RPS字段：使用 `-1` 表示数据不足无法计算
- 冗余字段：数据不足时记为 `null`，不影响查询
