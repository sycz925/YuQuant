# pytdx 完整接口参考手册

> 基于 pytdx 1.72, `pytdx.hq.TdxHq_API` (标准行情接口)
> 适用于 A 股/指数/板块数据获取

---

## 目录

1. [连接管理](#1-连接管理)
2. [实时行情报价](#2-实时行情报价-get_security_quotes)
3. [个股K线数据](#3-个股k线数据-get_security_bars)
4. [指数K线数据](#4-指数k线数据-get_index_bars)
5. [证券列表](#5-证券列表-get_security_list)
6. [证券总数](#6-证券总数-get_security_count)
7. [财务数据](#7-财务数据-get_finance_info)
8. [除权除息](#8-除权除息-get_xdxr_info)
9. [分时数据](#9-分时数据)
10. [成交明细](#10-成交明细)
11. [K线便捷接口](#11-k线便捷接口-get_k_data)
12. [板块文件](#12-板块文件)
13. [公司公告](#13-公司公告)
14. [其他工具方法](#14-其他工具方法)

---

## 1. 连接管理

### `connect(ip, port, time_out, bindport, bindip)`

连接通达信行情服务器。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `ip` | str | `'101.227.73.20'` | 服务器 IP 地址 |
| `port` | int | `7709` | 服务器端口 |
| `time_out` | float | `5.0` | 连接超时(秒) |
| `bindport` | int | `None` | 绑定本地端口(可选) |
| `bindip` | str | `'0.0.0.0'` | 绑定本地 IP(可选) |

**返回**: `bool` — True 表示连接成功

```python
api = TdxHq_API()
ok = api.connect('218.75.126.9', 7709, time_out=5)
```

### `disconnect()`

断开连接。无返回值。

### 常用服务器列表

```python
TDX_SERVERS = [
    ("218.75.126.9", 7709),   # 优选
    ("119.147.212.81", 7709),
    ("112.74.214.43", 7709),
    ("221.231.141.60", 7709),
    ("101.227.73.20", 7709),
    ("101.227.77.254", 7709),
    ("14.215.128.18", 7709),
    ("59.173.18.140", 7709),
]
```

### 市场编号常量

```python
MARKET_SZ = 0  # 深圳
MARKET_SH = 1  # 上海
```

### 代码推断规则

| 条件 | market |
|------|--------|
| 代码以 `6`, `8`, `9` 开头 | 1 (上海) |
| 其他 (以 `0`, `3` 开头) | 0 (深圳) |

---

## 2. 实时行情报价 `get_security_quotes`

获取股票/指数的实时五档行情快照。

### 签名

```python
get_security_quotes(all_stock, code=None)
```

### 三种调用形式

```python
# 形式1: 元组
api.get_security_quotes((0, '300750'))

# 形式2: 单个 market + code
api.get_security_quotes(0, '300750')

# 形式3: 列表批量
api.get_security_quotes([(0, '300750'), (1, '600519'), (0, '300014')])
```

### 参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `all_stock` | list[tuple] 或 tuple | `(market, code)` 的数组 |
| `code` | str | (可选) 单只股票代码 |

### 返回值

`list[dict]` — 每个 dict 包含以下字段:

```python
{
    'market': 0,                    # 市场编号 (0=深圳, 1=上海)
    'code': '300750',               # 纯数字代码
    'active1': 4820,                # 活跃标记1
    'price': 374.51,                # 最新价
    'last_close': 380.0,            # 昨收价
    'open': 379.23,                 # 今开价
    'high': 381.89,                 # 最高价
    'low': 374.05,                  # 最低价
    'servertime': '15:26:15.300',   # 服务器时间
    'vol': 216480,                  # 成交量(手)
    'cur_vol': 1877,                # 当前成交量
    'amount': 8167456256.0,         # 成交额(元)
    's_vol': 112459,                # 内盘(卖量)
    'b_vol': 104021,                # 外盘(买量)
    'bid1': 374.51,                 # 买一价
    'ask1': 374.52,                 # 卖一价
    'bid_vol1': 103,                # 买一量(手)
    'ask_vol1': 1,                  # 卖一量(手)
    'bid2': 374.5,                  # 买二价
    'ask2': 374.56,                 # 卖二价
    'bid_vol2': 450,                # 买二量
    'ask_vol2': 9,                  # 卖二量
    'bid3': 374.49,                 # 买三价
    'ask3': 374.7,                  # 卖三价
    'bid_vol3': 8,
    'ask_vol3': 3,
    'bid4': 374.48,
    'ask4': 374.74,
    'bid_vol4': 4,
    'ask_vol4': 1,
    'bid5': 374.47,
    'ask5': 374.75,
    'bid_vol5': 10,
    'ask_vol5': 23,
}
```

### 常用计算

```python
# 涨跌幅
pct = (q['price'] - q['last_close']) / q['last_close'] * 100

# 振幅
amplitude = (q['high'] - q['low']) / q['last_close'] * 100

# 量比 (需历史数据)
# 换手率 (需流通股本)
```

---

## 3. 个股K线数据 `get_security_bars`

获取个股/基金/债券的日K、周K、月K等K线数据。

### 签名

```python
get_security_bars(category, market, code, start, count)
```

### 参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `category` | int | K线周期类型 (见下表) |
| `market` | int | 市场编号 (0/1) |
| `code` | str | 纯数字代码 |
| `start` | int | 起始位置, 0=最新, 倒序递增 |
| `count` | int | 每次最多获取条数 (最大 800) |

### K线周期类型 `category`

| 值 | 含义 |
|----|------|
| 0 | 5分钟K线 |
| 1 | 15分钟K线 |
| 2 | 30分钟K线 |
| 3 | 60分钟K线 |
| 4 | 日K线 |
| 5 | 周K线 |
| 6 | 月K线 |
| 7 | 1分钟K线 |
| 8 | 1分钟K线 |
| 9 | 日K线 |

### 返回值

`list[dict]` — 按时间正序排列:

```python
[
    {
        'open': 392.49,              # 开盘价
        'close': 393.01,             # 收盘价
        'high': 402.36,              # 最高价
        'low': 390.0,                # 最低价
        'vol': 340754.0,             # 成交量(手)
        'amount': 13139767296.0,     # 成交额(元)
        'year': 2026,                # 年
        'month': 7,                  # 月
        'day': 2,                    # 日
        'hour': 15,                  # 时
        'minute': 0,                 # 分
        'datetime': '2026-07-02 15:00',  # 日期时间字符串
    },
    ...
]
```

### 用法示例

```python
# 获取最近10个交易日的日K线
bars = api.get_security_bars(9, 0, '300750', 0, 10)

# 获取5分钟K线 (最近500条, 需循环)
all_bars = []
for start in range(0, 2000, 800):
    bars = api.get_security_bars(0, 0, '300750', start, 800)
    if not bars:
        break
    all_bars.extend(bars)
```

### 注意事项

- `start` 是倒序的: `start=0` 表示最新, `start=800` 表示前800条之前的
- 每次最多返回 800 条, 获取更多需循环

---

## 4. 指数K线数据 `get_index_bars`

获取指数的日K/周K/月K数据。参数和返回格式与 `get_security_bars` 完全一致。

### 签名

```python
get_index_bars(category, market, code, start, count)
```

### 参数

与 `get_security_bars` 相同。

### 返回值

与 `get_security_bars` 相同。

### 常用指数代码

| 代码 | 名称 | market |
|------|------|--------|
| `000001` | 上证指数 | 1 |
| `399001` | 深证成指 | 0 |
| `399006` | 创业板指 | 0 |
| `000016` | 上证50 | 1 |
| `000300` | 沪深300 | 1 |
| `000905` | 中证500 | 1 |
| `000852` | 中证1000 | 1 |

### 用法示例

```python
# 获取沪深300近60日K线
bars = api.get_index_bars(9, 1, '000300', 0, 60)

# 获取板块指数 (板块指数 market=1)
bars = api.get_index_bars(9, 1, '880301', 0, 20)  # 某行业板块指数
```

---

## 5. 证券列表 `get_security_list`

获取某市场下的证券列表(股票、指数、基金等)。

### 签名

```python
get_security_list(market, start)
```

### 参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `market` | int | 市场编号 (0=深圳, 1=上海) |
| `start` | int | 起始位置, 每次返回最多 1000 条 |

### 返回值

`list[dict]`:

```python
[
    {
        'code': '395001',           # 代码
        'volunit': 100,             # 每手股数
        'decimal_point': 2,         # 小数位数
        'name': '主板Ａ股',          # 名称
        'pre_close': 1496.0,        # 昨收价
    },
    ...
]
```

### 用法示例

```python
# 分页获取深圳全部证券
all_securities = []
start = 0
while True:
    batch = api.get_security_list(0, start)
    if not batch:
        break
    all_securities.extend(batch)
    start += len(batch)

# 过滤股票
stocks = [s for s in all_securities if s['code'].startswith(('00', '30'))]
```

---

## 6. 证券总数 `get_security_count`

获取某市场的证券总数。

### 签名

```python
get_security_count(market)
```

### 参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `market` | int | 市场编号 (0/1) |

### 返回值

`int` — 证券总数

```python
sz_count = api.get_security_count(0)  # 深圳 ~23728
sh_count = api.get_security_count(1)  # 上海 ~27530
```

---

## 7. 财务数据 `get_finance_info`

获取个股的财务摘要数据。

### 签名

```python
get_finance_info(market, code)
```

### 参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `market` | int | 市场编号 |
| `code` | str | 纯数字代码 |

### 返回值

`dict`:

```python
{
    'market': 0,
    'code': '300750',
    'liutongguben': 4257012187.5,      # 流通股本(股)
    'province': 20,                     # 省份编码
    'industry': 43,                     # 行业编码
    'updated_date': 20260604,           # 更新日期(YYYYMMDD)
    'ipo_date': 20180611,               # 上市日期
    'zongguben': 4626627187.5,          # 总股本
    'guojiagu': 12380000.0,             # 国家股
    'faqirenfarengu': 139625580000.0,   # 发起人法人股
    'farengu': 847045920000.0,          # 法人股
    'bgu': 0.0,                         # B股
    'hgu': 218300292.96875,             # H股
    'zhigonggu': 45799.999,             # 职工股
    'zongzichan': 10463290240000.0,     # 总资产
    'liudongzichan': 6924981760000.0,   # 流动资产
    'gudingzichan': 1500433760000.0,    # 固定资产
    'wuxingzichan': 151226950000.0,     # 无形资产
    'gudongrenshu': 204504.0,           # 股东人数
    'liudongfuzhai': 4340102080000.0,   # 流动负债
    'changqifuzhai': 369697040000.0,    # 长期负债
    'zibengongjijin': 1571265760000.0,  # 资本公积金
    'jingzichan': 3572625920000.0,      # 净资产
    'zhuyingshouru': 1291310400000.0,   # 主营收入
    'zhuyinglirun': 970863680000.0,     # 主营利润
    'yingshouzhangkuan': 777100960000.0,# 应收账款
    'yingyelirun': 266512900000.0,      # 营业利润
    'touzishouyu': 26883280000.0,       # 投资收益
    'jingyingxianjinliu': 336808520000.0,# 经营现金流
    'zongxianjinliu': 278195600000.0,   # 总现金流
    'cunhuo': 1089409280000.0,          # 存货
    'lirunzonghe': 266816020000.0,      # 利润总额
    'shuihoulirun': 227372520000.0,     # 税后利润
    'jinglirun': 207377100000.0,        # 净利润
    'weifenpeilirun': 1953712000000.0,  # 未分配利润
    'meigujingzichan': 78.277,          # 每股净资产
}
```

### 常用计算

```python
fi = api.get_finance_info(0, '300750')

# 市盈率 (需配合实时价格)
pe = price / fi['meigujingzichan'] if fi['meigujingzichan'] else 0

# 资产负债率
debt_ratio = (fi['liudongfuzhai'] + fi['changqifuzhai']) / fi['zongzichan'] * 100
```

---

## 8. 除权除息 `get_xdxr_info`

获取个股的除权除息(分红送转)历史记录。

### 签名

```python
get_xdxr_info(market, code)
```

### 返回值

`list[dict]`:

```python
[
    {
        'year': 2024,
        'month': 7,
        'day': 12,
        'category': 1,                      # 类型 (见下表)
        'name': '10送5.0股派12.0元',        # 描述
        'fenhong': 12.0,                     # 分红(每10股派X元)
        'peigujia': None,                    # 配股价
        'songzhuangu': 5.0,                  # 送转股(每10股送X股)
        'peigu': None,                       # 配股(每10股配X股)
        'suogu': None,                       # 缩股比例
        'panqianliutong': 21724.373,         # 盘前流通(万股)
        'panhouliutong': 32586.560,          # 盘后流通
        'qianzongguben': 217243.703,         # 前总股本
        'houzongguben': 243501.734,          # 后总股本
        'fenshu': None,                      # 份数
        'xingquanjia': None,                 # 行权价
    },
    ...
]
```

### category 类型

| 值 | 含义 |
|----|------|
| 1 | 除权除息 |
| 2 | 送配股上市 |
| 3 | 非流通股上市 |
| 4 | 未知股本变动 |
| 5 | 股本变化 |
| 6 | 增发新股 |
| 7 | 股份回购 |
| 8 | 增发新股上市 |
| 9 | 转配股上市 |
| 10 | 可转债上市 |
| 11 | 扩缩股 |
| 12 | 非流通股缩股 |
| 13 | 送认购权证 |
| 14 | 送认沽权证 |

---

## 9. 分时数据

### `get_minute_time_data(market, code)`

获取当日分时图数据(每分钟一条)。

**返回**: `list[dict]` — 最多 240 条 (4小时交易时间)

```python
[
    {'price': 374.51, 'vol': 48},  # price=均价, vol=累计成交量(手)
    {'price': 374.48, 'vol': 102},
    ...
]
```

### `get_history_minute_time_data(market, code, date)`

获取历史某日分时图数据。

| 参数 | 类型 | 说明 |
|------|------|------|
| `date` | int | 日期, 格式 YYYYMMDD, 如 `20260701` |

**返回**: 同 `get_minute_time_data`

---

## 10. 成交明细

### `get_transaction_data(market, code, start, count)`

获取当日逐笔成交明细。

| 参数 | 类型 | 说明 |
|------|------|------|
| `start` | int | 起始位置, 0=最新 |
| `count` | int | 获取条数 (最大 2000) |

**返回**: `list[dict]`

```python
[
    {
        'time': '15:23',       # 时间 HH:MM
        'price': 374.51,       # 成交价
        'vol': 1,              # 成交量(手)
        'num': 1,              # 成交笔数
        'buyorsell': 5,        # 买卖方向 (0=买, 1=卖, 2=中性, 5=集合竞价)
    },
    ...
]
```

### `get_history_transaction_data(market, code, start, count, date)`

获取历史某日逐笔成交明细。

| 参数 | 类型 | 说明 |
|------|------|------|
| `date` | int | 日期, 格式 YYYYMMDD |

返回格式同 `get_transaction_data`。

---

## 11. K线便捷接口 `get_k_data`

封装好的K线获取接口, 自动分页循环获取。

### 签名

```python
get_k_data(code, start_date, end_date)
```

### 参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `code` | str | 纯数字代码 |
| `start_date` | str | 起始日期 `'YYYY-MM-DD'` |
| `end_date` | str | 截止日期 `'YYYY-MM-DD'` |

### 返回值

`pandas.DataFrame` — 需要安装 pandas

```python
          date    code    open   close    high     low        vol        amount
2026-06-01  300750  387.68  382.35  390.99  380.39  340754.0  13139767296.0
2026-06-02  300750  381.96  380.00  387.95  379.00  216480.0   8167456256.0
...
```

### 注意

- 内部调用 `get_security_bars(9, ...)` 循环获取最多 8000 条
- 需要 pandas 依赖
- 市场代码自动推断

---

## 12. 板块文件

通达信通过 `.dat` 文件存储板块数据。

### `get_block_info_meta(blockfile)`

获取板块文件元信息。

| 参数 | 类型 | 说明 |
|------|------|------|
| `blockfile` | str | 文件名 (见下表) |

**返回**: `dict`

```python
{'size': 759896, 'hash_value': b'8a9a2c64...'}
```

### `get_block_info(blockfile, start, size)`

下载板块文件的二进制数据。

| 参数 | 类型 | 说明 |
|------|------|------|
| `blockfile` | str | 文件名 |
| `start` | int | 起始偏移 |
| `size` | int | 下载字节数 (建议 `0x7530` = 30000) |

**返回**: `bytes` — 文件的二进制片段

### `get_and_parse_block_info(blockfile)`

一步完成下载+解析板块文件。

**返回**: `list[dict]`

```python
[
    {'name': '板块名称', 'stock_codes': ['000001', '000002', ...]},
    ...
]
```

### 板块文件名

| 文件名 | 类型 |
|--------|------|
| `block_gn.dat` | 概念板块 |
| `block_zs.dat` | 行业板块 (指数) |
| `block_fg.dat` | 风格板块 |

### 完整用法示例

```python
import struct

# 方法1: 一步获取
blocks = api.get_and_parse_block_info('block_gn.dat')

# 方法2: 手动下载+解析
meta = api.get_block_info_meta('block_gn.dat')
total = meta['size']
chunk_size = 0x7530
content = bytearray()
for start in range(0, total, chunk_size):
    data = api.get_block_info('block_gn.dat', start, min(chunk_size, total - start))
    if data:
        content.extend(data)

# 然后解析 content (二进制格式, 需自定义解析逻辑)
```

### 板块指数代码

板块指数使用沪市市场编号 (`market=1`):

```python
# 获取板块指数K线
bars = api.get_index_bars(9, 1, '880301', 0, 20)  # 880xxx 是行业板块指数
```

---

## 13. 公司公告

### `get_company_info_category(market, code)`

获取公司的公告分类列表。

**返回**: `list[dict]`

```python
[
    {
        'name': '最新提示',              # 分类名称
        'filename': '300750.txt',        # 文件名
        'start': 1174919,                # 文件内偏移
        'length': 14526,                 # 内容长度(字节)
    },
    {
        'name': '公司概况',
        'filename': '300750.txt',
        'start': 0,
        'length': 30645,
    },
    {
        'name': '财务分析',
        'filename': '300750.txt',
        'start': 30645,
        'length': 37859,
    },
    # 还有: 股本股东, 资产运作, 行业分析, 公司公告, 公司新闻...
]
```

### `get_company_info_content(market, code, filename, start, length)`

获取公告/财报的具体文本内容。

| 参数 | 类型 | 说明 |
|------|------|------|
| `filename` | str | 文件名 (从 category 获取) |
| `start` | int | 起始偏移 |
| `length` | int | 读取长度 |

**返回**: `dict` — 含 `content` 字段的公告文本

---

## 14. 其他工具方法

### `to_df(data)`

将 pytdx 返回的 `list[dict]` 转换为 `pandas.DataFrame`。

```python
bars = api.get_security_bars(9, 0, '300750', 0, 100)
df = api.to_df(bars)
```

### `get_report_file(filename, offset)`

从代理服务器下载文件片段。

```python
response = api.get_report_file('filename.dat', 0)
# response = {'chunksize': int, 'chunkdata': bytes}
```

### `get_report_file_by_size(filename, filesize, reporthook)`

按大小下载完整文件。

| 参数 | 类型 | 说明 |
|------|------|------|
| `filename` | str | 文件名 |
| `filesize` | int | 文件大小 (0=自动检测) |
| `reporthook` | callable | 进度回调 `fn(downloaded, total)` |

**返回**: `bytes` — 完整文件内容

### `get_traffic_stats()`

获取流量统计信息。

---

## 附录: 数据转换与清洗

### 实时行情 → DataFrame

```python
import pandas as pd

quotes = api.get_security_quotes([(0, '300750'), (1, '600519')])
df = pd.DataFrame(quotes)
df['pct_change'] = (df['price'] - df['last_close']) / df['last_close'] * 100
```

### K线 → DataFrame

```python
bars = api.get_security_bars(9, 0, '300750', 0, 100)
df = api.to_df(bars)
df['trade_date'] = df['datetime'].str[:10]
df['pct_change'] = df['close'].pct_change() * 100
```

### 板块文件解析 (新版格式)

```python
def parse_block_dat(data: bytes) -> list[dict]:
    """解析 block_gn.dat / block_zs.dat / block_fg.dat"""
    blocks = []
    pos = 0x0140  # 跳过文件头

    while pos < len(data):
        # 跳过空字节
        while pos < len(data) and data[pos] == 0:
            pos += 1
        if pos >= len(data):
            break

        # 寻找 GBK 中文板块名
        name_start = -1
        for try_pos in range(pos, min(pos + 80, len(data))):
            b1, b2 = data[try_pos], data[try_pos + 1] if try_pos + 1 < len(data) else 0
            if 0x81 <= b1 <= 0xFE and 0x40 <= b2 <= 0xFE:
                name_start = try_pos
                break

        if name_start < 0:
            pos += 4
            continue

        # 读取板块名 (以 0x00 结尾)
        name_end = data.find(b'\x00', name_start)
        if name_end < 0 or name_end - name_start > 32:
            pos = name_start + 1
            continue

        block_name = data[name_start:name_end].decode('gbk').strip()

        # 提取6位ASCII股票代码
        stock_codes = []
        code_pos = name_end + 1
        while code_pos < len(data) - 6:
            code_str = data[code_pos:code_pos + 6].decode('ascii', errors='ignore')
            if code_str.isdigit() and len(code_str) == 6:
                stock_codes.append(code_str)
                code_pos += 7
            else:
                break

        if stock_codes:
            blocks.append({'name': block_name, 'stock_codes': stock_codes})
        pos = code_pos

    return blocks
```

---

## 附录: 连接池模式 (生产推荐)

```python
from queue import Queue, Empty, Full
from pytdx.hq import TdxHq_API

POOL_SIZE = 8
_pool = Queue(maxsize=POOL_SIZE)

def _init_pool():
    for _ in range(POOL_SIZE):
        api = TdxHq_API()
        for host, port in TDX_SERVERS:
            try:
                if api.connect(host, port, time_out=5):
                    _pool.put_nowait(api)
                    break
            except Exception:
                continue

def get_conn():
    try:
        return _pool.get_nowait()
    except Empty:
        api = TdxHq_API()
        for host, port in TDX_SERVERS:
            try:
                if api.connect(host, port, time_out=5):
                    return api
            except Exception:
                continue
        return None

def return_conn(api):
    if api is None:
        return
    try:
        api.get_security_count(0)  # 测试连接是否存活
        _pool.put_nowait(api)
    except Exception:
        try:
            api.disconnect()
        except Exception:
            pass
```
