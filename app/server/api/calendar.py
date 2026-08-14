"""
日历复盘API - 提供日历视图所需的聚合数据
数据来源：base_data_daily + market_daily + index_daily
支持快照缓存，避免重复计算
业务逻辑已迁移至 services/calendar_service.py
"""
import logging
import threading
from typing import Optional, Dict, Any
from datetime import datetime as _dt

from fastapi import APIRouter, HTTPException, Query

from app.data.db import get_db
from app.data.holidays import is_workday
from app.server.services.calendar_service import (
    _get_month_weeks,
    _build_weekly_input_text,
    _run_fill_ai_task,
    WEEKLY_SUMMARY_SYSTEM_PROMPT,
    WEEKLY_SUMMARY_USER_TEMPLATE,
    MONTHLY_SUMMARY_SYSTEM_PROMPT,
    MONTHLY_SUMMARY_USER_TEMPLATE,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/calendar", tags=["日历复盘"])

# 默认大盘指数代码（上证指数）
DEFAULT_INDEX_CODE = "880003"  # 平均股价指数


def _call_summary_llm(analyst, user_message: str, system_hint: str, max_tokens: int = 8192) -> str:
    """调用 DeepSeek 生成周/月总结报告。

    背景：thinking 模式下模型会先输出 reasoning_content（思维链），再输出 content
    （最终报告）。若 max_tokens 预算被推理吃光，content 会被截断为空。因此：
    1. max_tokens 放大，给 content 预留空间；
    2. 即使 content 为空，也绝不回退到 reasoning_content（那是思考过程，不是报告）；
    3. 兜底重试必须显式关闭 thinking（思考模式默认开启，只设 temperature 不会生效）。
    返回最终 content；若始终为空则返回空字符串（由调用方判失败）。
    """
    import openai

    client = openai.OpenAI(api_key=analyst.api_key, base_url=analyst.base_url)

    def _build_kwargs(use_thinking: bool) -> dict:
        kwargs = {
            'model': analyst.model,
            'messages': [
                {'role': 'system', 'content': system_hint},
                {'role': 'user', 'content': user_message},
            ],
            'max_tokens': max_tokens,
            'timeout': 300,
        }
        if use_thinking:
            kwargs['reasoning_effort'] = 'high'
            kwargs['extra_body'] = {'thinking': {'type': 'enabled'}}
        else:
            kwargs['temperature'] = analyst.temperature
            kwargs['extra_body'] = {'thinking': {'type': 'disabled'}}
        return kwargs

    # 第一次尝试：thinking high（与第1周生成路径一致，保留深度思考质量）
    try:
        content = client.chat.completions.create(**_build_kwargs(True)).choices[0].message.content
    except Exception as e:
        logger.error(f"[总结] 首次调用失败: {e}")
        content = None

    # content 为空：推理吃光预算，显式关闭 thinking 重试
    if not content:
        logger.warning("[总结] thinking 模式 content 为空（推理耗尽 token 预算），显式关闭 thinking 重试")
        try:
            content = client.chat.completions.create(**_build_kwargs(False)).choices[0].message.content
        except Exception as e:
            logger.error(f"[总结] 关闭 thinking 重试失败: {e}")
            content = None

    return content or ''


def generate_calendar_snapshot(trade_date: str, db=None) -> Optional[Dict[str, Any]]:
    """
    生成单个交易日的日历快照数据
    返回格式：{
        'up_count': int,
        'down_count': int,
        'total_amount': int (亿),
        'market_change_pct': float,
        'top_sector': str,
        'top_sector_chg': float,
        'is_final': bool,
        'tdx_status': str (如 '日红周蓝')
    }
    """
    if db is None:
        db = get_db()

    try:
        # 从base_data_daily获取涨跌家数和成交额
        base_doc = db['base_data_daily'].find_one(
            {'date': trade_date},
            {'_id': 0, 'up_count': 1, 'down_count': 1, 'total_amount': 1, 'is_final': 1}
        )

        if not base_doc:
            return None

        up_count = base_doc.get('up_count', 0) or 0
        down_count = base_doc.get('down_count', 0) or 0
        total_amount = base_doc.get('total_amount', 0) or 0
        total_amount_yi = int(total_amount / 100000000) if total_amount else 0

        # 从market_daily获取最强板块
        market_doc = db['market_daily'].find_one(
            {'trade_date': trade_date},
            {'_id': 0, 'new_high': 1, 'ai_analysis': 1, 'overview.indices': 1}
        )

        top_sector = None
        top_sector_chg = 0
        tdx_status = ''

        if market_doc:
            new_high = market_doc.get('new_high', {})
            clusters = new_high.get('clusters', [])
            if clusters:
                top_cluster = clusters[0]
                top_sector = top_cluster.get('industry', None)
                top_sector_chg = top_cluster.get('chg_pct') or top_cluster.get('chg') or 0

                # 如果还是0，尝试从sector_daily获取（优先880通达信代码）
                if top_sector_chg == 0 and top_sector:
                    try:
                        sector_doc = db['sector_basics'].find_one(
                            {'name': top_sector, 'code': {'$regex': '^880'}}, {'_id': 0, 'code': 1}
                        ) or db['sector_basics'].find_one({'name': top_sector}, {'_id': 0, 'code': 1})
                        if sector_doc and sector_doc.get('code'):
                            sec_data = db['sector_daily'].find_one(
                                {'stock_code': sector_doc['code'], 'trade_date': trade_date},
                                {'_id': 0, 'chg_pct': 1}
                            )
                            if sec_data and sec_data.get('chg_pct') is not None:
                                top_sector_chg = sec_data['chg_pct']
                    except Exception:
                        pass

            # 从overview.indices中获取平均股价的tdx_status
            indices = market_doc.get('overview', {}).get('indices', [])
            for idx in indices:
                if idx.get('code') == '880003' and idx.get('tdx_status'):
                    tdx_status = idx['tdx_status']
                    break

        # 从index_daily获取大盘涨跌幅（使用平均股价指数 880003）
        index_doc = db['index_daily'].find_one(
            {'stock_code': '880003', 'trade_date': trade_date},
            {'_id': 0, 'chg_pct': 1}
        )
        market_change_pct = index_doc.get('chg_pct', 0) if index_doc else 0

        snapshot = {
            'up_count': up_count,
            'down_count': down_count,
            'total_amount': total_amount_yi,
            'market_change_pct': market_change_pct,
            'top_sector': top_sector,
            'top_sector_chg': top_sector_chg,
            'is_final': base_doc.get('is_final', False),
            'tdx_status': tdx_status,
        }

        return snapshot
    except Exception as e:
        logger.error(f"生成日历快照失败 {trade_date}: {e}")
        return None


def generate_month_snapshots(year: int, month: int, db=None) -> int:
    """生成整月的日历快照，返回成功数量"""
    if db is None:
        db = get_db()

    import calendar as cal
    days_in_month = cal.monthrange(year, month)[1]
    success_count = 0

    for day in range(1, days_in_month + 1):
        date_str = f"{year}{month:02d}{day:02d}"
        if not is_workday(date_str):
            continue

        # 检查是否已有快照
        existing = db['base_data_daily'].find_one(
            {'date': date_str, 'calendar_snapshot': {'$exists': True}},
            {'_id': 0, 'date': 1}
        )
        if existing:
            success_count += 1
            continue

        snapshot = generate_calendar_snapshot(date_str, db)
        if snapshot:
            save_calendar_snapshot(date_str, snapshot, db)
            success_count += 1

    return success_count


def save_calendar_snapshot(trade_date: str, snapshot: dict, db=None):
    """保存日历快照到 base_data_daily"""
    if db is None:
        db = get_db()

    try:
        db['base_data_daily'].update_one(
            {'date': trade_date},
            {'$set': {'calendar_snapshot': snapshot}},
            upsert=True
        )
        logger.info(f"保存日历快照成功: {trade_date}")
    except Exception as e:
        logger.error(f"保存日历快照失败 {trade_date}: {e}")


# ========== 每日摘要 API ==========

@router.post("/generate-snapshots")
def generate_snapshots_api(
    year: int = Query(..., description="年份 YYYY"),
    month: int = Query(..., description="月份 1-12"),
):
    """生成指定月份的日历快照"""
    try:
        db = get_db()
        success_count = generate_month_snapshots(year, month, db)
        return {
            'success': True,
            'message': f'生成 {year}-{month:02d} 快照完成',
            'count': success_count
        }
    except Exception as e:
        logger.error(f"生成日历快照失败: {e}")
        raise HTTPException(status_code=500, detail=f"生成日历快照失败: {str(e)}")


@router.post("/clear-snapshots")
def clear_snapshots_api(
    year: int = Query(..., description="年份 YYYY"),
    month: int = Query(..., description="月份 1-12"),
):
    """清理指定月份的日历快照"""
    try:
        db = get_db()
        import calendar as cal
        days_in_month = cal.monthrange(year, month)[1]
        
        # 构建该月所有日期
        dates = []
        for day in range(1, days_in_month + 1):
            date_str = f"{year}{month:02d}{day:02d}"
            dates.append(date_str)
        
        # 清除 calendar_snapshot 字段
        result = db['base_data_daily'].update_many(
            {'date': {'$in': dates}, 'calendar_snapshot': {'$exists': True}},
            {'$unset': {'calendar_snapshot': ''}}
        )
        
        return {
            'success': True,
            'message': f'清理 {year}-{month:02d} 快照完成',
            'count': result.modified_count
        }
    except Exception as e:
        logger.error(f"清理日历快照失败: {e}")
        raise HTTPException(status_code=500, detail=f"清理日历快照失败: {str(e)}")


@router.get("/daily-summary")
def get_calendar_daily_summary(
    year: int = Query(..., description="年份 YYYY"),
    month: int = Query(..., description="月份 1-12"),
    index_code: str = Query(DEFAULT_INDEX_CODE, description="指数代码，默认平均股价")
):
    """
    获取日历每日摘要数据
    优先从快照读取，没有快照则实时计算
    """
    try:
        db = get_db()
        
        # 构建日期范围
        month_str = f"{year}{month:02d}"
        start_date = f"{month_str}01"
        if month == 12:
            end_date = f"{year + 1}0101"
        else:
            end_date = f"{year}{month + 1:02d}01"
        
        # 优先从快照读取
        snapshot_cursor = db['base_data_daily'].find(
            {
                'date': {'$gte': start_date, '$lt': end_date},
                'calendar_snapshot': {'$exists': True}
            },
            {
                '_id': 0,
                'date': 1,
                'calendar_snapshot': 1
            }
        ).sort('date', 1)
        
        snapshot_data = {}
        for doc in snapshot_cursor:
            snapshot_data[doc['date']] = doc.get('calendar_snapshot', {})

        # 查询所有日期的AI分析数据（推荐仓位 + 风险）
        ai_cursor = db['market_daily'].find(
            {'trade_date': {'$gte': start_date, '$lt': end_date}},
            {'_id': 0, 'trade_date': 1, 'ai_analysis': 1}
        )
        ai_data = {}
        for doc in ai_cursor:
            ai = doc.get('ai_analysis')
            if ai and ai.get('allocation_and_focus_model'):
                model = ai['allocation_and_focus_model']
                ai_data[doc['trade_date']] = {
                    'recommended_position': model.get('recommended_position_range', ''),
                    'market_risk_level': model.get('market_risk_level', ''),
                    'position_management_commentary': model.get('position_management_commentary', ''),
                    'core_target_sectors': model.get('core_target_sectors', []),
                }

        # 检查哪些日期没有快照
        all_dates_in_month = set()
        import calendar as cal
        days_in_month = cal.monthrange(year, month)[1]
        for day in range(1, days_in_month + 1):
            date_str = f"{year}{month:02d}{day:02d}"
            if is_workday(date_str):
                all_dates_in_month.add(date_str)
        
        missing_dates = all_dates_in_month - set(snapshot_data.keys())
        
        # 对没有快照的日期实时计算
        if missing_dates:
            # 查询base_data_daily
            base_cursor = db['base_data_daily'].find(
                {'date': {'$in': list(missing_dates)}},
                {
                    '_id': 0,
                    'date': 1,
                    'up_count': 1,
                    'down_count': 1,
                    'total_amount': 1,
                    'cr5_pct': 1,
                    'ma50_pct': 1,
                    'is_final': 1
                }
            )
            base_data = {doc['date']: doc for doc in base_cursor}
            
            # 查询market_daily
            market_cursor = db['market_daily'].find(
                {'trade_date': {'$in': list(missing_dates)}},
                {'_id': 0, 'trade_date': 1, 'new_high': 1, 'overview.indices': 1}
            )
            market_data = {doc['trade_date']: doc for doc in market_cursor}
            
            # 查询index_daily
            index_cursor = db['index_daily'].find(
                {'stock_code': index_code, 'trade_date': {'$in': list(missing_dates)}},
                {'_id': 0, 'trade_date': 1, 'close': 1, 'chg_pct': 1}
            )
            index_data = {}
            prev_close = None
            for doc in index_cursor:
                trade_date = doc['trade_date']
                close = doc.get('close', 0)
                if 'chg_pct' in doc and doc['chg_pct'] is not None:
                    market_change_pct = doc['chg_pct']
                elif prev_close and prev_close > 0:
                    market_change_pct = round((close - prev_close) / prev_close * 100, 2)
                else:
                    market_change_pct = 0
                index_data[trade_date] = market_change_pct
                prev_close = close
            
            # 计算缺失日期的数据
            for date_str in missing_dates:
                base = base_data.get(date_str, {})
                market = market_data.get(date_str, {})
                
                top_sector = None
                top_sector_chg = 0
                new_high = market.get('new_high', {})
                clusters = new_high.get('clusters', [])
                if clusters:
                    top_cluster = clusters[0]
                    top_sector = top_cluster.get('industry', None)
                    top_sector_chg = top_cluster.get('chg_pct') or top_cluster.get('chg') or 0
                    if top_sector_chg == 0 and top_sector:
                        try:
                            sector_doc = db['sector_basics'].find_one({'name': top_sector}, {'_id': 0, 'code': 1})
                            if sector_doc and sector_doc.get('code'):
                                sec_data = db['sector_daily'].find_one(
                                    {'stock_code': sector_doc['code'], 'trade_date': date_str},
                                    {'_id': 0, 'chg_pct': 1}
                                )
                                if sec_data and sec_data.get('chg_pct') is not None:
                                    top_sector_chg = sec_data['chg_pct']
                        except Exception:
                            pass
                
                total_amount = base.get('total_amount', 0)
                if total_amount:
                    total_amount = round(total_amount / 100000000, 0)
                
                market_change_pct = index_data.get(date_str, 0)
                
                # 计算is_final
                total_count = db['stock_daily'].count_documents({'trade_date': date_str, 'close': {'$gt': 0}})
                final_count = db['stock_daily'].count_documents({'trade_date': date_str, 'close': {'$gt': 0}, 'is_final': True})
                is_final = (final_count / total_count > 0.95) if total_count > 0 else False

                # 获取平均股价的tdx_status
                tdx_status = ''
                indices = market.get('overview', {}).get('indices', [])
                for idx in indices:
                    if idx.get('code') == '880003' and idx.get('tdx_status'):
                        tdx_status = idx['tdx_status']
                        break
                
                snapshot_data[date_str] = {
                    'up_count': base.get('up_count', 0),
                    'down_count': base.get('down_count', 0),
                    'total_amount': int(total_amount) if total_amount else 0,
                    'market_change_pct': market_change_pct,
                    'top_sector': top_sector,
                    'top_sector_chg': top_sector_chg,
                    'is_final': is_final,
                    'tdx_status': tdx_status,
                }
        
        # 构建结果
        result = []
        for day in range(1, days_in_month + 1):
            date_str = f"{year}{month:02d}{day:02d}"
            is_trading = is_workday(date_str)
            
            if is_trading and date_str in snapshot_data:
                snap = snapshot_data[date_str]
                ai = ai_data.get(date_str, {})
                result.append({
                    'date': date_str,
                    'day': day,
                    'is_trading_day': True,
                    'has_data': True,
                    'up_count': snap.get('up_count', 0),
                    'down_count': snap.get('down_count', 0),
                    'total_amount': snap.get('total_amount', 0),
                    'market_change_pct': snap.get('market_change_pct', 0),
                    'top_sector': snap.get('top_sector'),
                    'top_sector_chg': snap.get('top_sector_chg', 0),
                    'is_final': snap.get('is_final', False),
                    'tdx_status': snap.get('tdx_status', ''),
                    'recommended_position': ai.get('recommended_position', ''),
                    'market_risk_level': ai.get('market_risk_level', ''),
                    'position_management_commentary': ai.get('position_management_commentary', ''),
                    'core_target_sectors': ai.get('core_target_sectors', []),
                })
            else:
                result.append({
                    'date': date_str,
                    'day': day,
                    'is_trading_day': False,
                    'has_data': False,
                    'up_count': 0,
                    'down_count': 0,
                    'total_amount': 0,
                    'market_change_pct': 0,
                    'top_sector': None,
                    'top_sector_chg': 0,
                    'is_final': False,
                    'tdx_status': '',
                    'recommended_position': '',
                    'market_risk_level': '',
                    'position_management_commentary': '',
                    'core_target_sectors': [],
                })
        
        return {
            'success': True,
            'data': result,
            'year': year,
            'month': month,
            'index_code': index_code
        }
        
    except Exception as e:
        logger.error(f"获取日历数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取日历数据失败: {str(e)}")


@router.get("/latest-trade-date")
def get_latest_trade_date_api():
    """获取最新交易日"""
    try:
        db = get_db()
        doc = db['stock_daily'].find_one(
            {'close': {'$gt': 0}},
            sort=[('trade_date', -1)],
            projection={'trade_date': 1, '_id': 0}
        )
        latest = doc['trade_date'] if doc else None
        return {'success': True, 'latest_trade_date': latest}
    except Exception as e:
        logger.error(f"获取最新交易日失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取最新交易日失败: {str(e)}")


# ========== 周总结 API ==========

@router.get("/weekly-task/{task_id}")
def get_weekly_task(task_id: str):
    """查询周总结任务状态"""
    from app.data.task_manager import get_task_manager
    tm = get_task_manager()
    task = tm.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.get("/weekly-cached")
def get_weekly_cached(
    year: int = Query(..., description="年份 YYYY"),
    month: int = Query(..., description="月份 1-12"),
    week_index: int = Query(..., description="第几周（从1开始）"),
):
    """获取已缓存的周总结，不触发生成"""
    try:
        db = get_db()
        weeks = _get_month_weeks(year, month)
        week_days = weeks.get(week_index, [])
        if not week_days:
            raise HTTPException(status_code=400, detail=f"第{week_index}周没有交易日")

        cached = db['weekly_summary'].find_one(
            {'year': year, 'month': month, 'week_index': week_index},
            {'_id': 0}
        )
        if cached:
            return {
                'success': True,
                'week_index': week_index,
                'dates': week_days,
                'summary': cached['summary'],
                'generated_at': cached.get('generated_at'),
            }
        return {'success': True, 'week_index': week_index, 'dates': week_days, 'summary': None}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询缓存周总结失败: {e}")
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)[:200]}")


@router.post("/weekly-summary")
def get_weekly_summary(
    year: int = Query(..., description="年份 YYYY"),
    month: int = Query(..., description="月份 1-12"),
    week_index: int = Query(..., description="第几周（从1开始）"),
):
    """
    生成周总结（任务模式，防超时）
    先查缓存，有则直接返回；无则启动后台任务，返回 task_id 供轮询
    """
    try:
        db = get_db()

        # 先查缓存
        cache_key = {'year': year, 'month': month, 'week_index': week_index}
        cached = db['weekly_summary'].find_one(cache_key, {'_id': 0})
        if cached:
            return {
                'success': True,
                'task_id': None,
                'week_index': week_index,
                'is_cached': True,
                'summary': cached['summary'],
            }

        weeks = _get_month_weeks(year, month)
        week_days = weeks.get(week_index, [])
        if not week_days:
            raise HTTPException(status_code=400, detail=f"第{week_index}周没有交易日")

        cursor = db['market_daily'].find(
            {'trade_date': {'$in': week_days}},
            {'_id': 0, 'trade_date': 1, 'ai_analysis': 1, 'new_high': 1, 'low_position_sectors': 1}
        )
        ai_docs = {}
        new_high_docs = {}
        lps_docs = {}
        for doc in cursor:
            td = doc['trade_date']
            ai_docs[td] = doc.get('ai_analysis')
            new_high_docs[td] = doc.get('new_high', {})
            lps_docs[td] = doc.get('low_position_sectors', [])

        missing_days = [d for d in week_days if not ai_docs.get(d)]
        if missing_days:
            raise HTTPException(
                status_code=400,
                detail=f"第{week_index}周还有{len(missing_days)}天缺少AI分析数据: {', '.join(missing_days)}"
            )

        daily_analyses = _build_weekly_input_text(week_days, ai_docs, new_high_docs, lps_docs)

        # 检查是否有正在运行的周总结任务
        running_task = db['sync_tasks'].find_one(
            {'status': 'running', 'current_stock_name': {'$regex': '周总结|周度'}},
            sort=[('created_at', -1)]
        )
        
        if running_task:
            task_id = running_task['task_id']
            return {
                'success': True,
                'task_id': task_id,
                'week_index': week_index,
                'is_cached': False,
                'already_running': True,
            }
        
        # 创建后台任务
        from app.data.task_manager import get_task_manager
        tm = get_task_manager()
        steps = [
            {'name': f'生成第{week_index}周总结', 'key': 'weekly_summary', 'status': 'pending', 'total_count': 1, 'completed_count': 0, 'failed_count': 0, 'skipped_count': 0},
        ]
        task_id = tm.create_task_with_steps(steps, name='周总结')

        def _run():
            try:
                tm.start_step(task_id, 0)
                tm.update_task_progress(task_id, current_stock_name="调用 DeepSeek 生成周总结...")
                from app.server.api.deepseek_analyst import get_deepseek_analyst, is_deepseek_available
                analyst = get_deepseek_analyst()
                if not analyst.api_key:
                    tm.fail_task(task_id, "DEEPSEEK_API_KEY 未配置")
                    return

                # 检查时间窗口
                available, msg = is_deepseek_available()
                if not available:
                    tm.fail_task(task_id, msg)
                    return

                user_message = WEEKLY_SUMMARY_USER_TEMPLATE.format(daily_analyses=daily_analyses)

                content = _call_summary_llm(
                    analyst,
                    user_message,
                    WEEKLY_SUMMARY_SYSTEM_PROMPT,
                )

                if not content:
                    tm.fail_task(task_id, "DeepSeek 返回空内容")
                    return

                # 存入缓存
                db['weekly_summary'].update_one(
                    cache_key,
                    {'$set': {
                        'summary': content,
                        'dates': week_days,
                        'generated_at': _dt.now().isoformat(),
                    }},
                    upsert=True
                )

                tm.complete_step(task_id, 0, f"第{week_index}周总结生成完成")
                tm.complete_task(task_id, f"第{week_index}周总结生成完成")
            except Exception as e:
                logger.error(f"周总结任务失败: {e}")
                try:
                    tm.fail_task(task_id, str(e)[:200])
                except Exception:
                    pass

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        return {
            'success': True,
            'task_id': task_id,
            'week_index': week_index,
            'is_cached': False,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"启动周总结任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"启动失败: {str(e)[:200]}")


@router.get("/weekly-input-data")
def get_weekly_input_data(
    year: int = Query(..., description="年份 YYYY"),
    month: int = Query(..., description="月份 1-12"),
    week_index: int = Query(..., description="第几周（从1开始）"),
):
    """获取周总结传给DeepSeek的原始输入数据"""
    try:
        db = get_db()

        weeks = _get_month_weeks(year, month)
        week_days = weeks.get(week_index, [])
        if not week_days:
            raise HTTPException(status_code=400, detail=f"第{week_index}周没有交易日")

        cursor = db['market_daily'].find(
            {'trade_date': {'$in': week_days}},
            {'_id': 0, 'trade_date': 1, 'ai_analysis': 1, 'new_high': 1, 'low_position_sectors': 1}
        )
        ai_docs = {}
        new_high_docs = {}
        lps_docs = {}
        for doc in cursor:
            td = doc['trade_date']
            ai_docs[td] = doc.get('ai_analysis')
            new_high_docs[td] = doc.get('new_high', {})
            lps_docs[td] = doc.get('low_position_sectors', [])

        daily_analyses = _build_weekly_input_text(week_days, ai_docs, new_high_docs, lps_docs)

        # 完整的 user message（仅数据，指令在 system_message 中）
        full_message = WEEKLY_SUMMARY_USER_TEMPLATE.format(daily_analyses=daily_analyses)

        return {
            'success': True,
            'week_index': week_index,
            'dates': week_days,
            'system_message': WEEKLY_SUMMARY_SYSTEM_PROMPT,
            'user_message': full_message,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取周输入数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取周输入数据失败: {str(e)[:200]}")


@router.get("/week-status")
def get_week_status(
    year: int = Query(..., description="年份 YYYY"),
    month: int = Query(..., description="月份 1-12"),
):
    """
    获取指定月份每周的完成状态
    返回每周的交易日列表、是否有ai_analysis、以及周总结是否已生成
    """
    try:
        db = get_db()

        # 获取周分组（第一周包含上月月末凑整的工作日）
        weeks = _get_month_weeks(year, month)

        # 查询所有交易日的ai_analysis状态
        all_dates = [d for week_days in weeks.values() for d in week_days]
        cursor = db['market_daily'].find(
            {'trade_date': {'$in': all_dates}},
            {'_id': 0, 'trade_date': 1, 'ai_analysis': 1}
        )
        ai_set = set()
        for doc in cursor:
            ai = doc.get('ai_analysis')
            # 必须有有效的AI分析数据：有market_phase_diagnosis且source不是failed
            if (ai
                and ai.get('market_phase_diagnosis')
                and ai.get('source') != 'failed'
                and not ai.get('is_fallback')):
                ai_set.add(doc['trade_date'])

        # 查询每周总结是否已生成
        weekly_summary_set = set()
        for wk in sorted(weeks.keys()):
            # 使用与存储时相同的cache_key结构查询周总结
            cache_key = {'year': year, 'month': month, 'week_index': wk}
            has_summary = db['weekly_summary'].count_documents(cache_key) > 0
            if has_summary:
                weekly_summary_set.add(wk)

        # 构建结果
        result = []
        for wk in sorted(weeks.keys()):
            days = weeks[wk]
            has_all_ai = all(d in ai_set for d in days)
            has_summary = wk in weekly_summary_set
            result.append({
                'week_index': wk,
                'dates': days,
                'total_days': len(days),
                'ai_ready_count': sum(1 for d in days if d in ai_set),
                'is_complete': has_all_ai,
                'has_summary': has_summary,
            })

        return {
            'success': True,
            'year': year,
            'month': month,
            'weeks': result,
        }

    except Exception as e:
        logger.error(f"获取周状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取周状态失败: {str(e)[:200]}")


@router.get("/trading-days")
def get_trading_days(
    start_date: Optional[str] = Query(None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD")
):
    """获取所有交易日列表（从index_daily提取）"""
    try:
        db = get_db()
        
        # 从index_daily获取所有交易日（上证指数）
        query = {'stock_code': '000001', 'close': {'$gt': 0}}
        if start_date or end_date:
            query['trade_date'] = {}
            if start_date:
                query['trade_date']['$gte'] = start_date
            if end_date:
                query['trade_date']['$lte'] = end_date
        
        # 获取所有交易日
        dates = sorted(db['index_daily'].distinct('trade_date', query))
        
        return {
            'success': True,
            'data': dates,
            'total': len(dates)
        }
    except Exception as e:
        logger.error(f"获取交易日列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取交易日列表失败: {str(e)}")


# ========== 月总结 API ==========

@router.get("/monthly-cached")
def get_monthly_cached(
    year: int = Query(..., description="年份 YYYY"),
    month: int = Query(..., description="月份 1-12"),
):
    """获取已缓存的月总结"""
    try:
        db = get_db()
        cached = db['monthly_summary'].find_one(
            {'year': year, 'month': month},
            {'_id': 0}
        )
        if cached:
            return {
                'success': True,
                'year': year,
                'month': month,
                'summary': cached['summary'],
                'generated_at': cached.get('generated_at'),
            }
        return {'success': True, 'year': year, 'month': month, 'summary': None}

    except Exception as e:
        logger.error(f"查询缓存月总结失败: {e}")
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)[:200]}")


@router.post("/monthly-summary")
def get_monthly_summary(
    year: int = Query(..., description="年份 YYYY"),
    month: int = Query(..., description="月份 1-12"),
):
    """
    生成月总结（任务模式，防超时）
    先查缓存，有则直接返回；无则启动后台任务，返回 task_id 供轮询
    """
    try:
        db = get_db()

        # 先查缓存
        cache_key = {'year': year, 'month': month}
        cached = db['monthly_summary'].find_one(cache_key, {'_id': 0})
        if cached:
            return {
                'success': True,
                'task_id': None,
                'year': year,
                'month': month,
                'is_cached': True,
                'summary': cached['summary'],
                'generated_at': cached.get('generated_at'),
            }

        # 获取当月所有周总结
        week_docs = list(db['weekly_summary'].find(
            {'year': year, 'month': month},
            {'_id': 0, 'week_index': 1, 'dates': 1, 'summary': 1}
        ).sort('week_index', 1))

        if not week_docs:
            raise HTTPException(status_code=400, detail=f"{year}年{month}月暂无周总结数据，请先生成周总结")

        # 拼接各周总结
        weekly_parts = []
        for doc in week_docs:
            wk = doc['week_index']
            dates = doc.get('dates', [])
            date_range = f"{dates[0][:4]}-{dates[0][4:6]}-{dates[0][6:]}" if dates else ''
            date_range_end = f"{dates[-1][:4]}-{dates[-1][4:6]}-{dates[-1][6:]}" if dates else ''
            weekly_parts.append(f"【第{wk}周 ({date_range} ~ {date_range_end})】")
            weekly_parts.append(doc.get('summary', ''))
            weekly_parts.append("")

        weekly_summaries = '\n'.join(weekly_parts)

        # 计算本月大盘指数涨跌幅（基准：上月末收盘价）
        all_dates = sorted(db['index_daily'].distinct('trade_date'))
        month_dates = [d for d in all_dates if d.startswith(f"{year}{month:02d}")]
        
        # 找上月末最后一天交易日
        prev_month = month - 1 if month > 1 else 12
        prev_year = year if month > 1 else year - 1
        prev_month_str = f"{prev_year}{prev_month:02d}"
        prev_month_dates = [d for d in all_dates if d.startswith(prev_month_str)]
        
        index_line = ''
        if month_dates and prev_month_dates:
            base_day = prev_month_dates[-1]  # 上月末收盘价作为基准
            last_day = month_dates[-1]  # 本月末收盘价
            
            base_docs = list(db['index_daily'].find(
                {'trade_date': base_day},
                {'_id': 0, 'stock_code': 1, 'close': 1}
            ))
            last_docs = list(db['index_daily'].find(
                {'trade_date': last_day},
                {'_id': 0, 'stock_code': 1, 'close': 1}
            ))
            base_map = {d['stock_code']: d.get('close', 0) for d in base_docs}
            last_map = {d['stock_code']: d.get('close', 0) for d in last_docs}

            idx_names = {}
            for b in db['index_basics'].find({'is_disable': {'$ne': True}}, {'_id': 0, 'code': 1, 'name': 1}):
                idx_names[b['code']] = b['name']

            idx_parts = []
            for code in last_map:
                base = base_map.get(code, 0)
                last = last_map.get(code, 0)
                if base and last:
                    chg = round((last / base - 1) * 100, 2)
                    name = idx_names.get(code, code)
                    idx_parts.append(f"{name} {chg:+.2f}%")
            if idx_parts:
                date_range = f"{base_day[:4]}-{base_day[4:6]}-{base_day[6:]}~{last_day[:4]}-{last_day[4:6]}-{last_day[6:]}"
                index_line = f"【本月大盘指数涨跌幅({date_range})】{', '.join(idx_parts)}"

        # 检查是否有正在运行的月总结任务
        running_task = db['sync_tasks'].find_one(
            {'status': 'running', 'current_stock_name': {'$regex': '月总结|月度'}},
            sort=[('created_at', -1)]
        )
        
        if running_task:
            task_id = running_task['task_id']
            return {
                'success': True,
                'task_id': task_id,
                'year': year,
                'month': month,
                'is_cached': False,
                'already_running': True,
            }
        
        # 创建后台任务
        from app.data.task_manager import get_task_manager
        tm = get_task_manager()
        steps = [
            {'name': f'生成{year}年{month}月总结', 'key': 'monthly_summary', 'status': 'pending', 'total_count': 1, 'completed_count': 0, 'failed_count': 0, 'skipped_count': 0},
        ]
        task_id = tm.create_task_with_steps(steps, name='月总结')

        def _run():
            try:
                tm.start_step(task_id, 0)
                tm.update_task_progress(task_id, current_stock_name="调用 DeepSeek 生成月总结...")
                from app.server.api.deepseek_analyst import get_deepseek_analyst, is_deepseek_available
                analyst = get_deepseek_analyst()
                if not analyst.api_key:
                    tm.fail_task(task_id, "DEEPSEEK_API_KEY 未配置")
                    return

                # 检查时间窗口
                available, msg = is_deepseek_available()
                if not available:
                    tm.fail_task(task_id, msg)
                    return

                # 组装输入：大盘指数 + 周总结
                full_input = ''
                if index_line:
                    full_input = index_line + '\n\n'
                full_input += weekly_summaries
                user_message = MONTHLY_SUMMARY_USER_TEMPLATE.format(weekly_summaries=full_input)

                content = _call_summary_llm(
                    analyst,
                    user_message,
                    MONTHLY_SUMMARY_SYSTEM_PROMPT,
                )

                if not content:
                    tm.fail_task(task_id, "DeepSeek 返回空内容")
                    return

                # 存入缓存
                db['monthly_summary'].update_one(
                    cache_key,
                    {'$set': {
                        'summary': content,
                        'week_count': len(week_docs),
                        'generated_at': _dt.now().isoformat(),
                    }},
                    upsert=True
                )

                tm.complete_step(task_id, 0, f"{year}年{month}月总结生成完成")
                tm.complete_task(task_id, f"{year}年{month}月总结生成完成")
            except Exception as e:
                logger.error(f"月总结任务失败: {e}")
                try:
                    tm.fail_task(task_id, str(e)[:200])
                except Exception:
                    pass

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        return {
            'success': True,
            'task_id': task_id,
            'message': f'{year}年{month}月总结生成任务已启动',
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"启动月总结任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"启动失败: {str(e)[:200]}")


@router.get("/monthly-task/{task_id}")
def get_monthly_task(task_id: str):
    """查询月总结任务状态"""
    from app.data.task_manager import get_task_manager
    tm = get_task_manager()
    task = tm.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.get("/monthly-input-data")
def get_monthly_input_data(
    year: int = Query(..., description="年份 YYYY"),
    month: int = Query(..., description="月份 1-12"),
):
    """获取月总结传给DeepSeek的原始输入数据"""
    try:
        db = get_db()

        # 获取该月所有交易日
        all_dates = sorted(db['stock_daily'].distinct('trade_date'))
        month_dates = [d for d in all_dates if d.startswith(f"{year}{month:02d}")]
        
        if not month_dates:
            raise HTTPException(status_code=400, detail=f"{year}年{month}月没有交易日")

        # 查询 weekly_summary 数据
        week_docs = list(db['weekly_summary'].find(
            {'year': year, 'month': month},
            {'_id': 0, 'week_index': 1, 'dates': 1, 'summary': 1}
        ).sort('week_index', 1))

        if not week_docs:
            raise HTTPException(status_code=400, detail=f"{year}年{month}月暂无周总结数据，请先生成周总结")

        # 拼接各周总结
        weekly_parts = []
        for doc in week_docs:
            wk = doc['week_index']
            dates = doc.get('dates', [])
            date_range = f"{dates[0][:4]}-{dates[0][4:6]}-{dates[0][6:]}" if dates else ''
            date_range_end = f"{dates[-1][:4]}-{dates[-1][4:6]}-{dates[-1][6:]}" if dates else ''
            weekly_parts.append(f"【第{wk}周 ({date_range} ~ {date_range_end})】")
            weekly_parts.append(doc.get('summary', ''))
            weekly_parts.append("")

        weekly_summaries = '\n'.join(weekly_parts)

        # 计算本月大盘指数涨跌幅（基准：上月末收盘价）
        all_dates = sorted(db['index_daily'].distinct('trade_date'))
        month_dates_idx = [d for d in all_dates if d.startswith(f"{year}{month:02d}")]
        
        # 找上月末最后一天交易日
        prev_month = month - 1 if month > 1 else 12
        prev_year = year if month > 1 else year - 1
        prev_month_str = f"{prev_year}{prev_month:02d}"
        prev_month_dates = [d for d in all_dates if d.startswith(prev_month_str)]
        
        index_line = ''
        if month_dates_idx and prev_month_dates:
            base_day = prev_month_dates[-1]  # 上月末收盘价作为基准
            last_day = month_dates_idx[-1]  # 本月末收盘价
            
            base_docs = list(db['index_daily'].find(
                {'trade_date': base_day},
                {'_id': 0, 'stock_code': 1, 'close': 1}
            ))
            last_docs = list(db['index_daily'].find(
                {'trade_date': last_day},
                {'_id': 0, 'stock_code': 1, 'close': 1}
            ))
            base_map = {d['stock_code']: d.get('close', 0) for d in base_docs}
            last_map = {d['stock_code']: d.get('close', 0) for d in last_docs}

            idx_names = {}
            for b in db['index_basics'].find({'is_disable': {'$ne': True}}, {'_id': 0, 'code': 1, 'name': 1}):
                idx_names[b['code']] = b['name']

            idx_parts = []
            for code in last_map:
                base = base_map.get(code, 0)
                last = last_map.get(code, 0)
                if base and last:
                    chg = round((last / base - 1) * 100, 2)
                    name = idx_names.get(code, code)
                    idx_parts.append(f"{name} {chg:+.2f}%")
            if idx_parts:
                date_range = f"{base_day[:4]}-{base_day[4:6]}-{base_day[6:]}~{last_day[:4]}-{last_day[4:6]}-{last_day[6:]}"
                index_line = f"【本月大盘指数涨跌幅({date_range})】{', '.join(idx_parts)}"

        # 完整的 user message（含 prompt）
        full_input = ''
        if index_line:
            full_input = index_line + '\n\n'
        full_input += weekly_summaries
        full_message = MONTHLY_SUMMARY_USER_TEMPLATE.format(weekly_summaries=full_input)

        return {
            'success': True,
            'year': year,
            'month': month,
            'dates': month_dates,
            'system_message': MONTHLY_SUMMARY_SYSTEM_PROMPT,
            'user_message': full_message,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取月输入数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取月输入数据失败: {str(e)[:200]}")


# ==================== 月度重算 ====================

@router.post("/recalculate-month")
def recalculate_month_api(
    year: int = Query(..., description="年份 YYYY"),
    month: int = Query(..., description="月份 1-12"),
):
    """启动月度重算任务"""
    try:
        from app.server.repositories import get_task_repo
        task_repo = get_task_repo()

        running_task = task_repo.collection.find_one(
            {'status': 'running', 'current_stock_name': {'$regex': '重算'}},
            sort=[('created_at', -1)]
        )

        if running_task:
            return {
                'success': True,
                'task_id': running_task['task_id'],
                'message': '任务正在运行中，共用task_id',
                'already_running': True
            }

        from app.server.orchestrators import get_monthly_recalc_orchestrator
        orchestrator = get_monthly_recalc_orchestrator()
        task_id = orchestrator.execute(year, month)

        return {
            'success': True,
            'task_id': task_id,
            'message': f'{year}年{month}月重算任务已启动'
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"启动月度重算失败: {e}")
        raise HTTPException(status_code=500, detail=f"启动失败: {str(e)[:200]}")


@router.get("/task/{task_id}")
def get_task_status(task_id: str):
    """通用任务状态查询接口"""
    db = get_db()
    
    task = db['sync_tasks'].find_one({'task_id': task_id})
    if not task:
        return {'status': 'not_found', 'task_id': task_id}
    
    return {
        'status': task.get('status', 'idle'),
        'task_id': task.get('task_id'),
        'name': task.get('name', ''),
        'current_step': task.get('current_step'),
        'current_stock_name': task.get('current_stock_name', ''),
        'completed_count': task.get('completed_count', 0),
        'total_count': task.get('total_count', 0),
        'message': task.get('message', ''),
        'error': task.get('error', ''),
        'steps': task.get('steps', []),
    }


# ==================== AI分析补全 ====================

@router.post("/fill-ai-analysis")
def fill_ai_analysis_api(
    year: int = Query(..., description="年份 YYYY"),
    month: int = Query(..., description="月份 1-12"),
):
    """启动AI分析补全任务"""
    try:
        from app.data.task_manager import get_task_manager
        tm = get_task_manager()
        db = get_db()
        
        # 检查是否有正在运行的AI分析补全任务
        running_task = db['sync_tasks'].find_one(
            {'status': 'running', 'current_stock_name': {'$regex': 'AI分析|fill'}},
            sort=[('created_at', -1)]
        )
        
        if running_task:
            task_id = running_task['task_id']
            return {
                'success': True,
                'task_id': task_id,
                'message': '任务正在运行中，共用task_id',
                'already_running': True
            }
        
        # 查询缺失AI分析的日期数
        all_dates_list = sorted(db['stock_daily'].distinct('trade_date'))
        month_dates_list = [d for d in all_dates_list if d.startswith(f"{year}{month:02d}")]
        missing_count = 0
        for date_str in month_dates_list:
            doc_check = db['market_daily'].find_one({'trade_date': date_str}, {'_id': 0, 'ai_analysis': 1})
            if not doc_check or not doc_check.get('ai_analysis'):
                missing_count += 1
        
        steps = [
            {'name': f'AI分析补全', 'key': 'fill_ai', 'status': 'pending', 'total_count': max(1, missing_count), 'completed_count': 0, 'failed_count': 0, 'skipped_count': 0},
        ]
        task_id = tm.create_task_with_steps(steps, name='AI分析补全')
        
        thread = threading.Thread(
            target=_run_fill_ai_task,
            args=(task_id, year, month),
            daemon=True
        )
        thread.start()
        
        return {
            'success': True,
            'task_id': task_id,
            'message': f'{year}年{month}月AI分析补全任务已启动'
        }
    except Exception as e:
        logger.error(f"启动AI分析补全失败: {e}")
        raise HTTPException(status_code=500, detail=f"启动失败: {str(e)[:200]}")


@router.get("/running-tasks")
def get_running_tasks():
    """获取所有正在运行的任务（用于页面恢复轮询）"""
    try:
        db = get_db()
        running_tasks = list(db['sync_tasks'].find(
            {'status': 'running'},
            {'_id': 0, 'task_id': 1, 'name': 1, 'current_step': 1, 'current_stock_name': 1, 'created_at': 1}
        ).sort('created_at', -1))
        
        return {
            'success': True,
            'tasks': running_tasks
        }
    except Exception as e:
        logger.error(f"获取运行中任务失败: {e}")
        return {'success': False, 'tasks': []}