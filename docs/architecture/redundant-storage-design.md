# 冗余存储设计文档

**日期**：2026-06-18  
**项目**：YuQuant - A股量化仿真与前端看板系统  
**目标**：优化市场分析和个股分析API响应速度

---

## 1. 背景与目标

### 1.1 性能瓶颈分析

当前市场分析API每次请求需要实时计算：

| API端点 | 实时计算字段 | 耗时 |
|---------|-------------|------|
| `/api/market_analysis` | chg_pct, RPS/成交额/股价分组统计 | 3-5秒 |
| `/api/market_analysis/bubble` | chg_pct, close_pct, amount_pct | 2-3秒 |
| `/api/market_analysis/active_pool` | chg_pct, rps_sum | 1-2秒 |

### 1.2 优化目标

- API响应时间降至 **500ms以内**
- 数据一致性：冗余字段在数据同步/RPS计算时自动更新
- 存储开销：控制在 **20%以内**

---

## 2. 冗余字段设计

### 2.1 `stock_daily` 集合新增字段

```javascript
{
  // === 原有字段保持不变 ===
  _id: ObjectId,
  stock_code: String,
  trade_date: String,
  open: Number,
  high: Number,
  low: Number,
  close: Number,
  vol: Number,
  amount: Number,
  data_type: String,
  data_source: String,
  is_final: Boolean,
  rps_10: Number | null,
  rps_20: Number | null,
  rps_50: Number | null,
  rps_120: Number | null,
  rps_250: Number | null,

  // === 新增冗余字段 ===
  
  // 1. 涨跌幅（消除前一日查询）
  chg_pct: Number,              // 日涨跌幅(%) = (close-prev_close)/prev_close*100
  
  // 2. RPS衍生指标（快速活跃股筛选）
  rps_sum: Number,              // RPS总分 = rps_20+rps_50+max(rps_120,rps_250)
  is_active: Boolean,           // 是否活跃股 = rps_sum>270 && chg_pct>5%
  
  // 3. 百分位指标（快速气泡图渲染）
  close_pct: Number,            // 股价百分位(1-100)
  amount_pct: Number,           // 成交额百分位(1-100)
  
  // 4. 均线指标（技术分析）
  ma10: Number | null,          // 10日移动平均线
  ma20: Number | null,          // 20日移动平均线
  ma50: Number | null,          // 50日移动平均线
  ma120: Number | null,         // 120日移动平均线
  
  // 5. 成交量均线（量能分析）
  vol_ma5: Number | null,       // 5日成交量均线
  vol_ma10: Number | null,      // 10日成交量均线
  vol_ma20: Number | null,      // 20日成交量均线
  vol_ma50: Number | null,      // 50日成交量均线
  
  // 6. 区间涨幅（多周期动量分析）
  chg_5d: Number | null,        // 5日涨幅(%) = (close-close_5d_ago)/close_5d_ago*100
  chg_10d: Number | null,       // 10日涨幅(%)
  chg_20d: Number | null,       // 20日涨幅(%)
  chg_50d: Number | null,       // 50日涨幅(%)
  chg_120d: Number | null,      // 120日涨幅(%)
  chg_250d: Number | null,      // 250日涨幅(%)
  
  update_time: ISODate
}
```

### 2.2 `sector_daily` 集合新增字段

```javascript
{
  // === 原有字段保持不变 ===
  
  // === 新增冗余字段 ===
  chg_pct: Number,              // 日涨跌幅(%)
  
  // 均线指标
  ma10: Number | null,          // 10日均线
  ma20: Number | null,          // 20日均线
  ma50: Number | null,          // 50日均线
  
  // 成交量均线
  vol_ma5: Number | null,       // 5日成交量均线
  vol_ma10: Number | null,      // 10日成交量均线
  vol_ma20: Number | null,      // 20日成交量均线
  
  // 区间涨幅（多周期动量分析）
  chg_5d: Number | null,        // 5日涨幅(%)
  chg_10d: Number | null,       // 10日涨幅(%)
  chg_20d: Number | null,       // 20日涨幅(%)
  chg_50d: Number | null,       // 50日涨幅(%)
  chg_120d: Number | null,      // 120日涨幅(%)
  chg_250d: Number | null,      // 250日涨幅(%)
  
  update_time: ISODate
}
```

### 2.3 新增集合 `market_stats_daily`

```javascript
{
  _id: ObjectId,
  trade_date: String,              // 交易日 YYYYMMDD
  rps_period: Number,              // RPS周期: 10/20/50/120/250
  total_stocks: Number,            // 参与统计的股票总数
  
  // 分组统计（预计算，消除运行时排序）
  rps_stats: [                     // RPS分组统计，50个区间
    {
      category_label: String,      // "(0,2]", "(2,4]" ...
      avg_chg: Number,             // 该区间平均涨跌幅
      count: Number                // 该区间股票数量
    }
  ],
  amount_stats: Array,             // 成交额分组统计（同结构）
  price_stats: Array,              // 股价分组统计（同结构）
  
  // 气泡图快照
  bubble_stock: Array,             // 个股气泡数据
  bubble_sector: Array,            // 板块气泡数据
  
  update_time: ISODate
}
```

---

## 3. 字段计算公式

### 3.1 涨跌幅 chg_pct

```python
# 需要前一日收盘价
chg_pct = (close - prev_close) / prev_close * 100
```

### 3.2 RPS总分 rps_sum

```python
# 用于活跃股筛选
rps_sum = rps_20 + rps_50 + max(rps_120, rps_250)
```

### 3.3 活跃股标记 is_active

```python
# 活跃股条件
is_active = (rps_sum > 270) and (chg_pct > 5)
```

### 3.4 移动平均线 MA

```python
# N日简单移动平均
ma_N = sum(close[i] for i in range(N)) / N
# 需要至少N日数据，不足时记为null
```

### 3.5 成交量均线 VOL_MA

```python
# N日成交量移动平均
vol_ma_N = sum(vol[i] for i in range(N)) / N
```

### 3.6 区间涨幅 CHG_Xd

```python
# N日涨幅（需要N日前收盘价）
chg_Nd = (close - close_Nd_ago) / close_Nd_ago * 100
# 数据不足时记为null
```

### 3.7 百分位计算

```python
# 对全市场按close/amount排序后计算百分位
close_pct = (rank / total) * 100  # 1-100
```

---

## 4. 更新策略

### 4.1 数据同步流程

```
┌─────────────────────────────────────────────────────────────┐
│                    数据同步流程                              │
├─────────────────────────────────────────────────────────────┤
│  Step 1: sync_daily_data()                                 │
│          ↓ 写入原始OHLCV数据                                │
│                                                             │
│  Step 2: calculate_rps()                                   │
│          ↓ 计算RPS + chg_pct + rps_sum + is_active         │
│                                                             │
│  Step 3: calculate_period_chg()  ← 新增                    │
│          ↓ 计算chg_5d/chg_10d/chg_20d/chg_50d/chg_120d/chg_250d    │
│                                                             │
│  Step 4: calculate_ma()  ← 新增                            │
│          ↓ 计算ma10/ma20/ma50/ma120                        │
│                                                             │
│  Step 5: calculate_vol_ma()  ← 新增                        │
│          ↓ 计算vol_ma5/vol_ma10/vol_ma20/vol_ma50          │
│                                                             │
│  Step 6: batch_calc_stats()  ← 新增                        │
│          ↓ 计算close_pct/amount_pct + market_stats_daily   │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 增量更新策略

| 字段类型 | 更新范围 | 触发时机 |
|---------|---------|---------|
| chg_pct, rps_*, rps_sum, is_active | 最近1天 | 每日RPS计算时 |
| chg_5d, chg_10d, chg_20d, chg_50d, chg_120d, chg_250d | 最近N天（N=最大周期） | 每日RPS计算后 |
| ma*, vol_ma* | 最近N天（N=最大周期） | 每日数据同步后 |
| close_pct, amount_pct | 最近1天 | 每日收盘后 |
| market_stats_daily | 最近1天 | 每日收盘后 |

### 4.3 代码修改点

| 文件 | 修改内容 |
|------|---------|
| `app/engine/factor_engine.py` | 新增 `calculate_ma()`, `calculate_vol_ma()`, `calculate_period_chg()` |
| `app/data/manager.py` | 在 `calculate_rps()` 后调用MA/涨幅计算 |
| `app/server/api/market_analysis.py` | 直接读取冗余字段，移除实时计算 |

---

## 5. 性能预估

### 5.1 优化前后对比

| 操作 | 优化前 | 优化后 | 提升 |
|------|--------|--------|------|
| 市场分析首页 | 3-5秒 | <500ms | **85%+** |
| 气泡图加载 | 2-3秒 | <300ms | **88%+** |
| 活跃股池查询 | 1-2秒 | <200ms | **87%+** |
| 个股日线查询 | <100ms | <50ms | 50%+ |

### 5.2 存储开销

| 集合 | 新增字段数 | 预计增长 |
|------|-----------|---------|
| stock_daily | 19个 | ~22% |
| sector_daily | 12个 | ~15% |
| market_stats_daily | 新集合 | ~80KB/天 |

### 5.3 最终字段汇总

| 集合 | 新增冗余字段数 | 预计存储增长 |
|------|---------------|-------------|
| stock_daily | 19个 | ~22% |
| sector_daily | 12个 | ~15% |
| market_stats_daily | 新集合 | ~80KB/天 |
| **合计** | **31个** | - |

---

## 6. 索引设计

### 6.1 `stock_daily` 新增索引

```javascript
// 活跃股快速查询
{ trade_date: 1, is_active: 1 }

// 按RPS总分排序
{ trade_date: 1, rps_sum: -1 }
```

### 6.2 `market_stats_daily` 索引

```javascript
// 唯一索引
{ trade_date: 1, rps_period: 1 }  // 唯一索引
```

---

## 7. 注意事项

1. **数据一致性**：冗余字段必须在数据同步流程中原子更新
2. **null处理**：数据不足时MA/VOL字段记为null，不影响查询
3. **向后兼容**：原有API返回格式保持不变，新增字段可选返回
4. **回刷策略**：首次部署需对历史数据进行一次性回刷计算

---

## 附录A：字段依赖关系

```
原始数据 (OHLCV)
    │
    ├─→ chg_pct (需要prev_close)
    │
    ├─→ rps_* (需要历史close序列)
    │   │
    │   └─→ rps_sum, is_active
    │
    ├─→ chg_5d/chg_10d/chg_20d/chg_50d/chg_120d/chg_250d (需要历史close)
    │
    ├─→ ma10/ma20/ma50/ma120 (需要历史close)
    │
    ├─→ vol_ma5/vol_ma10/vol_ma20/vol_ma50 (需要历史vol)
    │
    └─→ close_pct/amount_pct (需要全市场排序)
```
