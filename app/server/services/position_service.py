"""
Position Service - 持仓风控业务编排层

职责：
  1. 账户 / 持仓的增删改查
  2. 建仓前风控校验（ATR 止损、建议股数、风险超标提示）
  3. 持仓逐日回算（ATR 移动止损 + MTR 过滤），产出 K 线标注与每日轨迹
  4. 账户级风控看板
  5. 除权锚点折算：stock_daily/etf_daily 为前复权序列，用建仓时冻结的
     anchor_close 与当前同一日的前复权收盘价之比换算，保证 K 线/止损/盈亏对齐

分层约束（AGENTS.md §7）：本层不直连 get_db()，行情与集合访问全部经 PositionRepository。
"""
import logging
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.engine import position_risk as pr
from app.server.repositories import get_position_repo

logger = logging.getLogger(__name__)

# 买入日前回看的自然日数（覆盖 ATR14 + MTR20 + MA20 所需窗口，留足冗余）
BAR_LOOKBACK_DAYS = 500

# 预警动作集合
ALERT_ACTIONS = {pr.ACTION_GAP_STOP, pr.ACTION_INTRADAY_STOP,
                 pr.ACTION_CLOSE_STOP, pr.ACTION_TAKE_PROFIT,
                 pr.ACTION_DYNAMIC_TP}

# 硬性止损事件（不含 take_profit_ref —— 止盈参考命中是正面信号，不是风险事件）
STOP_EVENTS = {'gap_stop', 'intraday_stop', 'close_stop'}

# 卖出理由：主动减仓 / 被动止损 / 手动
SELL_REASONS = ('take_profit', 'stop_loss', 'manual')
SELL_REASON_LABEL = {'take_profit': '主动减仓', 'stop_loss': '被动止损', 'manual': '手动卖出'}

# ==================== 内部工具 ====================


class PositionError(Exception):
    """业务校验失败（映射为 HTTP 400/404/409）"""

    def __init__(self, message: str, status_code: int = 400, payload: Optional[Dict] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.payload = payload or {}


def _now() -> datetime:
    return datetime.now()


def _norm_date(value: Any, field: str = '日期') -> str:
    """接受 YYYYMMDD / YYYY-MM-DD / YYYY/MM/DD，输出 YYYYMMDD"""
    if value is None:
        raise PositionError(f'{field}不能为空')
    s = str(value).strip()
    for fmt in ('%Y%m%d', '%Y-%m-%d', '%Y/%m/%d'):
        try:
            return datetime.strptime(s, fmt).strftime('%Y%m%d')
        except ValueError:
            continue
    raise PositionError(f'{field}格式无法识别: {value!r}')


def _price_dec(asset_type: str) -> int:
    return 3 if asset_type == 'etf' else 2


def _normalize_sells(pos: Dict[str, Any]) -> List[Dict[str, Any]]:
    """归一化卖出流水（按卖出日升序）

    兼容两种数据形态：
      - 新数据：positions.sells = [{sell_id, sell_date, sell_price, shares, ...}]
      - 旧数据：只有顶层 sell_date / sell_price / realized_pnl（视为一次全平）
    """
    raw = pos.get('sells')
    out: List[Dict[str, Any]] = []
    if isinstance(raw, list) and raw:
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            shares = int(pr._to_float(item.get('shares')) or 0)
            if shares <= 0:
                continue
            out.append({
                'sell_id': item.get('sell_id') or f's{i + 1}',
                'sell_date': str(item.get('sell_date') or ''),
                'sell_price': pr._to_float(item.get('sell_price')),
                'shares': shares,
                'realized_pnl': pr._to_float(item.get('realized_pnl')),
                'return_ratio': pr._to_float(item.get('return_ratio')),
                'reason': item.get('reason') if item.get('reason') in SELL_REASONS else 'manual',
                'note': item.get('note'),
            })
        out.sort(key=lambda x: x['sell_date'])
        return out

    buy = int(pr._to_float(pos.get('buy_shares')) or 0)
    if pos.get('sell_date') and buy > 0:
        return [{
            'sell_id': 'legacy',
            'sell_date': str(pos['sell_date']),
            'sell_price': pr._to_float(pos.get('sell_price')),
            'shares': buy,
            'realized_pnl': pr._to_float(pos.get('realized_pnl')),
            'return_ratio': pr._to_float(pos.get('return_ratio')),
            'reason': 'manual',
            'note': pos.get('close_note'),
        }]
    return []


def _remaining_shares(pos: Dict[str, Any]) -> int:
    """剩余可卖股数：优先物化字段，否则 buy_shares − Σ已卖出"""
    if pos.get('remaining_shares') is not None:
        return max(int(pr._to_float(pos.get('remaining_shares')) or 0), 0)
    buy = int(pr._to_float(pos.get('buy_shares')) or 0)
    sold = sum(x['shares'] for x in _normalize_sells(pos))
    return max(buy - sold, 0)


def _calendar_days(start: Optional[str], end: Optional[str]) -> Optional[int]:
    """两个 YYYYMMDD 之间的自然日数（含首尾）"""
    if not start or not end:
        return None
    try:
        return (datetime.strptime(str(end), '%Y%m%d')
                - datetime.strptime(str(start), '%Y%m%d')).days + 1
    except Exception:
        return None


def _latest_trade_day(today: Optional[str] = None) -> str:
    """截至今天（含）的最近一个交易日（周末/节假日向前回退）"""
    from app.data.holidays import is_workday
    d = today or _now().strftime('%Y%m%d')
    for _ in range(20):
        if is_workday(d):
            return d
        d = (datetime.strptime(d, '%Y%m%d') - timedelta(days=1)).strftime('%Y%m%d')
    return d


def _position_shares(pos: Dict[str, Any]) -> int:
    """风控计算用的股数 = 剩余股数；已全部卖出的历史持仓返回 0"""
    return _remaining_shares(pos)


def _fmt_date(d: Optional[str]) -> Optional[str]:
    if d and len(str(d)) == 8 and str(d).isdigit():
        return f'{d[:4]}-{d[4:6]}-{d[6:]}'
    return d


def _get_params() -> Dict[str, Any]:
    """全局风控参数（DB 覆盖默认）"""
    return pr.normalize_params(get_position_repo().get_params())


# ==================== 参数设置 ====================


def get_settings() -> Dict[str, Any]:
    """返回当前生效参数 + 默认值 + 可调区间（供前端渲染表单）"""
    stored = get_position_repo().get_params() or {}
    return {
        'params': _get_params(),
        'defaults': pr.DEFAULT_PARAMS,
        'bounds': {k: list(v) for k, v in pr.PARAM_BOUNDS.items()},
        'choices': {k: list(v) for k, v in pr.PARAM_CHOICES.items()},
        'stored_keys': sorted(stored.keys()),
    }


def save_settings(params: Dict[str, Any]) -> Dict[str, Any]:
    """保存风控参数（非法值回落默认，不落库）"""
    merged = pr.normalize_params(params or {})
    get_position_repo().save_params(merged)
    return get_settings()


# ==================== 行情/锚点 ====================


def _load_bars(code: str, asset_type: str, buy_date: str,
               end_date: Optional[str] = None) -> List[Dict[str, Any]]:
    start = (datetime.strptime(buy_date, '%Y%m%d') - timedelta(days=BAR_LOOKBACK_DAYS)).strftime('%Y%m%d')
    return get_position_repo().get_bars(code, asset_type, start_date=start, end_date=end_date)


def _anchor_ratio(pos: Dict[str, Any], bars: List[Dict[str, Any]]) -> Tuple[float, Optional[Dict]]:
    """除权锚点折算比例 r = 当前前复权收盘(买入日) / 建仓时冻结的前复权收盘(买入日)

    r ≈ 1 表示持有期内无除权；r < 1 表示发生过除权，历史价格被整体下移，
    需把买入价/止损/止盈同比例折算到今天的前复权口径。
    """
    buy_date = pos['buy_date']
    now_bar = next((b for b in bars if b['trade_date'] >= buy_date), None)
    anchor = pr._to_float(pos.get('anchor_close'))
    if not now_bar or not anchor or anchor <= 0:
        return 1.0, now_bar
    return now_bar['close'] / anchor, now_bar


def _replay(pos: Dict[str, Any], params: Optional[Dict[str, Any]] = None,
            end_date: Optional[str] = None) -> Dict[str, Any]:
    """回算单笔持仓 → 含 bars / states / 折算后的成本与止损止盈"""
    asset_type = pos.get('asset_type') or 'stock'
    dec = _price_dec(asset_type)
    buy_date = pos['buy_date']
    p = pr.normalize_params({**_get_params(), **(params or {})})

    bars = _load_bars(pos['stock_code'], asset_type, buy_date, end_date=end_date)
    if not bars:
        raise PositionError(
            f'{pos["stock_code"]} 在 {buy_date} 之后没有日线数据，无法计算止损', 400)

    ratio, _ = _anchor_ratio(pos, bars)
    buy_price_adj = round(float(pos['buy_price']) * ratio, dec)
    atr_entry = pos.get('atr_entry')
    init_stop = pos.get('initial_stop_loss_price')
    take_profit = pos.get('take_profit_reference_price')

    states = pr.simulate(
        bars, buy_date, buy_price_adj, int(pos['buy_shares']),
        atr_entry=None if atr_entry is None else round(float(atr_entry) * ratio, dec),
        initial_stop_loss_price=None if init_stop is None else round(float(init_stop) * ratio, dec),
        take_profit_reference_price=None if take_profit is None else round(float(take_profit) * ratio, dec),
        params=p, price_dec=dec, asset_type=asset_type,
        sells=_normalize_sells(pos),
    )

    return {
        'bars': bars,
        'states': states,
        'ratio': ratio,
        'price_dec': dec,
        'params': p,
        'buy_price_adj': buy_price_adj,
        'anchor_close_now': (states[0]['close'] if states else None),
    }


def _latest_of(bars: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return bars[-1] if bars else None


# ==================== 刷新前的日线数据补齐 ====================

# 计算 ATR(14) + MTR(20) 所需的最少连续 K 线数（含前收盘）
MIN_BARS_FOR_RISK = 40


def ensure_position_data(positions: Optional[List[Dict[str, Any]]] = None,
                         account_id: Optional[str] = None) -> Dict[str, Any]:
    """刷新监控前检查持仓标的的日线基础数据，缺失/不足/过旧的按需补齐

    判定规则：
      - 完全没有日线数据                → 全量拉取（回溯 10 年）
      - 有数据但不足 MIN_BARS_FOR_RISK  → 全量拉取
      - 最后一根 < 买入日                 → 增量拉取（建仓日行情还没同步）
      - 最后一根 < 全市场最新交易日        → 增量拉取（数据过旧，快照会失真）
      - 其余                            → 跳过（由一键更新统一覆盖维护）

    这样"刷新监控"只补真正缺的那几只，不会为持仓去跑全市场同步。
    """
    repo = get_position_repo()
    if positions is None:
        positions = repo.list_positions(account_id=account_id)
    if not positions:
        return {'checked': 0, 'synced': [], 'failed': [], 'skipped': [],
                'full': {}, 'incremental': {}}

    # (asset_type, code) → 最早买入日（同一只票多笔持仓取最早，保证历史够长）
    needs: Dict[Tuple[str, str], str] = {}
    for pos in positions:
        at = pos.get('asset_type') or 'stock'
        key = (at, pos['stock_code'])
        buy_date = pos.get('buy_date') or ''
        if key not in needs or buy_date < needs[key]:
            needs[key] = buy_date

    # 批量取区间信息（每种类型一次聚合查询）
    ranges: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for at in {k[0] for k in needs}:
        codes = [c for (a, c) in needs if a == at]
        for code, rng in repo.get_bar_ranges(codes, at).items():
            ranges[(at, code)] = rng

    # 判断「是否已同步到最新」的基准日 = min(集合内最新日, 截至今天的最近交易日)
    # 注意：集合里可能含未来日期（或今天非交易日），直接用它会导致每次刷新都做无谓同步
    ref_day = _latest_trade_day()
    market_latest: Dict[str, str] = {}
    for at in {k[0] for k in needs}:
        coll_last = str(repo.get_market_latest_date(at) or '')
        market_latest[at] = min(coll_last, ref_day) if coll_last else ref_day

    full_req: Dict[str, List[str]] = {'stock': [], 'etf': []}
    inc_req: Dict[str, List[str]] = {'stock': [], 'etf': []}
    skipped: List[str] = []

    for (at, code), buy_date in needs.items():
        rng = ranges.get((at, code)) or {}
        count = int(rng.get('count') or 0)
        last = str(rng.get('last') or '')
        ml = str(market_latest.get(at) or '')
        if count == 0 or count < MIN_BARS_FOR_RISK:
            # 完全没数据 / 历史太短 → 全量
            full_req.setdefault(at, []).append(code)
        elif last < buy_date or (ml and last < ml):
            # ① 最后一根还没到买入日（建仓日行情未同步）
            # ② 已过买入日但没跟到全市场最新日（数据过旧，快照会失真）
            inc_req.setdefault(at, []).append(code)
        else:
            skipped.append(code)

    summary: Dict[str, Any] = {
        'checked': len(needs),
        'synced': [],
        'failed': [],
        'skipped': skipped,
        'full': {k: v for k, v in full_req.items() if v},
        'incremental': {k: v for k, v in inc_req.items() if v},
    }
    if not (any(full_req.values()) or any(inc_req.values())):
        return summary

    try:
        from app.data.manager import get_data_manager
        dm = get_data_manager()
    except Exception as e:  # noqa: BLE001
        logger.warning('[持仓] 数据管理器初始化失败，跳过数据补齐: %s', e)
        summary['failed'] = [c for at in ('stock', 'etf') for c in full_req[at] + inc_req[at]]
        return summary

    logger.info('[持仓] 日线数据补齐需求: 全量 %s / 增量 %s',
                summary['full'], summary['incremental'])

    for at in ('stock', 'etf'):
        for codes, is_full in ((full_req.get(at) or [], True), (inc_req.get(at) or [], False)):
            if not codes:
                continue
            try:
                res = dm.sync_codes_daily(codes, asset_type=at, full=is_full)
                summary['synced'].extend(res.get('synced') or [])
                summary['failed'].extend(res.get('failed') or [])
                summary['skipped'].extend(res.get('skipped') or [])
            except Exception as e:  # noqa: BLE001
                logger.warning('[持仓] %s 日线补齐失败: %s', at, e)
                summary['failed'].extend(codes)
    return summary


# ==================== 账户 ====================


def create_account(account_name: str, initial_capital: float,
                   risk_ratio_per_trade: Optional[float] = None) -> Dict[str, Any]:
    name = (account_name or '').strip()
    if not name:
        raise PositionError('账户名称不能为空')
    try:
        capital = float(initial_capital)
    except (TypeError, ValueError):
        raise PositionError('初始资金必须是数字')
    if capital <= 0:
        raise PositionError('初始资金必须大于 0')

    p = _get_params()
    ratio = float(risk_ratio_per_trade) if risk_ratio_per_trade is not None else p['risk_ratio_per_trade']
    if not (0 < ratio <= 0.5):
        raise PositionError('单笔风险比例必须在 0 ~ 50% 之间')

    repo = get_position_repo()
    repo.ensure_indexes()
    is_first = repo.count_accounts() == 0
    acct = repo.create_account(name, capital, ratio)
    # 新账户默认启用；禁用后该账户持仓不再产生顶部预警、也不参与批量刷新监控
    repo.update_account(acct['account_id'], {'is_disable': False})
    acct['is_disable'] = False
    if is_first:
        # 第一个账户默认设为主账户（进入持仓页默认展示）
        repo.set_primary(acct['account_id'])
        acct['is_primary'] = True
    logger.info('[持仓] 创建账户 %s(%s) 初始资金 %s', name, acct['account_id'], capital)
    return _decorate_account(acct)


def _account_open_positions(account_id: str) -> List[Dict[str, Any]]:
    return get_position_repo().list_open_positions(account_id)


def _live_quote_map(positions: List[Dict[str, Any]]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """批量取最新日线 → {(asset_type, code): bar}"""
    repo = get_position_repo()
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    grouped: Dict[str, List[str]] = {}
    for pos in positions:
        grouped.setdefault(pos.get('asset_type') or 'stock', []).append(pos['stock_code'])
    for asset_type, codes in grouped.items():
        for code, bar in repo.get_latest_bars(codes, asset_type).items():
            out[(asset_type, code)] = bar
    return out


def _decorate_account(acct: Dict[str, Any], quotes: Optional[Dict] = None) -> Dict[str, Any]:
    """补算账户实时权益与盈亏"""
    acct = dict(acct)
    positions = get_position_repo().list_positions(account_id=acct['account_id'])
    if quotes is None:
        quotes = _live_quote_map([p for p in positions if p.get('status') == 'OPEN'])

    rows = []
    for pos in positions:
        asset_type = pos.get('asset_type') or 'stock'
        dec = _price_dec(asset_type)
        bar = quotes.get((asset_type, pos['stock_code']))
        ratio = 1.0
        try:
            ratio, _ = _anchor_ratio(pos, _load_bars(pos['stock_code'], asset_type, pos['buy_date']))
        except Exception:
            pass
        cost = round(float(pos['buy_price']) * ratio, dec)
        snap = pos.get('snapshot') or {}
        rows.append({
            **pos,
            'buy_price_adj': cost,
            'status': pos.get('status'),
            'remaining_shares': _remaining_shares(pos),
            'sold_shares': int(pos.get('buy_shares') or 0) - _remaining_shares(pos),
            'close': (bar or {}).get('close'),
            'trade_date': (bar or {}).get('trade_date'),
            'current_stop_loss_price': snap.get('current_stop_loss_price'),
            'realized_pnl': sum((x['realized_pnl'] or 0) for x in _normalize_sells(pos)) or pos.get('realized_pnl'),
        })

    agg = pr.aggregate_account(
        acct.get('current_cash', 0), rows,
        initial_capital=acct.get('initial_capital', 0),
        risk_ratio_per_trade=acct.get('risk_ratio_per_trade', 0.005),
    )
    return {**acct, **agg, 'account_id': acct['account_id'],
            'account_name': acct['account_name'],
            'is_disable': bool(acct.get('is_disable', False)),
            'is_primary': bool(acct.get('is_primary', False)),
            'created_at': acct.get('created_at')}


def list_accounts() -> List[Dict[str, Any]]:
    repo = get_position_repo()
    accounts = repo.list_accounts()
    if not accounts:
        return []
    all_open = repo.list_open_positions()
    quotes = _live_quote_map(all_open)
    return [_decorate_account(a, quotes) for a in accounts]


def get_account(account_id: str) -> Dict[str, Any]:
    acct = get_position_repo().get_account(account_id)
    if not acct:
        raise PositionError('账户不存在', 404)
    return _decorate_account(acct)


def update_account(account_id: str, account_name: Optional[str] = None,
                   risk_ratio_per_trade: Optional[float] = None,
                   capital_delta: Optional[float] = None,
                   is_disable: Optional[bool] = None,
                   is_primary: Optional[bool] = None) -> Dict[str, Any]:
    repo = get_position_repo()
    acct = repo.get_account(account_id)
    if not acct:
        raise PositionError('账户不存在', 404)

    fields: Dict[str, Any] = {}
    if is_disable is not None:
        fields['is_disable'] = bool(is_disable)
    if is_primary is not None:
        # 主账户全局唯一：设为主账户时清除其它账户的标记
        if is_primary:
            repo.set_primary(account_id)
        else:
            repo.clear_primary(account_id)
    if account_name is not None:
        name = account_name.strip()
        if not name:
            raise PositionError('账户名称不能为空')
        fields['account_name'] = name
    if risk_ratio_per_trade is not None:
        r = float(risk_ratio_per_trade)
        if not (0 < r <= 0.5):
            raise PositionError('单笔风险比例必须在 0 ~ 50% 之间')
        fields['risk_ratio_per_trade'] = r
    if capital_delta:
        delta = float(capital_delta)
        new_cash = float(acct.get('current_cash', 0)) + delta
        if new_cash < 0:
            raise PositionError('出入金后可用现金不能为负')
        fields['current_cash'] = round(new_cash, 2)
        if delta > 0:
            fields['initial_capital'] = round(float(acct.get('initial_capital', 0)) + delta, 2)

    if fields:
        repo.update_account(account_id, fields)
        if 'is_disable' in fields:
            # 禁用/启用要立即生效，不能等预警缓存 TTL
            invalidate_alert_cache()
    return get_account(account_id)


def delete_account(account_id: str, force: bool = False) -> None:
    """删除账户

    Args:
        force: False 时，账户下仍有持仓则拒绝（409）；
               True 时一并删除该账户下所有持仓记录（含已平仓），不可撤销。
    """
    repo = get_position_repo()
    if not repo.get_account(account_id):
        raise PositionError('账户不存在', 404)

    positions = repo.list_positions(account_id=account_id)
    if positions:
        if not force:
            raise PositionError(
                f'该账户下仍有 {len(positions)} 笔持仓（含已平仓记录），'
                f'如需一并删除请使用「删除账户」并确认', 409)
        for pos in positions:
            repo.delete_position(pos['position_id'])
        logger.info('[持仓] 删除账户 %s，级联删除 %s 笔持仓', account_id, len(positions))

    repo.delete_account(account_id)
    invalidate_alert_cache()
    invalidate_alert_cache()


def get_dashboard(account_id: str) -> Dict[str, Any]:
    """账户级风控看板 + 实时持仓明细"""
    acct = get_account(account_id)
    positions = list_positions(account_id=account_id)
    return {
        'account': acct,
        'positions': [p for p in positions if p['status'] == 'OPEN'],
        'closed_count': sum(1 for p in positions if p['status'] == 'CLOSED'),
        'alerts': [p for p in positions if p['status'] == 'OPEN' and p.get('action') in ALERT_ACTIONS],
    }


# ==================== 建仓 ====================


def preview_entry(account_id: str, stock_code: str, buy_date: Any,
                  buy_price: Any, buy_shares: Any) -> Dict[str, Any]:
    """建仓预览（不落库）"""
    repo = get_position_repo()
    acct = repo.get_account(account_id)
    if not acct:
        raise PositionError('账户不存在', 404)

    asset = repo.find_asset(stock_code)
    if not asset:
        raise PositionError(f'未找到代码 {stock_code}（个股/ETF）', 404)
    asset_type = asset['asset_type']
    dec = _price_dec(asset_type)

    date = _norm_date(buy_date, '买入日期')
    if date > _now().strftime('%Y%m%d'):
        raise PositionError('买入日期不能晚于今天')

    # 建仓日行情：不再硬性要求存在。
    #   - 非交易日 → 直接拒绝
    #   - 是交易日但行情还没同步（如当天刚买、一键更新未跑）→ 允许建仓，
    #     ATR 用买入日之前的历史算（本来就不需要当天数据），
    #     复权锚点退回「买入日之前最后一根收盘价」，剩余数据交给「刷新监控」补齐
    from app.data.holidays import is_workday

    bar = repo.get_bar(asset['code'], asset_type, date)
    data_pending = bar is None
    if data_pending:
        if not is_workday(date):
            raise PositionError(f'{date} 不是交易日，请重新选择买入日期', 400)
        if not repo.get_latest_bar_before(asset['code'], asset_type, date):
            raise PositionError(
                f'{asset["code"]} 在 {date} 及之前都没有日线数据，无法计算 ATR，请先同步该股历史', 400)

    try:
        shares = pr.validate_shares(buy_shares)
    except pr.RiskDataError as e:
        raise PositionError(str(e))
    try:
        price = round(float(buy_price), dec)
    except (TypeError, ValueError):
        raise PositionError('买入价必须是数字')
    if price <= 0:
        raise PositionError('买入价必须大于 0')

    bars = _load_bars(asset['code'], asset_type, date, end_date=date)
    equity = _account_equity(account_id)

    try:
        result = pr.preview_entry(bars, date, price, shares, equity,
                                  params=_get_params(), price_dec=dec, asset_type=asset_type)
    except pr.RiskDataError as e:
        raise PositionError(str(e))

    # 行情缺失时用「买入日之前最后一根」当锚点与参考价
    ref_bar = bar or repo.get_latest_bar_before(asset['code'], asset_type, date) or {}
    anchor_close = (ref_bar.get('close') if ref_bar else None) or price

    result.update({
        'stock_code': asset['code'],
        'stock_name': asset['name'],
        'asset_type': asset_type,
        'price_dec': dec,
        'anchor_close': anchor_close,
        'current_price': ref_bar.get('close') if ref_bar else None,
        'data_pending': data_pending,
        'current_cash': round(float(acct.get('current_cash', 0)), 2),
        'cash_sufficient': price * shares <= float(acct.get('current_cash', 0)) + 1e-6,
    })
    if data_pending:
        result['messages'].append(
            f'{date} 的行情尚未同步（不影响建仓）。建仓后点「刷新监控」会自动补齐该股日线，'
            f'补齐前止损轨迹暂不可用。'
        )
    if not result['cash_sufficient']:
        result['messages'].append(
            f'可用现金 {float(acct.get("current_cash", 0)):,.2f} 元 < 本次买入金额 '
            f'{price * shares:,.2f} 元，请确认是否已记录入金。'
        )
    return result


def get_bar_info(stock_code: str, trade_date: Any) -> Dict[str, Any]:
    """查某标的在指定交易日的 OHLC（建仓/平仓弹窗自动带出收盘价用）"""
    repo = get_position_repo()
    asset = repo.find_asset(stock_code)
    if not asset:
        raise PositionError(f'未找到代码 {stock_code}（个股/ETF）', 404)
    date = _norm_date(trade_date, '日期')
    bar = repo.get_bar(asset['code'], asset['asset_type'], date)
    if not bar:
        from app.data.holidays import is_workday
        if not is_workday(date):
            raise PositionError(f'{date} 不是交易日', 404)
        raise PositionError(f'{date} 的行情尚未同步，请手动填写价格（刷新监控后会自动补齐）', 404)
    dec = _price_dec(asset['asset_type'])
    rnd = lambda v: None if v is None else round(float(v), dec)  # noqa: E731
    return {
        'stock_code': asset['code'],
        'stock_name': asset['name'],
        'asset_type': asset['asset_type'],
        'trade_date': date,
        'price_dec': dec,
        'open': rnd(bar['open']),
        'high': rnd(bar['high']),
        'low': rnd(bar['low']),
        'close': rnd(bar['close']),
    }


def _account_equity(account_id: str) -> float:
    """账户当前总权益 = 可用现金 + Σ(最新收盘 × 剩余股数)

    直接复用看板的计算口径，避免"建仓前校验用的权益"与"看板显示的权益"出现漂移。
    （旧实现用的是 buy_shares 且多乘了一个复权比例 ratio，分红/分批卖出后都会偏。）
    """
    acct = get_position_repo().get_account(account_id)
    if not acct:
        raise PositionError('账户不存在', 404)
    return float(_decorate_account(acct)['current_equity'])


def create_position(account_id: str, stock_code: str, buy_date: Any, buy_price: Any,
                    buy_shares: Any, force: bool = False,
                    note: Optional[str] = None) -> Dict[str, Any]:
    """建仓（扣减现金 + 冻结风控参数 + 生成快照）"""
    preview = preview_entry(account_id, stock_code, buy_date, buy_price, buy_shares)

    if preview['risk_check_status'] == pr.RISK_REJECT and not force:
        raise PositionError('风险校验未通过：' + ' '.join(preview['messages']),
                            409, payload=preview)
    if preview['risk_check_status'] == pr.RISK_WARN and not force:
        raise PositionError('风险超标，需要确认后建仓', 409, payload=preview)

    repo = get_position_repo()
    doc = {
        'account_id': account_id,
        'stock_code': preview['stock_code'],
        'stock_name': preview['stock_name'],
        'asset_type': preview['asset_type'],
        'buy_date': preview['buy_date'],
        'buy_price': preview['buy_price'],
        'buy_shares': preview['buy_shares'],
        'anchor_close': preview['anchor_close'],
        'atr_entry': preview['atr_entry'],
        'initial_stop_loss_price': preview['initial_stop_loss_price'],
        'take_profit_reference_price': preview['take_profit_reference_price'],
        'suggested_max_shares': preview['suggested_max_shares'],
        'risk_check_status': preview['risk_check_status'],
        'note': (note or '').strip() or None,
    }
    pos = repo.create_position(doc)
    repo.adjust_account_cash(account_id, -preview['position_value'])
    logger.info('[持仓] 建仓 %s %s @%s×%s (账户 %s, 风险校验 %s)',
                preview['stock_code'], preview['stock_name'], preview['buy_price'],
                preview['buy_shares'], account_id, preview['risk_check_status'])

    _refresh_one(pos['position_id'], silent=True)
    invalidate_alert_cache()
    return get_position_detail(pos['position_id'])


# ==================== 平仓 ====================


def sell_position(position_id: str, sell_date: Any, sell_price: Any,
                  shares: Any = None, reason: str = 'manual',
                  note: Optional[str] = None) -> Dict[str, Any]:
    """卖出（支持分批）：只卖部分股数时持仓保持 OPEN，卖完才转 CLOSED

    Args:
        position_id: 持仓 ID
        sell_date: 卖出日期 YYYYMMDD
        sell_price: 卖出价
        shares: 卖出股数；None / 空 表示把剩余股数全部卖出
        reason: 'take_profit'(主动减仓) / 'stop_loss'(被动止损) / 'manual'(手动)
        note: 备注

    规则（A 股）：
        - 卖出不要求 100 股整数倍（与买入不同）
        - 余额不足 100 股的部分属于零股，下次必须一次性卖完（仅提示不拦截）
        - 每笔卖出都受 T+1 约束（个股：卖出日 > 买入日；ETF 为 T+0）
        - 卖出日期不能早于上一笔卖出日期，且必须是交易日
        - 系统不做自动平仓，全部由用户触发
    """
    repo = get_position_repo()
    pos = repo.get_position(position_id)
    if not pos:
        raise PositionError('持仓不存在', 404)
    status = (pos.get('status') or '').upper()
    remaining = _remaining_shares(pos)
    if status != 'OPEN' or remaining <= 0:
        raise PositionError('该持仓已全部卖出', 409)

    asset_type = pos.get('asset_type') or 'stock'
    dec = _price_dec(asset_type)
    date = _norm_date(sell_date, '卖出日期')
    if date < pos['buy_date']:
        raise PositionError('卖出日期不能早于买入日期')
    if asset_type == 'stock' and date == pos['buy_date']:
        raise PositionError('A 股 T+1：买入当日不能卖出（ETF 除外）')
    if date > _now().strftime('%Y%m%d'):
        raise PositionError('卖出日期不能晚于今天')

    prev_sells = _normalize_sells(pos)
    if prev_sells and date < prev_sells[-1]['sell_date']:
        raise PositionError(f'卖出日期不能早于上一笔卖出（{_fmt_date(prev_sells[-1]["sell_date"])}）')

    # 卖出股数
    if shares is None or (isinstance(shares, str) and not shares.strip()):
        qty = remaining
    else:
        qty = int(pr._to_float(shares) or 0)
        if qty <= 0:
            raise PositionError('卖出股数必须大于 0')
        if qty > remaining:
            raise PositionError(f'卖出股数 {qty} 超过剩余持仓 {remaining} 股')

    bar = repo.get_bar(pos['stock_code'], asset_type, date)
    if not bar:
        raise PositionError(f'{date} 不是 {pos["stock_code"]} 的交易日（或该日停牌无行情）', 400)

    try:
        price = round(float(sell_price), dec)
    except (TypeError, ValueError):
        raise PositionError('卖出价必须是数字')
    if price <= 0:
        raise PositionError('卖出价必须大于 0')

    if reason not in SELL_REASONS:
        reason = 'manual'

    buy_price = float(pos['buy_price'])
    realized = round((price - buy_price) * qty, 2)
    cost = buy_price * qty
    left = remaining - qty

    warnings: List[str] = []
    if 0 < left < 100 and asset_type == 'stock':
        warnings.append(f'卖出后剩余 {left} 股为零股，下次必须一次性全部卖出')

    new_sells = prev_sells + [{
        'sell_id': f's{len(prev_sells) + 1}',
        'sell_date': date,
        'sell_price': price,
        'shares': qty,
        'realized_pnl': realized,
        'return_ratio': round(realized / cost, 6) if cost else None,
        'reason': reason,
        'note': (note or '').strip() or None,
        'created_at': _now(),
    }]
    sold_shares = sum(x['shares'] for x in new_sells)
    realized_total = round(sum((x['realized_pnl'] or 0) for x in new_sells), 2)
    realized_cost = round(buy_price * sold_shares, 2)
    avg_sell = round(sum((x['sell_price'] or 0) * x['shares'] for x in new_sells) / sold_shares, dec)

    # 持仓交易日数（含买入日，算到本次卖出日）
    replay = _replay({**pos, 'sells': new_sells, 'status': 'OPEN'}, end_date=date)
    holding_days = len(replay['states'])

    fields: Dict[str, Any] = {
        'sells': new_sells,
        'sold_shares': sold_shares,
        'remaining_shares': left,
        'realized_pnl': realized_total,
        'realized_cost': realized_cost,
        'return_ratio': round(realized_total / realized_cost, 6) if realized_cost else None,
        'avg_sell_price': avg_sell,
        'sell_date': date,
        'sell_price': price,
        'last_sell_date': date,
        'last_sell_price': price,
        'holding_days': holding_days,
        'last_updated': _now(),
    }
    if left == 0:
        fields.update({
            'status': 'CLOSED',
            'holding_calendar_days':
                (datetime.strptime(date, '%Y%m%d') - datetime.strptime(pos['buy_date'], '%Y%m%d')).days + 1,
            'close_note': (note or '').strip() or None,
            'closed_at': _now(),
        })

    repo.adjust_account_cash(pos['account_id'], price * qty)
    repo.update_position(position_id, fields)
    invalidate_alert_cache()
    _refresh_one(position_id, silent=True)

    logger.info('[持仓] 卖出 %s %s %s股 @%s（理由 %s）→ 本笔盈亏 %s，剩余 %s 股',
                pos['stock_code'], pos['stock_name'], qty, price, reason, realized, left)

    detail = get_position_detail(position_id)
    if warnings:
        detail['warnings'] = warnings
    return detail


def revoke_sell(position_id: str, sell_id: str) -> Dict[str, Any]:
    """撤回一笔卖出记录：现金反向回滚、持仓恢复、状态与统计重算

    注意：
      - 撤回后该笔卖出的「已实现盈亏」会被回吐，累计已实现按剩余卖出记录重算
      - 若撤回后仍有剩余股数 → 持仓恢复为 OPEN，重新纳入风控监控
      - 撤回会把卖出收到的现金从账户里扣回（可能因此变成负现金，属正常记录现象）
    """
    repo = get_position_repo()
    pos = repo.get_position(position_id)
    if not pos:
        raise PositionError('持仓不存在', 404)

    asset_type = pos.get('asset_type') or 'stock'
    dec = _price_dec(asset_type)
    sells = _normalize_sells(pos)
    idx = next((i for i, x in enumerate(sells) if x['sell_id'] == sell_id), None)
    if idx is None:
        raise PositionError('卖出记录不存在', 404)

    rec = sells.pop(idx)
    rec_shares = int(rec['shares'])
    rec_price = float(rec['sell_price'] or 0)

    buy_price = float(pos['buy_price'])
    sold_shares = sum(x['shares'] for x in sells)
    realized_total = round(sum((x['realized_pnl'] or 0) for x in sells), 2)
    realized_cost = round(buy_price * sold_shares, 2)
    remaining = max(int(pos['buy_shares']) - sold_shares, 0)

    fields: Dict[str, Any] = {
        'sells': [{k: v for k, v in x.items() if k not in ('return_ratio', 'reason_label')}
                  for x in sells],
        'sold_shares': sold_shares,
        'remaining_shares': remaining,
        'realized_pnl': realized_total,
        'realized_cost': realized_cost,
        'return_ratio': round(realized_total / realized_cost, 6) if realized_cost else None,
        'avg_sell_price': (round(sum((x['sell_price'] or 0) * x['shares'] for x in sells) / sold_shares, dec)
                           if sold_shares else None),
        'last_sell_date': sells[-1]['sell_date'] if sells else None,
        'last_sell_price': sells[-1]['sell_price'] if sells else None,
        'sell_date': sells[-1]['sell_date'] if sells else None,
        'sell_price': sells[-1]['sell_price'] if sells else None,
        'last_updated': _now(),
    }
    if remaining > 0:
        # 恢复为活跃持仓，重新纳入监控
        fields.update({
            'status': 'OPEN',
            'closed_at': None,
            'holding_calendar_days': None,
            'close_note': None,
        })

    repo.adjust_account_cash(pos['account_id'], -(rec_price * rec_shares))
    repo.update_position(position_id, fields)
    invalidate_alert_cache()
    _refresh_one(position_id, silent=True)

    logger.info('[持仓] 撤回卖出 %s %s %s股 @%s → 剩余 %s 股',
                pos['stock_code'], pos['stock_name'], rec_shares, rec_price, remaining)

    detail = get_position_detail(position_id)
    cash = float(repo.get_account(pos['account_id']).get('current_cash', 0))
    if cash < 0:
        detail['warnings'] = [f'撤回后该账户可用现金为 {cash:.2f}，已为负，请核对出入金记录']
    return detail


def close_position(position_id: str, sell_date: Any, sell_price: Any,
                   note: Optional[str] = None) -> Dict[str, Any]:
    """全平（兼容旧接口）：等价于把剩余股数一次性全部卖出"""
    return sell_position(position_id, sell_date, sell_price,
                         shares=None, reason='manual', note=note)


# ==================== 查询 / 快照 ====================


def _enrich(pos: Dict[str, Any], quotes: Optional[Dict] = None) -> Dict[str, Any]:
    """单笔持仓 → 补全实时风控字段（失败时降级为快照）"""
    asset_type = pos.get('asset_type') or 'stock'
    dec = _price_dec(asset_type)
    out = dict(pos)
    out['status'] = (pos.get('status') or 'OPEN').upper()
    out['price_dec'] = dec
    end_date = pos['sell_date'] if out['status'] == 'CLOSED' else None

    try:
        replay = _replay(pos, end_date=end_date)
        states = replay['states']
        snap = pr.summarize_day(states[-1]) if states else {}
        cost = replay['buy_price_adj']
        ratio = replay['ratio']

        # ⚠ 分批卖出后：浮盈/风险金额必须按「剩余股数」算
        shares = _position_shares(pos)
        buy_shares = int(pos['buy_shares'])
        price = snap.get('current_price')
        init_stop = pos.get('initial_stop_loss_price')
        tp = pos.get('take_profit_reference_price')

        sells = _normalize_sells(pos)
        sold_shares = sum(x['shares'] for x in sells)
        realized_total = round(sum((x['realized_pnl'] or 0) for x in sells), 2)
        realized_cost = round(float(pos['buy_price']) * sold_shares, 2)
        avg_sell = (round(sum((x['sell_price'] or 0) * x['shares'] for x in sells) / sold_shares, dec)
                    if sold_shares else None)
        for x in sells:
            base = float(pos['buy_price']) * x['shares']
            x['return_ratio'] = (round(((x['realized_pnl'] or 0)) / base, 6) if base else None)
            x['reason_label'] = SELL_REASON_LABEL.get(x['reason'], x['reason'])

        # ⚠ 严格区分两类事件：
        #   硬性止损（gap/intraday/close）—— 风险事件
        #   止盈参考（take_profit_ref）    —— 正面信号，绝不能算作"止损触发"
        stop_days = [s for s in states if STOP_EVENTS & set(s.get('events') or [])]
        tp_days = [s for s in states if 'take_profit_ref' in (s.get('events') or [])]
        first_stop = stop_days[0] if stop_days else None
        first_tp = tp_days[0] if tp_days else None

        out.update({
            'buy_price_adj': cost,
            'adjust_ratio': round(ratio, 8),
            'initial_stop_loss_price_adj': None if init_stop is None else round(float(init_stop) * ratio, dec),
            'take_profit_reference_price_adj': None if tp is None else round(float(tp) * ratio, dec),
            'trade_date': snap.get('trade_date'),
            'current_price': price,
            'atr_current': snap.get('atr_current'),
            'highest_since_entry': snap.get('highest_since_entry'),
            'current_stop_loss_price': snap.get('current_stop_loss_price'),
            'mtr_current': snap.get('mtr_current'),
            'mtr_mean': snap.get('mtr_mean'),
            'mtr_std': snap.get('mtr_std'),
            'mtr_filter_status': snap.get('mtr_filter_status'),
            'action': snap.get('action'),
            'action_suggestion': snap.get('action_suggestion'),
            'unrealized_pnl': None if price is None else round((price - cost) * shares, 2),
            'unrealized_return_ratio': None if not cost else round((price - cost) / cost, 6),
            'position_risk_amount': snap.get('risk_amount'),
            'current_rr': snap.get('current_rr'),
            # ---- 分批卖出 ----
            'sells': sells,
            'sell_count': len(sells),
            'buy_shares': buy_shares,
            'sold_shares': sold_shares,
            'remaining_shares': shares,
            'avg_sell_price': avg_sell,
            'realized_pnl': realized_total,
            'realized_cost': realized_cost,
            'realized_pnl_ratio': (round(realized_total / realized_cost, 6) if realized_cost else None),
            'last_sell_date': sells[-1]['sell_date'] if sells else None,
            'last_sell_price': sells[-1]['sell_price'] if sells else None,
            # ---- 硬性止损触发（首次 + 累计次数）----
            'stop_trigger_date': first_stop['trade_date'] if first_stop else None,
            'stop_trigger_action': first_stop['action'] if first_stop else None,
            'stop_trigger_price': first_stop['current_stop_loss_price'] if first_stop else None,
            'stop_trigger_count': len(stop_days),
            # ---- 动态止盈（以最高价×(1-回撤%)为离场线，浮盈达档位后接管）----
            'dynamic_tp_price': snap.get('dynamic_tp_price'),
            'dynamic_tp_armed': snap.get('dynamic_tp_armed'),
            'gain_r': snap.get('gain_r'),
            'exit_line_price': (states[-1].get('exit_line_price') if states else None),
            # ---- 止盈参考触发（首次 + 累计次数）----
            'take_profit_hit_date': first_tp['trade_date'] if first_tp else None,
            'take_profit_hit_price': first_tp['take_profit_reference_price'] if first_tp else None,
            'take_profit_hit_count': len(tp_days),
            'latest_events': (states[-1].get('events') or []) if states else [],
            'holding_days': len(states),
            'holding_calendar_days': _calendar_days(pos.get('buy_date'), snap.get('trade_date')),
            'error': None,
        })
        if out['status'] == 'CLOSED':
            out['action'] = '已平仓'
            out['action_suggestion'] = '该持仓已平仓，已停止风控监控。'
            out['latest_events'] = []

            # ---- 清仓后表现：卖飞了还是卖对了 ----
            try:
                repo = get_position_repo()
                latest = repo.get_latest_bar(pos['stock_code'], asset_type)
                sell_px = pr._to_float(pos.get('avg_sell_price') or pos.get('sell_price'))
                sell_day = pos.get('sell_date')
                if latest and latest.get('trade_date') and sell_px and sell_day:
                    px_now = pr._to_float(latest['close'])
                    if px_now is not None and px_now > 0:
                        out['post_exit_price'] = round(px_now, dec)
                        out['post_exit_date'] = latest['trade_date']
                        out['post_exit_change_pct'] = round((px_now / sell_px - 1) * 100, 2)
                        out['post_exit_pnl'] = round((px_now - sell_px) * sold_shares, 2)
                        try:
                            dates = repo.get_trade_dates(pos['stock_code'], asset_type,
                                                         sell_day, latest['trade_date'])
                            out['post_exit_days'] = max(len(dates) - 1, 0)
                        except Exception:
                            out['post_exit_days'] = None
            except Exception as e:  # noqa: BLE001
                logger.debug('[持仓] 清仓后表现计算失败 %s: %s', pos.get('position_id'), e)
    except Exception as e:  # noqa: BLE001 单笔失败不拖垮整个列表
        logger.warning('[持仓] 回算失败 %s: %s', pos.get('position_id'), e)
        snap = pos.get('snapshot') or {}
        out.update({
            'buy_price_adj': pos.get('buy_price'),
            'adjust_ratio': 1.0,
            'initial_stop_loss_price_adj': pos.get('initial_stop_loss_price'),
            'take_profit_reference_price_adj': pos.get('take_profit_reference_price'),
            'current_price': snap.get('current_price'),
            'atr_current': snap.get('atr_current'),
            'highest_since_entry': snap.get('highest_since_entry'),
            'current_stop_loss_price': snap.get('current_stop_loss_price'),
            'mtr_filter_status': snap.get('mtr_filter_status'),
            'action': snap.get('action') or '数据缺失',
            'action_suggestion': snap.get('action_suggestion') or str(e),
            'unrealized_pnl': snap.get('unrealized_pnl'),
            'unrealized_return_ratio': None,
            'position_risk_amount': snap.get('risk_amount'),
            'current_rr': snap.get('current_rr'),
            'stop_trigger_date': None,
            'stop_trigger_action': None,
            'stop_trigger_price': None,
            'stop_trigger_count': 0,
            'take_profit_hit_date': None,
            'take_profit_hit_price': None,
            'take_profit_hit_count': 0,
            'latest_events': [],
            'sells': _normalize_sells(pos),
            'sell_count': len(_normalize_sells(pos)),
            'buy_shares': int(pos.get('buy_shares') or 0),
            'sold_shares': int(pos.get('buy_shares') or 0) - _remaining_shares(pos),
            'remaining_shares': _remaining_shares(pos),
            'avg_sell_price': pos.get('avg_sell_price'),
            'realized_pnl': pos.get('realized_pnl'),
            'realized_cost': pos.get('realized_cost'),
            'realized_pnl_ratio': pos.get('return_ratio'),
            'last_sell_date': pos.get('sell_date'),
            'last_sell_price': pos.get('sell_price'),
            'holding_days': None,
            'error': str(e),
        })
    return out


def list_positions(account_id: Optional[str] = None, status: Optional[str] = None,
                   keyword: Optional[str] = None) -> List[Dict[str, Any]]:
    repo = get_position_repo()
    positions = repo.list_positions(account_id=account_id, status=status)
    if keyword:
        kw = keyword.strip().lower()
        positions = [p for p in positions
                     if kw in (p.get('stock_code') or '').lower()
                     or kw in (p.get('stock_name') or '').lower()]
    quotes = _live_quote_map([p for p in positions if (p.get('status') or '') == 'OPEN'])
    return [_enrich(p, quotes) for p in positions]


def get_position_detail(position_id: str) -> Dict[str, Any]:
    pos = get_position_repo().get_position(position_id)
    if not pos:
        raise PositionError('持仓不存在', 404)
    out = _enrich(pos)
    try:
        replay = _replay(pos, end_date=pos['sell_date'] if out['status'] == 'CLOSED' else None)
        out['chart'] = _build_chart_payload(pos, out, replay)
    except Exception as e:  # noqa: BLE001
        logger.warning('[持仓] 图表数据构建失败 %s: %s', position_id, e)
        out['chart'] = None
    return out


def _build_chart_payload(pos: Dict[str, Any], enriched: Dict[str, Any],
                         replay: Dict[str, Any]) -> Dict[str, Any]:
    """构建 K 线标注数据：买卖点 markers + 止损阶梯线 + 止盈/当前止损参考线"""
    dec = replay['price_dec']
    states = replay['states']
    buy_date = pos['buy_date']
    shares = int(pos['buy_shares'])

    markers: List[Dict[str, Any]] = [{
        'date': buy_date,
        'position': 'belowBar',
        'shape': 'arrowUp',
        'color': '#ef5350',
        'text': f'买入 {round(float(pos["buy_price"]), dec)}×{shares}',
    }]

    # 卖出标记：分批卖出 → 每个卖出日一个 ▼，同日多笔合并
    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for x in _normalize_sells(pos):
        by_date.setdefault(x['sell_date'], []).append(x)
    for sell_day, items in sorted(by_date.items()):
        tot = sum(i['shares'] for i in items)
        if tot <= 0:
            continue
        pnl = sum((i['realized_pnl'] or 0) for i in items)
        px = round(sum((i['sell_price'] or 0) * i['shares'] for i in items) / tot, dec)
        reasons = {i['reason'] for i in items}
        color = '#f59e0b' if reasons == {'stop_loss'} else ('#22c55e' if reasons == {'take_profit'} else '#26a69a')
        more = f' ×{len(items)}笔' if len(items) > 1 else ''
        sign = '+' if pnl >= 0 else ''
        markers.append({
            'date': sell_day,
            'position': 'aboveBar',
            'shape': 'arrowDown',
            'color': color,
            'text': f'卖出 {tot}股 @{px}{more} {sign}{pnl:,.0f}',
        })

    # 历史事件标注：硬性止损（风险）与止盈参考（正面）必须分开画
    # 已平仓持仓同样标注（持仓期内若曾触发止损而未离场，是有价值的纪律反馈）
    if states:
        stop_days = [s for s in states if STOP_EVENTS & set(s.get('events') or [])]
        if stop_days:
            first = stop_days[0]
            more = f' 等{len(stop_days)}次' if len(stop_days) > 1 else ''
            markers.append({
                'date': first['trade_date'],
                'position': 'aboveBar',
                'shape': 'circle',
                'color': '#f59e0b',
                'text': f'止损触发 {first["current_stop_loss_price"]}{more}',
            })
        dyn_days = [s for s in states if 'dynamic_tp_hit' in (s.get('events') or [])]
        if dyn_days:
            first = dyn_days[0]
            markers.append({
                'date': first['trade_date'],
                'position': 'aboveBar',
                'shape': 'square',
                'color': '#a855f7',
                'text': f'动态止盈 {first["dynamic_tp_price"]}',
            })
        tp_days = [s for s in states if 'take_profit_ref' in (s.get('events') or [])]
        if tp_days:
            first = tp_days[0]
            more = f' 等{len(tp_days)}次' if len(tp_days) > 1 else ''
            markers.append({
                'date': first['trade_date'],
                'position': 'belowBar',
                'shape': 'circle',
                'color': '#22c55e',
                'text': f'止盈参考 {first["take_profit_reference_price"]}{more}',
            })

    # 止损阶梯线
    stop_series = [{'date': s['trade_date'], 'value': s['current_stop_loss_price']}
                   for s in states if s.get('current_stop_loss_price') is not None]

    # 动态止盈阶梯线（只在浮盈达标、止盈档启用后才有值）
    dynamic_tp_series = [{'date': s['trade_date'], 'value': s['dynamic_tp_price']}
                         for s in states if s.get('dynamic_tp_price') is not None]

    price_lines: List[Dict[str, Any]] = []
    cur_stop = enriched.get('current_stop_loss_price')
    if cur_stop is not None:
        price_lines.append({
            'price': cur_stop, 'color': '#ef5350', 'lineStyle': 2, 'lineWidth': 1,
            'title': f'当前止损 {cur_stop}', 'axisLabelVisible': True,
        })
    tp = enriched.get('take_profit_reference_price_adj')
    if tp is not None:
        price_lines.append({
            'price': tp, 'color': '#22c55e', 'lineStyle': 3, 'lineWidth': 1,
            'title': f'止盈参考 {tp}', 'axisLabelVisible': True,
        })
    init_stop = enriched.get('initial_stop_loss_price_adj')
    if init_stop is not None and init_stop != cur_stop:
        price_lines.append({
            'price': init_stop, 'color': '#9ca3af', 'lineStyle': 1, 'lineWidth': 1,
            'title': f'初始止损 {init_stop}', 'axisLabelVisible': True,
        })

    markers.sort(key=lambda m: m.get('date') or '')

    return {
        'markers': markers,
        'price_lines': price_lines,
        'stop_series': stop_series,
        'dynamic_tp_series': dynamic_tp_series,
        'buy_price_line': enriched.get('buy_price_adj'),
        'daily': states,
    }


def get_trajectory(position_id: str) -> Dict[str, Any]:
    """每日风控轨迹（图表 + 明细表）"""
    repo = get_position_repo()
    pos = repo.get_position(position_id)
    if not pos:
        raise PositionError('持仓不存在', 404)
    enriched = _enrich(pos)
    replay = _replay(pos, end_date=pos['sell_date'] if enriched['status'] == 'CLOSED' else None)
    all_bars = replay['bars']
    # 只回传买入日之前 120 根作为图表上下文，避免前端加载上千根 K 线
    start_idx = next((i for i, b in enumerate(all_bars) if b['trade_date'] >= pos['buy_date']), 0)
    ctx_start = max(0, start_idx - 120)
    ctx_bars = all_bars[ctx_start:]

    # ATR 序列：与 bars 完全同日期范围（含买入前上下文），供 K 线 ATR 通道使用。
    # 用全精度值 —— states 里的 atr 是展示用的取整值，画通道会抖成台阶。
    atr_series: List[Dict[str, Any]] = []
    try:
        ind = pr.compute_indicators(all_bars, replay['params'])
        for k, bar in enumerate(ctx_bars):
            val = ind['atr'][ctx_start + k]
            if val is None:
                continue
            atr_series.append({'date': bar['trade_date'], 'value': round(float(val), 4)})
    except Exception as e:  # noqa: BLE001
        logger.warning('[持仓] ATR 序列构建失败: %s', e)

    return {
        'position': enriched,
        'chart': _build_chart_payload(pos, enriched, replay),
        'params': replay['params'],
        'atr_series': atr_series,
        'bars': [{
            'trade_date': b['trade_date'],
            'open': b['open'], 'high': b['high'], 'low': b['low'], 'close': b['close'],
        } for b in ctx_bars],
    }


def _refresh_one(position_id: str, silent: bool = True) -> bool:
    """重算单笔并写回快照"""
    repo = get_position_repo()
    pos = repo.get_position(position_id)
    if not pos:
        return False
    try:
        enriched = _enrich(pos)
        snapshot = {
            'trade_date': enriched.get('trade_date'),
            'current_price': enriched.get('current_price'),
            'atr_current': enriched.get('atr_current'),
            'highest_since_entry': enriched.get('highest_since_entry'),
            'current_stop_loss_price': enriched.get('current_stop_loss_price'),
            'take_profit_reference_price': enriched.get('take_profit_reference_price_adj'),
            'mtr_current': enriched.get('mtr_current'),
            'mtr_mean': enriched.get('mtr_mean'),
            'mtr_std': enriched.get('mtr_std'),
            'mtr_filter_status': enriched.get('mtr_filter_status'),
            'action': enriched.get('action'),
            'action_suggestion': enriched.get('action_suggestion'),
            'unrealized_pnl': enriched.get('unrealized_pnl'),
            'risk_amount': enriched.get('position_risk_amount'),
            'current_rr': enriched.get('current_rr'),
            'adjust_ratio': enriched.get('adjust_ratio'),
            'latest_events': enriched.get('latest_events') or [],
            'stop_trigger_date': enriched.get('stop_trigger_date'),
            'take_profit_hit_date': enriched.get('take_profit_hit_date'),
        }
        repo.update_snapshot(position_id, snapshot)
        return True
    except Exception as e:  # noqa: BLE001
        if not silent:
            raise
        logger.warning('[持仓] 刷新快照失败 %s: %s', position_id, e)
        return False


def refresh_all(account_id: Optional[str] = None) -> Dict[str, Any]:
    """刷新监控：先补齐缺失的日线基础数据，再重算全部持仓快照"""
    repo = get_position_repo()
    all_positions = repo.list_positions(account_id=account_id)
    if not account_id:
        disabled = {a['account_id'] for a in repo.list_accounts() if a.get('is_disable')}
        if disabled:
            all_positions = [p for p in all_positions if p['account_id'] not in disabled]
    data_report = ensure_position_data(all_positions)

    positions = [p for p in all_positions if (p.get('status') or '').upper() == 'OPEN']
    ok = sum(1 for p in positions if _refresh_one(p['position_id']))
    invalidate_alert_cache()
    logger.info('[持仓] 刷新监控 %s 笔，成功 %s 笔，数据补齐 %s 只',
                len(positions), ok, len(data_report.get('synced') or []))
    return {'total': len(positions), 'updated': ok,
            'data': data_report,
            'alerts': get_risk_alerts(account_id=account_id, use_cache=False)}


def refresh_position(position_id: str) -> Dict[str, Any]:
    """重算单笔持仓并返回详情（必要时补齐该标的日线）"""
    repo = get_position_repo()
    pos = repo.get_position(position_id)
    if not pos:
        raise PositionError('持仓不存在', 404)
    data_report = ensure_position_data([pos])
    invalidate_alert_cache()
    _refresh_one(position_id, silent=False)
    detail = get_position_detail(position_id)
    detail['data_report'] = data_report
    return detail


def delete_position(position_id: str) -> None:
    repo = get_position_repo()
    pos = repo.get_position(position_id)
    if not pos:
        raise PositionError('持仓不存在', 404)
    if (pos.get('status') or '').upper() == 'OPEN':
        raise PositionError('活跃持仓不可删除，请先平仓', 409)
    repo.delete_position(position_id)


# ==================== 预警（顶部红点） ====================

_alert_cache: Dict[str, Any] = {'ts': None, 'data': None}
_alert_lock = threading.Lock()
ALERT_TTL_SECONDS = 120


def get_risk_alerts(account_id: Optional[str] = None,
                    use_cache: bool = True) -> List[Dict[str, Any]]:
    """扫描 OPEN 持仓，返回触发止损/跳空/止盈参考的预警列表"""
    now = _now()
    cache_key = account_id or '__all__'
    if use_cache:
        with _alert_lock:
            cached = _alert_cache.get(cache_key)
            if cached and (now - cached['ts']).total_seconds() < ALERT_TTL_SECONDS:
                return cached['data']

    repo = get_position_repo()
    positions = repo.list_open_positions(account_id)
    if not account_id:
        # 未指定账户时跳过已禁用的账户（禁用=不想被打扰）
        disabled = {a['account_id'] for a in repo.list_accounts() if a.get('is_disable')}
        if disabled:
            positions = [p for p in positions if p['account_id'] not in disabled]

    alerts: List[Dict[str, Any]] = []
    for pos in positions:
        enriched = _enrich(pos)
        action = enriched.get('action')
        if action not in ALERT_ACTIONS:
            continue
        level = 'danger' if action in (pr.ACTION_GAP_STOP, pr.ACTION_INTRADAY_STOP,
                                       pr.ACTION_CLOSE_STOP) else 'warning'
        alerts.append({
            'position_id': pos['position_id'],
            'account_id': pos['account_id'],
            'stock_code': pos['stock_code'],
            'stock_name': pos.get('stock_name'),
            'asset_type': pos.get('asset_type') or 'stock',
            'action': action,
            'level': level,
            'trade_date': enriched.get('trade_date'),
            'current_price': enriched.get('current_price'),
            'current_stop_loss_price': enriched.get('current_stop_loss_price'),
            'take_profit_reference_price': enriched.get('take_profit_reference_price_adj'),
            'message': enriched.get('action_suggestion'),
            'unrealized_pnl': enriched.get('unrealized_pnl'),
        })

    alerts.sort(key=lambda a: (a['level'] != 'danger', a['stock_code']))
    # 空结果不缓存：新建仓/平仓后应立刻可见，避免"缓存住空列表"导致红点漏报
    if alerts:
        with _alert_lock:
            _alert_cache[cache_key] = {'ts': now, 'data': alerts}
    else:
        with _alert_lock:
            _alert_cache.pop(cache_key, None)
    return alerts


def invalidate_alert_cache() -> None:
    with _alert_lock:
        _alert_cache.clear()
