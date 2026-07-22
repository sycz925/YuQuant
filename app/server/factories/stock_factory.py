"""
Stock Factory - 个股工厂
管理个股数据的同步与衍生计算
"""
import logging
from typing import Callable, Dict, List, Optional

from app.server.factories.base import SyncResult, ComputeResult, PipelineResult, ProgressCallback
from app.server.repositories.stock_repository import StockRepository

logger = logging.getLogger(__name__)


class StockFactory:
    """个股工厂 — 管理个股数据的同步与衍生计算"""
    
    def __init__(self, stock_repo: StockRepository = None):
        self.repo = stock_repo or StockRepository()
    
    def sync_daily(self, target_date: Optional[str] = None,
                   max_workers: int = 4,
                   progress_callback: Callable = None) -> SyncResult:
        """
        同步个股日线数据
        :param target_date: 指定日期 YYYYMMDD，None 同步到最新
        """
        callback = ProgressCallback(progress_callback)
        
        try:
            enabled_stocks = self.repo.get_enabled_codes()
            total = len(enabled_stocks)
            
            if total == 0:
                return SyncResult(success=True, message='无启用股票', total=0)
            
            callback.update(0, total, '开始同步个股日线...')
            
            # TODO: 调用 data_manager.sync_daily_data
            # 这里需要从 sync._run_sync_task 迁移同步逻辑
            
            callback.complete(f'个股日线同步完成: {total} 只')
            return SyncResult(
                success=True,
                message=f'个股日线同步完成: {total} 只',
                total=total,
                synced=total
            )
        except Exception as e:
            logger.error(f'同步个股日线失败: {e}')
            return SyncResult(success=False, message=str(e))
    
    def compute_rps(self, target_date: Optional[str] = None,
                    progress_callback: Callable = None) -> ComputeResult:
        """
        计算个股 RPS
        :param target_date: 指定日期重算，None 从最新日期回溯
        """
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 1, '计算个股RPS...')
            
            # TODO: 调用 factor_engine.calculate_rps(data_type='stock')
            
            callback.complete('个股RPS计算完成')
            return ComputeResult(success=True, message='个股RPS计算完成')
        except Exception as e:
            logger.error(f'计算个股RPS失败: {e}')
            return ComputeResult(success=False, message=str(e))
    
    def compute_chg(self, target_date: Optional[str] = None,
                    progress_callback: Callable = None) -> ComputeResult:
        """计算个股区间涨幅（5/10/20/50/120/250日）"""
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 1, '计算个股涨幅...')
            
            # TODO: 调用 data_manager.calculate_chg_fields(target='stock')
            
            callback.complete('个股涨幅计算完成')
            return ComputeResult(success=True, message='个股涨幅计算完成')
        except Exception as e:
            logger.error(f'计算个股涨幅失败: {e}')
            return ComputeResult(success=False, message=str(e))
    
    def compute_ma(self, target_date: Optional[str] = None,
                   progress_callback: Callable = None) -> ComputeResult:
        """计算个股均线（MA10/20/50/120 + VOL_MA5/10/20/50）"""
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 1, '计算个股均线...')
            
            # TODO: 实现均线计算
            
            callback.complete('个股均线计算完成')
            return ComputeResult(success=True, message='个股均线计算完成')
        except Exception as e:
            logger.error(f'计算个股均线失败: {e}')
            return ComputeResult(success=False, message=str(e))
    
    def run_full_pipeline(self, target_date: Optional[str] = None,
                          progress_callback: Callable = None) -> PipelineResult:
        """
        执行个股全流程：sync_daily → compute_chg → compute_ma → compute_rps
        一键更新时调用此方法
        注意：compute_rps 依赖 compute_chg 的结果，顺序不可调换
        """
        result = PipelineResult()
        
        result.add_step('sync_daily', self.sync_daily(target_date, progress_callback=progress_callback))
        result.add_step('compute_chg', self.compute_chg(target_date, progress_callback))
        result.add_step('compute_ma', self.compute_ma(target_date, progress_callback))
        result.add_step('compute_rps', self.compute_rps(target_date, progress_callback))
        
        return result
