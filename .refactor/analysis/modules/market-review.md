# market_review.py 重构任务清单

**文件**: `app/server/api/market_review.py` (3095行)
**目标**: 拆分为 5 个文件，迁移 28 处 get_db() 调用

---

## 文件结构总览

### 当前结构（1个文件，3095行）
```
api/market_review.py
├── 数据计算函数 (7个)
├── 行业/股票辅助函数 (4个)
├── 信号分析函数 (7个)
├── 板块分析函数 (4个)
├── AI分析函数 (1个)
└── 路由端点 (11个)
```

### 目标结构（5个文件）
```
api/market_review.py          # 瘦路由（~250行）
services/market_data.py       # 数据计算函数（~900行）
services/market_signals.py    # 信号分析函数（~700行）
services/market_sectors.py    # 板块分析函数（~700行）
services/market_ai.py         # AI分析函数（~400行）
```

---

## Step 1: 创建 services/market_data.py（数据计算层）

**职责**: 所有数据读取、计算、缓存逻辑

### 需要迁移的函数

| 函数 | 行号 | 行数 | 说明 |
|------|------|------|------|
| `calculate_nh_nl_series()` | L18-100 | 83 | NH-NL 序列计算 |
| `precompute_market_daily()` | L103-651 | 549 | 核心预计算函数 |
| `get_market_daily()` | L654-676 | 23 | 读取缓存/触发计算 |
| `get_latest_trade_date()` | L678-688 | 11 | 获取最新交易日 |
| `get_previous_trade_date()` | L691-698 | 8 | 获取前一交易日 |
| `_build_stock_industry_map()` | L927-950 | 24 | 股票→行业映射 |
| `_build_stock_industries_map()` | L953-971 | 19 | 股票→行业列表映射 |
| `_get_latest_trade_date()` | L974-977 | 4 | ⚠️ **与 L678 重复，删除** |
| `_get_daily_data_for_stock()` | L980-986 | 7 | 获取个股日线数据 |
| `_compute_realtime()` | L2196-2359 | 164 | 实时计算 base_data |
| `_aggregate_base_data()` | L2361-2439 | 79 | 周期聚合 base_data |

**依赖处理**:
- `precompute_market_daily()` 内部调用 `analyze_low_position_sectors()`, `analyze_active_sectors()`, `analyze_new_high_blocks()` → 需要从 services/market_sectors.py 导入
- `precompute_market_daily()` 内部调用 `_quantile_groups` → 从 `market_analysis.py` 导入

### get_db() 替换
- 所有函数内的 `get_db()` 替换为 `MarketRepository` 实例

---

## Step 2: 创建 services/market_signals.py（信号分析层）

**职责**: 市场信号计算、概览生成、强弱分析

### 需要迁移的函数

| 函数 | 行号 | 行数 | 说明 |
|------|------|------|------|
| `generate_market_overview()` | L701-924 | 224 | 市场概览生成 |
| `_calc_market_summary()` | L989-1035 | 47 | 市场摘要（慢速） |
| `_calc_market_summary_fast()` | L1038-1138 | 101 | 市场摘要（快速） |
| `_calc_strong_stocks()` | L1141-1207 | 67 | 强势股计算 |
| `_calc_industry_cluster()` | L1209-1228 | 20 | 行业聚类 |
| `calc_market_signals()` | L1230-1392 | 163 | 市场信号综合 |
| `_generate_combined_interpretation()` | L1394-1464 | 71 | 信号解读 |

**依赖处理**:
- `_calc_market_summary_fast()` 内部调用 `_build_stock_industry_map()` → 从 services/market_data.py 导入
- `_calc_strong_stocks()` 内部调用 `_build_stock_industry_map()` → 同上

### get_db() 替换
- 所有函数内的 `get_db()` 替换为 `MarketRepository` 实例

---

## Step 3: 创建 services/market_sectors.py（板块分析层）

**职责**: 板块分析、新高板块、低位板块、活跃板块

### 需要迁移的函数

| 函数 | 行号 | 行数 | 说明 |
|------|------|------|------|
| `analyze_new_high_blocks()` | L1466-1726 | 261 | 新高强力板块分析 |
| `analyze_low_position_sectors()` | L1728-1914 | 187 | 低位潜力板块分析 |
| `analyze_active_sectors()` | L1916-2090 | 175 | 异动活跃板块分析 |
| `calc_ma_breadth_history()` | L2092-2194 | 103 | MA 广度历史计算 |

**依赖处理**:
- `analyze_new_high_blocks()` 内部调用 `_build_stock_industries_map()` → 从 services/market_data.py 导入
- `analyze_new_high_blocks()` 内部调用 `_call_deepseek()` → 从 services/market_ai.py 导入

### get_db() 替换
- 所有函数内的 `get_db()` 替换为 `MarketRepository` 实例

---

## Step 4: 创建 services/market_ai.py（AI分析层）

**职责**: DeepSeek AI 调用、结果落库

### 需要迁移的函数

| 函数 | 行号 | 行数 | 说明 |
|------|------|------|------|
| `_call_deepseek()` | L2907-2938 | 32 | 调用 DeepSeek 并落库 |

**依赖处理**:
- 内部调用 `get_deepseek_analyst()` → 从 `app.server.api.deepseek_analyst` 导入（后续迁移到 services/deepseek_service.py）

---

## Step 5: 精简 api/market_review.py（瘦路由层）

**保留**: 11 个路由端点，每个端点只做：接收请求 → 调用 service → 返回结果

### 保留的端点

| 端点 | 行号 | 应调用 |
|------|------|--------|
| `GET /base-data` | L2442-2519 | `market_data.get_base_data()` |
| `GET /overview` | L2536-2563 | `market_signals.generate_market_overview()` |
| `GET /signals` | L2566-2578 | `market_signals.calc_market_signals()` |
| `GET /new-high-blocks` | L2581-2609 | `market_sectors.analyze_new_high_blocks()` |
| `GET /low-position-sectors` | L2612-2629 | `market_sectors.analyze_low_position_sectors()` |
| `GET /active-sectors` | L2632-2649 | `market_sectors.analyze_active_sectors()` |
| `GET /group-stats` | L2652-2679 | `market_data.get_group_stats()` |
| `GET /ai-analysis` | L2682-2746 | `market_ai.get_ai_analysis()` |
| `POST /ai-analysis/generate` | L2749-2904 | `market_ai.generate_ai_analysis()` |
| `GET /ai-analysis/input-data` | L2941-2975 | `market_ai.get_ai_input_data()` |
| `GET /sector-detail` | L2978-3095 | `market_sectors.get_sector_detail()` |

### 路由层改造要点
- 移除所有 `from app.data.db import get_db`
- 移除所有内部函数定义
- 每个端点只做参数校验 + 调用 service + 异常处理
- 示例改造后：
```python
@router.get("/overview")
def get_market_overview_endpoint(date: Optional[str] = Query(None)):
    """主要大盘指数涨跌幅"""
    try:
        result = get_market_overview(date)
        if not result.get('success'):
            raise HTTPException(status_code=404, detail=result.get('message', '无数据'))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取市场概览失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

---

## 执行顺序

```
Phase 1: 创建 services/market_data.py
  ├── 1.1 创建文件，迁移数据计算函数
  ├── 1.2 替换 get_db() → MarketRepository
  ├── 1.3 删除 _get_latest_trade_date()（与 L678 重复）
  └── 1.4 验证：原有函数调用引用更新

Phase 2: 创建 services/market_signals.py
  ├── 2.1 迁移信号分析函数
  ├── 2.2 替换 get_db() → MarketRepository
  └── 2.3 更新对 market_data.py 的导入

Phase 3: 创建 services/market_sectors.py
  ├── 3.1 迁移板块分析函数
  ├── 3.2 替换 get_db() → MarketRepository
  └── 3.3 更新对 market_data.py 的导入

Phase 4: 创建 services/market_ai.py
  ├── 4.1 迁移 _call_deepseek()
  └── 4.2 更新对 deepseek_analyst 的导入

Phase 5: 精简 api/market_review.py
  ├── 5.1 改写 11 个端点为瘦路由
  ├── 5.2 移除所有内部函数定义
  ├── 5.3 移除 get_db 导入
  └── 5.4 全量接口测试验证
```

---

## 风险点

| 风险 | 说明 | 缓解措施 |
|------|------|----------|
| `precompute_market_daily()` 550行 | 是最大最复杂的函数，内部调用其他分析函数 | 保持函数签名不变，只替换 get_db() |
| 跨文件依赖 | 新文件间的相互导入 | 确保导入顺序：market_data → market_signals → market_sectors → market_ai |
| 循环导入 | `precompute_market_daily` 调用 `analyze_*_sectors` | 使用延迟导入或避免顶层循环依赖 |
| 其他文件引用 | `factors.py` 中 `_run_precompute_base_for_date()` 引用本文件函数 | 更新导入路径 |

---

## 验证清单

- [ ] 所有 11 个 API 端点响应格式不变
- [ ] `GET /base-data` 返回数据一致
- [ ] `GET /overview` 返回数据一致
- [ ] `GET /signals` 返回数据一致
- [ ] `GET /new-high-blocks` 返回数据一致
- [ ] `POST /ai-analysis/generate` 后台任务正常启动
- [ ] `GET /ai-analysis` 缓存读取正常
- [ ] `GET /sector-detail` 懒加载正常
- [ ] 其他文件引用 `market_review` 的导入路径已更新
- [ ] 无 `from app.data.db import get_db` 残留