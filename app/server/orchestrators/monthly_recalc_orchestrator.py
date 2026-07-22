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
        for i, date in enumerate(trading_days):
            self.task_repo.update_step_progress(task_id, i, status='running')
            
            try:
                self.daily_recalc.execute(date)
                self.task_repo.update_step_progress(
                    task_id, i,
                    status='completed',
                    message=f'{date} 重算完成'
                )
            except Exception as e:
                logger.error(f'{date} 重算失败: {e}')
                self.task_repo.update_step_progress(
                    task_id, i,
                    status='failed',
                    message=str(e)[:200]
                )
                self.task_repo.fail_task(task_id, f'{date} 重算失败: {str(e)[:200]}')
                return
        
        self.task_repo.complete_task(task_id, '月度重算完成')
    
    def _get_trading_days(self, year: int, month: int) -> List[str]:
        """获取月份内的交易日"""
        from app.data.db import get_db
        from app.data.holidays import is_workday
        
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
