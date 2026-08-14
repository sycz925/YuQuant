import logging
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor

from app.server.orchestrators.base import BaseOrchestrator
from app.server.orchestrators.daily_recalc_orchestrator import DailyRecalcOrchestrator

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="monthly")


class MonthlyRecalcOrchestrator(BaseOrchestrator):
    def __init__(self, daily_recalc: DailyRecalcOrchestrator = None, **kwargs):
        super().__init__(**kwargs)
        self.daily_recalc = daily_recalc or DailyRecalcOrchestrator()

    def get_steps(self) -> List[Dict[str, str]]:
        return [
            {'key': 'rps_stock', 'name': '计算个股RPS'},
            {'key': 'rps_sector', 'name': '计算板块RPS'},
            {'key': 'precompute', 'name': '预计算基础数据'},
        ]

    def execute(self, year: int, month: int) -> str:
        import uuid
        from app.data.db import get_db
        db = get_db()

        trading_days = self._get_trading_days(year, month)
        if not trading_days:
            raise ValueError(f'{year}-{month:02d} 无交易日')

        stock_count = db['stock_basics'].count_documents({'is_disable': {'$ne': True}})
        sector_count = db['sector_basics'].count_documents({'is_disable': {'$ne': True}})

        steps = []
        for date_str in trading_days:
            steps.append({'key': 'rps_stock', 'name': f'{date_str} 计算个股RPS', 'total_count': 1})
            steps.append({'key': 'rps_sector', 'name': f'{date_str} 计算板块RPS', 'total_count': 1})
            steps.append({'key': 'precompute', 'name': f'{date_str} 预计算基础数据', 'total_count': 1})

        task_id = str(uuid.uuid4())
        self.task_repo.create_task(task_id, steps, name='月度重算')
        _executor.submit(self._run_wrapper, task_id, trading_days)
        return task_id

    def _run(self, task_id: str, dates: Optional[List[str]] = None):
        from app.data.task_manager import get_task_manager
        tm = get_task_manager()
        steps_template = self.get_steps()

        for date_idx, date_str in enumerate(dates or []):
            for step_idx, step in enumerate(steps_template):
                global_step_idx = date_idx * len(steps_template) + step_idx

                if tm.is_cancelled(task_id):
                    logger.info(f'任务 {task_id} 已取消，停止执行')
                    return

                self.task_repo.update_step_progress(task_id, global_step_idx, status='running', completed_count=0)
                self.task_repo.update_task_progress(
                    task_id,
                    current_step=global_step_idx,
                    current_stock_name=f'重算 {date_str}: {step["name"]}'
                )

                try:
                    self.daily_recalc.execute_step(step['key'], task_id, date_str, global_step_idx=global_step_idx)
                except Exception as e:
                    logger.error(f'[{self.__class__.__name__}] {date_str} {step["name"]} 失败: {e}', exc_info=True)
                    self.task_repo.update_step_progress(task_id, global_step_idx, status='failed', message=str(e)[:200])
                    self.task_repo.fail_task(task_id, f'{date_str} {step["name"]} 失败: {str(e)[:200]}')
                    return

                self.task_repo.update_step_progress(task_id, global_step_idx, status='completed')

            logger.info(f'[{self.__class__.__name__}] {date_str} 重算完成 ({date_idx+1}/{len(dates)})')

        self.task_repo.complete_task(task_id, f'月度重算完成，共处理 {len(dates)} 个交易日')

    def _get_trading_days(self, year: int, month: int) -> List[str]:
        from app.data.db import get_db
        db = get_db()
        month_prefix = f'{year}{month:02d}'
        dates = sorted(db['stock_daily'].distinct('trade_date'))
        return [d for d in dates if d.startswith(month_prefix)]

    def execute_step(self, step_key: str, task_id: str, target_date: Optional[str]) -> None:
        pass
