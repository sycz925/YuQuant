# 数据更新系统（Data Update System）

> A股量化仿真与前端看板系统的数据更新核心模块。本文档详细介绍数据同步的架构设计、数据源优先级、板块数据获取机制、以及通达信（pytdx）数据源的集成实现。

---

## 1. 架构概览

### 1.1 模块结构图

```
app/data/
├── manager.py            # DataManager: 数据同步编排核心（入口）
├── db.py                 # MongoDB 数据访问层（DAO）
├── task_manager.py       # 异步任务状态管理
├── sources/              # 多数据源适配层
│   ├── pytdx_source.py   # 通达信接口（板块+个股日线，主数据源）
│   ├── tqcenter_source.py# TqCenter（通达信客户端 DLL，Windows 环境）
│   ├── akshare_source.py # AkShare（股票基础信息回退）
│   ├── baostock_source.py# BaoStock（个股日线回退）
│   ├── tushare_source.py # Tushare（积分制，备用）
│   └── yfinance_source.py# Yahoo Finance（美股 ADR，备用）
└── migration*.py         # 数据迁移脚本（历史遗留）
```

### 1.2 数据流

```
用户触发 /api/factors/sync-*  ──►  TaskManager 创建任务
    │
    ▼
DataManager.sync_*()  ──►  数据源选择（按优先级）
    │
    ├── TqCenter（Windows DLL，最高优先级）
    ├── PytdxSource（通达信协议直连，主数据源）
    ├── AkShare（同花顺/东财 Web API，回退）
    ├── BaoStock（个股日线回退）
    └── yfinance（美股备用）
    │
    ▼
MongoDB 批量写入（bulk_write upsert）
    │
    ▼
TaskManager 更新进度状态
```

---

## 2. 数据源优先级策略

| 优先级 | 数据源 | 用途 | 优点 | 限制 |
|--------|--------|------|------|------|
| 1 | **TqCenter** | 板块列表 + 板块指数日线 | 与通达信客户端一致，数据最完整 | 仅 Windows 环境，依赖 DLL |
| 2 | **PytdxSource** | 板块列表 + 成分股 + 880/881 指数日线 + 个股日线 | 跨平台，直接协议连接通达信服务器 | 部分板块无对应指数代码 |
| 3 | **AkShare** | 股票基础信息 | Web API，无需安装 | 速度慢，概念板块易失效 |
| 4 | **BaoStock** | 个股日线 | 免费，历史数据长 | 仅个股，无板块 |
| 5 | **yfinance** | 美股 ADR | 补充海外数据 | 非 A 股核心 |

> **当前默认策略**：在 Linux/Mac 开发环境下，PytdxSource 是实际主数据源。TqCenter 仅在 Windows 生产环境启用。

---

## 3. PytdxSource 核心实现（通达信数据源）

### 3.1 核心能力一览

[pytdx_source.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/data/sources/pytdx_source.py) 是整个数据更新系统的核心模块，提供以下 5 类功能：

```python
PytdxSource.
├── get_concept_blocks()       # 获取概念板块列表 + 成分股（block_gn.dat）
├── get_industry_blocks()      # 获取行业板块列表 + 成分股（block_zs.dat）
├── get_style_blocks()         # 获取风格板块列表 + 成分股（block_fg.dat）
├── get_tdx_index_daily()      # 板块指数日线（880XXX 行业 / 881XXX 概念）
├── get_stock_daily()          # 个股日线
└── get_stock_basics()         # 股票基础信息（security_list）
```

### 3.2 通达信服务器连接

```python
TDX_SERVERS = [
    ('180.153.18.170', 7709),   # 通达信上海主站
    ('119.147.212.81', 7709),   # 通达信深圳主站
    ('112.74.214.43',  7709),   # 备用 1
    ('121.14.110.194', 7709),   # 备用 2
    ('218.108.98.244', 7709),   # 备用 3
    ('60.12.136.250',  7709),   # 备用 4
]
```

`_connect()` 按顺序尝试连接，首个可用即返回。每次调用后需手动 `disconnect()`。

### 3.3 板块文件解析（block_*.dat）

**关键洞察**：pytdx 社区版本的 `get_block_info` 可以下载通达信的板块文件（`.dat`），但社区版的 `BlockReader` 对**新版通达信 block_gn.dat 格式解析不全**——返回的名称可能乱码，概念板块数量不足 100 个。

本项目实现了**自定义解析器** `_parse_block_file()`，核心步骤：

1. **下载板块文件**：`get_block_info(filename)` 分块读取 `block_gn.dat` / `block_zs.dat` / `block_fg.dat`
2. **定位板块名称起始**：扫描二进制字节流，通过 GBK 编码范围（`0x81-0xFE, 0x40-0xFE`）识别中文名称起始位置
3. **提取股票代码**：跳过 `0x02 0x00` 标志位后，提取后续 6 位 ASCII 数字（股票代码）+ `0x00` 分隔
4. **循环提取**：直到文件末尾

```python
# 伪代码表示二进制解析逻辑
while pos < data_length:
    # 1. 寻找 GBK 中文名称起始
    name_start = find_gbk_name(pos)           # 0x81-0xFE + 0x40-0xFE
    if not found:
        pos += 4; continue

    # 2. 读取 GBK 名称（以 0x00 结尾）
    block_name = decode_gbk(name_bytes)       # e.g., "光刻机"

    # 3. 跳过 0x00 + 标志位
    skip_to_flag = find_0x0200(name_end)

    # 4. 提取后续股票代码（6 位 ASCII + 0x00）
    stock_codes = extract_ascii_codes(flag_pos + 2)
    # e.g., ["600519", "601318", "000001", ...]

    blocks.append({name: block_name, stock_codes: stock_codes})
    pos = next_block_start
```

**实测产出**：
| 文件 | 板块数 | 代表板块 |
|------|--------|----------|
| `block_gn.dat` | ~246 个 | 光刻机、半导体、芯片、光伏、储能、锂电池、军工、5G、人工智能、ChatGPT、北交所概念... |
| `block_zs.dat` | ~108 个 | 银行、证券、保险、房地产、白酒、化学制药、煤炭、钢铁、有色、汽车、电力、家电、消费电子... |
| `block_fg.dat` | ~50 个 | 高股息、小盘、低价、预亏预减、预盈预增、融资融券、次新股、ST... |

### 3.4 板块指数日线获取（880XXX / 881XXX）

通达信为主要行业和概念板块提供了**指数代码**，格式为 `880XXX`（行业）或 `881XXX`（概念）。这些指数可以直接通过 `get_index_bars()` 获取 K 线数据。

```python
def get_tdx_index_daily(tdx_code, market=1, start_date='20200101'):
    """
    Args:
        tdx_code:   通达信指数代码，如 '880301'（半导体）、'881121'（光刻机）
        market:     1 = 沪市（板块指数都用沪市）
        start_date: 起始日期 YYYYMMDD

    Returns: DataFrame [trade_date, open, close, high, low, vol, amount, code]
    """
    api = _connect()
    bars = []
    for start in range(0, 10000, 800):   # 每次最多 800 条
        batch = api.get_index_bars(9, market, tdx_code, start, 800)
        if not batch: break
        bars.extend(batch)
    df = api.to_df(bars)
    # ...格式化列名、筛选日期
```

### 3.5 板块名称 → 通达信指数代码智能匹配

**问题**：`block_gn.dat` 中的板块名称（如"半导体"）与通达信指数的 `get_security_list` 结果（名称为"半导体"）并不总是完全一致。有些板块没有对应指数（如"海峡西岸"），有些名称有细微差异。

**解决方案**：`_match_block_to_tdx()` 实现 6 层匹配策略：

```
板块名称（如"人工智能"）
    │
    ├─► 1. 精确匹配（名称 == 通达信指数名称）? 880541
    │
    ├─► 2. BLOCK_ALIAS_MAP 别名映射? 人工智能 -> 人工智能
    │
    ├─► 3. 去括号（如"股权转让(并购重组)" → "股权转让"）?
    │
    ├─► 4. 去后缀（如去掉"概念""板块""指数"）?
    │
    ├─► 5. 包含关系（板块名包含指数名或反之）?
    │
    └─► 6. 别名包含匹配?

    → 返回：tdx_code（如 '880541'）或 ''（无对应指数，跳过日线）
```

**核心数据结构**：

```python
BLOCK_ALIAS_MAP = {
    # --- 概念板块别名映射（节选，共 900+ 条） ---
    '光刻机':   '光刻机',      # 881121
    '光刻胶':   '光刻胶',      # 881137
    '半导体':   '半导体',      # 880350
    '芯片':     '集成电路',    # 881126
    '军工':     '国防军工',    # 880507
    '卫星导航': '卫星导航',    # 880545
    '光伏':     '光伏设备',    # 880590
    '锂电池':   '锂电池',      # 880535
    '储能':     '电池',        # 881139
    '氢能源':   '燃料电池',    # 881149
    '白酒':     '白酒',        # 880381
    '银行':     '银行',        # 880471
    '证券':     '证券',        # 881157
    # ... 共 900+ 条行业/概念板块别名
}
```

**匹配流程**（在 `DataManager.sync_sector_indices()` 中调用）：

1. 首次扫描通达信服务器的 `get_security_list(1)`，获取所有 880/881 开头的指数名称与代码
2. 建立 `{index_name: tdx_code}` 映射并缓存
3. 对每个板块调用 `_match_block_to_tdx(block_name, name_to_code)` 获取对应 `tdx_code`
4. 成功匹配的板块调用 `get_tdx_index_daily(tdx_code)` 获取日线
5. 未匹配的板块仅保留板块基础信息（名称 + 成分股），无日线数据

**匹配率**：当前 354 个板块中约 **41 个** 可匹配到通达信指数日线。其余板块可通过成分股等权合成指数（后续扩展）。

### 3.6 个股日线与基础信息

- `get_stock_basics()`：遍历通达信沪市+深市 `get_security_list()`，提取所有 A 股代码/名称/市场
- `get_stock_daily(stock_code, start_date)`：根据代码首字符判断市场（6/8/9 → 沪市 market=1，其他 → 深市 market=0），调用 `get_security_bars()` 循环获取 K 线
- 市场推断逻辑：`6 开头 = 上证主板；8 开头 = 北交所；9 开头 = B 股；0/3 = 深市`

---

## 4. DataManager 数据同步编排

### 4.1 板块数据同步流程

[manager.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/data/manager.py) `sync_sector_indices()` 方法的完整流程：

```
阶段 1：获取板块列表
    ├─► 尝试 TqCenter（Windows 环境）
    │      └─► 成功 → 直接返回板块 DataFrame
    │
    └─► 回退 PytdxSource
           ├─► get_concept_blocks() → block_gn.dat → 概念板块
           ├─► get_industry_blocks() → block_zs.dat → 行业板块
           └─► 合并 → 354 个板块（246 概念 + 108 行业）

阶段 2：保存板块基础信息（MongoDB sector_basics 集合）
    └─► 字段: { code: "SECTOR_板块名", name: "板块名", source: "概念/行业",
                stock_count: N, stock_codes: ["600519", ...], ths_code: "",
                update_time: ISODate, block_type: 2 }
    └─► upsert（按 code 唯一键）

阶段 3：扫描通达信 880/881 指数代码映射（一次性）
    └─► 遍历 get_security_list(1)，筛选 880/881 开头的代码
    └─► 建立 {指数名称: tdx_code} 字典

阶段 4：下载板块指数日线（增量）
    ├─► 检查已有最新日期（MongoDB 查询该板块最后一条日线）
    ├─► 对每个板块：
    │      └─► 调用 _match_block_to_tdx() → 获得 tdx_code
    │      └─► 若 tdx_code 存在 → 调用 get_tdx_index_daily(tdx_code, start_date)
    │      └─► 无匹配 → 跳过（等待未来成分股等权合成）
    └─► 批量 bulk_write upsert 到 daily_data（data_type='sector'）

阶段 5：返回统计信息
    └─► { block_count: 354, sector_daily_count: 63878 }
```

### 4.2 增量更新机制

每次同步不删除旧数据，而是**按日期 upsert**：

```python
# 查询该板块已有最新日期
existing_latest = db['daily_data'].find_one(
    {'stock_code': 'SECTOR_半导体', 'data_type': 'sector'},
    sort=[('trade_date', -1)]
)

# 如果有旧数据，从 latest_date - 7 天开始请求（避免交易日对齐误差）
if existing_latest:
    start_date = (parse_date(existing_latest['trade_date']) - 7d).format('YYYYMMDD')
else:
    start_date = '20200101'

# 获取新数据后 upsert（相同 stock_code + trade_date 会覆盖）
UpdateOne({'stock_code': code, 'trade_date': date_str},
          {'$set': {open, close, high, low, vol, amount, data_source, ...}},
          upsert=True)
```

### 4.3 个股数据同步

```
sync_stock_basics() → PytdxSource.get_stock_basics()（优先）
                     → AkShare（回退）
                     → BaoStock（回退）

sync_daily_data()   → PytdxSource.get_stock_daily() 遍历每只股票
                     → 10 线程并行（ThreadPoolExecutor）
                     → 批量 bulk_write upsert
```

### 4.4 因子计算

```
calculate_rps(target='stock|sector|all')
    └─► RPSCalculator（相对强弱指标）
          └─► 计算所有个股 / 板块的 5/10/20/60/120 日 RPS
          └─► 写入 factor_results 集合
```

**关键过滤规则（RPS 计算前）：**

| 品种类型 | 最小存续天数 | 说明 |
|---------|------------|------|
| `stock` (个股) | ≥ 120 个交易日 | 新股上市不足 120 天的不参与 RPS 截面排名，避免上市初期价格剧烈波动失真 |
| `sector` (板块) | ≥ 20 个交易日 | 板块指数或板块聚合日线不足 20 天的不参与 RPS 计算，避免样本不足导致排名失真 |

过滤逻辑同时在 [factor_engine.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/factor_engine.py)（主路径）与 [rps_calculator.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/rps_calculator.py)（备用路径）中实现，确保两处一致。判断依据为每只股票/每个板块在 `daily_data` 中的有效日线条数（trade_date 计数）。

---

## 5. MongoDB 数据模型

### 5.1 集合清单

| 集合 | 用途 | 文档数（典型） |
|------|------|----------------|
| `stock_basics` | 股票基础信息（代码/名称/市场/上市日期） | ~5,000 只 |
| `sector_basics` | 板块基础信息（名称/来源/成分股数） | ~350 个 |
| `daily_data` | K 线数据（个股 + 板块，`data_type` 区分） | ~4-5M 条 |
| `factor_results` | 因子计算结果（RPS 等） | 动态 |
| `task_status` | 同步任务状态 | 运行时临时 |
| `index_basics` | 指数基础信息 | 备用 |
| `stock_universe` | 选股池（可扩展） | 备用 |
| `backtest_results` | 回测结果 | 动态 |

### 5.2 关键索引设计

```javascript
// daily_data
{ stock_code: 1, trade_date: 1 }   // 复合唯一索引（K 线按代码+日期定位）
{ data_type: 1 }                   // 过滤类型索引
{ trade_date: 1 }                  // 日期范围查询

// sector_basics
{ code: 1 }                        // 板块代码唯一索引
{ source: 1 }                      // 按来源过滤（概念/行业）

// factor_results
{ stock_code: 1, factor_name: 1, trade_date: 1 }  // 复合索引
```

### 5.3 字段规范

| 字段 | 类型 | 说明 |
|------|------|------|
| `stock_code` | string | 统一使用 A 股代码（纯数字，6 位），如 "600519" |
| `trade_date` | string | `YYYYMMDD` 格式字符串，如 "20260610" |
| `data_type` | string | `"stock"` = 个股；`"sector"` = 板块 |
| `code`（sector） | string | 内部统一格式：`"SECTOR_板块名"` |
| `ths_code` | string | 预留字段（历史原因），当前为空字符串 |

---

## 6. API 接口（后端）

### 6.1 板块板块同步

`POST /api/factors/sync-sectors` —— 同步板块列表 + 板块指数日线（后台任务）

```json
// POST /api/factors/sync-sectors
// 触发板块数据同步（block_gn.dat + block_zs.dat + 880/881 指数日线）
// 返回任务 ID，前端可轮询获取进度

Request:  {}
Response: {
  "success": true,
  "task_id": "sector_sync_20260610_143025"
}
```

`GET /api/factors/tasks/{task_id}` —— 轮询任务进度

```json
{
  "status": "running|completed|failed",
  "message": "已同步 354 个板块，41 个有指数日线",
  "total_count": 354,
  "completed_count": 41,
  "current_stock_name": "半导体"
}
```

`POST /api/factors/sync` —— 同步个股日线 + 股票基础信息

`POST /api/factors/calculate-rps?target=sector|stock|all` —— RPS 计算

`POST /api/factors/clear-rps` —— 清除 RPS 数据

`GET /api/factors/sectors?min_stock_count=5` —— 获取板块列表（用于下拉选择）

---

## 7. 核心数据结构示例

### 板块基础文档

```json
{
  "code": "SECTOR_光刻机",
  "name": "光刻机",
  "ths_code": "",
  "source": "概念",
  "stock_count": 12,
  "stock_codes": ["600703", "002436", "300223", ...],
  "block_type": 2,
  "update_time": ISODate("2026-06-10T...")
}
```

### 板块日线文档

```json
{
  "stock_code": "SECTOR_光刻机",
  "trade_date": "20260610",
  "open": 1250.50,
  "close": 1280.30,
  "high": 1295.00,
  "low": 1245.20,
  "volume": 28500000,
  "amount": 3580000000,
  "data_type": "sector",
  "data_source": "tdx_880",
  "update_time": ISODate("2026-06-10T...")
}
```

---

## 8. 调试与验证

### 8.1 测试脚本清单

项目根目录下提供若干测试脚本（开发期使用，**不建议在生产环境运行**）：

| 脚本 | 用途 |
|------|------|
| `tests/test_pytdx_source.py` | 测试板块文件解析和名称匹配 |
| `tests/test_sectors.py` | 查看 MongoDB 中板块数据 |
| `tests/test_match.py` | 调试板块名 → 880/881 代码匹配 |
| `tests/test_rps.py` | 测试 RPS 计算逻辑 |

### 8.2 验证数据完整性

```bash
# 1. 验证板块数量正确（应 >= 330）
python3 -c "
import sys; sys.path.insert(0, '_vendor/pytdx')
from app.data.db import get_db
db = get_db()
print('板块总数:', db['sector_basics'].count_documents({}))
print('概念板块:', db['sector_basics'].count_documents({'source': '概念'}))
print('行业板块:', db['sector_basics'].count_documents({'source': '行业'}))
print('有日线板块数:', len(list(db['daily_data'].aggregate([
    {'$match': {'data_type': 'sector'}},
    {'$group': {'_id': '$stock_code'}}
]))
"

# 2. 验证日线数据条数
python3 -c "
from app.data.db import get_db
db = get_db()
print('板块日线数:', db['daily_data'].count_documents({'data_type': 'sector'}))
print('个股日线数:', db['daily_data'].count_documents({'data_type': 'stock'}))
"
```

---

## 9. 设计决策与取舍

### 9.1 为何选择通达信（pytdx）而不是同花顺（akshare）

| 维度 | 通达信 pytdx | 同花顺 akshare |
|------|-------------|-------------|
| **板块数量** | 350+（246 概念 + 108 行业） | ~100 个概念 |
| **数据完整性** | 含完整成分股列表，历史 K 线长 | 概念板块常缺失，历史数据不完整 |
| **稳定性** | 通达信协议长期稳定 | Web API 经常变更 |
| **指数日线** | 880XXX/881XXX 指数直接获取 | 需依赖同花顺概念指数，常失效 |
| **更新频率** | 实时（与通达信客户端一致） | 延迟 1-2 小时 |
| **跨平台** | Linux/Mac/Windows 均可 | Web API 跨平台但不可靠 |

### 9.2 为何保留 `ths_code` 字段

**历史遗留**：早期版本使用同花顺数据源，板块代码格式为 `ths_xxxxx`。迁移到通达信后，为避免破坏已有数据结构，保留该字段（目前为空字符串）。

**未来计划**：下一次 schema 迁移时可将 `ths_code` 重命名为 `tdx_code`，存储 880/881 指数代码。

### 9.3 为何部分板块没有日线数据

354 个板块中约 41 个有直接通达信指数日线（880/881 代码）。

**剩余 313 个板块的解决思路**（尚未实现）：

1. **成分股等权/市值加权合成**：
   ```python
   # 伪代码
   for block in blocks_without_tdx_index:
       for date in trading_days:
           # 取所有成分股的当日涨跌幅均值作为板块指数涨跌幅
           avg_change = mean(stock_daily[code, date].change_pct
                             for code in block.stock_codes
                             if code in stock_daily)
           # 由涨跌幅回溯合成指数价格
   ```

2. **扩展通达信板块指数映射**：
   - 维护更多概念板块与 881XXX 代码的别名映射
   - 人工补充 `BLOCK_ALIAS_MAP`

3. **让无日线板块参与 RPS 计算**：
   - 即使无独立指数日线，仍可计算成分股的平均 RPS
   - 或标记 `has_daily_data=False`，RPS 仅计算有日线的板块

---

## 10. 常见问题排查

### 10.1 板块同步后找不到某概念板块

**问题**：如"存储芯片"板块未出现在列表中

**排查**：
1. `python3 -c "from app.data.sources.pytdx_source import PytdxSource; blocks = PytdxSource.get_concept_blocks(); [print(b['name']) for b in blocks if '存储' in b['name']]"`
2. 确认 block_gn.dat 是否包含该板块
3. 如包含但被解析器忽略 → 调试 `_parse_block_file()` 的 GBK 识别逻辑

### 10.2 板块同步成功但 RPS 计算结果为 0

**问题**：板块 RPS 全为 0 或 NaN

**可能原因**：
1. 该板块没有日线数据（未匹配到 880/881 指数）
2. 日线数据历史长度不足 120 天（RPS 最小时间窗口）

**解决**：
- 检查 `db.daily_data.count_documents({data_type: 'sector', stock_code: 'SECTOR_板块名'})`
- 如无数据 → 考虑成分股等权合成（见 9.3）

### 10.3 通达信服务器连接失败

**症状**：`_connect()` 返回 `None`，无板块数据

**排查**：
1. 网络是否可访问 `180.153.18.170:7709`
2. 尝试切换 `TDX_SERVERS` 列表中的其他服务器
3. 检查防火墙 / 代理设置
4. 如果开发环境无网络 → 回退使用 `tqcenter_source.py`（需要 Windows 客户端）

### 10.4 股票代码解析错误

**症状**：板块的 `stock_codes` 列表为空或含乱码

**排查**：`_parse_block_file()` 中股票代码提取逻辑：
- 检查 `0x02 0x00` 标志位的位置是否正确
- 验证 `6 位 ASCII 数字 + 0x00` 分隔模式是否仍适用于当前通达信文件格式
- 可能需要更新二进制解析规则（通达信会不定期升级文件格式）

---

## 11. 运维与监控

### 11.1 日志格式

所有 `DataManager` 同步任务输出结构化日志（标准输出 + 后台 API 响应）：

```
[2026-06-10 14:30:25] sync_sector_indices: 读取通达信板块信息...
[2026-06-10 14:30:28] 概念板块: 246 个
[2026-06-10 14:30:29] 行业板块: 108 个
[2026-06-10 14:30:31] 扫描通达信 880/881 指数代码: 56 个
[2026-06-10 14:31:45] 完成: 共 354 个板块，63878 条日线聚合
[2026-06-10 14:32:10] RPS sector: 41 个板块 × 1558 个交易日 = 63878 条计算
```

### 11.2 常见数据质量问题

| 现象 | 原因 | 解决 |
|------|------|------|
| 板块名称乱码（"3008533"等） | 旧解析器未正确识别 GBK 编码范围 | 使用新版 `_parse_block_file()` |
| 概念板块数 < 200 | `block_gn.dat` 下载不完整或解析不全 | 检查文件大小、重试下载 |
| 板块日线数 0 | 未匹配到 880/881 指数代码 | 扩展 `BLOCK_ALIAS_MAP` |
| 同日数据重复 | 代码 + 日期未建唯一索引 | 建立 `{stock_code:1, trade_date:1}` 唯一索引 |
| 数据缺失最近交易日 | 增量起始日期计算有误 | 调小 `latest_date - 7` 的安全窗口 |

---

## 12. 扩展方向（TODO）

### 12.1 板块指数等权合成

为无通达信指数的 313 个板块合成等权日线：

```
输入：所有股票日线数据 + 板块成分股列表
算法：对每个交易日，计算成分股涨跌幅的等权平均
输出：合成板块日线（data_source='synthetic_equal_weight'）
```

### 12.2 市值加权指数

在 `stock_basics` 中补充市值字段 → 市值加权合成 → 更接近实际市场指数

### 12.3 板块内个股排名聚合

每个板块计算：成分股平均 RPS、上涨家数 / 下跌家数、涨停家数等 → 作为板块强度辅助指标

### 12.4 通达信自定义数据（*.dat）扩展

- `block.dat` — 自选股 / 自定义板块
- `hq.dat` — 实时行情（盘中）
- `finance.dat` — 财务数据
- 这些文件的解析器可以复用 `_parse_block_file()` 的模式

---

## 13. 代码参考索引

| 模块 / 文件 | 行号范围 | 说明 |
|------------|---------|------|
| [app/data/manager.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/data/manager.py) | 1-200 | DataManager 定义、个股数据同步 |
| [app/data/manager.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/data/manager.py) | 295-620 | **板块数据同步核心逻辑** |
| [app/data/sources/pytdx_source.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/data/sources/pytdx_source.py) | 1-30 | 服务器列表与模块初始化 |
| [app/data/sources/pytdx_source.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/data/sources/pytdx_source.py) | 46-64 | `_connect()` 通达信服务器连接 |
| [app/data/sources/pytdx_source.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/data/sources/pytdx_source.py) | 68-224 | **板块文件二进制解析器** |
| [app/data/sources/pytdx_source.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/data/sources/pytdx_source.py) | 228-292 | 概念 / 行业 / 风格板块获取入口 |
| [app/data/sources/pytdx_source.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/data/sources/pytdx_source.py) | 296-358 | 板块指数日线获取 |
| [app/data/sources/pytdx_source.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/data/sources/pytdx_source.py) | 360-417 | 个股日线获取 |
| [app/data/sources/pytdx_source.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/data/sources/pytdx_source.py) | 419-1300+ | **板块名称智能匹配 + BLOCK_ALIAS_MAP**（900+ 条别名） |
| [app/data/db.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/data/db.py) | 全文 | MongoDB 连接与 CRUD 封装 |
| [app/server/api/factors.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/server/api/factors.py) | 600-680 | API 路由（板块同步 + RPS 计算） |
| [app/data/task_manager.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/data/task_manager.py) | 全文 | 后台任务状态管理 |

---

## 14. 依赖安装

```bash
# 核心依赖
pip install pymongo pandas pytdx python-dotenv uvicorn fastapi

# pytdx 从源码克隆（推荐，因为 PyPI 版本较旧）
git clone --depth 1 https://github.com/rainx/pytdx.git _vendor/pytdx
# 然后在代码中 sys.path.insert(0, '_vendor/pytdx')

# 可选回退数据源
pip install akshare baostock yfinance

# 启动服务（开发环境）
cd /Users/yubo/Desktop/work/study/YuQuant
source venv/bin/activate
uvicorn app.server.main:app --host 0.0.0.0 --port 8000 --reload
```

## 15. 典型运行结果（参考）

```
板块同步一次：
  └─► 读取板块文件: ~3 秒
  └─► 解析 + 保存基础信息: ~2 秒
  └─► 扫描 880/881 指数代码: ~1 秒
  └─► 下载 41 个板块日线: ~80 秒（每个板块 2-3 秒）
  └─► 总计: ~90 秒
  └─► 产出: 354 板块文档 + 63,878 条日线文档

RPS 计算一次（板块）：
  └─► 41 个板块 × 1558 个交易日 × 5 个周期
  └─► 约 320,000 条 RPS 记录
  └─► 耗时: ~30 秒

个股同步一次（全市场）：
  └─► 5,000 只股票 × 1558 天 ≈ 7.8M 条日线
  └─► 10 线程并行: 约 30-60 分钟
```

---

## 16. 变更记录

| 日期 | 变更 | 影响范围 |
|------|------|---------|
| 2026-06-05 | 从 SQLite+HDF5 迁移到 MongoDB | 全量数据重构 |
| 2026-06-10 | 替换同花顺（akshare）为通达信（pytdx）板块数据源 | sync-sectors API、板块数据模型 |
| 2026-06-10 | 实现自定义 block_gn.dat 解析器 | 板块数量从 100+ 提升到 350+ |
| 2026-06-10 | 实现板块名 → 880/881 代码智能匹配 | 41 个板块获得指数日线 |

---

## 17. 下一步建议

1. **合成指数**：为无通达信指数的 313 个板块实现成分股等权合成日线
2. **市值数据**：补充 `stock_basics` 市值字段 → 支持市值加权合成指数
3. **板块内个股统计**：每个板块的上涨/下跌/涨停家数、平均 RPS 等聚合指标
4. **前端可视化**：在「市场分析」页面增加板块 RPS 排行与板块成分股联动
5. **增量优化**：每日只同步新增交易日数据（目前逻辑已有，但可进一步减少 API 调用）
6. **HTTP API 健康检查**：增加 `GET /api/factors/health` 验证所有数据源连通性

---

**文档版本**：1.0（2026-06-10）
**维护者**：后端代理（DataManager / PytdxSource）
**关联文档**：
- [数据库设计](file:///Users/yubo/Desktop/work/study/YuQuant/docs/database/mongodb-schema.md)
- [架构设计](file:///Users/yubo/Desktop/work/study/YuQuant/docs/architecture/overview.md)
- [系统架构与数据流](file:///Users/yubo/Desktop/work/study/YuQuant/docs/architecture/data-source-strategy.md)
- [前端应用](file:///Users/yubo/Desktop/work/study/YuQuant/docs/features/frontend-app.md)
