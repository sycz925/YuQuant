# 数据管理器功能文档

审计日期：2026-07-24

## 概述

数据管理器（`app/data/manager.py` - `DataManager` 类）负责多数据源同步编排，是整个量化系统的核心数据入口。

当前系统纯 MongoDB 架构，无 SQLite / HDF5 依赖。

---

## DataManager 核心功能

### 数据同步

#### 股票基础信息同步
```python
from app.data.manager import DataManager
dm = DataManager()
dm.sync_stock_basics()  # PyTdX → AkShare → BaoStock
```

#### 个股日线同步
```python
dm.sync_daily_data(
    stock_codes=["000001", "000002"],
    end_date="20241231",
    max_workers=10      # 多线程并行
)
```
逐天回溯模式，返回 `{total, success, fail, skipped, sources}`。

#### 板块日线同步
```python
dm.sync_sector_indices(
    enabled_codes=["SECTOR_半导体", ...],
    task_id="..."
)
```
边找边同步模式：扫描 block_*.dat → 匹配 880/881 指数 → 下载日线 → upsert。

### RPS 计算
```python
dm.calculate_rps(target='all')    # target: 'all' / 'stock' / 'sector'
```

### 衍生字段计算
```python
dm.calculate_chg_fields(target='all', trade_date='20260615')
dm.calculate_all_derived_fields(target='all', trade_date=None, backfill=False)
```

### 数据查询
```python
dm.get_stock_list()      → pd.DataFrame  # 股票列表
dm.get_index_list()      → pd.DataFrame  # 指数列表
dm.get_stock_daily_data(code, start, end) → pd.DataFrame  # 个股日线
dm.has_daily_data(code)  → bool  # 是否有日线数据
```

---

## 数据源优先级

| 优先级 | 数据源 | 用途 |
|--------|--------|------|
| 1 | **PyTdX** | 通达信协议直连（个股日线、板块日线、基础信息） |
| 2 | **AkShare** | Web API（基础信息回退） |
| 3 | **BaoStock** | 个股日线回退 |
| 4 | **yfinance** | 最后备用（港股/美股ADR） |

---

## MongoDB 集合

| 集合 | 用途 |
|------|------|
| `stock_basics` | 股票基础信息 |
| `index_basics` | 指数基础信息 |
| `stock_daily` | 个股日线行情（含RPS/MA/CHG/百分位） |
| `sector_daily` | 板块日线行情（含RPS/MA/CHG/NH-NL） |
| `index_daily` | 指数日线行情（含PE_TTM） |
| `base_data_daily` | 预计算基础指标（CR5/CR10/MA/NH-NL） |
| `market_daily` | 盘后快照（总览+聚类+AI分析） |
| `exclusions` | 排除管理 |
| `sync_tasks` | 同步任务状态 |

---

## Factory + Orchestrator 关系

DataManager 底层被 Factories 调用，而 Factories 又被 Orchestrators 编排：

```
API 路由 → Orchestrators → Factories → DataManager → MongoDB / Data Sources
```

各 Factory 封装单一领域的同步逻辑：
- `IndexFactory` - 指数同步与计算
- `StockFactory` - 个股同步与计算
- `SectorFactory` - 板块同步与计算
- `MarketAggregator` - 跨域聚合
