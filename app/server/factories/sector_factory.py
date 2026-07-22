"""
Sector Factory - 板块工厂
管理板块数据的同步与衍生计算
"""
import logging
from typing import Callable, Dict, List, Optional

from app.server.factories.base import SyncResult, ComputeResult, PipelineResult, ProgressCallback
from app.server.repositories.sector_repository import SectorRepository

logger = logging.getLogger(__name__)


class SectorFactory:
    """板块工厂 — 管理板块数据的同步与衍生计算"""
    
    def __init__(self, sector_repo: SectorRepository = None):
        self.repo = sector_repo or SectorRepository()
    
    def sync_daily(self, target_date: Optional[str] = None,
                   task_id: str = None,
                   progress_callback: Callable = None) -> SyncResult:
        """
        同步板块日线数据
        :param target_date: 指定日期 YYYYMMDD，None 同步到最新
        :param task_id: 任务ID，用于更新进度
        """
        callback = ProgressCallback(progress_callback)
        
        try:
            enabled_sectors = self.repo.get_enabled_codes()
            total = len(enabled_sectors)
            
            if total == 0:
                return SyncResult(success=True, message='无启用板块', total=0)
            
            callback.update(0, total, '开始同步板块日线...')
            
            # 调用 data_manager 的板块同步逻辑
            from app.data.manager import get_data_manager
            dm = get_data_manager()
            
            result = dm.sync_sector_indices(
                task_id=task_id,
                enabled_codes=enabled_sectors,
                is_external=True
            )
            
            # 计算冗余字段
            dm.calculate_all_derived_fields(target='sector')
            
            callback.complete(f'板块日线同步完成: {total} 个')
            return SyncResult(
                success=True,
                message=f'板块日线同步完成: {total} 个',
                total=total,
                synced=total
            )
        except Exception as e:
            logger.error(f'同步板块日线失败: {e}')
            return SyncResult(success=False, message=str(e))
    
    def compute_rps(self, target_date: Optional[str] = None,
                    progress_callback: Callable = None) -> ComputeResult:
        """
        计算板块 RPS
        :param target_date: 指定日期重算，None 从最新日期回溯
        """
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 1, '计算板块RPS...')
            
            # 调用 factor_engine 的 RPS 计算
            from app.engine.factor_engine import FactorEngine
            engine = FactorEngine()
            result = engine.calculate_rps(data_type='sector', max_dates=None)
            
            callback.complete(f'板块RPS计算完成: {result}')
            return ComputeResult(success=True, message=f'板块RPS计算完成: {result}')
        except Exception as e:
            logger.error(f'计算板块RPS失败: {e}')
            return ComputeResult(success=False, message=str(e))
    
    def compute_chg(self, target_date: Optional[str] = None,
                    progress_callback: Callable = None) -> ComputeResult:
        """计算板块区间涨幅"""
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 1, '计算板块涨幅...')
            
            # 调用 data_manager 的涨幅计算
            from app.data.manager import get_data_manager
            dm = get_data_manager()
            dm.calculate_chg_fields(target='sector', trade_date=target_date)
            
            callback.complete('板块涨幅计算完成')
            return ComputeResult(success=True, message='板块涨幅计算完成')
        except Exception as e:
            logger.error(f'计算板块涨幅失败: {e}')
            return ComputeResult(success=False, message=str(e))
    
    def compute_ma(self, target_date: Optional[str] = None,
                   progress_callback: Callable = None) -> ComputeResult:
        """计算板块均线"""
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 1, '计算板块均线...')
            
            # 调用 data_manager 的均线计算
            from app.data.manager import get_data_manager
            dm = get_data_manager()
            dm.calculate_all_derived_fields(target='sector', trade_date=target_date)
            
            callback.complete('板块均线计算完成')
            return ComputeResult(success=True, message='板块均线计算完成')
        except Exception as e:
            logger.error(f'计算板块均线失败: {e}')
            return ComputeResult(success=False, message=str(e))
    
    def run_full_pipeline(self, target_date: Optional[str] = None,
                          progress_callback: Callable = None) -> PipelineResult:
        """
        执行板块全流程：sync_daily → compute_chg → compute_ma → compute_rps
        """
        result = PipelineResult()
        
        result.add_step('sync_daily', self.sync_daily(target_date, progress_callback))
        result.add_step('compute_chg', self.compute_chg(target_date, progress_callback))
        result.add_step('compute_ma', self.compute_ma(target_date, progress_callback))
        result.add_step('compute_rps', self.compute_rps(target_date, progress_callback))
        
        return result
