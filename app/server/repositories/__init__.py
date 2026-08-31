"""
Repositories - 数据访问层
封装 MongoDB 查询，路由层不再直接调用 get_db()
"""
from app.server.repositories.base import BaseRepository
from app.server.repositories.stock_repository import StockRepository
from app.server.repositories.index_repository import IndexRepository
from app.server.repositories.sector_repository import SectorRepository
from app.server.repositories.market_repository import MarketRepository
from app.server.repositories.task_repository import TaskRepository
from app.server.repositories.summary_repository import WeeklySummaryRepository, MonthlySummaryRepository
from app.server.repositories.watchlist_repository import WatchlistRepository
from app.server.repositories.search_repository import SearchRepository
from app.server.repositories.etf_repository import EtfRepository
from app.server.repositories.market_analysis_repository import MarketAnalysisRepository
from app.server.repositories.system_config_repository import SystemConfigRepository
from app.server.repositories.market_review_repository import MarketReviewRepository
from app.server.repositories.calendar_repository import CalendarRepository
from app.server.repositories.restricted_release_repository import RestrictedReleaseRepository

# 单例实例
_stock_repo: StockRepository = None
_index_repo: IndexRepository = None
_sector_repo: SectorRepository = None
_market_repo: MarketRepository = None
_task_repo: TaskRepository = None
_weekly_summary_repo: WeeklySummaryRepository = None
_monthly_summary_repo: MonthlySummaryRepository = None
_watchlist_repo: WatchlistRepository = None
_search_repo: SearchRepository = None
_etf_repo: EtfRepository = None
_market_analysis_repo: MarketAnalysisRepository = None
_system_config_repo: SystemConfigRepository = None
_market_review_repo: MarketReviewRepository = None
_calendar_repo: CalendarRepository = None
_restricted_release_repo: RestrictedReleaseRepository = None


def get_stock_repo() -> StockRepository:
    """获取股票仓库单例"""
    global _stock_repo
    if _stock_repo is None:
        _stock_repo = StockRepository()
    return _stock_repo


def get_index_repo() -> IndexRepository:
    """获取指数仓库单例"""
    global _index_repo
    if _index_repo is None:
        _index_repo = IndexRepository()
    return _index_repo


def get_sector_repo() -> SectorRepository:
    """获取板块仓库单例"""
    global _sector_repo
    if _sector_repo is None:
        _sector_repo = SectorRepository()
    return _sector_repo


def get_market_repo() -> MarketRepository:
    """获取市场仓库单例"""
    global _market_repo
    if _market_repo is None:
        _market_repo = MarketRepository()
    return _market_repo


def get_task_repo() -> TaskRepository:
    """获取任务仓库单例"""
    global _task_repo
    if _task_repo is None:
        _task_repo = TaskRepository()
    return _task_repo


def get_weekly_summary_repo() -> WeeklySummaryRepository:
    """获取周总结仓库单例"""
    global _weekly_summary_repo
    if _weekly_summary_repo is None:
        _weekly_summary_repo = WeeklySummaryRepository()
    return _weekly_summary_repo


def get_monthly_summary_repo() -> MonthlySummaryRepository:
    """获取月总结仓库单例"""
    global _monthly_summary_repo
    if _monthly_summary_repo is None:
        _monthly_summary_repo = MonthlySummaryRepository()
    return _monthly_summary_repo


def get_watchlist_repo() -> WatchlistRepository:
    """获取关注列表仓库单例"""
    global _watchlist_repo
    if _watchlist_repo is None:
        _watchlist_repo = WatchlistRepository()
    return _watchlist_repo


def get_search_repo() -> SearchRepository:
    """获取统一搜索仓库单例"""
    global _search_repo
    if _search_repo is None:
        _search_repo = SearchRepository()
    return _search_repo


def get_etf_repo() -> EtfRepository:
    """获取 ETF 仓库单例"""
    global _etf_repo
    if _etf_repo is None:
        _etf_repo = EtfRepository()
    return _etf_repo


def get_market_analysis_repo() -> MarketAnalysisRepository:
    """获取市场分析仓库单例"""
    global _market_analysis_repo
    if _market_analysis_repo is None:
        _market_analysis_repo = MarketAnalysisRepository()
    return _market_analysis_repo


def get_system_config_repo() -> SystemConfigRepository:
    """获取系统配置仓库单例"""
    global _system_config_repo
    if _system_config_repo is None:
        _system_config_repo = SystemConfigRepository()
    return _system_config_repo


def get_market_review_repo() -> MarketReviewRepository:
    """获取市场复盘仓库单例"""
    global _market_review_repo
    if _market_review_repo is None:
        _market_review_repo = MarketReviewRepository()
    return _market_review_repo


def get_calendar_repo() -> CalendarRepository:
    """获取日历复盘仓库单例"""
    global _calendar_repo
    if _calendar_repo is None:
        _calendar_repo = CalendarRepository()
    return _calendar_repo


def get_restricted_release_repo() -> RestrictedReleaseRepository:
    """获取限售股解禁数据仓库单例"""
    global _restricted_release_repo
    if _restricted_release_repo is None:
        _restricted_release_repo = RestrictedReleaseRepository()
    return _restricted_release_repo


__all__ = [
    'BaseRepository',
    'StockRepository',
    'IndexRepository',
    'SectorRepository',
    'MarketRepository',
    'TaskRepository',
    'WeeklySummaryRepository',
    'MonthlySummaryRepository',
    'WatchlistRepository',
    'SearchRepository',
    'EtfRepository',
    'MarketAnalysisRepository',
    'SystemConfigRepository',
    'MarketReviewRepository',
    'CalendarRepository',
    'RestrictedReleaseRepository',
    'get_stock_repo',
    'get_index_repo',
    'get_sector_repo',
    'get_market_repo',
    'get_task_repo',
    'get_weekly_summary_repo',
    'get_monthly_summary_repo',
    'get_watchlist_repo',
    'get_search_repo',
    'get_etf_repo',
    'get_market_analysis_repo',
    'get_system_config_repo',
    'get_market_review_repo',
    'get_calendar_repo',
    'get_restricted_release_repo',
]
