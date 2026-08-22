"""
Watchlist Repository - 重点关注列表数据访问层
"""
from datetime import datetime
from typing import Dict, List, Optional

from app.data.db import get_db, get_collection
from app.server.repositories.base import BaseRepository

# 列表行情字段投影（与 /etf 一致；路由层不再持有该常量）
_QUOTE_FIELDS = {
    'close': 1, 'chg_pct': 1, 'chg_5d': 1, 'chg_10d': 1, 'chg_20d': 1,
    'chg_50d': 1, 'chg_120d': 1, 'rps_10': 1, 'rps_50': 1, 'rps_120': 1, '_id': 0,
}


class WatchlistRepository(BaseRepository):
    """重点关注列表数据访问（watchlist 集合 + 行情解析）"""

    def __init__(self):
        super().__init__('watchlist')

    def list_entries(self) -> List[Dict]:
        """返回全部关注条目（按创建时间升序）"""
        return list(self.collection.find({}, {'_id': 0}).sort('created_at', 1))

    def resolve_entry(self, entry: Dict) -> Dict:
        """解析条目为基础信息 + 最新行情，返回字段名与 WatchlistItem 对齐的 dict"""
        code = entry['code']
        typ = entry.get('type', 'etf')
        if typ == 'etf':
            basic = get_db()['etf_basics'].find_one({'code': code}, {'_id': 0, 'name': 1})
            name = basic['name'] if basic else code
            coll = get_collection('etf')
        else:
            basic = get_db()['stock_basics'].find_one({'stock_code': code}, {'_id': 0, 'stock_name': 1})
            name = basic['stock_name'] if basic else code
            coll = get_collection('stock')

        latest = coll.find_one(
            {'stock_code': code, 'close': {'$gt': 0}},
            sort=[('trade_date', -1)],
            projection=_QUOTE_FIELDS,
        )

        result = {'code': code, 'name': name, 'type': typ, 'tdx_status': entry.get('tdx_status')}
        if latest:
            result['close'] = latest.get('close')
            result['change_pct'] = latest.get('chg_pct')  # DB 字段 chg_pct → 模型字段 change_pct
            for k in ('chg_5d', 'chg_10d', 'chg_20d', 'chg_50d', 'chg_120d', 'rps_10', 'rps_50', 'rps_120'):
                result[k] = latest.get(k)
        return result

    def find_type(self, code: str) -> Optional[str]:
        """识别代码类型（etf/stock），未找到返回 None"""
        db = get_db()
        if db['etf_basics'].find_one({'code': code}, {'_id': 1}):
            return 'etf'
        if db['stock_basics'].find_one({'stock_code': code}, {'_id': 1}):
            return 'stock'
        return None

    def add(self, code: str, typ: str):
        """插入一条关注记录"""
        return self.collection.insert_one({'code': code, 'type': typ, 'created_at': datetime.now()})

    def remove(self, code: str) -> int:
        """删除一条关注记录，返回删除数"""
        return self.collection.delete_one({'code': code}).deleted_count
