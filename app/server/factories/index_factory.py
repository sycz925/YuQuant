"""
Index Factory - 指数工厂
管理指数数据的同步与衍生计算
"""
import logging
from datetime import datetime
from typing import Callable, Dict, List, Optional

from app.server.factories.base import SyncResult, ComputeResult, PipelineResult, ProgressCallback
from app.server.repositories.index_repository import IndexRepository

logger = logging.getLogger(__name__)


class IndexFactory:
    """指数工厂 — 管理指数数据的同步与衍生计算"""
    
    def __init__(self, index_repo: IndexRepository = None):
        self.repo = index_repo or IndexRepository()
    
    def sync_kline(self, target_date: Optional[str] = None,
                   task_id: str = None,
                   progress_callback: Callable = None) -> SyncResult:
        """
        同步指数 K 线数据（TDX 数据源）
        :param target_date: 指定日期 YYYYMMDD，None 同步到最新
        :param task_id: 任务ID，用于更新进度
        """
        callback = ProgressCallback(progress_callback)
        
        try:
            enabled_indices = self.repo.get_enabled_list()
            total = len(enabled_indices)
            
            if total == 0:
                return SyncResult(success=True, message='无启用指数', total=0)
            
            callback.update(0, total, '开始同步指数K线...')
            
            # 调用 factor_service 的同步逻辑
            from app.server.services.factor_service import get_factor_service
            fs = get_factor_service()
            
            # 获取同步配置
            index_cfg = fs._get_sync_index_config()
            enabled_codes = set(idx['code'] for idx in enabled_indices)
            sync_cfg = [c for c in index_cfg if c.get('code') in enabled_codes]
            
            # 如果没有传入 task_id，生成临时的
            if not task_id:
                import uuid
                task_id = str(uuid.uuid4())
            
            # 调用同步方法
            end_date = target_date or datetime.now().strftime('%Y%m%d')
            start_date = '19900101'  # 从最早开始
            
            fs._run_sync_indices(task_id, sync_cfg, start_date, end_date, is_external=True)
            
            callback.complete(f'指数K线同步完成: {total} 个')
            return SyncResult(
                success=True,
                message=f'指数K线同步完成: {total} 个',
                total=total,
                synced=total
            )
        except Exception as e:
            logger.error(f'同步指数K线失败: {e}')
            return SyncResult(success=False, message=str(e))
    
    def sync_pe(self, target_date: Optional[str] = None,
                progress_callback: Callable = None) -> SyncResult:
        """
        同步指数 PE（legulegu.com 数据源）
        :param target_date: 指定日期，None 同步最新
        """
        callback = ProgressCallback(progress_callback)
        
        try:
            from app.server.config import get_settings
            settings = get_settings()
            
            if not settings.LEGULEGU_TOKEN:
                return SyncResult(success=True, message='未配置PE Token，跳过', skipped=True)
            
            callback.update(0, 1, '开始同步PE数据...')
            
            # 调用 factor_service 的 PE 同步逻辑
            from app.server.services.factor_service import get_factor_service
            fs = get_factor_service()
            
            import uuid
            temp_task_id = str(uuid.uuid4())
            fs._run_sync_pe(temp_task_id, settings.LEGULEGU_TOKEN, is_external=True)
            
            callback.complete('PE同步完成')
            return SyncResult(success=True, message='PE同步完成')
        except Exception as e:
            logger.error(f'同步PE失败: {e}')
            return SyncResult(success=False, message=str(e))
    
    def compute_rps(self, target_date: Optional[str] = None,
                    progress_callback: Callable = None) -> ComputeResult:
        """计算指数 RPS（当前系统指数无 RPS，此方法预留）"""
        return ComputeResult(skipped=True, skip_reason='指数不计算 RPS')
    
    def compute_chg(self, target_date: Optional[str] = None,
                    progress_callback: Callable = None) -> ComputeResult:
        """计算指数区间涨幅"""
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 1, '计算指数涨幅...')
            
            # 调用 data_manager 的涨幅计算
            from app.data.manager import get_data_manager
            dm = get_data_manager()
            dm.calculate_chg_fields(target='index', trade_date=target_date)
            
            callback.complete('指数涨幅计算完成')
            return ComputeResult(success=True, message='指数涨幅计算完成')
        except Exception as e:
            logger.error(f'计算指数涨幅失败: {e}')
            return ComputeResult(success=False, message=str(e))
    
    def compute_ma(self, target_date: Optional[str] = None,
                   progress_callback: Callable = None) -> ComputeResult:
        """计算指数均线"""
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 1, '计算指数均线...')
            
            # 指数暂不计算均线
            callback.complete('指数均线计算完成（跳过）')
            return ComputeResult(success=True, message='指数均线计算完成（跳过）')
        except Exception as e:
            logger.error(f'计算指数均线失败: {e}')
            return ComputeResult(success=False, message=str(e))
    
    def run_full_pipeline(self, target_date: Optional[str] = None,
                          progress_callback: Callable = None) -> PipelineResult:
        """
        执行指数全流程：sync_kline → sync_pe → compute_chg → compute_ma
        一键更新时调用此方法
        """
        result = PipelineResult()
        
        result.add_step('sync_kline', self.sync_kline(target_date, progress_callback))
        result.add_step('sync_pe', self.sync_pe(target_date, progress_callback))
        result.add_step('compute_chg', self.compute_chg(target_date, progress_callback))
        result.add_step('compute_ma', self.compute_ma(target_date, progress_callback))
        
        return result
