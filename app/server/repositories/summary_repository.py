"""
Summary Repository - 周/月总结数据访问层
"""
from typing import Dict, List, Optional
from app.server.repositories.base import BaseRepository


class WeeklySummaryRepository(BaseRepository):
    """周总结仓库"""
    
    def __init__(self):
        super().__init__('weekly_summary')
    
    def get_by_key(self, year: int, month: int, week_index: int) -> Optional[Dict]:
        """根据年月周索引获取周总结"""
        cache_key = f'{year}-{month:02d}-week-{week_index}'
        return self.collection.find_one(
            {'_id': cache_key},
            {'_id': 0}
        )
    
    def upsert(self, year: int, month: int, week_index: int, data: Dict) -> None:
        """更新或插入周总结"""
        cache_key = f'{year}-{month:02d}-week-{week_index}'
        self.collection.update_one(
            {'_id': cache_key},
            {'$set': data},
            upsert=True
        )
    
    def get_range(self, year: int, month: int) -> List[Dict]:
        """获取某月的所有周总结"""
        prefix = f'{year}-{month:02d}-week-'
        return list(self.collection.find(
            {'_id': {'$regex': f'^{prefix}'}},
            {'_id': 0}
        ).sort('_id', 1))


class MonthlySummaryRepository(BaseRepository):
    """月总结仓库"""
    
    def __init__(self):
        super().__init__('monthly_summary')
    
    def get_by_key(self, year: int, month: int) -> Optional[Dict]:
        """根据年月获取月总结"""
        cache_key = f'{year}-{month:02d}'
        return self.collection.find_one(
            {'_id': cache_key},
            {'_id': 0}
        )
    
    def upsert(self, year: int, month: int, data: Dict) -> None:
        """更新或插入月总结"""
        cache_key = f'{year}-{month:02d}'
        self.collection.update_one(
            {'_id': cache_key},
            {'$set': data},
            upsert=True
        )
    
    def has_summary(self, year: int, month: int) -> bool:
        """检查是否有月总结"""
        cache_key = f'{year}-{month:02d}'
        return self.collection.count_documents({'_id': cache_key}) > 0
