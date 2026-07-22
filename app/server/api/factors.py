"""
因子 API 路由层

路由函数只负责：接收请求 → 调用工厂/服务 → 返回结果。
所有业务逻辑、数据库访问、后台任务调度均在工厂层中。
"""
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, UploadFile
from pydantic import BaseModel

from app.server.factories import get_index_factory, get_stock_factory, get_sector_factory, get_market_aggregator
from app.data.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/factors", tags=["factors"])


# ==================== CR5% ====================

@router.get("/cr5")
def get_cr5_factor(
    start_date: Optional[str] = Query(None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD"),
    include_index: bool = Query(True, description="是否包含指数数据"),
    period: str = Query("day", description="聚合周期: day/week/month/quarter/year"),
):
    """获取CR5%因子数据（支持日/周/月/季/年聚合，默认近一年日数据）"""
    try:
        factory = get_index_factory()
        result = factory.get_cr5_data(start_date, end_date, include_index, period)
        if result is None:
            raise HTTPException(status_code=404, detail="暂无因子数据")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取CR5因子失败: {e}")
        raise HTTPException(status_code=500, detail="获取因子数据失败")


# ==================== 指数管理 ====================

@router.get("/indices")
def get_indices_list(
    page: Optional[int] = Query(None, ge=1, description="页码"),
    page_size: Optional[int] = Query(50, ge=1, le=500, description="每页数量"),
    keyword: Optional[str] = Query(None, description="搜索关键词（代码或名称）"),
    filter_mode: Optional[str] = Query(None, description="筛选模式: enabled/disabled"),
):
    """获取指数列表（支持分页、搜索和状态筛选）"""
    try:
        factory = get_index_factory()
        return factory.get_indices_list(page, page_size or 50, keyword, filter_mode)
    except Exception as e:
        logger.error(f"获取指数列表失败: {e}")
        raise HTTPException(status_code=500, detail="获取指数列表失败")


@router.get("/indices/search")
def search_indices(keyword: str = Query(..., description="搜索关键词（代码或名称）")):
    """搜索指数（先本地数据库，再查通达信 TDX）"""
    try:
        factory = get_index_factory()
        return factory.search_indices(keyword)
    except Exception as e:
        logger.error(f"搜索指数失败: {e}")
        raise HTTPException(status_code=500, detail="搜索指数失败")


@router.post("/sync-indices")
def sync_index_data(
    start_date: Optional[str] = Query(None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD"),
    max_workers: Optional[int] = Query(4, description="最大线程数"),
):
    """同步所有指数数据（后台任务）"""
    try:
        from app.server.api.sync import _check_sync_time
        allowed, msg = _check_sync_time()
        if not allowed:
            return {"success": False, "message": msg}
        return get_factor_service().sync_index_data(start_date, end_date, max_workers or 4)
    except Exception as e:
        logger.error(f"启动指数同步任务失败: {e}")
        return {"success": False, "message": str(e)}


# ==================== 预计算基础数据 ====================

@router.post("/precompute-base")
def precompute_base_data():
    """一键预计算 base_data_daily + market_daily（后台任务）"""
    import threading
    try:
        from app.data.task_manager import get_task_manager
        from app.data.db import get_db
        tm = get_task_manager()
        db = get_db()
        
        # 检查是否有正在运行的预计算任务
        running_task = db['sync_tasks'].find_one(
            {'status': 'running', 'current_stock_name': {'$regex': '预计算|base_data|market_daily'}},
            sort=[('created_at', -1)]
        )
        
        if running_task:
            task_id = running_task['task_id']
            return {'success': True, 'task_id': task_id, 'already_running': True}
        
        task_id = tm.create_task()

        thread = threading.Thread(
            target=_run_precompute_base,
            args=(task_id,),
            daemon=True,
        )
        thread.start()
        return {'success': True, 'task_id': task_id}
    except Exception as e:
        logger.error(f"启动预计算失败: {e}")
        return {'success': False, 'message': str(e)[:200]}


def _run_precompute_base(task_id: str, is_external: bool = False):
    """后台执行 base_data_daily + market_daily 预计算"""
    from app.data.db import get_db
    from app.data.task_manager import get_task_manager
    from app.server.api.market_review import _compute_realtime, generate_market_overview, analyze_new_high_blocks
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

        # 获取最新交易日
        dates = sorted(db['stock_daily'].distinct('trade_date', {'close': {'$gt': 0}}), reverse=True)
        latest = dates[0] if dates else None
        if not latest:
            tm.fail_task(task_id, "无交易数据")
            return

        now_bj = _dt.now(ZoneInfo('Asia/Shanghai'))
        is_market_closed = now_bj.hour > 15 or (now_bj.hour == 15 and now_bj.minute >= 30)

        # ---- Step 1: base_data_daily ----
        _safe_update_progress( current_stock_name="计算 CR5/CR10/MA/NH-NL...")

        merged_row = {'date': latest, 'is_final': is_market_closed}
        for dtype in ['cr5', 'cr10', 'ma', 'nh-nl']:
            try:
                row = _compute_realtime(dtype, latest)
                if row:
                    for k, v in row.items():
                        if k not in ('date', 'is_final'):
                            merged_row[k] = v
            except Exception as e:
                logger.warning(f"[预计算] {dtype} 失败: {e}")

        # ---- 涨跌家数 ----
        _safe_update_progress( current_stock_name="计算涨跌家数...")
        try:
            stock_pipeline = [
                {'$match': {'trade_date': latest, 'close': {'$gt': 0}}},
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
        _safe_update_progress( current_stock_name="计算总成交额...")
        try:
            index_amounts = list(db['index_daily'].find(
                {'trade_date': latest, 'stock_code': {'$in': ['000001', '399106']}},
                {'_id': 0, 'amount': 1}
            ))
            merged_row['total_amount'] = round(sum(d.get('amount', 0) for d in index_amounts), 2)
        except Exception as e:
            logger.warning(f"[预计算] 总成交额失败: {e}")

        # upsert 到 base_data_daily
        db['base_data_daily'].update_one(
            {'date': latest},
            {'$set': merged_row},
            upsert=True
        )

        _safe_update_progress( current_stock=50, current_stock_name="base_data_daily 完成")

        # ---- Step 1.5: 获取流通股本（如果没有数据）----
        liutong_count = db['stock_basics'].count_documents({'liutongguben': {'$gt': 0}})
        if liutong_count < 1000:  # 如果流通股本数据不足，批量获取
            _safe_update_progress( current_stock=52, current_stock_name="获取流通股本...")
            try:
                from app.data.sources.pytdx_source import _get_connection_for_liutong, _return_connection
                api = _get_connection_for_liutong()
                if api:
                    stock_basics = list(db['stock_basics'].find(
                        {'liutongguben': {'$exists': False}},
                        {'_id': 0, 'stock_code': 1, 'market': 1}
                    ))
                    updated = 0
                    for doc in stock_basics:
                        code = doc['stock_code']
                        market = 1 if code.startswith('6') else 0
                        try:
                            finance_info = api.get_finance_info(market, code)
                            if finance_info and finance_info.get('liutongguben'):
                                db['stock_basics'].update_one(
                                    {'stock_code': code},
                                    {'$set': {'liutongguben': finance_info['liutongguben']}}
                                )
                                updated += 1
                        except Exception:
                            pass
                    _return_connection(api)
                    logger.info(f"获取流通股本完成: 更新 {updated} 只股票")
            except Exception as e:
                logger.warning(f"获取流通股本失败: {e}")

        # ---- Step 2: market_daily ----
        _safe_update_progress( current_stock=50, current_stock_name="计算 overview/signals/new_high...")

        overview = generate_market_overview(latest)
        overview_clean = {k: v for k, v in overview.items() if k not in ('conclusion', 'style')}

        # 补充各指数成交额数据（今日、昨日、MA5、MA20）
        try:
            indices = overview_clean.get('indices', [])
            if indices:
                index_codes = [idx['code'] for idx in indices if idx.get('code')]
                yesterday_candidates = [d for d in sorted(db['index_daily'].distinct('trade_date'), reverse=True) if d < latest]
                yesterday = yesterday_candidates[0] if yesterday_candidates else None

                today_idx = {d['stock_code']: d for d in db['index_daily'].find(
                    {'stock_code': {'$in': index_codes}, 'trade_date': latest},
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

        _safe_update_progress( current_stock=60, current_stock_name="计算新高板块...")

        nh_result = analyze_new_high_blocks(latest)
        _safe_update_progress( current_stock=85, current_stock_name="计算低位潜力板块...")

        from app.server.api.market_review import analyze_low_position_sectors
        lps_result = analyze_low_position_sectors(latest)
        _safe_update_progress( current_stock=90, current_stock_name="落库 market_daily...")

        # 计算分组统计（RPS/成交额/股价/流通市值）
        group_stats = {}
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
                {'trade_date': latest, 'close': {'$gt': 0}, 'amount': {'$gt': 0},
                 'stock_code': {'$in': list(enabled_stock_codes)}},
                {'_id': 0, 'stock_code': 1, 'close': 1, 'amount': 1, 'chg_pct': 1,
                 'rps_10': 1, 'rps_20': 1, 'rps_50': 1, 'rps_120': 1, 'rps_250': 1}
            )}

            # 获取流通市值（优先从腾讯接口，其次从stock_basics）
            float_mv_map = {}
            try:
                from app.data.sources.tencent_mv import get_float_mv_batch
                stock_codes = list(today_stocks.keys())
                float_mv_map = get_float_mv_batch(stock_codes)
                logger.info(f"从腾讯接口获取 {len(float_mv_map)} 只股票流通市值")
            except Exception as e:
                logger.warning(f"腾讯接口获取流通市值失败: {e}，尝试从stock_basics获取")
                # 降级：从stock_basics获取流通股本计算
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

            logger.info(f"分组统计完成: {len(group_stats)} 个分组")
        except Exception as e:
            logger.warning(f"计算分组统计失败: {e}")

        # 落库 market_daily（overview 已清理 conclusion/style）
        db['market_daily'].update_one(
            {'trade_date': latest},
            {
                '$set': {
                    'overview': overview_clean,
                    'new_high': {
                        'total_count': nh_result.get('total_new_high_count', 0),
                        'clusters': nh_result.get('industry_clusters', [])[:10],
                    },
                    'low_position_sectors': lps_result.get('sectors', []),
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

        _safe_update_progress( current_stock=100, current_stock_name="预计算完成")
        
        # 生成日历快照
        try:
            from app.server.api.calendar import generate_calendar_snapshot, save_calendar_snapshot
            snapshot = generate_calendar_snapshot(latest, db)
            if snapshot:
                save_calendar_snapshot(latest, snapshot, db)
                logger.info(f"日历快照生成成功: {latest}")
        except Exception as e:
            logger.warning(f"生成日历快照失败: {e}")
        
        if not is_external:
            tm.complete_task(task_id, f"基础数据预计算完成 ({latest})")

    except Exception as e:
        logger.error(f"预计算失败: {e}")
        tm.fail_task(task_id, str(e)[:200])


def _run_precompute_base_for_date(task_id: str, target_date: str, is_external: bool = False):
    """按指定日期预计算 base_data_daily + market_daily"""
    from app.data.db import get_db
    from app.data.task_manager import get_task_manager
    from app.server.api.market_review import _compute_realtime, generate_market_overview, analyze_new_high_blocks
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
        overview_clean = {k: v for k, v in overview.items() if k not in ('conclusion', 'style')}

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

        from app.server.api.market_review import analyze_low_position_sectors
        lps_result = analyze_low_position_sectors(target_date)
        _safe_update_progress( current_stock=80, current_stock_name=f"计算 {target_date} 异动活跃板块...")

        from app.server.api.market_review import analyze_active_sectors
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


# ==================== PE 同步 ====================

@router.post("/sync-index-pe")
def sync_index_pe(token: str = Query(..., description="乐咕乐股 Token")):
    """从乐咕乐股同步指数PE数据（后台任务）"""
    import threading
    try:
        from app.data.task_manager import get_task_manager
        tm = get_task_manager()
        task_id = tm.create_task()

        thread = threading.Thread(
            target=_run_sync_pe,
            args=(task_id, token),
            daemon=True,
        )
        thread.start()
        return {'success': True, 'task_id': task_id}
    except Exception as e:
        logger.error(f"启动PE同步失败: {e}")
        return {'success': False, 'message': str(e)[:200]}


def _run_sync_pe(task_id: str, token: str, is_external: bool = False):
    """后台执行PE同步"""
    import time, requests as _req
    from hashlib import md5 as _md5
    from bs4 import BeautifulSoup
    from app.data.db import get_db
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


# ==================== RPS ====================

@router.post("/rps/calculate", response_model=Dict[str, Any])
def calculate_and_save_rps(
    start_date: Optional[str] = Query(None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD"),
    target_date: Optional[str] = Query(None, description="只计算指定日期的 RPS（增量模式）"),
    target: str = Query('stock', description="'stock' 个股 | 'sector' 板块 | 'all' 全部"),
    max_workers: Optional[int] = Query(16, description="最大线程数"),
    min_days: Optional[int] = Query(None, description="最小上市天数（可选）"),
    external_task_id: Optional[str] = Query(None, description="外部task_id（可选）"),
):
    """计算并保存 RPS 指标（后台任务）"""
    try:
        # 使用 MarketAggregator 的 calculate_rps 方法
        aggregator = get_market_aggregator()
        return aggregator.calculate_rps(target=target)
    except Exception as e:
        logger.error(f"启动 RPS 计算任务失败: {e}")
        return {"success": False, "message": f"启动任务失败: {str(e)}"}


@router.post("/tasks/clear", response_model=Dict[str, Any])
def clear_all_tasks():
    """清除所有后台任务状态（用于重置脏数据）"""
    try:
        aggregator = get_market_aggregator()
        return aggregator.clear_all_tasks()
    except Exception as e:
        logger.error(f"清除任务状态失败: {e}")
        return {"success": False, "message": str(e)}


@router.delete("/rps", response_model=Dict[str, Any])
def delete_rps_data(
    target: str = Query('all', description="'stock' 只清个股RPS | 'sector' 只清板块RPS | 'all' 全部"),
):
    """清除 RPS 数据（不删除日线，只清 rps_* 字段）"""
    try:
        aggregator = get_market_aggregator()
        return aggregator.delete_rps_data(target)
    except Exception as e:
        logger.error(f"清除 RPS 数据失败: {e}")
        return {"success": False, "message": str(e)}


@router.get("/rps/{code}", response_model=Dict[str, Any])
def get_stock_rps(
    code: str,
    start_date: Optional[str] = Query(None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD"),
    period: str = Query("day", description="数据周期: day/week/month"),
):
    """获取指定股票的 RPS 数据（支持日/周/月线聚合）"""
    try:
        factory = get_stock_factory()
        result = factory.get_stock_rps(code, start_date, end_date, period)
        if result is None:
            raise HTTPException(status_code=404, detail=f"股票 {code} 没有找到 RPS 数据")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取股票 RPS 失败: {e}")
        raise HTTPException(status_code=500, detail="获取 RPS 失败")


@router.get("/rps", response_model=Dict[str, Any])
def get_rps_by_date(
    trade_date: str = Query(..., description="交易日期 YYYYMMDD"),
    min_rps: Optional[int] = Query(None, description="最低 RPS 阈值（0-99），只返回 RPS 大于等于该值的股票"),
):
    """获取指定交易日的所有股票 RPS 数据"""
    try:
        factory = get_stock_factory()
        result = factory.get_rps_by_date(trade_date, min_rps)
        if result is None:
            raise HTTPException(status_code=404, detail=f"日期 {trade_date} 没有找到 RPS 数据")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取日期 RPS 失败: {e}")
        raise HTTPException(status_code=500, detail="获取 RPS 失败")


# ==================== 板块 ====================

@router.post("/sync-sectors", response_model=Dict[str, Any])
def sync_sectors(
    max_workers: Optional[int] = Query(16, description="最大线程数"),
    min_days: Optional[int] = Query(None, description="最小天数（可选）"),
):
    """同步板块日线 — 逐天回溯模式（后台任务）"""
    try:
        from app.server.api.sync import _check_sync_time
        allowed, msg = _check_sync_time()
        if not allowed:
            return {"success": False, "message": msg}
        factory = get_sector_factory()
        return factory.sync_daily(max_workers=max_workers or 16)
    except Exception as e:
        logger.error(f"启动板块同步任务失败: {e}")
        return {"success": False, "message": str(e)}


@router.get("/sectors", response_model=Dict[str, Any])
def get_sector_list(
    page: Optional[int] = Query(None, ge=1, description="页码"),
    page_size: Optional[int] = Query(50, ge=1, le=500, description="每页数量"),
    keyword: Optional[str] = Query(None, description="搜索关键词（代码或名称）"),
    filter_mode: Optional[str] = Query(None, description="筛选模式: enabled/disabled"),
    limit: Optional[int] = Query(None, description="返回数量（兼容旧接口）"),
    min_stock_count: Optional[int] = Query(5, description="最少成分股数"),
):
    """获取板块列表（支持分页、搜索和状态筛选，含RPS数据）"""
    try:
        factory = get_sector_factory()
        return factory.get_sector_list(
            page, page_size or 50, keyword, filter_mode, limit, min_stock_count or 0,
        )
    except Exception as e:
        logger.error(f"获取板块列表失败: {e}")
        return {"success": False, "message": str(e), "total": 0, "items": []}


class SectorDailyBar(BaseModel):
    trade_date: str
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[float] = None
    amount: Optional[float] = None
    change_pct: Optional[float] = None
    rps_10: Optional[float] = None
    rps_20: Optional[float] = None
    rps_50: Optional[float] = None


class SectorDailyResponse(BaseModel):
    code: str
    total: int
    data: List[SectorDailyBar]


@router.get("/sectors/{code}/daily", response_model=SectorDailyResponse)
def get_sector_daily_data(
    code: str,
    start_date: Optional[str] = Query(None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD"),
    limit: int = Query(200, description="返回数据条数"),
):
    """获取板块日线数据"""
    try:
        from app.data.db import get_db
        db = get_db()

        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
        if not start_date:
            start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")

        query = {
            'stock_code': code,
            'trade_date': {'$gte': start_date, '$lte': end_date}
        }
        cursor = db['sector_daily'].find(
            query,
            {'_id': 0, 'trade_date': 1, 'open': 1, 'high': 1, 'low': 1, 'close': 1,
             'vol': 1, 'amount': 1, 'change_pct': 1,
             'rps_10': 1, 'rps_20': 1, 'rps_50': 1, 'rps_120': 1, 'rps_250': 1}
        ).sort('trade_date', -1).limit(limit)

        items = list(cursor)
        if not items:
            raise HTTPException(status_code=404, detail=f"板块 {code} 暂无数据")

        # 映射字段：vol → volume
        for item in items:
            if 'vol' in item:
                item['volume'] = item.pop('vol')

        items.reverse()
        return SectorDailyResponse(code=code, total=len(items), data=items)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取板块日线数据失败: {e}")
        raise HTTPException(status_code=500, detail="获取板块日线数据失败")


@router.post("/sectors/import-codes")
async def import_sector_codes(file: UploadFile):
    """导入板块代码映射（Excel/CSV），用于将中文板块名匹配到数字代码"""
    try:
        content = await file.read()
        filename = file.filename or ''
        factory = get_sector_factory()
        return factory.import_sector_codes(content, filename)
    except Exception as e:
        logger.error(f"导入板块代码失败: {e}")
        return {"success": False, "message": str(e)}


@router.post("/sectors/import-eastmoney")
def import_eastmoney_sectors():
    """导入东方财富行业板块到 sector_basics（后台任务）"""
    import threading
    try:
        from app.data.task_manager import get_task_manager
        tm = get_task_manager()
        task_id = tm.create_task()

        thread = threading.Thread(
            target=_run_import_eastmoney,
            args=(task_id,),
            daemon=True,
        )
        thread.start()
        return {'success': True, 'task_id': task_id}
    except Exception as e:
        logger.error(f"启动东方财富行业板块导入失败: {e}")
        return {'success': False, 'message': str(e)}


def _run_import_eastmoney(task_id: str):
    """后台执行东方财富行业板块导入"""
    from app.data.db import get_db
    from app.data.task_manager import get_task_manager
    from app.data.sources.akshare_source import AkShareSource
    import time

    db = get_db()
    tm = get_task_manager()

    try:
        _safe_update_progress( current_stock_name="获取东方财富行业板块列表...")
        industry_df = AkShareSource.get_industry_list()
        if industry_df is None or industry_df.empty:
            tm.fail_task(task_id, "获取东方财富行业板块列表失败")
            return

        total = len(industry_df)
        success_count = 0
        skip_count = 0

        for i, (_, row) in enumerate(industry_df.iterrows()):
            if tm.is_cancelled(task_id):
                return

            industry_name = row['板块名称']
            industry_code = row['板块代码']  # BK开头，如 BK0437

            tm.update_task_progress(
                task_id, current_stock=industry_code,
                current_stock_name=f"导入 {industry_name}...",
                total_count=total, completed_count=i,
            )

            # 检查是否已存在
            existing = db['sector_basics'].find_one({'code': industry_code})
            if existing:
                skip_count += 1
                continue

            # 插入 sector_basics
            db['sector_basics'].update_one(
                {'code': industry_code},
                {'$set': {
                    'code': industry_code,
                    'name': industry_name,
                    'source': '东方财富',
                    'is_disable': False,
                    'update_time': datetime.now(),
                }},
                upsert=True,
            )
            success_count += 1
            time.sleep(0.2)  # 避免请求过快

        msg = f"东方财富行业板块导入完成: 新增 {success_count} 个，跳过 {skip_count} 个"
        tm.update_task_progress(
            task_id, current_stock_name=msg,
            total_count=total, completed_count=total,
        )
        tm.complete_task(task_id, msg)

    except Exception as e:
        logger.error(f"导入东方财富行业板块失败: {e}")
        tm.fail_task(task_id, str(e)[:200])


@router.post("/disable")
def update_disable_status(
    items: List[Dict[str, Any]]
):
    """批量更新禁用状态（is_disable字段）"""
    try:
        db = get_db()
        for item in items:
            code = item.get('code', '')
            category = item.get('category', '')
            disabled = item.get('disabled', False)

            if not code or not category:
                continue

            if category == 'index':
                db['index_basics'].update_one({'code': code}, {'$set': {'is_disable': disabled}})
            elif category == 'stock':
                db['stock_basics'].update_one({'stock_code': code}, {'$set': {'is_disable': disabled}})
            elif category == 'sector':
                db['sector_basics'].update_one({'code': code}, {'$set': {'is_disable': disabled}})

        return {'success': True, 'message': f'更新了 {len(items)} 项配置'}
    except Exception as e:
        logger.error(f"更新禁用状态失败: {e}")
        return {'success': False, 'message': str(e)}


@router.post("/create")
def create_item(item: Dict[str, Any]):
    """新增板块或指数"""
    try:
        db = get_db()
        from datetime import datetime as _dt

        category = item.get('category', '')
        code = item.get('code', '').strip()
        name = item.get('name', '').strip()

        if not code or not name:
            return {'success': False, 'message': '代码和名称不能为空'}

        if category == 'sector':
            existing = db['sector_basics'].find_one({'code': code})
            if existing:
                return {'success': False, 'message': f'板块 {code} 已存在'}
            db['sector_basics'].insert_one({
                'code': code,
                'block_type': 2,
                'name': name,
                'source': item.get('source', '手动新增'),
                'stock_codes': [],
                'stock_count': 0,
                'ths_code': '',
                'update_time': _dt.now(),
                'tdx_code': code,
                'is_disable': False,
            })
            return {'success': True, 'message': f'板块 {name}({code}) 新增成功'}

        elif category == 'index':
            existing = db['index_basics'].find_one({'code': code})
            if existing:
                return {'success': False, 'message': f'指数 {code} 已存在'}
            db['index_basics'].insert_one({
                'code': code,
                'name': name,
                'tdx_code': code,
                'market': 1,
                'update_time': _dt.now(),
                'pe_ttm': 0,
                'is_disable': False,
            })
            return {'success': True, 'message': f'指数 {name}({code}) 新增成功'}

        else:
            return {'success': False, 'message': f'不支持的分类: {category}'}
    except Exception as e:
        logger.error(f"新增失败: {e}")
        return {'success': False, 'message': str(e)}


# ==================== 对比数据 ====================

# 对比任务状态存储
_compare_tasks = {}
_compare_lock = __import__('threading').Lock()


def _compare_update_status(task_id, **kwargs):
    with _compare_lock:
        if task_id in _compare_tasks:
            _compare_tasks[task_id].update(kwargs)


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
        seen_codes = set()  # 用于去重

        # A股代码规则：沪市60/68开头，深市00/30开头（不含B股90）
        valid_prefixes = ('00', '30', '60', '68')

        for host, port in TDX_SERVERS:
            try:
                api.connect(host, port)
                for market in [0, 1]:  # 0=深市, 1=沪市
                    _compare_update_status(task_id, step=f'获取{"沪" if market else "深"}市数据', progress='40%')
                    count = api.get_security_count(market)
                    for start in range(0, min(count, 50000), 1000):
                        items = api.get_security_list(market, start)
                        for s in items:
                            code = s.get('code', '')
                            name = s.get('name', '')
                            # 过滤条件：6位数字、有效A股代码前缀、未重复
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
                # 用成分股集合的 frozenset 作为唯一标识
                key = (name, frozenset(stock_codes))
                local_sector_map[key] = doc.get('code', '')

        # 2. 从 pytdx 获取远程板块列表
        _compare_update_status(task_id, step='连接pytdx获取板块', progress='30%')
        import sys
        if '_vendor/pytdx' not in sys.path:
            sys.path.insert(0, '_vendor/pytdx')
        from app.data.sources.pytdx_source import PytdxSource

        # 构建本地名称到代码的映射
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
                    # 尝试从本地匹配代码
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
                new_sectors.append(sector)
        
        # 按成分股数量降序排列
        new_sectors.sort(key=lambda x: -x['stock_count'])

        # 4. 存储结果
        _compare_update_status(
            task_id,
            status='completed',
            step='完成',
            progress='100%',
            result={
                'local_count': len(local_codes),
                'remote_count': len(remote_sectors),
                'new_count': len(new_sectors),
                'new_sectors': new_sectors[:50],
            }
        )

    except Exception as e:
        logger.error(f"对比板块任务失败: {e}")
        _compare_update_status(task_id, status='failed', error=str(e))


@router.post("/compare-stocks")
def start_compare_stocks():
    """启动个股对比任务"""
    import threading
    import uuid

    task_id = str(uuid.uuid4())[:8]

    with _compare_lock:
        _compare_tasks[task_id] = {
            'task_id': task_id,
            'type': 'stock',
            'status': 'running',
            'step': '准备中',
            'progress': '0%',
            'result': None,
            'error': None,
        }

    thread = threading.Thread(target=_run_compare_stocks_task, args=(task_id,), daemon=True)
    thread.start()

    return {'success': True, 'task_id': task_id}


@router.post("/compare-sectors")
def start_compare_sectors():
    """启动板块对比任务"""
    import threading
    import uuid

    task_id = str(uuid.uuid4())[:8]

    with _compare_lock:
        _compare_tasks[task_id] = {
            'task_id': task_id,
            'type': 'sector',
            'status': 'running',
            'step': '准备中',
            'progress': '0%',
            'result': None,
            'error': None,
        }

    thread = threading.Thread(target=_run_compare_sectors_task, args=(task_id,), daemon=True)
    thread.start()

    return {'success': True, 'task_id': task_id}




@router.post("/sectors/import-excel")
async def import_sector_codes_from_excel(file: UploadFile):
    """从 Excel/CSV 导入板块代码，匹配本地缺少的板块（带 pytdx 成分股校验）"""
    try:
        db = get_db()
        
        # 读取文件内容
        content = await file.read()
        filename = file.filename or ''
        
        # 解析 Excel 或 CSV
        import pandas as pd
        import io
        
        if filename.endswith('.xlsx') or filename.endswith('.xls'):
            try:
                df = pd.read_excel(io.BytesIO(content), engine='openpyxl')
            except Exception:
                df = pd.read_excel(io.BytesIO(content), engine='xlrd')
        elif filename.endswith('.csv') or filename.endswith('.tsv'):
            df = pd.read_csv(io.BytesIO(content), encoding='utf-8', sep=None)
        else:
            # 尝试自动检测格式
            try:
                df = pd.read_csv(io.BytesIO(content), encoding='utf-8', sep=None)
            except Exception:
                return {'success': False, 'message': '不支持的文件格式，请使用 Excel、CSV 或 TSV'}
        
        # 查找 code 和 name 列
        code_col = None
        name_col = None
        for col in df.columns:
            col_lower = str(col).lower()
            if col_lower in ['code', '代码', '板块代码', 'tdx_code']:
                code_col = col
            elif col_lower in ['name', '名称', '板块名称', '板块名']:
                name_col = col
        
        if not code_col or not name_col:
            return {'success': False, 'message': f'未找到 code/name 列，当前列: {list(df.columns)}'}
        
        # 获取本地已有的板块名称
        local_names = set(
            doc['name'] for doc in db['sector_basics'].find({}, {'_id': 0, 'name': 1})
        )
        
        # 获取 pytdx 板块数据
        import sys
        if '_vendor/pytdx' not in sys.path:
            sys.path.insert(0, '_vendor/pytdx')
        from app.data.sources.pytdx_source import PytdxSource
        
        pytdx = PytdxSource()
        remote_blocks = {}
        try:
            blocks = pytdx.get_concept_blocks()
            for block in blocks:
                name = block.get('name', '')
                stock_codes = block.get('stock_codes', [])
                if name and stock_codes:
                    remote_blocks[name] = stock_codes
        except Exception as e:
            logger.warning(f"获取 pytdx 板块失败: {e}")
        
        # 匹配并导入
        imported = 0
        imported_codes = []
        skipped_no_data = 0
        skipped_exists = 0
        skipped_no_match = 0
        
        for _, row in df.iterrows():
            code = str(row[code_col]).strip()
            name = str(row[name_col]).strip()
            
            if not code or not name:
                continue
            
            # 检查本地是否已存在
            if name in local_names:
                skipped_exists += 1
                continue
            
            # 检查 pytdx 是否有该板块且有成分股
            stock_codes = remote_blocks.get(name, [])
            if not stock_codes:
                skipped_no_data += 1
                continue
            
            # 插入新板块
            db['sector_basics'].insert_one({
                'code': code,
                'tdx_code': code,
                'name': name,
                'source': 'Excel导入',
                'stock_count': len(stock_codes),
                'stock_codes': stock_codes,
                'block_type': 2,
                'is_disable': False,
                'update_time': __import__('datetime').datetime.now(),
            })
            imported += 1
            imported_codes.append(code)
        
        # 如果有新板块导入，启动后台任务同步日线数据
        if imported_codes:
            import threading
            def _sync_sector_daily():
                try:
                    import sys
                    if '_vendor/pytdx' not in sys.path:
                        sys.path.insert(0, '_vendor/pytdx')
                    from pytdx.hq import TdxHq_API
                    from app.data.sources.pytdx_source import TDX_SERVERS
                    import numpy as np
                    from datetime import datetime as _dt
                    
                    api = TdxHq_API()
                    for host, port in TDX_SERVERS:
                        try:
                            api.connect(host, port)
                            for sector_code in imported_codes:
                                # 获取板块信息
                                sector_doc = db['sector_basics'].find_one({'code': sector_code})
                                if not sector_doc:
                                    continue
                                
                                # 获取日线数据（最近250天）
                                data = api.get_index_bars(9, 1, sector_code, 0, 250)
                                if not data or len(data) == 0:
                                    logger.warning(f"[导入] 板块 {sector_doc['name']}({sector_code}) 无日线数据")
                                    continue
                                
                                # 写入 sector_daily
                                records = []
                                for bar in data:
                                    dt_str = bar['datetime']
                                    trade_date = dt_str[:10].replace('-', '')
                                    records.append({
                                        'stock_code': sector_code,
                                        'trade_date': trade_date,
                                        'open': bar['open'],
                                        'high': bar['high'],
                                        'low': bar['low'],
                                        'close': bar['close'],
                                        'vol': bar['vol'],
                                        'amount': bar['amount'],
                                        'volume': 0,
                                        'data_source': 'tdx_concept',
                                    })
                                
                                # 批量写入
                                from app.data.db import bulk_upsert_daily_data
                                bulk_upsert_daily_data(sector_code, records, 'tdx_concept', 'sector')
                                
                                # 计算技术指标
                                cursor = db['sector_daily'].find(
                                    {'stock_code': sector_code},
                                    {'_id': 0, 'trade_date': 1, 'close': 1, 'vol': 1}
                                ).sort('trade_date', 1)
                                all_data = list(cursor)
                                
                                if len(all_data) >= 5:
                                    closes = [d['close'] for d in all_data]
                                    vols = [d.get('vol', 0) for d in all_data]
                                    
                                    for i in range(len(all_data)):
                                        date = all_data[i]['trade_date']
                                        update_fields = {}
                                        
                                        # MA 均线
                                        if i >= 4:
                                            update_fields['ma5'] = round(np.mean(closes[i-4:i+1]), 2)
                                        if i >= 9:
                                            update_fields['ma10'] = round(np.mean(closes[i-9:i+1]), 2)
                                        if i >= 19:
                                            update_fields['ma20'] = round(np.mean(closes[i-19:i+1]), 2)
                                        if i >= 49:
                                            update_fields['ma50'] = round(np.mean(closes[i-49:i+1]), 2)
                                        if i >= 119:
                                            update_fields['ma120'] = round(np.mean(closes[i-119:i+1]), 2)
                                        
                                        # 成交量均线
                                        if i >= 4:
                                            update_fields['vol_ma5'] = round(np.mean(vols[i-4:i+1]), 2)
                                        if i >= 9:
                                            update_fields['vol_ma10'] = round(np.mean(vols[i-9:i+1]), 2)
                                        if i >= 19:
                                            update_fields['vol_ma20'] = round(np.mean(vols[i-19:i+1]), 2)
                                        if i >= 49:
                                            update_fields['vol_ma50'] = round(np.mean(vols[i-49:i+1]), 2)
                                        
                                        # 涨跌幅
                                        if i > 0 and closes[i-1] > 0:
                                            update_fields['chg_pct'] = round((closes[i] - closes[i-1]) / closes[i-1] * 100, 2)
                                        
                                        # 区间涨跌幅
                                        if i >= 4 and closes[i-4] > 0:
                                            update_fields['chg_5d'] = round((closes[i] - closes[i-4]) / closes[i-4] * 100, 2)
                                        if i >= 9 and closes[i-9] > 0:
                                            update_fields['chg_10d'] = round((closes[i] - closes[i-9]) / closes[i-9] * 100, 2)
                                        if i >= 19 and closes[i-19] > 0:
                                            update_fields['chg_20d'] = round((closes[i] - closes[i-19]) / closes[i-19] * 100, 2)
                                        if i >= 49 and closes[i-49] > 0:
                                            update_fields['chg_50d'] = round((closes[i] - closes[i-49]) / closes[i-49] * 100, 2)
                                        if i >= 119 and closes[i-119] > 0:
                                            update_fields['chg_120d'] = round((closes[i] - closes[i-119]) / closes[i-119] * 100, 2)
                                        if i >= 249 and closes[i-249] > 0:
                                            update_fields['chg_250d'] = round((closes[i] - closes[i-249]) / closes[i-249] * 100, 2)
                                        
                                        # is_final
                                        if i == len(all_data) - 1:
                                            update_fields['is_final'] = True
                                        
                                        if update_fields:
                                            db['sector_daily'].update_one(
                                                {'stock_code': sector_code, 'trade_date': date},
                                                {'$set': update_fields}
                                            )
                                
                                logger.info(f"[导入] 板块 {sector_doc['name']}({sector_code}) 日线同步完成，{len(data)} 条")
                            
                            api.disconnect()
                            break
                        except Exception as e:
                            logger.warning(f"[导入] pytdx 连接失败 {host}:{port}: {e}")
                            continue
                    
                    logger.info(f"[导入] 同步 {imported} 个新板块日线数据完成")
                except Exception as e:
                    logger.error(f"[导入] 同步板块日线数据失败: {e}")
            
            thread = threading.Thread(target=_sync_sector_daily, daemon=True)
            thread.start()
        
        return {
            'success': True,
            'imported': imported,
            'skipped_exists': skipped_exists,
            'skipped_no_data': skipped_no_data,
            'message': f'导入完成: 成功 {imported} 个, 已存在 {skipped_exists} 个, 无成分股 {skipped_no_data} 个' +
                       (f', 正在后台同步日线数据...' if imported > 0 else '')
        }
    except Exception as e:
        logger.error(f"导入板块代码失败: {e}")
        return {'success': False, 'message': str(e)}


@router.get("/compare-status/{task_id}")
def get_compare_status(task_id: str):
    """获取对比任务状态"""
    with _compare_lock:
        task = _compare_tasks.get(task_id)
        if not task:
            return {'success': False, 'message': '任务不存在'}
        return {'success': True, **task}


# ==================== 系统配置 ====================

@router.get("/config/deepseek-time-limit")
def get_deepseek_time_limit():
    """获取 DeepSeek 时间窗口限制配置及当前可用状态"""
    try:
        from app.server.api.deepseek_analyst import is_deepseek_available
        db = get_db()
        config = db['system_config'].find_one({'key': 'deepseek_time_limit'})
        enabled = config.get('value', True) if config else True
        available, msg = is_deepseek_available()
        return {'success': True, 'enabled': enabled, 'available': available, 'message': msg}
    except Exception as e:
        logger.error(f"获取配置失败: {e}")
        return {'success': True, 'enabled': True, 'available': False, 'message': str(e)}


@router.post("/config/deepseek-time-limit")
def set_deepseek_time_limit(enabled: bool = Query(..., description="是否启用时间窗口限制")):
    """设置 DeepSeek 时间窗口限制配置"""
    try:
        from app.server.api.deepseek_analyst import is_deepseek_available
        db = get_db()
        db['system_config'].update_one(
            {'key': 'deepseek_time_limit'},
            {'$set': {'key': 'deepseek_time_limit', 'value': enabled, 'update_time': __import__('datetime').datetime.now()}},
            upsert=True
        )
        available, msg = is_deepseek_available()
        return {'success': True, 'enabled': enabled, 'available': available, 'message': msg}
    except Exception as e:
        logger.error(f"设置配置失败: {e}")
        return {'success': False, 'message': str(e)}


# ==================== 导入数据 ====================

@router.post("/import-stocks")
def import_stocks(stocks: List[Dict[str, Any]]):
    """导入新增的个股到 stock_basics，并自动同步日线数据和技术指标"""
    try:
        db = get_db()
        from datetime import datetime as _dt

        imported_codes = []
        skipped = 0
        for stock in stocks:
            code = stock.get('stock_code', '')
            name = stock.get('stock_name', '')
            market = stock.get('market', 0)

            if not code or not name:
                continue

            # 检查是否已存在
            existing = db['stock_basics'].find_one({'stock_code': code})
            if existing:
                skipped += 1
                continue

            # 插入新股票（上市日期先设为默认值，后面会更新）
            db['stock_basics'].insert_one({
                'stock_code': code,
                'stock_name': name,
                'market': market,
                'list_date': '19900101',
                'is_st': 'ST' in name,
                'suspend': False,
                'update_time': _dt.now(),
            })
            imported_codes.append(code)

        imported = len(imported_codes)

        # 如果有新股票导入，启动后台任务同步日线数据
        if imported_codes:
            import threading
            def _sync_new_stocks():
                try:
                    import sys
                    if '_vendor/pytdx' not in sys.path:
                        sys.path.insert(0, '_vendor/pytdx')
                    from pytdx.hq import TdxHq_API
                    from app.data.sources.pytdx_source import TDX_SERVERS
                    from app.data.db import bulk_upsert_daily_data
                    import numpy as np

                    api = TdxHq_API()
                    for host, port in TDX_SERVERS:
                        try:
                            api.connect(host, port)
                            for code in imported_codes:
                                # 获取市场信息
                                stock_doc = db['stock_basics'].find_one({'stock_code': code})
                                market = stock_doc.get('market', 0) if stock_doc else 0

                                # 获取日线数据
                                data = api.get_security_bars(9, market, code, 0, 500)
                                if data and len(data) > 0:
                                    records = []
                                    for bar in data:
                                        dt_str = bar['datetime']
                                        trade_date = dt_str[:10].replace('-', '')
                                        records.append({
                                            'stock_code': code,
                                            'trade_date': trade_date,
                                            'open': bar['open'],
                                            'high': bar['high'],
                                            'low': bar['low'],
                                            'close': bar['close'],
                                            'volume': bar['vol'],
                                            'amount': bar['amount'],
                                            'data_source': 'pytdx',
                                        })

                                    bulk_upsert_daily_data(code, records, 'pytdx', 'stock')

                                    # 更新上市日期
                                    first_date = data[0]['datetime'][:10].replace('-', '')
                                    db['stock_basics'].update_one(
                                        {'stock_code': code},
                                        {'$set': {'list_date': first_date}}
                                    )

                                    # 计算技术指标
                                    cursor = db['stock_daily'].find(
                                        {'stock_code': code},
                                        {'_id': 0, 'trade_date': 1, 'close': 1, 'volume': 1}
                                    ).sort('trade_date', 1)
                                    all_data = list(cursor)

                                    if len(all_data) >= 5:
                                        closes = [d['close'] for d in all_data]
                                        vols = [d.get('volume', 0) or d.get('vol', 0) for d in all_data]

                                        for i in range(len(all_data)):
                                            date = all_data[i]['trade_date']
                                            update_fields = {}

                                            # MA 均线
                                            if i >= 4:
                                                update_fields['ma5'] = round(np.mean(closes[i-4:i+1]), 2)
                                            if i >= 9:
                                                update_fields['ma10'] = round(np.mean(closes[i-9:i+1]), 2)
                                            if i >= 19:
                                                update_fields['ma20'] = round(np.mean(closes[i-19:i+1]), 2)
                                            if i >= 49:
                                                update_fields['ma50'] = round(np.mean(closes[i-49:i+1]), 2)
                                            if i >= 119:
                                                update_fields['ma120'] = round(np.mean(closes[i-119:i+1]), 2)

                                            # 成交量均线
                                            if i >= 4:
                                                update_fields['vol_ma5'] = round(np.mean(vols[i-4:i+1]), 2)
                                            if i >= 9:
                                                update_fields['vol_ma10'] = round(np.mean(vols[i-9:i+1]), 2)
                                            if i >= 19:
                                                update_fields['vol_ma20'] = round(np.mean(vols[i-19:i+1]), 2)
                                            if i >= 49:
                                                update_fields['vol_ma50'] = round(np.mean(vols[i-49:i+1]), 2)

                                            # 涨跌幅
                                            if i > 0 and closes[i-1] > 0:
                                                update_fields['chg_pct'] = round((closes[i] - closes[i-1]) / closes[i-1] * 100, 2)

                                            # 区间涨跌幅
                                            if i >= 4 and closes[i-4] > 0:
                                                update_fields['chg_5d'] = round((closes[i] - closes[i-4]) / closes[i-4] * 100, 2)
                                            if i >= 9 and closes[i-9] > 0:
                                                update_fields['chg_10d'] = round((closes[i] - closes[i-9]) / closes[i-9] * 100, 2)
                                            if i >= 19 and closes[i-19] > 0:
                                                update_fields['chg_20d'] = round((closes[i] - closes[i-19]) / closes[i-19] * 100, 2)
                                            if i >= 49 and closes[i-49] > 0:
                                                update_fields['chg_50d'] = round((closes[i] - closes[i-49]) / closes[i-49] * 100, 2)
                                            if i >= 119 and closes[i-119] > 0:
                                                update_fields['chg_120d'] = round((closes[i] - closes[i-119]) / closes[i-119] * 100, 2)
                                            if i >= 249 and closes[i-249] > 0:
                                                update_fields['chg_250d'] = round((closes[i] - closes[i-249]) / closes[i-249] * 100, 2)

                                            # is_final
                                            if i == len(all_data) - 1:
                                                update_fields['is_final'] = True

                                            if update_fields:
                                                db['stock_daily'].update_one(
                                                    {'stock_code': code, 'trade_date': date},
                                                    {'$set': update_fields}
                                                )

                                    logger.info(f"[导入] {code} 同步完成，{len(data)} 条日线数据")
                                else:
                                    logger.warning(f"[导入] {code} 未获取到日线数据")

                            api.disconnect()
                            break
                        except Exception as e:
                            logger.warning(f"[导入] pytdx连接失败 {host}:{port}: {e}")
                            continue

                    logger.info(f"[导入] 同步 {imported} 只新股票日线数据完成")
                except Exception as e:
                    logger.error(f"[导入] 同步新股票日线数据失败: {e}")

            thread = threading.Thread(target=_sync_new_stocks, daemon=True)
            thread.start()

        return {
            'success': True,
            'imported': imported,
            'skipped': skipped,
            'message': f'成功导入 {imported} 只股票，跳过 {skipped} 只已存在' + 
                       (f'，正在后台同步日线数据...' if imported > 0 else '')
        }
    except Exception as e:
        logger.error(f"导入个股失败: {e}")
        return {'success': False, 'message': str(e)}


@router.post("/import-sectors")
def import_sectors(sectors: List[Dict[str, Any]]):
    """导入新增的板块到 sector_basics"""
    try:
        db = get_db()
        from datetime import datetime as _dt

        imported = 0
        skipped = 0
        for sector in sectors:
            name = sector.get('name', '')
            stock_codes = sector.get('stock_codes', [])

            if not name:
                continue

            # 检查是否已存在（按名称匹配）
            existing = db['sector_basics'].find_one({'name': name})
            if existing:
                skipped += 1
                continue

            # 生成板块代码
            code = f"PY{abs(hash(name)) % 1000000:06d}"

            # 插入新板块
            db['sector_basics'].insert_one({
                'code': code,
                'tdx_code': code,
                'name': name,
                'source': 'pytdx对比导入',
                'stock_count': len(stock_codes),
                'stock_codes': stock_codes,
                'block_type': 2,
                'is_disable': False,
                'update_time': _dt.now(),
            })
            imported += 1

        return {
            'success': True,
            'imported': imported,
            'skipped': skipped,
            'message': f'成功导入 {imported} 个板块，跳过 {skipped} 个已存在'
        }
    except Exception as e:
        logger.error(f"导入板块失败: {e}")
        return {'success': False, 'message': str(e)}


@router.post("/clear-sync-tasks")
def clear_sync_tasks():
    """清除 sync_tasks 表中的所有任务数据"""
    try:
        from app.data.db import get_db
        db = get_db()
        
        result = db['sync_tasks'].delete_many({})
        deleted_count = result.deleted_count
        
        return {
            'success': True,
            'message': f'已清除 {deleted_count} 条任务记录',
            'deleted_count': deleted_count
        }
    except Exception as e:
        logger.error(f"清除 sync_tasks 失败: {e}")
        raise HTTPException(status_code=500, detail=f"清除失败: {str(e)[:200]}")
