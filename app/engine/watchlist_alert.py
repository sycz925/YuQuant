"""
重点关注列表均线预警引擎

规则（首次跌破/穿越才触发，幂等）：
  - 跌破5日均线:   close < ma5 且 前一日 close >= 前一日 ma5
  - 跌破10日均线:  close < ma10 且 前一日 close >= 前一日 ma10
  - 跌破20日均线:  close < ma20 且 前一日 close >= 前一日 ma20
  - 5日均线上穿10日均线: ma5 > ma10 且 前一日 ma5 <= 前一日 ma10

stock_daily/etf_daily 仅冗余了 ma10/ma20/ma50/ma120，ma5 需现场计算。
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List

from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)

BJ_TZ = timezone(timedelta(hours=8))
ALERT_COLL = 'watchlist_alerts'
MA5_N = 5


def _now_bj() -> datetime:
    return datetime.now(BJ_TZ)


def _trade_date_close_time(trade_date: str) -> datetime:
    """将交易日字符串转为该日收盘时刻(15:00 北京时间)作为 created_at"""
    try:
        return datetime.strptime(trade_date, '%Y%m%d').replace(hour=15, minute=0, second=0, tzinfo=BJ_TZ)
    except Exception:
        return _now_bj()


def _resolve_name(code: str, typ: str, db) -> str:
    if typ == 'etf':
        basic = db['etf_basics'].find_one({'code': code}, {'_id': 0, 'name': 1})
        return basic['name'] if basic else code
    basic = db['stock_basics'].find_one({'stock_code': code}, {'_id': 0, 'stock_name': 1})
    return basic['stock_name'] if basic else code


def _ma(closes: List[float], period: int, idx: int) -> Optional[float]:
    window = closes[idx - period + 1: idx + 1]
    if len(window) < period:
        return None
    return round(sum(window) / period, 4)


def _check_one(code: str, typ: str, docs: list, name: str, alert_coll, max_dates: int = 1) -> int:
    """计算单只标的最近 max_dates 个交易日的均线预警，插入新预警，返回新增数

    docs 为升序（docs[-1] 最新）。逐日判断"首次跌破/穿越"（当日与前一日比较）。
    """
    if len(docs) < 2:
        return 0

    closes = [d.get('close') or 0 for d in docs]
    n = len(docs)
    start = max(1, n - max_dates)
    new_count = 0

    for i in range(start, n):
        if closes[i] <= 0 or closes[i - 1] <= 0:
            continue
        cur_close = closes[i]
        prev_close = closes[i - 1]

        cur_ma5 = _ma(closes, 5, i)
        prev_ma5 = _ma(closes, 5, i - 1)
        cur_ma10 = _ma(closes, 10, i)
        prev_ma10 = _ma(closes, 10, i - 1)
        cur_ma20 = _ma(closes, 20, i)
        prev_ma20 = _ma(closes, 20, i - 1)

        conditions = []
        if cur_ma5 is not None and prev_ma5 is not None:
            if cur_close < cur_ma5 and prev_close >= prev_ma5:
                conditions.append('跌破5日均线')
        if cur_ma10 is not None and prev_ma10 is not None:
            if cur_close < cur_ma10 and prev_close >= prev_ma10:
                conditions.append('跌破10日均线')
        if cur_ma20 is not None and prev_ma20 is not None:
            if cur_close < cur_ma20 and prev_close >= prev_ma20:
                conditions.append('跌破20日均线')
        if (cur_ma5 is not None and prev_ma5 is not None
                and cur_ma10 is not None and prev_ma10 is not None):
            if cur_ma5 > cur_ma10 and prev_ma5 <= prev_ma10:
                conditions.append('5日均线上穿10日均线')

        if not conditions:
            continue

        trade_date = docs[i]['trade_date']
        for reason in conditions:
            try:
                alert_coll.insert_one({
                    'code': code,
                    'name': name,
                    'type': typ,
                    'trade_date': trade_date,
                    'close': cur_close,
                    'chg_pct': docs[i].get('chg_pct'),
                    'reason': reason,
                    'created_at': _trade_date_close_time(trade_date),
                })
                new_count += 1
                logger.info(f'[Watchlist预警] {code} {trade_date} {reason} close={cur_close}')
            except DuplicateKeyError:
                pass

    return new_count


def check_latest(max_dates: int = 1) -> int:
    """扫描重点关注列表全部标的最近 max_dates 个交易日，返回新增预警数"""
    from app.data.db import get_db
    db = get_db()
    alert_coll = db[ALERT_COLL]
    entries = list(db['watchlist'].find({}, {'_id': 0, 'code': 1, 'type': 1}).sort('created_at', 1))

    limit = max_dates + 20
    total_new = 0
    for e in entries:
        code = e['code']
        typ = e.get('type', 'stock')
        name = _resolve_name(code, typ, db)
        try:
            coll = db['etf_daily'] if typ == 'etf' else db['stock_daily']
            docs = list(coll.find(
                {'stock_code': code, 'close': {'$gt': 0}},
                {'_id': 0, 'trade_date': 1, 'close': 1, 'chg_pct': 1}
            ).sort('trade_date', -1).limit(limit))
            docs.reverse()
            new_count = _check_one(code, typ, docs, name, alert_coll, max_dates)
            total_new += new_count
        except Exception as ex:
            logger.error(f'[Watchlist预警] 检查{code}失败: {ex}')

    logger.info(f'[Watchlist预警] 检查完成，新增{total_new}条')
    return total_new


def get_alerts(start_date: Optional[str] = None, end_date: Optional[str] = None,
               page: int = 1, page_size: int = 50) -> Dict:
    """分页查询预警记录"""
    from app.data.db import get_db
    coll = get_db()[ALERT_COLL]
    query = {}
    date_query = {}
    if start_date:
        date_query['$gte'] = start_date
    if end_date:
        date_query['$lte'] = end_date
    if date_query:
        query['trade_date'] = date_query
    total = coll.count_documents(query)
    items = list(coll.find(query, {'_id': 0})
                 .sort('trade_date', -1)
                 .skip((page - 1) * page_size)
                 .limit(page_size))
    return {'total': total, 'page': page, 'page_size': page_size, 'items': items}
