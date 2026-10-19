import React, { useState, useEffect, useCallback, useMemo } from 'react'
import { Spin, Segmented, Select, Tooltip as AntTooltip } from 'antd'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from 'recharts'
import { marketReviewApi, factorApi } from '../api'

const PERIOD_OPTIONS = [
  { value: 'day', label: '日' },
  { value: 'week', label: '周' },
  { value: 'month', label: '月' },
  { value: 'quarter', label: '季' },
  { value: 'year', label: '年' },
]

// MABTI 周期：固定 20 日简单移动平均（不提供切换）
const MA_PERIOD = 20

// 经典 Zweig Breadth Thrust 阈值
const UPPER_LINE = 61.5   // 天线
const LOWER_LINE = 40     // 地线
const MID_LINE = 50       // 中轴

const BTI_COLOR = '#3b82f6'
const MABTI_COLOR = '#dc2626'

const formatDate = (dateStr) => {
  if (!dateStr) return dateStr
  const s = String(dateStr)
  if (s.length === 4 && /^\d{4}$/.test(s)) return s
  if (s.length === 7 && /^\d{4}-\d{2}$/.test(s)) return s
  if (s.length === 6 && /^\d{4}Q\d$/.test(s)) return s
  if (s.length === 7 && /^\d{4}W\d{2}$/.test(s)) return s
  if (s.length === 8 && /^\d{8}$/.test(s)) return `${s.slice(4, 6)}-${s.slice(6, 8)}`
  return s
}

const CustomTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-white rounded-xl shadow-2xl border border-gray-100 p-3 min-w-[170px]">
        <p className="text-xs font-bold text-gray-400 uppercase mb-2 tracking-wider">{formatDate(label)}</p>
        {payload.map((p, i) => (
          <div key={i} className="flex items-center justify-between mb-1">
            <span style={{ color: p.color }} className="text-xs font-bold">{p.name}</span>
            <span style={{ color: p.color }} className="font-mono font-bold text-xs">
              {p.value != null ? `${Number(p.value).toFixed(2)}%` : '-'}
            </span>
          </div>
        ))}
      </div>
    )
  }
  return null
}

function BtiChart() {
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(true)
  const [period, setPeriod] = useState('day')
  const [indexConfig, setIndexConfig] = useState([])
  const [selectedIndex, setSelectedIndex] = useState('')
  const [initialized, setInitialized] = useState(false)
  // 图例点击切换系列显示（key: bti / mabti / index_value）
  const [hiddenSeries, setHiddenSeries] = useState([])
  const toggleSeries = useCallback((key) => {
    setHiddenSeries(prev => prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key])
  }, [])

  useEffect(() => { loadIndices() }, [])

  useEffect(() => {
    if (initialized) loadData()
  }, [period, selectedIndex, initialized])

  const loadIndices = async () => {
    try {
      const res = await factorApi.getIndices({ filter_mode: 'enabled' })
      const indices = res.items || res.indices || res.data || []
      if (indices.length > 0) {
        setIndexConfig(indices)
        setSelectedIndex(indices[0].code)
      }
    } catch (e) {
      console.error('加载指数列表失败:', e)
    } finally {
      setInitialized(true)
    }
  }

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await marketReviewApi.getBaseData({
        type: 'bti',
        period,
        index_code: selectedIndex || undefined,
      })
      setData(res.data || [])
    } catch (e) {
      console.error('加载BTI数据失败:', e)
    } finally {
      setLoading(false)
    }
  }, [period, selectedIndex])

  const indexName = indexConfig.find(c => c.code === selectedIndex)?.name || ''

  // 计算 MABTI：标准 20 日简单均线；窗口样本不足 20 时用已积累的样本（保证曲线从头可见，不出现"半截线"）
  const { chartData, yDomain } = useMemo(() => {
    const src = data || []
    const out = []
    let ring = []
    for (let i = 0; i < src.length; i++) {
      const v = src[i].bti
      if (v != null) {
        ring.push(v)
        if (ring.length > MA_PERIOD) ring.shift()
      }
      const mabti = ring.length > 0 ? ring.reduce((s, x) => s + x, 0) / ring.length : null
      out.push({ ...src[i], mabti: mabti != null ? Number(mabti.toFixed(2)) : null })
    }

    const vals = out.map(d => d.bti).filter(v => v != null)
    const dmin = vals.length ? Math.min(...vals) : LOWER_LINE
    const dmax = vals.length ? Math.max(...vals) : UPPER_LINE
    const lo = Math.max(0, Math.floor(Math.min(dmin, LOWER_LINE) - 4))
    const hi = Math.min(100, Math.ceil(Math.max(dmax, UPPER_LINE) + 4))
    return { chartData: out, yDomain: [lo, hi] }
  }, [data])

  const last = chartData.length ? chartData[chartData.length - 1] : null
  const bullish = last && last.bti != null && last.mabti != null ? last.bti >= last.mabti : null

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-3 md:p-6">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between mb-3 md:mb-4 gap-2 md:gap-4">
        <div className="flex items-center space-x-3">
          <div className="w-1 h-4 md:h-5 bg-sky-500 rounded-full"></div>
          <h2 className="text-sm md:text-base font-black text-gray-900 tracking-tight">BTI 广度指标</h2>
          <Segmented options={PERIOD_OPTIONS} value={period} onChange={setPeriod} size="small" />
        </div>
        <div className="flex items-center justify-between md:space-x-4">
          <div className="flex items-center space-x-2 md:space-x-3 text-[10px] md:text-xs font-bold text-gray-500">
            <button type="button" onClick={() => toggleSeries('bti')} title="点击切换显示/隐藏"
              className="flex items-center cursor-pointer select-none transition-opacity hover:opacity-70"
              style={{ opacity: hiddenSeries.includes('bti') ? 0.35 : 1, background: 'none', border: 'none', padding: 0, font: 'inherit', color: 'inherit' }}>
              <span className="w-2.5 h-2.5 md:w-3 md:h-3 rounded-full mr-1 md:mr-1.5" style={{ background: BTI_COLOR }}></span>
              <span className={hiddenSeries.includes('bti') ? 'line-through' : ''}>BTI</span>
            </button>
            <button type="button" onClick={() => toggleSeries('mabti')} title="点击切换显示/隐藏"
              className="flex items-center cursor-pointer select-none transition-opacity hover:opacity-70"
              style={{ opacity: hiddenSeries.includes('mabti') ? 0.35 : 1, background: 'none', border: 'none', padding: 0, font: 'inherit', color: 'inherit' }}>
              <span className="w-2.5 h-2.5 md:w-3 md:h-3 rounded-full mr-1 md:mr-1.5" style={{ background: MABTI_COLOR }}></span>
              <span className={hiddenSeries.includes('mabti') ? 'line-through' : ''}>MABTI({MA_PERIOD})</span>
            </button>
            <button type="button" onClick={() => toggleSeries('index_value')} title="点击切换显示/隐藏"
              className="flex items-center cursor-pointer select-none transition-opacity hover:opacity-70"
              style={{ opacity: hiddenSeries.includes('index_value') ? 0.35 : 1, background: 'none', border: 'none', padding: 0, font: 'inherit', color: 'inherit' }}>
              <span className="w-2.5 h-2.5 md:w-3 md:h-3 rounded-full bg-orange-400 mr-1 md:mr-1.5"></span>
              <span className={hiddenSeries.includes('index_value') ? 'line-through' : ''}>{indexName}</span>
            </button>
          </div>
          <Select value={selectedIndex} onChange={setSelectedIndex} size="small" className="w-28 md:w-32 flex-shrink-0"
            options={indexConfig.map(c => ({ value: c.code, label: c.name }))} />
        </div>
      </div>

      {/* 状态条 */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mb-2 text-[11px] md:text-xs">
        {last && last.bti != null && (
          <span className="font-bold text-gray-600">
            BTI <span className="font-mono" style={{ color: BTI_COLOR }}>{last.bti.toFixed(2)}%</span>
            {last.mabti != null && <> / MABTI <span className="font-mono" style={{ color: MABTI_COLOR }}>{last.mabti.toFixed(2)}%</span></>}
          </span>
        )}
        {bullish != null && (
          <span className={`font-black ${bullish ? 'text-red-500' : 'text-green-600'}`}>
            {bullish ? '▲ 多头（BTI 在 MABTI 之上）' : '▼ 空头（BTI 在 MABTI 之下）'}
          </span>
        )}
        <AntTooltip title={`BTI = 10日EMA(上涨家数/(上涨+下跌家数))；MABTI = BTI 的 ${MA_PERIOD} 日简单均线`}>
          <span className="text-gray-400 cursor-help border-b border-dotted border-gray-300">
            天线 {UPPER_LINE}% / 地线 {LOWER_LINE}%
          </span>
        </AntTooltip>
      </div>

      {loading ? (
        <div className="h-[200px] md:h-[280px] flex items-center justify-center"><Spin /></div>
      ) : (
        <div className="h-[200px] md:h-[280px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 12, right: 10, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f3f4f6" />
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#9ca3af', fontWeight: 600 }}
                tickFormatter={formatDate} axisLine={false} tickLine={false}
                interval={Math.floor(chartData.length / 6)} />
              <YAxis yAxisId="pct" domain={yDomain} tick={{ fontSize: 10, fill: '#9ca3af', fontWeight: 600 }}
                tickFormatter={(val) => `${val}%`} axisLine={false} tickLine={false} width={38} />
              {chartData.some(d => d.index_value != null) && (
                <YAxis yAxisId="idx" orientation="right" hide />
              )}
              <Tooltip content={<CustomTooltip />} />

              {/* 天线 / 中轴 / 地线 */}
              <ReferenceLine yAxisId="pct" y={UPPER_LINE} stroke="#ef4444" strokeDasharray="8 8" strokeWidth={1}
                label={{ value: `天线 ${UPPER_LINE}%`, position: 'insideTopRight', fill: '#ef4444', fontSize: 9, fontWeight: 700 }} />
              <ReferenceLine yAxisId="pct" y={MID_LINE} stroke="#d1d5db" strokeDasharray="4 6" strokeWidth={1} />
              <ReferenceLine yAxisId="pct" y={LOWER_LINE} stroke="#22c55e" strokeDasharray="8 8" strokeWidth={1}
                label={{ value: `地线 ${LOWER_LINE}%`, position: 'insideBottomRight', fill: '#22c55e', fontSize: 9, fontWeight: 700 }} />

              <Line yAxisId="pct" type="monotone" dataKey="bti" stroke={BTI_COLOR} strokeWidth={2} dot={false}
                activeDot={{ r: 4, strokeWidth: 0, fill: BTI_COLOR }} name="BTI" hide={hiddenSeries.includes('bti')} />
              <Line yAxisId="pct" type="monotone" dataKey="mabti" stroke={MABTI_COLOR} strokeWidth={2} dot={false}
                activeDot={{ r: 3, strokeWidth: 0, fill: MABTI_COLOR }}
                name={`MABTI(${MA_PERIOD})`} connectNulls hide={hiddenSeries.includes('mabti')} />
              {chartData.some(d => d.index_value != null) && (
                <Line yAxisId="idx" type="monotone" dataKey="index_value" stroke="#fbbf24" strokeWidth={1.5} dot={false}
                  strokeDasharray="8 4" strokeOpacity={0.8} name={indexName} hide={hiddenSeries.includes('index_value')} />
              )}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}

export default BtiChart
