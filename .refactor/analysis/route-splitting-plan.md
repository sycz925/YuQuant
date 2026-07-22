# 路由文件拆分计划

**创建日期**: 2026-07-22
**目标**: 将过大的路由文件拆分为职责清晰的小文件

---

## 当前状态

| 文件 | 行数 | 问题 |
|------|------|------|
| market_review.py | 3115 | 混合了数据计算、信号分析、AI分析 |
| factors.py | 1915 | 混合了因子计算、指数管理、板块管理 |
| calendar.py | 1546 | 混合了日历快照、周/月总结、重算 |

---

## 拆分策略

### market_review.py (3115行) → 4个文件

| 新文件 | 职责 | 预估行数 |
|--------|------|----------|
| `market_review.py` | API 端点（瘦路由） | ~300 |
| `market_data.py` | 数据计算函数 | ~800 |
| `market_signals.py` | 信号分析函数 | ~600 |
| `market_ai.py` | AI 分析函数 | ~400 |

**需要迁移的函数**:

#### → market_data.py
- `calculate_nh_nl_series()` (line 18)
- `precompute_market_daily()` (line 103)
- `get_market_daily()` (line 654)
- `_compute_realtime()` (line 2196)
- `_aggregate_base_data()` (line 2361)

#### → market_signals.py
- `generate_market_overview()` (line 701)
- `_calc_market_summary()` (line 989)
- `_calc_market_summary_fast()` (line 1038)
- `_calc_strong_stocks()` (line 1141)
- `_calc_industry_cluster()` (line 1209)
- `calc_market_signals()` (line 1230)
- `analyze_new_high_blocks()` (line 1466)
- `analyze_low_position_sectors()` (line 1728)
- `analyze_active_sectors()` (line 1916)
- `calc_ma_breadth_history()` (line 2092)

#### → market_ai.py
- `_call_deepseek()` (line 2927)
- `generate_ai_analysis()` (line 2750)

---

### factors.py (1915行) → 4个文件

| 新文件 | 职责 | 预估行数 |
|--------|------|----------|
| `factors.py` | API 端点 | ~200 |
| `factors_cr5.py` | CR5 计算 | ~300 |
| `factors_indices.py` | 指数管理 | ~400 |
| `factors_sectors.py` | 板块管理 | ~400 |
| `factors_rps.py` | RPS 计算 | ~300 |

---

### calendar.py (1546行) → 3个文件

| 新文件 | 职责 | 预估行数 |
|--------|------|----------|
| `calendar.py` | API 端点 | ~200 |
| `calendar_snapshot.py` | 日历快照 | ~400 |
| `calendar_summary.py` | 周/月总结 | ~500 |
| `calendar_recalc.py` | 重算逻辑 | ~300 |

---

## 执行顺序

1. **Phase 1**: 拆分 market_review.py（最大文件）
2. **Phase 2**: 拆分 factors.py
3. **Phase 3**: 拆分 calendar.py

每个 Phase 完成后验证 API 端点正常工作。

---

## 注意事项

1. 拆分时保持 API 端点不变，只移动内部函数
2. 使用相对导入避免循环依赖
3. 每个新文件添加 `__all__` 导出列表
4. 拆分后运行测试验证
