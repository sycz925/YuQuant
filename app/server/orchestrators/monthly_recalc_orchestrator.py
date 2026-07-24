"""
Monthly Recalc Orchestrator - 月度重算编排器
流程：遍历月份内每个交易日 → 对每个交易日执行 DailyRecalc
"""
import logging
from typing import List, Dict, Optional

from app.server.orchestrators.base import BaseOrchestrator
from app.server.orchestrators.daily_recalc_orchestrator import DailyRecalcOrchestrator

logger = logging.getLogger(__name__)


class MonthlyRecalcOrchestrator(BaseOrchestrator):
    """
    月度重算编排器
    流程：遍历月份内每个交易日 → 对每个交易日执行 DailyRecalc
    """

    def __init__(self, daily_recalc: DailyRecalcOrchestrator = None, **kwargs):
        super().__init__(**kwargs)
        self.daily_recalc = daily_recalc or DailyRecalcOrchestrator()

    def get_steps(self) -> List[Dict[str, str]]:
        # 月度重算的步骤在执行时动态确定
        return [{'key': 'monthly_recalc', 'name': '月度重算'}]

    def execute(self, year: int, month: int) -> str:
        """执行月度重算"""
        # 获取月份内的交易日
        trading_days = self._get_trading_days(year, month)

        if not trading_days:
            logger.warning(f'{year}-{month:02d} 无交易日')
            return ''

        # 创建任务
        steps = [{'key': f'recalc_{d}', 'name': f'重算{d}'} for d in trading_days]
        task_id = self.task_repo.create_task(steps)

        import threading
        thread = threading.Thread(
            target=self._run_monthly,
            args=(task_id, trading_days),
            daemon=True
        )
        thread.start()

        return task_id

    def _run_monthly(self, task_id: str, trading_days: List[str]) -> None:
        """后台执行月度重算"""
        from app.data.task_manager import get_task_manager
        from app.server.factories import get_stock_factory, get_sector_factory, get_market_aggregator
        tm = get_task_manager()

        for i, date in enumerate(trading_days):
            # 检查任务是否已取消
            if tm.is_cancelled(task_id):
                logger.info(f'任务 {task_id} 已取消，停止执行')
                return

            logger.info(f"[月度重算] 开始重算 {date} ({i+1}/{len(trading_days)})")

            try:
                # 1. 计算个股涨幅和RPS
                self.task_repo.update_step_progress(task_id, i, status='running', completed_count=0, message='计算个股RPS...')
                stock_factory = get_stock_factory()
                stock_factory.compute_chg(date)
                stock_factory.compute_rps(date)
                self.task_repo.update_step_progress(task_id, i, completed_count=1, message='计算个股RPS完成')
                # 工厂方法会覆盖 current_stock_name，这里重新设置
                self.task_repo.update_task_progress(task_id, current_step=i, current_stock_name=f'重算 {date}: 计算板块RPS...')

                # 2. 计算板块涨幅和RPS
                self.task_repo.update_step_progress(task_id, i, completed_count=1, message='计算板块RPS...')
                sector_factory = get_sector_factory()
                sector_factory.compute_chg(date)
                sector_factory.compute_rps(date)
                self.task_repo.update_step_progress(task_id, i, completed_count=1, message='计算板块RPS完成')
                # 工厂方法会覆盖 current_stock_name，这里重新设置
                self.task_repo.update_task_progress(task_id, current_stock_name=f'重算 {date}: 预计算基础数据...')

                # 3. 预计算基础数据
                self.task_repo.update_step_progress(task_id, i, completed_count=1, message='预计算基础数据...')
                aggregator = get_market_aggregator()
                aggregator.precompute_base_data(date, task_id=task_id)

                # 更新步骤完成状态
                self.task_repo.update_step_progress(
                    task_id, i,
                    status='completed',
                    completed_count=1,
                    message=f'{date} 重算完成'
                )
                # 更新顶层进度
                self.task_repo.update_task_progress(task_id, current_stock_name=f'{date} 重算完成 ({i+1}/{len(trading_days)})')
                logger.info(f"[月度重算] {date} 重算完成")
            except Exception as e:
                logger.error(f'{date} 重算失败: {e}', exc_info=True)
                self.task_repo.update_step_progress(
                    task_id, i,
                    status='failed',
                    message=str(e)[:200]
                )
                self.task_repo.fail_task(task_id, f'{date} 重算失败: {str(e)[:200]}')
                return

        self.task_repo.complete_task(task_id, '月度重算完成')
        logger.info(f"[月度重算] 月度重算完成，共处理 {len(trading_days)} 个交易日")

    def _get_trading_days(self, year: int, month: int) -> List[str]:
        """获取月份内的交易日"""
        from app.data.db import get_db

        db = get_db()

        # 获取月份内所有日期
        month_prefix = f'{year}-{month:02d}'

        # 从 stock_daily 获取实际交易日
        dates = sorted(db['stock_daily'].distinct('trade_date'))
        trading_days = [d for d in dates if d.startswith(month_prefix)]

        return trading_days

    def execute_step(self, step_key: str, task_id: str, target_date: Optional[str]) -> None:
        """此编排器不使用标准步骤执行"""
        pass
