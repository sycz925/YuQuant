# 三大工厂 + 聚合器 + 编排器架构设计

**日期**：2026-07-21
**负责代理**：ArchitectAgent（设计文档，不修改代码）
**设计目标**：将一键更新 / 月度重算 / 单日重算的 7 个步骤，按数据域内聚到三大工厂，实现共用与按日期执行

---

## 1. 现状问题分析

### 1.1 当前 7 个步骤的实现位置

| 步骤 | 当前实现 | 数据域 | 操作集合 |
| :--- | :--- | :--- | :--- |
| 1. 同步指数 | `FactorService._run_sync_indices()` | 指数 | `index_basics` → `index_daily` |
| 2. 同步个股 | `sync._run_sync_task()` → `dm.sync_daily_data()` | 个股 | `stock_basics` → `stock_daily` |
| 3. 同步板块 | `dm.sync_sector_indices()` + `calculate_all_derived_fields(sector)` | 板块 | `sector_basics` → `sector_daily` |
| 4. 计算个股RPS | `FactorEngine.calculate_rps('stock')` + `dm.calculate_chg_fields('stock')` | 个股 | `stock_daily` |
| 5. 计算板块RPS | `FactorEngine.calculate_rps('sector')` + `dm.calculate_chg_fields('sector')` | 板块 | `sector_daily` |
| 6. 更新PE | `_run_sync_pe()` (legulegu.com) | 指数 | `index_basics.pe_ttm` |
| 7. 预计算基础数据 | `_run_precompute_base_for_date()` | **跨域聚合** | `stock_daily`+`index_daily`+`sector_daily` → `base_data_daily`+`market_daily` |

### 1.2 当前架构的痛点

1. **业务逻辑散落在 API 路由层**：`_run_sync_task`、`_run_precompute_base_for_date`、`_run_sync_pe`、`_run_update_task`、`_run_recalc_task` 全部写在 `api/` 下，违反分层架构
2. **三种编排流程重复调用原子能力**：一键更新、月度重算、单日重算都调用 `calculate_rps`、`calculate_chg_fields`，但调用顺序和参数不同，代码重复
3. **按日期执行能力缺失**：`FactorEngine.calculate_rps(max_dates=None)` 只能从最新日期回溯，无法指定任意历史日期重算
4. **进度回调不统一**：`is_external` 参数散落各处，外部任务与独立任务的进度更新逻辑分叉
5. **跨域聚合操作无归属**：步骤 7 同时读取三个数据域，无法归入任何单一工厂

---

## 2. 三大工厂架构设计

### 2.1 设计原则

1. **按数据域内聚**：每个工厂管理自己域内的 `basics` + `daily` + 衍生字段
2. **按日期执行**：所有方法支持 `target_date` 参数，None 表示最新日期
3. **原子能力与编排分离**：工厂只提供原子能力，编排逻辑由独立的 Orchestrator 组合
4. **跨域操作独立**：跨数据域的聚合操作放入 `MarketAggregator`，不归入任何单一工厂
5. **进度回调统一**：所有工厂方法接受可选的 `progress_callback` 参数，由编排器注入

### 2.2 架构拓扑图

```
┌─────────────────────────────────────────────────────────────────┐
│                       API 路由层 (api/)                          │
│   one_click_update.py / sync.py / factors.py / calendar.py      │
└────────────────────────┬────────────────────────────────────────┘
                         │ 只调用 Orchestrator
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                   编排层 (orchestrators/)                        │
│  ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐│
│  │ OneClickUpdate   │ │ MonthlyRecalc    │ │ DailyRecalc      ││
│  │ Orchestrator     │ │ Orchestrator     │ │ Orchestrator     ││
│  │ 7步全流程        │ │ 3步RPS+预计算    │ │ 3步RPS+预计算    ││
│  └────────┬─────────┘ └────────┬─────────┘ └────────┬─────────┘│
└───────────┼────────────────────┼────────────────────┼──────────┘
            │                    │                    │
            ▼                    ▼                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                  工厂层 (factories/) + 聚合器                    │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌─────────┐│
│  │ IndexFactory │ │ StockFactory │ │SectorFactory │ │ Market  ││
│  │              │ │              │ │              │ │Aggregator││
│  │ • sync_kline │ │ • sync_daily │ │ • sync_daily │ │         ││
│  │ • sync_pe    │ │ • compute_rps│ │ • compute_rps│ │•precomp ││
│  │ • compute_rps│ │ • compute_chg│ │ • compute_chg│ │•overview││
│  │ • compute_chg│ │ • compute_ma │ │ • compute_ma │ │•signals ││
│  │ • compute_ma │ │              │ │              │ │•new_high││
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └────┬────┘└
└─────────┼────────────────┼────────────────┼──────────────┼─────┘
          ▼                ▼                ▼              ▼
┌─────────────────────────────────────────────────────────────────┐
│                  数据访问层 (repositories/)                      │
│  IndexRepo / StockRepo / SectorRepo / BaseDataRepo / TaskRepo   │
└─────────────────────────────────────────────────────────────────┘
          ▲                ▲                ▲              ▲
          │                │                │              │
┌─────────────────────────────────────────────────────────────────┐
│                    数据源层 (data/sources/)                      │
│      TdxSource / AkShareSource / BaoStockSource / LeguleguSource│
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 三大工厂职责划分

#### IndexFactory（指数工厂）

```python
# app/server/factories/index_factory.py

class IndexFactory:
    """指数工厂 — 管理指数数据的同步与衍生计算"""

    def __init__(self, index_repo: IndexRepo, tdx_source: TdxSource,
                 legulegu_source: LeguleguSource, factor_engine: FactorEngine):
        self.repo = index_repo
        self.tdx = tdx_source
        self.legulegu = legulegu_source
        self.engine = factor_engine

    def sync_kline(self, target_date: Optional[str] = None,
                   progress_callback: Callable = None) -> SyncResult:
        """
        同步指数 K 线数据（TDX 数据源）
        :param target_date: 指定日期 YYYYMMDD，None 同步到最新
        """
        enabled_indices = self.repo.get_enabled_list()
        # ... 调用 self.tdx.get_index_bars() 并写入 index_daily
        return SyncResult(...)

    def sync_pe(self, target_date: Optional[str] = None,
                progress_callback: Callable = None) -> SyncResult:
        """
        同步指数 PE（legulegu.com 数据源）
        :param target_date: 指定日期，None 同步最新
        """
        # ... 调用 self.legulegu.get_pe() 并更新 index_basics.pe_ttm
        return SyncResult(...)

    def compute_rps(self, target_date: Optional[str] = None,
                    progress_callback: Callable = None) -> ComputeResult:
        """计算指数 RPS（注意：当前系统指数无 RPS，此方法预留）"""
        return ComputeResult(skipped=True, reason='指数不计算 RPS')

    def compute_chg(self, target_date: Optional[str] = None) -> ComputeResult:
        """计算指数区间涨幅"""
        # ... 调用 engine.calculate_chg_fields(target='index', trade_date=target_date)
        return ComputeResult(...)

    def compute_ma(self, target_date: Optional[str] = None) -> ComputeResult:
        """计算指数均线"""
        return ComputeResult(...)

    def run_full_pipeline(self, target_date: Optional[str] = None,
                          progress_callback: Callable = None) -> PipelineResult:
        """
        执行指数全流程：sync_kline → sync_pe → compute_chg → compute_ma
        一键更新时调用此方法
        """
        results = {}
        results['sync_kline'] = self.sync_kline(target_date, progress_callback)
        results['sync_pe'] = self.sync_pe(target_date, progress_callback)
        results['compute_chg'] = self.compute_chg(target_date)
        results['compute_ma'] = self.compute_ma(target_date)
        return PipelineResult(results)
```

#### StockFactory（个股工厂）

```python
# app/server/factories/stock_factory.py

class StockFactory:
    """个股工厂 — 管理个股数据的同步与衍生计算"""

    def __init__(self, stock_repo: StockRepo, data_manager: DataManager,
                 factor_engine: FactorEngine):
        self.repo = stock_repo
        self.dm = data_manager
        self.engine = factor_engine

    def sync_daily(self, target_date: Optional[str] = None,
                   max_workers: int = 4,
                   progress_callback: Callable = None) -> SyncResult:
        """
        同步个股日线数据
        :param target_date: 指定日期 YYYYMMDD，None 同步到最新
        """
        enabled_stocks = self.repo.get_enabled_codes()
        # ... 调用 self.dm.sync_daily_data(stock_codes, end_date=target_date, ...)
        return SyncResult(...)

    def compute_rps(self, target_date: Optional[str] = None,
                    progress_callback: Callable = None) -> ComputeResult:
        """
        计算个股 RPS
        :param target_date: 指定日期重算，None 从最新日期回溯
        """
        # ... 调用 self.engine.calculate_rps(data_type='stock', target_date=target_date)
        return ComputeResult(...)

    def compute_chg(self, target_date: Optional[str] = None) -> ComputeResult:
        """计算个股区间涨幅（5/10/20/50/120/250日）"""
        # ... 调用 self.dm.calculate_chg_fields(target='stock', trade_date=target_date)
        return ComputeResult(...)

    def compute_ma(self, target_date: Optional[str] = None) -> ComputeResult:
        """计算个股均线（MA10/20/50/120 + VOL_MA5/10/20/50）"""
        return ComputeResult(...)

    def run_full_pipeline(self, target_date: Optional[str] = None,
                          progress_callback: Callable = None) -> PipelineResult:
        """
        执行个股全流程：sync_daily → compute_chg → compute_ma → compute_rps
        一键更新时调用此方法
        注意：compute_rps 依赖 compute_chg 的结果，顺序不可调换
        """
        results = {}
        results['sync_daily'] = self.sync_daily(target_date, progress_callback=progress_callback)
        results['compute_chg'] = self.compute_chg(target_date)
        results['compute_ma'] = self.compute_ma(target_date)
        results['compute_rps'] = self.compute_rps(target_date, progress_callback)
        return PipelineResult(results)
```

#### SectorFactory（板块工厂）

```python
# app/server/factories/sector_factory.py

class SectorFactory:
    """板块工厂 — 管理板块数据的同步与衍生计算"""

    def __init__(self, sector_repo: SectorRepo, data_manager: DataManager,
                 factor_engine: FactorEngine):
        self.repo = sector_repo
        self.dm = data_manager
        self.engine = factor_engine

    def sync_daily(self, target_date: Optional[str] = None,
                   progress_callback: Callable = None) -> SyncResult:
        """同步板块日线数据"""
        enabled_sectors = self.repo.get_enabled_codes()
        # ... 调用 self.dm.sync_sector_indices(enabled_codes=enabled_sectors, ...)
        return SyncResult(...)

    def compute_rps(self, target_date: Optional[str] = None,
                    progress_callback: Callable = None) -> ComputeResult:
        """计算板块 RPS"""
        # ... 调用 self.engine.calculate_rps(data_type='sector', target_date=target_date)
        return ComputeResult(...)

    def compute_chg(self, target_date: Optional[str] = None) -> ComputeResult:
        """计算板块区间涨幅"""
        # ... 调用 self.dm.calculate_chg_fields(target='sector', trade_date=target_date)
        return ComputeResult(...)

    def compute_ma(self, target_date: Optional[str] = None) -> ComputeResult:
        """计算板块均线"""
        return ComputeResult(...)

    def run_full_pipeline(self, target_date: Optional[str] = None,
                          progress_callback: Callable = None) -> PipelineResult:
        """
        执行板块全流程：sync_daily → compute_chg → compute_ma → compute_rps
        """
        results = {}
        results['sync_daily'] = self.sync_daily(target_date, progress_callback)
        results['compute_chg'] = self.compute_chg(target_date)
        results['compute_ma'] = self.compute_ma(target_date)
        results['compute_rps'] = self.compute_rps(target_date, progress_callback)
        return PipelineResult(results)
```

### 2.4 MarketAggregator（市场聚合器）— 跨域操作独立化

**关键设计决策**：步骤 7（预计算基础数据）同时读取 `stock_daily`、`index_daily`、`sector_daily` 三个集合，写入 `base_data_daily` 和 `market_daily`。这是一个**跨域聚合**操作，不应归入任何单一工厂，否则会破坏工厂的数据域内聚性。

```python
# app/server/factories/market_aggregator.py

class MarketAggregator:
    """
    市场聚合器 — 跨数据域的聚合计算
    依赖三大工厂提供的数据，不直接操作原始集合
    """

    def __init__(self, stock_repo: StockRepo, index_repo: IndexRepo,
                 sector_repo: SectorRepo, base_data_repo: BaseDataRepo):
        self.stock_repo = stock_repo
        self.index_repo = index_repo
        self.sector_repo = sector_repo
        self.base_data_repo = base_data_repo

    def precompute_base_data(self, target_date: str,
                             progress_callback: Callable = None) -> ComputeResult:
        """
        预计算 base_data_daily：CR5/CR10/MA/NH-NL/涨跌家数/总成交额
        :param target_date: 必须指定日期
        """
        # 1. 计算CR5/CR10/MA/NH-NL（读取 stock_daily）
        # 2. 统计涨跌家数（读取 stock_daily）
        # 3. 统计总成交额（读取 index_daily）
        # 4. upsert 到 base_data_daily
        return ComputeResult(...)

    def generate_market_overview(self, target_date: str) -> Dict:
        """生成市场总览（写入 market_daily）"""
        return {...}

    def analyze_new_high_blocks(self, target_date: str) -> Dict:
        """分析新高板块（写入 market_daily.new_high）"""
        return {...}

    def run_full_pipeline(self, target_date: str,
                          progress_callback: Callable = None) -> PipelineResult:
        """
        执行聚合全流程：precompute_base_data → generate_market_overview → analyze_new_high_blocks
        """
        results = {}
        results['base_data'] = self.precompute_base_data(target_date, progress_callback)
        results['overview'] = self.generate_market_overview(target_date)
        results['new_high'] = self.analyze_new_high_blocks(target_date)
        return PipelineResult(results)
```

### 2.5 三种编排器（Orchestrator）

编排器负责组合工厂与聚合器的原子能力，形成三种业务流程。

#### OneClickUpdateOrchestrator（一键更新编排器）

```python
# app/server/orchestrators/one_click_orchestrator.py

class OneClickUpdateOrchestrator:
    """
    一键更新编排器
    流程：指数同步 → 个股同步 → 板块同步 → 个股RPS → 板块RPS → PE同步 → 预计算
    7个步骤严格顺序执行，任一步骤失败则停止
    """

    STEPS = [
        {'key': 'sync_index',   'name': '同步指数',     'handler': '_step_sync_index'},
        {'key': 'sync_stocks',  'name': '同步个股',     'handler': '_step_sync_stocks'},
        {'key': 'sync_sectors', 'name': '同步板块',     'handler': '_step_sync_sectors'},
        {'key': 'rps_stock',    'name': '计算个股RPS',  'handler': '_step_rps_stock'},
        {'key': 'rps_sector',   'name': '计算板块RPS',  'handler': '_step_rps_sector'},
        {'key': 'sync_pe',      'name': '更新PE',       'handler': '_step_sync_pe'},
        {'key': 'precompute',   'name': '预计算基础数据','handler': '_step_precompute'},
    ]

    def __init__(self, index_factory: IndexFactory,
                 stock_factory: StockFactory,
                 sector_factory: SectorFactory,
                 market_aggregator: MarketAggregator,
                 task_repo: TaskRepo):
        self.index_factory = index_factory
        self.stock_factory = stock_factory
        self.sector_factory = sector_factory
        self.market_aggregator = market_aggregator
        self.task_repo = task_repo

    def execute(self, target_date: Optional[str] = None) -> str:
        """执行一键更新，返回 task_id"""
        task_id = self.task_repo.create_task_with_steps(self.STEPS)
        thread = threading.Thread(
            target=self._run, args=(task_id, target_date), daemon=True
        )
        thread.start()
        return task_id

    def _run(self, task_id: str, target_date: Optional[str]):
        """后台执行 7 步流程"""
        tm = get_task_manager()
        for i, step in enumerate(self.STEPS):
            tm.start_step(task_id, i)
            try:
                handler = getattr(self, step['handler'])
                handler(task_id, target_date)
                tm.complete_step(task_id, i, f"{step['name']}完成")
            except Exception as e:
                tm.fail_step(task_id, i, str(e)[:200])
                return
        tm.complete_task(task_id, "一键更新完成")

    def _step_sync_index(self, task_id, target_date):
        self.index_factory.sync_kline(target_date, self._make_callback(task_id))

    def _step_sync_stocks(self, task_id, target_date):
        self.stock_factory.sync_daily(target_date, progress_callback=self._make_callback(task_id))

    def _step_sync_sectors(self, task_id, target_date):
        self.sector_factory.sync_daily(target_date, progress_callback=self._make_callback(task_id))

    def _step_rps_stock(self, task_id, target_date):
        # 先算 chg，再算 rps（rps 依赖 chg）
        self.stock_factory.compute_chg(target_date)
        self.stock_factory.compute_rps(target_date, self._make_callback(task_id))

    def _step_rps_sector(self, task_id, target_date):
        self.sector_factory.compute_chg(target_date)
        self.sector_factory.compute_rps(target_date, self._make_callback(task_id))

    def _step_sync_pe(self, task_id, target_date):
        self.index_factory.sync_pe(target_date, self._make_callback(task_id))

    def _step_precompute(self, task_id, target_date):
        date = target_date or datetime.now().strftime('%Y%m%d')
        self.market_aggregator.run_full_pipeline(date, self._make_callback(task_id))

    def _make_callback(self, task_id):
        """构造进度回调闭包"""
        def callback(current, total, message):
            get_task_manager().update_task_progress(
                task_id, completed_count=current, total_count=total,
                current_stock_name=message
            )
        return callback
```

#### DailyRecalcOrchestrator（单日重算编排器）

```python
# app/server/orchestrators/daily_recalc_orchestrator.py

class DailyRecalcOrchestrator:
    """
    单日重算编排器
    流程：个股RPS → 板块RPS → 预计算基础数据
    用于补算指定历史日期的数据
    """

    STEPS = [
        {'key': 'rps_stock',    'name': '计算个股RPS',   'handler': '_step_rps_stock'},
        {'key': 'rps_sector',   'name': '计算板块RPS',   'handler': '_step_rps_sector'},
        {'key': 'precompute',   'name': '预计算基础数据', 'handler': '_step_precompute'},
    ]

    def __init__(self, stock_factory, sector_factory, market_aggregator, task_repo):
        # ... 同上
        pass

    def execute(self, target_date: str) -> str:
        """单日重算必须指定日期"""
        if not target_date:
            raise ValueError("单日重算必须指定 target_date")
        # ... 同上模式
```

#### MonthlyRecalcOrchestrator（月度重算编排器）

```python
# app/server/orchestrators/monthly_recalc_orchestrator.py

class MonthlyRecalcOrchestrator:
    """
    月度重算编排器
    流程：遍历月份内每个交易日 → 对每个交易日执行 DailyRecalc
    """

    def __init__(self, daily_recalc: DailyRecalcOrchestrator, calendar_repo):
        self.daily_recalc = daily_recalc
        self.calendar_repo = calendar_repo

    def execute(self, year: int, month: int) -> str:
        """执行月度重算"""
        trading_days = self.calendar_repo.get_trading_days_in_month(year, month)
        # 逐日调用 daily_recalc，或并行执行
        for date in trading_days:
            self.daily_recalc.execute(date)
```

---

## 3. 共用性与按日期执行能力评估

### 3.1 共用性矩阵

| 原子能力 | IndexFactory | StockFactory | SectorFactory | MarketAggregator | 一键更新 | 单日重算 | 月度重算 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| sync_kline | ✅ | — | — | — | ✅ | — | — |
| sync_daily | — | ✅ | ✅ | — | ✅ | — | — |
| sync_pe | ✅ | — | — | — | ✅ | — | — |
| compute_rps | ✅(预留) | ✅ | ✅ | — | ✅ | ✅ | ✅ |
| compute_chg | ✅ | ✅ | ✅ | — | ✅ | ✅ | ✅ |
| compute_ma | ✅ | ✅ | ✅ | — | ✅ | ✅ | ✅ |
| precompute_base | — | — | — | ✅ | ✅ | ✅ | ✅ |
| generate_overview | — | — | — | ✅ | ✅ | ✅ | ✅ |

**结论**：`compute_rps`、`compute_chg`、`compute_ma` 被三种编排流程共用，`sync_*` 仅一键更新使用。工厂化后消除重复调用代码。

### 3.2 按日期执行能力

**当前问题**：
- `FactorEngine.calculate_rps(max_dates=None)` 只能从最新日期回溯，无法指定任意历史日期
- `_run_precompute_base_for_date(target_date)` 已支持按日期，但写死在 `factors.py`
- `_run_sync_pe` 不支持按日期（legulegu.com 只返回最新 PE）

**工厂化后的改进**：
- 所有工厂方法统一接受 `target_date: Optional[str]` 参数
- `None` 表示最新日期（一键更新场景）
- 指定日期表示历史重算（单日/月度重算场景）
- 需要改造 `FactorEngine.calculate_rps` 增加 `target_date` 参数，从指定日期开始向前回溯

---

## 4. 重构收益评估

### 4.1 ✅ 有利方面

| 收益点 | 说明 |
| :--- | :--- |
| **内聚性提升** | 每个工厂管理自己数据域，修改指数逻辑不会影响个股 |
| **共用性增强** | `compute_rps`/`compute_chg` 统一接口，三种编排器共用 |
| **按日期执行** | 所有方法支持 `target_date`，单日重算与一键更新共用同一套代码 |
| **可测试性** | 工厂方法原子化，可独立单元测试，无需启动整个编排流程 |
| **消除重复** | 当前 `_run_sync_task`、`_run_update_task`、`_run_recalc_task` 中重复的 `calculate_chg_fields` 调用被内聚 |
| **进度回调统一** | `progress_callback` 由编排器注入，工厂不关心任务状态管理 |
| **扩展性** | 新增"季度重算"只需新增 Orchestrator，无需改动工厂 |

### 4.2 ⚠️ 需要注意的设计陷阱

| 风险点 | 缓解措施 |
| :--- | :--- |
| **步骤 7 不能放入任何单一工厂** | 独立为 `MarketAggregator`，避免破坏工厂的数据域内聚性 |
| **步骤 4/5 依赖步骤 2/3 的结果** | 工厂的 `compute_rps` 内部先调 `compute_chg`，或由编排器保证顺序 |
| **PE 同步数据源不同** | `IndexFactory.sync_pe` 使用 legulegu.com，与 `sync_kline` 的 TDX 数据源隔离 |
| **`FactorEngine` 需改造支持 `target_date`** | 这是前置依赖，需在工厂化之前完成 |
| **跨域事务一致性** | 编排器需处理某步骤失败后的回滚或补偿（当前是失败即停止） |
| **任务状态管理仍需独立** | 工厂不管理任务状态，`TaskRepo` 统一负责 |

### 4.3 ❌ 不适合放入工厂的操作

1. **任务状态管理**：`task_manager` 的 create/update/complete/fail 应在编排器层
2. **同步时间窗口检查**：`_check_sync_time` 应在编排器入口，不放入工厂
3. **跨域聚合**：步骤 7 的 `precompute_base`、`generate_overview` 放入 `MarketAggregator`
4. **API 响应封装**：路由层负责，工厂只返回 `SyncResult`/`ComputeResult` 数据类

---

## 5. 实施路线图

### 5.1 前置依赖

1. **阶段 1 完成**：`app/data/` 模块归位（否则工厂无法 import `DataManager`）
2. **仓库模式就绪**：`app/server/repositories/` 提供 `IndexRepo`/`StockRepo`/`SectorRepo`
3. **`FactorEngine` 改造**：`calculate_rps` 增加 `target_date` 参数

### 5.2 实施步骤

#### 步骤 1：定义数据类与接口契约
- `app/server/factories/base.py`：`SyncResult`、`ComputeResult`、`PipelineResult` 数据类
- `app/server/factories/protocols.py`：工厂接口 Protocol（可选，用于类型检查）

#### 步骤 2：实现三大工厂
- `app/server/factories/index_factory.py`
- `app/server/factories/stock_factory.py`
- `app/server/factories/sector_factory.py`
- 从现有 `FactorService._run_sync_indices`、`sync._run_sync_task`、`_run_sync_pe` 中抽取逻辑

#### 步骤 3：实现市场聚合器
- `app/server/factories/market_aggregator.py`
- 从现有 `_run_precompute_base_for_date`、`generate_market_overview`、`analyze_new_high_blocks` 中抽取

#### 步骤 4：实现编排器
- `app/server/orchestrators/one_click_orchestrator.py`
- `app/server/orchestrators/daily_recalc_orchestrator.py`
- `app/server/orchestrators/monthly_recalc_orchestrator.py`

#### 步骤 5：改造路由层
- `one_click_update.py`：只调用 `OneClickUpdateOrchestrator.execute()`
- `sync.py`：只调用 `StockFactory.sync_daily()`
- `factors.py`：只调用 `IndexFactory`/`SectorFactory` 方法
- 删除路由层中的 `_run_*` 函数

#### 步骤 6：验证与回归
- 一键更新流程回归测试
- 单日重算流程回归测试
- 月度重算流程回归测试

### 5.3 目标目录结构

```
app/server/
├── api/                         # 路由层（只调用 orchestrator/factory）
│   ├── one_click_update.py
│   ├── sync.py
│   ├── factors.py
│   └── ...
├── orchestrators/               # 编排层（组合工厂原子能力）
│   ├── __init__.py
│   ├── one_click_orchestrator.py
│   ├── daily_recalc_orchestrator.py
│   └── monthly_recalc_orchestrator.py
├── factories/                   # 工厂层（按数据域内聚）
│   ├── __init__.py
│   ├── base.py                  # SyncResult/ComputeResult/PipelineResult
│   ├── index_factory.py         # 指数工厂
│   ├── stock_factory.py         # 个股工厂
│   ├── sector_factory.py        # 板块工厂
│   └── market_aggregator.py     # 市场聚合器（跨域）
├── repositories/                # 数据访问层
│   ├── index_repo.py
│   ├── stock_repo.py
│   ├── sector_repo.py
│   ├── base_data_repo.py
│   └── task_repo.py
├── services/                    # 其他业务服务（保留 factor_service 过渡期）
│   └── factor_service.py
└── config.py                    # 配置中心
```

---

## 6. 结论与建议

### 6.1 ✅ 设计可行性结论

**三大工厂设计是合理的，且有利于项目优化**，但必须配合以下两个补充设计：

1. **MarketAggregator（市场聚合器）**：步骤 7 是跨域操作，不能放入任何单一工厂，必须独立
2. **Orchestrator（编排器）**：三种业务流程（一键更新/单日重算/月度重算）的编排逻辑必须独立于工厂

最终架构是 **三大工厂 + 一个聚合器 + 三个编排器**，不是单纯三大工厂。

### 6.2 📌 关键设计决策摘要

| 决策点 | 选择 | 理由 |
| :--- | :--- | :--- |
| 步骤 7 归属 | 独立 `MarketAggregator` | 跨域聚合不能破坏工厂内聚性 |
| 任务状态管理 | 编排器层 + `TaskRepo` | 工厂只管业务，不管任务状态 |
| 按日期执行 | 所有工厂方法支持 `target_date` | 统一一键更新与历史重算 |
| 进度回调 | 编排器注入 `progress_callback` | 工厂不关心任务上下文 |
| PE 同步 | 放入 `IndexFactory` | 数据域是指数，数据源隔离 |
| `compute_rps` 依赖 | 工厂内部保证 `compute_chg` 先执行 | 或由编排器显式调用 |

### 6.3 ⚠️ 不建议的过度设计

1. **不要为工厂引入继承体系**（`BaseFactory` + 子类）：三个工厂的数据源、计算逻辑差异大，继承反而增加耦合
2. **不要为编排器引入 DSL 或配置化**：当前三种流程固定，硬编码更清晰
3. **不要把 `_check_sync_time` 放入工厂**：这是业务规则，应在编排器入口

### 6.4 推荐实施顺序

建议在优化计划（`2026-07-21-optimization-plan.md`）的**阶段 2** 中实施本设计，作为"路由层业务逻辑下沉"的核心交付物。前置依赖为阶段 1 的 `app/data/` 模块归位与仓库模式建立。

---

## 7. 待用户确认事项

1. **是否认可"三大工厂 + 聚合器 + 编排器"的完整架构**（而非单纯三大工厂）？
2. **`FactorEngine.calculate_rps` 改造支持 `target_date`** 是否可作为前置任务？
3. **过渡期是否保留 `FactorService`**？建议保留 1-2 个版本，新代码用工厂，旧代码逐步迁移
4. **编排器是否需要支持并行执行**？例如一键更新的步骤 1-3（同步指数/个股/板块）理论上可并行

---

<!-- Context-Archived: 2026-07-21 三大工厂+聚合器+编排器架构设计文档，评估将7个步骤按数据域内聚的可行性 -->
