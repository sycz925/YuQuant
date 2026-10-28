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
            # RPS 计算后：一次加载历史，刷新均线(10~250) + 二阶段（含前复权兜底）
            from app.engine.factor_engine import FactorEngine
            logger.info(f"[DailyRecalc] 计算 {target_date} 个股均线与二阶段")
            FactorEngine().calculate_daily_factors(data_type='stock', trade_date=target_date)

        elif step_key == 'rps_sector':
            factory = get_sector_factory()
            logger.info(f"[DailyRecalc] 计算 {target_date} 板块涨幅和RPS")
            factory.compute_chg(target_date)
            factory.compute_rps(target_date)
            # RPS 计算后：刷新板块均线与二阶段
            from app.engine.factor_engine import FactorEngine
            logger.info(f"[DailyRecalc] 计算 {target_date} 板块均线与二阶段")
            FactorEngine().calculate_daily_factors(data_type='sector', trade_date=target_date)

        elif step_key == 'precompute':
            aggregator = get_market_aggregator()
            logger.info(f"[DailyRecalc] 预计算 {target_date} 基础数据")
            aggregator.precompute_base_data(target_date, task_id=task_id)

    def execute_step(self, step_key: str, task_id: str, target_date: Optional[str], global_step_idx: Optional[int] = None) -> None:
        """执行单个步骤"""
        step_idx = global_step_idx if global_step_idx is not None else next(i for i, s in enumerate(self.get_steps()) if s['key'] == step_key)

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

    def run_dates(self, task_id: str, dates: List[str], complete_message: Optional[str] = None) -> None:
        """多日重算：对每个交易日依次执行 个股RPS→板块RPS→预计算。

        供 MonthlyRecalcOrchestrator 复用（单日重算也可传单元素列表）。
        与基类 _run 的区别：本方法把 global_step_idx 传给 execute_step，
        并写 current_stock_name，以正确定位「日期 × 步骤」展开后的全局步骤。
        """
        from app.data.task_manager import get_task_manager
        tm = get_task_manager()
        steps = self.get_steps()
        dates = dates or []
        n_dates = len(dates)

        for date_idx, date_str in enumerate(dates):
            for step_idx, step in enumerate(steps):
                global_step_idx = date_idx * len(steps) + step_idx

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
                    self.execute_step(step['key'], task_id, date_str, global_step_idx=global_step_idx)
                except Exception as e:
                    logger.error(f'[{self.__class__.__name__}] {date_str} {step["name"]} 失败: {e}', exc_info=True)
                    self.task_repo.update_step_progress(task_id, global_step_idx, status='failed', message=str(e)[:200])
                    self.task_repo.fail_task(task_id, f'{date_str} {step["name"]} 失败: {str(e)[:200]}')
                    return

                self.task_repo.update_step_progress(task_id, global_step_idx, status='completed')

            logger.info(f'[{self.__class__.__name__}] {date_str} 重算完成 ({date_idx+1}/{n_dates})')

        self.task_repo.complete_task(task_id, complete_message or f'重算完成，共处理 {n_dates} 个交易日')
