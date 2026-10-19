"""
持仓风控引擎 —— ATR 止损止盈 + MTR 波动有效放大过滤

纯计算模块：
  - 不访问数据库，输入已排序的日线序列，输出风控结果
  - 供 app/server/services/position_service.py 调用

核心公式（参见 需求.txt v3.0）：
  TR  = max(High-Low, |High-PrevClose|, |Low-PrevClose|)
  ATR = SMA(TR, atr_period)

  MTR = max(|High-PrevClose|, |Low-PrevClose|)            # Chris Lindgren
  MTR_mean = SMA(MTR, mtr_period)
  MTR_std  = STDEV(MTR, mtr_period)                       # 总体标准差 ddof=0
  VALID_EXPANSION ⇔ MTR > MTR_mean + mtr_std_mult * MTR_std

  initial_stop  = buy_price - k_initial     * atr_entry
  take_profit   = buy_price + k_take_profit * atr_entry
  trailing_stop = highest_since_entry - k_trail * atr_current
  current_stop  = max(prev_stop, trailing_stop)           # 只上移，不下移
                  （MTR = INVALID_NOISE 时维持 prev_stop）

纪律约束：
  1. MTR 只过滤「移动止损上移 / 加仓 / 趋势确认」，不过滤硬性止损触发
  2. 盘中检查使用「前一交易日收盘后确定的止损价」（止损只在收盘后移动，无未来函数）
"""
import logging
import math
from typing import Any, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)

# ==================== 默认参数 ====================

DEFAULT_PARAMS: Dict[str, Any] = {
    'atr_period': 14,
    'k_initial': 2.0,
    'k_trail': 2.5,
    'k_take_profit': 3.0,
    'mtr_period': 20,
    'mtr_std_mult': 2.0,
    'trailing_high_source': 'close',   # 'close' | 'high'
    'mtr_filter_enabled': True,        # False = 关闭 MTR 对移动止损上移的过滤
    'trend_filter_enabled': False,
    'trend_ma_period': 20,
    'risk_ratio_per_trade': 0.005,
    # ---- 动态止盈（默认关闭）：浮盈达到 arm_r × R 后，可改用「最高价 × (1 - tp_trail_pct%)」接管离场 ----
    # 说明：接管会让离场线明显变宽（回吐更多）。经实测在 ATR 本身很紧的持仓上反而更差，
    # 因此默认关闭，需要时在「风控参数」里手动开启。
    'tp_dynamic_enabled': False,
    'tp_trail_pct': 30.0,
    'tp_arm_r': 2.0,
}

# 参数合法区间（防止前端/接口传入荒谬值把风控算崩）
PARAM_BOUNDS: Dict[str, tuple] = {
    'atr_period': (2, 120),
    'k_initial': (0.1, 20.0),
    'k_trail': (0.1, 20.0),
    'k_take_profit': (0.1, 20.0),
    'mtr_period': (2, 120),
    'mtr_std_mult': (0.1, 20.0),
    'trend_ma_period': (2, 250),
    'risk_ratio_per_trade': (0.0001, 0.5),
    'tp_trail_pct': (1.0, 90.0),
    'tp_arm_r': (0.5, 20.0),
}
PARAM_CHOICES = {'trailing_high_source': ('close', 'high')}

# 动作建议
ACTION_HOLD = '持仓'
ACTION_GAP_STOP = '跳空止损'
ACTION_INTRADAY_STOP = '盘中止损'
ACTION_CLOSE_STOP = '收盘止损'
ACTION_TAKE_PROFIT = '利润保护参考'
ACTION_MTR_FILTERED = 'MTR过滤'
ACTION_DYNAMIC_TP = '动态止盈'

# MTR 过滤状态
MTR_VALID = 'VALID_EXPANSION'
MTR_NOISE = 'INVALID_NOISE'

# 风险校验
RISK_PASS = 'PASS'
RISK_WARN = 'WARN_OVER_RISK'
RISK_REJECT = 'REJECT'


class RiskDataError(ValueError):
    """风控计算所需的数据不足或非法"""


# ==================== 参数处理 ====================

def normalize_params(params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """合并默认参数并做类型/区间校验，非法值回落默认"""
    merged = dict(DEFAULT_PARAMS)
    if not params:
        return merged

    for key, bounds in PARAM_BOUNDS.items():
        if key not in params or params[key] is None:
            continue
        try:
            val = float(params[key])
        except (TypeError, ValueError):
            logger.warning('风控参数 %s 非法值 %r，回落默认', key, params[key])
            continue
        lo, hi = bounds
        if key in ('atr_period', 'mtr_period', 'trend_ma_period'):
            val = int(round(val))
        if val < lo or val > hi:
            logger.warning('风控参数 %s=%s 超出区间 [%s, %s]，回落默认', key, val, lo, hi)
            continue
        merged[key] = val

    src = params.get('trailing_high_source')
    if src in PARAM_CHOICES['trailing_high_source']:
        merged['trailing_high_source'] = src

    for flag in ('mtr_filter_enabled', 'trend_filter_enabled', 'tp_dynamic_enabled'):
        if flag in params:
            merged[flag] = bool(params[flag])

    return merged


# ==================== 数据归一化 ====================

def _date_str(value: Any) -> str:
    """统一成 YYYYMMDD 定宽字符串"""
    if value is None:
        return ''
    s = str(value).strip()
    digits = ''.join(ch for ch in s if ch.isdigit())
    if len(digits) >= 8:
        return digits[:8]
    return s


def _to_float(value: Any) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float('inf'), float('-inf')):   # NaN / Inf
        return None
    return f


def normalize_bars(bars: Any) -> List[Dict[str, Any]]:
    """把 DataFrame / list[dict] 统一成按 trade_date 升序、字段为 float 的 list[dict]"""
    if bars is None:
        return []

    records: List[Dict[str, Any]]
    if hasattr(bars, 'columns') and hasattr(bars, 'to_dict'):
        df = bars.reset_index()
        cols = list(df.columns)
        if 'trade_date' not in cols:
            first = cols[0] if cols else None
            if first is not None and first not in ('open', 'high', 'low', 'close'):
                df = df.rename(columns={first: 'trade_date'})
        records = df.to_dict('records')
    else:
        records = list(bars)

    out: List[Dict[str, Any]] = []
    for row in records:
        if not isinstance(row, dict):
            continue
        date = _date_str(row.get('trade_date') or row.get('date'))
        if not date:
            continue
        o = _to_float(row.get('open'))
        h = _to_float(row.get('high'))
        l = _to_float(row.get('low'))
        c = _to_float(row.get('close'))
        if None in (o, h, l, c):
            continue
        if min(o, h, l, c) <= 0:
            continue
        out.append({'trade_date': date, 'open': o, 'high': h, 'low': l, 'close': c})

    out.sort(key=lambda r: r['trade_date'])

    # 同一天重复时保留最后一条
    seen: Dict[str, Dict[str, Any]] = {}
    for row in out:
        seen[row['trade_date']] = row
    return [seen[k] for k in sorted(seen)]


# ==================== 指标序列 ====================

def compute_true_range(bars: Sequence[Dict[str, Any]]) -> List[Optional[float]]:
    """TR 序列，第 0 根无前收盘 → None"""
    tr: List[Optional[float]] = [None]
    for i in range(1, len(bars)):
        prev_close = bars[i - 1]['close']
        cur = bars[i]
        tr.append(max(
            cur['high'] - cur['low'],
            abs(cur['high'] - prev_close),
            abs(cur['low'] - prev_close),
        ))
    return tr


def compute_mtr_raw(bars: Sequence[Dict[str, Any]]) -> List[Optional[float]]:
    """MTR 原始序列，第 0 根无前收盘 → None"""
    mtr: List[Optional[float]] = [None]
    for i in range(1, len(bars)):
        prev_close = bars[i - 1]['close']
        cur = bars[i]
        mtr.append(max(abs(cur['high'] - prev_close), abs(cur['low'] - prev_close)))
    return mtr


def _rolling_mean(values: Sequence[Optional[float]], period: int) -> List[Optional[float]]:
    """N 期简单移动平均；窗口必须落在连续的有效值上"""
    out: List[Optional[float]] = [None] * len(values)
    valid = [(i, v) for i, v in enumerate(values) if v is not None]
    for k in range(period - 1, len(valid)):
        window = valid[k - period + 1:k + 1]
        if window[-1][0] - window[0][0] != period - 1:
            continue
        out[window[-1][0]] = sum(v for _, v in window) / period
    return out


def _rolling_std(values: Sequence[Optional[float]], period: int) -> List[Optional[float]]:
    """N 期总体标准差（ddof=0）"""
    out: List[Optional[float]] = [None] * len(values)
    valid = [(i, v) for i, v in enumerate(values) if v is not None]
    for k in range(period - 1, len(valid)):
        window = valid[k - period + 1:k + 1]
        if window[-1][0] - window[0][0] != period - 1:
            continue
        nums = [v for _, v in window]
        mean = sum(nums) / period
        out[window[-1][0]] = math.sqrt(sum((x - mean) ** 2 for x in nums) / period)
    return out


def compute_indicators(bars: Sequence[Dict[str, Any]], params: Dict[str, Any]) -> Dict[str, List[Optional[float]]]:
    """一次性算出 ATR / MTR / MTR均值 / MTR标准差 / 趋势均线，供逐日回算复用"""
    tr = compute_true_range(bars)
    mtr = compute_mtr_raw(bars)
    atr_period = int(params['atr_period'])
    mtr_period = int(params['mtr_period'])
    closes = [b['close'] for b in bars]

    return {
        'tr': tr,
        'atr': _rolling_mean(tr, atr_period),
        'mtr': mtr,
        'mtr_mean': _rolling_mean(mtr, mtr_period),
        'mtr_std': _rolling_std(mtr, mtr_period),
        'ma_trend': _rolling_mean(closes, int(params['trend_ma_period'])),
    }


def _atr_at(bars: Sequence[Dict[str, Any]], end_index: int, period: int) -> Optional[float]:
    """取 bars[:end_index+1] 区间末尾的 ATR（end_index 为最后一根 K 线下标）"""
    if end_index < 0 or end_index >= len(bars):
        return None
    atr_series = _rolling_mean(compute_true_range(bars), period)
    return atr_series[end_index]


# ==================== 建仓前风控（事前） ====================

def preview_entry(
    bars: Any,
    buy_date: Any,
    buy_price: Any,
    buy_shares: Any,
    current_equity: Any,
    params: Optional[Dict[str, Any]] = None,
    price_dec: int = 2,
    asset_type: str = 'stock',
) -> Dict[str, Any]:
    """建仓预览：基于「买入日之前」的日线计算 ATR 与止损止盈，并做风险校验（不落库）

    Args:
        bars: 该标的日线（含买入日之前足够的历史）
        buy_date: 买入日期 YYYYMMDD
        buy_price: 买入价（真实成交价）
        buy_shares: 计划买入股数
        current_equity: 账户当前总权益
        price_dec: 价格小数位（个股 2 / ETF 3）

    Returns:
        dict，含 atr_entry / initial_stop_loss_price / take_profit_reference_price /
        suggested_max_shares / risk_check_status / risk_per_share / messages

    Raises:
        RiskDataError: 历史数据不足或入参非法
    """
    p = normalize_params(params)
    norm_bars = normalize_bars(bars)
    target_date = _date_str(buy_date)

    price = _to_float(buy_price)
    if price is None or price <= 0:
        raise RiskDataError(f'买入价非法: {buy_price!r}')
    shares_f = _to_float(buy_shares)
    if shares_f is None or shares_f <= 0:
        raise RiskDataError(f'买入股数非法: {buy_shares!r}')
    shares = int(shares_f)

    equity = _to_float(current_equity)
    if equity is None or equity <= 0:
        raise RiskDataError(f'账户权益非法: {current_equity!r}')

    # ← 关键：只用买入日「之前」的 K 线，避免未来函数
    prior = [b for b in norm_bars if b['trade_date'] < target_date]
    need = int(p['atr_period']) + 1
    if len(prior) < need:
        raise RiskDataError(
            f'买入日 {target_date} 之前的日线仅 {len(prior)} 根，'
            f'不足以计算 ATR({p["atr_period"]})（至少需要 {need} 根）'
        )

    atr_entry = _atr_at(prior, len(prior) - 1, int(p['atr_period']))
    if atr_entry is None or atr_entry <= 0:
        raise RiskDataError(f'无法计算 ATR({p["atr_period"]})，最近日线价格可能异常')

    # 与 simulate 保持一致：止损/止盈先对齐 tick，再参与后续计算
    _tick = lambda v: round(float(v), price_dec)  # noqa: E731
    initial_stop = _tick(price - float(p['k_initial']) * atr_entry)
    take_profit = _tick(price + float(p['k_take_profit']) * atr_entry)
    risk_per_share = _tick(price) - initial_stop

    max_loss = equity * float(p['risk_ratio_per_trade'])
    if risk_per_share <= 0:
        suggested = 0
        status = RISK_REJECT
        messages = ['每股风险 ≤ 0，止损价高于买入价，建议放弃该笔交易。']
    else:
        raw = max_loss / risk_per_share
        # A 股/ETF 均为 100 股(份) 整手
        suggested = int(math.floor(raw / 100.0) * 100)
        if suggested <= 0:
            status = RISK_REJECT
            messages = [
                f'按账户权益 {equity:,.2f} 与单笔风险上限 {float(p["risk_ratio_per_trade"]):.2%}，'
                f'最大可接受亏损 {max_loss:,.2f} 元，不足 1 手（100 股），建议放弃该笔交易。'
            ]
        elif shares <= suggested:
            status = RISK_PASS
            messages = [
                f'风险校验通过：计划买入 {shares:,} 股 ≤ 建议上限 {suggested:,} 股。'
            ]
        else:
            status = RISK_WARN
            messages = [
                f'风险超标！按账户当前权益和当前止损距离，单笔最大可买 {suggested:,} 股。'
                f'建议减仓至 {suggested:,} 股，或放弃该笔交易。'
            ]

    round_n = lambda v: round(v, price_dec)  # noqa: E731

    return {
        'asset_type': asset_type,
        'buy_date': target_date,
        'buy_price': round_n(price),
        'buy_shares': shares,
        'atr_entry': round_n(atr_entry),
        'atr_period': int(p['atr_period']),
        'initial_stop_loss_price': round_n(initial_stop),
        'take_profit_reference_price': round_n(take_profit),
        'risk_per_share': round_n(risk_per_share),
        'max_loss_per_trade': round(max_loss, 2),
        'current_equity': round(equity, 2),
        'suggested_max_shares': suggested,
        'risk_check_status': status,
        'position_value': round(price * shares, 2),
        'messages': messages,
        'params': p,
    }


# ==================== 逐日回算（事中） ====================

def _fmt_date(d: str) -> str:
    if len(d) == 8 and d.isdigit():
        return f'{d[:4]}-{d[4:6]}-{d[6:]}'
    return d


def _build_action(events: List[str], filtered: bool) -> str:
    """动作建议优先级：硬性止损 > 止盈参考 > MTR 过滤 > 持仓"""
    if 'gap_stop' in events:
        return ACTION_GAP_STOP
    if 'intraday_stop' in events:
        return ACTION_INTRADAY_STOP
    if 'close_stop' in events:
        return ACTION_CLOSE_STOP
    if 'dynamic_tp_hit' in events:
        return ACTION_DYNAMIC_TP
    if 'take_profit_ref' in events:
        return ACTION_TAKE_PROFIT
    if filtered:
        return ACTION_MTR_FILTERED
    return ACTION_HOLD


def _build_suggestion(action: str, detail: Dict[str, Any]) -> str:
    stop = detail.get('current_stop_loss_price')
    open_p = detail.get('open')
    if action == ACTION_GAP_STOP:
        return f'跳空止损提醒：开盘价 {open_p} 已低于止损价 {stop}，实际成交可能更差，建议立即市价卖出。'
    if action == ACTION_INTRADAY_STOP:
        return f'盘中止损触发提醒：最低价已触及止损价 {stop}，建议执行卖出。'
    if action == ACTION_CLOSE_STOP:
        return f'收盘止损触发提醒：收盘价已跌破止损价 {stop}，建议次日开盘执行卖出。'
    if action == ACTION_DYNAMIC_TP:
        return (f'跌破动态止盈线 {detail.get("dynamic_tp_price")}'
                f'（较高点回撤已达设定幅度），建议分批止盈或离场；'
                f'剩余仓位仍由 ATR 移动止损 {detail.get("current_stop_loss_price")} 保护。')
    if action == ACTION_TAKE_PROFIT:
        return '已达利润保护参考位，可考虑部分止盈，或上移移动止损继续持有。'
    if action == ACTION_MTR_FILTERED:
        return '触发价格边界，但 MTR 显示波动未有效放大，移动止损上移被过滤，维持观察。'
    return '持仓观察。'


def simulate(
    bars: Any,
    buy_date: Any,
    buy_price: Any,
    buy_shares: Any,
    atr_entry: Any = None,
    initial_stop_loss_price: Any = None,
    take_profit_reference_price: Any = None,
    params: Optional[Dict[str, Any]] = None,
    price_dec: int = 2,
    asset_type: str = 'stock',
    sells: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """从买入日逐日回算止损轨迹与动作建议

    Args:
        bars: 该标的日线（需包含买入日及之后的所有交易日）
        buy_date: 买入日 YYYYMMDD
        buy_price: 买入价（**当前前复权口径**，由 service 层用锚点比例折算好）
        buy_shares: **原始建仓股数**（分批卖出不改这个值）
        sells: 卖出流水 [{'sell_date','shares','sell_price','realized_pnl'}]，
               用于按当日实际持有股数计算浮盈 / 持仓风险 / 累计已实现
        atr_entry / initial_stop_loss_price / take_profit_reference_price:
            建仓时冻结的值；为 None 则按当前参数重算（用于历史持仓补算）
        price_dec: 价格小数位
        asset_type: 'stock' | 'etf'（ETF 为 T+0，买入当日即可卖出）

    Returns:
        按交易日升序的每日状态列表
    """
    p = normalize_params(params)
    norm_bars = normalize_bars(bars)
    target_date = _date_str(buy_date)
    price = _to_float(buy_price)
    if price is None or price <= 0:
        raise RiskDataError(f'买入价非法: {buy_price!r}')
    shares = int(_to_float(buy_shares) or 0)
    if shares <= 0:
        raise RiskDataError(f'持仓股数非法: {buy_shares!r}')

    start_index = next((i for i, b in enumerate(norm_bars) if b['trade_date'] >= target_date), None)
    if start_index is None:
        raise RiskDataError(
            f'买入日 {target_date} 之后还没有日线数据（行情可能尚未同步），'
            f'执行「刷新监控」可自动补齐后再回算')

    # 卖出流水：按日期升序，供逐日推进"当日剩余股数 / 累计已实现"
    sell_events: List[Dict[str, Any]] = []
    for item in (sells or []):
        if not isinstance(item, dict):
            continue
        d = _date_str(item.get('sell_date'))
        sh = int(_to_float(item.get('shares')) or 0)
        if not d or sh <= 0:
            continue
        rp = _to_float(item.get('realized_pnl'))
        if rp is None:
            sp = _to_float(item.get('sell_price'))
            rp = (sp - price) * sh if sp is not None else 0.0
        sell_events.append({'date': d, 'shares': sh, 'realized_pnl': float(rp)})
    sell_events.sort(key=lambda e: e['date'])

    ind = compute_indicators(norm_bars, p)

    # 未冻结时按当前参数补算
    if atr_entry is None:
        atr_entry = _atr_at(norm_bars[:start_index], start_index - 1, int(p['atr_period']))
    if atr_entry is None or _to_float(atr_entry) is None:
        raise RiskDataError(f'无法计算买入日 {target_date} 的 ATR({p["atr_period"]})')
    atr_entry = float(atr_entry)

    initial_stop = _to_float(initial_stop_loss_price)
    if initial_stop is None:
        initial_stop = price - float(p['k_initial']) * atr_entry
    if _to_float(take_profit_reference_price) is None:
        take_profit = price + float(p['k_take_profit']) * atr_entry
    else:
        take_profit = float(take_profit_reference_price)

    # ⚠ 关键：止损/止盈价必须对齐到最小价格变动单位（tick）
    # 否则「展示的止损价」与「实际用于穿越判断的止损价」会差一个浮点尾巴，
    # 恰好开盘在止损价上时会出现「图表显示已跌破、事件里却没有跳空止损」的矛盾。
    tick = lambda v: round(float(v), price_dec)  # noqa: E731
    initial_stop = tick(initial_stop)
    take_profit = tick(take_profit)

    tencent_t0 = (asset_type == 'etf')   # ETF 支持 T+0

    states: List[Dict[str, Any]] = []
    highest = tick(price)
    stop = initial_stop
    rnd = lambda v: None if v is None else round(v, price_dec)  # noqa: E731

    # 1R（每股初始风险）：动态止盈的档位基准
    risk_per_share = max(price - initial_stop, 0.0)
    tp_dyn_on = bool(p['tp_dynamic_enabled'])
    tp_pct = float(p['tp_trail_pct']) / 100.0
    arm_r = float(p['tp_arm_r'])

    # 分批卖出状态：held = 当日实际持有股数，realized_cum = 截至当日的累计已实现
    sell_idx = 0
    held = shares
    realized_cum = 0.0

    for i in range(start_index, len(norm_bars)):
        bar = norm_bars[i]
        while sell_idx < len(sell_events) and sell_events[sell_idx]['date'] <= bar['trade_date']:
            ev = sell_events[sell_idx]
            held -= ev['shares']
            realized_cum += ev['realized_pnl']
            sell_idx += 1
        held = max(held, 0)
        atr_i = ind['atr'][i]
        mtr_i = ind['mtr'][i]
        mtr_mean = ind['mtr_mean'][i]
        mtr_std = ind['mtr_std'][i]

        if mtr_i is None or mtr_mean is None or mtr_std is None:
            mtr_status: Optional[str] = None
        else:
            threshold = mtr_mean + float(p['mtr_std_mult']) * mtr_std
            mtr_status = MTR_VALID if mtr_i > threshold else MTR_NOISE

        events: List[str] = []
        filtered = False
        is_buy_day = (i == start_index)

        if is_buy_day and not tencent_t0:
            # 个股 T+1：买入当日不可卖出 → 不做触发判定，止损位＝初始止损
            stop_in_effect = initial_stop
            new_stop = initial_stop
            dyn_tp_in_effect = None
        else:
            # 止损只在收盘后移动 → 当日检查用「前一交易日收盘后」的止损价
            # stop 已是 tick 值，比较结果与图表展示完全一致
            stop_in_effect = stop

            # 动态止盈线：以「上一日为止的最高价」为锚，浮盈达 arm_r×R 后才启用
            dyn_tp_in_effect = None
            if tp_dyn_on and risk_per_share > 0:
                gain_r_prev = (highest - price) / risk_per_share
                if gain_r_prev >= arm_r:
                    dyn_tp_in_effect = tick(highest * (1 - tp_pct))

            if dyn_tp_in_effect is not None:
                # 动态止盈接管：ATR 移动止损让位（不再作为离场依据），
                # 只看收盘是否跌破「最高价 ×(1-回撤%)」——这才是让利润奔跑的关键
                if bar['close'] < dyn_tp_in_effect:
                    events.append('dynamic_tp_hit')
            else:
                if bar['open'] <= stop:
                    events.append('gap_stop')
                if bar['low'] <= stop:
                    events.append('intraday_stop')
                if bar['close'] <= stop:
                    events.append('close_stop')
            if bar['close'] >= take_profit:
                events.append('take_profit_ref')

            # 更新买入以来最高价
            src = bar['high'] if p['trailing_high_source'] == 'high' else bar['close']
            highest = max(highest, tick(src))

            new_stop = stop
            if atr_i is not None:
                trailing = tick(highest - float(p['k_trail']) * atr_i)
                allowed = True
                if p['mtr_filter_enabled']:
                    allowed = (mtr_status == MTR_VALID)
                if p['trend_filter_enabled']:
                    ma = ind['ma_trend'][i]
                    allowed = allowed and ma is not None and bar['close'] > ma
                if allowed:
                    new_stop = max(stop, trailing)
                elif trailing > stop:
                    filtered = True       # 本可上移，被 MTR/趋势过滤

        new_stop = max(tick(new_stop), initial_stop)   # 不低于初始止损
        stop = new_stop

        action = _build_action(events, filtered)
        # ⚠ 分批卖出后必须用「当日实际持有股数」，不能用原始建仓股数
        unrealized = (bar['close'] - price) * held
        stop_gap = price - stop
        risk_amount = stop_gap * held
        current_rr = (bar['close'] - price) / stop_gap if stop_gap > 0 else None

        state = {
            'trade_date': bar['trade_date'],
            'date': _fmt_date(bar['trade_date']),
            'open': rnd(bar['open']),
            'high': rnd(bar['high']),
            'low': rnd(bar['low']),
            'close': rnd(bar['close']),
            'atr': rnd(atr_i),
            'mtr': rnd(mtr_i),
            'mtr_mean': rnd(mtr_mean),
            'mtr_std': rnd(mtr_std),
            'mtr_threshold': rnd(None if (mtr_mean is None or mtr_std is None)
                                 else mtr_mean + float(p['mtr_std_mult']) * mtr_std),
            'mtr_filter_status': mtr_status,
            'highest_since_entry': rnd(highest),
            'gain_r': (round((highest - price) / risk_per_share, 2) if risk_per_share > 0 else None),
            'dynamic_tp_price': dyn_tp_in_effect,
            'dynamic_tp_armed': dyn_tp_in_effect is not None,
            'exit_line_price': (dyn_tp_in_effect if dyn_tp_in_effect is not None else rnd(stop)),
            'stop_loss_in_effect': stop_in_effect,
            'current_stop_loss_price': rnd(stop),
            'stop_raised': rnd(stop) != stop_in_effect,
            'stop_move_filtered': filtered,
            'take_profit_reference_price': rnd(take_profit),
            'events': events,
            'action': action,
            'action_suggestion': '',
            'held_shares': held,
            'realized_pnl_cum': round(realized_cum, 2),
            'unrealized_pnl': round(unrealized, 2),
            'position_risk_amount': round(risk_amount, 2),
            'current_rr': None if current_rr is None else round(current_rr, 2),
        }
        state['action_suggestion'] = _build_suggestion(action, state)
        states.append(state)

    return states


def summarize_day(state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """把最后一天的 DayState 压成持仓快照（写回 positions.snapshot）"""
    if not state:
        return {}
    return {
        'trade_date': state['trade_date'],
        'current_price': state['close'],
        'atr_current': state['atr'],
        'highest_since_entry': state['highest_since_entry'],
        'current_stop_loss_price': state['current_stop_loss_price'],
        'dynamic_tp_price': state.get('dynamic_tp_price'),
        'dynamic_tp_armed': state.get('dynamic_tp_armed'),
        'gain_r': state.get('gain_r'),
        'take_profit_reference_price': state['take_profit_reference_price'],
        'mtr_current': state['mtr'],
        'mtr_mean': state['mtr_mean'],
        'mtr_std': state['mtr_std'],
        'mtr_filter_status': state['mtr_filter_status'],
        'action': state['action'],
        'action_suggestion': state['action_suggestion'],
        'held_shares': state.get('held_shares'),
        'realized_pnl_cum': state.get('realized_pnl_cum'),
        'unrealized_pnl': state['unrealized_pnl'],
        'risk_amount': state['position_risk_amount'],
        'current_rr': state['current_rr'],
        'events': state['events'],
    }


# ==================== 账户级汇总（事后） ====================

def aggregate_account(
    current_cash: float,
    positions: Iterable[Dict[str, Any]],
    initial_capital: float = 0.0,
    risk_ratio_per_trade: float = 0.005,
) -> Dict[str, Any]:
    """账户级风控看板

    Args:
        current_cash: 可用现金
        positions: 每项需含 close(最新价) / buy_price_adj / remaining_shares(优先)
                   或 buy_shares / current_stop_loss_price / unrealized_pnl；
                   已平仓项需含 realized_pnl

    Returns:
        账户汇总 dict
    """
    cash = _to_float(current_cash) or 0.0
    active_count = 0
    market_value = 0.0
    total_unrealized = 0.0
    total_realized = 0.0
    risk_clamped = 0.0      # Σ max(0, 单笔风险) —— 组合真实潜在亏损
    risk_raw = 0.0          # Σ 单笔风险（止损高于成本时该笔为负，即已锁定利润）

    for pos in positions:
        status = (pos.get('status') or '').upper()
        if status == 'CLOSED':
            total_realized += _to_float(pos.get('realized_pnl')) or 0.0
            continue
        active_count += 1
        price = _to_float(pos.get('close'))
        cost = _to_float(pos.get('buy_price_adj')) or _to_float(pos.get('buy_price')) or 0.0
        shares = int(_to_float(pos.get('remaining_shares')) or _to_float(pos.get('buy_shares')) or 0)
        stop = _to_float(pos.get('current_stop_loss_price'))
        if price is None:
            price = cost
        market_value += price * shares
        total_unrealized += (price - cost) * shares
        if stop is not None:
            risk = (cost - stop) * shares
            risk_raw += risk
            if risk > 0:
                risk_clamped += risk

    equity = cash + market_value
    cost_basis = sum(
        (_to_float(p.get('buy_price_adj')) or _to_float(p.get('buy_price')) or 0.0)
        * int(_to_float(p.get('remaining_shares')) or _to_float(p.get('buy_shares')) or 0)
        for p in positions
        if (p.get('status') or '').upper() == 'OPEN'
    )

    return {
        'initial_capital': round(_to_float(initial_capital) or 0.0, 2),
        'current_cash': round(cash, 2),
        'market_value': round(market_value, 2),
        'cost_basis': round(cost_basis, 2),
        'current_equity': round(equity, 2),
        'active_positions_count': active_count,
        'total_unrealized_pnl': round(total_unrealized, 2),
        'total_realized_pnl': round(total_realized, 2),
        'total_pnl': round(total_unrealized + total_realized, 2),
        'total_position_risk_amount': round(risk_clamped, 2),
        'total_position_risk_amount_raw': round(risk_raw, 2),
        'total_position_risk_ratio': round(risk_clamped / equity, 6) if equity > 0 else 0.0,
        'locked_profit_amount': round(-risk_raw, 2) if risk_raw < 0 else 0.0,
        'equity_return_ratio': round((equity - (_to_float(initial_capital) or equity)) / (_to_float(initial_capital) or equity), 6)
        if (_to_float(initial_capital) or 0) > 0 else 0.0,
        'unrealized_return_ratio': round(total_unrealized / cost_basis, 6) if cost_basis > 0 else 0.0,
        'risk_ratio_per_trade': risk_ratio_per_trade,
    }


# ==================== 辅助：交易日校验 / 整手校验 ====================

def validate_shares(shares: Any) -> int:
    """A 股/ETF 均以 100 股(份) 为一手"""
    n = int(_to_float(shares) or 0)
    if n <= 0:
        raise RiskDataError('股数必须为正整数')
    if n % 100 != 0:
        raise RiskDataError(f'股数必须为 100 的整数倍，当前 {n}')
    return n
