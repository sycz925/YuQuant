"""
Index Repository - 指数数据访问层
"""
from typing import Dict, List, Optional
from app.server.repositories.base import BaseRepository


class IndexRepository(BaseRepository):
    """指数基础信息和日线数据仓库"""
    
    def __init__(self):
        super().__init__('index_basics')
    
    @property
    def daily(self):
        """获取日线数据集合"""
        from app.data.db import get_db
        return get_db()['index_daily']
    
    def get_enabled_codes(self) -> List[str]:
        """获取所有启用的指数代码"""
        return [
            doc['code'] for doc in self.collection.find(
                {'is_disable': {'$ne': True}},
                {'_id': 0, 'code': 1}
            )
        ]
    
    def get_enabled_list(self) -> List[Dict]:
        """获取所有启用的指数列表"""
        return list(self.collection.find(
            {'is_disable': {'$ne': True}},
            {'_id': 0, 'code': 1, 'name': 1, 'tdx_code': 1, 'market': 1}
        ))
    
    def get_by_code(self, code: str) -> Optional[Dict]:
        """根据指数代码获取指数信息"""
        return self.collection.find_one(
            {'code': code},
            {'_id': 0}
        )
    
    def search(self, keyword: str) -> List[Dict]:
        """搜索指数（代码、名称）"""
        return list(self.collection.find(
            {'$or': [
                {'code': {'$regex': keyword, '$options': 'i'}},
                {'name': {'$regex': keyword, '$options': 'i'}}
            ]},
            {'_id': 0, 'code': 1, 'name': 1, 'tdx_code': 1, 'market': 1}
        ).limit(50))
    
    def get_daily_data(self, code: str, start_date: Optional[str] = None,
                       end_date: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """获取指数日线数据"""
        query = {'stock_code': code}
        if start_date:
            query['trade_date'] = {'$gte': start_date}
        if end_date:
            query.setdefault('trade_date', {})['$lte'] = end_date
        
        return list(self.daily.find(
            query,
            {'_id': 0, 'trade_date': 1, 'open': 1, 'high': 1, 'low': 1, 'close': 1, 'amount': 1}
        ).sort('trade_date', -1).limit(limit))
    
    def update_pe(self, code: str, pe_ttm: float) -> int:
        """更新 PE 值"""
        return self.update_one(
            {'code': code},
            {'$set': {'pe_ttm': pe_ttm}}
        )

    def update_disable_status(self, code: str, is_disable: bool) -> int:
        """更新禁用状态"""
        return self.update_one(
            {'code': code},
            {'$set': {'is_disable': is_disable}}
        )
    
    def aggregate_daily(self, pipeline: List[Dict]) -> List[Dict]:
        """聚合日线数据"""
        return list(self.daily.aggregate(pipeline))
    
    def bulk_write_daily(self, operations: List, ordered: bool = False):
        """批量写入日线数据"""
        return self.daily.bulk_write(operations, ordered=ordered)
