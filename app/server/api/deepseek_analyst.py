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


def is_market_open() -> bool:
    """判断当前是否是盘中交易时间（9:30-15:00，含午休）"""
    now = datetime.now()
    hour = now.hour
    minute = now.minute
    time_in_minutes = hour * 60 + minute
    
    # 盘中时间：9:30(570)-15:00(900)，包含午休时间
    is_during_trading = 570 <= time_in_minutes < 900
    return is_during_trading

SYSTEM_PROMPT = """You are a senior quantitative strategy director who strictly adheres to the trading philosophies of William O'Neil (CANSLIM), Mark Minervini (SEPA/VCP), and Jesse Livermore.
Your task is to analyze the daily A-share structured market data provided by the user and output a professional, sharp, and highly actionable market wrap-up report.

[STRICT RULES]
1. NEVER echo or restate the raw numbers back to the user mechanically. Instead, translate numbers into concepts like "Institutional Accumulation/Distribution", "Market Divergence", or "Stage II Leadership".
2. Combine separate sector clusters if they belong to the same overarching macro supply chain (e.g., Merge "Memory Chips", "IC Design", and "Semiconductor Materials" into "The Semiconductor Super-Group").
3. Maintain a tone that is decisive, cynical of low-quality meme stock pumps, and highly protective of capital during corrections.
4. All output text MUST be in Chinese (简体中文).
5. [LANGUAGE STYLE] 尽量少用英文专业术语（如 SEPA、VCP、Pivot Point、CANSLIM 等），用通俗易懂的中文表达。例如说"选股环境好"而不是"SEPA系统选股环境极佳"，说"成交量萎缩后突破"而不是"VCP形态突破"。只在必要时才引用术语并附带中文解释。
6. [CRITICAL REGULATION] 用户提供的"历史新高个股板块效应聚类"中的行业，是按新高股票数量筛选出的 Top5 强势板块。这些板块今天都有大量个股创出历史新高，属于市场最强方向。你必须认可这些板块的强势地位，不得将它们标记为"弱势板块"、"跟风板块"或建议回避。即使某个板块平均涨幅为负，只要它有大量新高股，就说明该板块内部分化严重但仍有强势龙头，应聚焦龙头而非回避整个板块。你的任务是评估这些板块中谁最强、谁是主线，而不是质疑它们是否强势。

[STRICT TEXT FORMATTING RULE]
1. When outputting long text in `market_phase_diagnosis` and `industry_cluster_evaluation`, you MUST highlight important terms using Markdown bold syntax.
2. Wrap key terms with double asterisks. Use pure Chinese trading terms for examples: `**量价收紧突破**`, `**口袋突破**`, `**技术性止损**`, `**机构建仓铁证**`, etc.
3. Be precise and restrained — max 10 highlighted terms per paragraph. Never bold entire sentences.
4. Always output in Chinese (简体中文).

[OUTPUT JSON FORMAT]
{
    "market_phase_diagnosis": "一精炼段落：从Minervini/Livermore视角分析指数或广度背离，定性当日行情特征。",
    "industry_cluster_evaluation": "一精炼段落：评估最强产业链，揪出主力建仓铁证。必须基于用户提供的新高板块数据进行分析，不得凭空臆断板块强弱。",
    "execution_strategy_advice": "数组字符串：基于明日具体执行指令列表（例如：["锁定高位个股风险", "等待回调缩量低吸"]）。",
    "allocation_and_focus_model": {
        "recommended_position_range": "基于市场广度、拥挤度、新高数推演的推荐总仓位区间，例如 20% 到 30%",
        "market_risk_level": "风险评级：低/中低/中/中高/高",
        "core_target_sectors": ["从用户提供的新高板块中选出的资金集中攻击的核心板块名称数组，最多5个。注意：这里的板块名称必须与输入数据中的名称完全保持一致，严禁自造简称"],
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

        try:
            import openai
            client = openai.OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )

            user_message = self._build_user_message(market_data)

            kwargs = {
                'model': self.model,
                'response_format': {'type': 'json_object'},
                'messages': [
                    {'role': 'system', 'content': SYSTEM_PROMPT},
                    {'role': 'user', 'content': user_message},
                ],
                'max_tokens': 4096,
                'timeout': 60,
            }

            if self.enable_thinking:
                kwargs['reasoning_effort'] = 'high'
                kwargs['extra_body'] = {'thinking': {'type': 'enabled'}}
            else:
                kwargs['temperature'] = self.temperature

            response = client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content

            if not content:
                logger.warning("[DeepSeek] 返回空 content，重试一次")
                response = client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content

            result = json.loads(content)

            # 验证必要字段
            required_keys = ['market_phase_diagnosis', 'industry_cluster_evaluation', 'execution_strategy_advice']
            for key in required_keys:
                if key not in result:
                    result[key] = ''

            return result

        except Exception as e:
            logger.error(f"[DeepSeek] API 调用失败: {e}")
            return self._fallback()

    def _build_user_message(self, market_data: Dict[str, Any]) -> str:
        """构建发送给 DeepSeek 的用户消息"""
        overview = market_data.get('overview', {})
        new_high = market_data.get('new_high', {})
        trade_date = market_data.get('trade_date', '')
        
        # 判断是否是盘中时间
        is_trading = is_market_open()

        # 从base_data_daily获取量化指标
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

        # 交易日标识
        if trade_date:
            formatted_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}" if len(trade_date) == 8 else trade_date
            msg_parts.append(f"【分析日期】{formatted_date}")
            msg_parts.append("")

        # 市场概览
        indices = overview.get('indices', [])
        if indices:
            msg_parts.append("【主要大盘指数涨跌幅】")
            for idx in indices:
                pe_info = f" (PE_TTM: {idx['pe_ttm']})" if idx.get('pe_ttm') else ''
                # 盘中时不传递成交量信息
                if is_trading:
                    vol_info = ''
                else:
                    vol_today = idx.get('amount_today', 0)
                    vol_yest = idx.get('amount_yesterday', 0)
                    vol_ma5 = idx.get('amount_ma5', 0)
                    vol_ma20 = idx.get('amount_ma20', 0)
                    vol_info = f" | 成交额: {vol_today}亿(昨{vol_yest}亿 MA5:{vol_ma5}亿 MA20:{vol_ma20}亿)" if vol_today else ''
                msg_parts.append(f"  {idx['name']}: {idx.get('pct_chg', 0):+.2f}%{pe_info}{vol_info}")
            leader = indices[0].get('name', '') if indices else ''
            leader_chg = indices[0].get('pct_chg', 0) if indices else 0
            msg_parts.append(f"  领涨: {leader} ({leader_chg:+.2f}%)")

        # 量化指标
        msg_parts.append("")
        msg_parts.append("【市场运行状态量化指标】")
        msg_parts.append(f"  全市场股票数: {signals.get('total_stocks', 0)}")
        msg_parts.append(f"  站上50日线占比: {signals.get('ma50_pct', 0)}%")
        msg_parts.append(f"  站上20日线占比: {signals.get('ma20_pct', 0)}%")
        # 盘中时不传递成交额拥挤度信息
        if not is_trading:
            msg_parts.append(f"  个股成交额前5%拥挤度(CR5%): {round(signals.get('cr5_pct', 0), 2)}%")
            msg_parts.append(f"  板块成交额前10%拥挤度(CR10%): {round(signals.get('cr10_pct', 0), 2)}%")
        msg_parts.append(f"  250日新高-新低差: {signals.get('nh', 0) - signals.get('nl', 0)} (新高{signals.get('nh', 0)} / 新低{signals.get('nl', 0)})")
        msg_parts.append(f"  3个月新高-新低差: {signals.get('nh_3m', 0) - signals.get('nl_3m', 0)} (新高{signals.get('nh_3m', 0)} / 新低{signals.get('nl_3m', 0)})")
        msg_parts.append(f"  1个月新高-新低差: {signals.get('nh_1m', 0) - signals.get('nl_1m', 0)} (新高{signals.get('nh_1m', 0)} / 新低{signals.get('nl_1m', 0)})")

        # 多维分组统计（RPS / 成交额 / 股价）
        if trade_date:
            group_stats = self._compute_group_stats(trade_date, is_trading)
            if group_stats:
                msg_parts.append("")
                msg_parts.append("【市场多维分组统计分析】")
                msg_parts.append(group_stats)

        # 新高板块聚类
        clusters = new_high.get('clusters', [])[:5]
        if clusters:
            msg_parts.append("")
            msg_parts.append("【历史新高个股板块效应聚类】")
            for c in clusters:
                msg_parts.append(f"  {c['industry']}: 涨幅{c.get('chg', 0)}%")
                pioneer = c.get('pioneer', [])
                main_force = c.get('main_force', [])
                followers = c.get('followers', [])
                if pioneer:
                    msg_parts.append(f"    先锋(50日涨幅最高): {', '.join(pioneer)}")
                if main_force:
                    msg_parts.append(f"    中军(市值最大+50日涨幅最高): {', '.join(main_force)}")
                if followers:
                    msg_parts.append(f"    后排(低价+当天涨幅): {', '.join(followers)}")

        # 低位潜力板块
        lps = market_data.get('low_position_sectors', [])[:5]
        if lps:
            msg_parts.append("")
            msg_parts.append("【低位潜力板块】")
            for s in lps:
                msg_parts.append(f"  {s['name']}: 涨幅{s.get('chg_pct', 0)}%, RPS10={s.get('rps_10', 0)}, RPS50={s.get('rps_50', 0)}, MA10={s.get('ma10', 0)}/MA20={s.get('ma20', 0)}")
                pioneer = s.get('pioneer', [])
                main_force = s.get('main_force', [])
                followers = s.get('followers', [])
                if pioneer:
                    msg_parts.append(f"    先锋(50日涨幅最高): {', '.join(pioneer)}")
                if main_force:
                    msg_parts.append(f"    中军(市值最大+50日涨幅最高): {', '.join(main_force)}")
                if followers:
                    msg_parts.append(f"    后排(低价+当天涨幅): {', '.join(followers)}")

        return '\n'.join(msg_parts)

    def _compute_group_stats(self, trade_date: str, is_trading: bool = False) -> str:
        """从 stock_daily 计算 RPS/成交额/股价分组统计，返回格式化文本
        is_trading: 是否是盘中时间，盘中时不返回成交额分组统计
        """
        try:
            from app.data.db import get_db
            db = get_db()

            stocks = list(db['stock_daily'].find(
                {'trade_date': trade_date, 'close': {'$gt': 0}, 'amount': {'$gt': 0}},
                {'_id': 0, 'stock_code': 1, 'close': 1, 'amount': 1, 'chg_pct': 1,
                 'rps_10': 1, 'rps_20': 1, 'rps_50': 1}
            ))
            if not stocks:
                return ''

            merged = []
            for s in stocks:
                chg = s.get('chg_pct')
                if chg is None:
                    continue
                merged.append({
                    'chg_pct': chg,
                    'close': s.get('close', 0),
                    'amount': s.get('amount', 0),
                    'rps_20': s.get('rps_20'),
                })
            if not merged:
                return ''

            total = len(merged)
            n_groups = 20
            lines = []

            # --- RPS20 分组（20个等分位，每组5%） ---
            rps_items = [(d['rps_20'], d['chg_pct']) for d in merged if d.get('rps_20') is not None and d['rps_20'] > 0]
            if rps_items:
                rps_items.sort(key=lambda x: x[0])
                group_size = len(rps_items) // n_groups
                lines.append("  按RPS20分组（每组5%股票，从低到高，显示该组平均涨幅）：")
                for i in range(n_groups):
                    start = i * group_size
                    end = start + group_size if i < n_groups - 1 else len(rps_items)
                    grp = [c for _, c in rps_items[start:end]]
                    if grp:
                        avg = sum(grp) / len(grp)
                        pct_lo = round(start / len(rps_items) * 100)
                        pct_hi = round(end / len(rps_items) * 100)
                        lines.append(f"    RPS20 {pct_lo:3d}%~{pct_hi:3d}%分位: 均涨{avg:+.2f}%")

            # --- 成交额分组（20个等分位，每组5%） ---
            # 盘中时不返回成交额分组统计
            if not is_trading:
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

            # --- 股价分组（20个等分位，每组5%） ---
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

            return '\n'.join(lines)

        except Exception as e:
            logger.warning(f"[DeepSeek] 计算分组统计失败: {e}")
            return ''

    def _fallback(self) -> Dict[str, Any]:
        """降级返回（API不可用时）"""
        return {
            'market_phase_diagnosis': '系统分析服务暂时不可用，请稍后重试。',
            'industry_cluster_evaluation': '系统分析服务暂时不可用，请稍后重试。',
            'execution_strategy_advice': ['系统繁忙中，请稍后刷新查看分析结果。'],
        }


# 单例
_analyst: Optional[DeepSeekAnalyst] = None


def get_deepseek_analyst() -> DeepSeekAnalyst:
    global _analyst
    if _analyst is None:
        _analyst = DeepSeekAnalyst()
    return _analyst
