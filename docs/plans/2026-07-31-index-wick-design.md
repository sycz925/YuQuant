# 指数盘中涨跌幅存储（长影线分析）

## 目标
在 `market_daily.overview.indices[]` 中存入每个启用指数的 open/high/low/close/pct_chg + prev_close，供前端自行计算长影线标注。

## 覆盖范围
`index_basics` 中 `is_disable=False` 的 7 个指数：上证指数、科创50、创业板指、深圳综指、沪深300、平均股价、微盘股。

## 字段结构（每个 index 对象）
```
code, name, close, pct_chg,          ← 原有
open, high, low, prev_close,         ← 新增
amount_today, amount_yesterday,       ← 原有
amount_ma5, amount_ma20,             ← 原有
comment,                             ← 原有（现落库存储，含影线标注）
wick: {type, max_chg, min_chg}       ← 新增
```

## 计算逻辑（precompute_market_daily 内）
1. 查询 `index_daily` 当日 open/high/low/close/chg_pct
2. 查前一交易日 close 作为 prev_close
3. 对每个指数：max_chg = (high-prev_close)/prev_close*100，min_chg = (low-prev_close)/prev_close*100
4. 判定长上影（max_chg - pct_chg > 2pp）→ 标注最大涨幅
5. 判定长下影（pct_chg - min_chg > 2pp）→ 标注最大跌幅
6. 落库结构化 wick + 文本 comment（含影线标注）

## 集成点
- `app/server/services/market_data.py:precompute_market_daily`（line 99-648）
- 被 daily_recalc_orchestrator 和 precompute 步骤调用

## 修改文件
- `app/server/services/market_data.py`：precompute_market_daily 中查询 index_daily + 计算影线
- `app/client/src/components/MarketOverview.jsx`：根据 wick 展示影线标注
