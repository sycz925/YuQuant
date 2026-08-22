"""
Sector Repository - 板块数据访问层
"""
from typing import Dict, List, Optional
from app.server.repositories.base import BaseRepository


class SectorRepository(BaseRepository):
    """板块基础信息和日线数据仓库"""
    
    def __init__(self):
        super().__init__('sector_basics')
    
    @property
    def daily(self):
        """获取日线数据集合"""
        from app.data.db import get_db
        return get_db()['sector_daily']
    
    def get_enabled_codes(self) -> List[str]:
        """获取所有启用的板块代码"""
        return [
            doc['code'] for doc in self.collection.find(
                {'is_disable': {'$ne': True}},
                {'_id': 0, 'code': 1}
            )
        ]
    
    def get_enabled_list(self) -> List[Dict]:
        """获取所有启用的板块列表"""
        return list(self.collection.find(
            {'is_disable': {'$ne': True}},
            {'_id': 0, 'code': 1, 'name': 1, 'stock_count': 1}
        ))
    
    def get_by_code(self, code: str) -> Optional[Dict]:
        """根据板块代码获取板块信息"""
        return self.collection.find_one(
            {'code': code},
            {'_id': 0}
        )
    
    def get_by_name(self, name: str) -> Optional[Dict]:
        """根据板块名称获取板块信息"""
        return self.collection.find_one(
            {'name': name},
            {'_id': 0, 'code': 1, 'name': 1}
        )
    
    def search(self, keyword: str) -> List[Dict]:
        """搜索板块（代码、名称）"""
        return list(self.collection.find(
            {'$or': [
                {'code': {'$regex': keyword, '$options': 'i'}},
                {'name': {'$regex': keyword, '$options': 'i'}}
            ]},
            {'_id': 0, 'code': 1, 'name': 1, 'stock_count': 1}
        ).limit(50))
    
    def get_daily_data(self, code: str, start_date: Optional[str] = None,
                       end_date: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """获取板块日线数据"""
        query = {'stock_code': code, 'close': {'$gt': 0}}
        if start_date:
            query['trade_date'] = {'$gte': start_date}
        if end_date:
            query.setdefault('trade_date', {})['$lte'] = end_date
        
        return list(self.daily.find(
            query,
            {'_id': 0}
        ).sort('trade_date', -1).limit(limit))
    
    def get_daily_bars(self, code: str, start_date: str, end_date: str,
                       limit: int, projection: Dict) -> List[Dict]:
        """获取板块日线数据（带自定义投影，不含 close 过滤）"""
        query = {
            'stock_code': code,
            'trade_date': {'$gte': start_date, '$lte': end_date},
        }
        return list(self.daily.find(query, projection).sort('trade_date', -1).limit(limit))
    
    def get_all_names(self) -> set:
        """获取所有板块名称集合"""
        return {doc['name'] for doc in self.collection.find({}, {'_id': 0, 'name': 1})}
    
    def get_daily_docs(self, code: str) -> List[Dict]:
        """获取板块日线（trade_date/close/vol，升序）"""
        return list(self.daily.find(
            {'stock_code': code},
            {'_id': 0, 'trade_date': 1, 'close': 1, 'vol': 1}
        ).sort('trade_date', 1))
    
    def update_daily(self, code: str, trade_date: str, fields: Dict) -> int:
        """更新板块日线字段"""
        return self.daily.update_one(
            {'stock_code': code, 'trade_date': trade_date},
            {'$set': fields}
        )

    def get_sector_daily_field(self, code: str, trade_date: str, fields: Dict) -> Optional[Dict]:
        """获取板块日线指定字段"""
        return self.daily.find_one(
            {'stock_code': code, 'trade_date': trade_date},
            fields
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
