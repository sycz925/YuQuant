# 因子引擎功能文档

审计日期：2026-07-24

## 概述

因子引擎（`app/engine/factor_engine.py` - `FactorEngine` 类）负责全市场维度的技术指标与因子计算。

当前系统纯 MongoDB 架构，无 HDF5 依赖。

## 核心功能

### 1. RPS 相对强度计算

支持多周期 RPS 计算（10/20/50/120/250 日），写入 `stock_daily` / `sector_daily` 的 `rps_10` ~ `rps_250` 字段。

```python
from app.engine.factor_engine import FactorEngine
from app.data.db import get_db

db = get_db()
fe = FactorEngine(db)
result = fe.calculate_rps(stock_codes=["000001", "000002"])
```

过滤规则：
- 个股：上市满 120 个交易日才参与 RPS 截面排名
- 板块：日线数据满 20 条才参与 RPS 排名

### 2. 均线计算

```python
fe.calculate_ma(target='stock', trade_date='20260615')
# 计算 MA10/20/50/120 + VOL_MA5/10/20/50
# 写入 stock_daily / sector_daily 对应字段
```

### 3. 涨幅计算

```python
fe.calculate_chg_fields(target='stock', trade_date='20260615')
# 计算 chg_pct, chg_5d ~ chg_250d
```

### 4. CR5%/CR10% 计算

在 MarketAggregator 中通过 `precompute_base_data()` 触发：

```python
from app.server.factories.market_aggregator import MarketAggregator
aggregator = MarketAggregator()
result = aggregator.precompute_base_data(target_date='20260615')
# 计算 CR5/CR10/MA占比/NH-NL → 写入 base_data_daily
```

## 调用入口

API 层统一通过 Factory 间接调用因子引擎：
- `POST /api/factors/rps/calculate` → StockFactory/SectorFactory.compute_rps()
- `POST /api/factors/precompute-base` → MarketAggregator.precompute_base_data()

所有预计算结果存入 `base_data_daily`（基础指标）和 `market_daily`（聚类/AI分析）。
