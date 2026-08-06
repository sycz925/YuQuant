"""
市场复盘数据 API
提供全栈量化复盘报告所需的数据
盘后预计算落库，后续直接读取
"""
import logging
import threading
from typing import Dict, Any, List, Optional
from datetime import datetime as _dt, timedelta

from fastapi import APIRouter, HTTPException, Query

from app.data.db import get_db
from app.data.task_manager import get_task_manager
from app.server.services.market_data import (
    get_latest_trade_date,
    precompute_market_daily,
    _compute_realtime,
    _aggregate_base_data,
)
from app.server.services.market_signals import (
    generate_market_overview,
    calc_market_signals,
)
from app.server.services.market_sectors import analyze_new_high_blocks
from app.server.services.market_ai import call_deepseek

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/market-review", tags=["market-review"])


# ========== 基础数据 API ==========

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


# ========== 市场概览 API ==========

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


# ========== 板块分析 API ==========

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


# ========== AI 分析 API ==========

@router.get("/ai-analysis")
def get_ai_analysis(date: Optional[str] = Query(None, description="交易日期 YYYYMMDD")):
    """获取 AI 分析结果
    盘后数据(is_final=True)：有缓存直接返回
    盘中数据(is_final=False)：30分钟内返回缓存，超过30分钟需重新生成
    无缓存：返回 need_generate
    """
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
                return gen_time.hour > 15 or (gen_time.hour == 15 and gen_time.minute >= 30)
            except Exception:
                return False

        if existing_ai and existing_ai.get('market_phase_diagnosis') and existing_ai.get('source') != 'failed':
            generated_at = existing_ai.get('generated_at', '')

            if _is_after_market(generated_at):
                return {
                    'success': True,
                    'task_id': None,
                    'trade_date': trade_date,
                    'is_cached': True,
                    'generated_at': generated_at,
                    **existing_ai,
                }

            if generated_at:
                try:
                    gen_time = _dt.fromisoformat(generated_at)
                    if (_dt.now() - gen_time).total_seconds() < 1800:
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

        if existing_ai and existing_ai.get('source') == 'failed':
            db['market_daily'].update_one(
                {'trade_date': trade_date},
                {'$unset': {'ai_analysis': ''}}
            )

        # 创建后台任务
        task_id = tm.create_task(name='AI 综合研判')
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

                market_data = {
                    'trade_date': trade_date,
                    'overview': cached.get('overview', {}),
                    'new_high': cached.get('new_high', {}),
                    'low_position_sectors': cached.get('low_position_sectors', []),
                    'active_sectors': cached.get('active_sectors', []),
                }

                if not market_data['overview'].get('indices'):
                    tm.fail_task(task_id, f"{trade_date} 预计算数据不完整（无指数数据），请先同步指数")
                    return

                # 3. 调用 DeepSeek
                tm.update_task_progress(task_id, current_stock_name="调用 DeepSeek 分析...")
                ai_result = call_deepseek(trade_date, market_data)

                msg = f"AI分析完成 (来源: {ai_result.get('source', 'unknown')})"
                logger.info(f"[AI分析] 准备完成任务 {task_id}: {msg}")
                tm.complete_task(task_id, msg)
                logger.info(f"[AI分析] 任务 {task_id} 已标记完成")
            except Exception as e:
                logger.error(f"AI分析任务失败: {e}")
                try:
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


@router.get("/ai-analysis/input-data")
def get_ai_input_data(date: str = Query(..., description="交易日期 YYYYMMDD")):
    """获取传给DeepSeek的输入数据（从缓存读取）"""
    try:
        db = get_db()

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
        
        sector_doc = db['sector_basics'].find_one({'code': sector_code}, {'_id': 0, 'name': 1, 'stock_codes': 1})
        if not sector_doc:
            raise HTTPException(status_code=404, detail="未找到该板块")
        
        sector_name = sector_doc.get('name', sector_code)
        stock_codes = sector_doc.get('stock_codes', [])
        
        latest_stock = db['stock_daily'].find_one(sort=[('trade_date', -1)])
        if not latest_stock:
            raise HTTPException(status_code=404, detail="无数据")
        trade_date = latest_stock['trade_date']
        
        sector_daily_doc = db['sector_daily'].find_one(
            {'stock_code': sector_code, 'trade_date': trade_date},
            {'_id': 0, 'pioneer': 1, 'main_force': 1, 'followers': 1}
        )
        
        if sector_daily_doc and sector_daily_doc.get('pioneer') is not None:
            return {
                'success': True,
                'trade_date': trade_date,
                'sector_name': sector_name,
                'pioneer': sector_daily_doc.get('pioneer', []),
                'main_force': sector_daily_doc.get('main_force', []),
                'followers': sector_daily_doc.get('followers', []),
            }
        
        if not stock_codes:
            return {
                'success': True,
                'trade_date': trade_date,
                'sector_name': sector_name,
                'pioneer': [],
                'main_force': [],
                'followers': [],
            }
        
        liutong_map = {}
        for b in db['stock_basics'].find({'liutongguben': {'$gt': 0}}, {'_id': 0, 'stock_code': 1, 'liutongguben': 1, 'stock_name': 1}):
            liutong_map[b['stock_code']] = {'liutongguben': b.get('liutongguben', 0), 'name': b.get('stock_name', '')}
        
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
        
        for s in stocks:
            lt = liutong_map.get(s['stock_code'], {})
            liutong = lt.get('liutongguben', 0)
            close = s.get('close', 0)
            s['name'] = lt.get('name', s['stock_code'])
            s['_float_mv'] = liutong * close / 1e8 if liutong and close else 0
        
        by_chg50 = sorted(stocks, key=lambda x: -(x.get('chg_50d', 0) or 0))[:3]
        pioneer = [f"{s['name']}(50日{s.get('chg_50d', 0) or 0:+.1f}%, 今日{s.get('chg_pct', 0) or 0:+.1f}%)" for s in by_chg50]
        
        by_mv = sorted(stocks, key=lambda x: -(x.get('_float_mv', 0) or 0))[:10]
        by_mv_chg50 = sorted(by_mv, key=lambda x: -(x.get('chg_50d', 0) or 0))[:3]
        main_force = [f"{s['name']}(50日{s.get('chg_50d', 0) or 0:+.1f}%, 今日{s.get('chg_pct', 0) or 0:+.1f}%)" for s in by_mv_chg50]
        
        non_st = [s for s in stocks if 'ST' not in (s.get('name') or '').upper()]
        by_mv_asc = sorted(non_st, key=lambda x: x.get('_float_mv', 0) or 0)[:20]
        by_mv_asc_chg = sorted(by_mv_asc, key=lambda x: -(x.get('chg_pct', 0) or 0))[:2]
        followers = [f"{s['name']}({s.get('chg_pct', 0) or 0:+.1f}%)" for s in by_mv_asc_chg]
        
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


# ========== 辅助函数 ==========

def calc_ma_breadth_history(period: str = 'day', index_code: str = None) -> Dict[str, Any]:
    """
    计算近N个周期的MA50和MA20占比历史数据 + 叠加指数数据
    支持 day/week/month/quarter/year 聚合
    """
    from datetime import date as _date
    import calendar
    db = get_db()

    all_dates = sorted(db['stock_daily'].distinct('trade_date'), reverse=True)
    if not all_dates:
        return {'success': False, 'message': '无交易数据'}

    now = _dt.now()
    period_days = {'day': 120, 'week': 365, 'month': 365 * 3, 'quarter': 365 * 5, 'year': 365 * 10}
    cal_days = period_days.get(period, 120)
    start_date = (now - timedelta(days=cal_days)).strftime('%Y%m%d')

    target_dates = [d for d in all_dates if d >= start_date]

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