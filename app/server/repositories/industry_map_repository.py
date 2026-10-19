"""
Industry Map Repository - 产业地图数据访问层
封装产业链图谱结果（按 keyword 缓存）的查询与写入
"""
from datetime import datetime as _dt
from typing import Dict, List, Optional

from app.data.db import get_db
from app.server.repositories.base import BaseRepository


class IndustryMapRepository(BaseRepository):
    """产业地图仓库（key: keyword）"""

    def __init__(self):
        super().__init__('industry_map')

    def get_by_keyword(self, keyword: str) -> Optional[Dict]:
        """按关键字读取缓存的产业链图谱"""
        return self.collection.find_one({'keyword': keyword}, {'_id': 0})

    def upsert(self, keyword: str, data: Dict) -> Dict:
        """写入或更新产业链图谱（附生成时间）"""
        doc = {'keyword': keyword, **data, 'generated_at': _dt.now().isoformat()}
        self.collection.update_one({'keyword': keyword}, {'$set': doc}, upsert=True)
        return doc

    def delete_by_keyword(self, keyword: str) -> int:
        """删除指定关键字的缓存，返回删除数量"""
        result = self.collection.delete_one({'keyword': keyword})
        return result.deleted_count

    def list_history(self) -> List[Dict]:
        """历史记录列表（按生成时间倒序）"""
        return list(self.collection.find(
            {}, {'_id': 0, 'keyword': 1, 'industry': 1, 'generated_at': 1}
        ).sort('generated_at', -1))

    def get_stock_code_by_name(self, name: str) -> Optional[Dict]:
        """按公司名匹配 stock_basics，返回 {stock_code, stock_name, market}"""
        db = get_db()
        # 精确匹配优先
        doc = db['stock_basics'].find_one(
            {'stock_name': name},
            {'_id': 0, 'stock_code': 1, 'stock_name': 1, 'market': 1}
        )
        if doc:
            return doc
        # 包含匹配（忽略大小写）
        return db['stock_basics'].find_one(
            {'stock_name': {'$regex': name, '$options': 'i'}},
            {'_id': 0, 'stock_code': 1, 'stock_name': 1, 'market': 1}
        )

    def get_latest_stock_rps(self, codes: List[str]) -> Dict[str, Dict]:
        """批量读 stock_daily 每个 code 最新（收盘价>0）的 rps_10/rps_50/rps_120"""
        if not codes:
            return {}
        db = get_db()
        result = {}
        for code in set(codes):
            doc = db['stock_daily'].find_one(
                {'stock_code': code, 'close': {'$gt': 0}},
                sort=[('trade_date', -1)],
                projection={'rps_10': 1, 'rps_50': 1, 'rps_120': 1, '_id': 0}
            )
            if doc:
                result[code] = doc
        return result
