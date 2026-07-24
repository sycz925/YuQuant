# MongoDB 集合定义

审计日期：2026-07-24

## 集合总览

| 序号 | 集合名 | 用途 | 文档数（典型） |
|------|--------|------|----------------|
| 1 | `stock_basics` | 个股基础信息 | ~5,000 |
| 2 | `stock_daily` | 个股日线行情 + RPS + 衍生字段 | ~7-8M |
| 3 | `sector_basics` | 板块基础信息（成分股列表） | ~350 |
| 4 | `sector_daily` | 板块日线行情 + RPS + NH/NL | ~60K |
| 5 | `index_basics` | 指数基础信息 | ~10 |
| 6 | `index_daily` | 指数日线行情 + PE_TTM | ~20K |
| 7 | `base_data_daily` | 预计算基础指标（CR5/MA/NH-NL） | ~2K |
| 8 | `market_daily` | 盘后快照 + 聚类 + AI分析 | ~2K |
| 9 | `exclusions` | 排除管理（板块/指数/个股） | ~50 |
| 10 | `sync_tasks` | 同步任务状态 | 运行时临时 |

---

## 1. stock_basics - 个股基础信息

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

索引：`{ stock_code: 1 }` 唯一

---

## 2. stock_daily - 个股日线行情

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `stock_code` | String | 股票代码 |
| `trade_date` | String | 交易日（YYYYMMDD） |
| `open/high/low/close` | Number | OHLC |
| `vol` | Number | 成交量（股） |
| `amount` | Number | 成交额（元） |
| `data_source` | String | pytdx/akshare/baostock |
| `is_final` | Boolean | 是否已收盘 |
| `chg_pct` | Number | 日涨跌幅(%) |
| `rps_20/50/120/250` | Number | RPS多周期 |
| `rps_sum` | Number | RPS总分 |
| `is_active` | Boolean | 是否活跃股 |
| `close_pct/amount_pct` | Number | 百分位 |
| `ma10/20/50/120` | Number | 均线 |
| `vol_ma5/10/20/50` | Number | 成交量均线 |
| `chg_5d/10d/20d/50d/120d/250d` | Number | 区间涨幅 |
| `update_time` | ISODate | 更新时间 |

索引：`{ stock_code: 1, trade_date: -1 }` 复合

---

## 3. sector_basics - 板块基础信息

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `code` | String | 板块代码（SECTOR_板块名） |
| `name` | String | 板块名称 |
| `source` | String | 概念/行业/东方财富 |
| `stock_count` | Number | 成分股数量 |
| `stock_codes` | Array | 成分股代码列表 |
| `tdx_code` | String | 通达信指数代码 |
| `update_time` | ISODate | 更新时间 |

索引：`{ code: 1 }` 唯一

---

## 4. sector_daily - 板块日线行情

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `stock_code` | String | 板块代码（SECTOR_板块名） |
| `trade_date` | String | 交易日（YYYYMMDD） |
| `open/high/low/close` | Number | OHLC |
| `volume` | Number | 成交量 |
| `amount` | Number | 成交额 |
| `data_source` | String | 数据来源 |
| `is_final` | Boolean | 是否已收盘 |
| `chg_pct` | Number | 日涨跌幅(%) |
| `rps_10/20/50` | Number | RPS多周期 |
| `ma10/20/50` | Number | 均线 |
| `chg_5d/10d/20d/50d/120d/250d` | Number | 区间涨幅 |
| `nh/nl` | Number | 板块内新高/新低股票数 |
| `update_time` | ISODate | 更新时间 |

索引：`{ stock_code: 1, trade_date: -1 }` 复合

---

## 5. index_basics - 指数基础信息

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `code` | String | 指数代码（如 000001） |
| `name` | String | 指数名称 |
| `market` | Number | 市场（1=沪，0=深） |
| `tdx_code` | String | 通达信代码 |
| `is_disable` | Boolean | 是否禁用 |
| `update_time` | ISODate | 更新时间 |

索引：`{ code: 1 }` 唯一

---

## 6. index_daily - 指数日线行情

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `stock_code` | String | 指数代码 |
| `trade_date` | String | 交易日 |
| `open/high/low/close` | Number | OHLC |
| `volume` | Number | 成交量 |
| `amount` | Number | 成交额 |
| `chg_pct` | Number | 日涨跌幅 |
| `pe_ttm` | Number | 市盈率（乐咕乐股） |
| `data_source` | String | 数据来源 |
| `is_final` | Boolean | 是否已收盘 |
| `update_time` | ISODate | 更新时间 |

索引：`{ stock_code: 1, trade_date: -1 }` 复合

---

## 7. base_data_daily - 预计算基础指标

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `date` | String | 交易日（YYYYMMDD，主键字段名 date 非 trade_date） |
| `cr5_pct` | Number | 个股成交额前5%拥挤度 |
| `cr10_pct` | Number | 板块成交额前10%拥挤度 |
| `ma50_pct` | Number | 站上MA50比例 |
| `ma20_pct` | Number | 站上MA20比例 |
| `nh` | Number | 250日新高股票数 |
| `nl` | Number | 250日新低股票数 |
| `is_final` | Boolean | 是否收盘后最终数据 |

索引：`{ date: 1 }` 唯一

---

## 8. market_daily - 盘后快照

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `trade_date` | String | 交易日 |
| `overview` | Object | 大盘指数涨跌幅 + PE_TTM |
| `new_high` | Object | 新高板块聚类 Top10 |
| `low_position_sectors` | Object | 低位潜力板块 Top5 |
| `active_sectors` | Object | 异动活跃板块 |
| `group_stats` | Object | 分组统计数据 |
| `ai_analysis` | Object | DeepSeek AI 研判结果 |
| `is_final` | Boolean | 是否收盘后数据 |

索引：`{ trade_date: 1 }` 唯一

---

## 9. exclusions - 排除管理

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `code` | String | 板块/指数/个股代码 |
| `name` | String | 名称 |
| `category` | String | 类别（sector/index/stock） |
| `exclude_display` | Boolean | 是否在展示中排除 |
| `exclude_sync` | Boolean | 是否在同步中排除 |
| `exclude_rps` | Boolean | 是否在RPS计算中排除 |
| `update_time` | ISODate | 更新时间 |

---

## 10. sync_tasks - 同步任务状态

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `task_id` | String | 任务ID |
| `status` | String | pending/running/completed/failed |
| `progress` | Object | 进度信息 |
| `create_time` | ISODate | 创建时间 |
| `update_time` | ISODate | 更新时间 |

---

## 索引设计汇总

| 集合 | 索引 | 类型 |
|------|------|------|
| stock_daily | `{ stock_code: 1, trade_date: -1 }` | 复合 |
| stock_daily | `{ trade_date: -1 }` | 普通 |
| sector_daily | `{ stock_code: 1, trade_date: -1 }` | 复合 |
| index_daily | `{ stock_code: 1, trade_date: -1 }` | 复合 |
| base_data_daily | `{ date: 1 }` | 唯一 |
| market_daily | `{ trade_date: 1 }` | 唯一 |
| stock_basics | `{ stock_code: 1 }` | 唯一 |
| sector_basics | `{ code: 1 }` | 唯一 |
| index_basics | `{ code: 1 }` | 唯一 |
| exclusions | `{ code: 1 }` | 唯一 |

---

## 数据类型规范

- **日期格式**：统一使用 "YYYYMMDD" 字符串格式
- **价格**：Number（浮点数）
- **RPS值**：Number（整数，1-100，-1表示数据不足）
- **字符串缺失**：`null`
- **数值缺失**：`null`（RPS 用 -1）
