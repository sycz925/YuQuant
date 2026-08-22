import React, { useState } from 'react'
import { Table, Tag, Button, Modal, Spin, Select } from 'antd'
import { ArrowLeftOutlined, TeamOutlined } from '@ant-design/icons'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { factorApi, marketReviewApi } from '../api'

const COLORS = {
  red: '#ef4444',
  orange: '#f97316',
  green: '#22c55e',
  gray: '#9ca3af',
}

function rpsColor(v) {
  if (v >= 90) return COLORS.red
  if (v >= 80) return COLORS.orange
  if (v <= 20) return COLORS.green
  return COLORS.gray
}

function SectorDetail() {
  const navigate = useNavigate()
  const { code } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const sectorName = searchParams.get('name') || code

  const rpsRed = searchParams.get('rps_red') || undefined
  const current = parseInt(searchParams.get('page') || '1', 10) || 1
  const pageSize = parseInt(searchParams.get('pageSize') || '50', 10) || 50
  const sortField = searchParams.get('sortBy')
  const sortOrder = searchParams.get('sortOrder')

  const [queueVisible, setQueueVisible] = useState(false)
  const [queueData, setQueueData] = useState(null)
  const [queueLoading, setQueueLoading] = useState(false)

  const updateParams = (patch) => {
    const next = new URLSearchParams(searchParams)
    Object.entries(patch).forEach(([k, v]) => {
      if (v === undefined || v === null || v === '') next.delete(k)
      else next.set(k, String(v))
    })
    setSearchParams(next, { replace: true })
  }

  const { data, isFetching } = useQuery({
    queryKey: ['sector_stocks', code, rpsRed],
    queryFn: () => factorApi.getSectorStocks(code, rpsRed ? { rps_red: rpsRed } : {}).then(r => r || {}),
  })

  const stocks = data?.stocks || []
  const tradeDate = data?.trade_date || ''

  const handleShowQueue = async () => {
    setQueueVisible(true)
    setQueueLoading(true)
    try {
      const res = await marketReviewApi.getSectorDetail(code)
      setQueueData(res?.success ? res : null)
    } catch {
      setQueueData(null)
    } finally {
      setQueueLoading(false)
    }
  }

  const sorterOrder = (field) => (sortField === field ? sortOrder : null)

  const columns = [
    { title: '代码', dataIndex: 'stock_code', width: 100, render: v => <span className="font-mono text-gray-500 text-xs">{v}</span> },
    {
      title: '名称', dataIndex: 'name', width: 110,
      render: (v, r) => (
        <button onClick={() => navigate(`/search?code=${r.stock_code}&name=${encodeURIComponent(v)}`)} className="text-blue-600 hover:text-blue-800 text-left text-sm">
          {v}
        </button>
      ),
    },
    {
      title: '最新价', dataIndex: 'close', width: 90, sorter: (a, b) => a.close - b.close, sortOrder: sorterOrder('close'),
      render: v => <span className="text-sm">{v?.toFixed(2)}</span>,
    },
    {
      title: '日涨幅', dataIndex: 'change_pct', width: 90, sorter: (a, b) => (a.change_pct || 0) - (b.change_pct || 0), sortOrder: sorterOrder('change_pct'),
      render: v => <span style={{ color: v > 0 ? COLORS.red : v < 0 ? COLORS.green : COLORS.gray }}>{v > 0 ? '+' : ''}{v?.toFixed(2)}%</span>,
    },
    ...['5d', '10d', '20d', '50d', '120d'].map(d => ({
      title: `${d === '5d' ? '5' : d === '10d' ? '10' : d === '20d' ? '20' : d === '50d' ? '50' : '120'}日涨幅`,
      dataIndex: `chg_${d}`,
      width: 90,
      sorter: (a, b) => (a[`chg_${d}`] || 0) - (b[`chg_${d}`] || 0),
      sortOrder: sorterOrder(`chg_${d}`),
      render: v => v != null ? <span style={{ color: v > 0 ? COLORS.red : v < 0 ? COLORS.green : COLORS.gray }}>{v > 0 ? '+' : ''}{v.toFixed(2)}%</span> : '-',
    })),
    ...['10', '50', '120'].map(d => ({
      title: `RPS${d}`,
      dataIndex: `rps_${d}`,
      width: 75,
      sorter: (a, b) => (a[`rps_${d}`] || 0) - (b[`rps_${d}`] || 0),
      sortOrder: sorterOrder(`rps_${d}`),
      render: v => v != null ? <span className="text-xs font-bold" style={{ color: rpsColor(v) }}>{v}</span> : '-',
    })),
  ]

  return (
    <div className="max-w-7xl mx-auto space-y-4">
      {/* 顶部操作栏 */}
      <div className="bg-white rounded-2xl shadow-sm p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <button onClick={() => navigate(-1)} className="flex items-center text-gray-600 hover:text-blue-600 transition-colors">
              <ArrowLeftOutlined className="mr-1" />
              <span className="text-sm">返回</span>
            </button>
            <span className="text-gray-300">|</span>
            <span className="text-xs px-2 py-0.5 rounded font-bold bg-purple-100 text-purple-600">板块</span>
            <span className="text-base font-bold" style={{ fontFamily: 'Fira Sans' }}>{sectorName}</span>
            {tradeDate && <span className="text-xs text-gray-400">{tradeDate}</span>}
            {data?.stock_count > 0 && <Tag className="ml-1">{data.stock_count}只</Tag>}
          </div>
          <div className="flex items-center space-x-3">
            <Select
              placeholder="RPS红筛选"
              allowClear
              size="small"
              style={{ width: 140 }}
              value={rpsRed}
              onChange={(v) => updateParams({ rps_red: v, page: undefined })}
              options={[
                { value: 'one', label: '一线红' },
                { value: 'two', label: '二线红' },
                { value: 'three', label: '三线红' },
              ]}
            />
            <Button icon={<TeamOutlined />} onClick={handleShowQueue} size="small">队列概况</Button>
          </div>
        </div>
      </div>

      {/* 成分股表格 */}
      <div className="bg-white rounded-2xl shadow-sm p-4">
        <Table
          dataSource={stocks}
          columns={columns}
          rowKey="stock_code"
          loading={isFetching}
          size="small"
          pagination={{ current, pageSize, showSizeChanger: true, showTotal: t => `共 ${t} 只` }}
          onChange={(pag, _filters, sorter) => {
            const s = Array.isArray(sorter) ? sorter[0] : sorter
            updateParams({
              page: pag.current > 1 ? pag.current : undefined,
              pageSize: pag.pageSize !== 50 ? pag.pageSize : undefined,
              sortBy: s?.order ? s.field : undefined,
              sortOrder: s?.order || undefined,
            })
          }}
          scroll={{ x: 1200 }}
        />
      </div>

      {/* 队列概况 Modal */}
      <Modal
        title={`${sectorName} - 先锋·中军·后排`}
        open={queueVisible}
        onCancel={() => setQueueVisible(false)}
        footer={null}
        width={600}
      >
        {queueLoading ? (
          <div className="p-8 text-center"><Spin size="large" /><p className="mt-4 text-sm text-gray-500">加载中...</p></div>
        ) : queueData ? (
          <div className="space-y-4">
            <div className="text-xs text-gray-400">数据日期: {queueData.trade_date}</div>
            {[
              { key: 'pioneer', label: '🔥 先锋', desc: '50日涨幅最高的3只', cls: 'text-amber-600', bg: 'bg-amber-50', tc: 'text-amber-800' },
              { key: 'main_force', label: '🎯 中军', desc: '流通市值Top10中50日涨幅最高', cls: 'text-blue-600', bg: 'bg-blue-50', tc: 'text-blue-800' },
              { key: 'followers', label: '📌 后排', desc: '小市值中当天涨幅最高', cls: 'text-gray-600', bg: 'bg-gray-50', tc: 'text-gray-700' },
            ].map(({ key, label, desc, cls, bg, tc }) => (
              <div key={key}>
                <div className="flex items-center space-x-2 mb-2">
                  <span className={`text-sm font-bold ${cls}`}>{label}</span>
                  <span className="text-xs text-gray-400">{desc}</span>
                </div>
                <div className="space-y-1">
                  {(queueData[key] || []).map((s, i) => (
                    <div key={i} className={`px-3 py-2 ${bg} rounded-lg text-sm ${tc}`}>{s}</div>
                  ))}
                  {(!queueData[key] || queueData[key].length === 0) && <div className="text-xs text-gray-400">暂无数据</div>}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="p-8 text-center text-gray-400">暂无该板块数据</div>
        )}
      </Modal>
    </div>
  )
}

export default SectorDetail
