"""
板块分析服务
提供新高板块聚类、低位潜力板块、异动活跃板块分析
从 api/market_review.py 迁移而来
"""
import math
import logging
from collections import defaultdict, Counter
from datetime import datetime as _dt, timedelta
from typing import Dict, Any, List, Optional

from app.data.db import get_db
from app.server.services.market_data import get_latest_trade_date

logger = logging.getLogger(__name__)


def analyze_new_high_blocks(latest_date: Optional[str] = None) -> Dict[str, Any]:
    """
    新高强力板块分析与板块效应聚类

    筛选规则：
    1. 板块筛选：RPS10+RPS20+RPS50 > 250（三者之和）
    2. 个股筛选：当日收盘价 >= 历史最高收盘价 * 0.9（接近新高）

    返回: 接近新高股池 + 行业聚类Top5（先锋/中军/后排）
    """
    db = get_db()

    if not latest_date:
        latest_date = get_latest_trade_date(db)
    if not latest_date:
        return {'success': False, 'message': '无交易数据'}

    today_docs = list(db['stock_daily'].find(
        {'trade_date': latest_date, 'close': {'$gt': 0}},
        {'_id': 0, 'stock_code': 1, 'close': 1, 'chg_pct': 1, 'chg_20d': 1, 'chg_50d': 1, 'amount': 1}
    ))
    if not today_docs:
        return {'success': False, 'message': '今日无交易数据'}

    today_map = {d['stock_code']: d for d in today_docs}
    stock_codes = list(today_map.keys())

    try:
        date_obj = _dt.strptime(latest_date, '%Y%m%d')
        hist_start = (date_obj - timedelta(days=365)).strftime('%Y%m%d')
    except Exception:
        hist_start = latest_date

    high_cursor = db['stock_daily'].aggregate([
        {'$match': {
            'stock_code': {'$in': stock_codes},
            'trade_date': {'$gte': hist_start},
            'close': {'$gt': 0}
        }},
        {'$group': {'_id': '$stock_code', 'max_close': {'$max': '$close'}}}
    ])
    hist_max = {d['_id']: d['max_close'] for d in high_cursor}

    new_high_stocks = []
    for code, doc in today_map.items():
        close = doc['close']
        max_close = hist_max.get(code, 0)
        if max_close > 0 and close >= max_close * 0.9:
            new_high_stocks.append({'code': code, 'close': close})

    total_new_high_count = len(new_high_stocks)
    if total_new_high_count == 0:
        return {
            'success': True,
            'trade_date': latest_date,
            'total_new_high_count': 0,
            'industry_clusters': [],
            'interpretation': '今日无创新高个股。'
        }

    new_high_codes = {s['code'] for s in new_high_stocks}

    enabled_sector_docs = list(db['sector_basics'].find(
        {'is_disable': {'$ne': True}, 'stock_count': {'$gt': 0}},
        {'_id': 0, 'code': 1, 'name': 1, 'stock_codes': 1}
    ))
    enabled_sector_codes = {doc['code'] for doc in enabled_sector_docs}

    sector_rps_cursor = db['sector_daily'].find(
        {
            'trade_date': latest_date,
            'stock_code': {'$in': list(enabled_sector_codes)},
        },
        {'_id': 0, 'stock_code': 1, 'rps_10': 1, 'rps_20': 1, 'rps_50': 1}
    )
    strong_sector_rps = {}
    for doc in sector_rps_cursor:
        rps_10 = doc.get('rps_10', 0) or 0
        rps_20 = doc.get('rps_20', 0) or 0
        rps_50 = doc.get('rps_50', 0) or 0
        rps_sum = rps_10 + rps_20 + rps_50
        if rps_sum > 250:
            strong_sector_rps[doc['stock_code']] = {
                'rps_10': rps_10,
                'rps_20': rps_20,
                'rps_50': rps_50,
                'rps_sum': rps_sum,
            }

    sector_info_map = {}
    for doc in enabled_sector_docs:
        sector_info_map[doc['code']] = doc

    sector_new_high = {}
    for s in new_high_stocks:
        code = s['code']
        for sector_code in strong_sector_rps:
            sector_info = sector_info_map.get(sector_code, {})
            stock_codes_in_sector = set(sector_info.get('stock_codes', []))
            if code in stock_codes_in_sector:
                if sector_code not in sector_new_high:
                    sector_new_high[sector_code] = []
                sector_new_high[sector_code].append(s)

    sorted_sectors = sorted(sector_new_high.items(), key=lambda x: -len(x[1]))[:5]

    if total_new_high_count == 0 or not sorted_sectors:
        return {
            'success': True,
            'trade_date': latest_date,
            'total_new_high_count': 0,
            'industry_clusters': [],
            'interpretation': '今日强劲板块（RPS>90）无创新高个股。'
        }

    name_cursor = db['stock_basics'].find(
        {'is_disable': {'$ne': True}}, {'_id': 0, 'stock_code': 1, 'stock_name': 1}
    )
    name_map = {d['stock_code']: d.get('stock_name', '') for d in name_cursor}

    liutong_cursor = db['stock_basics'].find(
        {'is_disable': {'$ne': True}, 'liutongguben': {'$gt': 0}},
        {'_id': 0, 'stock_code': 1, 'liutongguben': 1}
    )
    liutong_map = {d['stock_code']: d.get('liutongguben', 0) for d in liutong_cursor}

    for s in new_high_stocks:
        today_doc = today_map.get(s['code'], {})
        s['pct_chg'] = today_doc.get('chg_pct', 0) or 0
        s['chg_pct'] = s['pct_chg']
        s['chg_20d'] = today_doc.get('chg_20d', 0) or 0
        s['chg_50d'] = today_doc.get('chg_50d', 0) or 0
        amount = today_doc.get('amount', 0)
        s['amount'] = 0 if amount is None or math.isnan(amount) else amount
        s['name'] = name_map.get(s['code'], s['code'])

    clusters = []
    for sector_code, stocks in sorted_sectors:
        sector_info = sector_info_map.get(sector_code, {})
        sector_name = sector_info.get('name', sector_code)
        rps_data = strong_sector_rps.get(sector_code, {})
        count = len(stocks)
        pct = round(count / total_new_high_count * 100, 1)

        sec_data = db['sector_daily'].find_one(
            {'stock_code': sector_code, 'trade_date': latest_date},
            {'_id': 0, 'chg_pct': 1}
        )
        avg_chg = round(sec_data['chg_pct'], 2) if sec_data and sec_data.get('chg_pct') is not None else 0

        all_codes = sector_info.get('stock_codes', [])
        all_sector_stocks = []
        for code in all_codes:
            today_doc = today_map.get(code, {})
            if today_doc and (today_doc.get('close', 0) or 0) > 0:
                all_sector_stocks.append({
                    'code': code,
                    'name': name_map.get(code, code),
                    'close': today_doc.get('close', 0) or 0,
                    'chg_pct': today_doc.get('chg_pct', 0) or 0,
                    'chg_50d': today_doc.get('chg_50d', 0) or 0,
                    'amount': today_doc.get('amount', 0) or 0,
                })

        by_chg50 = sorted(all_sector_stocks, key=lambda x: -(x.get('chg_50d', 0) or 0))
        representative = []
        seen_rep = set()
        for s in by_chg50:
            if s['code'] not in seen_rep and len(representative) < 3:
                representative.append(f"{s['name']}(50日{s.get('chg_50d', 0) or 0:+.1f}%, 今日{s.get('chg_pct', 0) or 0:+.1f}%)")
                seen_rep.add(s['code'])

        for s in all_sector_stocks:
            liutong = liutong_map.get(s['code'], 0)
            close = s.get('close', 0) or 0
            s['_float_mv'] = liutong * close / 1e8 if liutong and close else 0
        by_mv = sorted(all_sector_stocks, key=lambda x: -(x.get('_float_mv', 0) or 0))[:10]
        by_mv_chg50 = sorted(by_mv, key=lambda x: -(x.get('chg_50d', 0) or 0))
        core_selected = []
        seen_core = set()
        for s in by_mv_chg50:
            if s['code'] not in seen_core and len(core_selected) < 3:
                core_selected.append(s)
                seen_core.add(s['code'])
        core_stocks = [f"{s['name']}(50日{s.get('chg_50d', 0) or 0:+.1f}%, 今日{s.get('chg_pct', 0) or 0:+.1f}%)" for s in core_selected[:3]]

        non_st = [s for s in all_sector_stocks if 'ST' not in (s.get('name') or '').upper()]
        by_amount_asc = sorted(non_st, key=lambda x: x.get('amount', 0) or 0)[:20]
        by_amount_asc_chg = sorted(by_amount_asc, key=lambda x: -(x.get('chg_pct', 0) or 0))
        followers = [f"{s['name']}({s.get('chg_pct', 0) or 0:+.1f}%)" for s in by_amount_asc_chg[:2]]

        stocks_sorted = sorted(stocks, key=lambda x: -(x.get('chg_pct', 0) or 0))

        clusters.append({
            'industry': sector_name,
            'count': count,
            'pct': pct,
            'chg_pct': avg_chg,
            'rps_10': rps_data.get('rps_10'),
            'rps_20': rps_data.get('rps_20'),
            'rps_50': rps_data.get('rps_50'),
            'pioneer': representative,
            'main_force': core_stocks,
            'followers': followers,
            'stocks': stocks_sorted,
        })

    top1 = clusters[0] if clusters else None
    if top1 and top1['pct'] > 10:
        interpretation = (
            '【主线板块效应评估】：今日有 ' + top1['industry'] + ' 等板块呈现强烈的'
            '"新高个股成批涌现"特征。根据威廉·欧奈尔的 CANSLIM 理论，'
            '50% 以上的大牛股会跟随行业浪潮进行集团式冲锋。在指数震荡期，'
            '机构资金不计成本地将 ' + top1['industry'] + ' 的多只核心标的推向历史新高，'
            '这是极其明显的"机构板块化建仓(Institutional Crowding)"信号，'
            '该方向已确立为市场的绝对领头羊主线。'
        )
    elif top1:
        interpretation = (
            '今日新高股分布较为分散，' + top1['industry'] + ' 领先但集中度不足，'
            '暂未形成明显的板块集团效应。需观察后续几日是否出现行业聚拢。'
        )
    else:
        interpretation = '今日无明显板块效应。'

    return {
        'success': True,
        'trade_date': latest_date,
        'total_new_high_count': total_new_high_count,
        'industry_clusters': clusters,
        'interpretation': interpretation,
        'new_high_stocks': new_high_stocks,
    }


def analyze_low_position_sectors(trade_date: str) -> Dict[str, Any]:
    """
    低位潜力板块筛选
    条件：
    1. 板块当日涨幅 > 2%
    2. MA10 > MA20
    3. RPS10 > 85（短线爆发力）
    4. RPS50 < 70（长线趋势尚未走强，低位）
    5. 近3天有1天以上 >=15% 的股票创20日新高
    6. 近5天有4天净新高(20日新高-20日新低) > -10
    """
    from datetime import timedelta
    db = get_db()

    enabled_sector_codes = set(
        doc['code'] for doc in db['sector_basics'].find(
            {'is_disable': {'$ne': True}}, {'_id': 0, 'code': 1}
        )
    )

    candidates = list(db['sector_daily'].find(
        {
            'trade_date': trade_date,
            'stock_code': {'$in': list(enabled_sector_codes)},
            'chg_pct': {'$gt': 2},
            'ma10': {'$gt': 0}, 'ma20': {'$gt': 0},
            'rps_10': {'$gt': 85}, 'rps_50': {'$lt': 70},
        },
        {'_id': 0, 'stock_code': 1, 'ma10': 1, 'ma20': 1, 'rps_10': 1, 'rps_20': 1, 'rps_50': 1, 'chg_pct': 1}
    ))
    candidates = [c for c in candidates if c['ma10'] > c['ma20']]

    if not candidates:
        return {'success': True, 'trade_date': trade_date, 'sectors': []}

    sector_map = {}
    for s in db['sector_basics'].find(
        {'is_disable': {'$ne': True}},
        {'_id': 0, 'code': 1, 'name': 1, 'stock_codes': 1}
    ):
        sector_map[s['code']] = s

    list_date_map = {}
    for b in db['stock_basics'].find(
        {'is_disable': {'$ne': True}}, {'_id': 0, 'stock_code': 1, 'list_date': 1}
    ):
        ld = b.get('list_date')
        if ld:
            list_date_map[b['stock_code']] = str(ld)

    liutong_map = {}
    for b in db['stock_basics'].find(
        {'is_disable': {'$ne': True}, 'liutongguben': {'$gt': 0}},
        {'_id': 0, 'stock_code': 1, 'liutongguben': 1}
    ):
        liutong_map[b['stock_code']] = b.get('liutongguben', 0)

    all_dates = sorted(db['stock_daily'].distinct('trade_date', {
        'trade_date': {'$gte': (_dt.strptime(trade_date, '%Y%m%d') - timedelta(days=60)).strftime('%Y%m%d')}
    }))

    cursor = db['stock_daily'].find(
        {'trade_date': {'$in': all_dates}, 'close': {'$gt': 0}},
        {'_id': 0, 'stock_code': 1, 'trade_date': 1, 'close': 1}
    )
    stock_data = {}
    for d in cursor:
        stock_data.setdefault(d['stock_code'], {})[d['trade_date']] = d['close']

    recent_dates = sorted(db['sector_daily'].distinct('trade_date', {'trade_date': {'$lte': trade_date}}), reverse=True)[:5]
    last3_dates = recent_dates[:3]

    results = []
    for c in candidates:
        code = c['stock_code']
        info = sector_map.get(code, {})
        name = info.get('name', code)

        stocks = info.get('stock_codes', [])
        total = len(stocks)
        if total < 5:
            continue

        daily_nets = []
        daily_pcts = []
        latest_new_high_codes = []
        for date in recent_dates:
            nh, nl = 0, 0
            for s in stocks:
                dm = stock_data.get(s, {})
                close = dm.get(date)
                if close is None:
                    continue
                hist = sorted([d for d in dm if d < date])[-20:]
                if len(hist) < 10:
                    continue
                mx = max(dm[d] for d in hist)
                mn = min(dm[d] for d in hist)
                if close >= mx:
                    nh += 1
                    if date == recent_dates[0]:
                        latest_new_high_codes.append(s)
                elif close <= mn:
                    nl += 1
            daily_nets.append(nh - nl)
            pct = round(nh / total * 100, 1) if total > 0 else 0
            daily_pcts.append(pct)

        last3_pcts = daily_pcts[:3]
        has15 = any(p >= 15 for p in last3_pcts)
        if not has15:
            continue

        days_above_minus10 = sum(1 for n in daily_nets if n > -10)
        if days_above_minus10 < 4:
            continue

        stock_daily_docs = list(db['stock_daily'].find(
            {'stock_code': {'$in': stocks}, 'trade_date': trade_date, 'close': {'$gt': 0}},
            {'_id': 0, 'stock_code': 1, 'close': 1, 'amount': 1, 'chg_50d': 1, 'chg_pct': 1}
        ))
        name_map = {}
        for s_doc in db['stock_basics'].find({'stock_code': {'$in': stocks}}, {'_id': 0, 'stock_code': 1, 'stock_name': 1}):
            name_map[s_doc['stock_code']] = s_doc.get('stock_name', s_doc['stock_code'])

        all_stocks = []
        for s_doc in stock_daily_docs:
            s_doc['name'] = name_map.get(s_doc['stock_code'], s_doc['stock_code'])
            s_doc['pct_chg'] = s_doc.get('chg_pct', 0) or 0
            s_doc['amount'] = s_doc.get('amount', 0) or 0
            all_stocks.append(s_doc)

        by_chg50 = sorted(all_stocks, key=lambda x: -(x.get('chg_50d', 0) or 0))[:3]
        pioneer = [f"{s['name']}(50日{s.get('chg_50d', 0) or 0:+.1f}%, 今日{s.get('chg_pct', 0) or 0:+.1f}%)" for s in by_chg50]

        for s in all_stocks:
            liutong = liutong_map.get(s.get('stock_code'), 0)
            close = s.get('close', 0) or 0
            s['_float_mv'] = liutong * close / 1e8 if liutong and close else 0
        by_mv = sorted(all_stocks, key=lambda x: -(x.get('_float_mv', 0) or 0))[:10]
        by_mv_chg50 = sorted(by_mv, key=lambda x: -(x.get('chg_50d', 0) or 0))[:3]
        main_force = [f"{s['name']}(50日{s.get('chg_50d', 0) or 0:+.1f}%, 今日{s.get('chg_pct', 0) or 0:+.1f}%)" for s in by_mv_chg50]

        non_st = [s for s in all_stocks if 'ST' not in (s.get('name') or '').upper()]
        by_amount_asc = sorted(non_st, key=lambda x: x.get('amount', 0) or 0)[:20]
        by_amount_asc_chg = sorted(by_amount_asc, key=lambda x: -(x.get('chg_pct', 0) or 0))[:2]
        followers = [f"{s['name']}({s.get('chg_pct', 0) or 0:+.1f}%)" for s in by_amount_asc_chg]

        latest_nh_pct = daily_pcts[0] if daily_pcts else 0
        nh_count = round(latest_nh_pct * total / 100) if total > 0 else 0

        # 结构化"符合条件近新高"个股列表（与新高强力板块 stocks 同构，供前端弹窗展示）
        new_high_code_set = set(latest_new_high_codes)
        stocks_field = [
            {
                'code': s['stock_code'],
                'name': s.get('name', s['stock_code']),
                'close': s.get('close', 0),
                'pct_chg': s.get('pct_chg', 0) or 0,
                'chg_pct': s.get('chg_pct', 0) or 0,
                'chg_50d': s.get('chg_50d', 0) or 0,
                'amount': s.get('amount', 0) or 0,
            }
            for s in all_stocks if s['stock_code'] in new_high_code_set
        ]

        results.append({
            'name': name,
            'count': nh_count,
            'pct': latest_nh_pct,
            'chg_pct': round(c.get('chg_pct', 0) or 0, 2),
            'ma10': round(c['ma10'], 2),
            'ma20': round(c['ma20'], 2),
            'rps_10': c['rps_10'],
            'rps_20': c.get('rps_20'),
            'rps_50': c['rps_50'],
            'daily_nets': daily_nets,
            'daily_pcts': daily_pcts,
            'pioneer': pioneer,
            'main_force': main_force,
            'followers': followers,
            'stocks': stocks_field,
        })

    results.sort(key=lambda x: -x['rps_10'])
    results = results[:5]

    return {'success': True, 'trade_date': trade_date, 'sectors': results}


def analyze_active_sectors(trade_date: str) -> Dict[str, Any]:
    """
    异动活跃板块筛选（V2）
    条件：
    1. 板块内流通市值>200亿 且 当日涨幅>5% 的个股 >= 10 只
    2. 其中 RPS10+RPS20+RPS50>250 的个股占比 > 30%
    3. 板块自身 RPS10+RPS20+RPS50 <= 250（板块中期趋势未过热）
    4. 板块当日涨幅 > 2%
    """
    db = get_db()

    enabled_sector_codes = set(
        doc['code'] for doc in db['sector_basics'].find(
            {'$or': [{'is_disable': {'$ne': True}}, {'is_disable': {'$exists': False}}]},
            {'_id': 0, 'code': 1}
        )
    )

    sector_map = {}
    for s in db['sector_basics'].find(
        {'$or': [{'is_disable': {'$ne': True}}, {'is_disable': {'$exists': False}}]},
        {'_id': 0, 'code': 1, 'name': 1, 'stock_codes': 1}
    ):
        sector_map[s['code']] = s

    stock_name_map = {}
    for b in db['stock_basics'].find(
        {'$or': [{'is_disable': {'$ne': True}}, {'is_disable': {'$exists': False}}]},
        {'_id': 0, 'stock_code': 1, 'stock_name': 1}
    ):
        stock_name_map[b['stock_code']] = b.get('stock_name', b['stock_code'])

    liutong_map = {}
    for b in db['stock_basics'].find(
        {'$or': [{'is_disable': {'$ne': True}}, {'is_disable': {'$exists': False}}], 'liutongguben': {'$gt': 0}},
        {'_id': 0, 'stock_code': 1, 'liutongguben': 1}
    ):
        liutong_map[b['stock_code']] = b['liutongguben']

    today_stocks = {d['stock_code']: d for d in db['stock_daily'].find(
        {'trade_date': trade_date, 'close': {'$gt': 0}},
        {'_id': 0, 'stock_code': 1, 'close': 1, 'chg_pct': 1, 'chg_50d': 1, 'amount': 1,
         'rps_10': 1, 'rps_20': 1, 'rps_50': 1}
    )}

    sector_daily_map = {}
    for doc in db['sector_daily'].find(
        {'trade_date': trade_date, 'stock_code': {'$in': list(enabled_sector_codes)}},
        {'_id': 0, 'stock_code': 1, 'chg_pct': 1, 'rps_10': 1, 'rps_20': 1, 'rps_50': 1}
    ):
        sector_daily_map[doc['stock_code']] = doc

    if not today_stocks:
        return {'success': True, 'trade_date': trade_date, 'sectors': []}

    results = []
    for code in enabled_sector_codes:
        info = sector_map.get(code)
        if not info:
            continue
        sd = sector_daily_map.get(code)
        if not sd:
            continue

        sector_chg = sd.get('chg_pct', 0) or 0
        sector_rps_sum = (sd.get('rps_10', 0) or 0) + (sd.get('rps_20', 0) or 0) + (sd.get('rps_50', 0) or 0)
        # 板块级前置条件：RPS 和 <= 250 且 当日涨幅 > 2%
        if sector_rps_sum > 250 or sector_chg <= 2:
            continue

        name = info.get('name', code)
        stocks = info.get('stock_codes', [])
        if len(stocks) < 10:
            continue

        # 市值>200亿 且 涨幅>5% 的个股
        cond_stocks = []
        for s_code in stocks:
            d = today_stocks.get(s_code)
            if not d:
                continue
            liutong = liutong_map.get(s_code, 0)
            if liutong <= 0:
                continue
            close = d.get('close', 0) or 0
            if close <= 0:
                continue
            float_mv = liutong * close / 1e8
            chg = d.get('chg_pct', 0) or 0
            if float_mv <= 200 or chg <= 5:
                continue
            rps_sum = (d.get('rps_10', 0) or 0) + (d.get('rps_20', 0) or 0) + (d.get('rps_50', 0) or 0)
            cond_stocks.append({
                'stock_code': s_code,
                'name': stock_name_map.get(s_code, s_code),
                'close': close,
                'amount': d.get('amount', 0) or 0,
                'chg_pct': chg,
                'chg_50d': d.get('chg_50d', 0) or 0,
                'float_mv': float_mv,
                'rps_sum': rps_sum,
            })

        if len(cond_stocks) < 10:
            continue

        # RPS和>250 的个股占比 > 30%
        strong_stocks = [s for s in cond_stocks if s['rps_sum'] > 250]
        strong_pct = len(strong_stocks) / len(cond_stocks) * 100
        if strong_pct <= 30:
            continue

        by_chg50 = sorted(cond_stocks, key=lambda x: -x['chg_50d'])[:3]
        pioneer = [f"{s['name']}(50日{s['chg_50d']:+.1f}%, 今日{s['chg_pct']:+.1f}%)" for s in by_chg50]

        by_mv = sorted(cond_stocks, key=lambda x: -x['float_mv'])[:10]
        by_mv_chg50 = sorted(by_mv, key=lambda x: -x['chg_50d'])[:3]
        main_force = [f"{s['name']}(50日{s['chg_50d']:+.1f}%, 今日{s['chg_pct']:+.1f}%)" for s in by_mv_chg50]

        non_st = [s for s in cond_stocks if 'ST' not in s['name'].upper()]
        by_amount_asc = sorted(non_st, key=lambda x: x['amount'])[:20]
        by_amount_asc_chg = sorted(by_amount_asc, key=lambda x: -x['chg_pct'])[:2]
        followers = [f"{s['name']}({s['chg_pct']:+.1f}%)" for s in by_amount_asc_chg]

        avg_chg = sum(s['chg_pct'] for s in cond_stocks) / len(cond_stocks) if cond_stocks else 0

        stocks_field = [
            {
                'code': s['stock_code'],
                'name': s['name'],
                'close': s['close'],
                'pct_chg': s['chg_pct'],
                'chg_pct': s['chg_pct'],
                'chg_50d': s['chg_50d'],
                'amount': s['amount'],
            }
            for s in strong_stocks
        ]

        results.append({
            'name': name,
            'count': len(strong_stocks),
            'total': len(cond_stocks),
            'pct': round(strong_pct, 1),
            'chg_pct': round(sector_chg, 2),
            'sector_chg_pct': round(sector_chg, 2),
            'avg_stock_chg_pct': round(avg_chg, 2),
            'rps_10': sd.get('rps_10'),
            'rps_20': sd.get('rps_20'),
            'rps_50': sd.get('rps_50'),
            'pioneer': pioneer,
            'main_force': main_force,
            'followers': followers,
            'stocks': stocks_field,
        })

    results.sort(key=lambda x: -x['pct'])
    results = results[:5]

    return {'success': True, 'trade_date': trade_date, 'sectors': results}