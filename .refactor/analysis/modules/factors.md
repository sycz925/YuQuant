# 模块分析: 因子管理（factors.py）

**文件**: `app/server/api/factors.py` (1428行)
**路由数**: 20 | **函数数**: 30+

---

## 基本信息
- 入口: `router = APIRouter(prefix="/api/factors")`
- 架构状态: ⚠️ 新老架构混用

---

## Vibe Coding 问题检测

### 1. 新旧架构混用（核心问题）
- 文件头部同时导入 `get_index_factory()` 和 `get_db()`
- 部分路由已迁移到 factory（如 `get_cr5_factor`、`get_indices_list`）
- 部分路由仍有 13 处 `get_db()` 直接调用

### 2. 仍保留在 api 层的函数
| 函数 | 行数 | 应归属 |
|------|------|--------|
| `_run_precompute_base_for_date()` | ~237行 | MarketAggregator |
| `_run_sync_pe()` | ~113行 | IndexFactory |
| `_run_compare_stocks_task()` | ~80行 | 应该在 orchestrator |
| `_run_compare_sectors_task()` | ~80行 | 应该在 orchestrator |
| `_compare_update_status()` | ~6行 | 继续保留 |

### 3. 路由过多
- 20 个路由端点，职责混杂：
  - CR5% 因子（1个）
  - 指数管理（2个）
  - 板块管理（3个）
  - RPS 计算（3个）
  - 对比分析（3个）
  - 导入导出（3个）
  - 配置管理（2个）
  - 任务管理（3个）

### 4. 错误处理
- 37 处 `except Exception`

### 5. 代码质量问题
- `import_stocks()` 函数 ~180行
- `import_sectors()` 函数 ~50行
- 两个导入函数有大量重复的 Excel 解析逻辑

---

## 拆分方案

| 新文件 | 职责 | 预估行数 |
|--------|------|----------|
| `api/factors.py` | 瘦路由（20个端点） | ~200 |
| `factories/index_factory.py` | 迁移 `_run_sync_pe()` | +100 |
| `factories/market_aggregator.py` | 迁移 `_run_precompute_base_for_date()` | +200 |
| 删除 | 将 `_run_compare_*` 逻辑移到 orchestrator | - |

---

## 重构任务
| 编号 | 任务 | 优先级 |
|------|------|--------|
| M-FAC-01 | 迁移 `_run_precompute_base_for_date()` 到 MarketAggregator | P0 |
| M-FAC-02 | 迁移 `_run_sync_pe()` 到 IndexFactory | P0 |
| M-FAC-03 | 迁移 `_run_compare_*` 到 orchestrator | P1 |
| M-FAC-04 | 合并 import_stocks/import_sectors 重复逻辑 | P1 |
| M-FAC-05 | 13处 get_db() 替换 | P0 |