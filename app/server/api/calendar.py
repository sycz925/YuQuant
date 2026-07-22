"""
日历复盘API - 提供日历视图所需的聚合数据
数据来源：base_data_daily + market_daily + index_daily
支持快照缓存，避免重复计算
"""
import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query
from app.data.db import get_db
from app.data.holidays import is_workday

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/calendar", tags=["日历复盘"])

# 默认大盘指数代码（上证指数）
DEFAULT_INDEX_CODE = "000001"


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
        'is_final': bool
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
            {'_id': 0, 'new_high': 1, 'ai_analysis': 1}
        )
        
        top_sector = None
        top_sector_chg = 0
        
        if market_doc:
            new_high = market_doc.get('new_high', {})
            clusters = new_high.get('clusters', [])
            if clusters:
                top_cluster = clusters[0]
                top_sector = top_cluster.get('industry', None)
                top_sector_chg = top_cluster.get('chg_pct') or top_cluster.get('chg') or 0
                
                # 如果还是0，尝试从sector_daily获取
                if top_sector_chg == 0 and top_sector:
                    try:
                        sector_doc = db['sector_basics'].find_one({'name': top_sector}, {'_id': 0, 'code': 1})
                        if sector_doc and sector_doc.get('code'):
                            sec_data = db['sector_daily'].find_one(
                                {'stock_code': sector_doc['code'], 'trade_date': trade_date},
                                {'_id': 0, 'chg_pct': 1}
                            )
                            if sec_data and sec_data.get('chg_pct') is not None:
                                top_sector_chg = sec_data['chg_pct']
                    except Exception:
                        pass
        
        # 从index_daily获取大盘涨跌幅（直接使用预计算的chg_pct）
        index_doc = db['index_daily'].find_one(
            {'stock_code': DEFAULT_INDEX_CODE, 'trade_date': trade_date},
            {'_id': 0, 'chg_pct': 1}
        )
        
        market_change_pct = index_doc.get('chg_pct', 0) if index_doc else 0
        
        # 计算is_final比例
        total_count = db['stock_daily'].count_documents({'trade_date': trade_date, 'close': {'$gt': 0}})
        final_count = db['stock_daily'].count_documents({'trade_date': trade_date, 'close': {'$gt': 0}, 'is_final': True})
        is_final = (final_count / total_count > 0.95) if total_count > 0 else False
        
        # 从AI分析中提取核心目标板块
        core_target_sectors = []
        if market_doc:
            ai = market_doc.get('ai_analysis', {})
            if ai and ai.get('allocation_and_focus_model'):
                core_target_sectors = ai['allocation_and_focus_model'].get('core_target_sectors', [])

        return {
            'up_count': up_count,
            'down_count': down_count,
            'total_amount': total_amount_yi,
            'market_change_pct': market_change_pct,
            'top_sector': top_sector,
            'top_sector_chg': top_sector_chg,
            'is_final': is_final,
            'core_target_sectors': core_target_sectors,
        }
        
    except Exception as e:
        logger.error(f"生成日历快照失败 {trade_date}: {e}")
        return None


def save_calendar_snapshot(trade_date: str, snapshot: Dict[str, Any], db=None):
    """保存日历快照到base_data_daily"""
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


@router.get("/daily-summary")
def get_calendar_daily_summary(
    year: int = Query(..., description="年份 YYYY"),
    month: int = Query(..., description="月份 1-12"),
    index_code: str = Query(DEFAULT_INDEX_CODE, description="指数代码，默认上证指数")
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
                {'_id': 0, 'trade_date': 1, 'new_high': 1}
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
                
                snapshot_data[date_str] = {
                    'up_count': base.get('up_count', 0),
                    'down_count': base.get('down_count', 0),
                    'total_amount': int(total_amount) if total_amount else 0,
                    'market_change_pct': market_change_pct,
                    'top_sector': top_sector,
                    'top_sector_chg': top_sector_chg,
                    'is_final': is_final,
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


def _get_month_weeks(year: int, month: int) -> dict:
    """
    获取月份的周分组。规则：周的最后一个交易日在哪个月，这一周就归哪个月。
    跨月的周只在最后交易日所在的月份显示，不重复。
    返回 {week_index: [当月内的date_str, ...], ...}
    """
    import calendar as cal
    from collections import defaultdict, OrderedDict
    from datetime import datetime as _dt, timedelta

    days_in_month = cal.monthrange(year, month)[1]

    # 收集覆盖范围内的所有工作日（从1号所在周一到月末最后交易日所在周五）
    first_day = _dt(year, month, 1)
    first_monday = first_day - timedelta(days=first_day.isoweekday() - 1)
    last_day = _dt(year, month, days_in_month)
    wd = last_day.isoweekday()
    if wd <= 4:
        cover_end = last_day + timedelta(days=5 - wd)
    elif wd == 5:
        cover_end = last_day
    else:
        cover_end = last_day - timedelta(days=wd - 5)

    def _collect_range(start, end):
        result = []
        d = start
        while d <= end:
            ds = d.strftime('%Y%m%d')
            if d.isoweekday() <= 5 and is_workday(ds):
                result.append(ds)
            d += timedelta(days=1)
        return result

    all_in_range = _collect_range(first_monday, cover_end)

    # 按周一分组
    def _week_key(date_str):
        d = _dt.strptime(date_str, '%Y%m%d')
        monday = d - timedelta(days=d.isoweekday() - 1)
        return monday.strftime('%Y%m%d')

    weeks_raw = defaultdict(list)
    for ds in all_in_range:
        weeks_raw[_week_key(ds)].append(ds)

    # 只保留最后一个交易日在当月的周，展示完整一周（含跨月日期）
    month_prefix = f"{year}{month:02d}"
    result = OrderedDict()
    idx = 0
    for mk in sorted(weeks_raw.keys()):
        week_days = weeks_raw[mk]
        last_trading = week_days[-1]
        if not last_trading.startswith(month_prefix):
            continue  # 最后交易日在其他月，跳过
        idx += 1
        result[idx] = week_days

    return result


def _build_weekly_input_text(week_days: list, ai_docs: dict,
                             new_high_docs: dict = None, lps_docs: dict = None) -> str:
    """构建发送给 DeepSeek 的周总结输入文本"""
    if new_high_docs is None:
        new_high_docs = {}
    if lps_docs is None:
        lps_docs = {}

    # 预加载 sector_basics: name -> code（同名保留所有，code -> name 直接构建）
    from app.data.db import get_db
    db = get_db()
    sector_name_to_code = {}
    code_to_name_direct = {}
    for s in db['sector_basics'].find(
        {'is_disable': {'$ne': True}}, {'_id': 0, 'code': 1, 'name': 1}
    ):
        sector_name_to_code[s['name']] = s['code']
        code_to_name_direct[s['code']] = s['name']

    # 收集所有需要查的板块名和日期，批量查 sector_daily
    all_sector_names = set()
    for date_str in week_days:
        ai = ai_docs.get(date_str)
        if ai:
            alloc = ai.get('allocation_and_focus_model', {})
            for name in alloc.get('core_target_sectors', []):
                all_sector_names.add(name)
        nh = new_high_docs.get(date_str, {})
        for c in nh.get('clusters', []):
            if c.get('industry'):
                all_sector_names.add(c['industry'])
        for s in lps_docs.get(date_str, []):
            if s.get('name'):
                all_sector_names.add(s['name'])

    # 获取周涨幅（周一收盘到周五收盘）
    index_line = ''
    if len(week_days) >= 2:
        first_day = week_days[0]
        last_day = week_days[-1]
        first_docs = list(db['index_daily'].find(
            {'trade_date': first_day},
            {'_id': 0, 'stock_code': 1, 'close': 1}
        ))
        last_docs = list(db['index_daily'].find(
            {'trade_date': last_day},
            {'_id': 0, 'stock_code': 1, 'close': 1}
        ))
        first_map = {d['stock_code']: d.get('close', 0) for d in first_docs}
        last_map = {d['stock_code']: d.get('close', 0) for d in last_docs}

        idx_names = {}
        for b in db['index_basics'].find({'is_disable': {'$ne': True}}, {'_id': 0, 'code': 1, 'name': 1}):
            idx_names[b['code']] = b['name']

        idx_parts = []
        for code in last_map:
            f = first_map.get(code, 0)
            l = last_map.get(code, 0)
            if f and l:
                chg = round((l / f - 1) * 100, 2)
                name = idx_names.get(code, code)
                idx_parts.append(f"{name}{chg:+.2f}%")
        if idx_parts:
            date_range = f"{first_day[:4]}-{first_day[4:6]}-{first_day[6:]}~{last_day[:4]}-{last_day[4:6]}-{last_day[6:]}"
            index_line = f"【本周大盘指数涨跌幅({date_range})】{', '.join(idx_parts)}"

    # 批量查 sector_daily 的 chg_pct
    sector_chg_map = {}  # {(name, date): chg_pct}
    if all_sector_names:
        codes = [sector_name_to_code[n] for n in all_sector_names if n in sector_name_to_code]
        if codes:
            cursor = db['sector_daily'].find(
                {'stock_code': {'$in': codes}, 'trade_date': {'$in': week_days}},
                {'_id': 0, 'stock_code': 1, 'trade_date': 1, 'chg_pct': 1}
            )
            for doc in cursor:
                name = code_to_name_direct.get(doc['stock_code'], doc['stock_code'])
                sector_chg_map[(name, doc['trade_date'])] = doc.get('chg_pct', 0) or 0

    # 批量查每天 RPS>85 的板块（用于发现偷偷变强的方向）
    rps_strong_map = {}  # {date: {'rps_10': [(name, rps, chg), ...], ...}}
    for date_str in week_days:
        strong = {}
        for rps_key in ['rps_10', 'rps_20', 'rps_50']:
            cursor = db['sector_daily'].find(
                {'trade_date': date_str, rps_key: {'$gt': 85}},
                {'_id': 0, 'stock_code': 1, rps_key: 1, 'chg_pct': 1}
            )
            items = []
            for doc in cursor:
                name = code_to_name_direct.get(doc['stock_code'], doc['stock_code'])
                rps_val = doc.get(rps_key, 0) or 0
                chg = doc.get('chg_pct', 0) or 0
                items.append((name, rps_val, chg))
            items.sort(key=lambda x: -x[1])
            strong[rps_key] = items[:15]
        rps_strong_map[date_str] = strong

    parts = []
    if index_line:
        parts.append(index_line)
        parts.append("")
    for date_str in week_days:
        ai = ai_docs.get(date_str)
        if not ai:
            continue
        formatted = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        parts.append(f"【{formatted}】")
        parts.append(f"市场阶段诊断: {ai.get('market_phase_diagnosis', '无')}")
        parts.append(f"行业集群评估: {ai.get('industry_cluster_evaluation', '无')}")
        advices = ai.get('execution_strategy_advice', [])
        if advices:
            parts.append(f"执行策略建议: {'; '.join(advices)}")
        alloc = ai.get('allocation_and_focus_model', {})
        if alloc:
            core_sectors = alloc.get('core_target_sectors', [])
            if core_sectors:
                nh = new_high_docs.get(date_str, {})
                clusters = nh.get('clusters', [])
                cluster_map = {c['industry']: c for c in clusters if c.get('industry')}
                lps = lps_docs.get(date_str, [])
                lps_map = {s['name']: s for s in lps if s.get('name')}
                sector_details = []
                for s in core_sectors:
                    chg = sector_chg_map.get((s, date_str), 0)
                    c = cluster_map.get(s)
                    lps_item = lps_map.get(s)
                    nh250 = c.get('count', 0) if c else 0
                    nh20 = lps_item.get('count', 0) if lps_item else 0
                    parts_str = f"{s}(涨{chg:+.1f}%)"
                    if nh250:
                        parts_str += f",250日新高{nh250}只"
                    if nh20:
                        parts_str += f",20日新高{nh20}只"
                    sector_details.append(parts_str)
                parts.append(f"核心板块: {'; '.join(sector_details)}")
            else:
                parts.append(f"核心板块: 无")

        # RPS 强度板块（RPS>85，发现偷偷变强的方向）
        rps_data = rps_strong_map.get(date_str, {})
        rps_labels = [
            ('rps_10', '短线RPS10>85'),
            ('rps_20', '中线RPS20>85'),
            ('rps_50', '长线RPS50>85'),
        ]
        for rps_key, label in rps_labels:
            items = rps_data.get(rps_key, [])
            if items:
                entries = [f"{name}(RPS{val},涨{chg:+.1f}%)" for name, val, chg in items]
                parts.append(f"{label}: {', '.join(entries)}")
        parts.append("")
    return '\n'.join(parts)


WEEKLY_SUMMARY_PROMPT = """你是一位资深的A股量化策略总监，具备深厚的交易经验。请根据以下本周每个交易日的AI分析数据，撰写一份精炼的周度市场总结报告。

[严格要求]
1. 输出必须为中文（简体中文），使用Markdown格式。
2. 先用一段话总结本周市场整体走势（涨跌节奏、成交量变化、市场情绪）。
3. 再用一段话总结本周最强板块和主线逻辑。
4. **重点关注RPS强度板块**：每日数据中包含RPS10/20/50>85的板块列表及当日涨跌幅。请综合RPS值变化和涨跌幅分析：
   - **趋势偷偷变强**：RPS持续走高（如RPS10从86升到92），或从RPS10>85扩展到RPS20/50>85，说明资金在悄悄介入。
   - **由强转衰**：RPS从高位回落（如从95降到82跌破85线），或RPS仍高但连续大跌（如RPS98但连跌3天-3%以上），说明主力在出货、趋势即将逆转。
   分别用两段话总结"本周趋势偷偷变强的板块"和"本周由强转衰的板块"。
5. 最后给出下周操作建议（仓位建议、风控要点、重点关注的RPS走强板块、警惕的RPS转弱板块）。
6. 保持专业、果断的语气，避免空话套话。
7. [文本重点标记规则] 输出文本中，关键术语和重要结论必须使用Markdown加粗语法（**加粗**）进行标记，例如：**量价收紧突破**、**口袋突破**、**技术性止损**、**缩量回调**、**主力出货**等。每段最多标记10个重点词，不要整句加粗。

[每日AI分析数据]
{daily_analyses}

请输出周度总结报告。"""


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
    import threading
    from datetime import datetime as _dt
    from app.data.task_manager import get_task_manager

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
        from app.data.db import get_db
        db = get_db()
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
        tm = get_task_manager()
        steps = [
            {'name': f'生成第{week_index}周总结', 'key': 'weekly_summary', 'status': 'pending', 'total_count': 1, 'completed_count': 0, 'failed_count': 0, 'skipped_count': 0},
        ]
        task_id = tm.create_task_with_steps(steps)

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

                import openai
                client = openai.OpenAI(api_key=analyst.api_key, base_url=analyst.base_url)

                user_message = WEEKLY_SUMMARY_PROMPT.format(daily_analyses=daily_analyses)

                kwargs = {
                    'model': analyst.model,
                    'messages': [
                        {'role': 'system', 'content': '你是一位专业的A股量化策略分析师，输出中文周度总结报告。'},
                        {'role': 'user', 'content': user_message},
                    ],
                    'max_tokens': 4096,
                    'timeout': 300,
                }
                if analyst.enable_thinking:
                    kwargs['reasoning_effort'] = 'high'
                    kwargs['extra_body'] = {'thinking': {'type': 'enabled'}}
                else:
                    kwargs['temperature'] = analyst.temperature

                response = client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content

                # thinking模式下content可能为空，尝试从reasoning_content获取
                if not content and hasattr(response.choices[0].message, 'reasoning_content'):
                    content = response.choices[0].message.reasoning_content

                if not content:
                    # 重试一次
                    response = client.chat.completions.create(**kwargs)
                    content = response.choices[0].message.content
                    if not content and hasattr(response.choices[0].message, 'reasoning_content'):
                        content = response.choices[0].message.reasoning_content

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

        # 完整的 user message（含 prompt）
        full_message = WEEKLY_SUMMARY_PROMPT.format(daily_analyses=daily_analyses)

        return {
            'success': True,
            'week_index': week_index,
            'dates': week_days,
            'system_message': '你是一位专业的A股量化策略分析师，输出中文周度总结报告。',
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
        from app.data.db import get_db
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


MONTHLY_SUMMARY_PROMPT = """你是一位资深的A股量化策略总监。请完全基于用户提供的【周AI总结数据】（作为唯一的事实依据，严禁凭空臆断和捏造任何未提及的数据或个股），撰写一份精炼、专业的月度市场总结报告。

[严格要求]
1. [输出规范] 使用简体中文、Markdown格式。语气果断、专业，直奔主题，拒绝空话。
2. [整体走势回顾] 提取4周文本中的共性矛盾，用一段话定性全月特征（必须包含：4周里反复出现的“均线广度恶化/站上50日线低占比”、“资金极度抱团/CR5高企”以及全月市场情绪的演变过程）。
3. [最强主线提炼] 归纳4周文本中频繁出现、被各周报告共同公认为“唯一共识”或“诺亚方舟”的超级产业链。请理清该主线从月初到月末的内部轮动演变（例如：从月初的玻璃基板/消费电子，演变到中后期的半导体/存储芯片/先进封装等）。
4. [RPS动量纵轴归类] 严格根据4周文本中提及的RPS表现和价格走势，将板块划分为三类：
   - 【全月抗跌/反复走强真趋势】：在4周文本中虽然有起伏，但月末（第4周）依然维持高RPS、且表现逆市抗跌的板块。
   - 【高位见顶/由强转衰派发组】：在月初或月中RPS极高（如触及100或95+），但在第3周或第4周明确遭遇“断头铡/大阴线/转入弱势”的板块。
   - 【月末悄悄崛起/新晋异动组】：在第4周文本中明确提到“RPS10快速闯入强势区、资金试探性介入”的新面孔板块。
5. [下月操盘指引] 整合4周报告中的风控和策略共性，给出下月指南：
   - 给出全月最安全的【最高仓位硬性限制】（取4周数据中提及的合理仓位交集或底线）。
   - 总结4周文本里一致强调的【硬性止损/熔断生命线】。
   - 列出下月明确可小仓位低吸的【聚焦关注清单】与必须远离的【坚决规避清单】。
6. 保持专业、果断的语气，避免空话套话。
7. [文本重点标记规则] 输出文本中，关键术语和重要结论必须使用Markdown加粗语法（**加粗**）进行标记，例如：**均线广度崩溃**、**资金抱团**、**主线切换**、**放量突破**、**缩量见顶**等。每段最多标记10个重点词，不要整句加粗。

[各周AI总结数据]
{weekly_summaries}

请输出月度总结报告。"""


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
    import threading
    from datetime import datetime as _dt
    from app.data.task_manager import get_task_manager

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
        tm = get_task_manager()
        steps = [
            {'name': f'生成{year}年{month}月总结', 'key': 'monthly_summary', 'status': 'pending', 'total_count': 1, 'completed_count': 0, 'failed_count': 0, 'skipped_count': 0},
        ]
        task_id = tm.create_task_with_steps(steps)

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

                import openai
                client = openai.OpenAI(api_key=analyst.api_key, base_url=analyst.base_url)

                user_message = MONTHLY_SUMMARY_PROMPT.format(weekly_summaries=weekly_summaries)

                kwargs = {
                    'model': analyst.model,
                    'messages': [
                        {'role': 'system', 'content': '你是一位专业的A股量化策略分析师，输出中文月度总结报告。'},
                        {'role': 'user', 'content': user_message},
                    ],
                    'max_tokens': 4096,
                    'timeout': 300,
                }
                if analyst.enable_thinking:
                    kwargs['reasoning_effort'] = 'high'
                    kwargs['extra_body'] = {'thinking': {'type': 'enabled'}}
                else:
                    kwargs['temperature'] = analyst.temperature

                response = client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content

                # thinking模式下content可能为空，尝试从reasoning_content获取
                if not content and hasattr(response.choices[0].message, 'reasoning_content'):
                    content = response.choices[0].message.reasoning_content

                if not content:
                    # 重试一次
                    response = client.chat.completions.create(**kwargs)
                    content = response.choices[0].message.content
                    if not content and hasattr(response.choices[0].message, 'reasoning_content'):
                        content = response.choices[0].message.reasoning_content

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


# ==================== 月度重算 ====================

@router.post("/recalculate-month")
def recalculate_month_api(
    year: int = Query(..., description="年份 YYYY"),
    month: int = Query(..., description="月份 1-12"),
):
    """启动月度重算任务"""
    import threading
    try:
        from app.data.task_manager import get_task_manager
        from app.data.db import get_db
        tm = get_task_manager()
        db = get_db()
        
        # 检查是否有正在运行的任务
        running_task = db['sync_tasks'].find_one(
            {'status': 'running', 'current_stock_name': {'$regex': '重算'}},
            sort=[('created_at', -1)]
        )
        
        if running_task:
            # 复用正在运行的任务
            task_id = running_task['task_id']
            return {
                'success': True,
                'task_id': task_id,
                'message': f'任务正在运行中，共用task_id',
                'already_running': True
            }
        
        # 查询个股和板块数量
        stock_count = db['stock_basics'].count_documents({'is_disable': {'$ne': True}})
        sector_count = db['sector_basics'].count_documents({'is_disable': {'$ne': True}})
        
        # 查询该月实际交易日（从stock_daily中查询）
        month_prefix = f"{year}{month:02d}"
        trading_dates = sorted([d for d in db['stock_daily'].distinct('trade_date') if d.startswith(month_prefix)])
        trading_days = len(trading_dates)
        
        # 定义步骤：每天3个步骤（RPS个股、RPS板块、预计算）= 交易日数 × 3
        steps = []
        for date_str in trading_dates:
            steps.append({'name': f'{date_str} 计算个股RPS', 'key': 'rps_stock', 'current_date': date_str, 'status': 'pending', 'total_count': stock_count, 'completed_count': 0, 'failed_count': 0, 'skipped_count': 0})
            steps.append({'name': f'{date_str} 计算板块RPS', 'key': 'rps_sector', 'current_date': date_str, 'status': 'pending', 'total_count': sector_count, 'completed_count': 0, 'failed_count': 0, 'skipped_count': 0})
            steps.append({'name': f'{date_str} 预计算基础数据', 'key': 'precompute', 'current_date': date_str, 'status': 'pending', 'total_count': 1, 'completed_count': 0, 'failed_count': 0, 'skipped_count': 0})
        
        # 创建带步骤的任务
        task_id = tm.create_task_with_steps(steps)
        
        thread = threading.Thread(
            target=_run_monthly_recalc_task,
            args=(task_id, year, month),
            daemon=True
        )
        thread.start()
        
        return {
            'success': True,
            'task_id': task_id,
            'message': f'{year}年{month}月重算任务已启动'
        }
    except Exception as e:
        logger.error(f"启动月度重算失败: {e}")
        raise HTTPException(status_code=500, detail=f"启动失败: {str(e)[:200]}")


@router.get("/task/{task_id}")
def get_task_status(task_id: str):
    """通用任务状态查询接口"""
    from app.data.db import get_db
    db = get_db()
    
    task = db['sync_tasks'].find_one({'task_id': task_id})
    if not task:
        return {'status': 'not_found', 'task_id': task_id}
    
    return {
        'status': task.get('status', 'idle'),
        'task_id': task.get('task_id'),
        'current_step': task.get('current_step'),
        'current_stock_name': task.get('current_stock_name', ''),
        'completed_count': task.get('completed_count', 0),
        'total_count': task.get('total_count', 0),
        'message': task.get('message', ''),
        'steps': task.get('steps', []),
    }


def _run_monthly_recalc_task(task_id: str, year: int, month: int):
    """执行月度重算任务"""
    import time
    from datetime import datetime as _dt
    from app.data.task_manager import get_task_manager
    tm = get_task_manager()
    
    try:
        db = get_db()
        
        # 获取该月所有交易日
        all_dates = sorted(db['stock_daily'].distinct('trade_date'))
        month_dates = [d for d in all_dates if d.startswith(f"{year}{month:02d}")]
        
        if not month_dates:
            tm.fail_task(task_id, f"{year}年{month}月无交易数据")
            return
        
        total = len(month_dates)
        success_count = 0
        fail_count = 0
        
        for i, date_str in enumerate(month_dates):
            try:
                # 开始RPS步骤
                rps_step_idx = 0
                tm.start_step(task_id, rps_step_idx)
                
                # 直接调用底层函数，避免全局锁冲突
                from app.server.api.factors import calculate_and_save_rps, _run_precompute_base_for_date

                
                # 1. 计算RPS（传递task_id避免创建子任务）
                calculate_and_save_rps(target='stock', target_date=date_str, max_workers=4, min_days=200, external_task_id=task_id)
                calculate_and_save_rps(target='sector', target_date=date_str, max_workers=4, min_days=20, external_task_id=task_id)
                
                # 2. 预计算基础数据（使用同一个task_id，标记为外部任务）
                # 完成RPS步骤（只更新进度，不重复启动）
                if i == 0:
                    tm.complete_step(task_id, rps_step_idx, f"{date_str} 个股RPS计算完成")
                
                # 开始板块RPS步骤
                rps_sector_step_idx = 1
                tm.start_step(task_id, rps_sector_step_idx)
                tm.complete_step(task_id, rps_sector_step_idx, f"{date_str} 板块RPS计算完成")
                
                # 开始预计算步骤
                precompute_step_idx = 2
                tm.start_step(task_id, precompute_step_idx)
                _run_precompute_base_for_date(task_id, date_str, is_external=True)
                
                # 完成预计算步骤（只更新进度，不重复启动）
                if i == 0:
                    tm.complete_step(task_id, precompute_step_idx, f"{date_str} 预计算完成")
                success_count += 1
                time.sleep(0.5)  # 避免过快
            except Exception as e:
                logger.warning(f"重算 {date_str} 失败: {e}")
                fail_count += 1
        
        tm.complete_task(task_id, f"重算完成: 成功{success_count}天, 失败{fail_count}天")
        
    except Exception as e:
        logger.error(f"月度重算任务失败: {e}")
        tm.fail_task(task_id, str(e)[:200])


# ==================== AI分析补全 ====================

@router.post("/fill-ai-analysis")
def fill_ai_analysis_api(
    year: int = Query(..., description="年份 YYYY"),
    month: int = Query(..., description="月份 1-12"),
):
    """启动AI分析补全任务"""
    import threading
    try:
        from app.data.task_manager import get_task_manager
        from app.data.db import get_db
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
        task_id = tm.create_task_with_steps(steps)
        
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





def _run_fill_ai_task(task_id: str, year: int, month: int):
    """执行AI分析补全任务"""
    import time
    from datetime import datetime as _dt
    from app.data.task_manager import get_task_manager
    tm = get_task_manager()
    
    try:
        db = get_db()
        
        # 获取该月所有交易日
        all_dates = sorted(db['stock_daily'].distinct('trade_date'))
        month_dates = [d for d in all_dates if d.startswith(f"{year}{month:02d}")]
        
        if not month_dates:
            tm.fail_task(task_id, f"{year}年{month}月无交易数据")
            return
        
        # 筛选缺少AI分析的日期
        missing_dates = []
        for date_str in month_dates:
            doc = db['market_daily'].find_one({'trade_date': date_str}, {'_id': 0, 'ai_analysis': 1})
            if not doc or not doc.get('ai_analysis'):
                missing_dates.append(date_str)
        
        if not missing_dates:
            tm.complete_task(task_id, f"所有日期已有AI分析数据")
            return
        
        total = len(missing_dates)
        success_count = 0
        fail_count = 0
        
        # 开始步骤（steps已在endpoint中创建）
        tm.start_step(task_id, 0)
        
        for i, date_str in enumerate(missing_dates):
            if tm.is_cancelled(task_id):
                break
            try:
                tm.update_task_progress(
                    task_id,
                    current_stock_name=f"补全 {date_str}...",
                    completed_count=i,
                    total_count=total,
                )
                
                # 调用AI分析生成
                from app.server.api.market_review import generate_ai_analysis
                generate_ai_analysis(date_str)
                
                success_count += 1
                time.sleep(1)
            except Exception as e:
                logger.warning(f"补全 {date_str} AI分析失败: {e}")
                fail_count += 1
        
        tm.complete_step(task_id, 0, f"AI分析补全完成: 成功{success_count}天, 失败{fail_count}天")
        tm.complete_task(task_id, f"补全完成: 成功{success_count}天, 失败{fail_count}天")
        
    except Exception as e:
        logger.error(f"AI分析补全任务失败: {e}")
        tm.fail_task(task_id, str(e)[:200])



def get_task_status(task_id: str):
    """通用任务状态查询接口"""
    from app.data.db import get_db
    db = get_db()
    
    task = db['sync_tasks'].find_one({'task_id': task_id})
    if not task:
        return {'status': 'not_found', 'task_id': task_id}
    
    return {
        'status': task.get('status', 'idle'),
        'task_id': task.get('task_id'),
        'current_stock_name': task.get('current_stock_name', ''),
        'completed_count': task.get('completed_count', 0),
        'total_count': task.get('total_count', 0),
        'message': task.get('message', ''),
    }
