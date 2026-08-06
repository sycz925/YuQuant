"""
日历复盘服务
处理日历快照、周/月总结输入构建、AI补全等业务逻辑
从 api/calendar.py 迁移而来
"""
import logging
from typing import Any, Dict, List, Optional
from collections import defaultdict, OrderedDict
from datetime import datetime as _dt, timedelta

from app.data.db import get_db
from app.data.holidays import is_workday

logger = logging.getLogger(__name__)

# ========== 提示词常量 ==========

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

MONTHLY_SUMMARY_PROMPT_DAILY = """你是一位资深的A股量化策略总监，具备深厚的交易经验。请根据以下本月每个交易日的AI分析数据，撰写一份精炼的月度市场总结报告。

[严格要求]
1. 输出必须为中文（简体中文），使用Markdown格式。
2. 先用一段话总结本月市场整体走势（涨跌节奏、成交量变化、市场情绪）。
3. 再用一段话总结本月最强板块和主线逻辑。
4. 分析本月市场的主要变化趋势和风格切换。
5. 最后给出下月操作建议（仓位建议、风控要点、重点关注的方向）。
6. 保持专业、果断的语气，避免空话套话。
7. [文本重点标记规则] 输出文本中，关键术语和重要结论必须使用Markdown加粗语法（**加粗**）进行标记。每段最多标记10个重点词，不要整句加粗。

[每日AI分析数据]
{daily_analyses}

请输出月度总结报告。"""

MONTHLY_SUMMARY_PROMPT = """你是一位资深的A股量化策略总监。请完全基于用户提供的【周AI总结数据】（作为唯一的事实依据，严禁凭空臆断和捏造任何未提及的数据或个股），撰写一份精炼、专业的月度市场总结报告。

[严格要求]
1. [输出规范] 使用简体中文、Markdown格式。语气必须果断、硬核、直奔主题，像一位极其严苛的量化总监在下达实战指令，拒绝任何废话和虚饰。关键术语与结论适度**加粗**。

2. [结构精简] 全文仅保留以下三大核心模块，严禁多加其他无关段落：

## 一、 月度大势定性（一句话破局）
用一段极其干练的话，直接定性全月特征。必须包含：
- 全月反复出现的"均线广度恶化 / 站上50日线低占比（极低冰点）"；
- "资金极度抱团 / CR5高企"与全月情绪从抱团避险到恐慌踩踏的演变；
- 归纳全月频繁出现、被公认为"唯一共识/避风港"并经历"启动-抱团-补跌"的主线（医药）。

## 二、 RPS动量分类排队（三类硬指标划分）
严密对照4周数据，将板块分类列出，只说最核心的走势与RPS特征：
- 【真趋势/反复走强】：月末依然维持高RPS、逆市抗跌的板块（如：中特估、种业、周期防守）。
- 【高位见顶/派发杀跌】：月初月中RPS极高（95-100），但后半月明确遭遇巨量大阴线/断头铡的板块（如：半导体全链、创新药/仿制药/减肥药）。
- 【新晋异动/月末崛起】：第4-5周RPS10/20快速冲入强势区、低位放量突破的新面孔（如：AI科技/智谱AI/跨境电商）。

## 三、 下月操盘指令（硬性底线）
- [仓位红线]：给出全月最安全的最高仓位限制（取数据底线/交集）。
- [风控生命线]：硬性止损线与触发清仓的技术条件。
- [清单对决]：用简单列表/对比形式，明确【小仓位低吸清单】与【坚决规避清单】。

3. 保持专业、果断的语气，避免空话套话。
4. [文本重点标记规则] 输出文本中，关键术语和重要结论必须使用Markdown加粗语法（**加粗**）进行标记，例如：**均线广度崩溃**、**资金抱团**、**主线切换**、**放量突破**、**缩量见顶**等。每段最多标记10个重点词，不要整句加粗。

[各周AI总结数据]
{weekly_summaries}

请输出月度总结报告。"""


# ========== 快照服务 ==========

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
        
        # 从index_daily获取大盘涨跌幅（使用平均股价指数 880003）
        index_doc = db['index_daily'].find_one(
            {'stock_code': '880003', 'trade_date': trade_date},
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


# ========== 周/月分组 ==========

def _get_month_weeks(year: int, month: int) -> dict:
    """
    获取月份的周分组。规则：周的最后一个交易日在哪个月，这一周就归哪个月。
    跨月的周只在最后交易日所在的月份显示，不重复。
    返回 {week_index: [当月内的date_str, ...], ...}
    """
    import calendar as cal

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


# ========== AI 输入构建 ==========

def _build_weekly_input_text(week_days: list, ai_docs: dict,
                             new_high_docs: dict = None, lps_docs: dict = None) -> str:
    """构建发送给 DeepSeek 的周总结输入文本"""
    if new_high_docs is None:
        new_high_docs = {}
    if lps_docs is None:
        lps_docs = {}

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

    # 获取周涨跌幅（上周五收盘 → 本周五收盘）
    index_line = ''
    if len(week_days) >= 2:
        first_day = week_days[0]
        last_day = week_days[-1]
        prev_doc = db['index_daily'].find_one(
            {'trade_date': {'$lt': first_day}},
            sort=[('trade_date', -1)],
            projection={'trade_date': 1, '_id': 0}
        )
        prev_day = prev_doc['trade_date'] if prev_doc else first_day
        prev_docs = list(db['index_daily'].find(
            {'trade_date': prev_day},
            {'_id': 0, 'stock_code': 1, 'close': 1}
        ))
        last_docs = list(db['index_daily'].find(
            {'trade_date': last_day},
            {'_id': 0, 'stock_code': 1, 'close': 1}
        ))
        first_map = {d['stock_code']: d.get('close', 0) for d in prev_docs}
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

    # 批量查每天 RPS>85 的板块
    rps_strong_map = {}
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

        # RPS 强度板块
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


def _build_monthly_input_text(month_dates: list, ai_docs: dict,
                              new_high_docs: dict = None, lps_docs: dict = None,
                              overview_docs: dict = None) -> str:
    """构建发送给 DeepSeek 的月总结输入文本"""
    if new_high_docs is None:
        new_high_docs = {}
    if lps_docs is None:
        lps_docs = {}
    if overview_docs is None:
        overview_docs = {}

    db = get_db()

    # 获取月涨跌幅
    index_line = ''
    if len(month_dates) >= 2:
        first_day = month_dates[0]
        last_day = month_dates[-1]
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
            index_line = f"【本月大盘指数涨跌幅({date_range})】{', '.join(idx_parts)}"

    parts = []
    if index_line:
        parts.append(index_line)
        parts.append("")

    # 批量查 sector_daily 的 chg_pct
    sector_chg_map = {}
    sector_name_to_code = {}
    code_to_name_direct = {}
    for s in db['sector_basics'].find(
        {'is_disable': {'$ne': True}}, {'_id': 0, 'code': 1, 'name': 1}
    ):
        sector_name_to_code[s['name']] = s['code']
        code_to_name_direct[s['code']] = s['name']

    all_sector_names = set()
    for date_str in month_dates:
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

    if all_sector_names:
        codes = [sector_name_to_code[n] for n in all_sector_names if n in sector_name_to_code]
        if codes:
            cursor = db['sector_daily'].find(
                {'stock_code': {'$in': codes}, 'trade_date': {'$in': month_dates}},
                {'_id': 0, 'stock_code': 1, 'trade_date': 1, 'chg_pct': 1}
            )
            for doc in cursor:
                name = code_to_name_direct.get(doc['stock_code'], doc['stock_code'])
                sector_chg_map[(name, doc['trade_date'])] = doc.get('chg_pct', 0) or 0

    # 按周分组显示每日数据（带详细信息）
    current_week = []
    last_week_num = None
    
    for date_str in month_dates:
        try:
            dt = _dt.strptime(date_str, '%Y%m%d')
            week_num = dt.isocalendar()[1]
            
            if last_week_num is not None and week_num != last_week_num:
                if current_week:
                    parts.append(f"【第{last_week_num}周】")
                    for day_data in current_week:
                        parts.append(day_data)
                    parts.append("")
                current_week = []
            
            last_week_num = week_num
            formatted = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
            
            ai = ai_docs.get(date_str)
            if ai:
                day_text = f"【{formatted}】"
                day_text += f"\n市场阶段诊断: {ai.get('market_phase_diagnosis', '无')}"
                day_text += f"\n行业集群评估: {ai.get('industry_cluster_evaluation', '无')}"
                
                advices = ai.get('execution_strategy_advice', [])
                if advices:
                    day_text += f"\n执行策略建议: {'; '.join(advices)}"
                
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
                        day_text += f"\n核心板块: {'; '.join(sector_details)}"
                    else:
                        day_text += f"\n核心板块: 无"
                
                current_week.append(day_text)
            else:
                current_week.append(f"【{formatted}】无AI分析数据")
                
        except Exception:
            continue
    
    # 输出最后一周
    if current_week:
        parts.append(f"【第{last_week_num}周】")
        for day_data in current_week:
            parts.append(day_data)
        parts.append("")

    return '\n'.join(parts)


# ========== 后台任务 ==========

def _run_fill_ai_task(task_id: str, year: int, month: int):
    """执行AI分析补全任务"""
    import time
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
        
        # 开始步骤
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
                
                # 预计算 market_daily 数据
                from app.server.services.market_data import precompute_market_daily
                precompute_market_daily(date_str)
                
                # 从 market_daily 读取数据
                cached = db['market_daily'].find_one({'trade_date': date_str}, {'_id': 0})
                if not cached:
                    logger.warning(f"补全 {date_str}: 无 market_daily 数据")
                    fail_count += 1
                    continue
                
                # 调用 DeepSeek 分析
                from app.server.services.market_ai import call_deepseek
                market_data = {
                    'trade_date': date_str,
                    'overview': cached.get('overview', {}),
                    'new_high': cached.get('new_high', {}),
                    'low_position_sectors': cached.get('low_position_sectors', []),
                    'active_sectors': cached.get('active_sectors', []),
                }
                
                ai_result = call_deepseek(date_str, market_data)
                
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