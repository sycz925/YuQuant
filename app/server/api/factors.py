"""
因子 API 路由层

路由函数只负责：接收请求 → 调用 FactorService → 返回结果。
所有业务逻辑、数据库访问、后台任务调度均在 FactorService 中。
"""
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, UploadFile
from pydantic import BaseModel

from app.server.services.factor_service import get_factor_service

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
        svc = get_factor_service()
        result = svc.get_cr5_data(start_date, end_date, include_index, period)
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
        return get_factor_service().get_indices_list(page, page_size or 50, keyword, filter_mode)
    except Exception as e:
        logger.error(f"获取指数列表失败: {e}")
        raise HTTPException(status_code=500, detail="获取指数列表失败")


@router.get("/indices/search")
def search_indices(keyword: str = Query(..., description="搜索关键词（代码或名称）")):
    """搜索指数（先本地数据库，再查通达信 TDX）"""
    try:
        return get_factor_service().search_indices(keyword)
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
        tm = get_task_manager()
        task_id = tm.create_task(100)

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


def _run_precompute_base(task_id: str):
    """后台执行 base_data_daily + market_daily 预计算"""
    from app.data.db import get_db
    from app.data.task_manager import get_task_manager
    from app.server.api.market_review import _compute_realtime, generate_market_overview, analyze_new_high_blocks
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo

    tm = get_task_manager()
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
        tm.update_task_progress(task_id, current_stock_name="计算 CR5/CR10/MA/NH-NL...")

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

        # upsert 到 base_data_daily
        db['base_data_daily'].update_one(
            {'date': latest},
            {'$set': merged_row},
            upsert=True
        )

        tm.update_task_progress(task_id, current_stock=50, current_stock_name="base_data_daily 完成")

        # ---- Step 2: market_daily ----
        tm.update_task_progress(task_id, current_stock=50, current_stock_name="计算 overview/signals/new_high...")

        overview = generate_market_overview(latest)
        overview_clean = {k: v for k, v in overview.items() if k not in ('conclusion', 'style')}
        tm.update_task_progress(task_id, current_stock=60, current_stock_name="计算新高板块...")

        nh_result = analyze_new_high_blocks(latest)
        tm.update_task_progress(task_id, current_stock=85, current_stock_name="计算低位潜力板块...")

        from app.server.api.market_review import analyze_low_position_sectors
        lps_result = analyze_low_position_sectors(latest)
        tm.update_task_progress(task_id, current_stock=90, current_stock_name="落库 market_daily...")

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
                    'compute_time': _dt.now().isoformat(),
                    'is_final': is_market_closed,
                },
                '$unset': {
                    'signals': '',
                }
            },
            upsert=True,
        )

        tm.update_task_progress(task_id, current_stock=100, current_stock_name="预计算完成")
        tm.complete_task(task_id, f"基础数据预计算完成 ({latest})")

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
        task_id = tm.create_task(100)

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


def _run_sync_pe(task_id: str, token: str):
    """后台执行PE同步"""
    import time, requests as _req
    from hashlib import md5 as _md5
    from bs4 import BeautifulSoup
    from app.data.db import get_db
    from app.data.task_manager import get_task_manager

    db = get_db()
    tm = get_task_manager()

    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
        session = _req.Session()
        session.headers.update(headers)

        tm.update_task_progress(task_id, current_stock_name="获取CSRF...")
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

        index_cursor = db['index_basics'].find({}, {'_id': 0, 'code': 1, 'name': 1})
        enabled_indices = {c['code']: c['name'] for c in index_cursor}
        for ex in db['exclusions'].find({'category': 'index', 'exclude_sync': {'$ne': True}}, {'_id': 0, 'code': 1, 'name': 1}):
            if ex['code'] not in enabled_indices:
                enabled_indices[ex['code']] = ex.get('name', ex['code'])

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
        tm.complete_task(task_id, f"PE同步完成，{success_count}/{total}个指数")

    except Exception as e:
        logger.error(f"PE同步失败: {e}")
        tm.fail_task(task_id, str(e)[:200])


# ==================== RPS ====================

@router.post("/rps/calculate", response_model=Dict[str, Any])
def calculate_and_save_rps(
    start_date: Optional[str] = Query(None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD"),
    target_date: Optional[str] = Query(None, description="只计算指定日期的 RPS（增量模式）"),
    target: str = Query('stock', description="'stock' 个股 | 'sector' 板块 | 'all' 全部"),
    max_workers: Optional[int] = Query(16, description="最大线程数"),
    min_days: Optional[int] = Query(None, description="最小上市天数（可选）"),
):
    """计算并保存 RPS 指标（后台任务）"""
    try:
        return get_factor_service().calculate_rps(
            start_date, end_date, target_date, target, max_workers or 16, min_days,
        )
    except Exception as e:
        logger.error(f"启动 RPS 计算任务失败: {e}")
        return {"success": False, "message": f"启动任务失败: {str(e)}"}


@router.post("/tasks/clear", response_model=Dict[str, Any])
def clear_all_tasks():
    """清除所有后台任务状态（用于重置脏数据）"""
    try:
        return get_factor_service().clear_all_tasks()
    except Exception as e:
        logger.error(f"清除任务状态失败: {e}")
        return {"success": False, "message": str(e)}


@router.delete("/rps", response_model=Dict[str, Any])
def delete_rps_data(
    target: str = Query('all', description="'stock' 只清个股RPS | 'sector' 只清板块RPS | 'all' 全部"),
):
    """清除 RPS 数据（不删除日线，只清 rps_* 字段）"""
    try:
        return get_factor_service().delete_rps_data(target)
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
        result = get_factor_service().get_stock_rps(code, start_date, end_date, period)
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
        result = get_factor_service().get_rps_by_date(trade_date, min_rps)
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
        return get_factor_service().sync_sectors(max_workers or 16, min_days)
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
        return get_factor_service().get_sector_list(
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
             'rps_10': 1, 'rps_20': 1, 'rps_50': 1}
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
        return get_factor_service().import_sector_codes(content, filename)
    except Exception as e:
        logger.error(f"导入板块代码失败: {e}")
        return {"success": False, "message": str(e)}
