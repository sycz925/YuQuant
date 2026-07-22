"""
Market Repository - 市场聚合数据访问层
"""
from typing import Dict, List, Optional
from app.server.repositories.base import BaseRepository


class MarketRepository(BaseRepository):
    """市场聚合数据仓库（base_data_daily + market_daily）"""
    
    def __init__(self):
        super().__init__('base_data_daily')
    
    @property
    def market_daily(self):
        """获取 market_daily 集合"""
        from app.data.db import get_db
        return get_db()['market_daily']
    
    def get_base_data(self, date: str) -> Optional[Dict]:
        """获取某日的基础数据"""
        return self.collection.find_one(
            {'date': date},
            {'_id': 0}
        )
    
    def get_base_data_range(self, start_date: str, end_date: str) -> List[Dict]:
        """获取日期范围内的基础数据"""
        return list(self.collection.find(
            {'date': {'$gte': start_date, '$lte': end_date}},
            {'_id': 0}
        ).sort('date', 1))
    
    def upsert_base_data(self, date: str, data: Dict) -> None:
        """更新或插入基础数据"""
        self.collection.update_one(
            {'date': date},
            {'$set': data},
            upsert=True
        )
    
    def get_market_overview(self, trade_date: str) -> Optional[Dict]:
        """获取市场总览"""
        return self.market_daily.find_one(
            {'trade_date': trade_date},
            {'_id': 0}
        )
    
    def get_market_overview_range(self, start_date: str, end_date: str) -> List[Dict]:
        """获取日期范围内的市场总览"""
        return list(self.market_daily.find(
            {'trade_date': {'$gte': start_date, '$lte': end_date}},
            {'_id': 0}
        ).sort('trade_date', 1))
    
    def upsert_market_overview(self, trade_date: str, data: Dict) -> None:
        """更新或插入市场总览"""
        self.market_daily.update_one(
            {'trade_date': trade_date},
            {'$set': data},
            upsert=True
        )
    
    def get_ai_analysis(self, trade_date: str) -> Optional[Dict]:
        """获取 AI 分析"""
        doc = self.market_daily.find_one(
            {'trade_date': trade_date},
            {'_id': 0, 'ai_analysis': 1}
        )
        return doc.get('ai_analysis') if doc else None
    
    def update_ai_analysis(self, trade_date: str, analysis: Dict) -> None:
        """更新 AI 分析"""
        self.market_daily.update_one(
            {'trade_date': trade_date},
            {'$set': {'ai_analysis': analysis}},
            upsert=True
        )
    
    def get_new_high_blocks(self, trade_date: str) -> Optional[Dict]:
        """获取新高板块"""
        doc = self.market_daily.find_one(
            {'trade_date': trade_date},
            {'_id': 0, 'new_high': 1}
        )
        return doc.get('new_high') if doc else None
