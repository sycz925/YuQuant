"""
ENE 轨道线预警引擎（仅击穿ENE下轨）

ENE(10,11,9):
  - MA10 = 10日收盘价均线
  - UPPER = MA10 * 1.11
  - LOWER = MA10 * 0.91
  - 击穿预警: close < LOWER

自动前复权：从价格数据中检测除权除息跳空，计算复权因子并调整历史价格，
          确保 MA10 和 ENE 下轨计算不受除权影响。
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict

import numpy as np
from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)

BJ_TZ = timezone(timedelta(hours=8))
ALERT_COLL = 'etf_alerts'
ENE_N = 10
ENE_P1 = 11
ENE_P2 = 9
XDXR_THRESHOLD = 0.15  # 开盘价/昨收偏离 >15% 视为除权
REASON_ENE = '击穿ENE下轨'


def _now_bj() -> datetime:
    return datetime.now(BJ_TZ)


def _trade_date_close_time(trade_date: str) -> datetime:
    """将交易日字符串转为该日收盘时刻(15:00 北京时间)。

    回刷历史预警用此时间作为 created_at，避免历史击穿在 /recent 推送中被当作"新预警"。
    """
    try:
        return datetime.strptime(trade_date, '%Y%m%d').replace(hour=15, minute=0, second=0, tzinfo=BJ_TZ)
    except Exception:
        return _now_bj()


def _forward_adjust_closes(docs: List[Dict]) -> tuple:
    """从原始日线 detect 除权跳空，返回(前复权close数组, 最近除权索引)

    前复权（从最新往最旧扫描）：
      - 最新一天 close 不变（基准）
      - 往前遇到除权日时，将当天之前的 close 除以复权系数
      - factor = prev_close / open
    返回 (closes, newest_xdxr_idx)；最近 10 日内有除权时最后一项 > -1
    """
    n = len(docs)
    closes = np.array([d['close'] for d in docs], dtype=float)
    if n < 2:
        return closes, -1

    # 数据已在同步层做过前复权（有 close_raw 字段）→ 从 close vs close_raw 推断除权边界
    if 'close_raw' in docs[-1]:
        newest_xdxr_idx = -1
        for i in range(n - 1, 0, -1):
            cr = docs[i].get('close_raw')
            if cr is not None and abs(docs[i]['close'] / cr - 1) < 0.001:
                continue
            newest_xdxr_idx = i + 1
            break
        return closes, newest_xdxr_idx

    cum_factor = 1.0
    xdxr_boundaries = []
    for i in range(n - 1, 0, -1):
        prev_close = closes[i - 1]
        curr_open = docs[i].get('open', docs[i]['close'])
        if prev_close <= 0 or curr_open <= 0:
            continue
        gap = abs(curr_open / prev_close - 1)
        if gap > XDXR_THRESHOLD:
            factor = prev_close / curr_open
            cum_factor *= factor
            xdxr_boundaries.append((i, cum_factor))
            logger.debug(f'  xdxr {docs[i]["trade_date"]}: '
                         f'prev_close={prev_close:.4f} open={curr_open:.4f} '
                         f'factor={factor:.4f} cum={cum_factor:.4f}')

    newest_xdxr_idx = xdxr_boundaries[0][0] if xdxr_boundaries else -1

    if not xdxr_boundaries:
        return closes, -1

    xdxr_boundaries.reverse()
    prev_idx = 0
    for idx, factor in xdxr_boundaries:
        if prev_idx < idx:
            closes[prev_idx:idx] /= factor
        prev_idx = idx
    return closes, newest_xdxr_idx


def _check_one_etf(code: str, docs: list, name_map: dict, alert_coll) -> int:
    """计算单只ETF所有可用日期的ENE，插入新预警，返回新增数"""
    if len(docs) < ENE_N:
        return 0

    dates = [d['trade_date'] for d in docs]
    closes, newest_xdxr_idx = _forward_adjust_closes(docs)
    n = len(docs)
    name = name_map.get(code, code)
    new_count = 0

    for i in range(ENE_N - 1, n):
        if newest_xdxr_idx > i - ENE_N:
            trade_date = dates[i]
            logger.debug(f'[ENE跳过] {code} {trade_date} MA10窗口内含除权')
            continue
        ma10 = round(float(np.mean(closes[i - ENE_N + 1:i + 1])), 4)
        lower = round(ma10 * (1 - ENE_P2 / 100), 4)
        close = round(float(closes[i]), 4)
        if close >= lower:
            continue
        trade_date = dates[i]
        existing = alert_coll.find_one({'code': code, 'trade_date': trade_date})
        if existing:
            continue
        upper = round(ma10 * (1 + ENE_P1 / 100), 4)
        orig_close = docs[i]['close']
        try:
            alert_coll.insert_one({
                'code': code,
                'name': name,
                'trade_date': trade_date,
                'close': close,
                'close_raw': orig_close,
                'amount': docs[i].get('amount', 0) or 0,
                'ene_ma': ma10,
                'ene_upper': upper,
                'ene_lower': lower,
                'reason': '击穿ENE下轨',
                'created_at': _trade_date_close_time(trade_date),
            })
            new_count += 1
            logger.info(f'[ENE预警] {code} {trade_date} 击穿下轨: '
                        f'close(adj)={close} < lower={lower}')
        except DuplicateKeyError:
            pass

    return new_count


def backfill_alerts() -> int:
    """回刷所有ETF所有历史日期的ENE击穿，返回总新增数"""
    from app.data.db import get_db, get_collection
    db = get_db()
    etf_coll = get_collection('etf')
    alert_coll = db[ALERT_COLL]
    basics_coll = db['etf_basics']

    codes = etf_coll.distinct('stock_code')
    name_map = {d['code']: d['name'] for d in basics_coll.find({}, {'code': 1, 'name': 1})}

    total_new = 0
    for code in codes:
        try:
            docs = list(etf_coll.find(
                {'stock_code': code, 'close': {'$gt': 0}},
                {'_id': 0, 'trade_date': 1, 'close': 1, 'open': 1, 'close_raw': 1, 'amount': 1}
            ).sort('trade_date', ASCENDING))
            new_count = _check_one_etf(code, docs, name_map, alert_coll)
            if new_count:
                logger.info(f'[ENE回刷] {code} 新增{new_count}条预警')
            total_new += new_count
        except Exception as e:
            logger.error(f'[ENE回刷] 处理{code}失败: {e}')

    logger.info(f'[ENE回刷] 完成，总新增{total_new}条预警')
    return total_new


def check_latest(max_dates: int = 5) -> int:
    """检查所有ETF最近N个交易日（击穿ENE下轨），返回新增预警数"""
    from app.data.db import get_db, get_collection
    db = get_db()
    etf_coll = get_collection('etf')
    alert_coll = db[ALERT_COLL]
    basics_coll = db['etf_basics']

    codes = etf_coll.distinct('stock_code')
    name_map = {d['code']: d['name'] for d in basics_coll.find({}, {'code': 1, 'name': 1})}

    new_count = 0
    for code in codes:
        try:
            raw_docs = list(etf_coll.find(
                {'stock_code': code, 'close': {'$gt': 0}},
                {'_id': 0, 'trade_date': 1, 'close': 1, 'open': 1, 'close_raw': 1, 'amount': 1, 'chg_pct': 1}
            ).sort('trade_date', -1).limit(ENE_N + max_dates + 5))
            if len(raw_docs) < ENE_N:
                continue
            raw_docs.reverse()
            dates = [d['trade_date'] for d in raw_docs]
            closes, newest_xdxr_idx = _forward_adjust_closes(raw_docs)
            n = len(raw_docs)
            name = name_map.get(code, code)

            for offset in range(max_dates):
                i = n - 1 - offset
                if i < ENE_N - 1:
                    break
                if newest_xdxr_idx > i - ENE_N:
                    continue
                trade_date = dates[i]
                close = round(float(closes[i]), 4)
                doc = raw_docs[i]

                # 击穿ENE下轨
                ma10 = round(float(np.mean(closes[i - ENE_N + 1:i + 1])), 4)
                lower = round(ma10 * (1 - ENE_P2 / 100), 4)
                if close < lower:
                    existing = alert_coll.find_one({'code': code, 'trade_date': trade_date, 'reason': REASON_ENE})
                    if not existing:
                        upper = round(ma10 * (1 + ENE_P1 / 100), 4)
                        try:
                            alert_coll.insert_one({
                                'code': code,
                                'name': name,
                                'trade_date': trade_date,
                                'close': close,
                                'close_raw': doc['close'],
                                'amount': doc.get('amount', 0) or 0,
                                'chg_pct': doc.get('chg_pct'),
                                'ene_ma': ma10,
                                'ene_upper': upper,
                                'ene_lower': lower,
                                'reason': REASON_ENE,
                                'created_at': _now_bj(),
                            })
                            new_count += 1
                            logger.info(f'[ENE预警] {code} {trade_date} 击穿下轨: '
                                        f'close(adj)={close} < lower={lower}')
                        except DuplicateKeyError:
                            pass
        except Exception as e:
            logger.error(f'[ENE预警] 检查{code}失败: {e}')

    if new_count:
        logger.info(f'[ENE预警] 本轮新增{new_count}条预警')
    return new_count


def get_recent_alerts(since: Optional[datetime] = None, limit: int = 20) -> list:
    """获取最近的预警（用于前端轮询推送）"""
    from app.data.db import get_db
    coll = get_db()[ALERT_COLL]
    query = {}
    if since:
        query['created_at'] = {'$gt': since}
    else:
        query['created_at'] = {'$gt': _now_bj() - timedelta(hours=1)}
    return list(coll.find(query, {'_id': 0}).sort('created_at', -1).limit(limit))


def get_alerts(start_date: str = None, end_date: str = None,
               page: int = 1, page_size: int = 50) -> dict:
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
