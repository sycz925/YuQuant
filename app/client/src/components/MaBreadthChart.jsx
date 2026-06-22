import React, { useState, useEffect, useCallback } from 'react'
import { Spin, Segmented, Select } from 'antd'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts'
import { marketReviewApi, factorApi } from '../api'

const PERIOD_OPTIONS = [
  { value: 'day', label: '日' },
  { value: 'week', label: '周' },
  { value: 'month', label: '月' },
  { value: 'quarter', label: '季' },
  { value: 'year', label: '年' },
]

const formatDate = (dateStr) => {
  if (!dateStr) return dateStr
  const s = String(dateStr)
  if (s.length === 4 && /^\d{4}$/.test(s)) return s
  if (s.length === 7 && /^\d{4}-\d{2}$/.test(s)) return s
  if (s.length === 6 && /^\d{4}Q\d$/.test(s)) return s
  if (s.length === 7 && /^\d{4}W\d{2}$/.test(s)) return s
  if (s.length === 8 && /^\d{8}$/.test(s)) return `${s.slice(4,6)}-${s.slice(6,8)}`
  return s
}

const CustomTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    const rawData = payload[0]?.payload
    return (
      <div className="bg-white/90 backdrop-blur-md rounded-xl shadow-2xl border border-gray-100 p-3 min-w-[150px]">
        <p className="text-xs font-bold text-gray-400 uppercase mb-2 tracking-wider">{formatDate(label)}</p>
        {payload.map((p, i) => (
          <div key={i} className="flex items-center justify-between mb-1">
            <span style={{ color: p.color }} className="text-xs font-bold">{p.name}</span>
            <span style={{ color: p.color }} className="font-mono font-bold text-xs">
              {p.value != null ? `${p.value}%` : '-'}
            </span>
          </div>
        ))}
      </div>
    )
  }
  return null
}

function MaBreadthChart() {
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(true)
  const [period, setPeriod] = useState('day')
  const [indexConfig, setIndexConfig] = useState([])
  const [selectedIndex, setSelectedIndex] = useState('')
  const [initialized, setInitialized] = useState(false)

  useEffect(() => {
    loadIndices()
  }, [])

  useEffect(() => {
    if (initialized) {
      loadData()
    }
  }, [period, selectedIndex, initialized])

  const loadIndices = async () => {
    try {
      const res = await factorApi.getIndices({ filter_mode: 'enabled' })
      const indices = res.data.indices || []
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
      const res = await marketReviewApi.getMaBreadth({ period, index_code: selectedIndex || undefined })
      setData(res.data.data || [])
    } catch (e) {
      console.error('加载MA占比数据失败:', e)
    } finally {
      setLoading(false)
    }
  }, [period, selectedIndex])

  const indexName = indexConfig.find(c => c.code === selectedIndex)?.name || ''

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-4">
        <div className="flex items-center space-x-4">
          <div className="w-1 h-5 bg-teal-500 rounded-full"></div>
          <h2 className="text-base font-black text-gray-900 tracking-tight">均线占比趋势</h2>
          <Segmented options={PERIOD_OPTIONS} value={period} onChange={setPeriod} size="small" />
        </div>
        <div className="flex items-center space-x-4">
          <div className="flex items-center space-x-3 text-xs font-bold text-gray-500">
            <div className="flex items-center"><span className="w-3 h-3 rounded-full bg-blue-500 mr-1.5"></span>MA50</div>
            <div className="flex items-center"><span className="w-3 h-3 rounded-full bg-purple-500 mr-1.5"></span>MA20</div>
            {selectedIndex && <div className="flex items-center"><span className="w-3 h-3 rounded-full bg-orange-400 mr-1.5"></span>{indexName}</div>}
          </div>
          <Select value={selectedIndex} onChange={setSelectedIndex} size="small" style={{ width: 120 }}
            options={indexConfig.map(c => ({ value: c.code, label: c.name }))} />
        </div>
      </div>

      {loading ? (
        <div className="h-[280px] flex items-center justify-center">
          <Spin />
        </div>
      ) : (
        <div className="h-[280px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f3f4f6" />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#9ca3af', fontWeight: 600 }}
                tickFormatter={formatDate} axisLine={false} tickLine={false}
                interval={Math.floor(data.length / 8)} />
              <YAxis yAxisId="pct" domain={[0, 100]} tick={{ fontSize: 11, fill: '#9ca3af', fontWeight: 600 }}
                tickFormatter={(val) => `${val}%`} axisLine={false} tickLine={false} />
              {data.some(d => d.index_value != null) && (
                <YAxis yAxisId="idx" orientation="right" hide />
              )}
              <Tooltip content={<CustomTooltip />} />
              <ReferenceLine yAxisId="pct" y={80} stroke="#ef4444" strokeDasharray="8 8" strokeWidth={1}
                label={{ value: '80%警戒', position: 'insideTopRight', fill: '#ef4444', fontSize: 10, fontWeight: 700 }} />
              <ReferenceLine yAxisId="pct" y={20} stroke="#22c55e" strokeDasharray="8 8" strokeWidth={1}
                label={{ value: '20%超跌', position: 'insideBottomRight', fill: '#22c55e', fontSize: 10, fontWeight: 700 }} />
              <Line yAxisId="pct" type="monotone" dataKey="ma50_pct" stroke="#3b82f6" strokeWidth={2.5} dot={false}
                activeDot={{ r: 4, strokeWidth: 0, fill: '#3b82f6' }} name="MA50占比" />
              <Line yAxisId="pct" type="monotone" dataKey="ma20_pct" stroke="#a855f7" strokeWidth={2} dot={false}
                activeDot={{ r: 3, strokeWidth: 0, fill: '#a855f7' }} name="MA20占比" />
              {data.some(d => d.index_value != null) && (
                <Line yAxisId="pct" type="monotone" dataKey="index_value" stroke="#fbbf24" strokeWidth={2} dot={false}
                  strokeDasharray="8 4" strokeOpacity={0.8} name={indexName} />
              )}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}

export default MaBreadthChart
