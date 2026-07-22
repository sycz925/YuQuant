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

# 单例实例
_stock_repo: StockRepository = None
_index_repo: IndexRepository = None
_sector_repo: SectorRepository = None
_market_repo: MarketRepository = None
_task_repo: TaskRepository = None
_weekly_summary_repo: WeeklySummaryRepository = None
_monthly_summary_repo: MonthlySummaryRepository = None


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


__all__ = [
    'BaseRepository',
    'StockRepository',
    'IndexRepository',
    'SectorRepository',
    'MarketRepository',
    'TaskRepository',
    'WeeklySummaryRepository',
    'MonthlySummaryRepository',
    'get_stock_repo',
    'get_index_repo',
    'get_sector_repo',
    'get_market_repo',
    'get_task_repo',
    'get_weekly_summary_repo',
    'get_monthly_summary_repo',
]
