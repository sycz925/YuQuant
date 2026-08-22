# factors 域收口里程碑（剩余 10 处直连）

日期：2026-08-16

- **[负责代理]**：BackendAgent
- **[可用技能]**：@skills/vibecoding-refactor、@skills/VibeSec-Skill、@skills/autoproject

## 背景

`app/server/api/factors.py` 已完成 6 处 CRUD 收口（禁用/创建/DeepSeek 配置/导入简单 CRUD/清任务），剩余 **10 处 `db[...]` 直连**，分散在 3 个函数：

| 函数 | 直连数 | 性质 |
| :--- | :--- | :--- |
| `get_sector_daily_data` | 1 | 板块日线查询（带特定投影） |
| `get_sector_stocks` | 4 | 板块成分股（板块信息 + 最新交易日 + 成分股行情 + 股票名） |
| `import_sector_codes_from_excel` | 5 | Excel 导入 + 后台 `_sync_sector_daily` 均线计算 |

## 前置检查（先补表征测试，锁定返回结构）

在 `tests/` 下新增，用 `unittest.mock` 打掉 `get_collection`/repository，锁定当前返回结构：

1. `tests/test_sector_daily_data.py`：锁定 `GET /factors/sectors/{code}/daily` 的返回字段（`vol`→`volume` 映射、降序后 `reverse` 升序）。
2. `tests/test_sector_stocks.py`：锁定 `GET /factors/sectors/{code}/stocks` 的返回结构（`chg_pct`→`change_pct` 映射、`name` 字段注入、RPS 红筛选）。

> 这些测试先"绿"（锁定现状），重构后仍绿 = 行为未变。

## 执行步骤

### 1. 查询收口（5 处，低风险）

- `get_sector_daily_data` → `SectorRepository` 补 `get_daily_bars(code, start, end, limit, projection)`（带投影的日线查询，当前 `get_daily_data` 投影为全字段，不匹配）。
- `get_sector_stocks` →
  - 板块信息：复用 `SectorRepository.get_by_code`
  - 最新交易日/成分股行情/股票名：`StockRepository` 补 `get_latest_trade_date(codes)`、`get_daily_quotes(codes, trade_date, projection)`、`get_stock_names(codes)`

### 2. 均线计算下沉（5 处，中风险）

`import_sector_codes_from_excel` 的 `_sync_sector_daily` 手算了 MA5~MA250、VOL_MA、区间涨幅、`chg_pct`、`is_final`——**与 `app/data/db.py:bulk_upsert_daily_data` 的均线计算逻辑重复**。

- 将 `_sync_sector_daily` 的均线计算下沉到 `app/data/`（复用或抽公共函数），api 层只调 `bulk_upsert_daily_data`（它写入时已算均线/区间涨幅）。
- 消除 api 层手算均线的重复实现（DRY）。

## 验证

- 后端：`python -m unittest discover -s tests` 全绿（含新增表征测试）。
- 手动：curl 板块日线/成分股接口，与重构前返回一致；Excel 导入一个板块，验证均线字段与重构前一致。

## 明确不做（YAGNI）

- 不动 `import_stocks`/`import_sectors` 已收口的部分。
- 不做 `calendar`/`market_review`（独立里程碑）。
- 不引入新依赖。
