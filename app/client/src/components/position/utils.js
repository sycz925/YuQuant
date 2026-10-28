/**
 * 持仓模块共享格式化/映射工具
 * A 股配色约定：涨=红、跌=绿
 */

export const ACTION_META = {
  持仓: { color: 'green', label: '持仓' },
  跳空止损: { color: 'red', label: '跳空止损' },
  盘中止损: { color: 'red', label: '盘中止损' },
  收盘止损: { color: 'magenta', label: '收盘止损' },
  利润保护参考: { color: 'orange', label: '止盈参考' },
  动态止盈: { color: 'purple', label: '动态止盈' },
  MTR过滤: { color: 'blue', label: 'MTR过滤' },
  已平仓: { color: 'default', label: '已平仓' },
  数据缺失: { color: 'default', label: '数据缺失' },
}

/** 需要顶部红点提醒的动作 */
export const ALERT_ACTIONS = new Set(['跳空止损', '盘中止损', '收盘止损', '利润保护参考', '动态止盈'])

export const MTR_META = {
  VALID_EXPANSION: { color: 'red', label: '有效放大' },
  INVALID_NOISE: { color: 'default', label: '无效波动' },
}

export const RISK_META = {
  PASS: { color: 'green', label: '通过' },
  WARN_OVER_RISK: { color: 'orange', label: '风险超标' },
  REJECT: { color: 'red', label: '建议放弃' },
}

const dash = (v) => v === null || v === undefined || v === '' || Number.isNaN(Number(v))

export const fmtPrice = (v, dec = 2) => (dash(v) ? '-' : Number(v).toFixed(dec))

/** 金额：保留 2 位小数，但整数不显示 .00（1234.00 → 1,234） */
export const fmtMoney = (v) => {
  if (dash(v)) return '-'
  const n = Number(v)
  const s = n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return Number.isInteger(n) ? s.replace(/\.00$/, '') : s
}

/** v 为比例（0.0523 → +5.23%） */
export const fmtPct = (v, dec = 2) => {
  if (dash(v)) return '-'
  const n = Number(v) * 100
  return `${n >= 0 ? '+' : ''}${n.toFixed(dec)}%`
}

export const fmtDate = (d) => {
  if (!d) return '-'
  const s = String(d)
  return s.length === 8 && /^\d+$/.test(s) ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6)}` : s
}

/** A 股：正数红、负数绿 */
export const pnlClass = (v) => (dash(v) ? 'text-gray-400' : Number(v) > 0 ? 'text-red-500' : Number(v) < 0 ? 'text-green-500' : 'text-gray-500')

export const pnlStyle = (v) => {
  if (dash(v)) return { color: '#9ca3af' }
  const n = Number(v)
  return { color: n > 0 ? '#ef5350' : n < 0 ? '#26a69a' : '#6b7280' }
}

/** 自然日数 → 更直观的时长（天 / 周 / 月 / 年），整数不带 .0 */
export const fmtHoldingSpan = (calendarDays) => {
  const d = Number(calendarDays)
  if (!isFinite(d) || d <= 0) return ''
  // 保留 1 位小数，但 7.0 → 7、2.0 → 2（整数不显示 .0）
  const trim = (n) => String(Number(n.toFixed(1)))
  if (d < 7) return `${d} 天`
  if (d < 60) return `${trim(d / 7)} 周`
  if (d < 365) return `${trim(d / 30)} 月`
  return `${trim(d / 365)} 年`
}

export const assetLabel = (t) => (t === 'etf' ? 'ETF' : '个股')

/** 建仓/平仓弹窗用：YYYYMMDD ⇄ dayjs */
export const toDayjs = (s) => {
  if (!s) return null
  const str = String(s).replace(/-/g, '')
  if (str.length !== 8) return null
  return `${str.slice(0, 4)}-${str.slice(4, 6)}-${str.slice(6)}`
}
