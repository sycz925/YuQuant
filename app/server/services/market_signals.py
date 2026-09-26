"""
市场信号分析服务
提供指数概览、MA50广度、强势股、新高信号等分析逻辑
从 api/market_review.py 迁移而来
"""
import logging
from collections import defaultdict, Counter
from typing import Dict, Any, List, Optional

from app.data.db import get_db
from app.server.services.market_data import get_latest_trade_date, _build_stock_industry_map
from app.engine.watchlist_alert import get_index_tdx_status

logger = logging.getLogger(__name__)


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
        yesterday_candidates = [d for d in dates if d < today]
        yesterday = yesterday_candidates[0] if yesterday_candidates else today
    else:
        today, yesterday = dates[0], dates[1]

    # 批量拉取指数数据
    index_codes = [c['code'] for c in index_config]
    cursor = db['index_daily'].find(
        {'stock_code': {'$in': index_codes}, 'trade_date': today},
        {'_id': 0, 'stock_code': 1, 'trade_date': 1, 'open': 1, 'high': 1, 'low': 1, 'close': 1, 'chg_pct': 1}
    )
    rows = list(cursor)
    if not rows:
        return {'success': False, 'message': '无指数数据'}

    df = pd.DataFrame(rows)
    if df.empty:
        return {'success': False, 'message': '无有效指数数据'}

    # 合并配置名称
    config_map = {c['code']: c for c in index_config}
    df['code'] = df['stock_code']
    df['name'] = df['stock_code'].map(lambda c: config_map.get(c, {}).get('name', c))
    df['code_display'] = df['stock_code'].map(lambda c: config_map.get(c, {}).get('tdx_code', c))

    # 计算涨跌幅：优先用 chg_pct，缺失时从前一交易日 close 计算
    if 'chg_pct' in df.columns and df['chg_pct'].notna().any():
        df['pct_chg'] = df['chg_pct'].fillna(0)
    else:
        prev_close_map = {}
        for code in index_codes:
            prev_doc = db['index_daily'].find_one(
                {'stock_code': code, 'trade_date': {'$lt': today}},
                {'_id': 0, 'close': 1},
                sort=[('trade_date', -1)]
            )
            prev_close_map[code] = prev_doc['close'] if prev_doc and prev_doc.get('close') else 0
        df['pct_chg'] = df.apply(
            lambda r: round((r['close'] - prev_close_map.get(r['stock_code'], 0)) / prev_close_map.get(r['stock_code'], 1) * 100, 2)
            if prev_close_map.get(r['stock_code'], 0) > 0 else 0, axis=1
        )

    # 过滤掉无效数据
    df = df.dropna(subset=['close']).reset_index(drop=True)
    if df.empty:
        return {'success': False, 'message': '无有效指数数据'}

    # 排序（按涨跌幅降序）
    pivot = df.sort_values('pct_chg', ascending=False).reset_index(drop=True)

    # 查询各指数前一交易日收盘价（用于计算盘中最大涨幅/跌幅）
    prev_close_map = {}
    for code in index_codes:
        prev_doc = db['index_daily'].find_one(
            {'stock_code': code, 'trade_date': {'$lt': today}},
            {'_id': 0, 'close': 1},
            sort=[('trade_date', -1)]
        )
        prev_close_map[code] = prev_doc['close'] if prev_doc and prev_doc.get('close') else 0

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

        # 计算长影线（上影线=high-close，下影线=close-low）
        code = row.get('stock_code', row.get('code', ''))
        prev_close = prev_close_map.get(code, 0)
        high = row.get('high', 0)
        low = row.get('low', 0)
        close_price = row.get('close', 0)
        wick_suffix = ''
        if prev_close and prev_close > 0 and high and low and close_price:
            upper_wick_pct = round((high - close_price) / prev_close * 100, 2)
            lower_wick_pct = round((close_price - low) / prev_close * 100, 2)
            is_upper = upper_wick_pct > 3
            is_lower = lower_wick_pct > 3
            if is_upper and is_lower:
                wick_suffix = f"（回撤+{upper_wick_pct}%/反弹+{lower_wick_pct}%）"
            elif is_upper:
                wick_suffix = f"（回撤+{upper_wick_pct}%）"
            elif is_lower:
                wick_suffix = f"（反弹+{lower_wick_pct}%）"

        if row.name == max_idx.name:
            return (f'表现最强，{meaning}领涨' if meaning else '表现最强，领先全场') + wick_suffix
        if row.name == min_idx.name:
            return (f'表现最弱，{meaning}承压' if meaning else '表现最弱，明显落后') + wick_suffix

        abs_pct = abs(pct)
        if pct > 2.0:
            return (f'大涨，{meaning}资金涌入' if meaning else '大涨') + wick_suffix
        elif pct > 1.0:
            return (f'偏强，{meaning}表现积极' if meaning else '偏强') + wick_suffix
        elif pct > 0.5:
            return '小幅上涨' + wick_suffix
        elif pct > 0:
            return '窄幅震荡' + wick_suffix
        elif pct > -0.5:
            return '小幅回调' + wick_suffix
        elif pct > -1.0:
            return '偏弱' + wick_suffix
        else:
            return (f'大跌，{meaning}承压' if meaning else '大跌') + wick_suffix

    pivot['comment'] = pivot.apply(_gen_comment, axis=1)

    # 构建指数列表
    indices = []
    for _, row in pivot.iterrows():
        code = row.get('stock_code', row.get('code', ''))
        prev_close = prev_close_map.get(code, 0)
        high = float(row.get('high', 0) or 0)
        low = float(row.get('low', 0) or 0)
        open_price = float(row.get('open', 0) or 0)
        close_price = float(row.get('close', 0) or 0)

        wick = {'type': 'none', 'upper_pct': 0, 'lower_pct': 0}
        if prev_close and prev_close > 0 and high and low and close_price:
            upper_pct = round((high - close_price) / prev_close * 100, 2)
            lower_pct = round((close_price - low) / prev_close * 100, 2)
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

        indices.append({
            'code': code,
            'name': row['name'],
            'open': open_price,
            'high': high,
            'low': low,
            'close': close_price,
            'prev_close': round(prev_close, 2) if prev_close else 0,
            'pct_chg': float(row['pct_chg']),
            'wick': wick,
            'comment': row['comment'],
            'tdx_status': get_index_tdx_status(code, today),
        })

    # 获取指数PE_TTM（按日期从 index_pe_daily 读取，回退到 index_basics）
    try:
        from app.server.services.factors_service import get_pe_ttm_by_date
        for idx in indices:
            code = idx.get('code', '')
            pe = get_pe_ttm_by_date(code, today)
            if pe is not None:
                idx['pe_ttm'] = pe
            else:
                doc = db['index_basics'].find_one(
                    {'code': code, 'pe_ttm': {'$exists': True, '$ne': None}},
                    {'_id': 0, 'pe_ttm': 1}
                )
                if doc:
                    idx['pe_ttm'] = round(float(doc['pe_ttm']), 2)
    except Exception as e:
        logger.warning(f"[PE] 读取指数PE失败: {e}")

    # NLP 核心结论
    leader = pivot.iloc[0]
    laggard = pivot.iloc[-1]

    kc50 = pivot[pivot['name'].str.contains('科创', na=False)]
    kc50_pct = float(kc50.iloc[0]['pct_chg']) if not kc50.empty else 0

    cyb = pivot[pivot['name'].str.contains('创业板', na=False)]
    cyb_pct = float(cyb.iloc[0]['pct_chg']) if not cyb.empty else 0

    sh_idx = pivot[pivot['code'] == '000001']
    sh_pct = float(sh_idx.iloc[0]['pct_chg']) if not sh_idx.empty else 0

    tech_strong = kc50_pct > 1.0 or cyb_pct > 1.0
    old_money_strong = sh_pct > 1.0
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

    conclusion = f"【{style}】{detail}。"
    conclusion += f"涨幅居前：{leader['name']}（+{leader['pct_chg']}%），"
    conclusion += f"表现最弱：{laggard['name']}（{laggard['pct_chg']:+.1f}%）"

    if kc50_pct > 2.0:
        conclusion += f"。科创50暴涨{kc50_pct}%，国产替代主线持续强势"
    elif cyb_pct > 2.0:
        conclusion += f"。创业板指大涨{cyb_pct}%，成长风格占优"
    elif sh_pct < -1.0:
        conclusion += f"。上证跌{sh_pct}%，权重股集体承压"

    # 添加长影线信息到 conclusion
    wick_indices = []
    for idx in indices:
        w = idx.get('wick', {})
        name = idx.get('name', '')
        if w.get('type') == 'upper':
            wick_indices.append(f"{name}回撤{w['upper_pct']}%")
        elif w.get('type') == 'lower':
            wick_indices.append(f"{name}反弹{w['lower_pct']}%")
        elif w.get('type') == 'both':
            wick_indices.append(f"{name}回撤{w['upper_pct']}%/反弹{w['lower_pct']}%")
    if wick_indices:
        conclusion += f"。{'、'.join(wick_indices)}，关注反弹和回撤力度"

    # 按代码排序
    indices.sort(key=lambda x: x.get('code', ''))

    return {
        'success': True,
        'trade_date': today,
        'indices': indices,
        'conclusion': conclusion,
    }


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

    today_docs = list(db['stock_daily'].find(
        {'trade_date': latest_date, 'close': {'$gt': 0}},
        {'_id': 0, 'stock_code': 1, 'close': 1, 'high': 1, 'ma50': 1, 'chg_pct': 1}
    ))
    if not today_docs:
        return {'total_stocks': total_stocks, 'above_ma50_count': 0, 'above_ma50_pct': 0, 'new_high_count': 0,
                'above_ma50_stocks': [], 'new_high_stocks': []}

    stock_codes = [d['stock_code'] for d in today_docs]
    today_map = {d['stock_code']: d for d in today_docs}

    name_cursor = db['stock_basics'].find(
        {'is_disable': {'$ne': True}},
        {'_id': 0, 'stock_code': 1, 'stock_name': 1}
    )
    name_map = {d['stock_code']: d.get('stock_name', '') for d in name_cursor}

    above_ma50_stocks = []
    for d in today_docs:
        if d.get('ma50') and d['close'] > d['ma50']:
            above_ma50_stocks.append({
                'code': d['stock_code'],
                'name': name_map.get(d['stock_code'], d['stock_code']),
                'pct_chg': d.get('chg_pct', 0) or 0,
                'close': d.get('close', 0)
            })

    from datetime import datetime as _dt, timedelta
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

    above_ma50_stocks.sort(key=lambda x: x['pct_chg'], reverse=True)
    new_high_stocks.sort(key=lambda x: x['pct_chg'], reverse=True)

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
    import numpy as np
    db = get_db()

    if not latest_date:
        latest_date = get_latest_trade_date(db)
    if not latest_date:
        return {'success': False, 'message': '无交易数据'}

    today_docs = list(db['stock_daily'].find(
        {'trade_date': latest_date, 'close': {'$gt': 0}},
        {'_id': 0, 'stock_code': 1, 'close': 1, 'high': 1, 'ma50': 1, 'chg_pct': 1,
         'rps_20': 1, 'rps_50': 1, 'rps_120': 1, 'rps_250': 1}
    ))
    if not today_docs:
        return {'success': False, 'message': '今日无交易数据'}

    total_stocks = len(today_docs)

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

    above_ma50_count = 0
    strong_stocks = []
    cached_market = db['market_daily'].find_one({'trade_date': latest_date}, {'_id': 0, 'new_high': 1})
    new_high_count = cached_market.get('new_high', {}).get('total_count', 0) if cached_market else 0

    name_cursor = db['stock_basics'].find(
        {'is_disable': {'$ne': True}}, {'_id': 0, 'stock_code': 1, 'stock_name': 1}
    )
    name_map = {d['stock_code']: d.get('stock_name', '') for d in name_cursor}

    for d in today_docs:
        code = d['stock_code']

        ma50 = d.get('ma50')
        if ma50 and d['close'] > ma50:
            above_ma50_count += 1

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

    industry_map = _build_stock_industry_map()
    top_industry = '科技成长'
    if strong_top50:
        ind_counts = Counter()
        for s in strong_top50:
            ind = industry_map.get(s['code'], '其他')
            ind_counts[ind] += 1
        if ind_counts:
            top_industry = ind_counts.most_common(1)[0][0]

    cached_market = db['market_daily'].find_one({'trade_date': latest_date}, {'_id': 0, 'new_high': 1})
    if cached_market and cached_market.get('new_high', {}).get('clusters'):
        clusters = cached_market['new_high']['clusters']
        total_new_high = cached_market['new_high'].get('total_count', 0)
    else:
        base_doc = db['base_data_daily'].find_one({'date': latest_date}, {'_id': 0, 'nh': 1, 'nl': 1})
        total_new_high = (base_doc.get('nh', 0) if base_doc else 0)
        clusters = []
    top_cluster = clusters[0] if clusters else None

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

    has_block_effect = top_cluster and top_cluster.get('pct', 0) > 10
    block_industry = top_cluster['industry'] if top_cluster else None
    block_count = top_cluster['count'] if top_cluster else 0

    parts = []

    parts.append(f"【市场状态】{market_desc}。站上50日线占比 {above_ma50_pct}%，{new_high_count} 只个股创历史新高。")

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

    if market_state == "弱势" and has_block_effect:
        parts.append("【策略建议】放弃弱势股，聚焦领头羊板块中距离250日高点<10%的强势品种，等待口袋突破信号。")
    elif market_state == "强势":
        parts.append("【策略建议】市场强势，可积极参与，关注领头羊板块的回调买入机会。")
    elif market_state == "分化":
        parts.append("【策略建议】市场分化明显，聚焦领头羊板块，回避弱势板块。")
    else:
        parts.append("【策略建议】控制仓位，等待市场企稳信号，关注逆势走强的板块。")

    return '\n'.join(parts)