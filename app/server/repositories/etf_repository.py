"""
ETF Repository - ETF 数据访问层
"""
from typing import Dict, Optional

from app.data.db import get_collection
from app.server.repositories.base import BaseRepository

# 列表行情字段投影（与 watchlist 一致）
_QUOTE_FIELDS = {
    'close': 1, 'chg_pct': 1, 'chg_5d': 1, 'chg_10d': 1,
    'chg_20d': 1, 'chg_50d': 1, 'chg_120d': 1,
    'rps_10': 1, 'rps_50': 1, 'rps_120': 1, '_id': 0,
}


class EtfRepository(BaseRepository):
    """ETF 基础信息与行情数据访问"""

    def __init__(self):
        super().__init__('etf_basics')

    def get_latest_quote(self, code: str) -> Optional[Dict]:
        """获取 ETF 最新行情（含涨跌幅与 RPS 字段）"""
        coll = get_collection('etf')
        return coll.find_one(
            {'stock_code': code, 'close': {'$gt': 0}},
            sort=[('trade_date', -1)],
            projection=_QUOTE_FIELDS,
        )
