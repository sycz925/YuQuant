import React, { useState, useEffect, useRef } from 'react'
import ReactECharts from 'echarts-for-react'
import { ConfigProvider, DatePicker, Button, Select, Space, Segmented } from 'antd'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import { marketAnalysisApi, marketReviewApi } from '../api'

// A股配色
const COLORS = {
  up: '#ef5350',
  down: '#26a69a',
  bg: '#1a1a2e',
  cardBg: '#16213e',
  text: '#e0e0e0',
  grid: '#2a2a4a',
  accent: '#0f3460',
}

// 根据涨跌幅映射气泡颜色
const getBubbleColor = (chgPct) => {
  if (chgPct > 0) {
    const intensity = Math.min(Math.abs(chgPct) / 10, 1)
    const r = Math.round(239 - (239 - 166) * intensity)
    const g = Math.round(83 - 83 * intensity * 0.6)
    const b = Math.round(80 - 80 * intensity * 0.6)
    return `rgb(${r},${g},${b})`
  } else {
    const intensity = Math.min(Math.abs(chgPct) / 10, 1)
    const r = Math.round(38)
    const g = Math.round(166 - (166 - 105) * intensity)
    const b = Math.round(154 - (154 - 92) * intensity)
    return `rgb(${r},${g},${b})`
  }
}

// RPS 周期选项
const RPS_PERIODS = [
  { label: 'RPS10', value: 10 },
  { label: 'RPS20', value: 20 },
  { label: 'RPS50', value: 50 },
]

// RPS 分组周期选项
const RPS_GROUP_PERIODS = [
  { label: 'RPS20', value: 20 },
  { label: 'RPS50', value: 50 },
  { label: 'RPS120', value: 120 },
  { label: 'RPS250', value: 250 },
]

export default function MarketAnalysis({ initialDate }) {
  const navigate = useNavigate()
  const [date, setDate] = useState(initialDate ? dayjs(initialDate, 'YYYYMMDD') : null)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const [bubbleData, setBubbleData] = useState(null)
  const [bubbleLoading, setBubbleLoading] = useState(false)
  const [bubbleError, setBubbleError] = useState(null)

  // RPS 周期状态 - 气泡图默认RPS20，分组默认RPS120
  const [rpsPeriod, setRpsPeriod] = useState(20)
  const [rpsGroupPeriod, setRpsGroupPeriod] = useState(120)
  const initializedRef = useRef(false)

  const toYmd = (d) => (d ? d.format('YYYYMMDD') : '')

  // 外部传入的initialDate变化时更新
  useEffect(() => {
    if (initialDate) {
      const newDate = dayjs(initialDate, 'YYYYMMDD')
      setDate(newDate)
      // 重新加载数据
      fetchData(initialDate, rpsGroupPeriod)
      fetchBubbleData(initialDate, rpsPeriod)
    }
  }, [initialDate])

  // 获取气泡数据
  const fetchBubbleData = async (queryDate, rps) => {
    setBubbleLoading(true)
    setBubbleError(null)
    try {
      const params = { rps_period: rps }
      // 总是传date参数，使用queryDate或当前选中的date
      params.date = queryDate || toYmd(date) || undefined
      const res = await marketAnalysisApi.getBubble(params)
      setBubbleData(res)
    } catch (e) {
      setBubbleError(e.response?.data?.detail || '获取气泡数据失败')
    } finally {
      setBubbleLoading(false)
    }
  }

  // 获取分析数据（优先从缓存读取分组统计）
  const fetchData = async (queryDate, rpsGroup) => {
    setLoading(true)
    setError(null)
    try {
      const dateStr = queryDate || toYmd(date) || undefined

      // 缓存中的 rps_stats 固定为 RPS20，仅当选择 RPS20 时使用缓存
      // 其他周期需要实时计算以获取正确的分组数据
      const useCache = rpsGroup === 20
      let cachedStats = null

      if (useCache) {
        try {
          const groupRes = await marketReviewApi.getGroupStats(dateStr)
          if (groupRes?.success && groupRes?.stats && Object.keys(groupRes.stats).length > 0) {
            cachedStats = groupRes.stats
          }
        } catch (e) {
          // 缓存读取失败，继续实时计算
        }
      }

      if (cachedStats) {
        // 使用缓存数据
        setData({
          date: dateStr,
          total_stocks: 0,
          rps_stats: cachedStats.rps_stats || [],
          amount_stats: cachedStats.amount_stats || [],
          price_stats: cachedStats.price_stats || [],
          float_mv_stats: cachedStats.float_mv_stats || [],
        })
      } else {
        // 缓存未命中或非 RPS20 周期，实时计算
        const params = {}
        if (dateStr) params.date = dateStr
        if (rpsGroup) params.rps_period = rpsGroup
        const res = await marketAnalysisApi.getAnalysis(params)
        setData(res)
        // 首次加载时同步日期
        if (!queryDate && res?.date) {
          setDate(dayjs(res.date))
        }
      }
    } catch (e) {
      setError(e.response?.data?.detail || '获取数据失败')
    } finally {
      setLoading(false)
    }
  }

  // 初始加载
  useEffect(() => {
    if (initializedRef.current) return
    initializedRef.current = true
    fetchData(null, rpsGroupPeriod)
    fetchBubbleData(null, rpsPeriod)
  }, [])

  // RPS 周期改变时重新获取气泡数据
  useEffect(() => {
    const ymd = toYmd(date)
    fetchBubbleData(ymd || null, rpsPeriod)
  }, [rpsPeriod])

  // RPS 分组周期改变时重新获取分析数据
  useEffect(() => {
    const ymd = toYmd(date)
    fetchData(ymd || null, rpsGroupPeriod)
  }, [rpsGroupPeriod])

  const handleQuery = () => {
    const ymd = toYmd(date)
    fetchData(ymd, rpsGroupPeriod)
    fetchBubbleData(ymd, rpsPeriod)
  }

  // ===== 气泡图 ECharts 配置 =====
  const getBubbleOption = () => {
    if (!bubbleData || !bubbleData.nodes || bubbleData.nodes.length === 0) return {}

    const isSector = bubbleData.mode === 'sector'
    const yAxisName = isSector ? '涨跌幅%' : '股价百分位 (1-100)'
    const rpsLabel = `RPS${bubbleData.rps_period || rpsPeriod}`

    // 计算 Y 轴范围（基于实际数据，无边距）
    let yMin = 0, yMax = 100
    if (isSector && bubbleData.nodes.length > 0) {
      const chgValues = bubbleData.nodes.map(n => n[1])
      yMin = Math.min(...chgValues)
      yMax = Math.max(...chgValues)
    }

    // 预处理数据
    const processed = bubbleData.nodes.map(n => {
      const symbolSize = isSector
        ? 10 + Math.sqrt(n[2]) * 2.5  // 气泡大小+6px
        : 9 + Math.sqrt(n[2]) * 2
      return [
        n[0], n[1], n[2], n[3], n[4], n[5],
        n[6] || 0,        // 6: 成分股数
        symbolSize,       // 7: symbolSize
        getBubbleColor(n[3]), // 8: color
        n[7] || null,     // 9: RPS10
        n[8] || null,     // 10: RPS20
        n[9] || null,     // 11: RPS50
      ]
    })

    return {
      title: {
        show: false,
      },
      tooltip: {
        trigger: 'item',
        backgroundColor: 'rgba(255,255,255,0.96)',
        borderColor: '#ddd',
        borderWidth: 1,
        padding: [10, 12],
        textStyle: { color: '#333', fontSize: 12 },
        formatter: (params) => {
          const d = params.data
          const amountPct = d[2]
          const chg = d[3]
          const name = d[4]
          const code = d[5]
          const stockCount = d[6]
          const rps10 = d[9]
          const rps20 = d[10]
          const rps50 = d[11]
          const chgColor = chg > 0 ? COLORS.up : COLORS.down
          const sign = chg > 0 ? '+' : ''

          return `
            <div style="font-size:14px;font-weight:bold;margin-bottom:2px">${name}</div>
            <div style="font-size:11px;color:#999;margin-bottom:6px">${code}</div>
            <table style="font-size:12px;line-height:1.8">
              <tr><td style="color:#999;padding-right:8px">成交额百分位:</td><td style="font-weight:bold">${amountPct}%</td></tr>
              <tr><td style="color:#999;padding-right:8px">涨跌幅:</td><td style="font-weight:bold;color:${chgColor}">${sign}${chg}%</td></tr>
              <tr><td colspan="2" style="border-top:1px solid #eee;padding-top:4px"></td></tr>
              <tr><td style="color:#999;padding-right:8px">RPS10:</td><td style="font-weight:bold">${rps10 !== null && rps10 !== undefined ? rps10 : '-'}</td></tr>
              <tr><td style="color:#999;padding-right:8px">RPS20:</td><td style="font-weight:bold">${rps20 !== null && rps20 !== undefined ? rps20 : '-'}</td></tr>
              <tr><td style="color:#999;padding-right:8px">RPS50:</td><td style="font-weight:bold">${rps50 !== null && rps50 !== undefined ? rps50 : '-'}</td></tr>
            </table>`
        },
      },
      grid: { left: 55, right: 30, top: 15, bottom: 40 },
      xAxis: {
        type: 'value',
        name: `${rpsLabel} 相对强度 (85-100)`,
        nameLocation: 'center',
        nameGap: 30,
        nameTextStyle: { color: '#666', fontSize: 11 },
        min: 85, max: 100,
        axisLabel: { color: '#888', fontSize: 9 },
        splitLine: { lineStyle: { color: '#f0f0f0', type: 'dashed' } },
      },
      yAxis: {
        type: 'value',
        name: yAxisName,
        nameLocation: 'center',
        nameGap: 35,
        nameTextStyle: { color: '#666', fontSize: 11 },
        min: isSector ? yMin : 0,
        max: isSector ? yMax : 100,
        axisLabel: { color: '#888', fontSize: 9 },
        splitLine: { lineStyle: { color: '#f0f0f0', type: 'dashed' } },
      },
      dataZoom: [],
      series: [
        {
          type: 'scatter',
          data: processed,
          symbolSize: function (val) { return val[7] },
          itemStyle: {
            color: function (params) { return params.data[8] },
            borderColor: 'rgba(255,255,255,0.6)',
            borderWidth: 1,
            opacity: isSector ? 0.6 : 0.7,
          },
          label: {
            show: true,
            formatter: function (params) {
              const name = params.data[4] || ''
              const size = params.data[7] || 0
              if (size < 15) return ''

              const truncated = name.length > 6 ? name.slice(0, 6) : name
              return truncated
            },
            fontSize: 10,
            color: '#000',
            fontWeight: 'bold',
            textBorderColor: '#fff',
            textBorderWidth: 1,
            position: 'inside',
            lineHeight: 12,
            overflow: 'break',
          },
          labelLayout: function (params) {
            const size = params.data?.[7] || 0
            const fontSize = Math.max(7, Math.min(12, size / 4))
            return {
              fontSize: fontSize,
              lineHeight: fontSize + 2,
            }
          },
          emphasis: {
            scale: 1.6,
            label: {
              show: true,
              fontSize: 13,
              fontWeight: 'bold',
              formatter: function (params) { return params.data[4] || '' },
            },
            itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)' },
          },
          markLine: {
            silent: true,
            symbol: 'none',
            lineStyle: { color: '#ccc', type: 'dashed', width: 1 },
            data: [{ xAxis: 80 }],
            label: { show: true, position: 'end', formatter: '强势线', color: '#999', fontSize: 10 },
          },
          large: false,
          progressive: 1000,
          progressiveThreshold: 2000,
        },
      ],
    }
  }

  // ===== 通用柱状图配置 =====
  const getBarOption = (stats, xLabel) => {
    const categories = stats.map(s => s.category_label)
    const values = stats.map(s => s.avg_chg)

    return {
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(22,33,62,0.95)',
        borderColor: COLORS.grid,
        textStyle: { color: COLORS.text, fontSize: 11 },
        axisPointer: { type: 'cross' },
        formatter: (params) => {
          const d = params[0]
          const stat = stats[d.dataIndex]
          const chgColor = d.value > 0 ? COLORS.up : COLORS.down
          const sign = d.value > 0 ? '+' : ''
          return `<div style="font-weight:bold;margin-bottom:4px">${xLabel}: ${d.name}</div>
                  <div>平均涨跌幅: <span style="color:${chgColor};font-weight:bold">${sign}${d.value}%</span></div>
                  <div style="color:#999;font-size:11px">股票数: ${stat.count}</div>`
        },
      },
      grid: { left: 45, right: 12, top: 12, bottom: 32 },
      xAxis: {
        type: 'category',
        data: categories,
        axisLabel: {
          color: '#888',
          fontSize: 9,
          rotate: categories.length > 8 ? 30 : 0,
          interval: categories.length > 8 ? 'auto' : 0,
        },
        axisLine: { lineStyle: { color: '#e0e0e0' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          color: '#888',
          fontSize: 11,
          formatter: (v) => `${v > 0 ? '+' : ''}${v}%`,
        },
        splitLine: { lineStyle: { color: '#f0f0f0', type: 'dashed' } },
        axisLine: { show: false },
      },
      series: [{
        type: 'bar',
        data: values,
        barMaxWidth: 28,
        itemStyle: {
          color: (params) => params.value > 0 ? COLORS.up : COLORS.down,
          borderRadius: [3, 3, 0, 0],
        },
        emphasis: {
          itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)' },
        },
      }],
    }
  }

  return (
    <ConfigProvider>
      <div className="space-y-3 md:space-y-4">
        {/* 气泡图 */}
        <div data-section="板块气泡图" className="bg-white rounded-xl shadow-sm overflow-hidden">
          <div className="p-3 md:p-4 pb-2">
            <div className="flex items-center justify-between">
              <h3 className="text-sm md:text-base font-semibold text-gray-800">
                <span className="hidden sm:inline">板块四维动量气泡图</span>
                <span className="sm:hidden">板块气泡图</span>
                {bubbleData && (
                  <span className="text-xs font-normal text-gray-400 ml-1 md:ml-2">
                    ({bubbleData.date} · {bubbleData.total}个)
                  </span>
                )}
              </h3>
              <Segmented
                options={RPS_PERIODS}
                value={rpsPeriod}
                onChange={setRpsPeriod}
                size="small"
              />
            </div>
          </div>
          {bubbleLoading ? (
            <div className="flex justify-center items-center h-[300px] md:h-[500px]">
              <span className="text-gray-400">加载中...</span>
            </div>
          ) : bubbleError ? (
            <div className="flex justify-center items-center h-[300px] md:h-[500px]">
              <span className="text-red-400">{bubbleError}</span>
            </div>
          ) : bubbleData ? (
            <ReactECharts
              option={getBubbleOption()}
              style={{ height: '300px' }}
              opts={{ renderer: 'canvas' }}
              notMerge={true}
              className="md:!h-[600px]"
              onEvents={{
                click: (params) => {
                  if (params.componentType === 'series') {
                    const name = params.data?.[4]
                    if (name) {
                      navigate(`/search?keyword=${encodeURIComponent(name)}`)
                    }
                  }
                }
              }}
            />
          ) : null}
        </div>

        {/* RPS 分组统计 */}
        {data && !loading && (
          <div data-section="RPS分组统计" className="bg-white rounded-xl shadow-sm overflow-hidden">
            <div className="p-3 md:p-4 pb-2">
              <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-2">
                <div>
                  <h3 className="text-sm md:text-base font-semibold text-gray-800">按 RPS 分组</h3>
                  <p className="text-[10px] md:text-xs text-gray-400 mt-0.5 md:mt-1">RPS 越高代表相对强度越大</p>
                </div>
                <Segmented
                  options={RPS_GROUP_PERIODS}
                  value={rpsGroupPeriod}
                  onChange={setRpsGroupPeriod}
                  size="small"
                />
              </div>
            </div>
            <ReactECharts
              option={getBarOption(data.rps_stats, 'RPS区间')}
              style={{ height: '250px' }}
              opts={{ renderer: 'canvas' }}
              className="md:!h-[350px]"
            />
          </div>
        )}

        {/* 成交额统计 */}
        {data && !loading && (
          <div data-section="成交额分组统计" className="bg-white rounded-xl shadow-sm overflow-hidden">
            <div className="p-3 md:p-4 pb-2">
              <h3 className="text-sm md:text-base font-semibold text-gray-800">按成交额分组</h3>
              <p className="text-[10px] md:text-xs text-gray-400 mt-0.5 md:mt-1">从左到右成交额递增</p>
            </div>
            <ReactECharts
              option={getBarOption(data.amount_stats, '成交额区间')}
              style={{ height: '250px' }}
              opts={{ renderer: 'canvas' }}
              className="md:!h-[350px]"
            />
          </div>
        )}

        {/* 股价统计 */}
        {data && !loading && (
          <div data-section="股价分组统计" className="bg-white rounded-xl shadow-sm overflow-hidden">
            <div className="p-3 md:p-4 pb-2">
              <h3 className="text-sm md:text-base font-semibold text-gray-800">按股价分组</h3>
              <p className="text-[10px] md:text-xs text-gray-400 mt-0.5 md:mt-1">从左到右股价递增</p>
            </div>
            <ReactECharts
              option={getBarOption(data.price_stats, '股价区间')}
              style={{ height: '250px' }}
              opts={{ renderer: 'canvas' }}
              className="md:!h-[350px]"
            />
          </div>
        )}

        {/* 流通市值统计 */}
        {data && !loading && data.float_mv_stats && data.float_mv_stats.length > 0 && (
          <div data-section="流通市值分组统计" className="bg-white rounded-xl shadow-sm overflow-hidden">
            <div className="p-3 md:p-4 pb-2">
              <h3 className="text-sm md:text-base font-semibold text-gray-800">按流通市值分组</h3>
              <p className="text-[10px] md:text-xs text-gray-400 mt-0.5 md:mt-1">从左到右市值递增（亿元）</p>
            </div>
            <ReactECharts
              option={getBarOption(data.float_mv_stats, '市值区间')}
              style={{ height: '250px' }}
              opts={{ renderer: 'canvas' }}
              className="md:!h-[350px]"
            />
          </div>
        )}

        {/* 加载/错误状态 */}
        {loading && (
          <div className="flex justify-center items-center h-24 md:h-32 bg-white rounded-xl shadow-sm">
            <span className="text-gray-400">加载中...</span>
          </div>
        )}
        {error && !loading && (
          <div className="flex justify-center items-center h-24 md:h-32 bg-white rounded-xl shadow-sm">
            <span className="text-red-500">{error}</span>
          </div>
        )}
      </div>
    </ConfigProvider>
  )
}
