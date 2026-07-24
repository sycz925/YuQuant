# 数据源调度策略

审计日期：2026-07-24

---

## 概述

本文档定义 A股量化系统 的数据源调度策略，包括优先级、降级逻辑、各数据源的接口调用方式等。

---

## 数据源优先级

| 优先级 | 数据源 | 说明 | 稳定性 | 数据质量 |
|--------|--------|------|--------|---------|
| 1 | **PyTdX** | 通达信协议直连，板块文件解析 + 板块指数K线 + 个股日线 | 高 | 高 |
| 2 | **AkShare** | Web API，股票基础信息回退，个股日线回退 | 中（反爬限制） | 中 |
| 3 | **BaoStock** | 免费证券数据，个股日线回退 | 高 | 中 |
| 4 | **yfinance** | Yahoo Finance，最后备用（港股/美股ADR） | 中 | 低 |

> **注意**：旧文档中提到的 Tushare 和 TqCenter 在当前架构中已不再作为主用数据源。PyTdX 是实际主数据源。

---

## 降级逻辑

```
┌──────────────────┐
│  尝试 PyTdX      │  ──成功──→ 返回数据
└────────┬─────────┘
         │ 失败
         ↓
┌──────────────────┐
│  尝试 AkShare    │  ──成功──→ 返回数据
└────────┬─────────┘
         │ 失败
         ↓
┌──────────────────┐
│  尝试 BaoStock   │  ──成功──→ 返回数据
└────────┬─────────┘
         │ 失败
         ↓
┌──────────────────┐
│  尝试 yfinance   │  ──成功──→ 返回数据
└────────┬─────────┘
         │ 失败
         ↓
     返回错误
  （绝不生成假数据）
```

---

## 各数据源详细说明

### 1. PyTdX（主数据源）

#### 核心能力
```python
PytdxSource.
├── get_concept_blocks()       # block_gn.dat → 246 概念板块
├── get_industry_blocks()      # block_zs.dat → 108 行业板块
├── get_style_blocks()         # block_fg.dat → 50 风格板块
├── get_tdx_index_daily()      # 880XXX / 881XXX 板块指数日线
├── get_stock_daily()          # 个股日线
└── get_stock_basics()         # 股票基础信息
```

#### 服务器列表
```python
TDX_SERVERS = [
    ('180.153.18.170', 7709),   # 通达信上海主站
    ('119.147.212.81', 7709),   # 通达信深圳主站
    ('112.74.214.43',  7709),   # 备用1
    ('121.14.110.194', 7709),   # 备用2
]
```

#### 板块名称 → 指数代码智能匹配
6层匹配策略：精确匹配 → 别名映射（900+条 BLOCK_ALIAS_MAP）→ 去括号 → 去后缀 → 包含关系 → 别名包含

当前 354 个板块中约 41 个可匹配到 880/881 指数代码获得直接日线。

#### 日线数据
- 个股日线：`get_security_bars()` 循环获取，根据代码首字符判断市场（6/8/9→沪市，其他→深市）
- 板块指数日线：`get_index_bars(9, market, tdx_code)` 每次最多800条

---

### 2. AkShare（备选数据源）

#### 获取股票列表
```python
import akshare as ak
df = ak.stock_info_a_code_name()  # A股列表
```

#### 获取日线行情
```python
df = ak.stock_zh_a_hist(symbol='600519', period='daily',
                         start_date='20250101', end_date='20250605',
                         adjust='hfq')
```

---

### 3. BaoStock（补充数据源）

#### 获取日线行情
```python
import baostock as bs
lg = bs.login()
rs = bs.query_history_k_data_plus("sh.600519",
    "date,open,high,low,close,volume,amount",
    start_date="2025-01-01", end_date="2025-06-05",
    frequency="d", adjustflag="3")
bs.logout()
```

---

### 4. yfinance（最后备用）

用于获取港股/美股 ADR 数据，非 A 股核心数据源。

---

## 股票代码格式转换

| 市场 | 原始格式 | 标准格式 |
|------|---------|---------|
| 上交所 | `600519`（PyTdX/AkShare） | `600519` |
| 上交所 | `sh.600519`（BaoStock） | `600519` |
| 深交所 | `000001`（PyTdX/AkShare） | `000001` |
| 深交所 | `sz.000001`（BaoStock） | `000001` |

上证：6/8/9 开头；深证：0/3 开头（含创业板 300/301）

---

## 数据来源标记

所有存储到 MongoDB 的数据必须标记 `data_source` 字段，值为：
- `"pytdx"` / `"akshare"` / `"baostock"` / `"yfinance"`

板块日线额外标记 `data_type` 字段：
- `"stock"` = 个股，`"sector"` = 板块，`"index"` = 指数

## 错误处理策略

| 数据源 | 重试次数 | 间隔 | 失败行为 |
|--------|---------|------|---------|
| PyTdX | 2 | 1秒 | 降级到 AkShare |
| AkShare | 2 | 2秒 | 降级到 BaoStock |
| BaoStock | 2 | 1秒 | 降级到 yfinance |
| yfinance | 1 | 1秒 | 返回错误 |
