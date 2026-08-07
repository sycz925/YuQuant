"""
因子服务层
处理预计算、PE同步、对比任务等后台业务逻辑
从 api/factors.py 迁移而来
"""
import logging
import threading
from typing import Optional

from app.data.db import get_db

logger = logging.getLogger(__name__)

# ========== 对比任务共享状态 ==========

_compare_tasks = {}
_compare_lock = threading.Lock()


def _compare_update_status(task_id, **kwargs):
    with _compare_lock:
        if task_id in _compare_tasks:
            _compare_tasks[task_id].update(kwargs)


# ========== 预计算后台任务 ==========

def _run_precompute_base_for_date(task_id: str, target_date: str, is_external: bool = False):
    """按指定日期预计算 base_data_daily + market_daily"""
    from app.data.task_manager import get_task_manager
    from app.server.services.market_data import _compute_realtime
    from app.server.services.market_signals import generate_market_overview
    from app.server.services.market_sectors import analyze_new_high_blocks
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo

    tm = get_task_manager()
    
    def _safe_update_progress(**kwargs):
        """安全更新进度，外部任务不更新total_count和completed_count"""
        if is_external:
            kwargs.pop('total_count', None)
            kwargs.pop('completed_count', None)
        tm.update_task_progress(task_id, **kwargs)
    try:
        db = get_db()

        # 判断是否是盘后：历史日期始终是盘后，今天根据当前时间判断
        now_bj = _dt.now(ZoneInfo('Asia/Shanghai'))
        today_str = now_bj.strftime('%Y%m%d')
        if target_date == today_str:
            is_market_closed = now_bj.hour > 15 or (now_bj.hour == 15 and now_bj.minute >= 30)
        else:
            is_market_closed = True  # 历史日期始终是盘后

        # ---- Step 1: base_data_daily ----
        _safe_update_progress( current_stock_name=f"计算 {target_date} CR5/CR10/MA/NH-NL...")

        merged_row = {'date': target_date, 'is_final': is_market_closed}
        for dtype in ['cr5', 'cr10', 'ma', 'nh-nl']:
            try:
                row = _compute_realtime(dtype, target_date)
                if row:
                    for k, v in row.items():
                        if k not in ('date', 'is_final'):
                            merged_row[k] = v
            except Exception as e:
                logger.warning(f"[预计算] {dtype} 失败: {e}")

        # ---- 涨跌家数 ----
        _safe_update_progress( current_stock_name=f"计算 {target_date} 涨跌家数...")
        try:
            stock_pipeline = [
                {'$match': {'trade_date': target_date, 'close': {'$gt': 0}}},
                {'$group': {
                    '_id': None,
                    'up_count': {'$sum': {'$cond': [{'$gt': ['$chg_pct', 0]}, 1, 0]}},
                    'down_count': {'$sum': {'$cond': [{'$lt': ['$chg_pct', 0]}, 1, 0]}},
                }}
            ]
            stock_stats = list(db['stock_daily'].aggregate(stock_pipeline))
            if stock_stats:
                merged_row['up_count'] = stock_stats[0]['up_count']
                merged_row['down_count'] = stock_stats[0]['down_count']
        except Exception as e:
            logger.warning(f"[预计算] 涨跌家数失败: {e}")

        # ---- 总成交额（上证+深综）----
        _safe_update_progress( current_stock_name=f"计算 {target_date} 总成交额...")
        try:
            index_amounts = list(db['index_daily'].find(
                {'trade_date': target_date, 'stock_code': {'$in': ['000001', '399106']}},
                {'_id': 0, 'amount': 1}
            ))
            merged_row['total_amount'] = round(sum(d.get('amount', 0) for d in index_amounts), 2)
        except Exception as e:
            logger.warning(f"[预计算] 总成交额失败: {e}")

        # upsert 到 base_data_daily
        db['base_data_daily'].update_one(
            {'date': target_date},
            {'$set': merged_row},
            upsert=True
        )

        _safe_update_progress( current_stock=50, current_stock_name=f"{target_date} base_data_daily 完成")

        # ---- Step 2: market_daily ----
        _safe_update_progress( current_stock=50, current_stock_name=f"计算 {target_date} overview/signals/new_high...")

        overview = generate_market_overview(target_date)
        overview_clean = {k: v for k, v in overview.items() if k not in ('style',)}

        # 补充各指数成交额数据
        try:
            indices = overview_clean.get('indices', [])
            if indices:
                index_codes = [idx['code'] for idx in indices if idx.get('code')]
                yesterday_candidates = [d for d in sorted(db['index_daily'].distinct('trade_date'), reverse=True) if d < target_date]
                yesterday = yesterday_candidates[0] if yesterday_candidates else None

                today_idx = {d['stock_code']: d for d in db['index_daily'].find(
                    {'stock_code': {'$in': index_codes}, 'trade_date': target_date},
                    {'_id': 0, 'stock_code': 1, 'amount': 1}
                )}
                yest_idx = {}
                if yesterday:
                    yest_idx = {d['stock_code']: d for d in db['index_daily'].find(
                        {'stock_code': {'$in': index_codes}, 'trade_date': yesterday},
                        {'_id': 0, 'stock_code': 1, 'amount': 1}
                    )}

                vol_map = {}
                for code in index_codes:
                    rows = list(db['index_daily'].find(
                        {'stock_code': code},
                        {'_id': 0, 'amount': 1}
                    ).sort('trade_date', -1).limit(20))
                    vol_map[code] = [d.get('amount', 0) or 0 for d in rows]

                for idx in indices:
                    code = idx.get('code', '')
                    today_amt = today_idx.get(code, {}).get('amount', 0) or 0
                    yest_amt = yest_idx.get(code, {}).get('amount', 0) or 0
                    amounts = vol_map.get(code, [])
                    ma5 = round(sum(amounts[:5]) / min(len(amounts), 5) / 1e8, 1) if amounts else 0
                    ma20 = round(sum(amounts[:20]) / min(len(amounts), 20) / 1e8, 1) if amounts else 0
                    idx['amount_today'] = round(today_amt / 1e8, 1) if today_amt else 0
                    idx['amount_yesterday'] = round(yest_amt / 1e8, 1) if yest_amt else 0
                    idx['amount_ma5'] = ma5
                    idx['amount_ma20'] = ma20
        except Exception as e:
            logger.warning(f"[预计算] 成交额补充失败: {e}")

        _safe_update_progress( current_stock=60, current_stock_name=f"计算 {target_date} 新高板块...")

        nh_result = analyze_new_high_blocks(target_date)
        _safe_update_progress( current_stock=75, current_stock_name=f"计算 {target_date} 低位潜力板块...")

        from app.server.services.market_sectors import analyze_low_position_sectors
        lps_result = analyze_low_position_sectors(target_date)
        _safe_update_progress( current_stock=80, current_stock_name=f"计算 {target_date} 异动活跃板块...")

        from app.server.services.market_sectors import analyze_active_sectors
        active_result = analyze_active_sectors(target_date)
        _safe_update_progress( current_stock=90, current_stock_name=f"落库 {target_date} market_daily...")

        # 计算分组统计
        group_stats = {}
        try:
            from app.server.api.market_analysis import _quantile_groups

            enabled_stock_codes = set(
                doc['stock_code'] for doc in db['stock_basics'].find(
                    {'is_disable': {'$ne': True}},
                    {'_id': 0, 'stock_code': 1}
                )
            )
            today_stocks = {d['stock_code']: d for d in db['stock_daily'].find(
                {'trade_date': target_date, 'close': {'$gt': 0}, 'amount': {'$gt': 0},
                 'stock_code': {'$in': list(enabled_stock_codes)}},
                {'_id': 0, 'stock_code': 1, 'close': 1, 'amount': 1, 'chg_pct': 1,
                 'rps_10': 1, 'rps_20': 1, 'rps_50': 1, 'rps_120': 1, 'rps_250': 1}
            )}

            float_mv_map = {}
            try:
                from app.data.sources.tencent_mv import get_float_mv_batch
                stock_codes = list(today_stocks.keys())
                float_mv_map = get_float_mv_batch(stock_codes)
            except Exception as e:
                logger.warning(f"腾讯接口获取流通市值失败: {e}")
                for doc in db['stock_basics'].find(
                    {'stock_code': {'$in': list(today_stocks.keys())}},
                    {'_id': 0, 'stock_code': 1, 'liutongguben': 1}
                ):
                    if doc.get('liutongguben'):
                        row = today_stocks.get(doc['stock_code'], {})
                        if row.get('close'):
                            float_mv_map[doc['stock_code']] = round(doc['liutongguben'] * row['close'] / 1e8, 2)

            merged = []
            for code, row in today_stocks.items():
                chg_pct = row.get('chg_pct')
                if chg_pct is not None:
                    float_mv = float_mv_map.get(code, 0)
                    merged.append({
                        'chg_pct': chg_pct,
                        'close': row['close'],
                        'amount': row['amount'],
                        'rps': row.get('rps_20'),
                        'float_mv': float_mv,
                    })

            if merged:
                rps_data = [{'chg_pct': d['chg_pct'], 'sort_val': d['rps']} for d in merged if d.get('rps') is not None and d.get('rps') > 0]
                group_stats['rps_stats'] = _quantile_groups(rps_data, n_groups=20)

                amount_data = [{'chg_pct': d['chg_pct'], 'sort_val': d['amount']} for d in merged]
                group_stats['amount_stats'] = _quantile_groups(amount_data, n_groups=20)

                price_data = [{'chg_pct': d['chg_pct'], 'sort_val': d['close']} for d in merged]
                group_stats['price_stats'] = _quantile_groups(price_data, n_groups=20)

                mv_data = [{'chg_pct': d['chg_pct'], 'sort_val': d['float_mv']} for d in merged if d.get('float_mv', 0) > 0]
                group_stats['float_mv_stats'] = _quantile_groups(mv_data, n_groups=20)

        except Exception as e:
            logger.warning(f"计算分组统计失败: {e}")

        # 落库 market_daily
        db['market_daily'].update_one(
            {'trade_date': target_date},
            {
                '$set': {
                    'overview': overview_clean,
                    'new_high': {
                        'total_count': nh_result.get('total_new_high_count', 0),
                        'clusters': nh_result.get('industry_clusters', [])[:10],
                    },
                    'low_position_sectors': lps_result.get('sectors', []),
                    'active_sectors': active_result.get('sectors', []),
                    'group_stats': group_stats,
                    'compute_time': _dt.now().isoformat(),
                    'is_final': is_market_closed,
                },
                '$unset': {
                    'signals': '',
                }
            },
            upsert=True,
        )

        _safe_update_progress( current_stock=100, current_stock_name=f"{target_date} 预计算完成")
        if not is_external:
            tm.complete_task(task_id, f"{target_date} 基础数据预计算完成")

    except Exception as e:
        logger.error(f"预计算失败: {e}")
        tm.fail_task(task_id, str(e)[:200])


# ========== PE 同步后台任务 ==========

def _run_sync_pe(task_id: str, token: str, is_external: bool = False):
    """后台执行PE同步"""
    import time, requests as _req
    from hashlib import md5 as _md5
    from bs4 import BeautifulSoup
    from app.data.task_manager import get_task_manager

    db = get_db()
    tm = get_task_manager()

    def _safe_update_progress(**kwargs):
        if is_external:
            kwargs.pop('total_count', None)
            kwargs.pop('completed_count', None)
        tm.update_task_progress(task_id, **kwargs)

    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
        session = _req.Session()
        session.headers.update(headers)

        _safe_update_progress( current_stock_name="获取CSRF...")
        r0 = session.get('https://legulegu.com/stockdata/shanghaiPE', timeout=15)
        soup = BeautifulSoup(r0.text, 'html.parser')
        meta = soup.find('meta', attrs={'name': 'csrf-token'})
        csrf = meta.attrs['content'] if meta else ''
        session.cookies.set('XSRF-TOKEN', csrf)

        PE_ENDPOINTS = {
            '000001': ('/api/stock-data/market-pe', {'marketId': 1}, 'pe'),
            '399106': ('/api/stock-data/market-pe', {'marketId': 2}, 'pe'),
            '399006': ('/api/stock-data/market-pe', {'marketId': 4}, 'pe'),
            '000688': ('/api/stockdata/index-basic-pe', {'indexCode': '000688.SH'}, 'ttmPe'),
            '880823': ('/api/stockdata/index-basic-pe', {'indexCode': '000901.LG'}, 'ttmPe'),
            '000300': ('/api/stockdata/index-basic-pe', {'indexCode': '000300.SH'}, 'ttmPe'),
            '000016': ('/api/stockdata/index-basic-pe', {'indexCode': '000016.SH'}, 'ttmPe'),
            '000905': ('/api/stockdata/index-basic-pe', {'indexCode': '000905.SH'}, 'ttmPe'),
            '000852': ('/api/stockdata/index-basic-pe', {'indexCode': '000852.SH'}, 'ttmPe'),
            '000906': ('/api/stockdata/index-basic-pe', {'indexCode': '000906.SH'}, 'ttmPe'),
            '000903': ('/api/stockdata/index-basic-pe', {'indexCode': '000903.SH'}, 'ttmPe'),
            '000010': ('/api/stockdata/index-basic-pe', {'indexCode': '000010.SH'}, 'ttmPe'),
            '000009': ('/api/stockdata/index-basic-pe', {'indexCode': '000009.SH'}, 'ttmPe'),
            '000015': ('/api/stockdata/index-basic-pe', {'indexCode': '000015.SH'}, 'ttmPe'),
            '399324': ('/api/stockdata/index-basic-pe', {'indexCode': '399324.SZ'}, 'ttmPe'),
            '399330': ('/api/stockdata/index-basic-pe', {'indexCode': '399330.SZ'}, 'ttmPe'),
            '399673': ('/api/stockdata/index-basic-pe', {'indexCode': '399673.SZ'}, 'ttmPe'),
            '880003': ('/api/stock-data/market-ttm-lyr', {'marketId': 5}, 'averagePETTM'),
        }

        index_cursor = db['index_basics'].find({'is_disable': {'$ne': True}}, {'_id': 0, 'code': 1, 'name': 1})
        enabled_indices = {c['code']: c['name'] for c in index_cursor}

        to_sync = [(code, name) for code, name in enabled_indices.items() if code in PE_ENDPOINTS]
        total = len(to_sync)
        results = {}
        success_count = 0

        for i, (code, name) in enumerate(to_sync):
            if tm.is_cancelled(task_id):
                return
            path, params, pe_field = PE_ENDPOINTS[code]
            tm.update_task_progress(
                task_id, current_stock=code,
                current_stock_name=f"同步 {name} PE...",
                total_count=total, completed_count=i,
            )
            time.sleep(1)
            try:
                r = session.get(
                    f'https://legulegu.com{path}',
                    params={**params, 'token': token},
                    timeout=15
                )
                if r.status_code != 200 or not r.text.strip().startswith('{'):
                    continue
                data = r.json()
                d = data.get('data', {})
                pe_val = None
                pe_date = None
                if isinstance(d, dict):
                    pe_val = d.get(pe_field)
                    pe_date = d.get('date')
                elif isinstance(d, list) and d:
                    pe_val = d[-1].get(pe_field)
                    pe_date = d[-1].get('date')
                if pe_val and pe_date:
                    pe_val = round(float(pe_val), 2)
                    db['index_basics'].update_one(
                        {'code': code},
                        {'$set': {'pe_ttm': pe_val}},
                        upsert=True,
                    )
                    results[name] = {'pe_ttm': pe_val, 'date': pe_date}
                    success_count += 1
            except Exception as e:
                logger.warning(f"[PE] {name}({code}) 同步失败: {e}")

        tm.update_task_progress(
            task_id, current_stock_name=f"PE同步完成 ({success_count}/{total})",
            total_count=total, completed_count=total,
        )
        if not is_external:
            tm.complete_task(task_id, f"PE同步完成，{success_count}/{total}个指数")

    except Exception as e:
        logger.error(f"PE同步失败: {e}")
        if not is_external:
            tm.fail_task(task_id, str(e)[:200])
        raise


# ========== 对比任务 ==========

def _run_compare_stocks_task(task_id):
    """后台执行个股对比任务"""
    try:
        db = get_db()

        # 1. 获取本地所有股票代码
        _compare_update_status(task_id, step='获取本地数据', progress='0%')
        local_codes = set(
            doc['stock_code'] for doc in db['stock_basics'].find(
                {}, {'_id': 0, 'stock_code': 1}
            )
        )

        # 2. 从 pytdx 获取远程股票列表
        _compare_update_status(task_id, step='连接pytdx', progress='20%')
        import sys
        if '_vendor/pytdx' not in sys.path:
            sys.path.insert(0, '_vendor/pytdx')
        from pytdx.hq import TdxHq_API
        from app.data.sources.pytdx_source import TDX_SERVERS

        api = TdxHq_API()
        remote_stocks = []
        seen_codes = set()

        valid_prefixes = ('00', '30', '60', '68')

        for host, port in TDX_SERVERS:
            try:
                api.connect(host, port)
                for market in [0, 1]:
                    _compare_update_status(task_id, step=f'获取{"沪" if market else "深"}市数据', progress='40%')
                    count = api.get_security_count(market)
                    for start in range(0, min(count, 50000), 1000):
                        items = api.get_security_list(market, start)
                        for s in items:
                            code = s.get('code', '')
                            name = s.get('name', '')
                            if (code and name and len(code) == 6 and code.isdigit()
                                and code[:2] in valid_prefixes
                                and code not in seen_codes):
                                seen_codes.add(code)
                                remote_stocks.append({
                                    'stock_code': code,
                                    'stock_name': name,
                                    'market': market,
                                })
                api.disconnect()
                break
            except Exception as e:
                logger.warning(f"pytdx连接失败 {host}:{port}: {e}")
                continue

        # 3. 找出新增的股票
        _compare_update_status(task_id, step='对比数据', progress='80%')
        remote_set = {s['stock_code'] for s in remote_stocks}
        new_codes = remote_set - local_codes
        new_stocks = [s for s in remote_stocks if s['stock_code'] in new_codes]
        new_stocks.sort(key=lambda x: x['stock_code'])

        # 4. 存储结果
        _compare_update_status(
            task_id,
            status='completed',
            step='完成',
            progress='100%',
            result={
                'local_count': len(local_codes),
                'remote_count': len(remote_set),
                'new_count': len(new_stocks),
                'new_stocks': new_stocks[:100],
            }
        )

    except Exception as e:
        logger.error(f"对比个股任务失败: {e}")
        _compare_update_status(task_id, status='failed', error=str(e))


def _run_compare_sectors_task(task_id):
    """后台执行板块对比任务"""
    try:
        db = get_db()

        # 1. 获取本地所有板块（名称+成分股）
        _compare_update_status(task_id, step='获取本地数据', progress='0%')
        local_sector_map = {}
        for doc in db['sector_basics'].find({}, {'_id': 0, 'name': 1, 'stock_codes': 1, 'code': 1}):
            name = doc.get('name', '')
            stock_codes = set(doc.get('stock_codes', []))
            if name:
                key = (name, frozenset(stock_codes))
                local_sector_map[key] = doc.get('code', '')

        # 2. 从 pytdx 获取远程板块列表
        _compare_update_status(task_id, step='连接pytdx获取板块', progress='30%')
        import sys
        if '_vendor/pytdx' not in sys.path:
            sys.path.insert(0, '_vendor/pytdx')
        from app.data.sources.pytdx_source import PytdxSource

        local_name_to_code = {}
        for doc in db['sector_basics'].find({}, {'_id': 0, 'name': 1, 'code': 1}):
            local_name_to_code[doc['name']] = doc.get('code', '')

        pytdx = PytdxSource()
        remote_sectors = []

        try:
            blocks = pytdx.get_concept_blocks()
            for idx, block in enumerate(blocks):
                name = block.get('name', '')
                stock_codes = block.get('stock_codes', [])
                if name and stock_codes:
                    code = local_name_to_code.get(name, '')
                    remote_sectors.append({
                        'code': code,
                        'name': name,
                        'stock_count': len(stock_codes),
                        'stock_codes': stock_codes[:10],
                        'all_stock_codes': stock_codes,
                    })
        except Exception as e:
            logger.warning(f"获取pytdx板块失败: {e}")

        # 3. 按名称+成分股匹配找出新增的板块
        _compare_update_status(task_id, step='对比数据', progress='80%')
        new_sectors = []
        for sector in remote_sectors:
            key = (sector['name'], frozenset(sector['all_stock_codes']))
            if key not in local_sector_map:
                code = sector.get('code', '')
                if not code:
                    status = '无code'
                elif db['sector_basics'].find_one({'code': code}):
                    status = '待更新'
                else:
                    status = '待加入'
                sector['status'] = status
                new_sectors.append(sector)
        
        new_sectors.sort(key=lambda x: -x['stock_count'])

        # 4. 存储结果
        _compare_update_status(
            task_id,
            status='completed',
            step='完成',
            progress='100%',
            result={
                'local_count': len(local_sector_map),
                'remote_count': len(remote_sectors),
                'new_count': len(new_sectors),
                'new_sectors': new_sectors[:50],
            }
        )

    except Exception as e:
        logger.error(f"对比板块任务失败: {e}")
        _compare_update_status(task_id, status='failed', error=str(e))