# 数据源调度策略

**日期**：2026-06-05  
**项目**：YuQuant - A股量化仿真与前端看板系统

---

## 概述

本文档定义 YuQuant 系统的数据源调度策略，包括优先级、降级逻辑、各数据源的接口调用方式等。

---

## 数据源优先级

| 优先级 | 数据源 | 说明 | 稳定性 | 数据质量 |
|--------|--------|------|--------|---------|
| 1 | **Tushare** | 首选数据源，数据质量高，API 稳定 | 高 | 极高 |
| 2 | **AkShare** | 备选数据源，Tushare 不可用时使用 | 中（反爬限制） | 高 |
| 3 | **baostock** | 补充数据源，前两者都不可用时使用 | 高 | 中 |

---

## 降级逻辑

```
┌─────────────────┐
│  尝试 Tushare   │  ──成功──→ 返回数据
└────────┬────────┘
         │ 失败
         ↓
┌─────────────────┐
│  尝试 AkShare   │  ──成功──→ 返回数据
└────────┬────────┘
         │ 失败
         ↓
┌─────────────────┐
│  尝试 baostock  │  ──成功──→ 返回数据
└────────┬────────┘
         │ 失败
         ↓
    返回错误
  （绝不生成假数据）
```

---

## 各数据源详细说明

### 1. Tushare（主数据源）

#### 初始化
```python
import tushare as ts

# 设置 Token
ts.set_token('YOUR_TUSHARE_TOKEN')

# 创建 Pro 接口
pro = ts.pro_api()
```

#### 获取股票列表
```python
# 获取股票基础信息
df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name,area,industry,list_date')
```

#### 获取日线行情
```python
# 获取日线数据（后复权）
# ts_code 格式："600519.SH" / "000001.SZ"
df = pro.daily(ts_code='600519.SH', start_date='20250101', end_date='20250605')
```

#### 字段映射
| Tushare 字段 | 目标字段 | 说明 |
|-------------|---------|------|
| `ts_code` | - | 股票代码（格式转换后用） |
| `trade_date` | `trade_date` | 交易日 |
| `open` | `open` | 开盘价 |
| `high` | `high` | 最高价 |
| `low` | `low` | 最低价 |
| `close` | `close` | 收盘价 |
| `vol` | `volume` | 成交量 |
| `amount` | `amount` | 成交额 |
| `pct_chg` | `change_pct` | 涨跌幅 |
| `change` | `change` | 涨跌额 |

---

### 2. AkShare（备选数据源）

#### 获取股票列表
```python
import akshare as ak

# 获取 A 股列表
df = ak.stock_info_a_code_name()
```

#### 获取日线行情
```python
# 获取后复权日线数据
df = ak.stock_zh_a_hist(symbol='600519', period='daily', start_date='20250101', end_date='20250605', adjust='hfq')
```

#### 字段映射
| AkShare 字段 | 目标字段 | 说明 |
|-------------|---------|------|
| `日期` | `trade_date` | 交易日 |
| `开盘` | `open` | 开盘价 |
| `收盘` | `close` | 收盘价 |
| `最高` | `high` | 最高价 |
| `最低` | `low` | 最低价 |
| `成交量` | `volume` | 成交量 |
| `成交额` | `amount` | 成交额 |
| `涨跌幅` | `change_pct` | 涨跌幅 |
| `涨跌额` | `change` | 涨跌额 |
| `振幅` | `amplitude` | 振幅 |
| `换手率` | `turnover` | 换手率 |

---

### 3. baostock（补充数据源）

#### 初始化
```python
import baostock as bs

# 登录
lg = bs.login()

# 登出（用完后）
bs.logout()
```

#### 获取日线行情
```python
# 获取后复权日线数据
# adjustflag="3" 表示后复权
rs = bs.query_history_k_data_plus(
    "sh.600519",
    "date,open,high,low,close,volume,amount",
    start_date="2025-01-01",
    end_date="2025-06-05",
    frequency="d",
    adjustflag="3"
)

# 转换为 DataFrame
data_list = []
while (rs.error_code == '0') & rs.next():
    data_list.append(rs.get_row_data())
df = pd.DataFrame(data_list, columns=rs.fields)
```

#### 字段映射
| baostock 字段 | 目标字段 | 说明 |
|--------------|---------|------|
| `date` | `trade_date` | 交易日（需转换格式） |
| `open` | `open` | 开盘价 |
| `high` | `high` | 最高价 |
| `low` | `low` | 最低价 |
| `close` | `close` | 收盘价 |
| `volume` | `volume` | 成交量 |
| `amount` | `amount` | 成交额 |

---

## 股票代码格式转换

不同数据源的股票代码格式不同，需要统一转换：

| 市场 | 原始格式 | 标准格式 |
|------|---------|---------|
| 上交所 | `600519`（AkShare） | `600519` |
| 上交所 | `600519.SH`（Tushare） | `600519` |
| 上交所 | `sh.600519`（baostock） | `600519` |
| 深交所 | `000001`（AkShare） | `000001` |
| 深交所 | `000001.SZ`（Tushare） | `000001` |
| 深交所 | `sz.000001`（baostock） | `000001` |

### 转换函数

```python
# 从标准格式转换为各数据源格式
def to_tushare_code(stock_code):
    """转换为 Tushare 格式：600519 -> 600519.SH"""
    if stock_code.startswith('6'):
        return f"{stock_code}.SH"
    else:
        return f"{stock_code}.SZ"

def to_baostock_code(stock_code):
    """转换为 baostock 格式：600519 -> sh.600519"""
    if stock_code.startswith('6'):
        return f"sh.{stock_code}"
    else:
        return f"sz.{stock_code}"

def to_akshare_code(stock_code):
    """转换为 AkShare 格式：不需要转换"""
    return stock_code
```

---

## 错误处理策略

### Tushare 错误
- **Token 无效**：立即降级到 AkShare
- **网络错误**：重试 2 次，间隔 1 秒，失败则降级
- **API 限流**：等待 5 秒重试，或直接降级

### AkShare 错误
- **连接断开（RemoteDisconnected）**：立即降级到 baostock
- **反爬限制**：重试 2 次，间隔 2 秒，失败则降级

### baostock 错误
- **登录失败**：记录错误，返回失败
- **网络错误**：重试 2 次，间隔 1 秒，失败则返回错误

---

## 数据来源标记

所有存储到 MongoDB 的数据必须标记 `data_source` 字段，值为：
- `"tushare"`
- `"akshare"`
- `"baostock"`

---

## 重试策略

| 数据源 | 重试次数 | 间隔 |
|--------|---------|------|
| Tushare | 2 | 1 秒 |
| AkShare | 2 | 2 秒 |
| baostock | 2 | 1 秒 |
