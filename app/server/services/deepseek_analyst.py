"""
DeepSeek AI 分析服务
接入 DeepSeek API，生成基于大师交易哲学的综合研判
"""
import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def is_market_open(trade_date: str = None) -> bool:
    """
    判断是否是盘中交易时间
    - 如果 trade_date 是今天：用当前时间判断
    - 如果 trade_date 是历史日期：盘后（已收盘）
    """
    now = datetime.now()
    today_str = now.strftime('%Y%m%d')

    if not trade_date or trade_date != today_str:
        return False

    hour = now.hour
    minute = now.minute
    time_in_minutes = hour * 60 + minute

    is_during_trading = 570 <= time_in_minutes < 900
    return is_during_trading


def is_deepseek_available() -> tuple[bool, str]:
    """检查当前是否在 DeepSeek API 可用时间窗口内
    允许时段：12:00-13:00，18:00-23:59
    如果配置了忽略时间窗口，则始终返回可用
    返回: (available: bool, message: str)
    """
    try:
        from app.data.db import get_db
        db = get_db()
        config = db['system_config'].find_one({'key': 'deepseek_time_limit'})
        if config and config.get('value') is False:
            return True, ""
    except Exception:
        pass

    now = datetime.now()
    hour, minute = now.hour, now.minute
    t = hour * 60 + minute
    if 720 <= t < 780:
        return True, ""
    if 1080 <= t <= 1439:
        return True, ""

    return False, f"DeepSeek API 当前不可用，可用时间为 12:00-13:00 或 18:00-23:59（当前 {now.strftime('%H:%M')}）"


SYSTEM_PROMPT = """You are a senior quantitative strategy director who strictly adheres to the trading philosophies of William O'Neil (CANSLIM), Mark Minervini (SEPA/VCP), and Jesse Livermore.
Your task is to analyze the daily A-share structured market data provided by the user and output a professional, sharp, and highly actionable market wrap-up report.

[STRICT RULES]
1. NEVER echo or restate the raw numbers back to the user mechanically. Instead, translate numbers into concepts like "Institutional Accumulation/Distribution", "Market Divergence", or "Stage II Leadership".
2. Combine separate sector clusters if they belong to the same overarching macro supply chain (e.g., Merge "Memory Chips", "IC Design", and "Semiconductor Materials" into "The Semiconductor Super-Group").
3. Maintain a tone that is decisive, cynical of low-quality meme stock pumps, and highly protective of capital during corrections.
4. All output text MUST be in Chinese (简体中文).
5. [LANGUAGE STYLE] 尽量少用英文专业术语（如 SEPA、VCP、Pivot Point、CANSLIM 等），用通俗易懂的中文表达。例如说"选股环境好"而不是"SEPA系统选股环境极佳"，说"成交量萎缩后突破"而不是"VCP形态突破"。只在必要时才引用术语并附带中文解释。
6. [CRITICAL REGULATION] 用户提供的"新高强力板块"中的行业，是按近新高股票数量筛选出的 Top5 强势板块。这些板块今天都有大量个股创出历史接近新高（当日收盘价>历史最高*0.9），属于市场最强方向。你必须认可这些板块的强势地位，不得将它们标记为"弱势板块"、"跟风板块"或建议回避。即使某个板块平均涨幅为负，只要它有大量近新高股，就说明该板块内部分化严重但仍有强势龙头，应聚焦龙头而非回避整个板块。你的任务是评估这些板块中谁最强、谁是主线，而不是质疑它们是否强势。
7. [LOW POSITION SECTORS] 用户提供的"低位潜力板块"是经过量化筛选、具备中长期布局价值的板块。这些板块当前处于相对低位（RPS指标显示近期开始走强），但尚未进入主升浪。分析时应关注：哪些低位板块正在出现资金关注迹象、哪些有望成为下一阶段的补涨主线。不要因为它们涨幅不大就忽略，低位布局往往风险收益比更好。
8. [ACTIVE SECTORS - 异动活跃板块] 用户提供的"异动活跃板块"是当日出现集体异动的板块（板块内流通市值>200亿且涨幅>5%的个股≥10只，其中RPS10+20+50>250占比>30%，且板块自身RPS10+20+50≤250、当日涨幅>2%）。这些板块代表"中期趋势强度已建立 + 大市值放量突破 + 内部强度共振"的启动信号。分析时必须重视以下信号：(1) RPS10>85且RPS20>80说明短线动量已扩散至中线，是趋势转折信号而非一日游；(2) 板块内多只个股50日涨幅>30%说明资金已持续介入；(3) 板块名称与新高板块不同但相关（如医药vs新材料），可能是产业链轮动。禁止将RPS走强的异动板块简单定性为"超跌反弹"或"一日游"，必须基于数据判断是情绪脉冲还是趋势转折。
9. [DYNAMIC POSITION ADJUSTMENT] 仓位动态调整：在评估仓位时，虽然要严格遵循中期均线广度（站上50日线占比），但必须引入"短期动量与赚钱效应"的进攻加权。若数据同时满足以下两个条件：① 1个月/3个月新高差出现显著多头喷发（如1个月新高差接近或超过1000）；② 头部核心资金组（RPS20 95%~100%分位或成交额95%~100%分位）的平均涨幅极强（>4%），说明全市场最顶尖的股票正在疯狂赚钱，主线右侧进攻动量极强。此时必须打破中期广度的保守限制，允许并建议将总仓位区间上限提升至 60% 到 100%，定义为"核心主线右侧主升期"，不可一味盲目恐高。
10. [涨跌停板规则] 涨跌停幅度因板块而异：主板±10%，创业板/科创板±20%，北交所±30%。判断涨停/跌停必须先看股票代码前缀确定板块，再对比涨幅是否达到阈值。禁止将未触及涨跌停的个股称为"涨停/跌停"。
11. [DATA FIDELITY - 实事求是铁律] 分析数据必须做到实事求是：**禁止使用输入数据中不存在的指标（如成交量、放量、缩量、换手率、主力资金流向、资金净流入等）进行任何描述或推断**，只能基于输入中明确提供的字段（涨跌幅、RPS、新高数量、均线占比、价差等）进行分析。若输入中未提供某指标，严禁臆造、脑补或用先验知识虚构其表现。

[STRICT TEXT FORMATTING RULE]
1. When outputting long text in `market_phase_diagnosis` and `industry_cluster_evaluation`, you MUST highlight important terms using Markdown bold syntax.
2. Wrap key terms with double asterisks. Use pure Chinese trading terms for examples: `**量价收紧突破**`, `**口袋突破**`, `**技术性止损**`, `**机构建仓铁证**`, etc.
3. Be precise and restrained — max 10 highlighted terms per paragraph. Never bold entire sentences.
4. Always output in Chinese (简体中文).

[OUTPUT JSON FORMAT]
{
    "market_phase_diagnosis": "一精炼段落：从Minervini/Livermore视角分析指数或广度背离，定性当日行情特征。",
    "industry_cluster_evaluation": "一精炼段落：综合评估三类板块——(1)新高强力板块中谁是主线龙头、(2)低位潜力板块中哪些有资金介入迹象值得跟踪、(3)异动活跃板块是超跌反弹还是趋势转折信号。揪出主力建仓铁证，区分真突破与假信号。必须基于用户提供的数据进行分析，不得凭空臆断板块强弱。注意：如果用户未提供某类板块数据（如低位潜力板块或异动活跃板块为空数组），说明该类板块在今日未产生符合条件的数据（即没有板块满足筛选条件），而非数据缺失。此时只需分析有数据的板块即可，不要提及数据缺失。",
    "execution_strategy_advice": "数组字符串：基于明日具体执行指令列表（例如：[\"锁定高位个股风险\", \"等待回调缩量低吸\"]）。",
    "allocation_and_focus_model": {
        "recommended_position_range": "推荐总仓位区间（仅数字范围，如'0-20%'、'30-50%'、'60-80%'）。必须综合中期均线广度与[DYNAMIC POSITION ADJUSTMENT]规则：若短期主线动量与头部赚钱效应触发加权，应大方给出 60% 到 70% 或 60% 到 80% 的积极进攻仓位；若不触发，则保持 30% 到 50% 的防守仓位。严禁死板机械。",
        "position_management_commentary": "仓位管理说明（必填）。用1-2句话解释为什么给出这个仓位区间，结合市场状态、均线广度、动量信号等关键因素。例如：'总仓位降低至0-20%，坚决轻仓或空仓回避系统风险。中期均线广度崩溃，且短期无从触发进攻加权，必须采取最高级别的防守策略。' 或 '总仓位提升至60-80%，主线右侧进攻动量极强，头部核心资金组疯狂赚钱，必须果断重仓跟进。'",
        "market_risk_level": "风险评级：低/中低/中/中高/高",
        "core_target_sectors": ["从用户提供的三种板块（新高强力板块、低位潜力板块、异动活跃板块）中综合选出的核心目标板块名称数组，最多5个。优先选择新高板块中的主线龙头，若异动活跃板块有明确的趋势转折信号也可纳入。注意：板块名称必须与输入数据中的名称完全保持一致，严禁自造简称"],
        "capital_concentration_rule": "操盘手收盘后的核心风控警示（一句话）。"
    }
}"""


class DeepSeekAnalyst:
    """DeepSeek API 桥接服务"""

    def __init__(self):
        self.api_key = os.environ.get('DEEPSEEK_API_KEY', '')
        self.base_url = 'https://api.deepseek.com'
        self.model = 'deepseek-v4-pro'
        self.enable_thinking = True
        self.temperature = 0.3

    def analyze(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        调用 DeepSeek 生成综合研判
        返回: { market_phase_diagnosis, industry_cluster_evaluation, execution_strategy_advice }
        """
        if not self.api_key:
            logger.warning("[DeepSeek] API Key 未配置，返回降级数据")
            return self._fallback()

        available, msg = is_deepseek_available()
        if not available:
            logger.warning(f"[DeepSeek] {msg}")
            return self._fallback(error_msg=msg)

        try:
            import openai
            client = openai.OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )

            user_message = self._build_user_message(market_data)
            logger.info(f"[DeepSeek] 请求报文长度: {len(user_message)} 字符")
            logger.info(f"[DeepSeek] 请求报文前500字: {user_message[:500]}")

            kwargs = {
                'model': self.model,
                'response_format': {'type': 'json_object'},
                'messages': [
                    {'role': 'system', 'content': SYSTEM_PROMPT},
                    {'role': 'user', 'content': user_message},
                ],
                'max_tokens': 4096,
                'timeout': 120,
            }

            if self.enable_thinking:
                kwargs['reasoning_effort'] = 'high'
                kwargs['extra_body'] = {'thinking': {'type': 'enabled'}}
            else:
                kwargs['temperature'] = self.temperature

            logger.info(f"[DeepSeek] 调用 API, model={self.model}, enable_thinking={self.enable_thinking}")
            response = client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
            logger.info(f"[DeepSeek] 响应长度: {len(content) if content else 0} 字符")
            logger.info(f"[DeepSeek] 响应前500字: {content[:500] if content else 'None'}")

            if not content:
                logger.warning("[DeepSeek] 返回空 content，重试一次")
                response = client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content
                logger.info(f"[DeepSeek] 重试响应长度: {len(content) if content else 0}")

            try:
                result = json.loads(content)
            except json.JSONDecodeError as e:
                logger.warning(f"[DeepSeek] JSON 解析失败: {e}")
                logger.warning(f"[DeepSeek] 原始响应: {content}")
                logger.warning("[DeepSeek] 重试一次...")
                response = client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content
                logger.info(f"[DeepSeek] 重试响应前500字: {content[:500] if content else 'None'}")
                result = json.loads(content)

            required_keys = ['market_phase_diagnosis', 'industry_cluster_evaluation', 'execution_strategy_advice']
            for key in required_keys:
                if key not in result:
                    result[key] = ''

            logger.info(f"[DeepSeek] 解析成功, 字段: {list(result.keys())}")
            return result

        except Exception as e:
            logger.error(f"[DeepSeek] API 调用失败: {e}")
            return self._fallback()

    def _build_user_message(self, market_data: Dict[str, Any]) -> str:
        """构建发送给 DeepSeek 的用户消息"""
        overview = market_data.get('overview', {})
        new_high = market_data.get('new_high', {})
        trade_date = market_data.get('trade_date', '')

        is_trading = is_market_open(trade_date)

        try:
            from app.data.db import get_db
            db = get_db()
            base_doc = db['base_data_daily'].find_one({'date': trade_date}, {'_id': 0})
            if base_doc:
                signals = {
                    'total_stocks': 5200,
                    'ma50_pct': base_doc.get('ma50_pct', 0),
                    'ma20_pct': base_doc.get('ma20_pct', 0),
                    'cr5_pct': base_doc.get('cr5_pct', 0),
                    'cr10_pct': base_doc.get('cr10_pct', 0),
                    'nh': base_doc.get('nh', 0),
                    'nl': base_doc.get('nl', 0),
                    'nh_3m': base_doc.get('nh_3m', 0),
                    'nl_3m': base_doc.get('nl_3m', 0),
                    'nh_1m': base_doc.get('nh_1m', 0),
                    'nl_1m': base_doc.get('nl_1m', 0),
                }
            else:
                signals = {}
        except Exception:
            signals = {}

        msg_parts = []

        if trade_date:
            formatted_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}" if len(trade_date) == 8 else trade_date
            market_phase = "盘中" if is_trading else "盘后"
            msg_parts.append(f"【分析日期】{formatted_date}（{market_phase}）")
            msg_parts.append("")

        indices = overview.get('indices', [])
        if indices:
            msg_parts.append("【主要大盘指数涨跌幅】")
            for idx in indices:
                if is_trading:
                    vol_info = ''
                else:
                    vol_today = idx.get('amount_today', 0)
                    vol_yest = idx.get('amount_yesterday', 0)
                    vol_ma5 = idx.get('amount_ma5', 0)
                    vol_ma20 = idx.get('amount_ma20', 0)
                    vol_info = f" | 成交额: {vol_today}亿(昨{vol_yest}亿 MA5:{vol_ma5}亿 MA20:{vol_ma20}亿)" if vol_today else ''
                comment = idx.get('comment', '')
                import re
                wick_match = re.search(r'（([^）]*)）', comment)
                comment_info = f" {wick_match.group(1)}" if wick_match else ''
                tdx_status = idx.get('tdx_status', '')
                status_info = f" [{tdx_status}]" if tdx_status else ''
                msg_parts.append(f"  {idx['name']}: {idx.get('pct_chg', 0):+.2f}%{status_info}{comment_info}{vol_info}")
            msg_parts.append("  状态说明[日X周X]: 日为日线，周为周线，红色=不能卖(可观望/能买) 绿色=不能买(可观望/能卖) 蓝色=可观望/能买/能卖，仓位配置重点参考该指标。")

        msg_parts.append("")
        msg_parts.append("【市场运行状态量化指标】")
        msg_parts.append(f"  全市场股票数: {signals.get('total_stocks', 0)}")
        msg_parts.append(f"  站上50日线占比: {signals.get('ma50_pct', 0)}%")
        msg_parts.append(f"  站上20日线占比: {signals.get('ma20_pct', 0)}%")
        if not is_trading:
            msg_parts.append(f"  个股成交额前5%拥挤度(CR5%): {round(signals.get('cr5_pct', 0), 2)}%")
            msg_parts.append(f"  板块成交额前10%拥挤度(CR10%): {round(signals.get('cr10_pct', 0), 2)}%")
        msg_parts.append(f"  250日新高-新低差: {signals.get('nh', 0) - signals.get('nl', 0)} (新高{signals.get('nh', 0)} / 新低{signals.get('nl', 0)})")
        msg_parts.append(f"  3个月新高-新低差: {signals.get('nh_3m', 0) - signals.get('nl_3m', 0)} (新高{signals.get('nh_3m', 0)} / 新低{signals.get('nl_3m', 0)})")
        msg_parts.append(f"  1个月新高-新低差: {signals.get('nh_1m', 0) - signals.get('nl_1m', 0)} (新高{signals.get('nh_1m', 0)} / 新低{signals.get('nl_1m', 0)})")

        if trade_date:
            try:
                from app.data.db import get_db
                db = get_db()
                prev_dates = sorted([d for d in db['market_daily'].distinct('trade_date') if d < trade_date], reverse=True)
                if prev_dates:
                    prev_doc = db['market_daily'].find_one(
                        {'trade_date': prev_dates[0]},
                        {'_id': 0, 'trade_date': 1, 'ai_analysis': 1}
                    )
                    prev_ai = (prev_doc or {}).get('ai_analysis') or {}
                    prev_diagnosis = prev_ai.get('market_phase_diagnosis') or ''
                    if prev_diagnosis and prev_ai.get('source') != 'failed':
                        msg_parts.append("")
                        msg_parts.append(f"【上个交易日市场阶段诊断】（{prev_dates[0]}）")
                        msg_parts.append(prev_diagnosis)
            except Exception as e:
                logger.warning(f"[DeepSeek] 获取上个交易日阶段诊断失败: {e}")

        if trade_date:
            group_stats = self._compute_group_stats(trade_date, is_trading)
            if group_stats:
                msg_parts.append("")
                msg_parts.append("【市场多维分组统计分析】")
                msg_parts.append(group_stats)

        clusters = new_high.get('clusters', [])[:5]
        if clusters:
            msg_parts.append("")
            msg_parts.append("【新高强力板块】")
            msg_parts.append("筛选条件：RPS10+RPS20+RPS50三者之和>250的板块中取当日收盘价>历史最高*0.9的个股（接近新高），按行业聚类统计数量，取Top5")
            for c in clusters:
                chg = c.get('chg_pct', 0) or c.get('chg', 0)
                rps_info = ""
                if c.get('rps_10') or c.get('rps_20') or c.get('rps_50'):
                    rps_parts = []
                    if c.get('rps_10'):
                        rps_parts.append(f"RPS10={c['rps_10']}")
                    if c.get('rps_20'):
                        rps_parts.append(f"RPS20={c['rps_20']}")
                    if c.get('rps_50'):
                        rps_parts.append(f"RPS50={c['rps_50']}")
                    rps_info = f", {', '.join(rps_parts)}"
                count_info = f"(创250日近新高{c.get('count', 0)}个)"
                msg_parts.append(f"  {c['industry']}{count_info}: 涨幅{chg}%{rps_info}")
                pioneer = c.get('pioneer', [])
                main_force = c.get('main_force', [])
                followers = c.get('followers', [])
                if pioneer:
                    msg_parts.append(f"    先锋(50日涨幅最高): {', '.join(pioneer)}")
                if main_force:
                    msg_parts.append(f"    中军(流通市值Top10+50日涨幅最高): {', '.join(main_force)}")
                if followers:
                    msg_parts.append(f"    后排(低价+当天涨幅): {', '.join(followers)}")

        if trade_date:
            try:
                from app.data.db import get_db
                db = get_db()

                all_dates = sorted(db['market_daily'].distinct('trade_date'), reverse=True)
                prev_dates = [d for d in all_dates if d < trade_date][:4]

                if prev_dates:
                    all_sector_names = set()
                    hist_data = []
                    for d in reversed(prev_dates):
                        doc = db['market_daily'].find_one({'trade_date': d}, {'_id': 0, 'new_high': 1})
                        if doc and doc.get('new_high', {}).get('clusters'):
                            clusters = doc['new_high']['clusters'][:5]
                            hist_data.append((d, clusters))
                            for c in clusters:
                                all_sector_names.add(c.get('industry', ''))
                        else:
                            hist_data.append((d, []))

                    name_to_code = {}
                    code_to_name = {}
                    for sb in db['sector_basics'].find({'name': {'$in': list(all_sector_names)}}, {'_id': 0, 'code': 1, 'name': 1}):
                        name_to_code[sb['name']] = sb['code']
                        code_to_name[sb['code']] = sb['name']

                    today_sector_data = {}
                    if name_to_code:
                        codes = list(name_to_code.values())
                        sector_docs = db['sector_daily'].find(
                            {'trade_date': trade_date, 'stock_code': {'$in': codes}},
                            {'_id': 0, 'stock_code': 1, 'chg_pct': 1, 'rps_10': 1, 'rps_20': 1, 'rps_50': 1}
                        )
                        for sd in sector_docs:
                            name = code_to_name.get(sd['stock_code'], '')
                            if name:
                                today_sector_data[name] = sd

                    msg_parts.append("")
                    msg_parts.append("【近4日新高强力板块变化趋势】")
                    for d, clusters in hist_data:
                        formatted_date = f"{d[:4]}-{d[4:6]}-{d[6:]}"
                        cluster_strs = []
                        for c in clusters:
                            name = c.get('industry', '')
                            chg = c.get('chg_pct', 0) or c.get('chg', 0)
                            rps_parts = []
                            if c.get('rps_10'):
                                rps_parts.append(f"RPS10={c['rps_10']}")
                            if c.get('rps_20'):
                                rps_parts.append(f"RPS20={c['rps_20']}")
                            if c.get('rps_50'):
                                rps_parts.append(f"RPS50={c['rps_50']}")
                            rps_str = ', '.join(rps_parts) if rps_parts else ''

                            today_sd = today_sector_data.get(name)
                            today_str = ''
                            if today_sd:
                                today_rps = []
                                if today_sd.get('rps_10'):
                                    today_rps.append(f"RPS10={today_sd['rps_10']}")
                                if today_sd.get('rps_20'):
                                    today_rps.append(f"RPS20={today_sd['rps_20']}")
                                if today_sd.get('rps_50'):
                                    today_rps.append(f"RPS50={today_sd['rps_50']}")
                                today_rps_str = ', '.join(today_rps) if today_rps else ''
                                today_str = f"(今日: 涨幅{today_sd.get('chg_pct', 0)}%, {today_rps_str})"

                            cluster_strs.append(f"{name}: 涨幅{chg}%, {rps_str}{today_str}")
                        msg_parts.append(f"  {formatted_date}: {'; '.join(cluster_strs)}")
            except Exception as e:
                logger.warning(f"获取历史新高板块失败: {e}")

        lps = market_data.get('low_position_sectors', [])[:5]
        if lps:
            msg_parts.append("")
            msg_parts.append("【低位潜力板块】")
            msg_parts.append("筛选条件：板块涨幅>2% + MA10>MA20 + RPS10>85(短线爆发力) + RPS50<70(长线低位) + 近3天有1天以上≥15%个股创20日新高 + 近5天有4天净新高>-10")
            for s in lps:
                count_info = f"(创20日近新高{s.get('count', 0)}个)"
                msg_parts.append(f"  {s['name']}{count_info}: 涨幅{s.get('chg_pct', 0)}%, RPS10={s.get('rps_10', 0)}, RPS20={s.get('rps_20', 0)}, RPS50={s.get('rps_50', 0)}")
                pioneer = s.get('pioneer', [])
                main_force = s.get('main_force', [])
                followers = s.get('followers', [])
                if pioneer:
                    msg_parts.append(f"    先锋(50日涨幅最高): {', '.join(pioneer)}")
                if main_force:
                    msg_parts.append(f"    中军(流通市值Top10+50日涨幅最高): {', '.join(main_force)}")
                if followers:
                    msg_parts.append(f"    后排(低价+当天涨幅): {', '.join(followers)}")

        active = market_data.get('active_sectors', [])[:5]
        if active:
            msg_parts.append("")
            msg_parts.append("【异动活跃板块】")
            msg_parts.append("筛选条件：板块内流通市值>200亿且涨幅>5%的个股≥10只 + 其中RPS10+20+50>250占比>30% + 板块RPS10+20+50≤250 + 板块当日涨幅>2%")
            for s in active:
                rps_info = ""
                if s.get('rps_10') or s.get('rps_20') or s.get('rps_50'):
                    rps_parts = []
                    if s.get('rps_10'):
                        rps_parts.append(f"RPS10={s['rps_10']}")
                    if s.get('rps_20'):
                        rps_parts.append(f"RPS20={s['rps_20']}")
                    if s.get('rps_50'):
                        rps_parts.append(f"RPS50={s['rps_50']}")
                    rps_info = f", {', '.join(rps_parts)}"
                count_info = f"(强度共振{s.get('count', 0)}只/{s.get('total', 0)}只, 板块涨{s.get('chg_pct', 0)}%)"
                msg_parts.append(f"  {s['name']}{count_info}: 达标股均涨{s.get('avg_stock_chg_pct', 0)}%{rps_info}")
                pioneer = s.get('pioneer', [])
                main_force = s.get('main_force', [])
                followers = s.get('followers', [])
                if pioneer:
                    msg_parts.append(f"    先锋(50日涨幅最高): {', '.join(pioneer)}")
                if main_force:
                    msg_parts.append(f"    中军(流通市值Top10+50日涨幅最高): {', '.join(main_force)}")
                if followers:
                    msg_parts.append(f"    后排(低价+当天涨幅): {', '.join(followers)}")

        try:
            from app.data.db import get_db
            db = get_db()
            trade_date = market_data.get('trade_date', '')
            if trade_date:
                high_rps_sectors = list(db['sector_daily'].find(
                    {'trade_date': trade_date, 'rps_20': {'$gt': 85}},
                    {'_id': 0, 'stock_code': 1, 'rps_10': 1, 'rps_20': 1, 'rps_50': 1, 'chg_pct': 1, 'chg_5d': 1, 'chg_20d': 1}
                ).sort('rps_20', -1))
                if high_rps_sectors:
                    basics = {b['code']: b['name'] for b in db['sector_basics'].find({}, {'_id': 0, 'code': 1, 'name': 1})}
                    msg_parts.append("")
                    msg_parts.append("【板块四维动量气泡图】（RPS20>85 的强势板块，按RPS20降序）")
                    msg_parts.append("  四维指标: RPS20(中期动量) RPS10(短期动量) 当日涨幅 5日涨幅")
                    msg_parts.append(f"  共 {len(high_rps_sectors)} 个板块:")
                    for s in high_rps_sectors:
                        name = basics.get(s['stock_code'], s['stock_code'])
                        rps20 = s.get('rps_20', 0)
                        rps10 = s.get('rps_10', 0)
                        chg = s.get('chg_pct', 0) or 0
                        chg5 = s.get('chg_5d', 0) or 0
                        msg_parts.append(f"    {name}: RPS20={rps20}, RPS10={rps10}, 涨幅={chg:+.1f}%, 5日={chg5:+.1f}%")
        except Exception as e:
            logger.warning(f"[DeepSeek] 板块四维动量数据获取失败: {e}")

        return '\n'.join(msg_parts)

    def _compute_group_stats(self, trade_date: str, is_trading: bool = False) -> str:
        """从 market_daily 缓存或 stock_daily 计算分组统计，返回格式化文本"""
        try:
            from app.data.db import get_db
            db = get_db()

            cached = db['market_daily'].find_one({'trade_date': trade_date}, {'_id': 0, 'group_stats': 1})
            if cached and cached.get('group_stats'):
                return self._format_cached_group_stats(cached['group_stats'], is_trading)

            return self._compute_group_stats_from_db(trade_date, is_trading)
        except Exception as e:
            logger.warning(f"计算分组统计失败: {e}")
            return ''

    def _format_cached_group_stats(self, group_stats: dict, is_trading: bool = False) -> str:
        """从缓存的 group_stats 格式化为文本"""
        lines = []

        amount_stats = group_stats.get('amount_stats', [])
        if amount_stats:
            if lines:
                lines.append("")
            lines.append("  按成交额分组（每组5%股票，从低到高，显示该组平均涨幅）：")
            for g in amount_stats:
                label = g.get('category_label', '')
                avg_chg = g.get('avg_chg', 0)
                lines.append(f"    成交额{label}: 均涨{avg_chg:+.2f}%")

        float_mv_stats = group_stats.get('float_mv_stats', [])
        if float_mv_stats:
            lines.append("")
            lines.append("  按流通市值分组（每组5%股票，从低到高，显示该组平均涨幅）：")
            for g in float_mv_stats:
                label = g.get('category_label', '')
                avg_chg = g.get('avg_chg', 0)
                lines.append(f"    流通市值{label}: 均涨{avg_chg:+.2f}%")

        price_stats = group_stats.get('price_stats', [])
        if price_stats:
            lines.append("")
            lines.append("  按股价分组（每组5%股票，从低到高，显示该组平均涨幅）：")
            for g in price_stats:
                label = g.get('category_label', '')
                avg_chg = g.get('avg_chg', 0)
                lines.append(f"    股价{label}: 均涨{avg_chg:+.2f}%")

        return '\n'.join(lines) if lines else ''

    def _compute_group_stats_from_db(self, trade_date: str, is_trading: bool = False) -> str:
        """从 stock_daily 直接计算分组统计（缓存不存在时的备选方案）"""
        from app.data.db import get_db
        db = get_db()

        stocks = list(db['stock_daily'].find(
            {'trade_date': trade_date, 'close': {'$gt': 0}, 'amount': {'$gt': 0}},
            {'_id': 0, 'stock_code': 1, 'close': 1, 'amount': 1, 'chg_pct': 1,
             'rps_10': 1, 'rps_20': 1, 'rps_50': 1}
        ))
        if not stocks:
            return ''

        stock_codes = [s['stock_code'] for s in stocks]
        liutong_map = {}
        for doc in db['stock_basics'].find(
            {'stock_code': {'$in': stock_codes}, 'liutongguben': {'$gt': 0}},
            {'_id': 0, 'stock_code': 1, 'liutongguben': 1}
        ):
            liutong_map[doc['stock_code']] = doc['liutongguben']

        merged = []
        for s in stocks:
            chg = s.get('chg_pct')
            if chg is None:
                continue
            liutong = liutong_map.get(s['stock_code'], 0)
            close = s.get('close', 0)
            float_mv = round(liutong * close / 1e8, 2) if liutong > 0 and close > 0 else 0
            merged.append({
                'chg_pct': chg,
                'close': close,
                'amount': s.get('amount', 0),
                'rps_20': s.get('rps_20'),
                'float_mv': float_mv,
            })
        if not merged:
            return ''

        total = len(merged)
        n_groups = 20
        lines = []

        amt_items = [(d['amount'], d['chg_pct']) for d in merged if d['amount'] > 0]
        if amt_items:
            amt_items.sort(key=lambda x: x[0])
            group_size = len(amt_items) // n_groups
            lines.append("")
            lines.append("  按成交额分组（每组5%股票，从低到高，显示该组平均涨幅）：")
            for i in range(n_groups):
                start = i * group_size
                end = start + group_size if i < n_groups - 1 else len(amt_items)
                grp = [c for _, c in amt_items[start:end]]
                if grp:
                    avg = sum(grp) / len(grp)
                    pct_lo = round(start / len(amt_items) * 100)
                    pct_hi = round(end / len(amt_items) * 100)
                    lines.append(f"    成交额{pct_lo:3d}%~{pct_hi:3d}%分位: 均涨{avg:+.2f}%")

        mv_items = [(d['float_mv'], d['chg_pct']) for d in merged if d['float_mv'] > 0]
        if mv_items:
            mv_items.sort(key=lambda x: x[0])
            group_size = len(mv_items) // n_groups
            lines.append("")
            lines.append("  按流通市值分组（每组5%股票，从低到高，显示该组平均涨幅）：")
            for i in range(n_groups):
                start = i * group_size
                end = start + group_size if i < n_groups - 1 else len(mv_items)
                grp = [c for _, c in mv_items[start:end]]
                if grp:
                    avg = sum(grp) / len(grp)
                    pct_lo = round(start / len(mv_items) * 100)
                    pct_hi = round(end / len(mv_items) * 100)
                    lines.append(f"    流通市值{pct_lo:3d}%~{pct_hi:3d}%分位: 均涨{avg:+.2f}%")

        price_items = [(d['close'], d['chg_pct']) for d in merged if d['close'] > 0]
        if price_items:
            price_items.sort(key=lambda x: x[0])
            group_size = len(price_items) // n_groups
            lines.append("")
            lines.append("  按股价分组（每组5%股票，从低到高，显示该组平均涨幅）：")
            for i in range(n_groups):
                start = i * group_size
                end = start + group_size if i < n_groups - 1 else len(price_items)
                grp = [c for _, c in price_items[start:end]]
                if grp:
                    avg = sum(grp) / len(grp)
                    pct_lo = round(start / len(price_items) * 100)
                    pct_hi = round(end / len(price_items) * 100)
                    lines.append(f"    股价{pct_lo:3d}%~{pct_hi:3d}%分位: 均涨{avg:+.2f}%")

        return '\n'.join(lines) if lines else ''

    def _fallback(self, error_msg: str = None) -> Dict[str, Any]:
        """降级返回（API不可用时）"""
        msg = error_msg or '系统分析服务暂时不可用，请稍后重试。'
        return {
            'market_phase_diagnosis': msg,
            'industry_cluster_evaluation': msg,
            'execution_strategy_advice': [msg],
        }


# 单例
_analyst: Optional[DeepSeekAnalyst] = None


def get_deepseek_analyst() -> DeepSeekAnalyst:
    global _analyst
    if _analyst is None:
        _analyst = DeepSeekAnalyst()
    return _analyst