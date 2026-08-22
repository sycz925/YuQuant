# market_review 域收口里程碑（29 处直连）

日期：2026-08-16

- **[负责代理]**：BackendAgent
- **[可用技能]**：@skills/vibecoding-refactor、@skills/VibeSec-Skill、@skills/autoproject

## 背景

`app/server/api/market_review.py`（712 行）有 **29 处 `db[...]` 直连**，路由内夹带大量聚合、缓存读写、重算业务逻辑，属于「巨型控制器」。

主要直连函数（以 grep 核实）：

| 函数 | 直连点 |
| :--- | :--- |
| `get_base_data` / `get_overview` / `get_signals` | `base_data_daily`、`market_daily` 缓存读写、`stock_daily`/`index_daily` 查询 |
| `get_new_high_blocks` / `get_low_position_sectors` / `get_active_sectors` | `market_daily` 缓存 + 板块聚合 |
| `generate_ai_analysis` | `market_daily` 缓存 + 后台任务 |
| `get_sector_detail` | `sector_basics`、`sector_daily`、`stock_basics` 多集合 |

## 前置检查（先补表征测试）

在 `tests/` 下新增（`unittest.mock` 打掉 repository/get_db）：

1. `tests/test_market_review_overview.py`：锁定 `/market-review/overview` 返回结构（含缓存命中/未命中分支）。
2. `tests/test_market_review_signals.py`：锁定 `/market-review/signals` 返回结构。
3. `tests/test_market_review_sector_detail.py`：锁定板块详情返回结构。

## 执行步骤

### 1. 数据访问下移（建 `MarketReviewRepository`）

按查询类型封装到 repository（沿用 `MarketAnalysisRepository` 的模式）：

- 缓存读写：`get_cached(sub_collection, key, field)` / `set_cached(...)`（`market_daily` 的 `overview`/`new_high`/`active_sectors` 等子字段）。
- 基础数据：`get_base_data_range`、`get_latest_doc`。
- 聚合：`get_new_high_blocks`、`get_active_sectors`、`get_low_position_sectors` 的聚合管道。

### 2. 业务逻辑下沉（拆 `services/market_review_service.py`）

把路由里的聚合、缓存判断、重算逻辑下沉到 service，路由只做「参数解析 → 调 service → 组装响应」。

## 验证

- 后端测试全绿（含新增表征测试）。
- 手动：curl 各 `/market-review/*` 接口，与重构前返回一致。

## 明确不做（YAGNI）

- 不动 `calendar`/`factors`（独立里程碑）。
- 不改前端（返回结构不变）。
