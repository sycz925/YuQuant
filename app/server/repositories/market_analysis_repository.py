"""
Market Analysis Repository - 市场多维分析数据访问层
"""
from typing import Dict, List, Optional, Set

from app.data.db import get_db
from app.server.repositories.base import BaseRepository


class MarketAnalysisRepository(BaseRepository):
    """市场分析数据访问（stock_daily / sector_daily / stock_basics / sector_basics）"""

    def __init__(self):
        super().__init__('stock_daily')

    # ---- 日期 ----

    def get_latest_trade_date(self) -> Optional[str]:
        """最新交易日（stock_daily 与 sector_daily 中较小的）"""
        db = get_db()
        latest_stock = db['stock_daily'].find_one(
            {'close': {'$gt': 0}},
            sort=[('trade_date', -1)],
            projection={'trade_date': 1, '_id': 0},
        )
        latest_sector = db['sector_daily'].find_one(
            {},
            sort=[('trade_date', -1)],
            projection={'trade_date': 1, '_id': 0},
        )
        candidates = [d['trade_date'] for d in (latest_stock, latest_sector) if d]
        return min(candidates) if candidates else None

    def get_latest_stock_trade_date(self) -> Optional[str]:
        """仅从 stock_daily 获取最新交易日"""
        db = get_db()
        latest = db['stock_daily'].find_one(
            {'close': {'$gt': 0}},
            sort=[('trade_date', -1)],
            projection={'trade_date': 1, '_id': 0},
        )
        return latest['trade_date'] if latest else None

    def get_previous_trade_date(self, date: str) -> Optional[str]:
        """指定日期之前的最近一个交易日"""
        db = get_db()
        result = list(db['stock_daily'].find(
            {'trade_date': {'$lt': date}},
            {'trade_date': 1, '_id': 0},
        ).sort('trade_date', -1).limit(1))
        return result[0]['trade_date'] if result else None

    # ---- 基础信息 ----

    def get_enabled_stock_codes(self) -> Set[str]:
        db = get_db()
        return {doc['stock_code'] for doc in db['stock_basics'].find(
            {'is_disable': {'$ne': True}}, {'_id': 0, 'stock_code': 1})}

    def get_enabled_sector_codes(self) -> Set[str]:
        db = get_db()
        return {doc['code'] for doc in db['sector_basics'].find(
            {'is_disable': {'$ne': True}}, {'_id': 0, 'code': 1})}

    def get_stock_names(self, codes) -> Dict[str, str]:
        db = get_db()
        return {d['stock_code']: d['stock_name'] for d in db['stock_basics'].find(
            {'stock_code': {'$in': list(codes)}},
            {'_id': 0, 'stock_code': 1, 'stock_name': 1})}

    def get_liutong_map(self, codes) -> Dict[str, float]:
        db = get_db()
        result = {}
        for doc in db['stock_basics'].find(
            {'stock_code': {'$in': list(codes)}},
            {'_id': 0, 'stock_code': 1, 'liutongguben': 1}):
            if doc.get('liutongguben'):
                result[doc['stock_code']] = doc['liutongguben']
        return result

    def get_sector_name_map(self) -> Dict[str, str]:
        db = get_db()
        return {s['code']: s.get('name', s['code']) for s in db['sector_basics'].find(
            {}, {'_id': 0, 'code': 1, 'name': 1})}

    # ---- 当日行情 ----

    def get_stock_daily_map(self, date: str, codes, projection: Dict) -> Dict:
        """当日个股行情 → {stock_code: doc}"""
        db = get_db()
        return {d['stock_code']: d for d in db['stock_daily'].find(
            {'trade_date': date, 'close': {'$gt': 0}, 'amount': {'$gt': 0},
             'stock_code': {'$in': list(codes)}},
            projection)}

    def get_sector_daily_map(self, date: str, codes, projection: Dict) -> Dict:
        """当日板块行情 → {stock_code: doc}"""
        db = get_db()
        return {d['stock_code']: d for d in db['sector_daily'].find(
            {'trade_date': date, 'close': {'$gt': 0},
             'stock_code': {'$in': list(codes)}},
            projection)}

    def get_active_stocks(self, date: str, codes, projection: Dict) -> List[Dict]:
        """活跃股列表（is_active=True）"""
        db = get_db()
        return list(db['stock_daily'].find(
            {'trade_date': date, 'close': {'$gt': 0}, 'amount': {'$gt': 0},
             'is_active': True, 'stock_code': {'$in': list(codes)}},
            projection))

    def get_trade_date_info(self, date: str, limit: int = 50) -> List[Dict]:
        """某交易日数据的 is_final/update_time/data_source 信息"""
        db = get_db()
        return list(db['stock_daily'].find(
            {'trade_date': date},
            {'_id': 0, 'is_final': 1, 'update_time': 1, 'data_source': 1}).limit(limit))
