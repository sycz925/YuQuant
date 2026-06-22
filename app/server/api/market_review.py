"""
市场复盘数据 API
提供全栈量化复盘报告所需的数据
"""
import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Query
from datetime import datetime

from app.data.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/market-review", tags=["market-review"])


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

    # 从 index_basics 读取启用的指数（与趋势图下拉框一致）
    index_cursor = db['index_basics'].find({}, {'_id': 0, 'code': 1, 'name': 1})
    index_config = list(index_cursor)

    # 合并 exclusions 中新增的指数
    try:
        existing_codes = {c['code'] for c in index_config}
        excl_items = list(db['exclusions'].find(
            {'category': 'index'}, {'_id': 0, 'code': 1, 'name': 1, 'exclude_sync': 1}
        ))
        disabled_codes = set()
        for item in excl_items:
            code = item.get('code', '')
            if not code:
                continue
            if item.get('exclude_sync'):
                disabled_codes.add(code)
            if code not in existing_codes:
                index_config.append({'code': code, 'name': item.get('name', code)})
                existing_codes.add(code)
        index_config = [c for c in index_config if c['code'] not in disabled_codes]
    except Exception:
        pass

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

    # 批量拉取指数数据
    index_codes = [c['code'] for c in index_config]
    cursor = db['index_daily'].find(
        {'stock_code': {'$in': index_codes}, 'trade_date': {'$in': [today, yesterday]}},
        {'_id': 0, 'stock_code': 1, 'trade_date': 1, 'close': 1, 'open': 1, 'high': 1, 'low': 1}
    )
    rows = list(cursor)
    df = pd.DataFrame(rows)
    if df.empty:
        return {'success': False, 'message': '无指数数据'}

    # pivot: stock_code -> {today_close, yesterday_close}
    pivot = df.pivot(index='stock_code', columns='trade_date', values='close').reset_index()
    pivot.columns = ['code', 'close_y', 'close_t']
    # 确保列顺序正确（yesterday 在前，today 在后）
    if today not in pivot.columns and yesterday not in pivot.columns:
        pass
    else:
        pivot.columns = ['code', 'close_y', 'close_t']

    # 合并配置名称
    config_map = {c['code']: c for c in index_config}
    pivot['name'] = pivot['code'].map(lambda c: config_map.get(c, {}).get('name', c))
    pivot['code_display'] = pivot['code'].map(lambda c: config_map.get(c, {}).get('tdx_code', c))

    # 计算涨跌幅
    pivot['pct_chg'] = ((pivot['close_t'] - pivot['close_y']) / pivot['close_y'] * 100).round(2)

    # 过滤掉无效数据
    pivot = pivot.dropna(subset=['pct_chg', 'close_t', 'close_y']).reset_index(drop=True)
    if pivot.empty:
        return {'success': False, 'message': '无有效指数数据'}

    # 排序（按涨跌幅降序）
    pivot = pivot.sort_values('pct_chg', ascending=False).reset_index(drop=True)

    # 自动生成点评
    max_idx = pivot.iloc[0]
    min_idx = pivot.iloc[-1]

    # 指数含义映射
    INDEX_MEANING = {
        '上证指数': '老登股（消费、金融、银行）',
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
            'close': round(float(row['close_t']), 2),
            'pct_chg': float(row['pct_chg']),
            'comment': row['comment'],
        })

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
        'conclusion': conclusion,
        'style': style,
    }


def _build_stock_industry_map() -> Dict[str, str]:
    """从 sector_basics 构建 stock_code -> 主行业名称 映射（取成分股最多的行业）"""
    db = get_db()
    cursor = db['sector_basics'].find(
        {'stock_count': {'$gt': 0}},
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
    """从 sector_basics 构建 stock_code -> 行业名称列表 映射（每只股票可归属多个行业）"""
    db = get_db()
    cursor = db['sector_basics'].find(
        {'stock_count': {'$gt': 0}},
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

    # 获取股票名称
    name_cursor = db['stock_basics'].find({}, {'_id': 0, 'stock_code': 1, 'stock_name': 1})
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

    # 获取股票名称
    name_cursor = db['stock_basics'].find({}, {'_id': 0, 'stock_code': 1, 'stock_name': 1})
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
        {}, {'_id': 0, 'stock_code': 1, 'stock_name': 1}
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

    # 获取上市日期（判断上市天数）
    list_date_map = {}
    basics_cursor = db['stock_basics'].find(
        {}, {'_id': 0, 'stock_code': 1, 'list_date': 1}
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
    above_ma50_stocks = []
    # ====== 指标二：强势股（直接用 rps/chg_pct 字段） ======
    strong_stocks = []
    # ====== 指标三：历史新高（需要历史最高收盘价） ======
    new_high_count = 0
    new_high_stocks = []

    # 历史新高需要查询365天最高收盘价（年新高）
    try:
        date_obj = _dt.strptime(latest_date, '%Y%m%d')
        hist_start = (date_obj - timedelta(days=365)).strftime('%Y%m%d')
    except Exception:
        hist_start = latest_date

    # 统一用收盘价 >= 历史最高收盘价
    high_cursor = db['stock_daily'].aggregate([
        {'$match': {'trade_date': {'$gte': hist_start}, 'close': {'$gt': 0}}},
        {'$group': {'_id': '$stock_code', 'max_close': {'$max': '$close'}}}
    ])
    high_map = {d['_id']: d['max_close'] for d in high_cursor}

    # 获取股票名称
    name_cursor = db['stock_basics'].find({}, {'_id': 0, 'stock_code': 1, 'stock_name': 1})
    name_map = {d['stock_code']: d.get('stock_name', '') for d in name_cursor}

    for d in today_docs:
        code = d['stock_code']

        # MA50 广度（直接用冗余字段）
        ma50 = d.get('ma50')
        if ma50 and d['close'] > ma50:
            above_ma50_count += 1
            above_ma50_stocks.append({
                'code': code,
                'name': name_map.get(code, code),
                'pct_chg': d.get('chg_pct', 0) or 0,
                'close': d.get('close', 0)
            })

        # 历史新高：收盘价 >= 历史最高收盘价
        max_close = high_map.get(code, 0)
        if max_close > 0 and d['close'] >= max_close:
            new_high_count += 1
            new_high_stocks.append({
                'code': code,
                'name': name_map.get(code, code),
                'pct_chg': d.get('chg_pct', 0) or 0,
                'close': d.get('close', 0)
            })

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
                'ratio': round(d['close'] / max_close * 100, 1) if max_close > 0 else 0
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
    blocks_result = analyze_new_high_blocks(latest_date=latest_date)
    total_new_high = blocks_result.get('total_new_high_count', 0)
    clusters = blocks_result.get('industry_clusters', [])
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
        'indicators': [
            {
                'name': '50日线广度',
                'data': f"{above_ma50_count} / {total_stocks}",
                'data_value': above_ma50_pct,
                'signal': signal_1,
                'stocks': above_ma50_stocks,
            },
            {
                'name': '强势股（近250H≥90%）',
                'data': f"{len(strong_top50)} 只",
                'data_value': len(strong_top50),
                'signal': signal_2,
                'stocks': strong_top50,
            },
            {
                'name': '历史新高',
                'data': f"{new_high_count} 只",
                'data_value': new_high_count,
                'signal': signal_3,
                'stocks': new_high_stocks,
            },
        ],
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
    历史新高个股分析与板块效应聚类
    返回: 新高股池 + 行业聚类Top5 + 欧奈尔文案
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
        {'_id': 0, 'stock_code': 1, 'close': 1, 'chg_pct': 1, 'chg_20d': 1, 'amount': 1}
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

    # 筛选新高股：今日收盘 >= 历史最高收盘价
    new_high_stocks = []
    for code, doc in today_map.items():
        close = doc['close']
        max_close = hist_max.get(code, 0)
        if max_close > 0 and close >= max_close:
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

    # 获取股票名称
    name_cursor = db['stock_basics'].find(
        {}, {'_id': 0, 'stock_code': 1, 'stock_name': 1}
    )
    name_map = {d['stock_code']: d.get('stock_name', '') for d in name_cursor}

    # 计算新高股涨跌幅和成交额（直接用冗余字段）
    import math
    for s in new_high_stocks:
        today_doc = today_map.get(s['code'], {})
        s['pct_chg'] = today_doc.get('chg_pct', 0) or 0
        s['chg_20d'] = today_doc.get('chg_20d', 0) or 0
        amount = today_doc.get('amount', 0)
        s['amount'] = 0 if amount is None or math.isnan(amount) else amount
        s['name'] = name_map.get(s['code'], s['code'])

    # 行业聚类（一只股票可归属多个行业，分别计入）
    industries_map = _build_stock_industries_map()
    industry_groups = defaultdict(list)
    industry_stock_set = defaultdict(set)  # 去重用
    for s in new_high_stocks:
        inds = industries_map.get(s['code'], ['其他'])
        for ind in inds:
            if s['code'] not in industry_stock_set[ind]:
                industry_stock_set[ind].add(s['code'])
                industry_groups[ind].append(s)

    # Top5行业（按新高数量降序）
    sorted_industries = sorted(industry_groups.items(), key=lambda x: -len(x[1]))[:5]

    clusters = []
    for ind, stocks in sorted_industries:
        count = len(stocks)
        pct = round(count / total_new_high_count * 100, 1)
        
        # 计算平均涨幅
        avg_chg = round(sum(s['pct_chg'] for s in stocks) / len(stocks), 2) if stocks else 0
        
        # 按涨幅排序（今日涨幅）
        by_chg = sorted(stocks, key=lambda x: -x.get('pct_chg', 0))
        # 按20日涨幅排序
        by_chg20 = sorted(stocks, key=lambda x: -x.get('chg_20d', 0))
        # 按成交额排序取前5
        by_amount = sorted(stocks, key=lambda x: -x.get('amount', 0))[:5]

        # 代表个股：今日涨幅最高的4只
        representative = []
        seen_rep = set()
        for s in by_chg:
            if s['code'] not in seen_rep and len(representative) < 4:
                representative.append(f"{s['name']}({s['pct_chg']:+.1f}%)")
                seen_rep.add(s['code'])

        # 核心个股：20日涨幅最高取2只 + 成交额前5中取20日涨幅最高的2只
        top2_chg20 = by_chg20[:2]
        top2_amount = sorted(by_amount, key=lambda x: -x.get('chg_20d', 0))[:2]
        core_selected = []
        seen_core = set()
        for s in top2_chg20:
            if s['code'] not in seen_core:
                core_selected.append(s)
                seen_core.add(s['code'])
        for s in top2_amount:
            if s['code'] not in seen_core and len(core_selected) < 4:
                core_selected.append(s)
                seen_core.add(s['code'])
        if len(core_selected) < 4:
            for s in by_chg20:
                if s['code'] not in seen_core and len(core_selected) < 4:
                    core_selected.append(s)
                    seen_core.add(s['code'])
        core_stocks = [f"{s['name']}({s['chg_20d']:+.1f}%)" for s in core_selected[:4]]
        
        # 按涨幅排序的个股列表（用于点击弹出）
        stocks_sorted = sorted(stocks, key=lambda x: -x['pct_chg'])
        
        clusters.append({
            'industry': ind,
            'count': count,
            'pct': pct,
            'avg_chg': avg_chg,
            'representative_stocks': representative,
            'core_stocks': core_stocks,
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

    # 根据周期决定回溯日历天数（与趋势对比图 factors.py 保持一致）
    now = _dt.now()
    period_days = {
        'day': 120,
        'week': 365,
        'month': 365 * 3,
        'quarter': 365 * 5,
        'year': 365 * 10,
    }
    cal_days = period_days.get(period, 120)
    start_date = (now - timedelta(days=cal_days)).strftime('%Y%m%d')

    # 按日期范围筛选交易日
    target_dates = [d for d in all_dates if d >= start_date]
    target_dates.reverse()

    # 计算每日占比
    daily_data = {}
    for d in target_dates:
        pipeline = [
            {'$match': {'trade_date': d, 'close': {'$gt': 0}, 'ma50': {'$gt': 0}}},
            {'$group': {
                '_id': None,
                'total': {'$sum': 1},
                'above_ma50': {'$sum': {'$cond': [{'$gt': ['$close', '$ma50']}, 1, 0]}},
                'above_ma20': {'$sum': {'$cond': [{'$gt': ['$close', '$ma20']}, 1, 0]}}
            }}
        ]
        result = list(db['stock_daily'].aggregate(pipeline))
        if result and result[0]['total'] > 0:
            r = result[0]
            daily_data[d] = {
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


@router.get("/ma-breadth")
def get_ma_breadth(
    period: str = Query("day", description="聚合周期: day/week/month/quarter/year"),
    index_code: Optional[str] = Query(None, description="叠加指数代码")
):
    """MA50和MA20占比历史曲线"""
    try:
        result = calc_ma_breadth_history(period=period, index_code=index_code)
        if not result.get('success'):
            raise HTTPException(status_code=404, detail=result.get('message', '无数据'))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取MA占比失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取MA占比失败: {str(e)}")


@router.get("/new-high-blocks")
def get_new_high_blocks(date: Optional[str] = Query(None, description="交易日期 YYYYMMDD")):
    """历史新高个股分析与板块效应聚类"""
    try:
        result = analyze_new_high_blocks(latest_date=date)
        if not result.get('success'):
            raise HTTPException(status_code=404, detail=result.get('message', '无数据'))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取新高板块分析失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取新高板块分析失败: {str(e)}")


@router.get("/signals")
def get_market_signals(date: Optional[str] = Query(None, description="交易日期 YYYYMMDD")):
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


@router.get("/overview")
def get_market_overview(date: Optional[str] = Query(None, description="交易日期 YYYYMMDD")):
    """主要宽基指数涨跌幅 + 核心结论"""
    try:
        result = generate_market_overview(latest_date=date)
        if not result.get('success'):
            raise HTTPException(status_code=404, detail=result.get('message', '无数据'))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取市场概览失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取市场概览失败: {str(e)}")


@router.get("")
def get_market_review():
    """获取全栈量化复盘报告数据"""
    try:
        latest_date = _get_latest_trade_date()
        if not latest_date:
            raise HTTPException(status_code=404, detail="暂无交易数据")

        market_summary = _calc_market_summary_fast(latest_date)
        strong_stocks = _calc_strong_stocks(latest_date)
        industry_cluster = _calc_industry_cluster(strong_stocks)

        return {
            'success': True,
            'trade_date': latest_date,
            'market_summary': market_summary,
            'strong_stocks_top50': strong_stocks,
            'industry_cluster': industry_cluster
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取复盘数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取复盘数据失败: {str(e)}")
