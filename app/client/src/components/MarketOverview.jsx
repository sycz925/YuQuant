import React, { useState, useEffect } from 'react'
import { Spin, Table } from 'antd'
import { marketReviewApi } from '../api'

function MarketOverview({ date }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    loadData()
  }, [date])

  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await marketReviewApi.getOverview(date)
      setData(res)
    } catch (e) {
      console.error('加载市场概览失败:', e)
      setError(e.response?.data?.detail || '加载失败')
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-12 flex flex-col items-center justify-center">
        <Spin size="large" />
        <p className="mt-4 text-sm text-gray-500 font-medium">加载市场数据...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-8 text-center">
        <p className="text-red-500 text-sm">{error}</p>
      </div>
    )
  }

  if (!data || !data.indices || data.indices.length === 0) return null

  const { indices, trade_date } = data

  const formatDate = (d) => {
    if (!d || d.length !== 8) return d
    return `${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6,8)}`
  }

  const STATUS_COLORS = { '红': '#ef5350', '绿': '#22c55e', '蓝': '#3b82f6' }

  const renderStatus = (text) => {
    if (!text) return '-'
    const parts = text.match(/日([红绿蓝])周([红绿蓝])/)
    if (!parts) return <span>{text}</span>
    return (
      <span>
        <span style={{ color: STATUS_COLORS[parts[1]] }}>日{parts[1]}</span>
        <span style={{ color: STATUS_COLORS[parts[2]] }}>周{parts[2]}</span>
      </span>
    )
  }

  const columns = [
    {
      title: '指数名称',
      dataIndex: 'name',
      key: 'name',
      width: 120,
      render: (v, _, idx) => (
        <span className={`font-bold ${idx === 0 ? 'text-indigo-600' : 'text-gray-900'}`}>
          {v}
        </span>
      ),
    },
    {
      title: '代码',
      dataIndex: 'code',
      key: 'code',
      width: 60,
      render: (v) => <span className="font-mono text-gray-400 text-xs">{v}</span>,
    },
    {
      title: '最新价',
      dataIndex: 'close',
      key: 'close',
      width: 100,
      align: 'center',
      render: (v) => <span className="font-mono font-bold text-gray-700">{v?.toFixed(2)}</span>,
    },
    {
      title: '涨跌幅',
      dataIndex: 'pct_chg',
      key: 'pct_chg',
      width: 100,
      align: 'center',
      sorter: (a, b) => (a.pct_chg || 0) - (b.pct_chg || 0),
      render: (v) => (
        <span className={`font-mono font-bold ${v > 0 ? 'text-red-600' : v < 0 ? 'text-green-600' : 'text-gray-500'}`}>
          {v > 0 ? '+' : ''}{v?.toFixed(2)}%
        </span>
      ),
    },
    {
      title: '状态',
      dataIndex: 'tdx_status',
      key: 'tdx_status',
      width: 100,
      align: 'center',
      render: (v) => renderStatus(v),
    },
    {
      title: 'PE_TTM',
      dataIndex: 'pe_ttm',
      key: 'pe_ttm',
      width: 100,
      align: 'center',
      render: (v) => <span className="font-mono text-gray-500 text-xs">{v ? v.toFixed(2) : '-'}</span>,
    },
    {
      title: '点评',
      dataIndex: 'comment',
      key: 'comment',
      render: (v) => (
        <span className={`text-xs font-medium ${
          (v || '').includes('爆发') ? 'text-orange-500' :
          (v || '').includes('最强') ? 'text-indigo-500' :
          (v || '').includes('偏强') ? 'text-red-500' :
          (v || '').includes('调整') ? 'text-green-500' :
          'text-gray-500'
        }`}>
          {v || '-'}
        </span>
      ),
    },
  ]

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
      {/* 标题栏 */}
      <div className="px-3 md:px-6 py-3 md:py-4 border-b border-gray-100 flex items-center justify-between">
        <div className="flex items-center space-x-2 md:space-x-3">
          <div className="w-1 h-4 md:h-5 bg-indigo-500 rounded-full"></div>
          <h2 className="text-sm md:text-base font-black text-gray-900 tracking-tight">主要大盘指数涨跌幅</h2>
        </div>
        <span className="text-[10px] md:text-xs text-gray-400 font-mono">{formatDate(trade_date)}</span>
      </div>

      {/* 指数表格 */}
      <div className="p-3 md:p-6">
        <Table
          dataSource={indices}
          columns={columns}
          rowKey="code"
          pagination={false}
          size="small"
          scroll={{ x: 700 }}
        />
      </div>
    </div>
  )
}

export default MarketOverview
