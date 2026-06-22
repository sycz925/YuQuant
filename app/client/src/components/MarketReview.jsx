import React, { useState, useEffect } from 'react'
import { Spin, Tag, Table, Tooltip, Modal } from 'antd'
import ReactECharts from 'echarts-for-react'
import { marketReviewApi } from '../api'

function MarketReview() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [modalVisible, setModalVisible] = useState(false)
  const [modalTitle, setModalTitle] = useState('')
  const [modalData, setModalData] = useState([])

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await marketReviewApi.getReview()
      setData(res)
    } catch (e) {
      console.error('加载复盘数据失败:', e)
      setError(e.response?.data?.detail || '加载失败')
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="bg-gray-900/95 rounded-2xl p-12 flex flex-col items-center justify-center">
        <Spin size="large" />
        <p className="mt-4 text-gray-400 text-sm font-medium">正在生成复盘报告...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-gray-900/95 rounded-2xl p-8 text-center">
        <p className="text-red-400 text-sm">{error}</p>
      </div>
    )
  }

  if (!data) return null

  const { market_summary, strong_stocks_top50, industry_cluster, trade_date } = data

  const formatPercent = (v) => v != null ? `${v}%` : '-'
  const formatDate = (d) => {
    if (!d || d.length !== 8) return d
    return `${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6,8)}`
  }

  const getChgColor = (v) => {
    if (v > 0) return 'text-red-500'
    if (v < 0) return 'text-green-500'
    return 'text-gray-400'
  }

  const getChgBg = (v) => {
    if (v >= 20) return 'bg-red-500/20 text-red-400'
    if (v >= 10) return 'bg-orange-500/20 text-orange-400'
    if (v > 0) return 'bg-red-500/10 text-red-400'
    if (v < 0) return 'bg-green-500/10 text-green-400'
    return 'bg-gray-500/10 text-gray-400'
  }

  const getTagColor = (v) => {
    if (v >= 20) return '#ef4444'
    if (v >= 10) return '#f97316'
    if (v > 0) return '#ef4444'
    return '#22c55e'
  }

  const showStockModal = (title, stocks) => {
    setModalTitle(title)
    setModalData(stocks || [])
    setModalVisible(true)
  }

  const stockColumns = [
    { title: '代码', dataIndex: 'code', key: 'code', width: 80, render: (v) => <span className="font-mono text-xs">{v}</span> },
    { title: '名称', dataIndex: 'name', key: 'name', width: 100 },
    { title: '涨跌幅', dataIndex: 'pct_chg', key: 'pct_chg', width: 80, render: (v) => <span className={`font-mono text-xs ${getChgColor(v)}`}>{v > 0 ? '+' : ''}{v}%</span> },
    { title: '收盘价', dataIndex: 'close', key: 'close', width: 80, render: (v) => <span className="font-mono text-xs">{v?.toFixed(2)}</span> },
  ]

  const getBarChartOption = () => {
    if (!industry_cluster || industry_cluster.length === 0) return null
    const sorted = [...industry_cluster].sort((a, b) => a.pct - b.pct)
    return {
      grid: { left: 100, right: 60, top: 10, bottom: 30 },
      xAxis: {
        type: 'value',
        axisLabel: { color: '#6b7280', fontSize: 11, formatter: '{value}%' },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { lineStyle: { color: '#1f2937' } }
      },
      yAxis: {
        type: 'category',
        data: sorted.map(i => i.industry),
        axisLabel: { color: '#d1d5db', fontSize: 11, fontWeight: 600 },
        axisLine: { show: false },
        axisTick: { show: false }
      },
      series: [{
        type: 'bar',
        data: sorted.map(i => ({
          value: i.pct,
          label: {
            show: true,
            position: 'right',
            formatter: `${i.pct}%  (${i.count}只)`,
            color: '#9ca3af',
            fontSize: 11,
            fontWeight: 600
          }
        })),
        barWidth: 18,
        itemStyle: {
          borderRadius: [0, 4, 4, 0],
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 1, y2: 0,
            colorStops: [
              { offset: 0, color: '#6366f1' },
              { offset: 1, color: '#8b5cf6' }
            ]
          }
        }
      }],
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#1f2937',
        borderColor: '#374151',
        textStyle: { color: '#e5e7eb', fontSize: 12 },
        formatter: (params) => {
          const p = params[0]
          const item = industry_cluster.find(i => i.industry === p.name)
          const stocks = item?.stocks?.join('、') || ''
          return `<div style="font-weight:700;margin-bottom:4px">${p.name}</div>
                  <div>占比: ${p.value}%</div>
                  <div>数量: ${item?.count || 0} 只</div>
                  ${stocks ? `<div style="margin-top:4px;color:#9ca3af;font-size:11px">${stocks}</div>` : ''}`
        }
      }
    }
  }

  const columns = [
    {
      title: '#',
      width: 40,
      render: (_, __, i) => <span className="text-gray-500 text-xs font-mono">{i + 1}</span>
    },
    {
      title: '代码',
      dataIndex: 'code',
      width: 80,
      render: (t) => <span className="font-mono text-xs text-gray-300">{t}</span>
    },
    {
      title: '名称',
      dataIndex: 'name',
      width: 100,
      render: (t, r) => (
        <span className="text-xs font-medium text-white">
          {t}
          {r.is_touch_250h && (
            <Tooltip title="创250日新高">
              <span className="ml-1 text-yellow-400">★</span>
            </Tooltip>
          )}
        </span>
      )
    },
    {
      title: '收盘',
      dataIndex: 'close',
      width: 80,
      align: 'right',
      render: (v) => <span className="font-mono text-xs text-gray-300">{v?.toFixed(2)}</span>
    },
    {
      title: '涨幅',
      dataIndex: 'pct_chg',
      width: 80,
      align: 'right',
      sorter: (a, b) => a.pct_chg - b.pct_chg,
      defaultSortOrder: 'descend',
      render: (v) => (
        <span className={`font-mono text-xs font-bold ${getChgColor(v)}`}>
          {v > 0 ? '+' : ''}{v?.toFixed(2)}%
        </span>
      )
    },
    {
      title: '距250H',
      dataIndex: 'ratio_250h',
      width: 80,
      align: 'right',
      render: (v) => (
        <span className={`font-mono text-xs ${v >= 99 ? 'text-yellow-400 font-bold' : 'text-gray-400'}`}>
          {v}%
        </span>
      )
    },
  ]

  const expandColumns = [
    ...columns.slice(0, 5),
    {
      title: '分组',
      width: 100,
      render: (_, r) => {
        if (r.pct_chg >= 20) return <Tag color="#ef4444" style={{ margin: 0, fontSize: 10 }}>涨停</Tag>
        if (r.pct_chg >= 10) return <Tag color="#f97316" style={{ margin: 0, fontSize: 10 }}>强势</Tag>
        return <Tag color="#3b82f6" style={{ margin: 0, fontSize: 10 }}>活跃</Tag>
      }
    }
  ]

  const getGroupedData = () => {
    if (!strong_stocks_top50) return []
    const limitUp = strong_stocks_top50.filter(s => s.pct_chg >= 20)
    const strong = strong_stocks_top50.filter(s => s.pct_chg >= 10 && s.pct_chg < 20)
    const active = strong_stocks_top50.filter(s => s.pct_chg < 10)

    const groups = []
    if (limitUp.length > 0) groups.push({ group: '涨停组 (≥20%)', stocks: limitUp })
    if (strong.length > 0) groups.push({ group: '强势组 (10%~19%)', stocks: strong })
    if (active.length > 0) groups.push({ group: '活跃组 (<10%)', stocks: active })
    return groups
  }

  return (
    <div className="bg-gray-900/95 rounded-2xl border border-gray-800 overflow-hidden">
      <div className="px-6 py-4 border-b border-gray-800 flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <div className="w-1 h-6 bg-gradient-to-b from-indigo-500 to-purple-600 rounded-full"></div>
          <h2 className="text-lg font-black text-white tracking-tight">全栈量化复盘报告</h2>
          <span className="text-xs text-gray-500 font-mono">{formatDate(trade_date)}</span>
        </div>
        <span className="text-xs text-gray-600">Powered by YuQuant</span>
      </div>

      <div className="p-6 space-y-6">
        {/* 市场概览卡片 */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-gray-800/50 rounded-xl p-4 border border-gray-700/50">
            <div className="text-gray-500 text-[10px] font-bold uppercase tracking-widest mb-2">全市场股票</div>
            <div className="text-2xl font-black text-white">{market_summary?.total_stocks || 0}</div>
            <div className="text-[10px] text-gray-500 mt-1">只</div>
          </div>
          <div className="bg-gray-800/50 rounded-xl p-4 border border-gray-700/50">
            <div className="text-gray-500 text-[10px] font-bold uppercase tracking-widest mb-2">站上50日线</div>
            <div 
              className="text-2xl font-black text-blue-400 cursor-pointer hover:text-blue-300 transition-colors"
              onClick={() => showStockModal('站上50日线个股', market_summary?.above_ma50_stocks)}
            >
              {market_summary?.above_ma50_count || 0}
            </div>
            <div className="text-[10px] text-gray-500 mt-1">
              占比 <span className={`font-bold ${(market_summary?.above_ma50_pct || 0) > 50 ? 'text-green-400' : (market_summary?.above_ma50_pct || 0) > 30 ? 'text-yellow-400' : 'text-red-400'}`}>
                {formatPercent(market_summary?.above_ma50_pct)}
              </span>
            </div>
          </div>
          <div className="bg-gray-800/50 rounded-xl p-4 border border-gray-700/50">
            <div className="text-gray-500 text-[10px] font-bold uppercase tracking-widest mb-2">历史新高</div>
            <div 
              className="text-2xl font-black text-yellow-400 cursor-pointer hover:text-yellow-300 transition-colors"
              onClick={() => showStockModal('历史新高个股', market_summary?.new_high_stocks)}
            >
              {market_summary?.new_high_count || 0}
            </div>
            <div className="text-[10px] text-gray-500 mt-1">只 (250日)</div>
          </div>
          <div className="bg-gray-800/50 rounded-xl p-4 border border-gray-700/50">
            <div className="text-gray-500 text-[10px] font-bold uppercase tracking-widest mb-2">强势股</div>
            <div 
              className="text-2xl font-black text-orange-400 cursor-pointer hover:text-orange-300 transition-colors"
              onClick={() => showStockModal('强势股（近250H≥90%）', strong_stocks_top50)}
            >
              {strong_stocks_top50?.length || 0}
            </div>
            <div className="text-[10px] text-gray-500 mt-1">只 (近250H≥90%)</div>
          </div>
        </div>

        {/* Modal */}
        <Modal
          title={modalTitle}
          open={modalVisible}
          onCancel={() => setModalVisible(false)}
          footer={null}
          width={600}
        >
          <Table
            dataSource={modalData}
            columns={stockColumns}
            rowKey="code"
            size="small"
            pagination={{ pageSize: 20 }}
            bordered
          />
        </Modal>

        {/* 行业聚类图 */}
        {industry_cluster && industry_cluster.length > 0 && (
          <div className="bg-gray-800/30 rounded-xl p-5 border border-gray-700/50">
            <div className="flex items-center space-x-2 mb-4">
              <div className="w-1 h-4 bg-purple-500 rounded-full"></div>
              <h3 className="text-sm font-bold text-gray-300">强势股产业链分布</h3>
              <span className="text-[10px] text-gray-600 ml-auto">Top {industry_cluster.length} 行业</span>
            </div>
            <div className="h-[280px]">
              <ReactECharts option={getBarChartOption()} style={{ height: '100%', width: '100%' }} />
            </div>
          </div>
        )}

        {/* 强势股列表 */}
        {strong_stocks_top50 && strong_stocks_top50.length > 0 && (
          <div className="bg-gray-800/30 rounded-xl p-5 border border-gray-700/50">
            <div className="flex items-center space-x-2 mb-4">
              <div className="w-1 h-4 bg-orange-500 rounded-full"></div>
              <h3 className="text-sm font-bold text-gray-300">强势股集中营</h3>
              <span className="text-[10px] text-gray-600 ml-auto">共 {strong_stocks_top50.length} 只</span>
            </div>

            {getGroupedData().map((group, gi) => (
              <div key={gi} className="mb-4 last:mb-0">
                <div className="flex items-center space-x-2 mb-2">
                  <Tag
                    color={group.group.includes('涨停') ? '#ef4444' : group.group.includes('强势') ? '#f97316' : '#3b82f6'}
                    style={{ margin: 0, fontSize: 10, fontWeight: 700 }}
                  >
                    {group.group}
                  </Tag>
                  <span className="text-[10px] text-gray-600">{group.stocks.length} 只</span>
                </div>
                <Table
                  dataSource={group.stocks}
                  columns={expandColumns}
                  rowKey="code"
                  size="small"
                  pagination={false}
                  bordered
                  className="dark-table"
                  rowClassName={() => 'bg-gray-900/50 hover:bg-gray-800/50'}
                />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default MarketReview
