"""
Calendar Service - 日历复盘服务
处理日历快照、周/月总结相关的业务逻辑
"""
import logging
from typing import Callable, Dict, List, Optional

from app.server.repositories.market_repository import MarketRepository
from app.server.repositories.stock_repository import StockRepository
from app.server.repositories.index_repository import IndexRepository
from app.server.repositories.sector_repository import SectorRepository
from app.server.repositories.summary_repository import WeeklySummaryRepository, MonthlySummaryRepository
from app.server.factories.base import ComputeResult, ProgressCallback

logger = logging.getLogger(__name__)


class CalendarService:
    """日历复盘服务"""
    
    def __init__(self, market_repo: MarketRepository = None,
                 stock_repo: StockRepository = None,
                 index_repo: IndexRepository = None,
                 sector_repo: SectorRepository = None,
                 weekly_summary_repo: WeeklySummaryRepository = None,
                 monthly_summary_repo: MonthlySummaryRepository = None):
        self.market_repo = market_repo or MarketRepository()
        self.stock_repo = stock_repo or StockRepository()
        self.index_repo = index_repo or IndexRepository()
        self.sector_repo = sector_repo or SectorRepository()
        self.weekly_summary_repo = weekly_summary_repo or WeeklySummaryRepository()
        self.monthly_summary_repo = monthly_summary_repo or MonthlySummaryRepository()
    
    def get_calendar_snapshot(self, trade_date: str,
                              progress_callback: Callable = None) -> Optional[Dict]:
        """
        获取日历快照
        :param trade_date: 交易日期
        """
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 50, '获取日历快照...')
            
            # TODO: 从 calendar.generate_calendar_snapshot 迁移逻辑
            
            callback.complete('日历快照获取完成')
            return {}
        except Exception as e:
            logger.error(f'获取日历快照失败: {e}')
            return None
    
    def get_daily_summary(self, year: int, month: int,
                          progress_callback: Callable = None) -> List[Dict]:
        """
        获取每日总结列表
        :param year: 年份
        :param month: 月份
        """
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 50, '获取每日总结...')
            
            # TODO: 实现每日总结查询
            
            callback.complete('每日总结获取完成')
            return []
        except Exception as e:
            logger.error(f'获取每日总结失败: {e}')
            return []
    
    def get_weekly_summary(self, year: int, month: int, week_index: int,
                           progress_callback: Callable = None) -> Optional[Dict]:
        """
        获取周总结
        :param year: 年份
        :param month: 月份
        :param week_index: 周索引
        """
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 50, '获取周总结...')
            
            # 先检查缓存
            cached = self.weekly_summary_repo.get_by_key(year, month, week_index)
            if cached:
                callback.complete('周总结获取完成（缓存）')
                return cached
            
            # TODO: 实现周总结生成逻辑
            
            callback.complete('周总结获取完成')
            return {}
        except Exception as e:
            logger.error(f'获取周总结失败: {e}')
            return None
    
    def get_monthly_summary(self, year: int, month: int,
                            progress_callback: Callable = None) -> Optional[Dict]:
        """
        获取月总结
        :param year: 年份
        :param month: 月份
        """
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 50, '获取月总结...')
            
            # 先检查缓存
            cached = self.monthly_summary_repo.get_by_key(year, month)
            if cached:
                callback.complete('月总结获取完成（缓存）')
                return cached
            
            # TODO: 实现月总结生成逻辑
            
            callback.complete('月总结获取完成')
            return {}
        except Exception as e:
            logger.error(f'获取月总结失败: {e}')
            return None
    
    def recalculate_month(self, year: int, month: int,
                          progress_callback: Callable = None) -> Optional[str]:
        """
        月度重算
        :param year: 年份
        :param month: 月份
        :return: task_id
        """
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 50, '启动月度重算...')
            
            # TODO: 从 calendar._run_monthly_recalc 迁移逻辑
            
            callback.complete('月度重算已启动')
            return None
        except Exception as e:
            logger.error(f'月度重算失败: {e}')
            return None


# 单例实例
_calendar_service: CalendarService = None


def get_calendar_service() -> CalendarService:
    """获取日历服务单例"""
    global _calendar_service
    if _calendar_service is None:
        _calendar_service = CalendarService()
    return _calendar_service
