import React, { useState, useEffect, useRef, useCallback } from 'react'
import { Segmented, Spin, Select, DatePicker, Button } from 'antd'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts'
import dayjs from 'dayjs'
import { factorApi, healthApi, marketReviewApi } from '../api'
import MarketOverview from '../components/MarketOverview'
import MarketSignals from '../components/MarketSignals'
import MaBreadthChart from '../components/MaBreadthChart'
import NhNlOverlayChart from '../components/NhNlOverlayChart'
import AiAnalysis from '../components/AiAnalysis'

const CustomTooltip = ({ active, payload, label, selectedIndexName = '上证指数' }) => {
  if (active && payload && payload.length) {
    const valueData = payload.find(p => p.dataKey === 'value')
    const sectorData = payload.find(p => p.dataKey === 'sectorCr')
    const rawData = payload[0]?.payload
    const indexRaw = rawData?.indexRaw

    return (
      <div className="bg-white rounded-xl shadow-2xl border border-gray-100 p-4 min-w-[180px]">
        <p className="text-xs font-bold text-gray-400 uppercase mb-2 tracking-wider">{label}</p>
        {valueData && (
          <div className="flex items-center justify-between mb-2">
            <span className="text-blue-600 font-bold">个股CR5%</span>
            <div className="flex items-center">
              <span className="font-mono font-bold text-blue-600 mr-2">{valueData.value?.toFixed(2)}%</span>
              <span className={`text-[10px] ${valueData.value >= 50 ? 'text-red-500' : 'text-green-500'}`}>
                {valueData.value >= 50 ? '● 拥挤' : '● 正常'}
              </span>
            </div>
          </div>
        )}
        {sectorData && sectorData.value != null && (
          <div className="flex items-center justify-between mb-2">
            <span className="text-purple-600 font-bold">板块CR10%</span>
            <div className="flex items-center">
              <span className="font-mono font-bold text-purple-600 mr-2">{sectorData.value?.toFixed(2)}%</span>
              <span className={`text-[10px] ${sectorData.value >= 50 ? 'text-red-500' : 'text-green-500'}`}>
                {sectorData.value >= 50 ? '● 拥挤' : '● 正常'}
              </span>
            </div>
          </div>
        )}
        {indexRaw && (
          <div className="flex items-center justify-between pt-2 border-t border-gray-50">
            <span className="text-orange-500 font-bold">{selectedIndexName}</span>
            <span className="font-mono font-bold text-orange-500">{indexRaw.toFixed(2)}</span>
          </div>
        )}
      </div>
    )
  }
  return null
}

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

function MarketMonitor() {
  const [cr5Data, setCr5Data] = useState([])
  const [indexConfig, setIndexConfig] = useState([])
  const [selectedIndex, setSelectedIndex] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadingText, setLoadingText] = useState('加载中...')
  const [period, setPeriod] = useState('day')
  const [queryDate, setQueryDate] = useState(null)
  const [latestDate, setLatestDate] = useState(null)
  const dateRef = useRef(null)
  const [, forceUpdate] = useState(0)
  const [totalStocks, setTotalStocks] = useState(0)
  const requestIdRef = useRef(0)
  const initializedRef = useRef(false)

  const PERIOD_OPTIONS = [
    { value: 'day', label: '日' },
    { value: 'week', label: '周' },
    { value: 'month', label: '月' },
    { value: 'quarter', label: '季' },
    { value: 'year', label: '年' },
  ]

  useEffect(() => {
    if (initializedRef.current) return
    initializedRef.current = true
    initLoad()
  }, [])

  // 周期或指数切换时重新加载趋势对比图
  useEffect(() => {
    if (initializedRef.current && selectedIndex) {
      loadCr5Data(selectedIndex)
    }
  }, [period, selectedIndex])

  const initLoad = async () => {
    try {
      const [idxRes, healthRes] = await Promise.all([
        factorApi.getIndices({ filter_mode: 'enabled' }),
        healthApi.check()
      ])
      const indices = idxRes.indices || []
      const latest = healthRes?.latest_trade_date || null

      if (indices.length > 0) {
        setIndexConfig(indices)
        setSelectedIndex(indices[0].code)
      }
      if (latest) {
        setLatestDate(latest)
      }
      loadCr5Data(indices[0]?.code)
    } catch (e) {
      console.error('初始化加载失败:', e)
    }
  }

  const loadCr5Data = async (targetIndex) => {
    if (!targetIndex) return
    const myId = ++requestIdRef.current
    setLoading(true)
    setLoadingText(period === 'day' ? '加载日线数据...' : `加载${period === 'week' ? '周' : period === 'month' ? '月' : period === 'quarter' ? '季' : '年'}线数据...`)
    try {
      const res = await marketReviewApi.getBaseData({ type: 'cr5', period, index_code: selectedIndex || undefined })
      if (myId !== requestIdRef.current) return

      const cr5List = res?.data || []

      // base-data 返回 {date, cr5_pct, cr10_pct, index_value, index_raw}
      // 映射为趋势图格式
      const data = cr5List.map(item => ({
        date: item.date,
        value: item.cr5_pct,
        sectorCr: item.cr10_pct,
        indexValue: item.index_value || null,
        indexRaw: item.index_raw || null,
      }))

      setCr5Data(data)
    } catch (e) {
      if (myId !== requestIdRef.current) return
      console.error('加载CR5数据失败:', e)
      setCr5Data([])
    } finally {
      if (myId === requestIdRef.current) {
        setLoading(false)
      }
    }
  }

  const handleQuery = () => {
    setQueryDate(dateRef.current)
  }

  const selectedIndexName = indexConfig.find(c => c.code === selectedIndex)?.name || '上证指数'

  const getYAxisDomain = () => {
    if (cr5Data.length === 0) return [0, 100]
    const allValues = cr5Data.flatMap(d => [d.value, d.sectorCr10].filter(v => v != null))
    if (allValues.length === 0) return [0, 100]
    const minVal = Math.min(...allValues)
    const maxVal = Math.max(...allValues)
    const padding = Math.max((maxVal - minVal) * 0.15, 5)
    return [
      Math.max(0, Math.floor((minVal - padding) / 5) * 5),
      Math.min(100, Math.ceil((maxVal + padding) / 5) * 5)
    ]
  }

  return (
    <div className="space-y-3 md:space-y-4">
      {/* 标题栏 */}
      <div data-section="标题栏" className="bg-white rounded-xl shadow-sm p-3 md:p-4">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <h1 className="text-lg md:text-xl font-bold text-gray-800">市场监控</h1>
          <div className="flex items-center space-x-2">
            <DatePicker
              value={dateRef.current ? dayjs(dateRef.current, 'YYYYMMDD') : null}
              onChange={(d) => { dateRef.current = d ? d.format('YYYYMMDD') : null; forceUpdate(n => n + 1) }}
              format="YYYYMMDD"
              placeholder="选择交易日"
              allowClear
              className="w-32 md:w-40"
              size="small"
            />
            <Button type="primary" onClick={handleQuery} loading={loading} size="small">
              查询
            </Button>
          </div>
        </div>

        {/* 数据概览 */}
        <div className="mt-2 md:mt-3 pt-2 md:pt-3 border-t border-gray-100 text-xs md:text-sm text-gray-500 flex flex-wrap gap-x-3">
          <span>交易日: <span className="font-mono font-medium text-gray-700">{queryDate || latestDate || '-'}</span></span>
          <span>统计: <span className="font-medium text-gray-700">{totalStocks}</span> 只</span>
        </div>
      </div>

      {/* 趋势对比图 */}
      <div data-section="趋势对比图" className="bg-white rounded-xl shadow-sm overflow-hidden">
        <div className="p-3 md:p-4 pb-2">
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-2 md:gap-4">
            <div className="flex items-center space-x-3">
              <h3 className="text-sm md:text-base font-semibold text-gray-800">趋势对比图</h3>
              <Segmented
                options={PERIOD_OPTIONS}
                value={period}
                onChange={setPeriod}
                size="small"
              />
            </div>
            <div className="flex items-center justify-between md:space-x-4">
              <div className="flex items-center space-x-2 md:space-x-3 text-[10px] md:text-xs font-bold text-gray-500">
                <div className="flex items-center"><span className="w-2.5 h-2.5 md:w-3 md:h-3 rounded-full bg-blue-500 mr-1 md:mr-1.5"></span><span className="hidden sm:inline">个股CR5%</span><span className="sm:hidden">CR5</span></div>
                <div className="flex items-center"><span className="w-2.5 h-2.5 md:w-3 md:h-3 rounded-full bg-purple-500 mr-1 md:mr-1.5"></span><span className="hidden sm:inline">板块CR10%</span><span className="sm:hidden">CR10</span></div>
                <div className="flex items-center"><span className="w-2.5 h-2.5 md:w-3 md:h-3 rounded-full bg-orange-400 mr-1 md:mr-1.5"></span>{selectedIndexName}</div>
              </div>
              <Select
                value={selectedIndex}
                onChange={setSelectedIndex}
                size="small"
                className="w-28 md:w-32 flex-shrink-0"
                placeholder="选择指数"
                options={indexConfig.map(c => ({ value: c.code, label: c.name }))}
              />
            </div>
          </div>

          <div className="h-[250px] md:h-[350px] w-full">
            {loading ? (
              <div className="h-full flex flex-col items-center justify-center bg-gray-50/30 rounded-2xl">
                <Spin size="large" />
                <p className="mt-4 text-xs md:text-sm text-gray-500 font-medium">{loadingText}</p>
              </div>
            ) : cr5Data.length === 0 ? (
              <div className="h-full flex items-center justify-center bg-gray-50/30 rounded-2xl">
                <p className="text-xs md:text-sm text-gray-400">暂无数据</p>
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={cr5Data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f3f4f6" />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 10, fill: '#9ca3af', fontWeight: 600 }}
                    tickFormatter={formatDate}
                    axisLine={false}
                    tickLine={false}
                    interval={Math.floor(cr5Data.length / 6)}
                  />
                  <YAxis
                    domain={getYAxisDomain()}
                    tick={{ fontSize: 10, fill: '#9ca3af', fontWeight: 600 }}
                    tickFormatter={(val) => `${val}%`}
                    axisLine={false}
                    tickLine={false}
                    width={35}
                  />
                  <Tooltip content={<CustomTooltip selectedIndexName={selectedIndexName} />} />
                  <ReferenceLine
                    y={50}
                    stroke="#ef4444"
                    strokeDasharray="8 8"
                    strokeWidth={1}
                    label={{ value: '警戒线', position: 'insideBottomRight', fill: '#ef4444', fontSize: 9, fontWeight: 800 }}
                  />
                  <Line type="monotone" dataKey="value" stroke="#3b82f6" strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 0, fill: '#3b82f6' }} name="个股CR5%" />
                  <Line type="monotone" dataKey="sectorCr" stroke="#a855f7" strokeWidth={1.5} dot={false} activeDot={{ r: 3, strokeWidth: 0, fill: '#a855f7' }} name="板块CR10%" connectNulls />
                  <Line type="monotone" dataKey="indexValue" stroke="#fbbf24" strokeWidth={1.5} dot={false} strokeDasharray="8 4" strokeOpacity={0.8} name={selectedIndexName} />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
      </div>

      {/* 均线占比趋势 */}
      <div data-section="均线占比趋势"><MaBreadthChart /></div>

      {/* 新高新低指数 */}
      <div data-section="新高新低指数"><NhNlOverlayChart /></div>

      {/* 市场概览 */}
      <div data-section="市场概览"><MarketOverview date={queryDate} /></div>

      {/* A股运行状态与新高板块效应 */}
      <div data-section="市场状态与新高板块"><MarketSignals date={queryDate} /></div>

      {/* AI综合研判 */}
      <div data-section="AI综合研判"><AiAnalysis date={queryDate || latestDate} /></div>
    </div>
  )
}

export default MarketMonitor
