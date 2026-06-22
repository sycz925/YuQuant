# 因子引擎功能文档

## 概述

因子引擎（FactorEngine）负责技术指标和因子计算，包括 CR5% 拥挤度因子、移动平均线等。

## 核心功能

### 1. CR5% 拥挤度因子

计算每日成交额前 5% 股票的成交额占全市场的比例，用于判断市场拥挤度。

```python
from app.data_manager import DataManager
from app.factor_engine import FactorEngine

dm = DataManager("data/sqlite/quant.db", "data/hdf5")
fe = FactorEngine(dm)

cr5 = fe.calculate_cr5_percent("20241201")
```

### 2. 移动平均线（MA）

计算单只股票的移动平均线：
```python
ma20 = fe.calculate_ma("000001", "20241201", 20)
```

批量计算多只股票的 MA：
```python
ma_df = fe.batch_calculate_ma(
    stock_codes=["000001", "000002"],
    start_date="20240101",
    end_date="20241231",
    window=20
)
```

### 3. 历史 CR5% 序列

获取历史 CR5% 数据（用于可视化）：
```python
cr5_series = fe.get_all_cr5_history("20240101", "20241231")
```

### 4. 指数 MA

计算指数移动平均线：
```python
index_ma20 = fe.calculate_index_ma("000001", "20241201", 20)
```

## 数据缓存

计算结果自动缓存到 HDF5 文件，提高性能。
