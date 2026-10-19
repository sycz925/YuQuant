import logging
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor

from app.server.orchestrators.daily_recalc_orchestrator import DailyRecalcOrchestrator

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="monthly")


class MonthlyRecalcOrchestrator(DailyRecalcOrchestrator):
    """月度重算：对指定月份的所有交易日依次执行单日重算（个股RPS→板块RPS→预计算）。

    复用 DailyRecalcOrchestrator 的 get_steps / execute_step / run_dates，
    仅提供「按月取交易日 + 展开日期×步骤」的编排。
    """

    def execute(self, year: int, month: int) -> str:
        import uuid

        trading_days = self._get_trading_days(year, month)
        if not trading_days:
            raise ValueError(f'{year}-{month:02d} 无交易日')

        # 展开步骤：每个交易日 × (rps_stock → rps_sector → precompute)
        steps = []
        for date_str in trading_days:
            for s in self.get_steps():
                steps.append({'key': s['key'], 'name': f'{date_str} {s["name"]}', 'total_count': 1})

        task_id = str(uuid.uuid4())
        self.task_repo.create_task(task_id, steps, name='月度重算')
        _executor.submit(self._run_wrapper, task_id, trading_days)
        return task_id

    def _run(self, task_id: str, dates: Optional[List[str]] = None) -> None:
        """复用单日重算的多日循环"""
        self.run_dates(task_id, dates, complete_message=f'月度重算完成，共处理 {len(dates or [])} 个交易日')

    def _get_trading_days(self, year: int, month: int) -> List[str]:
        from app.data.db import get_db
        db = get_db()
        month_prefix = f'{year}{month:02d}'
        dates = sorted(db['stock_daily'].distinct('trade_date'))
        return [d for d in dates if d.startswith(month_prefix)]
