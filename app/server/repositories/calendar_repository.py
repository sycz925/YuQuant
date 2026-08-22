"""
Calendar Repository - 日历复盘数据访问层
封装 base_data_daily / market_daily / index_daily / stock_daily / sector_* 的查询
（供 services/calendar_service.py 快照生成 + 每日总结使用）
"""
from typing import Dict, List, Optional

from app.data.db import get_db
from app.server.repositories.base import BaseRepository


class CalendarRepository(BaseRepository):
    """日历复盘数据访问（快照 + 每日总结的多集合查询）"""

    def __init__(self):
        super().__init__('base_data_daily')

    def _db(self):
        return get_db()

    # ---- 快照生成读取 ----

    def get_base_snapshot(self, date: str) -> Optional[Dict]:
        """读 base_data_daily 单日涨跌家数/成交额/is_final"""
        return self.collection.find_one(
            {'date': date},
            {'_id': 0, 'up_count': 1, 'down_count': 1, 'total_amount': 1, 'is_final': 1}
        )

    def get_market_snapshot(self, date: str) -> Optional[Dict]:
        """读 market_daily 单日新高集群 + 指数状态"""
        return self._db()['market_daily'].find_one(
            {'trade_date': date},
            {'_id': 0, 'new_high': 1, 'ai_analysis': 1, 'overview.indices': 1}
        )

    def get_index_chg_pct(self, code: str, date: str) -> Optional[Dict]:
        """读 index_daily 单日涨跌幅"""
        return self._db()['index_daily'].find_one(
            {'stock_code': code, 'trade_date': date},
            {'_id': 0, 'chg_pct': 1}
        )

    def get_sector_code(self, name: str, tdx_first: bool = False) -> Optional[Dict]:
        """按板块名查 code（tdx_first=True 时优先 880 通达信代码）"""
        if tdx_first:
            doc = self._db()['sector_basics'].find_one(
                {'name': name, 'code': {'$regex': '^880'}}, {'_id': 0, 'code': 1}
            )
            if doc:
                return doc
        return self._db()['sector_basics'].find_one({'name': name}, {'_id': 0, 'code': 1})

    def get_sector_chg_pct(self, code: str, date: str) -> Optional[Dict]:
        """读 sector_daily 单日涨跌幅"""
        return self._db()['sector_daily'].find_one(
            {'stock_code': code, 'trade_date': date},
            {'_id': 0, 'chg_pct': 1}
        )

    # ---- 快照写入 ----

    def save_snapshot(self, date: str, snapshot: Dict) -> None:
        """写 calendar_snapshot 到 base_data_daily（upsert）"""
        self.collection.update_one(
            {'date': date},
            {'$set': {'calendar_snapshot': snapshot}},
            upsert=True
        )

    def has_snapshot(self, date: str) -> Optional[Dict]:
        """检查某日是否已有快照"""
        return self.collection.find_one(
            {'date': date, 'calendar_snapshot': {'$exists': True}},
            {'_id': 0, 'date': 1}
        )

    def clear_snapshots(self, dates: List[str]):
        """清除指定日期列表的 calendar_snapshot 字段，返回 UpdateResult"""
        return self.collection.update_many(
            {'date': {'$in': dates}, 'calendar_snapshot': {'$exists': True}},
            {'$unset': {'calendar_snapshot': ''}}
        )

    # ---- 每日总结读取 ----

    def get_snapshots_range(self, start: str, end: str):
        """读日期范围内的快照（按 date 升序）"""
        return self.collection.find(
            {
                'date': {'$gte': start, '$lt': end},
                'calendar_snapshot': {'$exists': True}
            },
            {'_id': 0, 'date': 1, 'calendar_snapshot': 1}
        ).sort('date', 1)

    def get_ai_analysis_range(self, start: str, end: str):
        """读日期范围内的 AI 分析"""
        return self._db()['market_daily'].find(
            {'trade_date': {'$gte': start, '$lt': end}},
            {'_id': 0, 'trade_date': 1, 'ai_analysis': 1}
        )

    def get_base_daily_bulk(self, dates: List[str]):
        """按日期列表读 base_data_daily 基础字段"""
        return self.collection.find(
            {'date': {'$in': dates}},
            {
                '_id': 0, 'date': 1, 'up_count': 1, 'down_count': 1,
                'total_amount': 1, 'cr5_pct': 1, 'ma50_pct': 1, 'is_final': 1
            }
        )

    def get_market_daily_bulk(self, dates: List[str]):
        """按日期列表读 market_daily 新高集群 + 指数状态"""
        return self._db()['market_daily'].find(
            {'trade_date': {'$in': dates}},
            {'_id': 0, 'trade_date': 1, 'new_high': 1, 'overview.indices': 1}
        )

    def get_index_daily_bulk(self, code: str, dates: List[str]):
        """按指数代码 + 日期列表读 index_daily 收盘/涨跌幅"""
        return self._db()['index_daily'].find(
            {'stock_code': code, 'trade_date': {'$in': dates}},
            {'_id': 0, 'trade_date': 1, 'close': 1, 'chg_pct': 1}
        )

    def count_stock_daily(self, date: str, is_final: Optional[bool] = None) -> int:
        """统计某日 stock_daily 收盘价>0 的股票数（可选 is_final 过滤）"""
        query = {'trade_date': date, 'close': {'$gt': 0}}
        if is_final is not None:
            query['is_final'] = is_final
        return self._db()['stock_daily'].count_documents(query)

    # ---- 周/月总结输入构建 ----

    def list_enabled_sectors(self) -> List[Dict]:
        """读所有未禁用板块的 code+name"""
        return list(self._db()['sector_basics'].find(
            {'is_disable': {'$ne': True}}, {'_id': 0, 'code': 1, 'name': 1}
        ))

    def get_sector_chg_bulk(self, codes: List[str], dates: List[str]):
        """按板块代码列表 + 日期列表读 sector_daily 涨跌幅"""
        return self._db()['sector_daily'].find(
            {'stock_code': {'$in': codes}, 'trade_date': {'$in': dates}},
            {'_id': 0, 'stock_code': 1, 'trade_date': 1, 'chg_pct': 1}
        )

    def get_strong_sectors(self, date: str, rps_key: str):
        """读某日 RPS>85 的板块（stock_code + rps + chg_pct）"""
        return self._db()['sector_daily'].find(
            {'trade_date': date, rps_key: {'$gt': 85}},
            {'_id': 0, 'stock_code': 1, rps_key: 1, 'chg_pct': 1}
        )

    def list_enabled_indices(self) -> List[Dict]:
        """读所有未禁用指数的 code+name"""
        return list(self._db()['index_basics'].find(
            {'is_disable': {'$ne': True}}, {'_id': 0, 'code': 1, 'name': 1}
        ))

    def get_index_close_by_date(self, date: str) -> List[Dict]:
        """读某日所有指数收盘价"""
        return list(self._db()['index_daily'].find(
            {'trade_date': date}, {'_id': 0, 'stock_code': 1, 'close': 1}
        ))

    def get_prev_index_trade_date(self, before_date: str) -> Optional[str]:
        """读 before_date 之前的最近一个指数交易日"""
        doc = self._db()['index_daily'].find_one(
            {'trade_date': {'$lt': before_date}},
            sort=[('trade_date', -1)],
            projection={'trade_date': 1, '_id': 0}
        )
        return doc['trade_date'] if doc else None

    def get_index_status_by_date(self, date: str) -> Optional[Dict]:
        """读某日 market_daily 的指数状态（overview.indices）"""
        return self._db()['market_daily'].find_one(
            {'trade_date': date}, {'_id': 0, 'overview.indices': 1}
        )

    # ---- AI 补全任务 ----

    def get_stock_trade_dates(self) -> List[str]:
        """读 stock_daily 所有交易日（升序）"""
        return sorted(self._db()['stock_daily'].distinct('trade_date'))

    def get_market_ai_analysis(self, date: str) -> Optional[Dict]:
        """读 market_daily 某日 ai_analysis"""
        return self._db()['market_daily'].find_one(
            {'trade_date': date}, {'_id': 0, 'ai_analysis': 1}
        )

    def get_market_full(self, date: str) -> Optional[Dict]:
        """读 market_daily 某日全字段"""
        return self._db()['market_daily'].find_one({'trade_date': date}, {'_id': 0})
