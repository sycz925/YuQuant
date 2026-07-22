"""
Market Service - 市场分析服务
处理市场分析、信号计算相关的业务逻辑
"""
import logging
from typing import Callable, Dict, List, Optional

from app.server.repositories.market_repository import MarketRepository
from app.server.repositories.stock_repository import StockRepository
from app.server.repositories.index_repository import IndexRepository
from app.server.repositories.sector_repository import SectorRepository
from app.server.factories.base import ComputeResult, ProgressCallback

logger = logging.getLogger(__name__)


class MarketService:
    """市场分析服务"""
    
    def __init__(self, market_repo: MarketRepository = None,
                 stock_repo: StockRepository = None,
                 index_repo: IndexRepository = None,
                 sector_repo: SectorRepository = None):
        self.market_repo = market_repo or MarketRepository()
        self.stock_repo = stock_repo or StockRepository()
        self.index_repo = index_repo or IndexRepository()
        self.sector_repo = sector_repo or SectorRepository()
    
    def get_market_overview(self, trade_date: str = None,
                            progress_callback: Callable = None) -> Optional[Dict]:
        """
        获取市场总览
        :param trade_date: 交易日期，None 表示最新
        """
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 50, '获取市场总览...')
            
            # TODO: 从 market_review.get_market_daily 迁移逻辑
            
            callback.complete('市场总览获取完成')
            return {}
        except Exception as e:
            logger.error(f'获取市场总览失败: {e}')
            return None
    
    def calculate_market_signals(self, trade_date: str = None,
                                 progress_callback: Callable = None) -> Optional[Dict]:
        """
        计算市场信号
        :param trade_date: 交易日期，None 表示最新
        """
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 50, '计算市场信号...')
            
            # TODO: 从 market_review.calc_market_signals 迁移逻辑
            
            callback.complete('市场信号计算完成')
            return {}
        except Exception as e:
            logger.error(f'计算市场信号失败: {e}')
            return None
    
    def analyze_new_high_blocks(self, trade_date: str = None,
                                progress_callback: Callable = None) -> Optional[Dict]:
        """
        分析新高板块
        :param trade_date: 交易日期，None 表示最新
        """
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 50, '分析新高板块...')
            
            # TODO: 从 market_review.analyze_new_high_blocks 迁移逻辑
            
            callback.complete('新高板块分析完成')
            return {}
        except Exception as e:
            logger.error(f'分析新高板块失败: {e}')
            return None
    
    def analyze_active_sectors(self, trade_date: str = None,
                               progress_callback: Callable = None) -> Optional[Dict]:
        """
        分析活跃板块
        :param trade_date: 交易日期，None 表示最新
        """
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 50, '分析活跃板块...')
            
            # TODO: 从 market_review.analyze_active_sectors 迁移逻辑
            
            callback.complete('活跃板块分析完成')
            return {}
        except Exception as e:
            logger.error(f'分析活跃板块失败: {e}')
            return None
    
    def get_base_data(self, start_date: str = None, end_date: str = None,
                      progress_callback: Callable = None) -> List[Dict]:
        """
        获取基础数据
        :param start_date: 开始日期
        :param end_date: 结束日期
        """
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 50, '获取基础数据...')
            
            if start_date and end_date:
                data = self.market_repo.get_base_data_range(start_date, end_date)
            else:
                # 获取最近30天数据
                from datetime import datetime, timedelta
                today = datetime.now().strftime('%Y%m%d')
                month_ago = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')
                data = self.market_repo.get_base_data_range(month_ago, today)
            
            callback.complete('基础数据获取完成')
            return data
        except Exception as e:
            logger.error(f'获取基础数据失败: {e}')
            return []
    
    def get_sector_detail(self, sector_code: str,
                          progress_callback: Callable = None) -> Optional[Dict]:
        """
        获取板块详情
        :param sector_code: 板块代码
        """
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 50, '获取板块详情...')
            
            # TODO: 实现板块详情查询
            
            callback.complete('板块详情获取完成')
            return {}
        except Exception as e:
            logger.error(f'获取板块详情失败: {e}')
            return None


# 单例实例
_market_service: MarketService = None


def get_market_service() -> MarketService:
    """获取市场服务单例"""
    global _market_service
    if _market_service is None:
        _market_service = MarketService()
    return _market_service
