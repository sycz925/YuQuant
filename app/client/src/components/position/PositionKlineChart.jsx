import React, { useEffect, useImperativeHandle, useRef, forwardRef } from 'react'
import { createChart } from 'lightweight-charts'

/**
 * 持仓专用 K 线图（独立实现，不复用 TradingViewChart）
 *
 * 设计取舍：
 *  - 只画 K 线 + 持仓标注，不带成交量 / MACD / RPS 子图 → 主图更大、更清晰
 *  - 保留完整的价格轴与时间轴
 *  - 顶部固定图例（类通达信），随十字光标联动，不遮挡 K 线
 *  - 止损阶梯线用 lineType=WithSteps 画成真阶梯，一眼看出哪天上了台阶
 *  - ATR 通道为可选开关：开启后在 K 线上下各画一条 close ± k×ATR 的通道线，
 *    用于判断"正常波动区间"，避免把止损放进噪声带里被扫掉
 */

const COLORS = {
  bg: '#131722',
  grid: '#1e222d',
  border: '#2a2e39',
  up: '#ef5350',
  down: '#26a69a',
  text: '#d1d4dc',
  muted: '#787b86',
  stop: '#f59e0b',
  dynTp: '#a855f7',
  cost: '#9ca3af',
  atrUpper: '#38bdf8',
  atrLower: '#38bdf8',
}

const EMPTY = []

const toChartTime = (d) => {
  const s = String(d || '')
  return s.length === 8 && /^\d+$/.test(s) ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6)}` : s
}

const toDisplayDate = (t) => String(t || '').replace(/-/g, '/')

/** lightweight-charts 的 Time 可能是字符串，也可能是 {year,month,day} 对象 */
const normTime = (t) => {
  if (t && typeof t === 'object') {
    return `${t.year}-${String(t.month).padStart(2, '0')}-${String(t.day).padStart(2, '0')}`
  }
  return String(t || '')
}

const fmtP = (v, dec = 2) => {
  const n = Number(v)
  return v === null || v === undefined || v === '' || !isFinite(n) ? '-' : n.toFixed(dec)
}

const fmtAtr = (v) => {
  const n = Number(v)
  if (!isFinite(n)) return '-'
  const a = Math.abs(n)
  if (a >= 100) return n.toFixed(1)
  if (a >= 10) return n.toFixed(2)
  if (a >= 1) return n.toFixed(3)
  return n.toFixed(4)
}

/** 去重 + 升序 + 剔除非法值 */
const normalizeBars = (bars) => {
  const map = new Map()
  ;(bars || []).forEach((b) => {
    const t = toChartTime(b.trade_date || b.date)
    const o = Number(b.open)
    const h = Number(b.high)
    const l = Number(b.low)
    const c = Number(b.close)
    if (!t || ![o, h, l, c].every((x) => isFinite(x) && x > 0)) return
    map.set(t, { time: t, open: o, high: h, low: l, close: c })
  })
  return Array.from(map.values()).sort((a, b) => a.time.localeCompare(b.time))
}

/** 逐日止损阶梯数据 */
const buildStopSeries = (daily) => {
  const map = new Map()
  ;(daily || []).forEach((s) => {
    const t = toChartTime(s.trade_date || s.date)
    const v = Number(s.current_stop_loss_price)
    if (!t || !isFinite(v)) return
    map.set(t, { time: t, value: v })
  })
  return Array.from(map.values()).sort((a, b) => a.time.localeCompare(b.time))
}

/** date -> ATR（优先用后端给的全精度 atr_series） */
const buildAtrMap = (atrSeries, daily) => {
  const map = new Map()
  const push = (t, v) => {
    const n = Number(v)
    if (!t || !isFinite(n) || n <= 0) return
    map.set(t, n)
  }
  const src = atrSeries && atrSeries.length
    ? atrSeries
    : (daily || []).map((s) => ({ date: s.trade_date || s.date, value: s.atr }))
  src.forEach((d) => push(toChartTime(d.date || d.time), d.value))
  return map
}

const PositionKlineChart = forwardRef(function PositionKlineChart({
  bars = EMPTY,
  daily = EMPTY,
  markers = EMPTY,
  priceLines = EMPTY,
  atrSeries = EMPTY,
  buyDate = null,
  priceDec = 2,
  height = 620,
  showAtr = false,
  atrPeriod = 14,
  atrBandK = 2.0,
  dynamicTpSeries = EMPTY,
}, ref) {
  const containerRef = useRef(null)
  // 图表上下文（供外部 ref 的「前 / 后」翻页使用）
  const replayRef = useRef(null)

  // 逐日明细（图例用）：date -> state
  const dailyMapRef = useRef({})
  useEffect(() => {
    const m = {}
    ;(daily || []).forEach((s) => {
      m[toChartTime(s.trade_date || s.date)] = s
    })
    dailyMapRef.current = m
  }, [daily])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return undefined

    const candles = normalizeBars(bars)
    if (!candles.length) return undefined

    container.innerHTML = ''

    const chart = createChart(container, {
      width: container.clientWidth,
      height,
      layout: {
        background: { type: 'solid', color: COLORS.bg },
        textColor: COLORS.text,
        fontSize: 11,
      },
      grid: { vertLines: { color: COLORS.grid }, horzLines: { color: COLORS.grid } },
      crosshair: {
        mode: 1, // Magnet
        vertLine: { color: COLORS.muted, width: 1, style: 2, labelVisible: true },
        horzLine: { color: COLORS.muted, width: 1, style: 2, labelVisible: true },
      },
      rightPriceScale: {
        visible: true,
        borderColor: COLORS.border,
        scaleMargins: { top: 0.08, bottom: 0.08 },
      },
      timeScale: {
        visible: true,
        borderColor: COLORS.border,
        rightOffset: 0,
        barSpacing: 8,
        fixRightEdge: true,          // 最新交易日固定在右边界，不能往未来（左移）拖动
        fixLeftEdge: false,
        tickMarkFormatter: (time) => {
          const s = normTime(time)
          return s.length >= 10 ? s.slice(5, 10).replace('-', '/') : s
        },
      },
      localization: {
        priceFormatter: (p) => Number(p).toFixed(priceDec),
        timeFormatter: (time) => toDisplayDate(normTime(time)),
      },
      // 禁止缩放：滚轮/捏合/拖价格轴都不改缩放
      handleScale: false,
      // 保留按住拖动来平移（往左拖到最新一天就会停住）
      handleScroll: { mouseWheel: false, pressedMouseMove: true, vertTouchDrag: false },
    })

    // ==================== ATR 通道（K 线上下方）====================
    const atrMap = buildAtrMap(atrSeries, daily)
    const bandK = Number(atrBandK) > 0 ? Number(atrBandK) : 2.0
    const upperByTime = new Map()
    const lowerByTime = new Map()

    if (showAtr && atrMap.size) {
      const upper = []
      const lower = []
      candles.forEach((c) => {
        const a = atrMap.get(c.time)
        if (!isFinite(a) || a <= 0) return
        const u = roundTick(c.close + bandK * a, priceDec)
        const l = roundTick(c.close - bandK * a, priceDec)
        if (l <= 0) return
        upper.push({ time: c.time, value: u })
        lower.push({ time: c.time, value: l })
        upperByTime.set(c.time, u)
        lowerByTime.set(c.time, l)
      })
      const mkSeries = (data, color) => {
        const s = chart.addLineSeries({
          color,
          lineWidth: 1,
          lineStyle: 2,          // Dashed —— 不抢主图视觉
          crosshairMarkerVisible: false,
          priceLineVisible: false,
          lastValueVisible: false,
        })
        s.setData(data)
        return s
      }
      if (upper.length) {
        mkSeries(upper, COLORS.atrUpper)
        mkSeries(lower, COLORS.atrLower)
      }
    }

    // ---- K 线 ----
    const candleSeries = chart.addCandlestickSeries({
      upColor: COLORS.up,
      downColor: COLORS.down,
      borderUpColor: COLORS.up,
      borderDownColor: COLORS.down,
      wickUpColor: COLORS.up,
      wickDownColor: COLORS.down,
      priceFormat: { type: 'price', precision: priceDec, minMove: 1 / 10 ** priceDec },
      priceLineVisible: false,
    })
    candleSeries.setData(candles)

    // ---- 止损阶梯线 ----
    const stops = buildStopSeries(daily)
    let stopSeries = null
    if (stops.length) {
      stopSeries = chart.addLineSeries({
        color: COLORS.stop,
        lineWidth: 2,
        lineStyle: 0,      // Solid（阶梯形状本身已足够区分）
        lineType: 1,       // WithSteps —— 真阶梯
        crosshairMarkerVisible: false,
        priceLineVisible: false,
        lastValueVisible: false,
      })
      stopSeries.setData(stops)
    }

    // ---- 动态止盈阶梯线（只在浮盈达标后出现，接管 ATR 止损作为离场依据）----
    const dynTp = (dynamicTpSeries || [])
      .map((d) => ({ time: toChartTime(d.date || d.time), value: Number(d.value) }))
      .filter((d) => d.time && isFinite(d.value))
      .sort((a, b) => a.time.localeCompare(b.time))
    if (dynTp.length) {
      chart.addLineSeries({
        color: COLORS.dynTp,
        lineWidth: 2,
        lineStyle: 0,
        lineType: 1,       // WithSteps —— 阶梯
        crosshairMarkerVisible: false,
        priceLineVisible: false,
        lastValueVisible: false,
      }).setData(dynTp)
    }

    // ---- 买卖点 / 止损触发 / 止盈参考触发 ----
    let sortedMarkers = []
    try {
      const list = (markers || [])
        .filter((m) => m && (m.date || m.time))
        .map((m) => ({
          time: toChartTime(m.date || m.time),
          position: m.position || 'aboveBar',
          shape: m.shape || 'circle',
          color: m.color || '#ffffff',
          text: m.text || '',
        }))
        .sort((a, b) => a.time.localeCompare(b.time))
      const seen = new Set()
      sortedMarkers = list.filter((m) => (seen.has(m.time) ? false : seen.add(m.time)))
      candleSeries.setMarkers(sortedMarkers)
    } catch (e) {
      console.warn('[PositionKline] setMarkers 失败', e)
    }

    // ---- 水平参考线（成本 / 当前止损 / 止盈参考 / 初始止损）----
    ;(priceLines || []).forEach((pl) => {
      const price = Number(pl && pl.price)
      if (!isFinite(price)) return
      try {
        candleSeries.createPriceLine({
          price,
          color: pl.color || COLORS.cost,
          lineWidth: pl.lineWidth || 1,
          lineStyle: pl.lineStyle === undefined ? 2 : pl.lineStyle,
          axisLabelVisible: pl.axisLabelVisible !== false,
          title: pl.title || '',
        })
      } catch (e) {
        console.warn('[PositionKline] createPriceLine 失败', e)
      }
    })

    const buyTime = toChartTime(buyDate)
    const candleTimes = candles.map((c) => c.time)
    const buyIdx = buyTime ? Math.max(0, candleTimes.indexOf(buyTime)) : 0

    // 保存图表上下文（供外部 ref 的「前 / 后」翻页使用）
    replayRef.current = {
      chart,
      candleSeries,
      stopSeries,                       // 可能为 null
      stopPts: stops,
      markerList: sortedMarkers,
      dates: candleTimes,
      buyIdx,
      defaultRange: null,               // 初始视野在下面的 rAF 里写入
    }

    // ---- 图例 ----
    const legend = document.createElement('div')
    legend.style.cssText = `
      position: absolute; top: 8px; left: 10px; z-index: 5;
      font-family: 'Consolas','Monaco',monospace; font-size: 12px; line-height: 1.6;
      color: ${COLORS.text}; pointer-events: none;
      text-shadow: 0 0 4px ${COLORS.bg}, 0 0 4px ${COLORS.bg};
      white-space: nowrap;
    `
    container.appendChild(legend)

    const byTime = new Map(candles.map((c, i) => [c.time, { c, i }]))
    const dailyMap = dailyMapRef.current
    const sep = '<span style="color:#3a3f4b">　|　</span>'

    const renderLegend = (time) => {
      const hit = byTime.get(time) || byTime.get(candles[candles.length - 1].time)
      if (!hit) return
      const { c, i } = hit
      const prev = i > 0 ? candles[i - 1] : null
      const chg = prev ? c.close - prev.close : 0
      const chgPct = prev && prev.close ? (chg / prev.close) * 100 : 0
      const color = c.close >= c.open ? COLORS.up : COLORS.down
      const extra = dailyMap[c.time] || {}
      const atrVal = atrMap.get(c.time)

      const parts = [
        `<span style="color:#e5e7eb">${toDisplayDate(c.time)}</span>`,
        `<span style="color:${color}">开 ${fmtP(c.open, priceDec)}　高 ${fmtP(c.high, priceDec)}　低 ${fmtP(c.low, priceDec)}　收 ${fmtP(c.close, priceDec)}</span>`,
        `<span style="color:${chg >= 0 ? COLORS.up : COLORS.down}">${chg >= 0 ? '+' : ''}${chgPct.toFixed(2)}%</span>`,
      ]
      if (showAtr && atrVal) {
        const u = upperByTime.get(c.time)
        const l = lowerByTime.get(c.time)
        parts.push(
          `<span style="color:${COLORS.atrUpper}">ATR(${atrPeriod}) ${fmtAtr(atrVal)}　` +
          `上轨 ${fmtP(u, priceDec)}　下轨 ${fmtP(l, priceDec)}</span>`
        )
      } else if (!showAtr && extra.atr != null) {
        parts.push(`<span style="color:${COLORS.atrUpper}">ATR ${fmtAtr(extra.atr)}</span>`)
      }
      if (extra.current_stop_loss_price != null) {
        parts.push(`<span style="color:${COLORS.stop}">止损 ${fmtP(extra.current_stop_loss_price, priceDec)}</span>`)
      }
      if (extra.action && extra.action !== '持仓') {
        parts.push(`<span style="color:${COLORS.stop}">${extra.action}</span>`)
      }
      if (buyTime && c.time === buyTime) {
        parts.push('<span style="color:#ef5350">建仓日</span>')
      }
      legend.innerHTML = parts.join(sep)
    }

    chart.subscribeCrosshairMove((param) => {
      renderLegend(param && param.time ? normTime(param.time) : null)
    })

    renderLegend(null)

    // ---- 初始视野：买入日之前 60 根 ~ 最新 ----
    requestAnimationFrame(() => {
      if (container.clientWidth > 0) chart.applyOptions({ width: container.clientWidth })
      let from = 0
      if (buyTime) {
        const idx = candles.findIndex((c) => c.time === buyTime)
        if (idx > 0) from = Math.max(0, idx - 60)
      }
      const range = candles.length - from > 30
        ? { from, to: candles.length - 1 }
        : null
      if (range) chart.timeScale().setVisibleLogicalRange(range)
      else chart.timeScale().fitContent()
      if (replayRef.current) {
        replayRef.current.defaultRange = range || chart.timeScale().getVisibleLogicalRange()
      }
    })

    // ---- 响应式 ----
    const ro = new ResizeObserver(() => {
      if (container.clientWidth > 0) chart.applyOptions({ width: container.clientWidth })
    })
    ro.observe(container)

    return () => {
      ro.disconnect()
      chart.remove()
      legend.remove()
      replayRef.current = null
    }
  }, [bars, daily, markers, priceLines, atrSeries, buyDate, priceDec, height, showAtr, atrPeriod, atrBandK])

  // ==================== 对外暴露：前 / 后 逐日平移 ====================
  // 固定等量平移：保持可视跨度不变，整体左右移动，缩放不会变
  useImperativeHandle(ref, () => ({
    shift: (dir = 1, stepBars) => {
      const info = replayRef.current
      if (!info || !info.chart) return
      const ts = info.chart.timeScale()
      const r = ts.getVisibleLogicalRange()
      if (!r) return
      const last = info.dates.length - 1
      const span = r.to - r.from
      const step = stepBars || 1          // 默认一次平移 1 个交易日
      let from = r.from + dir * step
      let to = from + span
      if (from < 0) { from = 0; to = span }
      if (to > last) { to = last; from = Math.max(0, last - span) }
      ts.setVisibleLogicalRange({ from, to })
    },
    reset() {
      const info = replayRef.current
      if (!info || !info.chart) return
      const r = info.defaultRange
      if (r) info.chart.timeScale().setVisibleLogicalRange(r)
      else info.chart.timeScale().fitContent()
    },
  }), [])

  return (
    <div
      style={{
        position: 'relative',
        width: '100%',
        height,
        background: COLORS.bg,
        borderRadius: 8,
        overflow: 'hidden',
      }}
    >
      <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
    </div>
  )
})

export default PositionKlineChart

/** 价格对齐 tick */
function roundTick(v, dec) {
  return Math.round(Number(v) * 10 ** dec) / 10 ** dec
}
