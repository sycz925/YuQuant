"""
Search Repository - 统一搜索数据访问层（股票/板块/ETF）
"""
from typing import Dict, List

from app.data.db import get_db
from app.server.repositories.base import BaseRepository


class SearchRepository(BaseRepository):
    """统一搜索：跨 stock_basics / sector_basics / etf_basics 三集合"""

    def __init__(self):
        super().__init__('stock_basics')

    def search_stocks(self, keyword: str, limit: int = 15) -> List[Dict]:
        """按代码/名称搜索股票，返回 [{code, name}]"""
        db = get_db()
        by_code = list(db['stock_basics'].find(
            {'stock_code': {'$regex': keyword, '$options': 'i'}},
            {'_id': 0, 'stock_code': 1, 'stock_name': 1}
        ).limit(5))
        by_name = list(db['stock_basics'].find(
            {'stock_name': {'$regex': keyword, '$options': 'i'}},
            {'_id': 0, 'stock_code': 1, 'stock_name': 1}
        ).limit(10))

        seen = set()
        result = []
        for s in by_code + by_name:
            if s['stock_code'] not in seen:
                seen.add(s['stock_code'])
                result.append({'code': s['stock_code'], 'name': s['stock_name']})
        return result[:limit]

    def search_sectors(self, keyword: str, limit: int = 10) -> List[Dict]:
        """按名称搜索板块，返回 [{code, name}]"""
        db = get_db()
        cursor = db['sector_basics'].find(
            {'name': {'$regex': keyword, '$options': 'i'}},
            {'_id': 0, 'code': 1, 'name': 1}
        ).limit(limit)
        return [{'code': s['code'], 'name': s['name']} for s in cursor]

    def search_etfs(self, keyword: str, limit: int = 15) -> List[Dict]:
        """按代码/名称搜索ETF，返回 [{code, name}]"""
        db = get_db()
        by_code = list(db['etf_basics'].find(
            {'code': {'$regex': keyword, '$options': 'i'}},
            {'_id': 0, 'code': 1, 'name': 1}
        ).limit(5))
        by_name = list(db['etf_basics'].find(
            {'name': {'$regex': keyword, '$options': 'i'}},
            {'_id': 0, 'code': 1, 'name': 1}
        ).limit(10))

        seen = set()
        result = []
        for e in by_code + by_name:
            if e['code'] not in seen:
                seen.add(e['code'])
                result.append({'code': e['code'], 'name': e['name']})
        return result[:limit]
