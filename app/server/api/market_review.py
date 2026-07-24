"""
市场复盘数据 API
提供全栈量化复盘报告所需的数据
盘后预计算落库，后续直接读取
"""
import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Query
from datetime import datetime

from app.data.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/market-review", tags=["market-review"])


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
        # avg_chg先占位，后面用all_ind_stocks计算

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
        {'_id': 0, 'stock_code': 1, 'close': 1, 'amount': 1, 'chg_pct': 1}
    )}

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

        overview_indices.append({
            'code': code,
            'name': c['name'],
            'close': round(t.get('close', 0), 2) if t else 0,
            'pct_chg': pct_chg,
            'comment': '',
            'amount_today': round(today_amt / 1e8, 1) if today_amt else 0,
            'amount_yesterday': 0,
            'amount_ma5': ma5_amt,
            'amount_ma20': ma20_amt,
        })

    overview_indices.sort(key=lambda x: -x['pct_chg'])
    if overview_indices:
        overview_indices[0]['comment'] = '表现最强，领先全场'
    for idx in overview_indices:
        if '科创' in idx['name']:
            if idx['pct_chg'] >= 3.0:
                idx['comment'] = '🚀 科创爆发'
            elif idx['pct_chg'] >= 1.5:
                idx['comment'] = '强势'
        elif not idx['comment']:
            if abs(idx['pct_chg']) >= 1.0:
                idx['comment'] = '偏强' if idx['pct_chg'] > 0 else '遭遇调整'
            elif abs(idx['pct_chg']) >= 0.5:
                idx['comment'] = '整体均衡' if idx['pct_chg'] > 0 else '小幅回调'
            else:
                idx['comment'] = '窄幅震荡' if idx['pct_chg'] > 0 else '小盘股偏弱'

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
                'close': i['close'],
                'pct_chg': i['pct_chg'],
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
        'compute_time': datetime.now().isoformat(),
    }

    # 低位潜力板块
    try:
        lps_result = analyze_low_position_sectors(trade_date)
        result['low_position_sectors'] = lps_result.get('sectors', [])
    except Exception as e:
        logger.warning(f"计算低位潜力板块失败: {e}")
        result['low_position_sectors'] = []

    # 异动活跃板块
    try:
        active_result = analyze_active_sectors(trade_date)
        result['active_sectors'] = active_result.get('sectors', [])
    except Exception as e:
        logger.warning(f"计算异动活跃板块失败: {e}")
        result['active_sectors'] = []

    # 新高强力板块（使用统一的 analyze_new_high_blocks）
    try:
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

    # 落库（upsert）
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


def generate_market_overview(latest_date: Optional[str] = None) -> Dict[str, Any]:
    """
    生成主要大盘指数涨跌幅 + 核心结论
    返回结构化 JSON 供前端渲染
    """
    import pandas as pd
    db = get_db()

    # 从 index_basics 读取启用的指数（排除禁用的）
    try:
        index_cursor = db['index_basics'].find(
            {'is_disable': {'$ne': True}},
            {'_id': 0, 'code': 1, 'name': 1}
        )
    except Exception:
        index_cursor = db['index_basics'].find({}, {'_id': 0, 'code': 1, 'name': 1})
    index_config = list(index_cursor)

    if not index_config:
        return {'success': False, 'message': '无指数配置'}

    # 获取交易日（使用共用方法）
    if not latest_date:
        latest_date = get_latest_trade_date(db)
    if not latest_date:
        return {'success': False, 'message': '无交易数据'}
    
    # 获取最新两个交易日
    dates = sorted(db['index_daily'].distinct('trade_date'), reverse=True)
    if len(dates) < 2:
        return {'success': False, 'message': '交易日数据不足'}
    
    if latest_date:
        today = latest_date
        # 找前一个交易日
        yesterday_candidates = [d for d in dates if d < today]
        yesterday = yesterday_candidates[0] if yesterday_candidates else today
    else:
        today, yesterday = dates[0], dates[1]

    # 批量拉取指数数据（直接使用预计算的chg_pct）
    index_codes = [c['code'] for c in index_config]
    cursor = db['index_daily'].find(
        {'stock_code': {'$in': index_codes}, 'trade_date': today},
        {'_id': 0, 'stock_code': 1, 'trade_date': 1, 'close': 1, 'chg_pct': 1}
    )
    rows = list(cursor)
    if not rows:
        return {'success': False, 'message': '无指数数据'}

    df = pd.DataFrame(rows)
    if df.empty:
        return {'success': False, 'message': '无指数数据'}

    # 合并配置名称
    config_map = {c['code']: c for c in index_config}
    df['code'] = df['stock_code']  # 添加code列以兼容后续代码
    df['name'] = df['stock_code'].map(lambda c: config_map.get(c, {}).get('name', c))
    df['code_display'] = df['stock_code'].map(lambda c: config_map.get(c, {}).get('tdx_code', c))
    df['pct_chg'] = df['chg_pct'].fillna(0)

    # 过滤掉无效数据
    df = df.dropna(subset=['close']).reset_index(drop=True)
    if df.empty:
        return {'success': False, 'message': '无有效指数数据'}

    # 排序（按涨跌幅降序）
    pivot = df.sort_values('pct_chg', ascending=False).reset_index(drop=True)

    # 自动生成点评
    max_idx = pivot.iloc[0]
    min_idx = pivot.iloc[-1]

    # 指数含义映射
    INDEX_MEANING = {
        '上证指数': '老登股',
        '创业板指': '海外链',
        '科创50': '国产科技',
        '深圳综指': '新兴成长、中小市值',
        '微盘股': '增量资金敏感',
        '平均股价': '全市场均价',
    }

    def _gen_comment(row):
        name = row['name']
        pct = row['pct_chg']
        meaning = INDEX_MEANING.get(name, '')

        # 最强
        if row.name == max_idx.name:
            return f'表现最强，{meaning}领涨' if meaning else '表现最强，领先全场'
        # 最弱
        if row.name == min_idx.name:
            return f'表现最弱，{meaning}承压' if meaning else '表现最弱，明显落后'

        # 按涨跌幅点评
        abs_pct = abs(pct)
        if pct > 2.0:
            return f'大涨，{meaning}资金涌入' if meaning else '大涨'
        elif pct > 1.0:
            return f'偏强，{meaning}表现积极' if meaning else '偏强'
        elif pct > 0.5:
            return '小幅上涨'
        elif pct > 0:
            return '窄幅震荡'
        elif pct > -0.5:
            return '小幅回调'
        elif pct > -1.0:
            return '偏弱'
        else:
            return f'大跌，{meaning}承压' if meaning else '大跌'

    pivot['comment'] = pivot.apply(_gen_comment, axis=1)

    # 构建指数列表
    indices = []
    for _, row in pivot.iterrows():
        indices.append({
            'code': row['code'],
            'name': row['name'],
            'close': round(float(row['close']), 2),
            'pct_chg': float(row['pct_chg']),
            'comment': row['comment'],
        })

    # 获取指数PE_TTM（从 index_basics 读取，由 sync-index-pe 写入）
    try:
        pe_map = {}
        pe_cursor = db['index_basics'].find(
            {'pe_ttm': {'$exists': True, '$ne': None}, 'is_disable': {'$ne': True}},
            {'_id': 0, 'code': 1, 'pe_ttm': 1}
        )
        for doc in pe_cursor:
            pe_map[doc['code']] = round(float(doc['pe_ttm']), 2)
        for idx in indices:
            if idx['code'] in pe_map:
                idx['pe_ttm'] = pe_map[idx['code']]
    except Exception as e:
        logger.warning(f"[PE] 读取指数PE失败: {e}")

    # NLP 核心结论
    leader = pivot.iloc[0]
    laggard = pivot.iloc[-1]

    # 找科创50
    kc50 = pivot[pivot['name'].str.contains('科创', na=False)]
    kc50_pct = float(kc50.iloc[0]['pct_chg']) if not kc50.empty else 0

    # 找创业板
    cyb = pivot[pivot['name'].str.contains('创业板', na=False)]
    cyb_pct = float(cyb.iloc[0]['pct_chg']) if not cyb.empty else 0

    # 指数含义映射
    INDEX_MEANING = {
        '上证指数': '老登股（消费、金融保险、银行等）',
        '创业板指': '海外链',
        '科创50': '国产科技',
        '深圳综指': '新兴成长型企业与中小市值',
        '微盘股': '增量资金敏感型，盘子极轻',
        '平均股价': '全市场均价水平',
    }

    # 市场风格判定
    leader = pivot.iloc[0]
    laggard = pivot.iloc[-1]

    # 找关键指数
    kc50 = pivot[pivot['name'].str.contains('科创', na=False)]
    kc50_pct = float(kc50.iloc[0]['pct_chg']) if not kc50.empty else 0

    cyb = pivot[pivot['name'].str.contains('创业板', na=False)]
    cyb_pct = float(cyb.iloc[0]['pct_chg']) if not cyb.empty else 0

    sh_idx = pivot[pivot['code'] == '000001']
    sh_pct = float(sh_idx.iloc[0]['pct_chg']) if not sh_idx.empty else 0

    # 判断市场主线
    tech_strong = kc50_pct > 1.0 or cyb_pct > 1.0  # 科技/成长强
    old_money_strong = sh_pct > 1.0  # 老登股强
    all_up = all(pivot['pct_chg'] > 0)
    all_down = all(pivot['pct_chg'] < 0)

    if tech_strong and not old_money_strong:
        if kc50_pct > cyb_pct:
            style = '国产科技主导'
            detail = f'科创50涨{kc50_pct}%领涨，国产科技线受资金追捧'
        else:
            style = '海外链领涨'
            detail = f'创业板涨{cyb_pct}%领涨，海外市场映射效应明显'
    elif old_money_strong and not tech_strong:
        style = '价值回归'
        detail = f'上证指数涨{sh_pct}%，消费金融等老登股发力'
    elif all_up:
        style = '全面做多'
        detail = '全线上涨，市场做多情绪高涨'
    elif all_down:
        style = '全面承压'
        detail = '全线下跌，市场避险情绪升温'
    elif leader['pct_chg'] > 0.5 and laggard['pct_chg'] < -0.5:
        style = '结构分化'
        detail = f'{leader["name"]}领涨，但{laggard["name"]}明显拖累'
    else:
        style = '窄幅震荡'
        detail = '市场等待方向选择'

    # 构建核心结论
    conclusion = f"【{style}】{detail}。"
    conclusion += f"涨幅居前：{leader['name']}（+{leader['pct_chg']}%），"
    conclusion += f"表现最弱：{laggard['name']}（{laggard['pct_chg']:+.1f}%）"

    # 补充特殊点评
    if kc50_pct > 2.0:
        conclusion += f"。科创50暴涨{kc50_pct}%，国产替代主线持续强势"
    elif cyb_pct > 2.0:
        conclusion += f"。创业板指大涨{cyb_pct}%，成长风格占优"
    elif sh_pct < -1.0:
        conclusion += f"。上证跌{sh_pct}%，权重股集体承压"


    return {
        'success': True,
        'trade_date': today,
        'indices': indices,
    }


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


def _get_latest_trade_date() -> str:
    db = get_db()
    doc = db['stock_daily'].find_one({}, sort=[('trade_date', -1)])
    return doc['trade_date'] if doc else ''


def _get_daily_data_for_stock(stock_code: str, end_date: str, limit: int = 260) -> List[Dict]:
    db = get_db()
    cursor = db['stock_daily'].find(
        {'stock_code': stock_code, 'trade_date': {'$lte': end_date}},
        {'_id': 0, 'trade_date': 1, 'close': 1, 'high': 1}
    ).sort('trade_date', -1).limit(limit)
    return list(cursor)


def _calc_market_summary(latest_date: str) -> Dict[str, Any]:
    db = get_db()

    total_pipeline = [
        {'$match': {'trade_date': latest_date}},
        {'$group': {'_id': None, 'count': {'$sum': 1}}}
    ]
    total_result = list(db['stock_daily'].aggregate(total_pipeline))
    total_stocks = total_result[0]['count'] if total_result else 0

    if total_stocks == 0:
        return {'total_stocks': 0, 'above_ma50_count': 0, 'above_ma50_pct': 0, 'new_high_count': 0}

    ma50_pipeline = [
        {'$match': {'trade_date': latest_date, 'close': {'$gt': 0}}},
        {'$lookup': {
            'from': 'stock_daily',
            'let': {'code': '$stock_code', 'date': '$trade_date'},
            'pipeline': [
                {'$match': {
                    '$expr': {'$eq': ['$stock_code', '$$code']},
                    'trade_date': {'$lte': '$$date'}
                }},
                {'$sort': {'trade_date': -1}},
                {'$limit': 50},
                {'$group': {'_id': None, 'avg_close': {'$avg': '$close'}}}
            ],
            'as': 'ma50_data'
        }},
        {'$addFields': {
            'ma50': {'$arrayElemAt': ['$ma50_data.avg_close', 0]}
        }},
        {'$match': {
            '$expr': {'$gt': ['$close', {'$ifNull': ['$ma50', 0]}]}
        }},
        {'$group': {'_id': None, 'count': {'$sum': 1}}}
    ]
    ma50_result = list(db['stock_daily'].aggregate(ma50_pipeline))
    above_ma50_count = ma50_result[0]['count'] if ma50_result else 0
    above_ma50_pct = round(above_ma50_count / total_stocks * 100, 1) if total_stocks > 0 else 0

    return {
        'total_stocks': total_stocks,
        'above_ma50_count': above_ma50_count,
        'above_ma50_pct': above_ma50_pct,
        'new_high_count': 0
    }


def _calc_market_summary_fast(latest_date: str) -> Dict[str, Any]:
    db = get_db()

    total_result = list(db['stock_daily'].aggregate([
        {'$match': {'trade_date': latest_date}},
        {'$group': {'_id': None, 'count': {'$sum': 1}}}
    ]))
    total_stocks = total_result[0]['count'] if total_result else 0

    if total_stocks == 0:
        return {'total_stocks': 0, 'above_ma50_count': 0, 'above_ma50_pct': 0, 'new_high_count': 0,
                'above_ma50_stocks': [], 'new_high_stocks': []}

    # 直接用冗余字段 ma50
    today_docs = list(db['stock_daily'].find(
        {'trade_date': latest_date, 'close': {'$gt': 0}},
        {'_id': 0, 'stock_code': 1, 'close': 1, 'high': 1, 'ma50': 1, 'chg_pct': 1}
    ))
    if not today_docs:
        return {'total_stocks': total_stocks, 'above_ma50_count': 0, 'above_ma50_pct': 0, 'new_high_count': 0,
                'above_ma50_stocks': [], 'new_high_stocks': []}

    stock_codes = [d['stock_code'] for d in today_docs]
    today_map = {d['stock_code']: d for d in today_docs}

    # 获取股票名称（只获取启用的股票）
    name_cursor = db['stock_basics'].find(
        {'is_disable': {'$ne': True}},
        {'_id': 0, 'stock_code': 1, 'stock_name': 1}
    )
    name_map = {d['stock_code']: d.get('stock_name', '') for d in name_cursor}

    # MA50广度（直接用冗余字段）
    import math
    above_ma50_stocks = []
    for d in today_docs:
        if d.get('ma50') and d['close'] > d['ma50']:
            above_ma50_stocks.append({
                'code': d['stock_code'],
                'name': name_map.get(d['stock_code'], d['stock_code']),
                'pct_chg': d.get('chg_pct', 0) or 0,
                'close': d.get('close', 0)
            })

    # 历史新高：用聚合管道查最近365天最高收盘价（年新高）
    from datetime import datetime as _dt, timedelta
    try:
        date_obj = _dt.strptime(latest_date, '%Y%m%d')
        hist_start = (date_obj - timedelta(days=365)).strftime('%Y%m%d')
    except Exception:
        hist_start = latest_date

    # 统一用收盘价 >= 历史最高收盘价
    high_cursor = db['stock_daily'].aggregate([
        {'$match': {
            'stock_code': {'$in': stock_codes},
            'trade_date': {'$gte': hist_start},
            'close': {'$gt': 0}
        }},
        {'$group': {'_id': '$stock_code', 'max_close': {'$max': '$close'}}}
    ])
    high_map = {d['_id']: d['max_close'] for d in high_cursor}

    new_high_stocks = []
    for code, d in today_map.items():
        if high_map.get(code, 0) > 0 and d.get('close', 0) >= high_map[code]:
            new_high_stocks.append({
                'code': code,
                'name': name_map.get(code, code),
                'pct_chg': d.get('chg_pct', 0) or 0,
                'close': d.get('close', 0)
            })

    above_ma50_count = len(above_ma50_stocks)
    new_high_count = len(new_high_stocks)
    above_ma50_pct = round(above_ma50_count / total_stocks * 100, 1) if total_stocks > 0 else 0

    # 按涨幅排序
    above_ma50_stocks.sort(key=lambda x: x['pct_chg'], reverse=True)
    new_high_stocks.sort(key=lambda x: x['pct_chg'], reverse=True)

    # 获取股票名称（只获取启用的股票）
    name_cursor = db['stock_basics'].find(
        {'is_disable': {'$ne': True}},
        {'_id': 0, 'stock_code': 1, 'stock_name': 1}
    )
    name_map = {d['stock_code']: d.get('stock_name', '') for d in name_cursor}

    for s in above_ma50_stocks:
        s['name'] = name_map.get(s['code'], s['code'])
    for s in new_high_stocks:
        s['name'] = name_map.get(s['code'], s['code'])

    return {
        'total_stocks': total_stocks,
        'above_ma50_count': above_ma50_count,
        'above_ma50_pct': above_ma50_pct,
        'new_high_count': new_high_count,
        'above_ma50_stocks': above_ma50_stocks,
        'new_high_stocks': new_high_stocks
    }


def _calc_strong_stocks(latest_date: str) -> List[Dict[str, Any]]:
    db = get_db()

    from datetime import datetime as _dt, timedelta
    try:
        date_obj = _dt.strptime(latest_date, '%Y%m%d')
        hist_start = (date_obj - timedelta(days=365)).strftime('%Y%m%d')
    except Exception:
        hist_start = latest_date

    today_docs = list(db['stock_daily'].find(
        {'trade_date': latest_date, 'close': {'$gt': 0}},
        {'_id': 0, 'stock_code': 1, 'close': 1, 'high': 1, 'chg_pct': 1}
    ))
    if not today_docs:
        return []

    stock_codes = [d['stock_code'] for d in today_docs]
    today_map = {d['stock_code']: d for d in today_docs}

    # 用聚合管道计算365天最高价（年新高）
    high_cursor = db['stock_daily'].aggregate([
        {'$match': {
            'stock_code': {'$in': stock_codes},
            'trade_date': {'$gte': hist_start},
            'high': {'$gt': 0}
        }},
        {'$group': {'_id': '$stock_code', 'max_high': {'$max': '$high'}}}
    ])
    high_map = {d['_id']: d['max_high'] for d in high_cursor}

    name_cursor = db['stock_basics'].find(
        {'is_disable': {'$ne': True}}, {'_id': 0, 'stock_code': 1, 'stock_name': 1}
    )
    name_map = {d['stock_code']: d.get('stock_name', '') for d in name_cursor}

    industry_map = _build_stock_industry_map()

    strong_stocks = []
    for code in stock_codes:
        today = today_map.get(code)
        if not today or today['close'] <= 0:
            continue

        hhv_high = high_map.get(code, 0)
        if hhv_high <= 0:
            continue

        ratio = today['close'] / hhv_high
        if ratio < 0.9:
            continue

        pct_chg = today.get('chg_pct', 0) or 0

        strong_stocks.append({
            'code': code,
            'name': name_map.get(code, code),
            'close': today['close'],
            'pct_chg': pct_chg,
            'ratio_250h': round(ratio * 100, 1),
            'is_touch_250h': ratio >= 0.99,
            'industry': industry_map.get(code, '其他')
        })

    strong_stocks.sort(key=lambda x: x['pct_chg'], reverse=True)
    return strong_stocks[:50]


def _calc_industry_cluster(strong_stocks: List[Dict]) -> List[Dict[str, Any]]:
    from collections import defaultdict
    industry_map = defaultdict(list)

    for s in strong_stocks:
        ind = s.get('industry') or '其他'
        industry_map[ind].append(s['name'])

    total = len(strong_stocks) if strong_stocks else 1
    clusters = []
    for ind, stocks in sorted(industry_map.items(), key=lambda x: -len(x[1])):
        clusters.append({
            'industry': ind,
            'count': len(stocks),
            'pct': round(len(stocks) / total * 100, 1),
            'stocks': stocks[:10]
        })

    return clusters[:10]


def calc_market_signals(latest_date: Optional[str] = None) -> Dict[str, Any]:
    """
    A股运行状态量化指标
    返回: MA50广度、强势股、历史新高 + 自动解读
    使用冗余字段 ma50, chg_pct 等，无需加载历史数据
    """
    from datetime import datetime as _dt, timedelta
    from collections import defaultdict
    import numpy as np
    db = get_db()

    # 获取交易日（使用共用方法）
    if not latest_date:
        latest_date = get_latest_trade_date(db)
    if not latest_date:
        return {'success': False, 'message': '无交易数据'}

    # 直接获取今日全市场数据（含冗余字段 ma50, chg_pct, high, close）
    today_docs = list(db['stock_daily'].find(
        {'trade_date': latest_date, 'close': {'$gt': 0}},
        {'_id': 0, 'stock_code': 1, 'close': 1, 'high': 1, 'ma50': 1, 'chg_pct': 1,
         'rps_20': 1, 'rps_50': 1, 'rps_120': 1, 'rps_250': 1}
    ))
    if not today_docs:
        return {'success': False, 'message': '今日无交易数据'}

    total_stocks = len(today_docs)

    # 获取上市日期（判断上市天数，只获取启用的股票）
    list_date_map = {}
    basics_cursor = db['stock_basics'].find(
        {'is_disable': {'$ne': True}}, {'_id': 0, 'stock_code': 1, 'list_date': 1}
    )
    for b in basics_cursor:
        ld = b.get('list_date')
        if ld:
            list_date_map[b['stock_code']] = str(ld)

    def _days_listed(code):
        ld = list_date_map.get(code)
        if not ld or len(ld) < 8:
            return 9999
        try:
            d = _dt.strptime(ld, '%Y%m%d')
            now = _dt.strptime(latest_date, '%Y%m%d')
            return (now - d).days
        except:
            return 9999

    # ====== 指标一：MA50广度（直接用 ma50 字段） ======
    above_ma50_count = 0
    # ====== 指标二：强势股（直接用 rps/chg_pct 字段） ======
    strong_stocks = []
    # ====== 指标三：历史新高（从 market_daily 读取已缓存数据） ======
    cached_market = db['market_daily'].find_one({'trade_date': latest_date}, {'_id': 0, 'new_high': 1})
    new_high_count = cached_market.get('new_high', {}).get('total_count', 0) if cached_market else 0

    # 获取股票名称（只获取启用的股票）
    name_cursor = db['stock_basics'].find(
        {'is_disable': {'$ne': True}}, {'_id': 0, 'stock_code': 1, 'stock_name': 1}
    )
    name_map = {d['stock_code']: d.get('stock_name', '') for d in name_cursor}

    for d in today_docs:
        code = d['stock_code']

        # MA50 广度（直接用冗余字段）
        ma50 = d.get('ma50')
        if ma50 and d['close'] > ma50:
            above_ma50_count += 1

        # 强势股：rps_20+rps_50+max(rps_120,rps_250) > 270
        rps20 = d.get('rps_20') or 0
        rps50 = d.get('rps_50') or 0
        rps120 = d.get('rps_120') or 0
        rps250 = d.get('rps_250') or 0
        rps_sum = rps20 + rps50 + max(rps120, rps250)
        if rps_sum > 270 and _days_listed(code) > 30:
            strong_stocks.append({
                'code': code,
                'name': name_map.get(code, code),
                'pct_chg': d.get('chg_pct', 0) or 0,
                'close': d.get('close', 0),
            })

    above_ma50_pct = round(above_ma50_count / total_stocks * 100, 1) if total_stocks > 0 else 0
    strong_stocks.sort(key=lambda x: x['pct_chg'], reverse=True)
    strong_top50 = strong_stocks[:50]

    # 获取强势股的行业分布（取占比最高的行业）
    industry_map = _build_stock_industry_map()
    top_industry = '科技成长'
    if strong_top50:
        from collections import Counter
        ind_counts = Counter()
        for s in strong_top50:
            ind = industry_map.get(s['code'], '其他')
            ind_counts[ind] += 1
        if ind_counts:
            top_industry = ind_counts.most_common(1)[0][0]

    # 信号解读
    signal_1 = f"占比约 {above_ma50_pct}%"
    signal_2 = "全市场最强者"
    signal_3 = "结构性做多力量强" if new_high_count > 200 else "局部活跃"

    # 动态文本生成器
    if above_ma50_pct < 35 and new_high_count > 150:
        interpretation = (
            '大盘仅 ' + str(above_ma50_pct) + '% 站上50日线，但 ' + str(new_high_count) + ' 只个股创历史新高，'
            '呈现典型"指数冰点+个股井喷"背离。'
            '米内尔维尼指出这是"先行者现象"——机构正集中建仓 ' + top_industry + ' 等领头羊板块。'
            '策略：放弃弱势股，聚焦距离250日高点<10%的强势品种，等待口袋突破信号。'
        )
    else:
        if above_ma50_pct > 70:
            market_phase = "市场强势"
        elif above_ma50_pct > 50:
            market_phase = "分歧偏强"
        elif above_ma50_pct > 30:
            market_phase = "整体分歧"
        else:
            market_phase = "整体弱势"

        interpretation = (
            f"站上50日线占比 {above_ma50_pct}%，{market_phase}。"
            f"{new_high_count} 只创历史新高"
            f"{'，局部做多动能极强。' if new_high_count > 100 else '，局部仍有做多动能。'}"
        )

    # 获取新高板块数据（用于综合分析）
    # 直接从 market_daily 或 base_data_daily 读取，避免重复计算
    cached_market = db['market_daily'].find_one({'trade_date': latest_date}, {'_id': 0, 'new_high': 1})
    if cached_market and cached_market.get('new_high', {}).get('clusters'):
        clusters = cached_market['new_high']['clusters']
        total_new_high = cached_market['new_high'].get('total_count', 0)
    else:
        # 从 base_data_daily 读取新高数（快）
        base_doc = db['base_data_daily'].find_one({'date': latest_date}, {'_id': 0, 'nh': 1, 'nl': 1})
        total_new_high = (base_doc.get('nh', 0) if base_doc else 0)  # 用nh近似
        clusters = []
    top_cluster = clusters[0] if clusters else None

    # 综合分析文案
    interpretation = _generate_combined_interpretation(
        above_ma50_pct=above_ma50_pct,
        new_high_count=new_high_count,
        total_stocks=total_stocks,
        top_industry=top_industry,
        total_new_high=total_new_high,
        top_cluster=top_cluster
    )

    return {
        'success': True,
        'trade_date': latest_date,
        'total_stocks': total_stocks,
        'above_ma50_pct': above_ma50_pct,
        'new_high_count': new_high_count,
        'strong_count': len(strong_top50),
        'interpretation': interpretation,
    }


def _generate_combined_interpretation(above_ma50_pct: float, new_high_count: int, 
                                       total_stocks: int, top_industry: str,
                                       total_new_high: int, top_cluster: dict) -> str:
    """生成智能整合的综合分析文案"""
    
    # 判断市场状态
    if above_ma50_pct >= 70:
        market_state = "强势"
        market_desc = "市场整体强势，多头氛围浓厚"
    elif above_ma50_pct >= 50:
        market_state = "偏强"
        market_desc = "市场分歧偏强，结构性机会明显"
    elif above_ma50_pct >= 35:
        market_state = "分化"
        market_desc = "市场分化明显，资金抱团主线"
    else:
        market_state = "弱势"
        market_desc = "大盘整体弱势，仅局部个股活跃"
    
    # 判断板块效应
    has_block_effect = top_cluster and top_cluster.get('pct', 0) > 10
    block_industry = top_cluster['industry'] if top_cluster else None
    block_count = top_cluster['count'] if top_cluster else 0
    
    # 综合分析
    parts = []
    
    # 开篇：市场状态
    parts.append(f"【市场状态】{market_desc}。站上50日线占比 {above_ma50_pct}%，{new_high_count} 只个股创历史新高。")
    
    # 板块效应分析
    if has_block_effect and block_industry:
        if market_state == "弱势":
            parts.append(
                f"【板块效应】尽管大盘弱势，但 {block_industry} 等板块呈现强烈的新高个股成批涌现特征"
                f"（{block_count}只新高），呈现典型的指数冰点+个股井喷背离。"
                f"这往往是先行者现象——机构正逆势建仓领头羊板块。"
            )
        else:
            parts.append(
                f"【板块效应】{block_industry} 等板块呈现新高个股成批涌现特征"
                f"（{block_count}只新高），根据欧奈尔CANSLIM理论，"
                f"这是机构板块化建仓信号，该方向已确立为市场主线。"
            )
    elif total_new_high > 100:
        if market_state == "弱势":
            parts.append(
                f"【板块效应】大盘弱势但有 {total_new_high} 只个股创新高，"
                f"呈现指数冰点+个股井喷背离。"
                f"米内尔维尼指出这是先行者现象——机构正集中建仓 {top_industry} 等领头羊板块。"
            )
        else:
            parts.append(
                f"【板块效应】{total_new_high} 只个股创新高，局部做多动能极强。"
                f"需关注领头羊板块 {top_industry} 的持续性。"
            )
    else:
        parts.append(f"【板块效应】新高股数量较少（{total_new_high}只），暂未形成明显板块效应。")
    
    # 策略建议
    if market_state == "弱势" and has_block_effect:
        parts.append("【策略建议】放弃弱势股，聚焦领头羊板块中距离250日高点<10%的强势品种，等待口袋突破信号。")
    elif market_state == "强势":
        parts.append("【策略建议】市场强势，可积极参与，关注领头羊板块的回调买入机会。")
    elif market_state == "分化":
        parts.append("【策略建议】市场分化明显，聚焦领头羊板块，回避弱势板块。")
    else:
        parts.append("【策略建议】控制仓位，等待市场企稳信号，关注逆势走强的板块。")
    
    return '\n'.join(parts)


def analyze_new_high_blocks(latest_date: Optional[str] = None) -> Dict[str, Any]:
    """
    新高强力板块分析与板块效应聚类
    
    筛选规则：
    1. 板块筛选：RPS10+RPS20+RPS50 > 250（三者之和）
    2. 个股筛选：当日收盘价 >= 历史最高收盘价 * 0.9（接近新高）
    
    返回: 接近新高股池 + 行业聚类Top5（先锋/中军/后排）
    """
    from datetime import datetime as _dt, timedelta
    from collections import defaultdict, Counter
    db = get_db()

    # 获取交易日（使用共用方法）
    if not latest_date:
        latest_date = get_latest_trade_date(db)
    if not latest_date:
        return {'success': False, 'message': '无交易数据'}

    # 获取今日全市场数据（含 chg_pct, chg_20d, amount）
    today_docs = list(db['stock_daily'].find(
        {'trade_date': latest_date, 'close': {'$gt': 0}},
        {'_id': 0, 'stock_code': 1, 'close': 1, 'chg_pct': 1, 'chg_20d': 1, 'chg_50d': 1, 'amount': 1}
    ))
    if not today_docs:
        return {'success': False, 'message': '今日无交易数据'}

    today_map = {d['stock_code']: d for d in today_docs}
    stock_codes = list(today_map.keys())

    # 用聚合管道在数据库中计算历史最高收盘价（最近1年，年新高）
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

    # 筛选接近新高股：今日收盘 >= 历史最高收盘价 * 0.9
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

    # 获取板块RPS强劲的板块（RPS10/RPS20/RPS50其中之一>90）
    enabled_sector_docs = list(db['sector_basics'].find(
        {'is_disable': {'$ne': True}, 'stock_count': {'$gt': 0}},
        {'_id': 0, 'code': 1, 'name': 1, 'stock_codes': 1}
    ))
    enabled_sector_codes = {doc['code'] for doc in enabled_sector_docs}

    # 获取板块RPS数据，筛选RPS10+RPS20+RPS50 > 250的板块
    sector_rps_cursor = db['sector_daily'].find(
        {
            'trade_date': latest_date,
            'stock_code': {'$in': list(enabled_sector_codes)},
        },
        {'_id': 0, 'stock_code': 1, 'rps_10': 1, 'rps_20': 1, 'rps_50': 1}
    )
    # {板块代码: {rps_10, rps_20, rps_50, rps_sum}} - 只保留RPS和>250的板块
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

    # 构建板块代码→板块信息映射
    sector_info_map = {}
    for doc in enabled_sector_docs:
        sector_info_map[doc['code']] = doc

    # 按板块统计新高个股数
    sector_new_high = {}  # {板块代码: [新高个股列表]}
    for s in new_high_stocks:
        code = s['code']
        # 查找该股票所属的板块
        for sector_code in strong_sector_rps:
            sector_info = sector_info_map.get(sector_code, {})
            stock_codes_in_sector = set(sector_info.get('stock_codes', []))
            if code in stock_codes_in_sector:
                if sector_code not in sector_new_high:
                    sector_new_high[sector_code] = []
                sector_new_high[sector_code].append(s)

    # 按新高个股数排序，取Top5
    sorted_sectors = sorted(sector_new_high.items(), key=lambda x: -len(x[1]))[:5]

    total_new_high_count = len(new_high_stocks)
    if total_new_high_count == 0 or not sorted_sectors:
        return {
            'success': True,
            'trade_date': latest_date,
            'total_new_high_count': 0,
            'industry_clusters': [],
            'interpretation': '今日强劲板块（RPS>90）无创新高个股。'
        }

    # 获取股票名称
    name_cursor = db['stock_basics'].find(
        {'is_disable': {'$ne': True}}, {'_id': 0, 'stock_code': 1, 'stock_name': 1}
    )
    name_map = {d['stock_code']: d.get('stock_name', '') for d in name_cursor}

    # 获取流通股本（用于计算流通市值）
    liutong_cursor = db['stock_basics'].find(
        {'is_disable': {'$ne': True}, 'liutongguben': {'$gt': 0}}, 
        {'_id': 0, 'stock_code': 1, 'liutongguben': 1}
    )
    liutong_map = {d['stock_code']: d.get('liutongguben', 0) for d in liutong_cursor}

    # 获取股票涨跌幅等数据
    import math
    for s in new_high_stocks:
        today_doc = today_map.get(s['code'], {})
        s['pct_chg'] = today_doc.get('chg_pct', 0) or 0
        s['chg_pct'] = s['pct_chg']
        s['chg_20d'] = today_doc.get('chg_20d', 0) or 0
        s['chg_50d'] = today_doc.get('chg_50d', 0) or 0
        amount = today_doc.get('amount', 0)
        s['amount'] = 0 if amount is None or math.isnan(amount) else amount
        s['name'] = name_map.get(s['code'], s['code'])

    # 构建板块聚类结果
    clusters = []
    for sector_code, stocks in sorted_sectors:
        sector_info = sector_info_map.get(sector_code, {})
        sector_name = sector_info.get('name', sector_code)
        rps_data = strong_sector_rps.get(sector_code, {})
        count = len(stocks)
        pct = round(count / total_new_high_count * 100, 1)

        # 板块涨幅
        sec_data = db['sector_daily'].find_one(
            {'stock_code': sector_code, 'trade_date': latest_date},
            {'_id': 0, 'chg_pct': 1}
        )
        avg_chg = round(sec_data['chg_pct'], 2) if sec_data and sec_data.get('chg_pct') is not None else 0

        # 获取板块全部成分股数据（用于先锋/中军/后排分类）
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

        # 先锋：50日涨幅最高的3只（从全部成分股中选）
        by_chg50 = sorted(all_sector_stocks, key=lambda x: -(x.get('chg_50d', 0) or 0))
        representative = []
        seen_rep = set()
        for s in by_chg50:
            if s['code'] not in seen_rep and len(representative) < 3:
                representative.append(f"{s['name']}(50日{s.get('chg_50d', 0) or 0:+.1f}%, 今日{s.get('chg_pct', 0) or 0:+.1f}%)")
                seen_rep.add(s['code'])

        # 中军：流通市值Top10中50日涨幅最高的3只（从全部成分股中选）
        # 流通市值 = 流通股本 * 收盘价
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

        # 后排：成交额最小的20只中（排除ST），当天涨幅最高的2只（从全部成分股中选）
        non_st = [s for s in all_sector_stocks if 'ST' not in (s.get('name') or '').upper()]
        by_amount_asc = sorted(non_st, key=lambda x: x.get('amount', 0) or 0)[:20]
        by_amount_asc_chg = sorted(by_amount_asc, key=lambda x: -(x.get('chg_pct', 0) or 0))
        followers = [f"{s['name']}({s.get('chg_pct', 0) or 0:+.1f}%)" for s in by_amount_asc_chg[:2]]

        # 按涨幅排序的个股列表
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

    # 欧奈尔文案生成
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
    1. MA10 > MA20
    2. RPS10 > 85（短线爆发力）
    3. RPS50 < 70（长线趋势尚未走强，低位）
    4. 近3天有1天以上 ≥15% 的股票创20日新高
    5. 近5天有4天净新高(20日新高-20日新低) > -10
    """
    from datetime import timedelta
    db = get_db()

    # 获取启用的板块代码列表
    enabled_sector_codes = set(
        doc['code'] for doc in db['sector_basics'].find(
            {'is_disable': {'$ne': True}}, {'_id': 0, 'code': 1}
        )
    )

    # 初筛：MA10>MA20 + RPS10>85 + RPS50<70（只获取启用的板块）
    candidates = list(db['sector_daily'].find(
        {
            'trade_date': trade_date,
            'stock_code': {'$in': list(enabled_sector_codes)},
            'ma10': {'$gt': 0}, 'ma20': {'$gt': 0},
            'rps_10': {'$gt': 85}, 'rps_50': {'$lt': 70},
        },
        {'_id': 0, 'stock_code': 1, 'ma10': 1, 'ma20': 1, 'rps_10': 1, 'rps_20': 1, 'rps_50': 1, 'chg_pct': 1}
    ))
    candidates = [c for c in candidates if c['ma10'] > c['ma20']]

    if not candidates:
        return {'success': True, 'trade_date': trade_date, 'sectors': []}

    # 获取板块名称和成分股（只获取启用的板块）
    sector_map = {}
    for s in db['sector_basics'].find(
        {'is_disable': {'$ne': True}},
        {'_id': 0, 'code': 1, 'name': 1, 'stock_codes': 1}
    ):
        sector_map[s['code']] = s

    # 获取上市日期（只获取启用的股票）
    list_date_map = {}
    for b in db['stock_basics'].find(
        {'is_disable': {'$ne': True}}, {'_id': 0, 'stock_code': 1, 'list_date': 1}
    ):
        ld = b.get('list_date')
        if ld:
            list_date_map[b['stock_code']] = str(ld)

    # 获取流通股本（用于计算流通市值）
    liutong_map = {}
    for b in db['stock_basics'].find(
        {'is_disable': {'$ne': True}, 'liutongguben': {'$gt': 0}}, 
        {'_id': 0, 'stock_code': 1, 'liutongguben': 1}
    ):
        liutong_map[b['stock_code']] = b.get('liutongguben', 0)

    # 获取近60天交易日
    all_dates = sorted(db['stock_daily'].distinct('trade_date', {
        'trade_date': {'$gte': (datetime.strptime(trade_date, '%Y%m%d') - timedelta(days=60)).strftime('%Y%m%d')}
    }))

    # 加载股票日线数据
    cursor = db['stock_daily'].find(
        {'trade_date': {'$in': all_dates}, 'close': {'$gt': 0}},
        {'_id': 0, 'stock_code': 1, 'trade_date': 1, 'close': 1}
    )
    stock_data = {}
    for d in cursor:
        stock_data.setdefault(d['stock_code'], {})[d['trade_date']] = d['close']

    # 获取最近5个交易日
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

        # 计算近5天的20日新高/新低
        daily_nets = []
        daily_pcts = []
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
                elif close <= mn:
                    nl += 1
            daily_nets.append(nh - nl)
            pct = round(nh / total * 100, 1) if total > 0 else 0
            daily_pcts.append(pct)

        # 条件4: 近3天有1天 ≥15%
        last3_pcts = daily_pcts[:3]
        has15 = any(p >= 15 for p in last3_pcts)
        if not has15:
            continue

        # 条件5: 近5天有4天净新高 > -10
        days_above_minus10 = sum(1 for n in daily_nets if n > -10)
        if days_above_minus10 < 4:
            continue

        # 获取先锋/中军/后排（复用新高板块聚类逻辑）
        # 成分股日线数据
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

        # 先锋：50日涨幅最高的3只
        by_chg50 = sorted(all_stocks, key=lambda x: -(x.get('chg_50d', 0) or 0))[:3]
        pioneer = [f"{s['name']}(50日{s.get('chg_50d', 0) or 0:+.1f}%, 今日{s.get('chg_pct', 0) or 0:+.1f}%)" for s in by_chg50]

        # 中军：流通市值Top10中50日涨幅最高的3只
        # 流通市值 = 流通股本 * 收盘价
        for s in all_stocks:
            liutong = liutong_map.get(s.get('stock_code'), 0)
            close = s.get('close', 0) or 0
            s['_float_mv'] = liutong * close / 1e8 if liutong and close else 0
        by_mv = sorted(all_stocks, key=lambda x: -(x.get('_float_mv', 0) or 0))[:10]
        by_mv_chg50 = sorted(by_mv, key=lambda x: -(x.get('chg_50d', 0) or 0))[:3]
        main_force = [f"{s['name']}(50日{s.get('chg_50d', 0) or 0:+.1f}%, 今日{s.get('chg_pct', 0) or 0:+.1f}%)" for s in by_mv_chg50]

        # 后排：成交额最小的20只(排除ST)中当天涨幅最高的2只
        non_st = [s for s in all_stocks if 'ST' not in (s.get('name') or '').upper()]
        by_amount_asc = sorted(non_st, key=lambda x: x.get('amount', 0) or 0)[:20]
        by_amount_asc_chg = sorted(by_amount_asc, key=lambda x: -(x.get('chg_pct', 0) or 0))[:2]
        followers = [f"{s['name']}({s.get('chg_pct', 0) or 0:+.1f}%)" for s in by_amount_asc_chg]

        # 20日新高个股数（最新一天）
        latest_nh_pct = daily_pcts[0] if daily_pcts else 0
        nh_count = round(latest_nh_pct * total / 100) if total > 0 else 0

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
        })

    # 按 RPS10 降序，最多5个
    results.sort(key=lambda x: -x['rps_10'])
    results = results[:5]

    return {'success': True, 'trade_date': trade_date, 'sectors': results}


def analyze_active_sectors(trade_date: str) -> Dict[str, Any]:
    """
    异动活跃板块筛选
    条件：
    1. 板块中大市值(流通市值Top10%)个股
    2. 其中60%以上今日涨幅≥5%
    3. 符合条件的大市值个股数量最少要超过5只
    4. 放量(成交量≥5日均量×1.5)，涨停股豁免量能检查
    """
    db = get_db()

    # 获取启用板块代码列表（兼容 is_disable 字段不存在的情况）
    enabled_sector_codes = set(
        doc['code'] for doc in db['sector_basics'].find(
            {'$or': [{'is_disable': {'$ne': True}}, {'is_disable': {'$exists': False}}]},
            {'_id': 0, 'code': 1}
        )
    )

    # 获取板块名称和成分股
    sector_map = {}
    for s in db['sector_basics'].find(
        {'$or': [{'is_disable': {'$ne': True}}, {'is_disable': {'$exists': False}}]},
        {'_id': 0, 'code': 1, 'name': 1, 'stock_codes': 1}
    ):
        sector_map[s['code']] = s

    # 获取股票名称
    stock_name_map = {}
    for b in db['stock_basics'].find(
        {'$or': [{'is_disable': {'$ne': True}}, {'is_disable': {'$exists': False}}]},
        {'_id': 0, 'stock_code': 1, 'stock_name': 1}
    ):
        stock_name_map[b['stock_code']] = b.get('stock_name', b['stock_code'])

    # 获取流通股本
    liutong_map = {}
    for b in db['stock_basics'].find(
        {'$or': [{'is_disable': {'$ne': True}}, {'is_disable': {'$exists': False}}], 'liutongguben': {'$gt': 0}},
        {'_id': 0, 'stock_code': 1, 'liutongguben': 1}
    ):
        liutong_map[b['stock_code']] = b['liutongguben']

    # 获取当日全市场数据（注意：字段名是 vol，不是 volume）
    today_stocks = {d['stock_code']: d for d in db['stock_daily'].find(
        {'trade_date': trade_date, 'close': {'$gt': 0}, 'vol': {'$gt': 0}},
        {'_id': 0, 'stock_code': 1, 'close': 1, 'vol': 1, 'amount': 1, 'chg_pct': 1,
         'chg_50d': 1, 'vol_ma5': 1}
    )}

    # 获取板块 RPS 数据
    sector_rps_map = {}
    for doc in db['sector_daily'].find(
        {'trade_date': trade_date, 'stock_code': {'$in': list(enabled_sector_codes)}},
        {'_id': 0, 'stock_code': 1, 'rps_10': 1, 'rps_20': 1, 'rps_50': 1}
    ):
        sector_rps_map[doc['stock_code']] = {
            'rps_10': doc.get('rps_10'),
            'rps_20': doc.get('rps_20'),
            'rps_50': doc.get('rps_50'),
        }

    if not today_stocks:
        return {'success': True, 'trade_date': trade_date, 'sectors': []}

    results = []
    for code in enabled_sector_codes:
        info = sector_map.get(code)
        if not info:
            continue

        name = info.get('name', code)
        stocks = info.get('stock_codes', [])
        total = len(stocks)
        if total < 10:  # 板块至少10只股票才有意义
            continue

        # 获取板块成分股数据，计算流通市值
        sector_stocks = []
        for s_code in stocks:
            if s_code not in today_stocks:
                continue
            today_data = today_stocks[s_code]
            liutong = liutong_map.get(s_code, 0)
            if liutong <= 0:
                continue
            float_mv = liutong * today_data['close'] / 1e8  # 流通市值（亿元）
            vol_ma5 = today_data.get('vol_ma5', 0) or 0
            sector_stocks.append({
                'stock_code': s_code,
                'name': stock_name_map.get(s_code, s_code),
                'close': today_data['close'],
                'volume': today_data['vol'],  # 注意：字段名是 vol
                'amount': today_data.get('amount', 0) or 0,
                'chg_pct': today_data.get('chg_pct', 0) or 0,
                'chg_50d': today_data.get('chg_50d', 0) or 0,
                'vol_ma5': vol_ma5,
                'float_mv': float_mv,
            })

        if len(sector_stocks) < 5:
            continue

        # 按流通市值降序排列，取前20%为"大市值组"
        sector_stocks.sort(key=lambda x: -x['float_mv'])
        top_20pct_count = max(1, int(len(sector_stocks) * 0.2))
        large_cap_stocks = sector_stocks[:top_20pct_count]

        if len(large_cap_stocks) < 5:  # 大市值个股至少5只
            continue

        # 检查大市值组中的异动情况
        active_count = 0
        for s in large_cap_stocks:
            chg = s['chg_pct']

            # 涨幅≥3.5%
            if chg < 3.5:
                continue

            # 涨幅≥6%不检查量能，涨幅<6%需要放量
            if chg < 6:
                vol_ma5 = s['vol_ma5']
                if vol_ma5 <= 0 or s['volume'] < vol_ma5 * 1.5:
                    continue

            active_count += 1

        # 条件：50%以上的大市值个股符合条件，且数量≥5
        active_pct = active_count / len(large_cap_stocks) * 100
        if active_pct < 50 or active_count < 5:
            continue

        # 计算板块涨幅（用成分股平均涨幅）
        avg_chg = sum(s['chg_pct'] for s in sector_stocks) / len(sector_stocks) if sector_stocks else 0

        # 先锋：50日涨幅最高的3只
        by_chg50 = sorted(sector_stocks, key=lambda x: -x['chg_50d'])[:3]
        pioneer = [f"{s['name']}(50日{s['chg_50d']:+.1f}%, 今日{s['chg_pct']:+.1f}%)" for s in by_chg50]

        # 中军：流通市值Top10中50日涨幅最高的3只
        # 流通市值已经在sector_stocks中计算过（float_mv字段）
        by_mv = sorted(sector_stocks, key=lambda x: -x.get('float_mv', 0))[:10]
        by_mv_chg50 = sorted(by_mv, key=lambda x: -x['chg_50d'])[:3]
        main_force = [f"{s['name']}(50日{s['chg_50d']:+.1f}%, 今日{s['chg_pct']:+.1f}%)" for s in by_mv_chg50]

        # 后排：成交额最小的20只(排除ST)中当天涨幅最高的2只
        non_st = [s for s in sector_stocks if 'ST' not in s['name'].upper()]
        by_amount_asc = sorted(non_st, key=lambda x: x['amount'])[:20]
        by_amount_asc_chg = sorted(by_amount_asc, key=lambda x: -x['chg_pct'])[:2]
        followers = [f"{s['name']}({s['chg_pct']:+.1f}%)" for s in by_amount_asc_chg]

        # 获取板块 RPS 数据
        sector_rps = sector_rps_map.get(code, {})

        results.append({
            'name': name,
            'count': active_count,  # 符合条件的大市值个股数
            'total': len(large_cap_stocks),  # 大市值个股总数
            'pct': round(active_pct, 1),  # 符合条件占比
            'chg_pct': round(avg_chg, 2),  # 板块平均涨幅
            'rps_10': sector_rps.get('rps_10'),
            'rps_20': sector_rps.get('rps_20'),
            'rps_50': sector_rps.get('rps_50'),
            'pioneer': pioneer,
            'main_force': main_force,
            'followers': followers,
        })

    # 按符合条件占比降序，最多5个
    results.sort(key=lambda x: -x['pct'])
    results = results[:5]

    return {'success': True, 'trade_date': trade_date, 'sectors': results}


def calc_ma_breadth_history(period: str = 'day', index_code: str = None) -> Dict[str, Any]:
    """
    计算近N个周期的MA50和MA20占比历史数据 + 叠加指数数据
    支持 day/week/month/quarter/year 聚合
    时间范围与趋势对比图保持一致（按日历天计算）
    """
    from datetime import datetime as _dt, timedelta, date as _date
    import calendar
    db = get_db()

    all_dates = sorted(db['stock_daily'].distinct('trade_date'), reverse=True)
    if not all_dates:
        return {'success': False, 'message': '无交易数据'}

    # 根据周期决定回溯日历天数
    now = _dt.now()
    period_days = {'day': 120, 'week': 365, 'month': 365 * 3, 'quarter': 365 * 5, 'year': 365 * 10}
    cal_days = period_days.get(period, 120)
    start_date = (now - timedelta(days=cal_days)).strftime('%Y%m%d')

    target_dates = [d for d in all_dates if d >= start_date]

    # 批量聚合：一次查询所有日期的MA50/MA20占比
    pipeline = [
        {'$match': {'trade_date': {'$in': target_dates}, 'close': {'$gt': 0}, 'ma50': {'$gt': 0}}},
        {'$group': {
            '_id': '$trade_date',
            'total': {'$sum': 1},
            'above_ma50': {'$sum': {'$cond': [{'$gt': ['$close', '$ma50']}, 1, 0]}},
            'above_ma20': {'$sum': {'$cond': [{'$gt': ['$close', '$ma20']}, 1, 0]}}
        }},
        {'$sort': {'_id': 1}}
    ]
    results = list(db['stock_daily'].aggregate(pipeline))

    daily_data = {}
    for r in results:
        if r['total'] > 0:
            daily_data[r['_id']] = {
                'ma50_pct': round(r['above_ma50'] / r['total'] * 100, 1),
                'ma20_pct': round(r['above_ma20'] / r['total'] * 100, 1),
            }

    # 按周期聚合
    def _agg_key(d):
        y, m, day = int(d[0:4]), int(d[4:6]), int(d[6:8])
        if period == 'week':
            iso_year, iso_week, _ = _date(y, m, day).isocalendar()
            return f"{iso_year}W{iso_week:02d}"
        elif period == 'month':
            return f"{y}-{m:02d}"
        elif period == 'quarter':
            q = (m - 1) // 3 + 1
            return f"{y}Q{q}"
        elif period == 'year':
            return f"{y}"
        return d

    if period == 'day':
        result_data = [{'date': d, **daily_data[d]} for d in sorted(daily_data.keys())]
    else:
        buckets = {}
        for d in sorted(daily_data.keys()):
            key = _agg_key(d)
            buckets[key] = {'date': key, **daily_data[d]}
        result_data = list(buckets.values())

    # 叠加指数数据
    index_data = {}
    if index_code and result_data:
        idx_start = start_date
        idx_end = all_dates[0]

        idx_cursor = db['index_daily'].find(
            {'stock_code': index_code, 'trade_date': {'$gte': idx_start, '$lte': idx_end}},
            {'_id': 0, 'trade_date': 1, 'close': 1}
        ).sort('trade_date', 1)
        idx_raw = {d['trade_date']: d['close'] for d in idx_cursor}

        if idx_raw:
            vals = list(idx_raw.values())
            min_v, max_v = min(vals), max(vals)
            rng = max_v - min_v or 1
            if period == 'day':
                for item in result_data:
                    if item['date'] in idx_raw:
                        item['index_value'] = round(20 + (idx_raw[item['date']] - min_v) / rng * 60, 1)
                        item['index_raw'] = idx_raw[item['date']]
            else:
                agg_idx = {}
                for d, v in idx_raw.items():
                    key = _agg_key(d)
                    agg_idx[key] = v
                for item in result_data:
                    if item['date'] in agg_idx:
                        item['index_value'] = round(20 + (agg_idx[item['date']] - min_v) / rng * 60, 1)
                        item['index_raw'] = agg_idx[item['date']]

    return {
        'success': True,
        'data': result_data,
    }


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
        if r10 and len(r10[0]['amounts']) >= 10:
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


@router.get("/base-data")
def get_base_data(
    type: str = Query(..., description="数据类型: cr5/ma/nh-nl"),
    period: str = Query("day", description="聚合周期: day/week/month/quarter/year"),
    index_code: Optional[str] = Query(None, description="叠加指数代码")
):
    """统一基础数据接口：从 base_data_daily 读取，支持周期聚合"""
    try:
        db = get_db()

        # 根据周期决定数据量
        period_days = {'day': 120, 'week': 365, 'month': 365 * 3, 'quarter': 365 * 5, 'year': 365 * 10}
        days = period_days.get(period, 120)

        # 选择查询字段
        if type == 'cr5':
            fields = {'_id': 0, 'date': 1, 'cr5_pct': 1, 'cr10_pct': 1}
            filter_q = {'cr5_pct': {'$exists': True}}
        elif type == 'ma':
            fields = {'_id': 0, 'date': 1, 'ma50_pct': 1, 'ma20_pct': 1}
            filter_q = {'ma50_pct': {'$exists': True}}
        elif type == 'nh-nl':
            fields = {'_id': 0, 'date': 1, 'nh': 1, 'nl': 1, 'nh_3m': 1, 'nl_3m': 1, 'nh_1m': 1, 'nl_1m': 1}
            filter_q = {'nh': {'$exists': True}}
        else:
            raise HTTPException(status_code=400, detail=f"未知type: {type}")

        # 读取数据
        cursor = db['base_data_daily'].find(filter_q, fields).sort('date', -1).limit(days)
        data = list(cursor)
        data.reverse()

        # 检查是否需要补充最新日期（base_data_daily 比 stock_daily 滞后）
        latest_stock = db['stock_daily'].find_one(sort=[('trade_date', -1)], projection={'_id': 0, 'trade_date': 1})
        latest_base = data[-1]['date'] if data else ''
        if latest_stock and latest_stock['trade_date'] > latest_base:
            # 补充缺失日期的实时计算并落库
            from pymongo import UpdateOne
            missing_dates = [d for d in sorted(db['stock_daily'].distinct('trade_date'), reverse=True)
                           if d > latest_base][:5]
            bulk_ops = []
            for md in missing_dates:
                row = _compute_realtime(type, md)
                if row:
                    data.append(row)
                    bulk_ops.append(UpdateOne({'date': md}, {'$set': row}, upsert=True))
            if bulk_ops:
                db['base_data_daily'].bulk_write(bulk_ops, ordered=False)
                logger.info(f"[base-data] 盘中补充{len(bulk_ops)}天数据到base_data_daily")
            data.sort(key=lambda x: x['date'])

        # 周期聚合（非日线时）
        if period != 'day' and data:
            data = _aggregate_base_data(data, type, period)

        # 叠加指数数据
        if index_code and data:
            idx_dates = [d['date'] for d in data]
            idx_cursor = db['index_daily'].find(
                {'stock_code': index_code, 'trade_date': {'$in': idx_dates}},
                {'_id': 0, 'trade_date': 1, 'close': 1}
            ).sort('trade_date', 1)
            idx_map = {d['trade_date']: d['close'] for d in idx_cursor}
            if idx_map:
                vals = list(idx_map.values())
                min_v, max_v = min(vals), max(vals)
                rng = max_v - min_v or 1
                for item in data:
                    if item['date'] in idx_map:
                        item['index_value'] = round(20 + (idx_map[item['date']] - min_v) / rng * 60, 1)
                        item['index_raw'] = idx_map[item['date']]

        return {'success': True, 'data': data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取基础数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取基础数据失败: {str(e)}")


# ========== 旧接口（已废弃，统一用 /base-data 替代） ==========
# @router.get("/nh-nl")
# def get_nh_nl(...):
#     """已废弃，用 GET /base-data?type=nh-nl 替代"""

# @router.post("/nh-nl/precompute")
# def precompute_nh_nl(...):
#     """已废弃，NH-NL数据已预计算落库到 base_data_daily"""

# @router.get("/ma-breadth")
# def get_ma_breadth(...):
#     """已废弃，用 GET /base-data?type=ma 替代"""


@router.get("/overview")
def get_market_overview_endpoint(date: Optional[str] = Query(None)):
    """主要大盘指数涨跌幅"""
    try:
        db = get_db()
        
        # 确定日期
        if not date:
            latest_doc = db['base_data_daily'].find_one(sort=[('date', -1)], projection={'_id': 0, 'date': 1})
            date = latest_doc['date'] if latest_doc else get_latest_trade_date(db)
        
        if not date:
            raise HTTPException(status_code=404, detail="无交易数据")
        
        # 检查market_daily中是否有该日期的数据
        cached = db['market_daily'].find_one({'trade_date': date}, {'_id': 0, 'overview': 1})
        if not cached or not cached.get('overview'):
            raise HTTPException(status_code=404, detail=f"日期 {date} 无市场概览数据，请先执行一键更新")
        
        result = generate_market_overview(latest_date=date)
        if not result.get('success'):
            raise HTTPException(status_code=404, detail=result.get('message', '无数据'))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取市场概览失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取市场概览失败: {str(e)}")


@router.get("/signals")
def get_market_signals_endpoint(date: Optional[str] = Query(None)):
    """A股运行状态量化指标"""
    try:
        result = calc_market_signals(latest_date=date)
        if not result.get('success'):
            raise HTTPException(status_code=404, detail=result.get('message', '无数据'))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取市场信号失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取市场信号失败: {str(e)}")


@router.get("/new-high-blocks")
def get_new_high_blocks_endpoint(date: Optional[str] = Query(None)):
    """新高强力板块"""
    try:
        db = get_db()
        if not date:
            date = get_latest_trade_date(db)

        # 优先从 market_daily 缓存读取
        cached = db['market_daily'].find_one({'trade_date': date}, {'_id': 0, 'new_high': 1})
        if cached and cached.get('new_high'):
            nh = cached['new_high']
            return {
                'success': True,
                'trade_date': date,
                'total_new_high_count': nh.get('total_count', 0),
                'industry_clusters': nh.get('clusters', []),
            }

        # 缓存未命中，实时计算
        result = analyze_new_high_blocks(latest_date=date)
        if not result.get('success'):
            raise HTTPException(status_code=404, detail=result.get('message', '无数据'))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取新高板块分析失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取新高板块分析失败: {str(e)}")


@router.get("/low-position-sectors")
def get_low_position_sectors(date: Optional[str] = Query(None)):
    """低位潜力板块（只读 market_daily）"""
    try:
        db = get_db()
        if not date:
            date = get_latest_trade_date(db)
        cached = db['market_daily'].find_one({'trade_date': date}, {'_id': 0, 'low_position_sectors': 1})
        if cached and cached.get('low_position_sectors'):
            return {
                'success': True,
                'trade_date': date,
                'sectors': cached['low_position_sectors'],
            }
        return {'success': True, 'trade_date': date, 'sectors': []}
    except Exception as e:
        logger.error(f"获取低位潜力板块失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取低位潜力板块失败: {str(e)}")


@router.get("/active-sectors")
def get_active_sectors(date: Optional[str] = Query(None)):
    """异动活跃板块（只读 market_daily）"""
    try:
        db = get_db()
        if not date:
            date = get_latest_trade_date(db)
        cached = db['market_daily'].find_one({'trade_date': date}, {'_id': 0, 'active_sectors': 1})
        if cached and cached.get('active_sectors'):
            return {
                'success': True,
                'trade_date': date,
                'sectors': cached['active_sectors'],
            }
        return {'success': True, 'trade_date': date, 'sectors': []}
    except Exception as e:
        logger.error(f"获取异动活跃板块失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取异动活跃板块失败: {str(e)}")


@router.get("/group-stats")
def get_group_stats(date: Optional[str] = Query(None, description="交易日期 YYYYMMDD")):
    """获取分组统计数据（从 market_daily 缓存读取）"""
    try:
        db = get_db()
        if not date:
            date = get_latest_trade_date(db)
        if not date:
            raise HTTPException(status_code=404, detail="无交易数据")

        cached = db['market_daily'].find_one({'trade_date': date}, {'_id': 0, 'group_stats': 1})
        if cached and cached.get('group_stats'):
            return {
                'success': True,
                'trade_date': date,
                'stats': cached['group_stats'],
            }

        return {
            'success': True,
            'trade_date': date,
            'stats': {},
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取分组统计失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取分组统计失败: {str(e)}")


@router.get("/ai-analysis")
def get_ai_analysis(date: Optional[str] = Query(None, description="交易日期 YYYYMMDD")):
    """获取 AI 分析结果
    盘后数据(is_final=True)：有缓存直接返回
    盘中数据(is_final=False)：30分钟内返回缓存，超过30分钟需重新生成
    无缓存：返回 need_generate
    """
    from datetime import datetime as _dt, timedelta
    try:
        db = get_db()

        # 优先从 base_data_daily 确定日期
        if not date:
            latest_doc = db['base_data_daily'].find_one(sort=[('date', -1)], projection={'_id': 0, 'date': 1})
            date = latest_doc['date'] if latest_doc else get_latest_trade_date(db)
        
        # 从 market_daily 读取 AI 缓存
        cached = db['market_daily'].find_one({'trade_date': date}, {'_id': 0})
        existing_ai = cached.get('ai_analysis') if cached else None
        is_final = cached.get('is_final', False) if cached else False

        if existing_ai and existing_ai.get('market_phase_diagnosis') and existing_ai.get('source') != 'failed':
            generated_at = existing_ai.get('generated_at', '')

            # 有缓存的AI分析数据，直接返回（不再限制30分钟）
            return {
                'success': True,
                'trade_date': date,
                'is_final': is_final,
                'is_cached': True,
                'generated_at': generated_at,
                **existing_ai,
            }

        # 检查是否有失败记录
        if existing_ai and existing_ai.get('source') == 'failed':
            return {
                'success': True,
                'trade_date': date,
                'is_final': is_final,
                'is_cached': False,
                'need_generate': True,
                'last_error': existing_ai.get('error', '未知错误'),
                'failed_at': existing_ai.get('generated_at', ''),
            }

        # 无缓存
        return {
            'success': True,
            'trade_date': date,
            'is_final': is_final,
            'is_cached': False,
            'need_generate': True,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI分析查询失败: {e}")
        return {
            'success': True,
            'trade_date': date or 'unknown',
            'is_cached': False,
            'need_generate': True,
        }


@router.post("/ai-analysis/generate")
def generate_ai_analysis(date: Optional[str] = Query(None, description="交易日期 YYYYMMDD")):
    """启动 AI 分析后台任务"""
    import threading
    from datetime import datetime as _dt
    from app.data.task_manager import get_task_manager

    try:
        db = get_db()
        tm = get_task_manager()

        # 优先从 base_data_daily 读取指标（快）
        if not date:
            latest_doc = db['base_data_daily'].find_one(sort=[('date', -1)], projection={'_id': 0, 'date': 1})
            date = latest_doc['date'] if latest_doc else get_latest_trade_date(db)
        
        base_data = db['base_data_daily'].find_one({'date': date}, {'_id': 0})
        if not base_data:
            raise HTTPException(status_code=404, detail=f"无 {date} 的基础数据，请先同步数据")

        trade_date = date

        # 检查是否已有缓存
        cached = db['market_daily'].find_one({'trade_date': trade_date}, {'_id': 0})
        existing_ai = cached.get('ai_analysis') if cached else None

        def _is_after_market(gen_time_str):
            """判断生成时间是否在盘后（15:30之后）"""
            if not gen_time_str:
                return False
            try:
                gen_time = _dt.fromisoformat(gen_time_str)
                # 盘后时间：15:30之后
                return gen_time.hour > 15 or (gen_time.hour == 15 and gen_time.minute >= 30)
            except Exception:
                return False

        if existing_ai and existing_ai.get('market_phase_diagnosis') and existing_ai.get('source') != 'failed':
            generated_at = existing_ai.get('generated_at', '')

            # 如果是盘后时间生成的，永久缓存，直接返回
            if _is_after_market(generated_at):
                return {
                    'success': True,
                    'task_id': None,
                    'trade_date': trade_date,
                    'is_cached': True,
                    'generated_at': generated_at,
                    **existing_ai,
                }

            # 盘中时间生成的，检查是否超过30分钟
            if generated_at:
                try:
                    gen_time = _dt.fromisoformat(generated_at)
                    if (_dt.now() - gen_time).total_seconds() < 1800:
                        # 30分钟内，返回缓存
                        return {
                            'success': True,
                            'task_id': None,
                            'trade_date': trade_date,
                            'is_cached': True,
                            'generated_at': generated_at,
                            **existing_ai,
                        }
                except Exception:
                    pass

            # 盘中数据超过30分钟或无生成时间，需要重新生成（不返回缓存）

        # 如果是失败记录，清除它以便重新生成
        if existing_ai and existing_ai.get('source') == 'failed':
            db['market_daily'].update_one(
                {'trade_date': trade_date},
                {'$unset': {'ai_analysis': ''}}
            )
            # 清除失败记录后继续重新生成，不返回错误

        # 创建后台任务
        task_id = tm.create_task()
        tm.update_task_progress(task_id, current_stock_name="准备生成 AI 分析...")

        def _run():
            try:
                # 1. 预计算 overview/signals/new_high 并落库
                tm.update_task_progress(task_id, current_stock_name="预计算市场数据...")
                precompute_market_daily(trade_date)

                # 2. 从 market_daily 读取完整数据
                tm.update_task_progress(task_id, current_stock_name="读取预计算数据...")
                cached = db['market_daily'].find_one({'trade_date': trade_date}, {'_id': 0})
                if not cached:
                    tm.fail_task(task_id, "预计算失败，无 market_daily 数据")
                    return

                base = db['base_data_daily'].find_one({'date': trade_date}, {'_id': 0})
                total_stocks = db['stock_daily'].count_documents({'trade_date': trade_date, 'close': {'$gt': 0}})

                market_data = {
                    'trade_date': trade_date,
                    'overview': cached.get('overview', {}),
                    'new_high': cached.get('new_high', {}),
                    'low_position_sectors': cached.get('low_position_sectors', []),
                    'active_sectors': cached.get('active_sectors', []),
                }

                # 检查 overview 是否完整
                if not market_data['overview'].get('indices'):
                    tm.fail_task(task_id, f"{trade_date} 预计算数据不完整（无指数数据），请先同步指数")
                    return

                # 3. 调用 DeepSeek
                tm.update_task_progress(task_id, current_stock_name="调用 DeepSeek 分析...")
                ai_result = _call_deepseek(db, trade_date, market_data)

                msg = f"AI分析完成 (来源: {ai_result.get('source', 'unknown')})"
                logger.info(f"[AI分析] 准备完成任务 {task_id}: {msg}")
                tm.complete_task(task_id, msg)
                logger.info(f"[AI分析] 任务 {task_id} 已标记完成")
            except Exception as e:
                logger.error(f"AI分析任务失败: {e}")
                # 存储失败信息到 market_daily
                try:
                    from datetime import datetime as _dt
                    db['market_daily'].update_one(
                        {'trade_date': trade_date},
                        {'$set': {
                            'ai_analysis': {
                                'source': 'failed',
                                'error': str(e)[:500],
                                'generated_at': _dt.now().isoformat(),
                            }
                        }}
                    )
                except Exception:
                    pass
                try:
                    tm.fail_task(task_id, str(e)[:200])
                except Exception:
                    pass

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        return {
            'success': True,
            'task_id': task_id,
            'trade_date': trade_date,
            'is_cached': False,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"启动AI分析任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"启动失败: {str(e)[:100]}")


@router.get("/ai-analysis/task/{task_id}")
def get_ai_analysis_task(task_id: str):
    """查询 AI 分析任务状态"""
    from app.data.task_manager import get_task_manager
    tm = get_task_manager()
    task = tm.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


def _call_deepseek(db, trade_date: str, market_data: dict) -> dict:
    """调用 DeepSeek 并落库"""
    from datetime import datetime as _dt
    from app.server.api.deepseek_analyst import get_deepseek_analyst

    analyst = get_deepseek_analyst()

    if not analyst.api_key:
        raise ValueError("DEEPSEEK_API_KEY 未配置")

    ai_result = analyst.analyze(market_data)
    ai_result['generated_at'] = _dt.now().isoformat()

    # 检查是否是降级结果（API调用失败）
    # 降级时 market_phase_diagnosis 会包含错误信息或特定的降级消息
    diagnosis = ai_result.get('market_phase_diagnosis', '')
    is_fallback = (
        diagnosis == '系统分析服务暂时不可用，请稍后重试。' or
        '不可用' in diagnosis or
        '失败' in diagnosis or
        '未配置' in diagnosis or
        not diagnosis
    )
    ai_result['source'] = 'failed' if is_fallback else 'deepseek'

    # 落库
    db['market_daily'].update_one(
        {'trade_date': trade_date},
        {'$set': {'ai_analysis': ai_result}}
    )
    logger.info(f"[AI分析] {trade_date} 来源={ai_result['source']}")
    return ai_result


@router.get("/ai-analysis/input-data")
def get_ai_input_data(date: str = Query(..., description="交易日期 YYYYMMDD")):
    """获取传给DeepSeek的输入数据（从缓存读取）"""
    try:
        db = get_db()

        # 从 market_daily 获取数据
        cached = db['market_daily'].find_one({'trade_date': date}, {'_id': 0})
        if not cached:
            raise HTTPException(status_code=404, detail=f"日期 {date} 无预计算数据")

        market_data = {
            'trade_date': date,
            'overview': cached.get('overview', {}),
            'new_high': cached.get('new_high', {}),
            'low_position_sectors': cached.get('low_position_sectors', []),
            'active_sectors': cached.get('active_sectors', []),
        }

        # 调用 _build_user_message 拼接数据
        from app.server.api.deepseek_analyst import get_deepseek_analyst
        analyst = get_deepseek_analyst()
        input_data = analyst._build_user_message(market_data)

        return {
            'success': True,
            'trade_date': date,
            'input_data': input_data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取AI输入数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取AI输入数据失败: {str(e)}")


@router.get("/sector-detail")
def get_sector_detail(sector_code: str = Query(..., description="板块代码")):
    """获取板块详情：先锋、中军、后排（懒加载：查询时检查并计算）"""
    try:
        db = get_db()
        
        # 获取板块信息
        sector_doc = db['sector_basics'].find_one({'code': sector_code}, {'_id': 0, 'name': 1, 'stock_codes': 1})
        if not sector_doc:
            raise HTTPException(status_code=404, detail="未找到该板块")
        
        sector_name = sector_doc.get('name', sector_code)
        stock_codes = sector_doc.get('stock_codes', [])
        
        # 获取最新交易日
        latest_stock = db['stock_daily'].find_one(sort=[('trade_date', -1)])
        if not latest_stock:
            raise HTTPException(status_code=404, detail="无数据")
        trade_date = latest_stock['trade_date']
        
        # 检查 sector_daily 中是否已有先锋、中军、后排数据
        sector_daily_doc = db['sector_daily'].find_one(
            {'stock_code': sector_code, 'trade_date': trade_date},
            {'_id': 0, 'pioneer': 1, 'main_force': 1, 'followers': 1}
        )
        
        # 如果已有数据，直接返回
        if sector_daily_doc and sector_daily_doc.get('pioneer') is not None:
            return {
                'success': True,
                'trade_date': trade_date,
                'sector_name': sector_name,
                'pioneer': sector_daily_doc.get('pioneer', []),
                'main_force': sector_daily_doc.get('main_force', []),
                'followers': sector_daily_doc.get('followers', []),
            }
        
        # 没有数据，实时计算
        if not stock_codes:
            return {
                'success': True,
                'trade_date': trade_date,
                'sector_name': sector_name,
                'pioneer': [],
                'main_force': [],
                'followers': [],
            }
        
        # 获取流通股本
        liutong_map = {}
        for b in db['stock_basics'].find({'liutongguben': {'$gt': 0}}, {'_id': 0, 'stock_code': 1, 'liutongguben': 1, 'stock_name': 1}):
            liutong_map[b['stock_code']] = {'liutongguben': b.get('liutongguben', 0), 'name': b.get('stock_name', '')}
        
        # 获取当日数据
        stocks = list(db['stock_daily'].find(
            {'stock_code': {'$in': stock_codes}, 'trade_date': trade_date, 'close': {'$gt': 0}},
            {'_id': 0, 'stock_code': 1, 'close': 1, 'chg_50d': 1, 'chg_pct': 1}
        ))
        
        if not stocks:
            return {
                'success': True,
                'trade_date': trade_date,
                'sector_name': sector_name,
                'pioneer': [],
                'main_force': [],
                'followers': [],
            }
        
        # 计算流通市值
        for s in stocks:
            lt = liutong_map.get(s['stock_code'], {})
            liutong = lt.get('liutongguben', 0)
            close = s.get('close', 0)
            s['name'] = lt.get('name', s['stock_code'])
            s['_float_mv'] = liutong * close / 1e8 if liutong and close else 0
        
        # 先锋：50日涨幅最高的3只
        by_chg50 = sorted(stocks, key=lambda x: -(x.get('chg_50d', 0) or 0))[:3]
        pioneer = [f"{s['name']}(50日{s.get('chg_50d', 0) or 0:+.1f}%, 今日{s.get('chg_pct', 0) or 0:+.1f}%)" for s in by_chg50]
        
        # 中军：流通市值Top10中50日涨幅最高的3只
        by_mv = sorted(stocks, key=lambda x: -(x.get('_float_mv', 0) or 0))[:10]
        by_mv_chg50 = sorted(by_mv, key=lambda x: -(x.get('chg_50d', 0) or 0))[:3]
        main_force = [f"{s['name']}(50日{s.get('chg_50d', 0) or 0:+.1f}%, 今日{s.get('chg_pct', 0) or 0:+.1f}%)" for s in by_mv_chg50]
        
        # 后排：小市值中当天涨幅最高的2只
        non_st = [s for s in stocks if 'ST' not in (s.get('name') or '').upper()]
        by_mv_asc = sorted(non_st, key=lambda x: x.get('_float_mv', 0) or 0)[:20]
        by_mv_asc_chg = sorted(by_mv_asc, key=lambda x: -(x.get('chg_pct', 0) or 0))[:2]
        followers = [f"{s['name']}({s.get('chg_pct', 0) or 0:+.1f}%)" for s in by_mv_asc_chg]
        
        # 写入 sector_daily
        from pymongo import UpdateOne
        db['sector_daily'].update_one(
            {'stock_code': sector_code, 'trade_date': trade_date},
            {'$set': {
                'pioneer': pioneer,
                'main_force': main_force,
                'followers': followers,
            }},
            upsert=True
        )
        
        return {
            'success': True,
            'trade_date': trade_date,
            'sector_name': sector_name,
            'pioneer': pioneer,
            'main_force': main_force,
            'followers': followers,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取板块详情失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)[:200]}")
