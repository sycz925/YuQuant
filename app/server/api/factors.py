"""
因子API
"""
import logging
import threading
import pandas as pd
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query, UploadFile
from datetime import datetime, timedelta, date

from app.engine.factor_engine import FactorEngine
from app.engine.rps_calculator import (
    calculate_rps, calculate_rps_incremental,
    save_rps_to_database, load_all_daily_data_for_rps
)
from app.data.manager import get_data_manager
from app.data.task_manager import get_task_manager, TaskStatus
from app.data.db import get_db, get_collection, COLLECTION_MAP
from app.server.models import CR5FactorResponse, CR5FactorData, SyncResponse
from app.server.api.exclusions import get_excluded_set
from app.server.api.constants import INDEX_CONFIG_SEED, TDX_INDEX_NAME_MAP

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/factors", tags=["factors"])

_factor_engine: Optional[FactorEngine] = None
_engine_lock = threading.Lock()


def get_factor_engine():
    """获取FactorEngine单例（线程安全）"""
    global _factor_engine
    if _factor_engine is None:
        with _engine_lock:
            if _factor_engine is None:
                dm = get_data_manager()
                _factor_engine = FactorEngine(dm)
    return _factor_engine


def get_index_config_from_db() -> List[Dict[str, Any]]:
    """从数据库 index_basics 集合读取指数配置列表"""
    try:
        db = get_db()
        cursor = db['index_basics'].find({}, {'_id': 0}).sort('code', 1)
        results = list(cursor)
        if results:
            return results
    except Exception as e:
        logger.warning(f"从数据库读取指数列表失败: {e}")
    # 回退：用种子数据初始化数据库，同时写入数据库
    try:
        db = get_db()
        for cfg in INDEX_CONFIG_SEED:
            db['index_basics'].update_one(
                {'code': cfg['code']},
                {'$set': {'code': cfg['code'], 'name': cfg['name'],
                         'tdx_code': cfg['tdx_code'], 'market': cfg['market']}},
                upsert=True
            )
    except Exception as e:
        logger.warning(f"初始化指数种子数据失败: {e}")
    return [{'code': c['code'], 'name': c['name'], 'tdx_code': c['tdx_code'], 'market': c['market']}
            for c in INDEX_CONFIG_SEED]


def get_sync_index_config() -> List[Dict[str, Any]]:
    """获取用于同步的指数完整配置（含 tdx_code 和 market），合并 exclusions 中新增的指数"""
    cfgs = get_index_config_from_db()
    # 确保每条记录都有 tdx_code 和 market（从数据库读可能没有）
    result = []
    existing_codes = set()
    for c in cfgs:
        item = {
            'code': c.get('code', ''),
            'name': c.get('name', ''),
            'tdx_code': c.get('tdx_code', c.get('code', '')),
            'market': c.get('market', 1),
        }
        result.append(item)
        existing_codes.add(item['code'])

    # 合并 exclusions 集合中新增的指数（通过管理弹窗添加的）
    try:
        db = get_db()
        excl_items = list(db['exclusions'].find(
            {'category': 'index'}, {'_id': 0, 'code': 1, 'name': 1}
        ))
        for item in excl_items:
            code = item.get('code', '')
            if code and code not in existing_codes:
                result.append({
                    'code': code,
                    'name': item.get('name', code),
                    'tdx_code': code,
                    'market': 1,
                })
                existing_codes.add(code)
    except Exception as e:
        logger.warning(f"合并 exclusions 指数失败: {e}")

    return result


def get_index_data(index_code: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
    """获取指数数据"""
    db = get_db()
    
    pipeline = [
        {'$match': {
            'stock_code': index_code,
            'trade_date': {'$gte': start_date, '$lte': end_date}
        }},
        {'$sort': {'trade_date': 1}},
        {'$project': {
            '_id': 0,
            'trade_date': 1,
            'close': 1,
            'open': 1,
            'high': 1,
            'low': 1
        }}
    ]
    
    return list(db.index_daily.aggregate(pipeline))


def normalize_index_data(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """归一化指数数据到0-100范围"""
    if not data:
        return []
    
    # 获取第一个交易日的收盘价作为基准
    base_value = data[0]['close']
    
    result = []
    for item in data:
        normalized = ((item['close'] / base_value) - 1) * 100 + 50  # 基准在50的位置
        result.append({
            'trade_date': item['trade_date'],
            'value': normalized,
            'close': item['close']
        })
    
    return result


@router.get("/cr5")
def get_cr5_factor(
    start_date: Optional[str] = Query(None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD"),
    include_index: bool = Query(True, description="是否包含指数数据"),
    period: str = Query("day", description="聚合周期: day/week/month/quarter/year")
):
    """获取CR5%因子数据（支持日/周/月/季/年聚合，默认近一年日数据）"""
    try:
        now = datetime.now()

        # 根据周期决定默认拉取时间范围
        if not start_date or not end_date:
            if period == "day":
                default_start = now - timedelta(days=120)
            elif period == "week":
                default_start = now - timedelta(days=365)  # 1年
            elif period == "month":
                default_start = now - timedelta(days=365 * 3)  # 3年
            elif period == "quarter":
                default_start = now - timedelta(days=365 * 5)  # 5年
            else:  # year
                default_start = now - timedelta(days=365 * 10)  # 10年
            if not start_date:
                start_date = default_start.strftime("%Y%m%d")
            if not end_date:
                end_date = now.strftime("%Y%m%d")

        fe = get_factor_engine()
        cr5_series = fe.get_all_cr5_history(start_date, end_date)
        sector_cr_series = fe.get_sector_cr_history(start_date, end_date, percentile=10)

        if len(cr5_series) == 0 and len(sector_cr_series) == 0:
            raise HTTPException(status_code=404, detail="暂无因子数据")

        # 转换为日数据
        daily_data = []
        for idx, value in cr5_series.items():
            date_str = str(idx)
            if start_date and date_str < start_date:
                continue
            if end_date and date_str > end_date:
                continue
            daily_data.append({
                'trade_date': date_str,
                'value': float(value)
            })

        # 板块 CR 日数据
        sector_daily_data = []
        for idx, value in sector_cr_series.items():
            date_str = str(idx)
            if start_date and date_str < start_date:
                continue
            if end_date and date_str > end_date:
                continue
            sector_daily_data.append({
                'trade_date': date_str,
                'value': float(value)
            })

        # 根据周期聚合
        data = _aggregate_by_period(daily_data, period)
        sector_data = _aggregate_by_period(sector_daily_data, period)

        # 指数数据（同步聚合到相同周期）
        extra_data = {}
        db_index_list = get_index_config_from_db()

        # 合并 exclusions 中新增的指数（通过管理弹窗添加的，如微盘股）
        try:
            db = get_db()
            existing_codes = {c.get('code') for c in db_index_list}
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
                    db_index_list.append({
                        'code': code,
                        'name': item.get('name', code),
                    })
                    existing_codes.add(code)
            # 过滤掉禁用的指数
            if disabled_codes:
                db_index_list = [c for c in db_index_list if c.get('code') not in disabled_codes]
        except Exception:
            pass

        if include_index and daily_data:
            # 使用聚合前的日数据日期范围查询指数（数据库存储YYYYMMDD格式）
            dates = [d['trade_date'] for d in daily_data]
            date_start = min(dates)
            date_end = max(dates)
            for config in db_index_list:
                index_code = config['code']
                index_raw = get_index_data(index_code, date_start, date_end)
                if index_raw:
                    normalized = normalize_index_data(index_raw)
                    extra_data[index_code] = _aggregate_index_by_period(normalized, period)

        # 按日期排序
        data.sort(key=lambda x: x['trade_date'])
        sector_data.sort(key=lambda x: x['trade_date'])
        for idx in extra_data:
            extra_data[idx].sort(key=lambda x: x['trade_date'])

        # 获取最新交易日的股票数量
        total_stocks = 0
        if data:
            latest_date = data[-1]['trade_date']
            db = get_db()
            stock_count_result = list(db['stock_daily'].aggregate([
                {'$match': {'trade_date': latest_date, 'amount': {'$exists': True, '$gt': 0}}},
                {'$count': 'count'}
            ]))
            total_stocks = stock_count_result[0]['count'] if stock_count_result else 0

        return {
            'total': len(data),
            'period': period,
            'data': data,
            'sector_cr_data': sector_data,
            'index_data': extra_data,
            'index_config': [{'code': c['code'], 'name': c['name']} for c in db_index_list],
            'total_stocks': total_stocks
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取CR5因子失败: {e}")
        raise HTTPException(status_code=500, detail="获取因子数据失败")


def _aggregate_by_period(daily_data: List[Dict[str, Any]], period: str) -> List[Dict[str, Any]]:
    """把日级 CR5% 按周/月/季/年聚合，非日周期取该周期最后一个交易日的值"""
    if period == "day":
        return daily_data

    bucket_map = {}  # bucket_key -> {trade_date, value, sort_key}
    for item in daily_data:
        d = item['trade_date']  # YYYYMMDD
        y, m, day = int(d[0:4]), int(d[4:6]), int(d[6:8])
        
        if period == "week":
            iso_year, iso_week, _ = date(y, m, day).isocalendar()
            key = f"{iso_year}W{iso_week:02d}"
            # 使用该周最后一天作为显示日期
            from datetime import timedelta as td
            week_end = date(y, m, day) + td(days=(6 - date(y, m, day).weekday()))
            sort_key = week_end.strftime("%Y%m%d")
        elif period == "month":
            key = f"{y}-{m:02d}"
            # 使用该月最后一天
            if m == 12:
                sort_key = f"{y}1231"
            else:
                sort_key = f"{y}{m+1:02d}01" if m < 9 else f"{y}{m+1:02d}01"
                # 简化：用当月最后一天
                import calendar
                last_day = calendar.monthrange(y, m)[1]
                sort_key = f"{y}{m:02d}{last_day:02d}"
        elif period == "quarter":
            q = (m - 1) // 3 + 1
            key = f"{y}Q{q}"
            # 季度末日期
            quarter_end_month = q * 3
            import calendar
            last_day = calendar.monthrange(y, quarter_end_month)[1]
            sort_key = f"{y}{quarter_end_month:02d}{last_day:02d}"
        else:  # year
            key = f"{y}"
            sort_key = f"{y}1231"

        # 保留最后一个交易日的值
        if key not in bucket_map or d > bucket_map[key]['original_date']:
            bucket_map[key] = {
                'trade_date': key,  # 使用周期标签作为日期
                'value': item['value'],
                'original_date': d,
                'sort_key': sort_key
            }

    # 按排序键排序
    result = sorted(bucket_map.values(), key=lambda x: x['sort_key'])
    # 移除 sort_key 字段
    for item in result:
        del item['sort_key']
        del item['original_date']
    return result


def _aggregate_index_by_period(normalized: List[Dict[str, Any]], period: str) -> List[Dict[str, Any]]:
    """把归一化后的指数数据按相同周期聚合"""
    if period == "day":
        return normalized

    bucket_map = {}
    for item in normalized:
        d = item['trade_date']
        y, m, day = int(d[0:4]), int(d[4:6]), int(d[6:8])
        
        if period == "week":
            iso_year, iso_week, _ = date(y, m, day).isocalendar()
            key = f"{iso_year}W{iso_week:02d}"
            from datetime import timedelta as td
            week_end = date(y, m, day) + td(days=(6 - date(y, m, day).weekday()))
            sort_key = week_end.strftime("%Y%m%d")
        elif period == "month":
            key = f"{y}-{m:02d}"
            import calendar
            last_day = calendar.monthrange(y, m)[1]
            sort_key = f"{y}{m:02d}{last_day:02d}"
        elif period == "quarter":
            q = (m - 1) // 3 + 1
            key = f"{y}Q{q}"
            quarter_end_month = q * 3
            import calendar
            last_day = calendar.monthrange(y, quarter_end_month)[1]
            sort_key = f"{y}{quarter_end_month:02d}{last_day:02d}"
        else:
            key = f"{y}"
            sort_key = f"{y}1231"

        if key not in bucket_map or d > bucket_map[key]['original_date']:
            bucket_map[key] = {
                'trade_date': key,
                'value': item['value'],
                'close': item.get('close'),  # 保留原始收盘价
                'original_date': d,
                'sort_key': sort_key
            }

    result = sorted(bucket_map.values(), key=lambda x: x['sort_key'])
    for item in result:
        del item['sort_key']
        del item['original_date']
    return result




@router.get("/indices")
def get_indices_list(
    page: Optional[int] = Query(None, ge=1, description="页码"),
    page_size: Optional[int] = Query(50, ge=1, le=500, description="每页数量"),
    keyword: Optional[str] = Query(None, description="搜索关键词（代码或名称）"),
    filter_mode: Optional[str] = Query(None, description="筛选模式: enabled/disabled")
):
    """获取指数列表（支持分页、搜索和状态筛选）"""
    try:
        cfgs = get_index_config_from_db()
        indices = [{'code': c.get('code', ''), 'name': c.get('name', '')} for c in cfgs]
        existing_codes = {item['code'] for item in indices}
        disabled_codes = set()

        try:
            db = get_db()
            excl_items = list(db['exclusions'].find(
                {'category': 'index'}, {'_id': 0, 'code': 1, 'name': 1, 'exclude_sync': 1}
            ))
            for item in excl_items:
                code = item.get('code', '')
                if not code:
                    continue
                if item.get('exclude_sync'):
                    disabled_codes.add(code)
                if code not in existing_codes:
                    indices.append({'code': code, 'name': item.get('name', code)})
                    existing_codes.add(code)
        except Exception as e:
            logger.warning(f"合并 exclusions 指数失败: {e}")

        if filter_mode == 'disabled':
            indices = [i for i in indices if i['code'] in disabled_codes]
        elif filter_mode == 'enabled':
            indices = [i for i in indices if i['code'] not in disabled_codes]

        if keyword:
            kw = keyword.lower()
            indices = [i for i in indices if kw in i['code'].lower() or kw in i.get('name', '').lower()]

        total = len(indices)

        if page is not None:
            start = (page - 1) * page_size
            indices = indices[start:start + page_size]

        return {'success': True, 'indices': indices, 'total': total}
    except Exception as e:
        logger.error(f"获取指数列表失败: {e}")
        raise HTTPException(status_code=500, detail="获取指数列表失败")


@router.get("/indices/search")
def search_indices(keyword: str = Query(..., description="搜索关键词（代码或名称）")):
    """搜索指数（先本地数据库，再查通达信 TDX）"""
    try:
        db = get_db()
        results = []
        keyword_lower = keyword.lower()
        
        # 1. 先从本地数据库 index_basics 搜索
        local_cursor = db['index_basics'].find(
            {'$or': [
                {'code': {'$regex': keyword, '$options': 'i'}},
                {'name': {'$regex': keyword, '$options': 'i'}}
            ]},
            {'_id': 0, 'code': 1, 'name': 1, 'tdx_code': 1, 'market': 1}
        ).limit(20)
        local_results = list(local_cursor)
        results.extend([{'code': r['code'], 'name': r['name'], 'source': 'local'} for r in local_results])
        
        # 2. 从 TDX 搜索
        try:
            import sys
            if '_vendor/pytdx' not in sys.path:
                sys.path.insert(0, '_vendor/pytdx')
            from pytdx.hq import TdxHq_API
            from pytdx.params import TDXParams
            servers = [
                ('180.153.18.170', 7709),
                ('119.147.212.81', 7709),
                ('60.12.136.250', 7709),
            ]
            existing_codes = {r['code'] for r in results}
            
            for server in servers:
                try:
                    api = TdxHq_API()
                    if api.connect(*server, time_out=5):
                        # 搜索沪市指数 (market=1)
                        count = api.get_security_count(1) or 0
                        for start in range(0, min(count, 30000), 1000):
                            items = api.get_security_list(1, start)
                            if not items:
                                continue
                            for s in items:
                                code = s.get('code', '')
                                name = s.get('name', '')
                                if code and name and (
                                    keyword_lower in code.lower() or 
                                    keyword in name
                                ):
                                    full_code = code
                                    if full_code not in existing_codes:
                                        results.append({
                                            'code': full_code,
                                            'name': name,
                                            'source': 'tdx'
                                        })
                                        existing_codes.add(full_code)
                                        if len(results) >= 20:
                                            break
                            if len(results) >= 20:
                                break
                        
                        # 如果搜索结果不足，尝试直接通过 get_index_bars 验证输入的代码
                        if len(results) < 10 and keyword.isdigit() and len(keyword) == 6:
                            test_code = keyword
                            if test_code not in existing_codes:
                                try:
                                    data = api.get_index_bars(
                                        TDXParams.KLINE_TYPE_DAILY, 1, test_code, 0, 1
                                    )
                                    if data and len(data) > 0:
                                        # 从名称映射表查找真实名称
                                        real_name = TDX_INDEX_NAME_MAP.get(test_code)
                                        # 尝试通过 get_security_quotes 获取
                                        if not real_name:
                                            try:
                                                quotes = api.get_security_quotes([(1, test_code)])
                                                if quotes and len(quotes) > 0:
                                                    real_name = quotes[0].get('name', '')
                                            except Exception:
                                                pass
                                        if not real_name:
                                            try:
                                                quotes = api.get_security_quotes([(0, test_code)])
                                                if quotes and len(quotes) > 0:
                                                    real_name = quotes[0].get('name', '')
                                            except Exception:
                                                pass
                                        results.append({
                                            'code': test_code,
                                            'name': real_name or f'指数{test_code}',
                                            'source': 'tdx'
                                        })
                                        existing_codes.add(test_code)
                                except Exception:
                                    pass
                        
                        api.disconnect()
                        break
                except Exception as e:
                    logger.warning(f"TDX 服务器 {server} 搜索失败: {e}")
                    continue
        except Exception as e:
            logger.warning(f"TDX 搜索失败: {e}")
        
        return {'success': True, 'data': results[:20], 'total': len(results)}
    except Exception as e:
        logger.error(f"搜索指数失败: {e}")
        raise HTTPException(status_code=500, detail="搜索指数失败")


@router.post("/sync-indices")
def sync_index_data(
    start_date: Optional[str] = Query(None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD"),
    max_workers: Optional[int] = Query(4, description="最大线程数")
):
    """同步所有指数数据（后台任务）"""
    try:
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
        if not start_date:
            start_date = "20180101"

        tm = get_task_manager()
        task_id = tm.create_task(100)

        excluded_indices = get_excluded_set('index', 'sync')
        sync_cfg = get_sync_index_config()
        if excluded_indices:
            sync_cfg = [c for c in sync_cfg if c.get('code') not in excluded_indices]
            logger.info(f"排除 {len(excluded_indices)} 个指数，实际同步 {len(sync_cfg)} 个")

        def _run_sync_indices(tid):
            try:
                from pytdx.hq import TdxHq_API
                from pytdx.params import TDXParams
                from app.data.db import get_db
                from pymongo import UpdateOne
                import time

                db = get_db()
                servers = [
                    ('180.153.18.170', 7709),
                    ('180.153.18.171', 7709),
                    ('60.12.136.250', 7709),
                ]

                success_count = 0
                fail_count = 0
                total = len(sync_cfg)

                tm.update_task_progress(tid, current_stock="0", current_stock_name="开始同步指数...")

                for i, idx_config in enumerate(sync_cfg):
                    if tm.is_cancelled(tid):
                        logger.info(f"任务 {tid} 已取消，停止指数同步")
                        return
                    try:
                        tm.update_task_progress(
                            tid,
                            current_stock=str(i),
                            current_stock_name=f"正在同步 {idx_config['name']}...",
                            total_count=total,
                            completed_count=i
                        )
                        logger.info(f"正在同步 {idx_config['name']}...")

                        records_saved = False
                        for server in servers:
                            try:
                                api = TdxHq_API()
                                if api.connect(*server):
                                    all_data = []
                                    offset = 0
                                    max_retries = 3
                                    retry_count = 0

                                    while True:
                                        data = api.get_index_bars(
                                            category=TDXParams.KLINE_TYPE_DAILY,
                                            market=idx_config['market'],
                                            code=idx_config['tdx_code'],
                                            start=offset,
                                            count=800
                                        )

                                        if not data or len(data) == 0:
                                            break

                                        valid_data = []
                                        abnormal_count = 0
                                        for item in data:
                                            try:
                                                year = item.get('year', 0)
                                                vol = item.get('vol', 0)
                                                amount = item.get('amount', 0)
                                                if year > 2050 or vol > 1e15 or amount > 1e20:
                                                    abnormal_count += 1
                                                    continue
                                                if 2000 <= year <= 2050:
                                                    valid_data.append(item)
                                            except:
                                                continue

                                        if len(data) > 0 and (abnormal_count / len(data)) > 0.5:
                                            api.disconnect()
                                            time.sleep(1)
                                            if retry_count < max_retries:
                                                retry_count += 1
                                                continue
                                            else:
                                                break

                                        all_data.extend(valid_data)
                                        if len(data) < 800:
                                            break
                                        offset += 800

                                    api.disconnect()

                                    if all_data and len(all_data) > 0:
                                        records = []
                                        for item in all_data:
                                            try:
                                                if 'year' in item and 'month' in item and 'day' in item:
                                                    trade_date = f"{item['year']:04d}{item['month']:02d}{item['day']:02d}"
                                                elif 'datetime' in item:
                                                    dt_str = str(item['datetime'])
                                                    if ' ' in dt_str:
                                                        dt_str = dt_str.split(' ')[0]
                                                    trade_date = dt_str.replace('-', '')
                                                elif 'date' in item:
                                                    trade_date = str(item['date']).replace('-', '')
                                                else:
                                                    continue

                                                if len(trade_date) != 8:
                                                    continue
                                                if not (start_date <= trade_date <= end_date):
                                                    continue

                                                open_val = float(item.get('open', 0))
                                                high_val = float(item.get('high', 0))
                                                low_val = float(item.get('low', 0))
                                                close_val = float(item.get('close', 0))

                                                if (open_val <= 0 or open_val > 100000 or
                                                    high_val <= 0 or high_val > 100000 or
                                                    low_val <= 0 or low_val > 100000 or
                                                    close_val <= 0 or close_val > 100000):
                                                    continue

                                                records.append({
                                                    'stock_code': idx_config['code'],
                                                    'trade_date': trade_date,
                                                    'open': open_val,
                                                    'high': high_val,
                                                    'low': low_val,
                                                    'close': close_val,
                                                    'volume': float(item.get('vol', item.get('volume', 0))),
                                                    'amount': float(item.get('amount', 0))
                                                })
                                            except:
                                                continue

                                        if records:
                                            ops = []
                                            for rec in records:
                                                doc = dict(rec)
                                                doc['data_type'] = 'index'
                                                doc['data_source'] = 'pytdx'
                                                doc['update_time'] = datetime.utcnow()
                                                ops.append(UpdateOne(
                                                    {'stock_code': doc['stock_code'], 'trade_date': doc['trade_date']},
                                                    {'$set': doc},
                                                    upsert=True
                                                ))
                                            db.index_daily.bulk_write(ops, ordered=False)
                                            success_count += 1
                                            logger.info(f"成功同步 {idx_config['name']} {len(records)} 条数据")
                                            records_saved = True
                                            break

                            except Exception as e:
                                logger.warning(f"服务器 {server} 获取 {idx_config['name']} 失败: {e}")
                                continue

                        if not records_saved:
                            fail_count += 1
                            logger.error(f"所有服务器获取 {idx_config['name']} 都失败")

                    except Exception as e:
                        logger.error(f"同步 {idx_config['name']} 失败: {e}")
                        fail_count += 1

                msg = f"指数数据同步完成，成功 {success_count} 个，失败 {fail_count} 个"
                logger.info(msg)
                tm.complete_task(tid, msg)
                try:
                    from app.server.cache import refresh_trade_dates
                    refresh_trade_dates()
                except Exception:
                    pass

            except Exception as e:
                logger.error(f"指数同步失败: {e}")
                tm.fail_task(tid, f"失败: {str(e)}")

        thread = threading.Thread(target=_run_sync_indices, args=(task_id,))
        thread.daemon = True
        thread.start()

        return {
            "success": True,
            "task_id": task_id,
            "message": f"指数同步任务已启动，共 {len(sync_cfg)} 个指数"
        }

    except Exception as e:
        logger.error(f"启动指数同步任务失败: {e}")
        return {"success": False, "message": str(e)}


# ==================== RPS 相关 API ====================


def _run_rps_calculation_task(
    task_id: str,
    start_date: Optional[str],
    end_date: Optional[str],
    target_date: Optional[str],
    target: str = 'stock',
    excluded_codes: Optional[List[str]] = None
):
    """后台任务：计算 RPS
    Args:
        target: 'stock' - 仅个股, 'sector' - 仅板块, 'all' - 全部
        excluded_codes: 被排除的代码列表
    """
    try:
        tm = get_task_manager()
        from app.engine.factor_engine import FactorEngine

        # 1. 启动进度
        tm.update_task_progress(
            task_id,
            current_stock="0",
            current_stock_name="正在扫描日期范围..."
        )

        # 2. 执行计算（带进度回调，含取消检查）
        def _progress(msg, current_idx, total_count, phase=""):
            if tm.is_cancelled(task_id):
                raise InterruptedError("任务已取消")
            tm.update_task_progress(
                task_id,
                current_stock=str(current_idx),
                current_stock_name=msg,
                total_count=max(1, int(total_count)),
                completed_count=int(current_idx)
            )

        engine = FactorEngine()
        result = engine.calculate_rps(
            data_type=target,
            max_dates=None,
            progress_callback=_progress,
            excluded_codes=excluded_codes or []
        )

        message = f"RPS-{target} 完成: 日期={result.get('dates', 0)}, 品种={result.get('codes', 0)}, 更新={result.get('updates', 0)}"
        logger.info(message)

        # 4. RPS计算完成后自动计算涨幅字段
        logger.info("RPS计算完成，开始计算涨幅字段...")
        try:
            from app.data.manager import get_data_manager
            dm = get_data_manager()
            chg_result = dm.calculate_chg_fields(target=target)
            logger.info(f"涨幅字段计算完成: {chg_result}")
        except Exception as e:
            logger.error(f"计算涨幅字段失败: {e}")

        # 5. 更新任务状态
        tm.update_task_progress(
            task_id,
            current_stock=str(result.get('dates', 0)),
            current_stock_name="计算完成",
            total_count=max(1, int(result.get('dates', 0))),
            completed_count=int(result.get('dates', 0))
        )
        tm.complete_task(task_id, message)
        try:
            from app.server.cache import refresh_trade_dates
            refresh_trade_dates()
        except Exception:
            pass

    except Exception as e:
        logger.error(f"RPS 计算任务失败: {e}")
        import traceback
        traceback.print_exc()
        tm = get_task_manager()
        tm.fail_task(task_id, f"计算失败: {str(e)}")


@router.post("/rps/calculate", response_model=Dict[str, Any])
def calculate_and_save_rps(
    start_date: Optional[str] = Query(None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD"),
    target_date: Optional[str] = Query(None, description="只计算指定日期的 RPS（增量模式）"),
    target: str = Query('stock', description="'stock' 个股 | 'sector' 板块 | 'all' 全部"),
    max_workers: Optional[int] = Query(16, description="最大线程数"),
    min_days: Optional[int] = Query(None, description="最小上市天数（可选）")
):
    """计算并保存 RPS 指标（后台任务）"""
    try:
        tm = get_task_manager()
        task_id = tm.create_task(100)

        # 获取排除列表（按target分别取）
        if target == 'stock':
            excluded_codes = list(get_excluded_set('stock', 'rps'))
        elif target == 'sector':
            excluded_codes = list(get_excluded_set('sector', 'rps'))
        else:
            excluded_codes = list(get_excluded_set('stock', 'rps')) + list(get_excluded_set('sector', 'rps'))

        thread = threading.Thread(
            target=_run_rps_calculation_task,
            args=(task_id, start_date, end_date, target_date, target, excluded_codes)
        )
        thread.daemon = True
        thread.start()

        return {
            "success": True,
            "task_id": task_id,
            "message": f"RPS({target}) 计算任务已启动，后台执行中，最小天数: {min_days or '不限'}"
        }

    except Exception as e:
        logger.error(f"启动 RPS 计算任务失败: {e}")
        return {
            "success": False,
            "message": f"启动任务失败: {str(e)}"
        }


@router.post("/tasks/clear", response_model=Dict[str, Any])
def clear_all_tasks():
    """清除所有后台任务状态（用于重置脏数据）"""
    try:
        from app.data.db import get_db
        db = get_db()
        result = db['sync_tasks'].delete_many({})
        return {
            "success": True,
            "message": f"已清除 {result.deleted_count} 条任务状态"
        }
    except Exception as e:
        logger.error(f"清除任务状态失败: {e}")
        return {"success": False, "message": str(e)}


@router.delete("/rps", response_model=Dict[str, Any])
def delete_rps_data(
    target: str = Query('all', description="'stock' 只清个股RPS | 'sector' 只清板块RPS | 'all' 全部")
):
    """清除 RPS 数据（不删除日线，只清 rps_* 字段）"""
    try:
        from app.data.db import get_db
        db = get_db()

        rps_fields = ['rps_10', 'rps_20', 'rps_50', 'rps_120', 'rps_250']
        chg_fields = ['chg_10', 'chg_20', 'chg_50', 'chg_120', 'chg_250']
        unset_doc = {f: "" for f in rps_fields + chg_fields}
        unset_doc['update_time'] = ""

        total_modified = 0
        if target in ('stock', 'all'):
            result = db['stock_daily'].update_many({}, {'$unset': unset_doc})
            total_modified += result.modified_count
        if target in ('sector', 'all'):
            result = db['sector_daily'].update_many({}, {'$unset': unset_doc})
            total_modified += result.modified_count

        return {
            "success": True,
            "message": f"已清除 {total_modified} 条 RPS 字段（{target}）"
        }
    except Exception as e:
        logger.error(f"清除 RPS 数据失败: {e}")
        return {"success": False, "message": str(e)}


# ==================== 板块行业相关 API ====================

@router.post("/sync-sectors", response_model=Dict[str, Any])
def sync_sectors(
    start_date: Optional[str] = Query(None, description="起始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="截止日期 YYYYMMDD"),
    max_workers: Optional[int] = Query(16, description="最大线程数"),
    min_days: Optional[int] = Query(None, description="最小天数（可选）")
):
    """同步板块概念 + 聚合板块日线（后台任务）"""
    try:
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
        if not start_date:
            start_date = "20180101"

        tm = get_task_manager()
        task_id = tm.create_task(100)

        excluded_sectors = get_excluded_set('sector', 'sync')

        def _run_sync_sectors(tid):
            try:
                logger.info(f"启动板块同步任务: {start_date} ~ {end_date}，线程数: {max_workers}，最小天数: {min_days}")
                if excluded_sectors:
                    logger.info(f"排除 {len(excluded_sectors)} 个板块")
                tm.update_task_progress(tid, current_stock="初始化", current_stock_name="读取通达信板块信息...")
                dm = get_data_manager()

                def _progress(current_idx, total_count, sector_name):
                    if tm.is_cancelled(tid):
                        raise InterruptedError("任务已取消")
                    tm.update_task_progress(
                        tid,
                        current_stock=str(current_idx),
                        current_stock_name=sector_name,
                        total_count=total_count,
                        completed_count=current_idx
                    )

                result = dm.sync_sector_indices(
                    start_date=start_date,
                    end_date=end_date,
                    progress_callback=_progress,
                    excluded_codes=excluded_sectors
                )
                msg = f"完成: 共 {result.get('block_count', 0)} 个板块，{result.get('sector_daily_count', 0)} 条日线聚合"
                logger.info(msg)

                # 板块同步完成后自动计算冗余字段
                logger.info("板块同步完成，开始计算冗余字段...")
                try:
                    derived_result = dm.calculate_all_derived_fields(target='sector')
                    logger.info(f"板块冗余字段计算完成: {derived_result}")
                except Exception as e:
                    logger.error(f"计算板块冗余字段失败: {e}")

                tm.complete_task(tid, msg)
                try:
                    from app.server.cache import refresh_trade_dates
                    refresh_trade_dates()
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"板块同步失败: {e}")
                tm.fail_task(tid, f"失败: {str(e)}")

        thread = threading.Thread(target=_run_sync_sectors, args=(task_id,))
        thread.daemon = True
        thread.start()

        return {
            "success": True,
            "task_id": task_id,
            "message": "板块同步任务已启动"
        }
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
    min_stock_count: Optional[int] = Query(5, description="最少成分股数")
):
    """获取板块列表（支持分页、搜索和状态筛选，含RPS数据）"""
    try:
        db = get_db()
        query = {}
        if min_stock_count:
            query['stock_count'] = {'$gte': min_stock_count}

        cursor = db['sector_basics'].find(query, {'_id': 0, 'code': 1, 'name': 1, 'source': 1, 'stock_count': 1})
        items = list(cursor)

        # 获取最新交易日的RPS数据
        sector_coll = db['sector_daily']
        latest_doc = sector_coll.find_one(
            {},
            sort=[('trade_date', -1)],
            projection={'trade_date': 1, '_id': 0}
        )
        if latest_doc:
            latest_date = latest_doc['trade_date']
            rps_cursor = sector_coll.find(
                {'trade_date': latest_date},
                {'_id': 0, 'stock_code': 1, 'rps_10': 1, 'rps_20': 1, 'rps_50': 1}
            )
            rps_map = {d['stock_code']: d for d in rps_cursor}
            for item in items:
                rps = rps_map.get(item['code'], {})
                item['rps_10'] = rps.get('rps_10')
                item['rps_20'] = rps.get('rps_20')
                item['rps_50'] = rps.get('rps_50')

        if filter_mode in ('enabled', 'disabled'):
            excl_docs = list(db['exclusions'].find(
                {'category': 'sector', 'exclude_sync': True},
                {'_id': 0, 'code': 1}
            ))
            disabled_codes = {d['code'] for d in excl_docs if d.get('code')}
            if filter_mode == 'disabled':
                items = [i for i in items if i.get('code') in disabled_codes]
            else:
                items = [i for i in items if i.get('code') not in disabled_codes]

        if keyword:
            kw = keyword.lower()
            items = [i for i in items if kw in i.get('code', '').lower() or kw in i.get('name', '').lower()]

        total = len(items)

        if limit and page is None:
            items = items[:limit]
        elif page is not None:
            start = (page - 1) * page_size
            items = items[start:start + page_size]

        return {
            "success": True,
            "total": total,
            "items": items
        }
    except Exception as e:
        logger.error(f"获取板块列表失败: {e}")
        return {"success": False, "message": str(e), "total": 0, "items": []}


@router.post("/sectors/import-codes")
async def import_sector_codes(file: 'UploadFile'):
    """导入板块代码映射（Excel/CSV），用于将中文板块名匹配到数字代码"""
    try:
        import io
        from fastapi import UploadFile
        from pymongo import UpdateOne

        content = await file.read()
        filename = file.filename or ''

        if filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(content))
        elif filename.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(io.BytesIO(content))
        else:
            return {"success": False, "message": "请上传 Excel (.xlsx/.xls) 或 CSV 文件"}

        # 自动识别列名：找 code/name 列
        cols = [str(c).strip() for c in df.columns]
        code_col = None
        name_col = None
        for c in cols:
            cl = c.lower()
            if cl in ('code', '代码', '板块代码', 'tdx_code', '数字代码'):
                code_col = c
            elif cl in ('name', '名称', '板块名称', '板块名'):
                name_col = c

        if not code_col or not name_col:
            # 回退：第一列当代码，第二列当名称
            if len(cols) >= 2:
                code_col = cols[0]
                name_col = cols[1]
            else:
                return {"success": False, "message": "无法识别代码和名称列，请确保表头包含 code/代码 和 name/名称"}

        mapping = {}
        skipped = 0
        for _, row in df.iterrows():
            code = str(row[code_col]).strip()
            name = str(row[name_col]).strip()
            if code and name and code != 'nan' and name != 'nan':
                # 只接受880/881开头的代码
                if code.startswith('880') or code.startswith('881'):
                    mapping[name] = code
                else:
                    skipped += 1

        if not mapping:
            return {"success": False, "message": "文件中没有有效的880/881板块代码"}

        if skipped > 0:
            logger.info(f"导入板块代码: 跳过 {skipped} 个非880/881代码")

        logger.info(f"导入板块代码映射: {len(mapping)} 条")

        # 更新 sector_basics
        db = get_db()
        updated = 0
        added = 0
        migrated = 0
        for name, code in mapping.items():
            # 查找是否已存在
            existing = db['sector_basics'].find_one({'$or': [{'code': code}, {'name': name}]})

            if existing:
                # 更新代码
                if existing.get('code') != code:
                    old_code = existing['code']
                    db['sector_basics'].update_one(
                        {'_id': existing['_id']},
                        {'$set': {'code': code, 'tdx_code': code}}
                    )
                    # 迁移日线数据
                    result = db['sector_daily'].update_many(
                        {'stock_code': old_code},
                        {'$set': {'stock_code': code}}
                    )
                    migrated += result.modified_count
                    updated += 1
            else:
                # 新增板块
                db['sector_basics'].insert_one({
                    'code': code,
                    'tdx_code': code,
                    'name': name,
                    'source': '导入',
                    'stock_count': 0,
                    'stock_codes': [],
                    'block_type': 2,
                    'update_time': datetime.utcnow()
                })
                added += 1

        return {
            "success": True,
            "message": f"导入完成: 新增 {added} 个板块, 更新 {updated} 个, 迁移 {migrated} 条日线数据",
            "added": added,
            "updated": updated,
            "migrated": migrated,
            "total_mapping": len(mapping)
        }

    except Exception as e:
        logger.error(f"导入板块代码失败: {e}")
        return {"success": False, "message": str(e)}


@router.get("/rps/{code}", response_model=Dict[str, Any])
def get_stock_rps(
    code: str,
    start_date: Optional[str] = Query(None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD"),
    period: str = Query("day", description="数据周期: day/week/month")
):
    """
    获取指定股票的 RPS 数据（支持日/周/月线聚合）
    
    Args:
        code: 股票代码
        start_date: 开始日期（可选）
        end_date: 结束日期（可选）
        period: 数据周期 day/week/month
    
    Returns:
        该股票的 RPS 历史数据
    """
    try:
        db = get_db()

        # 根据代码判断数据类型
        if code.startswith('88'):
            coll = db['sector_daily']
        elif code.startswith(('00', '30', '60', '68')):
            coll = db['stock_daily']
        else:
            coll = db['index_daily']

        query = {"stock_code": code}
        if start_date or end_date:
            query["trade_date"] = {}
            if start_date:
                query["trade_date"]["$gte"] = start_date
            if end_date:
                query["trade_date"]["$lte"] = end_date

        cursor = coll.find(
            query,
            {"_id": 0, "stock_code": 1, "trade_date": 1,
             "rps_10": 1, "rps_20": 1, "rps_50": 1, "rps_120": 1, "rps_250": 1,
             "chg_10": 1, "chg_20": 1, "chg_50": 1, "chg_120": 1, "chg_250": 1}
        ).sort("trade_date", 1)
        
        data = list(cursor)
        
        if not data:
            raise HTTPException(status_code=404, detail=f"股票 {code} 没有找到 RPS 数据")
        
        # 转换格式
        result = []
        for item in data:
            result.append({
                "date": item["trade_date"],
                "code": item["stock_code"],
                "rps_10": item.get("rps_10"),
                "rps_20": item.get("rps_20"),
                "rps_50": item.get("rps_50"),
                "rps_120": item.get("rps_120"),
                "rps_250": item.get("rps_250"),
                "chg_10": item.get("chg_10"),
                "chg_20": item.get("chg_20"),
                "chg_50": item.get("chg_50"),
                "chg_120": item.get("chg_120"),
                "chg_250": item.get("chg_250")
            })
        
        # 周线/月线聚合：取每个周期最后一天的RPS值
        if period == "week":
            aggregated = []
            current_week = None
            week_items = []
            
            for item in result:
                date_str = item["date"]
                # 使用ISO周计算：获取年份和周数
                from datetime import datetime
                dt = datetime.strptime(date_str, "%Y%m%d")
                year, week_num, _ = dt.isocalendar()
                week_key = f"{year}-W{week_num:02d}"
                
                if current_week != week_key and week_items:
                    # 取该周最后一天的RPS值，但用第一天的日期
                    last_rps = week_items[-1].copy()
                    last_rps["date"] = week_items[0]["date"]  # 使用第一天日期
                    aggregated.append(last_rps)
                    week_items = []
                
                current_week = week_key
                week_items.append(item)
            
            if week_items:
                last_rps = week_items[-1].copy()
                last_rps["date"] = week_items[0]["date"]
                aggregated.append(last_rps)
            
            result = aggregated
            
        elif period == "month":
            aggregated = []
            current_month = None
            month_items = []
            
            for item in result:
                month_key = item["date"][:6]  # YYYYMM
                
                if current_month != month_key and month_items:
                    # 取该月最后一天的RPS值，但用第一天的日期
                    last_rps = month_items[-1].copy()
                    last_rps["date"] = month_items[0]["date"]  # 使用第一天日期
                    aggregated.append(last_rps)
                    month_items = []
                
                current_month = month_key
                month_items.append(item)
            
            if month_items:
                last_rps = month_items[-1].copy()
                last_rps["date"] = month_items[0]["date"]
                aggregated.append(last_rps)
            
            result = aggregated
        
        return {
            "code": code,
            "period": period,
            "total": len(result),
            "data": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取股票 RPS 失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取 RPS 失败: {str(e)}")


@router.get("/rps", response_model=Dict[str, Any])
def get_rps_by_date(
    trade_date: str = Query(..., description="交易日期 YYYYMMDD"),
    min_rps: Optional[int] = Query(None, description="最低 RPS 阈值（0-99），只返回 RPS 大于等于该值的股票")
):
    """
    获取指定交易日的所有股票 RPS 数据
    
    Args:
        trade_date: 交易日期
        min_rps: 可选的最低 RPS 阈值，用于筛选
    
    Returns:
        该交易日的 RPS 数据
    """
    try:
        db = get_db()

        query = {"trade_date": trade_date}

        # 查询所有三个集合
        data = []
        rps_projection = {"_id": 0, "stock_code": 1, "trade_date": 1,
                          "rps_10": 1, "rps_20": 1, "rps_50": 1, "rps_120": 1, "rps_250": 1,
                          "chg_10": 1, "chg_20": 1, "chg_50": 1, "chg_120": 1, "chg_250": 1}
        for coll_name in ['stock_daily', 'sector_daily', 'index_daily']:
            cursor = db[coll_name].find(query, rps_projection)
            data.extend(list(cursor))
        
        if not data:
            raise HTTPException(status_code=404, detail=f"日期 {trade_date} 没有找到 RPS 数据")
        
        # 转换格式
        result = []
        for item in data:
            rps_record = {
                "code": item["stock_code"],
                "date": item["trade_date"],
                "rps_10": item.get("rps_10"),
                "rps_20": item.get("rps_20"),
                "rps_50": item.get("rps_50"),
                "rps_120": item.get("rps_120"),
                "rps_250": item.get("rps_250"),
                "chg_10": item.get("chg_10"),
                "chg_20": item.get("chg_20"),
                "chg_50": item.get("chg_50"),
                "chg_120": item.get("chg_120"),
                "chg_250": item.get("chg_250")
            }
            
            # 如果指定了最低 RPS 阈值，进行过滤
            if min_rps is not None:
                # 检查任意周期的 RPS 是否满足
                has_valid_rps = any(
                    rps_record[r] is not None and rps_record[r] >= min_rps
                    for r in ["rps_10", "rps_20", "rps_50", "rps_120", "rps_250"]
                )
                if not has_valid_rps:
                    continue
            
            result.append(rps_record)
        
        return {
            "trade_date": trade_date,
            "total": len(result),
            "data": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取日期 RPS 失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取 RPS 失败: {str(e)}")
