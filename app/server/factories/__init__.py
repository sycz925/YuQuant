"""
Factories - 工厂层
按数据域内聚，提供原子能力
"""
from app.server.factories.base import SyncResult, ComputeResult, PipelineResult, ProgressCallback
from app.server.factories.index_factory import IndexFactory
from app.server.factories.stock_factory import StockFactory
from app.server.factories.sector_factory import SectorFactory
from app.server.factories.market_aggregator import MarketAggregator

# 单例实例
_index_factory: IndexFactory = None
_stock_factory: StockFactory = None
_sector_factory: SectorFactory = None
_market_aggregator: MarketAggregator = None


def get_index_factory() -> IndexFactory:
    """获取指数工厂单例"""
    global _index_factory
    if _index_factory is None:
        _index_factory = IndexFactory()
    return _index_factory


def get_stock_factory() -> StockFactory:
    """获取个股工厂单例"""
    global _stock_factory
    if _stock_factory is None:
        _stock_factory = StockFactory()
    return _stock_factory


def get_sector_factory() -> SectorFactory:
    """获取板块工厂单例"""
    global _sector_factory
    if _sector_factory is None:
        _sector_factory = SectorFactory()
    return _sector_factory


def get_market_aggregator() -> MarketAggregator:
    """获取市场聚合器单例"""
    global _market_aggregator
    if _market_aggregator is None:
        _market_aggregator = MarketAggregator()
    return _market_aggregator


__all__ = [
    'SyncResult',
    'ComputeResult',
    'PipelineResult',
    'ProgressCallback',
    'IndexFactory',
    'StockFactory',
    'SectorFactory',
    'MarketAggregator',
    'get_index_factory',
    'get_stock_factory',
    'get_sector_factory',
    'get_market_aggregator',
]
