"""
因子 API 路由层

路由函数只负责：接收请求 → 调用工厂/服务 → 返回结果。
所有业务逻辑、数据库访问、后台任务调度均在服务层中。
"""
import logging
import threading
import uuid
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, UploadFile
from pydantic import BaseModel

from app.server.factories import get_index_factory, get_stock_factory, get_sector_factory, get_market_aggregator
from app.server.repositories import (
    get_stock_repo, get_sector_repo, get_index_repo, get_task_repo, get_system_config_repo,
)
from app.server.services.factors_service import (
    _run_compare_stocks_task,
    _run_compare_sectors_task,
    repair_stock_names,
)

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
    """获取 CR5% 因子数据（从 base_data_daily 读取）"""
    try:
        factory = get_index_factory()
        return factory.get_cr5_data(start_date, end_date, include_index, period)
    except Exception as e:
        logger.error(f"获取CR5因子失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取CR5因子失败: {str(e)}")


# ==================== 指数列表 ====================

@router.get("/indices")
def get_indices_list(
    filter_mode: Optional[str] = Query(None, description="筛选模式: enabled/disabled"),
    keyword: Optional[str] = Query(None, description="搜索关键词"),
):
    """获取指数列表"""
    try:
        factory = get_index_factory()
        return factory.get_indices_list(filter_mode=filter_mode, keyword=keyword)
    except Exception as e:
        logger.error(f"获取指数列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取指数列表失败: {str(e)}")


@router.get("/indices/search")
def search_indices(keyword: str = Query(..., description="搜索关键词（代码或名称）")):
    """搜索指数"""
    try:
        factory = get_index_factory()
        return factory.search_indices(keyword)
    except Exception as e:
        logger.error(f"搜索指数失败: {e}")
        raise HTTPException(status_code=500, detail=f"搜索指数失败: {str(e)}")


# ==================== 任务管理 ====================

@router.post("/tasks/clear", response_model=Dict[str, Any])
def clear_all_tasks():
    """清除所有后台任务状态（用于重置脏数据）"""
    try:
        aggregator = get_market_aggregator()
        return aggregator.clear_all_tasks()
    except Exception as e:
        logger.error(f"清除任务状态失败: {e}")
        return {"success": False, "message": str(e)}


# ==================== RPS ====================

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

@router.get("/sectors", response_model=Dict[str, Any])
def get_sector_list(
    page: Optional[int] = Query(None, ge=1, description="页码"),
    page_size: Optional[int] = Query(50, ge=1, le=500, description="每页数量"),
    keyword: Optional[str] = Query(None, description="搜索关键词（代码或名称）"),
    filter_mode: Optional[str] = Query(None, description="筛选模式: enabled/disabled"),
    limit: Optional[int] = Query(None, description="返回数量（兼容旧接口）"),
    min_stock_count: Optional[int] = Query(0, description="最少成分股数（0=不过滤）"),
    sort_by: Optional[str] = Query(None, description="排序字段"),
    sort_order: Optional[str] = Query("desc", description="排序方向"),
    rps_red: Optional[str] = Query(None, description="RPS红筛选: one/two/three"),
):
    """获取板块列表（支持分页、搜索、状态筛选和排序，含最新行情数据）"""
    try:
        factory = get_sector_factory()
        return factory.get_sector_list(
            page, page_size or 50, keyword, filter_mode, limit, min_stock_count or 0,
            sort_by, sort_order, rps_red,
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
    vol_ma5: Optional[float] = None
    vol_ma10: Optional[float] = None
    vol_ma20: Optional[float] = None
    vol_ma50: Optional[float] = None
    rps_10: Optional[float] = None
    rps_20: Optional[float] = None
    rps_50: Optional[float] = None
    rps_120: Optional[float] = None
    rps_250: Optional[float] = None


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
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
        if not start_date:
            start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")

        projection = {
            '_id': 0, 'trade_date': 1, 'open': 1, 'high': 1, 'low': 1, 'close': 1,
            'vol': 1, 'amount': 1, 'change_pct': 1,
            'vol_ma5': 1, 'vol_ma10': 1, 'vol_ma20': 1, 'vol_ma50': 1,
            'rps_10': 1, 'rps_20': 1, 'rps_50': 1, 'rps_120': 1, 'rps_250': 1,
        }
        items = get_sector_repo().get_daily_bars(code, start_date, end_date, limit, projection)
        if not items:
            raise HTTPException(status_code=404, detail=f"板块 {code} 暂无数据")

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


@router.get("/sectors/{code}/stocks")
def get_sector_stocks(
    code: str,
    rps_red: Optional[str] = Query(None, description="RPS红筛选: one/two/three"),
):
    """获取板块成分股列表（含当日行情+RPS）"""
    try:
        sector_repo = get_sector_repo()
        stock_repo = get_stock_repo()

        sector_doc = sector_repo.get_by_code(code)
        if not sector_doc:
            raise HTTPException(status_code=404, detail="未找到该板块")

        stock_codes = sector_doc.get('stock_codes', [])
        if not stock_codes:
            return {
                'success': True,
                'sector_name': sector_doc.get('name', code),
                'stock_count': 0,
                'trade_date': None,
                'stocks': [],
            }

        # 获取最新交易日
        trade_date = stock_repo.get_latest_trade_date(stock_codes)
        if not trade_date:
            return {
                'success': True,
                'sector_name': sector_doc.get('name', code),
                'stock_count': len(stock_codes),
                'trade_date': None,
                'stocks': [],
            }

        # 批量查成分股行情
        quotes = stock_repo.get_daily_quotes(stock_codes, trade_date, {
            '_id': 0,
            'stock_code': 1,
            'close': 1,
            'chg_pct': 1,
            'chg_5d': 1,
            'chg_10d': 1,
            'chg_20d': 1,
            'chg_50d': 1,
            'chg_120d': 1,
            'rps_10': 1,
            'rps_50': 1,
            'rps_120': 1,
        })

        # 查股票名称
        basics = stock_repo.get_stock_names(stock_codes)

        stocks = []
        for doc in quotes:
            doc['name'] = basics.get(doc['stock_code'], doc['stock_code'])
            doc['change_pct'] = doc.pop('chg_pct')
            stocks.append(doc)

        # 按名称排序
        stocks.sort(key=lambda x: x.get('name', ''))

        # RPS红筛选
        if rps_red in ('one', 'two', 'three'):
            rps_threshold = 87
            filtered = []
            for doc in stocks:
                rps_values = [v for v in (doc.get('rps_10'), doc.get('rps_50'), doc.get('rps_120')) if v is not None]
                red_count = sum(1 for v in rps_values if v > rps_threshold)
                if rps_red == 'one' and red_count >= 1:
                    filtered.append(doc)
                elif rps_red == 'two' and red_count >= 2:
                    filtered.append(doc)
                elif rps_red == 'three' and red_count >= 3:
                    filtered.append(doc)
            stocks = filtered

        return {
            'success': True,
            'sector_name': sector_doc.get('name', code),
            'stock_count': len(stock_codes),
            'trade_date': trade_date,
            'stocks': stocks,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取板块成分股失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)[:200]}")


@router.post("/disable")
def update_disable_status(
    items: List[Dict[str, Any]]
):
    """批量更新禁用状态（is_disable字段）"""
    try:
        for item in items:
            code = item.get('code', '')
            category = item.get('category', '')
            disabled = item.get('disabled', False)

            if not code or not category:
                continue

            if category == 'index':
                get_index_repo().update_disable_status(code, disabled)
            elif category == 'sector':
                get_sector_repo().update_disable_status(code, disabled)
            elif category == 'stock':
                get_stock_repo().update_disable_status(code, disabled)
            else:
                continue

        return {'success': True, 'message': f'已更新 {len(items)} 个条目'}
    except Exception as e:
        logger.error(f"更新禁用状态失败: {e}")
        return {'success': False, 'message': str(e)}


@router.post("/create")
def create_item(item: Dict[str, Any]):
    """创建新条目（指数/板块/股票）"""
    try:
        code = item.get('code', '')
        name = item.get('name', '')
        category = item.get('category', '')
        tdx_code = item.get('tdx_code', '')

        if not code or not name or not category:
            raise HTTPException(status_code=400, detail="缺少必要参数")

        if category == 'index':
            repo = get_index_repo()
            key = {'code': code}
            doc = {'code': code, 'name': name, 'tdx_code': tdx_code or code, 'is_disable': False}
        elif category == 'sector':
            repo = get_sector_repo()
            key = {'code': code}
            doc = {'code': code, 'name': name, 'tdx_code': tdx_code or code, 'stock_codes': [], 'is_disable': False}
        elif category == 'stock':
            repo = get_stock_repo()
            key = {'stock_code': code}
            doc = {'stock_code': code, 'stock_name': name, 'is_disable': False}
        else:
            raise HTTPException(status_code=400, detail=f"未知类别: {category}")

        if repo.find_one(key):
            return {'success': False, 'message': f'{category} {code} 已存在'}

        repo.insert_one(doc)
        return {'success': True, 'message': f'已创建 {category} {code}'}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建条目失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建失败: {str(e)}")


# ==================== 对比任务 ====================

@router.post("/compare-stocks")
def start_compare_stocks():
    """启动次新股对比任务"""
    task_id = str(uuid.uuid4())
    steps = [{'key': 'compare_stocks', 'name': '次新股对比', 'total_count': 1, 'completed_count': 0}]
    get_task_repo().create_task(task_id, steps, name='次新股对比')

    thread = threading.Thread(target=_run_compare_stocks_task, args=(task_id,), daemon=True)
    thread.start()

    return {'success': True, 'task_id': task_id}


@router.post("/compare-sectors")
def start_compare_sectors():
    """启动板块对比任务"""
    task_id = str(uuid.uuid4())
    steps = [{'key': 'compare_sectors', 'name': '板块对比', 'total_count': 1, 'completed_count': 0}]
    get_task_repo().create_task(task_id, steps, name='板块对比')

    thread = threading.Thread(target=_run_compare_sectors_task, args=(task_id,), daemon=True)
    thread.start()

    return {'success': True, 'task_id': task_id}


def _parse_concept_txt(content: bytes) -> List[Dict]:
    """解析概念板块 txt（UTF-8，分号分隔：板块代码;板块名称;成分股代码;成分股名称），按板块聚合成分股"""
    text = content.decode('utf-8-sig', errors='ignore')
    sectors = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(';')
        if len(parts) < 3:
            continue
        code = parts[0].strip()
        name = parts[1].strip()
        stock_code = parts[2].strip()
        if not code or not name or not stock_code:
            continue
        sectors.setdefault((code, name), []).append(stock_code)
    return [{'code': c, 'name': n, 'stock_codes': codes} for (c, n), codes in sectors.items()]


@router.post("/sectors/import-excel")
async def import_sector_codes_from_excel(file: UploadFile, preview: bool = Query(False)):
    """导入板块（preview=True 只预览不落库）。

    支持两种格式：
    - .txt：板块代码;板块名称;成分股代码;成分股名称（成分股来自文件）
    - .xlsx/.xls/.csv：code + name 两列（成分股从 pytdx 拿）

    本地不存在的 code，导入时会先验证能拉到板块日线，能拉到才落库。
    """
    try:
        sector_repo = get_sector_repo()
        content = await file.read()
        filename = file.filename or ''

        import pandas as pd
        import io

        # ---- 解析：得到统一板块列表 [{code, name, stock_codes}] ----
        sectors = []
        if filename.endswith('.txt'):
            sectors = _parse_concept_txt(content)
        else:
            # Excel/CSV：解析 code + name 两列，成分股从 pytdx 拿
            df = None
            if filename.endswith('.xlsx'):
                try:
                    df = pd.read_excel(io.BytesIO(content), engine='openpyxl')
                except Exception:
                    df = None
            elif filename.endswith('.xls'):
                try:
                    df = pd.read_excel(io.BytesIO(content), engine='xlrd')
                except Exception:
                    df = None
                if df is None:
                    for enc in ('gbk', 'gb18030', 'utf-8'):
                        try:
                            df = pd.read_csv(io.BytesIO(content), sep='\t', encoding=enc)
                            break
                        except Exception:
                            df = None
            else:
                for enc in ('utf-8', 'gbk', 'gb18030'):
                    try:
                        df = pd.read_csv(io.BytesIO(content), sep=None, engine='python', encoding=enc)
                        break
                    except Exception:
                        df = None

            if df is None:
                return {'success': False, 'message': '无法解析文件，请使用 Excel(.xlsx)、CSV 或通达信导出的 .xls'}

            code_col = name_col = None
            for col in df.columns:
                col_lower = str(col).strip().lower()
                if col_lower in ['code', '代码', '板块代码', 'tdx_code']:
                    code_col = col
                elif col_lower in ['name', '名称', '板块名称', '板块名']:
                    name_col = col
            if not code_col or not name_col:
                return {'success': False, 'message': f'未找到 code/name 列，当前列: {list(df.columns)}'}

            # pytdx 成分股（name -> stock_codes）
            import sys
            if '_vendor/pytdx' not in sys.path:
                sys.path.insert(0, '_vendor/pytdx')
            from app.data.sources.pytdx_source import PytdxSource
            remote_blocks = {}
            try:
                blocks = PytdxSource().get_concept_blocks()
                for block in blocks:
                    nm = block.get('name', '')
                    sc = block.get('stock_codes', [])
                    if nm and sc:
                        remote_blocks[nm] = sc
            except Exception as e:
                logger.warning(f"获取 pytdx 板块失败: {e}")

            for _, row in df.iterrows():
                code = str(row[code_col]).strip()
                name = str(row[name_col]).strip()
                if code.startswith('="') and code.endswith('"'):
                    code = code[2:-1]
                if not code or not name:
                    continue
                sectors.append({'code': code, 'name': name, 'stock_codes': remote_blocks.get(name, [])})

        if not sectors:
            return {'success': False, 'message': '文件无有效板块数据'}

        # ---- 对比：按 code 判重 ----
        local_codes = {d['code'] for d in sector_repo.get_all_with_stocks() if d.get('code')}

        new_sectors = []
        skipped = []
        invalid = []
        no_data = []

        for s in sectors:
            code = s['code']
            name = s['name']
            if not (len(code) == 6 and code.isdigit()):
                invalid.append({'code': code, 'name': name})
                continue
            if code in local_codes:
                skipped.append({'code': code, 'name': name})
                continue
            if not s['stock_codes']:
                no_data.append({'code': code, 'name': name})
                continue
            new_sectors.append({
                'code': code,
                'name': name,
                'stock_count': len(s['stock_codes']),
                'all_stock_codes': s['stock_codes'],
            })

        # ---- 预览 ----
        if preview:
            return {
                'success': True,
                'preview': True,
                'total': len(sectors),
                'new_count': len(new_sectors),
                'skipped_count': len(skipped),
                'no_data_count': len(no_data),
                'invalid_count': len(invalid),
                'new_sectors': new_sectors,
                'skipped': skipped,
                'no_data': no_data,
                'invalid': invalid,
            }

        # ---- 导入：后台线程逐个验证拉日线，能拉到才存 ----
        if not new_sectors:
            return {'success': True, 'imported': 0, 'skipped': len(skipped),
                    'message': f'无新增板块（重复 {len(skipped)} 个）'}

        def _import_with_verify():
            import sys
            if '_vendor/pytdx' not in sys.path:
                sys.path.insert(0, '_vendor/pytdx')
            from app.data.sources.pytdx_source import PytdxSource
            from app.data.db import bulk_upsert_daily_data

            imported = 0
            failed_codes = []
            for s in new_sectors:
                code = s['code']
                df = PytdxSource.get_tdx_index_daily(code, market=1, start_date='20200101', max_bars=250)
                if df is None or df.empty:
                    logger.warning(f"[导入] 板块 {s['name']}({code}) 无法通过 pytdx 拉取日线，跳过")
                    failed_codes.append(code)
                    continue

                sector_repo.insert_one({
                    'code': code,
                    'tdx_code': code,
                    'name': s['name'],
                    'source': '概念板块导入',
                    'stock_count': s['stock_count'],
                    'stock_codes': s['all_stock_codes'],
                    'block_type': 2,
                    'is_disable': False,
                    'update_time': __import__('datetime').datetime.now(),
                })

                records = []
                for _, bar in df.iterrows():
                    records.append({
                        'stock_code': code,
                        'trade_date': bar['trade_date'],
                        'open': bar['open'],
                        'high': bar['high'],
                        'low': bar['low'],
                        'close': bar['close'],
                        'vol': bar['vol'],
                        'amount': bar['amount'],
                        'data_source': 'tdx_concept',
                    })
                bulk_upsert_daily_data(code, records, 'tdx_concept', 'sector')
                imported += 1

            # 统一计算板块衍生字段（均线/涨跌幅等）
            if imported > 0:
                try:
                    from app.data.manager import get_data_manager
                    get_data_manager().calculate_all_derived_fields(target='sector')
                except Exception as e:
                    logger.warning(f"[导入] 计算板块衍生字段失败: {e}")

            logger.info(
                f"[导入] 板块导入完成：成功 {imported}/{len(new_sectors)} 个" +
                (f"，失败 {len(failed_codes)} 个: {failed_codes}" if failed_codes else '')
            )

        thread = threading.Thread(target=_import_with_verify, daemon=True)
        thread.start()

        return {
            'success': True,
            'imported': 0,
            'pending': len(new_sectors),
            'skipped': len(skipped),
            'message': f'已启动导入，后台验证 {len(new_sectors)} 个板块日线并导入中...',
        }
    except Exception as e:
        logger.error(f"导入板块失败: {e}")
        return {'success': False, 'message': str(e)}


@router.get("/compare-status/{task_id}")
def get_compare_status(task_id: str):
    """获取对比任务状态（从 MongoDB 任务记录读取）"""
    task = get_task_repo().get_by_task_id(task_id)
    if not task:
        return {'success': False, 'message': '任务不存在'}
    return {
        'success': True,
        'status': task.get('status', 'idle'),
        'step': task.get('current_stock_name', ''),
        'progress': '100%' if task.get('status') == 'completed' else '',
        'result': task.get('result'),
        'error': task.get('message') or task.get('error', ''),
    }


# ==================== 系统配置 ====================

@router.get("/config/deepseek-time-limit")
def get_deepseek_time_limit():
    """获取 DeepSeek 时间窗口限制配置及当前可用状态"""
    try:
        from app.server.api.deepseek_analyst import is_deepseek_available
        enabled = get_system_config_repo().get_config('deepseek_time_limit', True)
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
        get_system_config_repo().set_config('deepseek_time_limit', enabled)
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
        from datetime import datetime as _dt
        stock_repo = get_stock_repo()

        imported_codes = []
        skipped = 0
        for stock in stocks:
            code = stock.get('stock_code', '')
            name = stock.get('stock_name', '')
            market = stock.get('market', 0)

            if not code or not name:
                continue

            if stock_repo.get_by_code(code):
                skipped += 1
                continue

            stock_repo.insert_one({
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

        if imported_codes:
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
                                market = 0 if code.startswith(('00', '30')) else 1
                                data = api.get_security_bars(9, market, code, 0, 300)
                                if not data or len(data) == 0:
                                    continue
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
                                        'vol': bar['vol'],
                                        'amount': bar['amount'],
                                        'volume': 0,
                                        'data_source': 'pytdx',
                                    })
                                bulk_upsert_daily_data(code, records, 'pytdx', 'stock')
                                logger.info(f"[导入] 股票 {code} 日线同步完成，{len(data)} 条")
                            api.disconnect()
                            break
                        except Exception as e:
                            logger.warning(f"[导入] pytdx 连接失败: {e}")
                            continue
                    
                    logger.info(f"[导入] 同步 {imported} 只新股票日线数据完成")
                except Exception as e:
                    logger.error(f"[导入] 同步股票日线数据失败: {e}")
            
            thread = threading.Thread(target=_sync_new_stocks, daemon=True)
            thread.start()

        return {
            'success': True,
            'imported': imported,
            'skipped': skipped,
            'message': f'导入完成: 成功 {imported} 只, 已存在 {skipped} 只' +
                       (f', 正在后台同步日线数据...' if imported > 0 else '')
        }
    except Exception as e:
        logger.error(f"导入股票失败: {e}")
        return {'success': False, 'message': str(e)}


@router.post("/import-sectors")
def import_sectors(sectors: List[Dict[str, Any]]):
    """导入或更新板块：新增板块插入 sector_basics，已存在板块同步远程最新成分股"""
    try:
        from datetime import datetime as _dt
        sector_repo = get_sector_repo()

        imported_codes = []
        updated_codes = []
        skipped = 0
        for sector in sectors:
            code = sector.get('code', '')
            name = sector.get('name', '')
            stock_codes = sector.get('all_stock_codes') or sector.get('stock_codes', [])

            if not code or not name:
                continue

            existing = sector_repo.get_by_code(code)
            if existing:
                old_codes = existing.get('stock_codes', [])
                if set(old_codes) != set(stock_codes):
                    sector_repo.update_one(
                        {'code': code},
                        {'$set': {
                            'stock_codes': stock_codes,
                            'stock_count': len(stock_codes),
                            'update_time': _dt.now(),
                        }}
                    )
                    updated_codes.append(code)
                else:
                    skipped += 1
                continue

            sector_repo.insert_one({
                'code': code,
                'tdx_code': code,
                'name': name,
                'stock_codes': stock_codes,
                'stock_count': len(stock_codes),
                'source': '手工导入',
                'block_type': 2,
                'is_disable': False,
                'update_time': _dt.now(),
            })
            imported_codes.append(code)

        return {
            'success': True,
            'imported': len(imported_codes),
            'updated': len(updated_codes),
            'skipped': skipped,
            'message': f'导入完成: 新增 {len(imported_codes)} 个, 更新 {len(updated_codes)} 个, 未变 {skipped} 个'
        }
    except Exception as e:
        logger.error(f"导入板块失败: {e}")
        return {'success': False, 'message': str(e)}


@router.post("/repair-stock-names")
def repair_stock_names_api():
    """一键修复股票名称（任务模式，后台执行 baostock 查询 + 批量修复）"""
    import uuid
    task_id = str(uuid.uuid4())
    steps = [{'key': 'repair', 'name': '修复股票名称', 'total_count': 1, 'completed_count': 0}]
    get_task_repo().create_task(task_id, steps, name='名称修复')

    def _run():
        task_repo = get_task_repo()
        try:
            task_repo.update_task_progress(task_id, current_stock_name='连接 baostock 并查询股票列表...')
            result = repair_stock_names()
            task_repo.update_task_progress(task_id, result=result)
            task_repo.complete_task(
                task_id,
                f"名称修复完成：修复 {result['fixed']} 个，禁用退市 {result['disabled']} 个"
            )
        except Exception as e:
            logger.error(f"名称修复失败: {e}")
            task_repo.fail_task(task_id, str(e)[:200])

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return {'success': True, 'task_id': task_id, 'message': '名称修复已启动'}