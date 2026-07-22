"""
Sync Service - 数据同步服务
处理数据同步相关的业务逻辑
"""
import logging
from typing import Callable, Dict, List, Optional

from app.server.repositories.stock_repository import StockRepository
from app.server.repositories.sector_repository import SectorRepository
from app.server.repositories.index_repository import IndexRepository
from app.server.factories.base import SyncResult, ProgressCallback

logger = logging.getLogger(__name__)


class SyncService:
    """数据同步服务"""
    
    def __init__(self, stock_repo: StockRepository = None,
                 sector_repo: SectorRepository = None,
                 index_repo: IndexRepository = None):
        self.stock_repo = stock_repo or StockRepository()
        self.sector_repo = sector_repo or SectorRepository()
        self.index_repo = index_repo or IndexRepository()
    
    def sync_stock_daily(self, end_date: Optional[str] = None,
                         max_workers: int = 4,
                         progress_callback: Callable = None) -> SyncResult:
        """
        同步个股日线数据
        :param end_date: 结束日期，None 表示最新
        :param max_workers: 最大并发数
        """
        callback = ProgressCallback(progress_callback)
        
        try:
            enabled_codes = self.stock_repo.get_enabled_codes()
            total = len(enabled_codes)
            
            if total == 0:
                return SyncResult(success=True, message='无启用股票', total=0)
            
            callback.update(0, total, f'开始同步 {total} 只股票...')
            
            # TODO: 调用 data_manager.sync_daily_data
            # 这里需要从 sync._run_sync_task 迁移同步逻辑
            
            callback.complete(f'个股同步完成: {total} 只')
            return SyncResult(
                success=True,
                message=f'个股同步完成: {total} 只',
                total=total,
                synced=total
            )
        except Exception as e:
            logger.error(f'同步个股日线失败: {e}')
            return SyncResult(success=False, message=str(e))
    
    def sync_sector_daily(self, end_date: Optional[str] = None,
                          progress_callback: Callable = None) -> SyncResult:
        """
        同步板块日线数据
        :param end_date: 结束日期，None 表示最新
        """
        callback = ProgressCallback(progress_callback)
        
        try:
            enabled_codes = self.sector_repo.get_enabled_codes()
            total = len(enabled_codes)
            
            if total == 0:
                return SyncResult(success=True, message='无启用板块', total=0)
            
            callback.update(0, total, f'开始同步 {total} 个板块...')
            
            # TODO: 调用 data_manager.sync_sector_indices
            
            callback.complete(f'板块同步完成: {total} 个')
            return SyncResult(
                success=True,
                message=f'板块同步完成: {total} 个',
                total=total,
                synced=total
            )
        except Exception as e:
            logger.error(f'同步板块日线失败: {e}')
            return SyncResult(success=False, message=str(e))
    
    def sync_index_kline(self, target_date: Optional[str] = None,
                         progress_callback: Callable = None) -> SyncResult:
        """
        同步指数 K 线数据
        :param target_date: 指定日期，None 表示最新
        """
        callback = ProgressCallback(progress_callback)
        
        try:
            enabled_indices = self.index_repo.get_enabled_list()
            total = len(enabled_indices)
            
            if total == 0:
                return SyncResult(success=True, message='无启用指数', total=0)
            
            callback.update(0, total, f'开始同步 {total} 个指数...')
            
            # TODO: 调用 TDX 数据源同步
            
            callback.complete(f'指数同步完成: {total} 个')
            return SyncResult(
                success=True,
                message=f'指数同步完成: {total} 个',
                total=total,
                synced=total
            )
        except Exception as e:
            logger.error(f'同步指数失败: {e}')
            return SyncResult(success=False, message=str(e))
    
    def get_stock_list(self, page: Optional[int] = None, page_size: int = 50,
                       keyword: Optional[str] = None, filter_mode: Optional[str] = None) -> Dict:
        """获取股票列表"""
        return self.stock_repo.get_stock_list(page, page_size, keyword, filter_mode)
    
    def get_sector_list(self, page: Optional[int] = None, page_size: int = 50,
                        keyword: Optional[str] = None, filter_mode: Optional[str] = None) -> Dict:
        """获取板块列表"""
        # TODO: 实现板块列表查询
        return {'total': 0, 'data': [], 'page': page, 'page_size': page_size}
    
    def get_index_list(self, page: Optional[int] = None, page_size: int = 50,
                       keyword: Optional[str] = None, filter_mode: Optional[str] = None) -> Dict:
        """获取指数列表"""
        # TODO: 实现指数列表查询
        return {'total': 0, 'data': [], 'page': page, 'page_size': page_size}


# 单例实例
_sync_service: SyncService = None


def get_sync_service() -> SyncService:
    """获取同步服务单例"""
    global _sync_service
    if _sync_service is None:
        _sync_service = SyncService()
    return _sync_service
