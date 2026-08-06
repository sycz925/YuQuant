"""
Daily Recalc Orchestrator - 单日重算编排器
流程：个股RPS → 板块RPS → 预计算基础数据
"""
import logging
from typing import List, Dict, Optional

from app.server.orchestrators.base import BaseOrchestrator

logger = logging.getLogger(__name__)


class DailyRecalcOrchestrator(BaseOrchestrator):
    """
    单日重算编排器
    流程：个股RPS → 板块RPS → 预计算基础数据
    用于补算指定历史日期的数据
    """

    name = '单日重算'

    def get_steps(self) -> List[Dict[str, str]]:
        return [
            {'key': 'rps_stock', 'name': '计算个股RPS'},
            {'key': 'rps_sector', 'name': '计算板块RPS'},
            {'key': 'precompute', 'name': '预计算基础数据'},
        ]

    def execute(self, target_date: str) -> str:
        """单日重算必须指定日期"""
        if not target_date:
            raise ValueError('单日重算必须指定 target_date')
        return super().execute(target_date)

    @staticmethod
    def compute_for_step(step_key: str, target_date: str, task_id: str = None) -> None:
        """执行单步骤的纯计算（不含 step 进度跟踪），供本类和 OneClickUpdateOrchestrator 共享"""
        from app.server.factories import get_stock_factory, get_sector_factory, get_market_aggregator

        if step_key == 'rps_stock':
            factory = get_stock_factory()
            logger.info(f"[DailyRecalc] 计算 {target_date} 个股涨幅和RPS")
            factory.compute_chg(target_date)
            factory.compute_rps(target_date)

        elif step_key == 'rps_sector':
            factory = get_sector_factory()
            logger.info(f"[DailyRecalc] 计算 {target_date} 板块涨幅和RPS")
            factory.compute_chg(target_date)
            factory.compute_rps(target_date)

        elif step_key == 'precompute':
            aggregator = get_market_aggregator()
            logger.info(f"[DailyRecalc] 预计算 {target_date} 基础数据")
            aggregator.precompute_base_data(target_date, task_id=task_id)

    def execute_step(self, step_key: str, task_id: str, target_date: Optional[str]) -> None:
        """执行单个步骤"""
        step_idx = next(i for i, s in enumerate(self.get_steps()) if s['key'] == step_key)

        if step_key == 'rps_stock':
            self.task_repo.update_step_progress(task_id, step_idx, completed_count=0, message='计算个股涨幅...')
            self.compute_for_step(step_key, target_date)
            self.task_repo.update_step_progress(task_id, step_idx, completed_count=1, message='个股RPS完成')

        elif step_key == 'rps_sector':
            self.task_repo.update_step_progress(task_id, step_idx, completed_count=0, message='计算板块涨幅...')
            self.compute_for_step(step_key, target_date)
            self.task_repo.update_step_progress(task_id, step_idx, completed_count=1, message='板块RPS完成')

        elif step_key == 'precompute':
            self.task_repo.update_step_progress(task_id, step_idx, completed_count=0, message='预计算基础数据...')
            self.compute_for_step(step_key, target_date, task_id=task_id)
            self.task_repo.update_step_progress(task_id, step_idx, completed_count=1, message='预计算完成')
