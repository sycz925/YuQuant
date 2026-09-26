"""
重点关注列表预警引擎（统一4种触发条件）

规则（首次跌破才触发，幂等）：
  1. 跌破10日均线且量能 < MIN(vol5, vol20)
  2. 跌破20日均线且量能 < MIN(vol5, vol20)
  3. 跌破50日均线且量能 < MIN(vol5, vol20)
  4. 击穿ENE下轨（close < MA10 × 0.91）

自动前复权：从价格数据中检测除权除息跳空，计算复权因子并调整历史价格。
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Tuple

import numpy as np
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)

BJ_TZ = timezone(timedelta(hours=8))
ALERT_COLL = 'watchlist_alerts'
ENE_N = 10
ENE_P1 = 11
ENE_P2 = 9
XDXR_THRESHOLD = 0.15  # 开盘价/昨收偏离 >15% 视为除权

REASON_MA10 = '跌破10日均线'
REASON_MA20 = '跌破20日均线'
REASON_MA50 = '跌破50日均线'
REASON_ENE = '击穿ENE下轨'


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


def _forward_adjust_closes(docs: List[Dict]) -> Tuple[np.ndarray, int]:
    """从原始日线 detect 除权跳空，返回(前复权close数组, 最近除权索引)

    前复权（从最新往最旧扫描）：
      - 最新一天 close 不变（基准）
      - 往前遇到除权日时，将当天之前的 close 除以复权系数
    返回 (closes, newest_xdxr_idx)；最近 ENE_N 日内有除权时最后一项 > -1
    """
    n = len(docs)
    closes = np.array([d.get('close', 0) or 0 for d in docs], dtype=float)
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


def _check_one(code: str, typ: str, docs: list, name: str, alert_coll, max_dates: int = 1) -> int:
    """计算单只标的最近 max_dates 个交易日的预警，插入新预警，返回新增数

    规则（首次跌破才触发）：
      1. 跌破10日均线且量能 < MIN(vol5, vol20)
      2. 跌破20日均线且量能 < MIN(vol5, vol20)
      3. 跌破50日均线且量能 < MIN(vol5, vol20)
      4. 击穿ENE下轨

    docs 为升序（docs[-1] 最新）。
    """
    if len(docs) < max(ENE_N, 50) + 1:
        return 0

    dates = [d['trade_date'] for d in docs]
    closes, newest_xdxr_idx = _forward_adjust_closes(docs)
    n = len(docs)
    start = max(1, n - max_dates)
    new_count = 0

    for i in range(start, n):
        if closes[i] <= 0 or closes[i - 1] <= 0:
            continue

        trade_date = dates[i]
        cur_close = closes[i]
        prev_close = closes[i - 1]
        doc = docs[i]

        # 获取成交量数据
        cur_vol = doc.get('vol', 0) or 0
        cur_vol_ma5 = doc.get('vol_ma5', 0) or 0
        cur_vol_ma20 = doc.get('vol_ma20', 0) or 0

        # 跳过除权窗口内的日期（ENE计算）
        skip_ene = newest_xdxr_idx > i - ENE_N

        conditions = []

        # 规则1-3：跌破均线（10/20/50日）且量能 < MIN(vol5, vol20)
        for ma_period, reason in [(10, REASON_MA10), (20, REASON_MA20), (50, REASON_MA50)]:
            cur_ma = _ma(closes, ma_period, i)
            prev_ma = _ma(closes, ma_period, i - 1)
            if cur_ma is None or prev_ma is None:
                continue
            # 首次跌破：前一日在均线上方，当日跌破
            if prev_close >= prev_ma and cur_close < cur_ma:
                # 量能条件：当日成交量 < MIN(vol5, vol20)
                vol_min = min(cur_vol_ma5, cur_vol_ma20) if cur_vol_ma5 > 0 and cur_vol_ma20 > 0 else 0
                if vol_min > 0 and cur_vol < vol_min:
                    conditions.append((reason, ma_period, cur_vol, vol_min))

        # 规则4：击穿ENE下轨
        if not skip_ene:
            ma10 = _ma(closes, ENE_N, i)
            if ma10 is not None:
                lower = round(ma10 * (1 - ENE_P2 / 100), 4)
                if cur_close < lower:
                    upper = round(ma10 * (1 + ENE_P1 / 100), 4)
                    conditions.append((REASON_ENE, None, None, None))
                    # 保存ENE信息
                    ene_info = {'ene_ma': ma10, 'ene_upper': upper, 'ene_lower': lower}

        if not conditions:
            continue

        for reason, ma_period, cur_vol_val, vol_min_val in conditions:
            # 检查是否已存在相同预警
            existing = alert_coll.find_one({'code': code, 'trade_date': trade_date, 'reason': reason})
            if existing:
                continue

            try:
                alert_doc = {
                    'code': code,
                    'name': name,
                    'type': typ,
                    'trade_date': trade_date,
                    'close': round(float(cur_close), 4),
                    'close_raw': doc.get('close'),
                    'chg_pct': doc.get('chg_pct'),
                    'reason': reason,
                    'created_at': _trade_date_close_time(trade_date),
                }
                # 跌破均线时记录成交量信息
                if ma_period is not None:
                    alert_doc['ma_period'] = ma_period
                    alert_doc['vol'] = cur_vol_val
                    alert_doc['vol_min'] = vol_min_val
                # ENE预警记录ENE信息
                if reason == REASON_ENE:
                    alert_doc.update(ene_info)

                alert_coll.insert_one(alert_doc)
                new_count += 1
                logger.info(f'[Watchlist预警] {code} {trade_date} {reason} close={cur_close}')
            except DuplicateKeyError:
                pass

    return new_count


def check_latest(max_dates: int = 1) -> Dict:
    """扫描重点关注列表全部标的最近 max_dates 个交易日，返回新增预警数和各标的TDX状态"""
    from app.data.db import get_db
    db = get_db()
    alert_coll = db[ALERT_COLL]
    entries = list(db['watchlist'].find({}, {'_id': 0, 'code': 1, 'type': 1}).sort('created_at', 1))

    # 需要足够的历史数据计算MA50和前复权
    limit = max_dates + 60
    total_new = 0
    statuses = {}
    for e in entries:
        code = e['code']
        typ = e.get('type', 'stock')
        name = _resolve_name(code, typ, db)
        try:
            coll = db['etf_daily'] if typ == 'etf' else db['stock_daily']
            docs = list(coll.find(
                {'stock_code': code, 'close': {'$gt': 0}},
                {'_id': 0, 'trade_date': 1, 'close': 1, 'open': 1, 'close_raw': 1,
                 'chg_pct': 1, 'vol': 1, 'vol_ma5': 1, 'vol_ma20': 1}
            ).sort('trade_date', -1).limit(limit))
            docs.reverse()
            new_count = _check_one(code, typ, docs, name, alert_coll, max_dates)
            total_new += new_count
            daily_status = get_tdx_status(code, typ)
            weekly_status = get_weekly_tdx_status(code, typ)
            status_text = f'日{daily_status}周{weekly_status}'
            statuses[code] = status_text
            db['watchlist'].update_one({'code': code}, {'$set': {'tdx_status': status_text}})
        except Exception as ex:
            logger.error(f'[Watchlist预警] 检查{code}失败: {ex}')
            statuses[code] = '日蓝周蓝'

    logger.info(f'[Watchlist预警] 检查完成，新增{total_new}条')
    return {'new_alerts': total_new, 'statuses': statuses}


def get_tdx_status(code: str, typ: str) -> str:
    """根据最新日线数据计算通达信MA7变色线状态：红/绿/蓝"""
    from app.data.db import get_db
    db = get_db()
    coll = db['etf_daily'] if typ == 'etf' else db['stock_daily']
    docs = list(coll.find(
        {'stock_code': code, 'close': {'$gt': 0}},
        {'_id': 0, 'trade_date': 1, 'close': 1}
    ).sort('trade_date', -1).limit(30))
    if len(docs) < 22:
        return '蓝'
    docs.reverse()
    closes = [d['close'] for d in docs]
    return _calc_tdx_status(closes)


def get_weekly_tdx_status(code: str, typ: str) -> str:
    """根据最新周线数据计算通达信MA7变色线状态：红/绿/蓝"""
    from app.data.db import get_db
    from datetime import datetime
    db = get_db()
    coll = db['etf_daily'] if typ == 'etf' else db['stock_daily']
    docs = list(coll.find(
        {'stock_code': code, 'close': {'$gt': 0}},
        {'_id': 0, 'trade_date': 1, 'close': 1}
    ).sort('trade_date', -1).limit(150))
    if len(docs) < 50:
        return '蓝'
    docs.reverse()

    # 日线转周线：按ISO周分组，取每周最后一个交易日的收盘价
    weekly = {}
    for d in docs:
        td = d['trade_date']
        dt = datetime.strptime(td, '%Y%m%d')
        year, week, _ = dt.isocalendar()
        key = f'{year}-W{week:02d}'
        weekly[key] = d['close']

    closes = list(weekly.values())
    if len(closes) < 22:
        return '蓝'
    return _calc_tdx_status(closes)


def _calc_tdx_status(closes: list) -> str:
    """根据收盘价序列计算通达信MA7变色线状态：红/绿/蓝
    
    规则：
    - 红：EMA7↑ 且 EMA21↑ 且 MACD↑（不能卖/观望/能买）
    - 绿：(EMA7↓ 或 EMA21↓) 且 MACD↓（不能买/观望/能卖）
    - 蓝：其他情况（观望/能买/能卖）
    """
    def ema(arr, period):
        k = 2 / (period + 1)
        prev = arr[0]
        res = [prev]
        for i in range(1, len(arr)):
            prev = arr[i] * k + prev * (1 - k)
            res.append(prev)
        return res

    emad = ema(closes, 7)
    emac = ema(closes, 14)

    ema_fast = ema(closes, 12)
    ema_slow = ema(closes, 26)
    dif = [f - s for f, s in zip(ema_fast, ema_slow)]
    dea = ema(dif, 9)
    macd_arr = [(d - de) * 2 for d, de in zip(dif, dea)]

    n = len(closes)
    cur, prev = n - 1, n - 2
    emad_up = emad[cur] > emad[prev]
    emac_up = emac[cur] > emac[prev]
    macd_up = macd_arr[cur] > macd_arr[prev]

    kd = emad_up and emac_up and macd_up
    kk = (not emad_up or not emac_up) and not macd_up
    if kd:
        return '红'
    elif kk:
        return '绿'
    return '蓝'


def get_index_tdx_status(code: str, trade_date: str = None) -> str:
    """根据指数日线数据计算通达信MA7变色线状态：日X周X
    Args:
        code: 指数代码
        trade_date: 指定日期（可选），不传则取最新数据
    """
    from app.data.db import get_db
    from datetime import datetime
    db = get_db()

    # 构建查询条件
    query = {'stock_code': code, 'close': {'$gt': 0}}
    if trade_date:
        query['trade_date'] = {'$lte': trade_date}

    # 日线状态
    docs = list(db['index_daily'].find(
        query,
        {'_id': 0, 'trade_date': 1, 'close': 1}
    ).sort('trade_date', -1).limit(30))
    if len(docs) < 22:
        daily_status = '蓝'
    else:
        docs.reverse()
        closes = [d['close'] for d in docs]
        daily_status = _calc_tdx_status(closes)

    # 周线状态
    query_all = {'stock_code': code, 'close': {'$gt': 0}}
    if trade_date:
        query_all['trade_date'] = {'$lte': trade_date}
    docs_all = list(db['index_daily'].find(
        query_all,
        {'_id': 0, 'trade_date': 1, 'close': 1}
    ).sort('trade_date', -1).limit(150))
    if len(docs_all) < 50:
        weekly_status = '蓝'
    else:
        docs_all.reverse()
        weekly = {}
        for d in docs_all:
            td = d['trade_date']
            dt = datetime.strptime(td, '%Y%m%d')
            year, week, _ = dt.isocalendar()
            key = f'{year}-W{week:02d}'
            weekly[key] = d['close']
        closes_weekly = list(weekly.values())
        if len(closes_weekly) < 22:
            weekly_status = '蓝'
        else:
            weekly_status = _calc_tdx_status(closes_weekly)

    return f'日{daily_status}周{weekly_status}'


def delete_alerts(code: str) -> int:
    """删除指定代码的全部均线预警记录（配合移除关注列表），返回删除数"""
    from app.data.db import get_db
    return get_db()[ALERT_COLL].delete_many({'code': code}).deleted_count


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
