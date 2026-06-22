import React, { useState, useEffect, useRef } from 'react'
import ReactECharts from 'echarts-for-react'
import { ConfigProvider, DatePicker, Button, Select, Space, Segmented } from 'antd'
import dayjs from 'dayjs'
import { marketAnalysisApi } from '../api'

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

export default function MarketAnalysis() {
  const [date, setDate] = useState(null)
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

  // 获取气泡数据
  const fetchBubbleData = async (queryDate, rps) => {
    setBubbleLoading(true)
    setBubbleError(null)
    try {
      const params = { rps_period: rps }
      if (queryDate) params.date = queryDate
      const res = await marketAnalysisApi.getBubble(params)
      setBubbleData(res)
    } catch (e) {
      setBubbleError(e.response?.data?.detail || '获取气泡数据失败')
    } finally {
      setBubbleLoading(false)
    }
  }

  // 获取分析数据
  const fetchData = async (queryDate, rpsGroup) => {
    setLoading(true)
    setError(null)
    try {
      const params = {}
      if (queryDate) params.date = queryDate
      if (rpsGroup) params.rps_period = rpsGroup
      const res = await marketAnalysisApi.getAnalysis(params)
      const data = res
      setData(data)
      // 首次加载时同步日期
      if (!queryDate && data?.date) {
        setDate(dayjs(data.date))
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
        padding: [12, 16],
        textStyle: { color: '#333', fontSize: 13 },
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
      grid: { left: 70, right: 40, top: 20, bottom: 50 },
      xAxis: {
        type: 'value',
        name: `${rpsLabel} 相对强度 (0-100)`,
        nameLocation: 'center',
        nameGap: 38,
        nameTextStyle: { color: '#666', fontSize: 13 },
        min: 0, max: 100,
        axisLabel: { color: '#888', fontSize: 11 },
        splitLine: { lineStyle: { color: '#f0f0f0', type: 'dashed' } },
      },
      yAxis: {
        type: 'value',
        name: yAxisName,
        nameLocation: 'center',
        nameGap: 42,
        nameTextStyle: { color: '#666', fontSize: 13 },
        min: isSector ? yMin : 0,
        max: isSector ? yMax : 100,
        axisLabel: { color: '#888', fontSize: 11 },
        splitLine: { lineStyle: { color: '#f0f0f0', type: 'dashed' } },
      },
      dataZoom: [
        { type: 'inside', xAxisIndex: 0, startValue: 80, endValue: 100 },
        { type: 'inside', yAxisIndex: 0 },
        { type: 'slider', xAxisIndex: 0, bottom: 8, height: 16, startValue: 80, endValue: 100, borderColor: 'transparent', backgroundColor: 'rgba(0,0,0,0.05)', fillerColor: 'rgba(0,0,0,0.08)', handleStyle: { color: '#999' } },
        { type: 'slider', yAxisIndex: 0, right: 4, width: 16, borderColor: 'transparent', backgroundColor: 'rgba(0,0,0,0.05)', fillerColor: 'rgba(0,0,0,0.08)', handleStyle: { color: '#999' } },
      ],
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
              if (size < 18) return ''

              const truncated = name.length > 9 ? name.slice(0, 9) : name
              const lines = []
              let i = 0
              while (i < truncated.length) {
                const ch = truncated[i]
                const isAscii = ch.charCodeAt(0) <= 127
                if (isAscii) {
                  let end = i
                  while (end < truncated.length && end - i < 6 && truncated[end].charCodeAt(0) <= 127) end++
                  lines.push(truncated.slice(i, end))
                  i = end
                } else {
                  let end = i
                  while (end < truncated.length && end - i < 3 && truncated[end].charCodeAt(0) > 127) end++
                  lines.push(truncated.slice(i, end))
                  i = end
                }
              }
              return lines.join('\n')
            },
            fontSize: 13,
            color: '#000',
            fontWeight: 'bold',
            textBorderColor: '#fff',
            textBorderWidth: 2,
            position: 'inside',
            lineHeight: 13,
            overflow: 'break',
          },
          labelLayout: function (params) {
            const size = params.data?.[7] || 0
            // 根据气泡大小调整字体
            const fontSize = Math.max(8, Math.min(14, size / 4))
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
        textStyle: { color: COLORS.text, fontSize: 12 },
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
      grid: { left: 50, right: 16, top: 16, bottom: 36 },
      xAxis: {
        type: 'category',
        data: categories,
        axisLabel: {
          color: '#888',
          fontSize: 10,
          rotate: categories.length > 10 ? 30 : 0,
          interval: categories.length > 10 ? 'auto' : 0,
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
      <div className="space-y-4">
        {/* 标题栏 */}
        <div className="bg-white rounded-xl shadow-sm p-4">
          <div className="flex items-center justify-between flex-wrap gap-4">
            <h1 className="text-xl font-bold text-gray-800">市场多维统计分析</h1>
            <div className="flex items-center space-x-3">
              <DatePicker
                value={date}
                onChange={(d) => setDate(d)}
                format="YYYYMMDD"
                placeholder="选择交易日"
                allowClear
                style={{ minWidth: 150 }}
              />
              <Button type="primary" onClick={handleQuery} loading={loading}>
                查询
              </Button>
            </div>
          </div>

          {/* 数据概览 */}
          {data && (
            <div className="mt-3 pt-3 border-t border-gray-100 text-sm text-gray-500 flex flex-wrap gap-x-4">
              <span>交易日: <span className="font-mono font-medium text-gray-700">{data.date}</span></span>
              <span>统计: <span className="font-medium text-gray-700">{data.total_stocks}</span> 只股票</span>
              {data.is_final === true && (
                <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-700">
                  已收盘
                </span>
              )}
              {data.is_final === false && (
                <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-700">
                  收盘前
                </span>
              )}
            </div>
          )}
        </div>

        {/* 气泡图 */}
        <div className="bg-white rounded-xl shadow-sm overflow-hidden">
          <div className="p-4 pb-2">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-gray-800">
                板块四维动量气泡图
                {bubbleData && (
                  <span className="text-sm font-normal text-gray-400 ml-2">
                    ({bubbleData.date} · {bubbleData.total}个板块)
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
            <div className="flex justify-center items-center h-[500px]">
              <span className="text-gray-400">加载中...</span>
            </div>
          ) : bubbleError ? (
            <div className="flex justify-center items-center h-[500px]">
              <span className="text-red-400">{bubbleError}</span>
            </div>
          ) : bubbleData ? (
            <ReactECharts
              option={getBubbleOption()}
              style={{ height: 600 }}
              opts={{ renderer: 'canvas' }}
              notMerge={true}
            />
          ) : null}
        </div>

        {/* RPS 分组统计 */}
        {data && !loading && (
          <div className="bg-white rounded-xl shadow-sm overflow-hidden">
            <div className="p-4 pb-2">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="font-semibold text-gray-800">按 RPS 分组</h3>
                  <p className="text-xs text-gray-400 mt-1">RPS 越高代表相对强度越大，柱状图为该区间平均涨跌幅</p>
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
              style={{ height: 350 }}
              opts={{ renderer: 'canvas' }}
            />
          </div>
        )}

        {/* 成交额统计 */}
        {data && !loading && (
          <div className="bg-white rounded-xl shadow-sm overflow-hidden">
            <div className="p-4 pb-2">
              <h3 className="font-semibold text-gray-800">按成交额分组</h3>
              <p className="text-xs text-gray-400 mt-1">从左到右成交额递增（百分位），观察大/小成交额股票的平均涨跌幅</p>
            </div>
            <ReactECharts
              option={getBarOption(data.amount_stats, '成交额区间')}
              style={{ height: 350 }}
              opts={{ renderer: 'canvas' }}
            />
          </div>
        )}

        {/* 股价统计 */}
        {data && !loading && (
          <div className="bg-white rounded-xl shadow-sm overflow-hidden">
            <div className="p-4 pb-2">
              <h3 className="font-semibold text-gray-800">按股价分组</h3>
              <p className="text-xs text-gray-400 mt-1">从左到右股价递增（百分位），观察高/低股价股票的平均涨跌幅</p>
            </div>
            <ReactECharts
              option={getBarOption(data.price_stats, '股价区间')}
              style={{ height: 350 }}
              opts={{ renderer: 'canvas' }}
            />
          </div>
        )}

        {/* 加载/错误状态 */}
        {loading && (
          <div className="flex justify-center items-center h-32 bg-white rounded-xl shadow-sm">
            <span className="text-gray-400">加载中...</span>
          </div>
        )}
        {error && !loading && (
          <div className="flex justify-center items-center h-32 bg-white rounded-xl shadow-sm">
            <span className="text-red-500">{error}</span>
          </div>
        )}
      </div>
    </ConfigProvider>
  )
}
