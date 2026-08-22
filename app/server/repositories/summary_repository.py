"""
Summary Repository - 周/月总结数据访问层
"""
from typing import Dict, List, Optional
from app.server.repositories.base import BaseRepository


class WeeklySummaryRepository(BaseRepository):
    """周总结仓库（key: year + month + week_index）"""

    def __init__(self):
        super().__init__('weekly_summary')

    def get_by_key(self, year: int, month: int, week_index: int) -> Optional[Dict]:
        """根据年月周索引获取周总结"""
        return self.collection.find_one(
            {'year': year, 'month': month, 'week_index': week_index},
            {'_id': 0}
        )

    def upsert(self, year: int, month: int, week_index: int, data: Dict) -> None:
        """更新或插入周总结"""
        self.collection.update_one(
            {'year': year, 'month': month, 'week_index': week_index},
            {'$set': data},
            upsert=True
        )

    def get_range(self, year: int, month: int) -> List[Dict]:
        """获取某月的所有周总结"""
        return list(self.collection.find(
            {'year': year, 'month': month},
            {'_id': 0}
        ).sort('week_index', 1))

    def has_summary(self, year: int, month: int, week_index: int) -> bool:
        """检查是否有周总结"""
        return self.collection.count_documents(
            {'year': year, 'month': month, 'week_index': week_index}) > 0


class MonthlySummaryRepository(BaseRepository):
    """月总结仓库（key: year + month）"""

    def __init__(self):
        super().__init__('monthly_summary')

    def get_by_key(self, year: int, month: int) -> Optional[Dict]:
        """根据年月获取月总结"""
        return self.collection.find_one(
            {'year': year, 'month': month},
            {'_id': 0}
        )

    def upsert(self, year: int, month: int, data: Dict) -> None:
        """更新或插入月总结"""
        self.collection.update_one(
            {'year': year, 'month': month},
            {'$set': data},
            upsert=True
        )

    def has_summary(self, year: int, month: int) -> bool:
        """检查是否有月总结"""
        return self.collection.count_documents({'year': year, 'month': month}) > 0
