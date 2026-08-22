"""
Market Review Repository - 市场复盘数据访问层
"""
from typing import Dict, List, Optional

from app.data.db import get_db
from app.server.repositories.base import BaseRepository


class MarketReviewRepository(BaseRepository):
    """市场复盘数据访问（market_daily 缓存 + base_data_daily + 最新交易日）"""

    def __init__(self):
        super().__init__('market_daily')

    # ---- market_daily 缓存 ----

    def get_cached(self, date: str, field: Optional[str] = None) -> Optional[Dict]:
        """读 market_daily 缓存（可选子字段），返回 doc 或 None"""
        projection = {'_id': 0, field: 1} if field else {'_id': 0}
        return self.collection.find_one({'trade_date': date}, projection)

    def get_cached_multi(self, dates: List[str], fields: Dict) -> List[Dict]:
        """按日期列表读 market_daily 缓存"""
        return list(self.collection.find(
            {'trade_date': {'$in': dates}},
            fields
        ))

    def set_cached_field(self, date: str, field: str, value) -> None:
        """写 market_daily 子字段（upsert）"""
        self.collection.update_one(
            {'trade_date': date}, {'$set': {field: value}}, upsert=True)

    def unset_cached_field(self, date: str, field: str) -> None:
        """删 market_daily 子字段"""
        self.collection.update_one({'trade_date': date}, {'$unset': {field: ''}})

    # ---- 最新交易日 / 基础数据 ----

    def get_latest_base_date(self) -> Optional[str]:
        """base_data_daily 最新日期"""
        db = get_db()
        doc = db['base_data_daily'].find_one(sort=[('date', -1)], projection={'_id': 0, 'date': 1})
        return doc['date'] if doc else None

    def get_base_data(self, date: str) -> Optional[Dict]:
        """读 base_data_daily 某日完整数据"""
        db = get_db()
        return db['base_data_daily'].find_one({'date': date}, {'_id': 0})

    def get_latest_stock_date(self) -> Optional[str]:
        """stock_daily 最新交易日"""
        db = get_db()
        doc = db['stock_daily'].find_one(sort=[('trade_date', -1)], projection={'_id': 0, 'trade_date': 1})
        return doc['trade_date'] if doc else None

    def get_stock_trade_dates(self) -> List[str]:
        """stock_daily 所有交易日（降序）"""
        db = get_db()
        return sorted(db['stock_daily'].distinct('trade_date'), reverse=True)

    def get_base_data_list(self, filter_q: Dict, fields: Dict, days: int) -> List[Dict]:
        """读取 base_data_daily（按日期降序，limit days）"""
        db = get_db()
        return list(db['base_data_daily'].find(filter_q, fields).sort('date', -1).limit(days))

    def bulk_write_base(self, operations: List) -> None:
        """批量写 base_data_daily"""
        db = get_db()
        db['base_data_daily'].bulk_write(operations, ordered=False)

    def get_index_daily(self, index_code: str, dates: List[str]) -> Dict[str, float]:
        """读取指数日线 close → {trade_date: close}"""
        db = get_db()
        cursor = db['index_daily'].find(
            {'stock_code': index_code, 'trade_date': {'$in': dates}},
            {'_id': 0, 'trade_date': 1, 'close': 1}
        ).sort('trade_date', 1)
        return {d['trade_date']: d['close'] for d in cursor}

    def aggregate_stock_daily(self, pipeline: List[Dict]) -> List[Dict]:
        """stock_daily 聚合管道"""
        db = get_db()
        return list(db['stock_daily'].aggregate(pipeline))

    def get_index_daily_range(self, index_code: str, start: str, end: str) -> Dict[str, float]:
        """读取指数日线 close（日期范围）→ {trade_date: close}"""
        db = get_db()
        cursor = db['index_daily'].find(
            {'stock_code': index_code, 'trade_date': {'$gte': start, '$lte': end}},
            {'_id': 0, 'trade_date': 1, 'close': 1}
        ).sort('trade_date', 1)
        return {d['trade_date']: d['close'] for d in cursor}

    def get_index_trade_dates(self, query: Dict) -> List[str]:
        """index_daily 交易日列表（升序）"""
        db = get_db()
        return sorted(db['index_daily'].distinct('trade_date', query))

    def get_index_daily_by_date(self, date: str) -> List[Dict]:
        """某日所有指数收盘价"""
        db = get_db()
        return list(db['index_daily'].find(
            {'trade_date': date},
            {'_id': 0, 'stock_code': 1, 'close': 1}
        ))
