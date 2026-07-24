import React, { useState, useEffect } from 'react'
import { Spin, Select, Segmented } from 'antd'
import ReactECharts from 'echarts-for-react'
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
  if (s.length === 7 && /^\d{4}Q\d$/.test(s)) return s
  if (s.length === 7 && /^\d{4}W\d{2}$/.test(s)) return s
  if (s.length === 7 && /^\d{4}-\d{2}$/.test(s)) return s
  if (s.length === 8 && /^\d{8}$/.test(s)) return `${s.slice(4,6)}-${s.slice(6,8)}`
  return s
}

const aggregateByPeriod = (data, period) => {
  if (period === 'day') return data
  const buckets = {}
  data.forEach(d => {
    const s = String(d.date)
    let key
    if (period === 'week') {
      const y = parseInt(s.slice(0,4)), m = parseInt(s.slice(4,6)), day = parseInt(s.slice(6,8))
      const dt = new Date(y, m-1, day)
      const weekStart = new Date(dt)
      weekStart.setDate(dt.getDate() - dt.getDay())
      key = `${weekStart.getFullYear()}W${String(Math.ceil(((weekStart - new Date(weekStart.getFullYear(),0,1)) / 86400000 + 1) / 7)).padStart(2,'0')}`
    } else if (period === 'quarter') {
      const y = parseInt(s.slice(0,4)), m = parseInt(s.slice(4,6))
      key = `${y}Q${Math.ceil(m/3)}`
    } else if (period === 'year') {
      key = s.slice(0,4)
    } else {
      key = s.slice(0,6)
    }
    if (!buckets[key]) {
      buckets[key] = { date: key, nh: 0, nl: 0, nh_3m: 0, nl_3m: 0, nh_1m: 0, nl_1m: 0, index_raw: 0, count: 0 }
    }
    buckets[key].nh += d.nh || 0
    buckets[key].nl += d.nl || 0
    buckets[key].nh_3m += d.nh_3m || 0
    buckets[key].nl_3m += d.nl_3m || 0
    buckets[key].nh_1m += d.nh_1m || 0
    buckets[key].nl_1m += d.nl_1m || 0
    buckets[key].index_raw = d.index_raw || buckets[key].index_raw
    buckets[key].count++
  })
  return Object.values(buckets).sort((a, b) => a.date > b.date ? 1 : -1)
}

function NhNlOverlayChart() {
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(true)
  const [indexConfig, setIndexConfig] = useState([])
  const [selectedIndex, setSelectedIndex] = useState('000001')
  const [period, setPeriod] = useState('day')

  useEffect(() => { loadIndices() }, [])
  useEffect(() => { loadData() }, [selectedIndex, period])

  const loadIndices = async () => {
    try {
      const res = await factorApi.getIndices({ filter_mode: 'enabled' })
      setIndexConfig(res?.items || res?.indices || res?.data || [])
    } catch (e) {
      console.error('加载指数列表失败:', e)
    }
  }

  const loadData = async () => {
    setLoading(true)
    try {
      const res = await marketReviewApi.getBaseData({ type: 'nh-nl', period, index_code: selectedIndex })
      setData(res?.data || [])
    } catch (e) {
      console.error('加载NH-NL数据失败:', e)
    } finally {
      setLoading(false)
    }
  }

  const indexName = indexConfig.find(c => c.code === selectedIndex)?.name || '上证指数'

  const getOption = () => {
    const displayData = aggregateByPeriod(data, period)
    if (!displayData.length) return {}

    const dates = displayData.map(d => d.date)
    const nhNlRaw = displayData.map(d => (d.nh || 0) - (d.nl || 0))
    const nhNl3m = displayData.map(d => (d.nh_3m || 0) - (d.nl_3m || 0))
    const nhNl1m = displayData.map(d => (d.nh_1m || 0) - (d.nl_1m || 0))
    const indexPrices = displayData.map(d => d.index_raw || 0).filter(v => v > 0)

    // 大盘指数动态极值 + 50%缓冲
    const minPrice = Math.min(...indexPrices)
    const maxPrice = Math.max(...indexPrices)
    const priceGap = maxPrice - minPrice
    const yAxisMin = Math.floor(minPrice - priceGap * 0.5)
    const yAxisMax = Math.ceil(maxPrice + priceGap * 0.5)

    // NH-NL 对称极值（零轴居中）
    const allNlValues = [...nhNlRaw, ...nhNl3m, ...nhNl1m]
    const nhNlMax = Math.max(...allNlValues.map(v => Math.abs(v)), 100)
    const nhNlYMin = -nhNlMax
    const nhNlYMax = nhNlMax

    return {
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        backgroundColor: 'rgba(255,255,255,0.95)',
        borderColor: '#e5e7eb',
        textStyle: { color: '#374151', fontSize: 12 },
        formatter: (params) => {
          if (!params.length) return ''
          const date = params[0].axisValue
          let html = `<div style="font-weight:700;margin-bottom:4px">${formatDate(date)}</div>`
          params.forEach(p => {
            if (p.seriesName === '_zero') return
            let raw, color
            if (p.seriesName === 'NH-NL (250日)') {
              raw = nhNlRaw[p.dataIndex]
              color = raw >= 0 ? '#ef4444' : '#22c55e'
            } else if (p.seriesName === 'NH-NL (3个月)') {
              raw = nhNl3m[p.dataIndex]
              color = raw >= 0 ? '#f97316' : '#14b8a6'
            } else if (p.seriesName === 'NH-NL (1个月)') {
              raw = nhNl1m[p.dataIndex]
              color = raw >= 0 ? '#a855f7' : '#7c3aed'
            } else {
              raw = p.value
              color = '#f59e0b'
            }
            html += `<div style="display:flex;justify-content:space-between;gap:16px">
              <span>${p.seriesName}</span>
              <span style="font-weight:700;color:${color}">${p.value != null ? p.value.toFixed(0) : '-'}</span>
            </div>`
          })
          return html
        }
      },
      legend: { data: ['NH-NL (250日)', 'NH-NL (3个月)', 'NH-NL (1个月)', indexName], top: 5, textStyle: { fontSize: 11, color: '#6b7280' } },
      grid: { left: 55, right: 15, top: 35, bottom: 30 },
      xAxis: { type: 'category', data: dates, axisLabel: { fontSize: 10, color: '#9ca3af', formatter: (v) => formatDate(v) }, axisLine: { lineStyle: { color: '#e5e7eb' } }, axisTick: { show: false } },
      yAxis: [
        {
          type: 'value', name: 'NH-NL',
          min: nhNlYMin, max: nhNlYMax,
          nameTextStyle: { fontSize: 10, color: '#6b7280' },
          axisLabel: { fontSize: 10, color: '#9ca3af' },
          splitLine: { lineStyle: { color: '#f3f4f6' } },
          axisLine: { show: false }, axisTick: { show: false }
        },
        {
          type: 'value', name: indexName,
          min: yAxisMin, max: yAxisMax, scale: true,
          position: 'right',
          nameTextStyle: { fontSize: 10, color: '#f59e0b' },
          axisLabel: { fontSize: 10, color: '#f59e0b' },
          splitLine: { show: false },
          axisLine: { show: false }, axisTick: { show: false }
        }
      ],
      series: [
        { name: 'NH-NL (250日)', type: 'line', yAxisIndex: 0, data: nhNlRaw, lineStyle: { color: '#6366f1', width: 2.5 }, itemStyle: { color: '#6366f1' }, symbol: 'none', smooth: true, areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(99,102,241,0.15)' }, { offset: 1, color: 'rgba(99,102,241,0.01)' }] } } },
        { name: 'NH-NL (3个月)', type: 'line', yAxisIndex: 0, data: nhNl3m, lineStyle: { color: '#f97316', width: 2 }, itemStyle: { color: '#f97316' }, symbol: 'none', smooth: true },
        { name: 'NH-NL (1个月)', type: 'line', yAxisIndex: 0, data: nhNl1m, lineStyle: { color: '#a855f7', width: 1.5 }, itemStyle: { color: '#a855f7' }, symbol: 'none', smooth: true },
        { name: indexName, type: 'line', yAxisIndex: 1, data: displayData.map(d => d.index_raw || null), lineStyle: { color: '#f59e0b', width: 2, type: 'dashed' }, itemStyle: { color: '#f59e0b' }, symbol: 'none', smooth: true },
        { name: '_zero', type: 'line', data: [], markLine: { silent: true, symbol: 'none', lineStyle: { color: '#9ca3af', type: 'solid', width: 1 }, data: [{ yAxis: 0 }], label: { show: true, position: 'end', formatter: '0', fontSize: 10, color: '#9ca3af' } } }
      ]
    }
  }

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-4">
        <div className="flex items-center space-x-4">
          <div className="w-1 h-5 bg-rose-500 rounded-full"></div>
          <h2 className="text-base font-black text-gray-900 tracking-tight">新高新低指数（NH-NL）</h2>
          <Segmented options={PERIOD_OPTIONS} value={period} onChange={setPeriod} size="small" />
        </div>
        <div className="flex items-center space-x-3 text-xs font-bold text-gray-500">
          <div className="flex items-center"><span className="w-3 h-3 rounded-full bg-indigo-500 mr-1.5"></span>NH-NL (250日)</div>
          <div className="flex items-center"><span className="w-3 h-3 rounded-full bg-orange-500 mr-1.5"></span>NH-NL (3个月)</div>
          <div className="flex items-center"><span className="w-3 h-3 rounded-full bg-purple-500 mr-1.5"></span>NH-NL (1个月)</div>
          <div className="flex items-center"><span className="w-3 h-3 rounded-full bg-amber-500 mr-1.5"></span>{indexName}</div>
          <Select value={selectedIndex} onChange={setSelectedIndex} size="small" style={{ width: 120 }}
            options={indexConfig.map(c => ({ value: c.code, label: c.name }))} />
        </div>
      </div>

      {loading ? (
        <div className="h-[300px] flex items-center justify-center"><Spin /></div>
      ) : (
        <div className="h-[300px] w-full">
          <ReactECharts option={getOption()} style={{ height: '100%', width: '100%' }} />
        </div>
      )}
    </div>
  )
}

export default NhNlOverlayChart
