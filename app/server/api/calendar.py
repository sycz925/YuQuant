"""
日历复盘API - 提供日历视图所需的聚合数据
数据来源：base_data_daily + market_daily + index_daily
支持快照缓存，避免重复计算
业务逻辑已迁移至 services/calendar_service.py
"""
import logging
import threading
from typing import Optional
from datetime import datetime as _dt

from fastapi import APIRouter, HTTPException, Query

from app.server.repositories import (
    get_market_review_repo, get_task_repo, get_weekly_summary_repo, get_monthly_summary_repo, get_index_repo,
)
from app.server.services.calendar_service import (
    _get_month_weeks,
    _build_weekly_input_text,
    _run_fill_ai_task,
    generate_month_snapshots,
    clear_calendar_snapshots,
    get_calendar_daily_summary as build_calendar_daily_summary,
    DEFAULT_INDEX_CODE,
    WEEKLY_SUMMARY_SYSTEM_PROMPT,
    WEEKLY_SUMMARY_USER_TEMPLATE,
    MONTHLY_SUMMARY_SYSTEM_PROMPT,
    MONTHLY_SUMMARY_USER_TEMPLATE,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/calendar", tags=["日历复盘"])


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


# ========== 每日摘要 API ==========

@router.post("/generate-snapshots")
def generate_snapshots_api(
    year: int = Query(..., description="年份 YYYY"),
    month: int = Query(..., description="月份 1-12"),
):
    """生成指定月份的日历快照"""
    try:
        success_count = generate_month_snapshots(year, month)
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
        count = clear_calendar_snapshots(year, month)
        return {
            'success': True,
            'message': f'清理 {year}-{month:02d} 快照完成',
            'count': count
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
        return build_calendar_daily_summary(year, month, index_code)
    except Exception as e:
        logger.error(f"获取日历数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取日历数据失败: {str(e)}")


@router.get("/latest-trade-date")
def get_latest_trade_date_api():
    """获取最新交易日"""
    try:
        latest = get_market_review_repo().get_latest_stock_date()
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
        weeks = _get_month_weeks(year, month)
        week_days = weeks.get(week_index, [])
        if not week_days:
            raise HTTPException(status_code=400, detail=f"第{week_index}周没有交易日")

        cached = get_weekly_summary_repo().get_by_key(year, month, week_index)
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
        weekly_repo = get_weekly_summary_repo()
        market_repo = get_market_review_repo()

        # 先查缓存
        cached = weekly_repo.get_by_key(year, month, week_index)
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

        docs = market_repo.get_cached_multi(week_days,
            {'_id': 0, 'trade_date': 1, 'ai_analysis': 1, 'new_high': 1, 'low_position_sectors': 1})
        ai_docs = {}
        new_high_docs = {}
        lps_docs = {}
        for doc in docs:
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
        running_task = get_task_repo().find_running_by_stock_name('周总结|周度')
        
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
                weekly_repo.upsert(year, month, week_index, {
                    'summary': content,
                    'dates': week_days,
                    'generated_at': _dt.now().isoformat(),
                })

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
        weeks = _get_month_weeks(year, month)
        week_days = weeks.get(week_index, [])
        if not week_days:
            raise HTTPException(status_code=400, detail=f"第{week_index}周没有交易日")

        docs = get_market_review_repo().get_cached_multi(week_days,
            {'_id': 0, 'trade_date': 1, 'ai_analysis': 1, 'new_high': 1, 'low_position_sectors': 1})
        ai_docs = {}
        new_high_docs = {}
        lps_docs = {}
        for doc in docs:
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
        # 获取周分组（第一周包含上月月末凑整的工作日）
        weeks = _get_month_weeks(year, month)

        # 查询所有交易日的ai_analysis状态
        all_dates = [d for week_days in weeks.values() for d in week_days]
        docs = get_market_review_repo().get_cached_multi(all_dates,
            {'_id': 0, 'trade_date': 1, 'ai_analysis': 1})
        ai_set = set()
        for doc in docs:
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
            if get_weekly_summary_repo().has_summary(year, month, wk):
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
        # 从index_daily获取所有交易日（上证指数）
        query = {'stock_code': '000001', 'close': {'$gt': 0}}
        if start_date or end_date:
            query['trade_date'] = {}
            if start_date:
                query['trade_date']['$gte'] = start_date
            if end_date:
                query['trade_date']['$lte'] = end_date
        
        # 获取所有交易日
        dates = get_market_review_repo().get_index_trade_dates(query)
        
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
        cached = get_monthly_summary_repo().get_by_key(year, month)
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
        monthly_repo = get_monthly_summary_repo()

        # 先查缓存
        cached = monthly_repo.get_by_key(year, month)
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
        week_docs = get_weekly_summary_repo().get_range(year, month)

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
        all_dates = get_market_review_repo().get_index_trade_dates({})
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
            
            base_docs = get_market_review_repo().get_index_daily_by_date(base_day)
            last_docs = get_market_review_repo().get_index_daily_by_date(last_day)
            base_map = {d['stock_code']: d.get('close', 0) for d in base_docs}
            last_map = {d['stock_code']: d.get('close', 0) for d in last_docs}

            idx_names = {b['code']: b['name'] for b in get_index_repo().get_enabled_list()}

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
        running_task = get_task_repo().find_running_by_stock_name('月总结|月度')
        
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
                monthly_repo.upsert(year, month, {
                    'summary': content,
                    'week_count': len(week_docs),
                    'generated_at': _dt.now().isoformat(),
                })

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
        # 获取该月所有交易日
        all_dates = get_market_review_repo().get_stock_trade_dates()
        month_dates = [d for d in all_dates if d.startswith(f"{year}{month:02d}")]
        
        if not month_dates:
            raise HTTPException(status_code=400, detail=f"{year}年{month}月没有交易日")

        # 查询 weekly_summary 数据
        week_docs = get_weekly_summary_repo().get_range(year, month)

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
        all_dates = get_market_review_repo().get_index_trade_dates({})
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
            
            base_docs = get_market_review_repo().get_index_daily_by_date(base_day)
            last_docs = get_market_review_repo().get_index_daily_by_date(last_day)
            base_map = {d['stock_code']: d.get('close', 0) for d in base_docs}
            last_map = {d['stock_code']: d.get('close', 0) for d in last_docs}

            idx_names = {b['code']: b['name'] for b in get_index_repo().get_enabled_list()}

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
    task = get_task_repo().get_by_task_id(task_id)
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
        # 检查是否有正在运行的AI分析补全任务
        running_task = get_task_repo().find_running_by_stock_name('AI分析|fill')
        
        if running_task:
            task_id = running_task['task_id']
            return {
                'success': True,
                'task_id': task_id,
                'message': '任务正在运行中，共用task_id',
                'already_running': True
            }
        
        # 查询缺失AI分析的日期数
        all_dates_list = get_market_review_repo().get_stock_trade_dates()
        month_dates_list = [d for d in all_dates_list if d.startswith(f"{year}{month:02d}")]
        missing_count = 0
        for date_str in month_dates_list:
            doc_check = get_market_review_repo().get_cached(date_str, 'ai_analysis')
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
        running_tasks = get_task_repo().get_running_tasks()
        
        return {
            'success': True,
            'tasks': running_tasks
        }
    except Exception as e:
        logger.error(f"获取运行中任务失败: {e}")
        return {'success': False, 'tasks': []}