"""
Position Repository - 持仓风控数据访问层

负责三个集合：
  - accounts   账户（资金池）
  - positions  持仓（一笔买入 = 一条，以 position_id 为最小风控单位）
  - system_config 中的风控参数（key = POSITION_PARAM_KEY）

行情只读访问（stock_daily / etf_daily / *_basics）也收敛在此，
确保 services 层不直连集合（AGENTS.md §7）。
"""
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from app.data.db import get_db
from app.server.repositories.base import BaseRepository
from app.server.repositories.system_config_repository import SystemConfigRepository

logger = logging.getLogger(__name__)

POSITION_PARAM_KEY = 'position_risk_params'

# 日线读取字段
_BAR_FIELDS = {'_id': 0, 'trade_date': 1, 'open': 1, 'high': 1, 'low': 1, 'close': 1}


def _new_id(prefix: str) -> str:
    return prefix + uuid.uuid4().hex[:8]


def _now() -> datetime:
    return datetime.now()


class PositionRepository(BaseRepository):
    """账户 + 持仓 + 风控参数 + 行情读取"""

    def __init__(self):
        super().__init__('positions')
        self._accounts: Optional[BaseRepository] = None

    # ==================== 索引 ====================

    def ensure_indexes(self) -> None:
        """创建集合与索引（幂等）"""
        db = get_db()
        db['accounts'].create_index([('account_id', ASCENDING)], unique=True)
        db['positions'].create_index([('position_id', ASCENDING)], unique=True)
        db['positions'].create_index([('account_id', ASCENDING), ('status', ASCENDING)])
        db['positions'].create_index([('stock_code', ASCENDING)])

    # ==================== 账户 ====================

    @property
    def accounts(self):
        from app.data.db import get_db as _get_db
        return _get_db()['accounts']

    def create_account(self, account_name: str, initial_capital: float,
                       risk_ratio_per_trade: float) -> Dict[str, Any]:
        doc = {
            'account_id': _new_id('a'),
            'account_name': account_name.strip(),
            'initial_capital': float(initial_capital),
            'current_cash': float(initial_capital),
            'risk_ratio_per_trade': float(risk_ratio_per_trade),
            'created_at': _now(),
            'update_time': _now(),
        }
        # account_id 碰撞重试
        for _ in range(3):
            try:
                self.accounts.insert_one(dict(doc))
                break
            except DuplicateKeyError:
                doc['account_id'] = _new_id('a')
        else:
            raise RuntimeError('生成 account_id 失败，请重试')
        doc.pop('_id', None)
        return doc

    def list_accounts(self) -> List[Dict[str, Any]]:
        return list(self.accounts.find({}, {'_id': 0}).sort('created_at', ASCENDING))

    def get_account(self, account_id: str) -> Optional[Dict[str, Any]]:
        return self.accounts.find_one({'account_id': account_id}, {'_id': 0})

    def update_account(self, account_id: str, fields: Dict[str, Any]) -> bool:
        if not fields:
            return False
        fields = dict(fields)
        fields['update_time'] = _now()
        res = self.accounts.update_one({'account_id': account_id}, {'$set': fields})
        return res.matched_count > 0

    def set_primary(self, account_id: str) -> None:
        """把指定账户设为主账户（同时清除其它账户的主账户标记，保证全局唯一）"""
        self.accounts.update_many({'is_primary': True}, {'$set': {'is_primary': False}})
        self.accounts.update_one({'account_id': account_id},
                                 {'$set': {'is_primary': True, 'update_time': _now()}})

    def clear_primary(self, account_id: str) -> None:
        self.accounts.update_one({'account_id': account_id},
                                 {'$set': {'is_primary': False, 'update_time': _now()}})

    def count_accounts(self) -> int:
        return self.accounts.count_documents({})

    def delete_account(self, account_id: str) -> bool:
        res = self.accounts.delete_one({'account_id': account_id})
        return res.deleted_count > 0

    def adjust_account_cash(self, account_id: str, delta: float) -> None:
        """现金增减（建仓扣减 / 平仓加回 / 出入金）"""
        if abs(delta) < 1e-9:
            return
        self.accounts.update_one(
            {'account_id': account_id},
            {'$inc': {'current_cash': float(delta)}, '$set': {'update_time': _now()}},
        )

    # ==================== 持仓 ====================

    def create_position(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        doc = dict(doc)
        doc['position_id'] = _new_id('p')
        doc['status'] = 'OPEN'
        doc['created_at'] = _now()
        doc['last_updated'] = _now()
        doc['update_time'] = _now()
        self.collection.insert_one(dict(doc))
        doc.pop('_id', None)
        return doc

    def get_position(self, position_id: str) -> Optional[Dict[str, Any]]:
        return self.collection.find_one({'position_id': position_id}, {'_id': 0})

    def list_positions(self, account_id: Optional[str] = None,
                       status: Optional[str] = None) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {}
        if account_id:
            query['account_id'] = account_id
        if status:
            query['status'] = status
        return list(self.collection.find(query, {'_id': 0}).sort('buy_date', DESCENDING))

    def list_open_positions(self, account_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.list_positions(account_id=account_id, status='OPEN')

    def update_position(self, position_id: str, fields: Dict[str, Any]) -> bool:
        if not fields:
            return False
        fields = dict(fields)
        fields['update_time'] = _now()
        res = self.collection.update_one({'position_id': position_id}, {'$set': fields})
        return res.matched_count > 0

    def update_snapshot(self, position_id: str, snapshot: Dict[str, Any]) -> None:
        """写回最新风控快照（供列表排序/预警，不含轨迹）"""
        snapshot = dict(snapshot)
        snapshot['update_time'] = _now()
        self.collection.update_one(
            {'position_id': position_id},
            {'$set': {'snapshot': snapshot, 'last_updated': _now(), 'update_time': _now()}},
        )

    def delete_position(self, position_id: str) -> bool:
        res = self.collection.delete_one({'position_id': position_id})
        return res.deleted_count > 0

    def count_by_account(self, account_id: str, status: Optional[str] = None) -> int:
        query: Dict[str, Any] = {'account_id': account_id}
        if status:
            query['status'] = status
        return self.collection.count_documents(query)

    # ==================== 风控参数 ====================

    def get_params(self) -> Dict[str, Any]:
        return SystemConfigRepository().get_config(POSITION_PARAM_KEY, {}) or {}

    def save_params(self, params: Dict[str, Any]) -> None:
        SystemConfigRepository().set_config(POSITION_PARAM_KEY, params)

    # ==================== 行情读取（唯一允许碰日线集合的地方之一） ====================

    @staticmethod
    def _daily_collection(asset_type: str):
        return get_db()['etf_daily' if asset_type == 'etf' else 'stock_daily']

    def find_asset(self, code: str) -> Optional[Dict[str, Any]]:
        """识别代码是 stock 还是 etf，并返回名称

        Returns:
            {'asset_type': 'stock'|'etf', 'code': ..., 'name': ...}，未找到返回 None
        """
        code = (code or '').strip()
        if not code:
            return None
        db = get_db()
        etf = db['etf_basics'].find_one({'code': code}, {'_id': 0, 'code': 1, 'name': 1})
        if etf:
            return {'asset_type': 'etf', 'code': etf['code'], 'name': etf.get('name') or code}
        stock = db['stock_basics'].find_one(
            {'stock_code': code}, {'_id': 0, 'stock_code': 1, 'stock_name': 1})
        if stock:
            return {'asset_type': 'stock', 'code': stock['stock_code'],
                    'name': stock.get('stock_name') or code}
        # basics 缺失时退化为按日线集合探测
        if db['etf_daily'].find_one({'stock_code': code}, {'_id': 1}):
            return {'asset_type': 'etf', 'code': code, 'name': code}
        if db['stock_daily'].find_one({'stock_code': code}, {'_id': 1}):
            return {'asset_type': 'stock', 'code': code, 'name': code}
        return None

    def get_bars(self, code: str, asset_type: str, start_date: Optional[str] = None,
                 end_date: Optional[str] = None, limit: int = 0) -> List[Dict[str, Any]]:
        """读取日线（按 trade_date 升序）"""
        coll = self._daily_collection(asset_type)
        query: Dict[str, Any] = {'stock_code': code, 'close': {'$gt': 0}}
        rng: Dict[str, str] = {}
        if start_date:
            rng['$gte'] = str(start_date)
        if end_date:
            rng['$lte'] = str(end_date)
        if rng:
            query['trade_date'] = rng

        if limit and limit > 0:
            docs = list(coll.find(query, _BAR_FIELDS).sort('trade_date', DESCENDING).limit(limit))
            docs.reverse()
            return docs
        return list(coll.find(query, _BAR_FIELDS).sort('trade_date', ASCENDING))

    def get_bar(self, code: str, asset_type: str, trade_date: str) -> Optional[Dict[str, Any]]:
        return self._daily_collection(asset_type).find_one(
            {'stock_code': code, 'trade_date': str(trade_date), 'close': {'$gt': 0}}, _BAR_FIELDS)

    def get_latest_bar(self, code: str, asset_type: str) -> Optional[Dict[str, Any]]:
        return self._daily_collection(asset_type).find_one(
            {'stock_code': code, 'close': {'$gt': 0}},
            _BAR_FIELDS, sort=[('trade_date', DESCENDING)])

    def get_latest_bars(self, codes: List[str], asset_type: str) -> Dict[str, Dict[str, Any]]:
        """批量取多只标的最新一根日线 → {code: bar}"""
        if not codes:
            return {}
        coll = self._daily_collection(asset_type)
        out: Dict[str, Dict[str, Any]] = {}
        for doc in coll.aggregate([
            {'$match': {'stock_code': {'$in': list(codes)}, 'close': {'$gt': 0}}},
            {'$sort': {'stock_code': 1, 'trade_date': -1}},
            {'$group': {'_id': '$stock_code', 'doc': {'$first': '$$ROOT'}}},
        ]):
            bar = doc['doc']
            bar.pop('_id', None)
            out[doc['_id']] = bar
        return out

    def get_latest_bar_before(self, code: str, asset_type: str,
                              trade_date: str) -> Optional[Dict[str, Any]]:
        """取严格早于 trade_date 的最后一根日线（建仓日行情未同步时的锚点回退）"""
        return self._daily_collection(asset_type).find_one(
            {'stock_code': code, 'trade_date': {'$lt': str(trade_date)}, 'close': {'$gt': 0}},
            _BAR_FIELDS, sort=[('trade_date', DESCENDING)])

    def get_market_latest_date(self, asset_type: str) -> Optional[str]:
        """该日线集合里全市场最新交易日（判断某只票是否已同步到最新）"""
        doc = self._daily_collection(asset_type).find_one(
            {'close': {'$gt': 0}}, sort=[('trade_date', DESCENDING)],
            projection={'trade_date': 1, '_id': 0})
        return doc['trade_date'] if doc else None

    def get_trade_dates(self, code: str, asset_type: str,
                        start_date: str, end_date: Optional[str] = None) -> List[str]:
        """取某标的在区间内的交易日序列（用于校验买入日是否为交易日）"""
        query: Dict[str, Any] = {'stock_code': code, 'trade_date': {'$gte': str(start_date)}}
        if end_date:
            query['trade_date']['$lte'] = str(end_date)
        return list(self._daily_collection(asset_type).distinct('trade_date', query))

    def get_bar_ranges(self, codes: List[str], asset_type: str) -> Dict[str, Dict[str, Any]]:
        """批量取多个标的的日线区间信息 → {code: {'first','last','count'}}

        用于「刷新监控」前判断该标的是否已有日线基础数据（无 / 不足 / 过旧）。
        """
        if not codes:
            return {}
        coll = self._daily_collection(asset_type)
        out: Dict[str, Dict[str, Any]] = {}
        for doc in coll.aggregate([
            {'$match': {'stock_code': {'$in': list(codes)}, 'close': {'$gt': 0}}},
            {'$group': {
                '_id': '$stock_code',
                'first': {'$min': '$trade_date'},
                'last': {'$max': '$trade_date'},
                'count': {'$sum': 1},
            }},
        ]):
            out[doc['_id']] = {'first': doc.get('first'), 'last': doc.get('last'),
                               'count': doc.get('count', 0)}
        return out


class AccountRepository(BaseRepository):
    """账户集合（独立出来便于扩展，实际读写走 PositionRepository）"""

    def __init__(self):
        super().__init__('accounts')
