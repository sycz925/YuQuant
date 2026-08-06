"""
市场数据计算服务
提供数据计算、缓存读写的业务逻辑
从 api/market_review.py 迁移而来
"""
import logging
from typing import Dict, Any, List, Optional

from app.data.db import get_db

logger = logging.getLogger(__name__)


def calculate_nh_nl_series(days: int = 250) -> List[Dict[str, Any]]:
    """
    计算新高新低指数（NH-NL Index）— 优化版：批量向量化计算
    NH = 当日创下N日新高的股票数
    NL = 当日创下N日新低的股票数
    NH-NL = NH - NL
    """
    import pandas as pd
    from datetime import datetime as _dt, timedelta
    db = get_db()

    # 获取最近的交易日
    all_dates = sorted(db['stock_daily'].distinct('trade_date', {'close': {'$gt': 0}}), reverse=True)
    lookback = days + 50
    target_dates = all_dates[:lookback]
    target_dates.reverse()

    if not target_dates:
        return []

    # 获取大盘指数收盘价
    index_code = '000001'
    idx_cursor = db['index_daily'].find(
        {'stock_code': index_code, 'trade_date': {'$in': target_dates}},
        {'_id': 0, 'trade_date': 1, 'close': 1}
    ).sort('trade_date', 1)
    index_map = {d['trade_date']: d['close'] for d in idx_cursor}

    # 批量拉取数据构建DataFrame
    try:
        date_obj = _dt.strptime(target_dates[0], '%Y%m%d')
        pre_start = (date_obj - timedelta(days=days + 100)).strftime('%Y%m%d')
    except Exception:
        pre_start = '20200101'

    cursor = db['stock_daily'].find(
        {'trade_date': {'$gte': pre_start, '$lte': target_dates[-1]}, 'close': {'$gt': 0}},
        {'_id': 0, 'stock_code': 1, 'trade_date': 1, 'close': 1}
    )

    rows = list(cursor)
    if not rows:
        return []

    df = pd.DataFrame(rows)
    pivot = df.pivot_table(index='trade_date', columns='stock_code', values='close')
    pivot = pivot.sort_index()

    # 对每个目标日期计算NH-NL
    result = []
    all_pivot_dates = list(pivot.index)

    for target_date in target_dates:
        if target_date not in pivot.index:
            continue

        # 找到target_date在pivot中的位置
        try:
            idx = all_pivot_dates.index(target_date)
        except ValueError:
            continue

        if idx < days:
            continue

        # 取过去days天的数据窗口
        window = pivot.iloc[idx-days+1:idx+1]

        today_prices = pivot.iloc[idx]
        max_prices = window.max()
        min_prices = window.min()

        nh = ((today_prices >= max_prices) & today_prices.notna()).sum()
        nl = ((today_prices <= min_prices) & today_prices.notna()).sum()

        result.append({
            'date': target_date,
            'nh': int(nh),
            'nl': int(nl),
        })

    logger.info(f"[NH-NL] 计算完成: {len(result)}天, 最新: nh={result[-1]['nh']}, nl={result[-1]['nl']}" if result else "[NH-NL] 无数据")
    return result


def precompute_market_daily(trade_date: str) -> Dict[str, Any]:
    """
    盘后预计算市场指标并落库到 market_daily 集合
    在 stock_daily 同步完成且 is_final=true 后调用
    """
    from collections import defaultdict
    from datetime import datetime as _dt, timedelta
    db = get_db()

    logger.info(f"[预计算] 开始计算 {trade_date} 市场指标...")

    # 1. 获取启用的股票代码列表
    enabled_stock_codes = set(
        doc['stock_code'] for doc in db['stock_basics'].find(
            {'is_disable': {'$ne': True}}, {'_id': 0, 'stock_code': 1}
        )
    )
    
    # 获取今日全市场数据（只获取启用的股票）
    today_docs = list(db['stock_daily'].find(
        {'trade_date': trade_date, 'close': {'$gt': 0}, 'stock_code': {'$in': list(enabled_stock_codes)}},
        {'_id': 0, 'stock_code': 1, 'close': 1, 'high': 1, 'ma50': 1, 'ma20': 1,
         'chg_pct': 1, 'chg_20d': 1, 'amount': 1}
    ))
    if not today_docs:
        logger.warning(f"[预计算] {trade_date} 无交易数据")
        return {'success': False, 'message': '无交易数据'}

    total_stocks = len(today_docs)
    today_map = {d['stock_code']: d for d in today_docs}

    # 2. MA50/MA20 占比（直接用已有字段）
    above_ma50 = sum(1 for d in today_docs if d.get('ma50') and d['close'] > d['ma50'])
    above_ma20 = sum(1 for d in today_docs if d.get('ma20') and d['close'] > d['ma20'])
    ma50_pct = round(above_ma50 / total_stocks * 100, 1) if total_stocks > 0 else 0
    ma20_pct = round(above_ma20 / total_stocks * 100, 1) if total_stocks > 0 else 0

    # 3. 历史新高（收盘价 >= 历史最高收盘价）
    try:
        date_obj = _dt.strptime(trade_date, '%Y%m%d')
        hist_start = (date_obj - timedelta(days=365)).strftime('%Y%m%d')
    except Exception:
        hist_start = '20250101'

    new_high_pipeline = [
        {'$match': {'trade_date': {'$gte': hist_start, '$lte': trade_date}, 'close': {'$gt': 0}, 'stock_code': {'$in': list(enabled_stock_codes)}}},
        {'$group': {'_id': '$stock_code', 'max_close': {'$max': '$close'}}},
    ]
    hist_max_map = {r['_id']: r['max_close'] for r in db['stock_daily'].aggregate(new_high_pipeline)}

    new_high_count = 0
    new_high_codes = []
    for code, doc in today_map.items():
        max_close = hist_max_map.get(code, 0)
        if max_close > 0 and doc['close'] >= max_close:
            new_high_count += 1
            new_high_codes.append(code)

    # 4. 强势股（CLOSE / HHV(HIGH, 250) >= 0.9 且上市>30天）
    strong_pipeline = [
        {'$match': {'trade_date': {'$gte': hist_start, '$lte': trade_date}, 'high': {'$gt': 0}, 'stock_code': {'$in': list(enabled_stock_codes)}}},
        {'$group': {'_id': '$stock_code', 'max_high': {'$max': '$high'}}},
    ]
    hhv_map = {r['_id']: r['max_high'] for r in db['stock_daily'].aggregate(strong_pipeline)}

    # 获取上市日期
    list_date_map = {}
    for b in db['stock_basics'].find({}, {'_id': 0, 'stock_code': 1, 'list_date': 1}):
        ld = b.get('list_date')
        if ld:
            list_date_map[b['stock_code']] = str(ld)

    # 获取流通股本（用于计算流通市值）
    liutong_map = {}
    for b in db['stock_basics'].find({'liutongguben': {'$gt': 0}}, {'_id': 0, 'stock_code': 1, 'liutongguben': 1}):
        liutong_map[b['stock_code']] = b.get('liutongguben', 0)

    strong_count = 0
    for code, doc in today_map.items():
        hhv = hhv_map.get(code, 0)
        if hhv <= 0:
            continue
        # 检查上市天数
        ld = list_date_map.get(code, '')
        if ld and len(ld) >= 8:
            try:
                days_listed = (_dt.strptime(trade_date, '%Y%m%d') - _dt.strptime(ld, '%Y%m%d')).days
                if days_listed <= 30:
                    continue
            except:
                pass
        if doc['close'] / hhv >= 0.9:
            strong_count += 1

    # 5. 新高板块聚类（_build_stock_industries_map已只返回启用的板块）
    industries_map = _build_stock_industries_map()

    industry_groups = defaultdict(list)
    for code in new_high_codes:
        doc = today_map.get(code, {})
        inds = industries_map.get(code, ['其他'])
        for ind in inds:
            industry_groups[ind].append({
                'code': code,
                'name': '',
                'pct_chg': doc.get('chg_pct', 0) or 0,
                'chg_20d': doc.get('chg_20d', 0) or 0,
                'amount': doc.get('amount', 0) or 0,
            })

    # 获取股票名称
    for ind, stocks in industry_groups.items():
        for s in stocks:
            basic = db['stock_basics'].find_one({'stock_code': s['code']}, {'_id': 0, 'stock_name': 1})
            s['name'] = basic.get('stock_name', '') if basic else s['code']

    # Top10行业：先按数量取前10，再按新高占比降序排列
    top10_by_count = sorted(industry_groups.items(), key=lambda x: -len(x[1]))[:10]
    industry_pct = {}
    for ind, stocks in top10_by_count:
        seen = set()
        unique = [s for s in stocks if s['code'] not in seen and not seen.add(s['code'])]
        industry_pct[ind] = len(unique) / new_high_count * 100 if new_high_count > 0 else 0
    sorted_industries = sorted(top10_by_count, key=lambda x: -industry_pct.get(x[0], 0))
    industry_clusters = []
    # 构建行业→股票代码反向映射
    industry_to_codes = defaultdict(set)
    for code, inds in industries_map.items():
        for ind_name in inds:
            industry_to_codes[ind_name].add(code)

    for ind, stocks in sorted_industries:
        # 按code去重（一只股票可能因多行业重复）
        seen_codes = set()
        unique_stocks = []
        for s in stocks:
            if s['code'] not in seen_codes:
                seen_codes.add(s['code'])
                unique_stocks.append(s)
        stocks = unique_stocks

        count = len(stocks)
        pct = round(count / new_high_count * 100, 1) if new_high_count > 0 else 0

        def _fmt(s):
            return f"{s['name']}(50日{s.get('chg_50d', 0) or 0:+.1f}%, 今日{s.get('chg_pct', 0) or 0:+.1f}%)"

        def _fmt_chg(s):
            return f"{s['name']}({s.get('chg_pct', 0) or 0:+.1f}%)"

        def _dedup(lst, limit):
            seen = set()
            result = []
            for s in lst:
                if s['code'] not in seen and len(result) < limit:
                    seen.add(s['code'])
                    result.append(s)
            return result

        # 从该行业所有股票中选取（不限新高股池）
        try:
            all_industry_codes = list(industry_to_codes.get(ind, set()))
            all_ind_stocks = []
            if all_industry_codes:
                raw = list(db['stock_daily'].find(
                    {'stock_code': {'$in': all_industry_codes}, 'trade_date': trade_date, 'close': {'$gt': 0}},
                    {'_id': 0, 'stock_code': 1, 'close': 1, 'amount': 1, 'chg_50d': 1, 'chg_pct': 1}
                ))
                for s in raw:
                    basic = db['stock_basics'].find_one({'stock_code': s['stock_code']}, {'_id': 0, 'stock_name': 1})
                    s['name'] = basic.get('stock_name', '') if basic else s['stock_code']
                    s['code'] = s['stock_code']
                    s['pct_chg'] = s.get('chg_pct', 0) or 0
                    all_ind_stocks.append(s)
        except Exception:
            all_ind_stocks = []

        # 先锋：历史涨幅(chg_50d)最高的3只
        by_chg50 = sorted(all_ind_stocks, key=lambda x: -x.get('chg_50d', 0))
        pioneer = [_fmt(s) for s in _dedup(by_chg50, 3)]

        # 中军：流通市值Top10中，历史涨幅最高的3只
        # 流通市值 = 流通股本 * 收盘价
        for s in all_ind_stocks:
            code = s.get('stock_code') or s.get('code', '')
            liutong = liutong_map.get(code, 0)
            close = s.get('close', 0) or 0
            s['_float_mv'] = liutong * close / 1e8 if liutong and close else 0
        by_mv = sorted(all_ind_stocks, key=lambda x: -x.get('_float_mv', 0))[:10]
        by_mv_chg50 = sorted(by_mv, key=lambda x: -x.get('chg_50d', 0))
        main_force = [_fmt(s) for s in _dedup(by_mv_chg50, 3)]

        # 后排：成交额最小的20只中（排除ST），当天涨幅最高的2只
        non_st = [s for s in all_ind_stocks if 'ST' not in (s.get('name') or '').upper()]
        by_amount_asc = sorted(non_st, key=lambda x: x.get('amount', 0) or 0)[:20]
        by_amount_asc_chg = sorted(by_amount_asc, key=lambda x: -(x.get('chg_pct', 0) or 0))
        followers = [_fmt_chg(s) for s in _dedup(by_amount_asc_chg, 2)]

        # 涨幅和RPS：用板块自身数据（sector_daily）
        # 同板块名可能存在多个来源（880通达信/881同花顺），优先取 880 通达信
        sector_doc_pre = db['sector_basics'].find_one(
            {'name': ind, 'code': {'$regex': '^880'}}, {'_id': 0, 'code': 1}
        )
        if not sector_doc_pre:
            sector_doc_pre = db['sector_basics'].find_one({'name': ind}, {'_id': 0, 'code': 1})
        avg_chg = 0
        rps_10 = None
        rps_20 = None
        rps_50 = None
        if sector_doc_pre and sector_doc_pre.get('code'):
            sec_data_pre = db['sector_daily'].find_one(
                {'stock_code': sector_doc_pre['code'], 'trade_date': trade_date},
                {'_id': 0, 'chg_pct': 1, 'rps_10': 1, 'rps_20': 1, 'rps_50': 1}
            )
            if sec_data_pre:
                avg_chg = round(sec_data_pre['chg_pct'], 2) if sec_data_pre.get('chg_pct') is not None else 0
                rps_10 = sec_data_pre.get('rps_10')
                rps_20 = sec_data_pre.get('rps_20')
                rps_50 = sec_data_pre.get('rps_50')

        industry_clusters.append({
            'industry': ind,
            'count': count,
            'pct': pct,
            'chg': avg_chg,
            'rps_10': rps_10,
            'rps_20': rps_20,
            'rps_50': rps_50,
            'pioneer': pioneer,
            'main_force': main_force,
            'followers': followers,
            'stocks': sorted(stocks, key=lambda x: -x['pct_chg']),
        })

    # 6. 主要大盘指数涨跌幅（直接查询非禁用的指数）
    index_cursor = db['index_basics'].find(
        {'is_disable': {'$ne': True}},
        {'_id': 0, 'code': 1, 'name': 1}
    ).sort('code', 1)
    index_config = list(index_cursor)

    index_codes = [c['code'] for c in index_config]
    today_idx = {d['stock_code']: d for d in db['index_daily'].find(
        {'stock_code': {'$in': index_codes}, 'trade_date': trade_date},
        {'_id': 0, 'stock_code': 1, 'open': 1, 'high': 1, 'low': 1, 'close': 1, 'amount': 1, 'chg_pct': 1}
    )}

    # 批量查询各指数前一交易日收盘价（用于计算盘中最大涨幅/跌幅）
    prev_close_map = {}
    for code in index_codes:
        prev_doc = db['index_daily'].find_one(
            {'stock_code': code, 'trade_date': {'$lt': trade_date}},
            {'_id': 0, 'close': 1},
            sort=[('trade_date', -1)]
        )
        prev_close_map[code] = prev_doc['close'] if prev_doc and prev_doc.get('close') else 0

    overview_indices = []

    # 批量查询各指数最近20天成交额用于计算MA5/MA20
    vol_map = {}  # {code: [amount_list sorted by date desc]}
    for code in index_codes:
        rows = list(db['index_daily'].find(
            {'stock_code': code},
            {'_id': 0, 'amount': 1}
        ).sort('trade_date', -1).limit(20))
        vol_map[code] = [d.get('amount', 0) or 0 for d in rows]

    for c in index_config:
        code = c['code']
        t = today_idx.get(code, {})
        pct_chg = t.get('chg_pct', 0) or 0

        # 成交额数据（今日、MA5、MA20）
        today_amt = today_idx.get(code, {}).get('amount', 0) or 0
        amounts = vol_map.get(code, [])
        ma5_amt = round(sum(amounts[:5]) / min(len(amounts), 5) / 1e8, 1) if amounts else 0
        ma20_amt = round(sum(amounts[:20]) / min(len(amounts), 20) / 1e8, 1) if amounts else 0

        # 盘中最大涨幅/跌幅 + 长影线检测
        open_price = round(t.get('open', 0), 2) if t else 0
        high_price = round(t.get('high', 0), 2) if t else 0
        low_price = round(t.get('low', 0), 2) if t else 0
        close_price = round(t.get('close', 0), 2) if t else 0
        prev_close = prev_close_map.get(code, 0)

        wick = {'type': 'none', 'upper_pct': 0, 'lower_pct': 0}
        if prev_close and prev_close > 0 and close_price and high_price and low_price:
            upper_pct = round((high_price - close_price) / prev_close * 100, 2)
            lower_pct = round((close_price - low_price) / prev_close * 100, 2)
            wick['upper_pct'] = upper_pct
            wick['lower_pct'] = lower_pct
            is_upper = upper_pct > 3
            is_lower = lower_pct > 3
            if is_upper and is_lower:
                wick['type'] = 'both'
            elif is_upper:
                wick['type'] = 'upper'
            elif is_lower:
                wick['type'] = 'lower'

        overview_indices.append({
            'code': code,
            'name': c['name'],
            'open': open_price,
            'high': high_price,
            'low': low_price,
            'close': close_price,
            'prev_close': round(prev_close, 2) if prev_close else 0,
            'pct_chg': pct_chg,
            'wick': wick,
            'comment': '',
            'amount_today': round(today_amt / 1e8, 1) if today_amt else 0,
            'amount_yesterday': 0,
            'amount_ma5': ma5_amt,
            'amount_ma20': ma20_amt,
        })

    overview_indices.sort(key=lambda x: -x['pct_chg'])
    for idx in overview_indices:
        wick = idx.get('wick', {})
        wick_suffix = ''
        if wick.get('type') == 'upper':
            wick_suffix = f"（回撤+{wick['upper_pct']}%）"
        elif wick.get('type') == 'lower':
            wick_suffix = f"（反弹+{wick['lower_pct']}%）"
        elif wick.get('type') == 'both':
            wick_suffix = f"（回撤+{wick['upper_pct']}%/反弹+{wick['lower_pct']}%）"

        if idx == overview_indices[0]:
            idx['comment'] = '表现最强，领先全场' + wick_suffix
        elif '科创' in idx['name']:
            if idx['pct_chg'] >= 3.0:
                idx['comment'] = '🚀 科创爆发' + wick_suffix
            elif idx['pct_chg'] >= 1.5:
                idx['comment'] = '强势' + wick_suffix
            else:
                idx['comment'] = wick_suffix.lstrip('（') if wick_suffix else ''
        elif '创业板' in idx['name']:
            if idx['pct_chg'] >= 1.5:
                idx['comment'] = '创业板强势' + wick_suffix
            else:
                idx['comment'] = wick_suffix.lstrip('（') if wick_suffix else ''
        else:
            if abs(idx['pct_chg']) >= 1.0:
                idx['comment'] = ('偏强' if idx['pct_chg'] > 0 else '遭遇调整') + wick_suffix
            elif abs(idx['pct_chg']) >= 0.5:
                idx['comment'] = ('整体均衡' if idx['pct_chg'] > 0 else '小幅回调') + wick_suffix
            else:
                idx['comment'] = ('窄幅震荡' if idx['pct_chg'] > 0 else '小盘股偏弱') + wick_suffix

    # 核心结论
    leader = overview_indices[0] if overview_indices else {'name': '', 'pct_chg': 0}
    laggard = overview_indices[-1] if overview_indices else {'name': '', 'pct_chg': 0}
    kc50 = next((i for i in overview_indices if '科创' in i['name']), None)
    cyb = next((i for i in overview_indices if '创业板' in i['name']), None)

    if leader['name'] in ['科创50'] or leader['name'] in ['创业板指']:
        style = '科技成长领涨，结构分化明显'
    elif leader['pct_chg'] > 1.0 and laggard['pct_chg'] < -0.5:
        style = '市场分化明显，资金抱团权重'
    elif leader['pct_chg'] > 0.5 and laggard['pct_chg'] > 0:
        style = '全线上涨，市场情绪回暖'
    elif leader['pct_chg'] < 0:
        style = '市场整体承压，避险情绪升温'
    else:
        style = '市场窄幅震荡，等待方向选择'

    conclusion = style + '。' + leader['name'] + '领涨主板，涨幅 ' + str(leader['pct_chg']) + '%'
    if kc50 and kc50['pct_chg'] > 1.5:
        conclusion += '，科创50更是暴涨 ' + str(kc50['pct_chg']) + '%，显示资金集中涌向科技成长赛道'
    elif cyb and cyb['pct_chg'] > 1.5:
        conclusion += '，创业板指强势 ' + str(cyb['pct_chg']) + '%，成长风格占优'
    conclusion += '。' + laggard['name'] + '仅 ' + str(laggard['pct_chg']) + '%'
    if laggard['pct_chg'] < 0:
        conclusion += '，部分板块明显落后。'
    else:
        conclusion += '，表现相对平稳。'

    # 7. 信号解读
    if ma50_pct < 35 and new_high_count > 150:
        top_industry = industry_clusters[0]['industry'] if industry_clusters else '科技成长'
        interpretation = (
            '大盘仅 ' + str(ma50_pct) + '% 站上50日线，但 ' + str(new_high_count) + ' 只个股创历史新高，'
            '呈现典型"指数冰点+个股井喷"背离。'
            '米内尔维尼指出这是"先行者现象"——机构正集中建仓 ' + top_industry + ' 等领头羊板块。'
            '策略：放弃弱势股，聚焦距离250日高点<10%的强势品种，等待口袋突破信号。'
        )
    else:
        if ma50_pct > 70:
            mp = '市场强势'
        elif ma50_pct > 50:
            mp = '分歧偏强'
        elif ma50_pct > 30:
            mp = '整体分歧'
        else:
            mp = '整体弱势'
        interpretation = (
            '站上50日线占比 ' + str(ma50_pct) + '%，' + mp + '。'
            + str(new_high_count) + ' 只创历史新高'
            + ('，局部做多动能极强。' if new_high_count > 100 else '，局部仍有做多动能。')
        )

    # 组装结果并落库（精简结构，数值落库，文本留空待DeepSeek填充）
    # 获取最新CR5%和CR10%
    from app.engine.factor_engine import FactorEngine
    try:
        fe = FactorEngine()
        cr5_val = fe.calculate_cr5_percent(trade_date)
        # CR10%：板块成交额前10%拥挤度（使用 sector_daily 数据）
        import numpy as np
        sector_pipeline = [
            {'$match': {'trade_date': trade_date, 'amount': {'$gt': 0}}},
            {'$group': {
                '_id': '$trade_date',
                'amounts': {'$push': '$amount'},
                'total': {'$sum': '$amount'},
                'count': {'$sum': 1}
            }}
        ]
        sector_result = list(db['sector_daily'].aggregate(sector_pipeline))
        cr10_val = None
        if sector_result and sector_result[0].get('count', 0) >= 10:
            r = sector_result[0]
            amounts = np.array(r['amounts'])
            threshold = np.percentile(amounts, 90)
            top_amount = amounts[amounts >= threshold].sum()
            cr10_val = round((top_amount / r['total']) * 100, 2) if r['total'] > 0 else None
    except Exception:
        cr5_val = None
        cr10_val = None

    # 判断是否盘后（个股is_final=true > 95%）
    is_final = True
    try:
        total_count = db['stock_daily'].count_documents({'trade_date': trade_date, 'close': {'$gt': 0}})
        if total_count > 0:
            final_count = db['stock_daily'].count_documents({'trade_date': trade_date, 'close': {'$gt': 0}, 'is_final': True})
            final_ratio = final_count / total_count
            is_final = final_ratio > 0.95
    except Exception:
        pass

    result = {
        'trade_date': trade_date,
        'is_final': is_final,
        'overview': {
            'indices': [{
                'code': i['code'],
                'name': i['name'],
                'open': i.get('open', 0),
                'high': i.get('high', 0),
                'low': i.get('low', 0),
                'close': i['close'],
                'prev_close': i.get('prev_close', 0),
                'pct_chg': i['pct_chg'],
                'wick': i.get('wick', {'type': 'none', 'upper_pct': 0, 'lower_pct': 0}),
                'comment': i.get('comment', ''),
                'amount_today': i.get('amount_today', 0),
                'amount_yesterday': i.get('amount_yesterday', 0),
                'amount_ma5': i.get('amount_ma5', 0),
                'amount_ma20': i.get('amount_ma20', 0),
            } for i in overview_indices],
            'leader': overview_indices[0]['name'] if overview_indices else '',
            'leader_chg': overview_indices[0]['pct_chg'] if overview_indices else 0,
        },
        'new_high': {
            'total_count': new_high_count,
            'clusters': [],
        },
        'compute_time': _dt.now().isoformat(),
    }

    # === 桥接：以下函数已在 services/market_sectors.py ===
    # 低位潜力板块
    try:
        from app.server.services.market_sectors import analyze_low_position_sectors
        lps_result = analyze_low_position_sectors(trade_date)
        result['low_position_sectors'] = lps_result.get('sectors', [])
    except Exception as e:
        logger.warning(f"计算低位潜力板块失败: {e}")
        result['low_position_sectors'] = []

    # 异动活跃板块
    try:
        from app.server.services.market_sectors import analyze_active_sectors
        active_result = analyze_active_sectors(trade_date)
        result['active_sectors'] = active_result.get('sectors', [])
    except Exception as e:
        logger.warning(f"计算异动活跃板块失败: {e}")
        result['active_sectors'] = []

    # 新高强力板块（使用统一的 analyze_new_high_blocks）
    try:
        from app.server.services.market_sectors import analyze_new_high_blocks
        nh_result = analyze_new_high_blocks(trade_date)
        if nh_result.get('success'):
            result['new_high'] = {
                'total_count': nh_result.get('total_new_high_count', 0),
                'clusters': nh_result.get('industry_clusters', []),
            }
    except Exception as e:
        logger.warning(f"计算新高板块失败: {e}")

    # 分组统计（RPS/成交额/股价/流通市值）
    try:
        from app.server.api.market_analysis import _quantile_groups

        # 获取启用的股票数据
        enabled_stock_codes = set(
            doc['stock_code'] for doc in db['stock_basics'].find(
                {'is_disable': {'$ne': True}},
                {'_id': 0, 'stock_code': 1}
            )
        )
        today_stocks = {d['stock_code']: d for d in db['stock_daily'].find(
            {'trade_date': trade_date, 'close': {'$gt': 0}, 'amount': {'$gt': 0},
             'stock_code': {'$in': list(enabled_stock_codes)}},
            {'_id': 0, 'stock_code': 1, 'close': 1, 'amount': 1, 'chg_pct': 1,
             'rps_10': 1, 'rps_20': 1, 'rps_50': 1, 'rps_120': 1, 'rps_250': 1}
        )}

        # 获取流通股本
        liutong_map = {}
        for doc in db['stock_basics'].find(
            {'stock_code': {'$in': list(today_stocks.keys())}},
            {'_id': 0, 'stock_code': 1, 'liutongguben': 1}
        ):
            if doc.get('liutongguben'):
                liutong_map[doc['stock_code']] = doc['liutongguben']

        merged = []
        for code, row in today_stocks.items():
            chg_pct = row.get('chg_pct')
            if chg_pct is not None:
                liutongguben = liutong_map.get(code, 0)
                float_mv = round(liutongguben * row['close'] / 1e8, 2) if liutongguben > 0 else 0
                merged.append({
                    'chg_pct': chg_pct,
                    'close': row['close'],
                    'amount': row['amount'],
                    'rps': row.get('rps_20'),
                    'float_mv': float_mv,
                })

        group_stats = {}
        if merged:
            # RPS20 分组
            rps_data = [{'chg_pct': d['chg_pct'], 'sort_val': d['rps']} for d in merged if d.get('rps') is not None and d.get('rps') > 0]
            group_stats['rps_stats'] = _quantile_groups(rps_data, n_groups=20)

            # 成交额分组
            amount_data = [{'chg_pct': d['chg_pct'], 'sort_val': d['amount']} for d in merged]
            group_stats['amount_stats'] = _quantile_groups(amount_data, n_groups=20)

            # 股价分组
            price_data = [{'chg_pct': d['chg_pct'], 'sort_val': d['close']} for d in merged]
            group_stats['price_stats'] = _quantile_groups(price_data, n_groups=20)

            # 流通市值分组
            mv_data = [{'chg_pct': d['chg_pct'], 'sort_val': d['float_mv']} for d in merged if d.get('float_mv', 0) > 0]
            group_stats['float_mv_stats'] = _quantile_groups(mv_data, n_groups=20)

        result['group_stats'] = group_stats
    except Exception as e:
        logger.warning(f"计算分组统计失败: {e}")
        result['group_stats'] = {}

    # 预计算MA占比历史（最近120天）
    ma_breadth_data = []
    try:
        from datetime import date as _date
        all_trade_dates = sorted(db['stock_daily'].distinct('trade_date', {'close': {'$gt': 0}, 'ma50': {'$gt': 0}}), reverse=True)
        ma_dates = [d for d in all_trade_dates if d <= trade_date][:120]
        ma_dates.reverse()
        if ma_dates:
            pipeline = [
                {'$match': {'trade_date': {'$in': ma_dates}, 'close': {'$gt': 0}, 'ma50': {'$gt': 0}}},
                {'$group': {
                    '_id': '$trade_date',
                    'total': {'$sum': 1},
                    'above_ma50': {'$sum': {'$cond': [{'$gt': ['$close', '$ma50']}, 1, 0]}},
                    'above_ma20': {'$sum': {'$cond': [{'$gt': ['$close', '$ma20']}, 1, 0]}}
                }},
                {'$sort': {'_id': 1}}
            ]
            for r in db['stock_daily'].aggregate(pipeline):
                if r['total'] > 0:
                    ma_breadth_data.append({
                        'date': r['_id'],
                        'ma50_pct': round(r['above_ma50'] / r['total'] * 100, 1),
                        'ma20_pct': round(r['above_ma20'] / r['total'] * 100, 1),
                    })
    except Exception as e:
        logger.warning(f"预计算MA占比失败: {e}")

    # 落库到 base_data_daily（合并MA占比到已有记录）
    if ma_breadth_data:
        for item in ma_breadth_data:
            db['base_data_daily'].update_one(
                {'date': item['date']},
                {'$set': {'ma50_pct': item['ma50_pct'], 'ma20_pct': item['ma20_pct']}},
                upsert=True
            )

    # 落库 market_daily（快照数据）
    db['market_daily'].update_one(
        {'trade_date': trade_date},
        {'$set': result},
        upsert=True
    )
    logger.info(f"[预计算] {trade_date} 完成: MA50={ma50_pct}% 新高={new_high_count} 强势={strong_count} MA占比={len(ma_breadth_data)}天")

    return result


def get_market_daily(trade_date: str = None, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
    """从 market_daily 集合读取预计算数据，不存在则自动计算并落库
    force_refresh: 强制刷新（盘中数据变化时使用）
    """
    db = get_db()
    if not trade_date:
        # 优先从market_daily取最新日期
        latest_doc = db['market_daily'].find_one({'trade_date': {'$exists': True}}, sort=[('trade_date', -1)], projection={'_id': 0, 'trade_date': 1})
        if latest_doc:
            trade_date = latest_doc['trade_date']
        else:
            trade_date = get_latest_trade_date(db)
    if not trade_date:
        return None
    # 非强制刷新时，先查缓存
    if not force_refresh:
        cached = db['market_daily'].find_one({'trade_date': trade_date}, {'_id': 0})
        if cached:
            return cached
    # 缓存未命中或强制刷新，计算并落库
    logger.info(f"[{'强制刷新' if force_refresh else '缓存未命中'}] 预计算 {trade_date}")
    return precompute_market_daily(trade_date)


def get_latest_trade_date(db=None) -> Optional[str]:
    """获取最新交易日（优先从缓存读取）"""
    from app.server.cache import get_latest_trade_date as _get_cached_date
    cached = _get_cached_date()
    if cached:
        return cached
    # 缓存未命中时查数据库
    if db is None:
        db = get_db()
    dates = sorted(db['stock_daily'].distinct('trade_date', {'close': {'$gt': 0}}), reverse=True)
    return dates[0] if dates else None


def get_previous_trade_date(db, date: str) -> Optional[str]:
    """获取指定日期的前一个交易日"""
    result = db['stock_daily'].find_one(
        {'trade_date': {'$lt': date}},
        sort=[('trade_date', -1)],
        projection={'trade_date': 1, '_id': 0}
    )
    return result['trade_date'] if result else None


def _build_stock_industry_map() -> Dict[str, str]:
    """从 sector_basics 构建 stock_code -> 主行业名称 映射（取成分股最多的行业，只返回启用的板块）"""
    db = get_db()
    cursor = db['sector_basics'].find(
        {'stock_count': {'$gt': 0}, 'is_disable': {'$ne': True}},
        {'_id': 0, 'name': 1, 'stock_codes': 1, 'stock_count': 1}
    )
    stock_map = {}
    all_sectors = []
    for sector in cursor:
        name = sector.get('name', '')
        codes = sector.get('stock_codes', [])
        count = sector.get('stock_count', 0)
        if name and codes:
            all_sectors.append((name, count, codes))

    all_sectors.sort(key=lambda x: -x[1])

    for name, count, codes in all_sectors:
        for code in codes:
            if code not in stock_map:
                stock_map[code] = name

    return stock_map


def _build_stock_industries_map() -> Dict[str, List[str]]:
    """从 sector_basics 构建 stock_code -> 行业名称列表 映射（只返回启用的板块）"""
    db = get_db()
    cursor = db['sector_basics'].find(
        {'stock_count': {'$gt': 0}, 'is_disable': {'$ne': True}},
        {'_id': 0, 'name': 1, 'stock_codes': 1, 'stock_count': 1}
    )
    stock_map = {}
    for sector in cursor:
        name = sector.get('name', '')
        codes = sector.get('stock_codes', [])
        count = sector.get('stock_count', 0)
        if name and codes and count >= 5:
            for code in codes:
                if code not in stock_map:
                    stock_map[code] = []
                stock_map[code].append(name)

    return stock_map


def _get_daily_data_for_stock(stock_code: str, end_date: str, limit: int = 260) -> List[Dict]:
    db = get_db()
    cursor = db['stock_daily'].find(
        {'stock_code': stock_code, 'trade_date': {'$lte': end_date}},
        {'_id': 0, 'trade_date': 1, 'close': 1, 'high': 1}
    ).sort('trade_date', -1).limit(limit)
    return list(cursor)


def _compute_realtime(data_type, trade_date):
    """实时计算某一天的指标（用于base_data_daily缺失时兜底）"""
    db = get_db()
    # 盘后（15:30后）标记为 is_final=True，盘中标记 False
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo
    now_bj = _dt.now(ZoneInfo('Asia/Shanghai'))
    is_market_closed = now_bj.hour > 15 or (now_bj.hour == 15 and now_bj.minute >= 30)
    row = {'date': trade_date, 'is_final': is_market_closed}

    if data_type == 'cr5':
        # CR5: 个股成交额前5%
        pipeline = [
            {'$match': {'trade_date': trade_date, 'amount': {'$gt': 0}}},
            {'$group': {'_id': '$trade_date', 'amounts': {'$push': '$amount'}}}
        ]
        r = list(db['stock_daily'].aggregate(pipeline))
        if r and len(r[0]['amounts']) >= 50:
            amounts = sorted(r[0]['amounts'], reverse=True)
            n5 = max(1, int(len(amounts) * 0.05))
            row['cr5_pct'] = round(sum(amounts[:n5]) / sum(amounts) * 100, 4)
        # CR10: 板块成交额前10%
        pipeline10 = [
            {'$match': {'trade_date': trade_date, 'amount': {'$gt': 0}}},
            {'$group': {'_id': '$trade_date', 'amounts': {'$push': '$amount'}}}
        ]
        r10 = list(db['sector_daily'].aggregate(pipeline10))
        if r10 and len(r10[0]['amounts']) >= 100:
            amounts = sorted(r10[0]['amounts'], reverse=True)
            n10 = max(1, int(len(amounts) * 0.10))
            row['cr10_pct'] = round(sum(amounts[:n10]) / sum(amounts) * 100, 4)

    elif data_type == 'ma':
        # MA50/MA20占比
        pipeline = [
            {'$match': {'trade_date': trade_date, 'close': {'$gt': 0}, 'ma50': {'$gt': 0}}},
            {'$group': {
                '_id': '$trade_date', 'total': {'$sum': 1},
                'above_ma50': {'$sum': {'$cond': [{'$gt': ['$close', '$ma50']}, 1, 0]}},
                'above_ma20': {'$sum': {'$cond': [{'$gt': ['$close', '$ma20']}, 1, 0]}}
            }}
        ]
        r = list(db['stock_daily'].aggregate(pipeline))
        if r and r[0]['total'] > 0:
            row['ma50_pct'] = round(r[0]['above_ma50'] / r[0]['total'] * 100, 1)
            row['ma20_pct'] = round(r[0]['above_ma20'] / r[0]['total'] * 100, 1)

    elif data_type == 'nh-nl':
        # NH-NL：支持250日/60日(3个月)/20日(1个月)滚动窗口
        from datetime import datetime as _dt, timedelta
        try:
            hist_start = (_dt.strptime(trade_date, '%Y%m%d') - timedelta(days=365)).strftime('%Y%m%d')
        except Exception:
            hist_start = '20200101'

        # 获取上市日期（只获取启用的股票）
        list_date_map = {}
        for b in db['stock_basics'].find(
            {'is_disable': {'$ne': True}},
            {'_id': 0, 'stock_code': 1, 'list_date': 1}
        ):
            ld = b.get('list_date')
            if ld:
                list_date_map[b['stock_code']] = str(ld)

        def _days_listed(code):
            ld = list_date_map.get(code)
            if not ld or len(ld) < 8:
                return 9999
            try:
                return (_dt.strptime(trade_date, '%Y%m%d') - _dt.strptime(ld, '%Y%m%d')).days
            except:
                return 9999

        # 批量查询每只股票的最高/最低收盘价（不含当天）
        all_codes = [d['stock_code'] for d in db['stock_daily'].find(
            {'trade_date': trade_date, 'close': {'$gt': 0}},
            {'_id': 0, 'stock_code': 1}
        )]

        # 取当天前一个交易日作为截止日
        prev_date = db['stock_daily'].find_one(
            {'trade_date': {'$lt': trade_date}},
            sort=[('trade_date', -1)],
            projection={'_id': 0, 'trade_date': 1}
        )
        end_date = prev_date['trade_date'] if prev_date else trade_date

        # 250日窗口
        pipeline_250 = [
            {'$match': {'stock_code': {'$in': all_codes}, 'trade_date': {'$gte': hist_start, '$lte': end_date}, 'close': {'$gt': 0}}},
            {'$group': {'_id': '$stock_code', 'max_high': {'$max': '$close'}, 'min_low': {'$min': '$close'}}}
        ]
        hist_stats_250 = {d['_id']: d for d in db['stock_daily'].aggregate(pipeline_250)}

        # 60日窗口（3个月）
        try:
            hist_start_60 = (_dt.strptime(end_date, '%Y%m%d') - timedelta(days=90)).strftime('%Y%m%d')
        except Exception:
            hist_start_60 = hist_start
        pipeline_60 = [
            {'$match': {'stock_code': {'$in': all_codes}, 'trade_date': {'$gte': hist_start_60, '$lte': end_date}, 'close': {'$gt': 0}}},
            {'$group': {'_id': '$stock_code', 'max_high': {'$max': '$close'}, 'min_low': {'$min': '$close'}}}
        ]
        hist_stats_60 = {d['_id']: d for d in db['stock_daily'].aggregate(pipeline_60)}

        # 20日窗口（1个月）
        try:
            hist_start_20 = (_dt.strptime(end_date, '%Y%m%d') - timedelta(days=30)).strftime('%Y%m%d')
        except Exception:
            hist_start_20 = hist_start
        pipeline_20 = [
            {'$match': {'stock_code': {'$in': all_codes}, 'trade_date': {'$gte': hist_start_20, '$lte': end_date}, 'close': {'$gt': 0}}},
            {'$group': {'_id': '$stock_code', 'max_high': {'$max': '$close'}, 'min_low': {'$min': '$close'}}}
        ]
        hist_stats_20 = {d['_id']: d for d in db['stock_daily'].aggregate(pipeline_20)}

        nh, nl = 0, 0
        nh_3m, nl_3m = 0, 0
        nh_1m, nl_1m = 0, 0
        for code, doc in [(d['stock_code'], d) for d in db['stock_daily'].find(
            {'trade_date': trade_date, 'close': {'$gt': 0}}, {'_id': 0, 'stock_code': 1, 'close': 1}
        )]:
            # 剔除上市未满1年的新股
            if _days_listed(code) < 365:
                continue
            close = doc.get('close', 0)

            # 250日窗口
            stats_250 = hist_stats_250.get(code, {})
            max_high_250 = stats_250.get('max_high', 0)
            min_low_250 = stats_250.get('min_low', 0)
            if max_high_250 > 0 and close >= max_high_250:
                nh += 1
            elif min_low_250 > 0 and close <= min_low_250:
                nl += 1

            # 60日窗口（3个月）
            stats_60 = hist_stats_60.get(code, {})
            max_high_60 = stats_60.get('max_high', 0)
            min_low_60 = stats_60.get('min_low', 0)
            if max_high_60 > 0 and close >= max_high_60:
                nh_3m += 1
            elif min_low_60 > 0 and close <= min_low_60:
                nl_3m += 1

            # 20日窗口（1个月）
            stats_20 = hist_stats_20.get(code, {})
            max_high_20 = stats_20.get('max_high', 0)
            min_low_20 = stats_20.get('min_low', 0)
            if max_high_20 > 0 and close >= max_high_20:
                nh_1m += 1
            elif min_low_20 > 0 and close <= min_low_20:
                nl_1m += 1

        row['nh'] = nh
        row['nl'] = nl
        row['nh_3m'] = nh_3m
        row['nl_3m'] = nl_3m
        row['nh_1m'] = nh_1m
        row['nl_1m'] = nl_1m

    return row if len(row) > 1 else None


def _aggregate_base_data(data, data_type, period):
    """按周期聚合 base_data_daily 数据"""
    from datetime import date as _date
    import calendar

    buckets = {}
    for d in data:
        s = str(d['date'])
        if len(s) < 8:
            continue
        y, m, day = int(s[0:4]), int(s[4:6]), int(s[6:8])

        if period == 'week':
            iso_year, iso_week, _ = _date(y, m, day).isocalendar()
            key = f"{iso_year}W{iso_week:02d}"
        elif period == 'month':
            key = f"{y}-{m:02d}"
        elif period == 'quarter':
            q = (m - 1) // 3 + 1
            key = f"{y}Q{q}"
        elif period == 'year':
            key = f"{y}"
        else:
            key = s

        if key not in buckets:
            buckets[key] = {'date': key}
            if data_type == 'cr5':
                buckets[key]['cr5_sum'] = 0
                buckets[key]['cr10_sum'] = 0
                buckets[key]['count'] = 0
            elif data_type == 'ma':
                buckets[key]['ma50_sum'] = 0
                buckets[key]['ma20_sum'] = 0
                buckets[key]['count'] = 0
            elif data_type == 'nh-nl':
                buckets[key]['nh'] = 0
                buckets[key]['nl'] = 0
                buckets[key]['nh_3m'] = 0
                buckets[key]['nl_3m'] = 0
                buckets[key]['nh_1m'] = 0
                buckets[key]['nl_1m'] = 0

        b = buckets[key]
        if data_type == 'cr5':
            b['cr5_sum'] += d.get('cr5_pct', 0) or 0
            b['cr10_sum'] += d.get('cr10_pct', 0) or 0
            b['count'] += 1
        elif data_type == 'ma':
            b['ma50_sum'] += d.get('ma50_pct', 0) or 0
            b['ma20_sum'] += d.get('ma20_pct', 0) or 0
            b['count'] += 1
        elif data_type == 'nh-nl':
            b['nh'] += d.get('nh', 0) or 0
            b['nl'] += d.get('nl', 0) or 0
            b['nh_3m'] += d.get('nh_3m', 0) or 0
            b['nl_3m'] += d.get('nl_3m', 0) or 0
            b['nh_1m'] += d.get('nh_1m', 0) or 0
            b['nl_1m'] += d.get('nl_1m', 0) or 0

    # 计算均值
    result = []
    for b in sorted(buckets.values(), key=lambda x: x['date']):
        item = {'date': b['date']}
        if data_type == 'cr5' and b.get('count', 0) > 0:
            item['cr5_pct'] = round(b['cr5_sum'] / b['count'], 4)
            item['cr10_pct'] = round(b['cr10_sum'] / b['count'], 4)
        elif data_type == 'ma' and b.get('count', 0) > 0:
            item['ma50_pct'] = round(b['ma50_sum'] / b['count'], 1)
            item['ma20_pct'] = round(b['ma20_sum'] / b['count'], 1)
        elif data_type == 'nh-nl':
            item['nh'] = b['nh']
            item['nl'] = b['nl']
            item['nh_3m'] = b['nh_3m']
            item['nl_3m'] = b['nl_3m']
            item['nh_1m'] = b['nh_1m']
            item['nl_1m'] = b['nl_1m']
        result.append(item)
    return result