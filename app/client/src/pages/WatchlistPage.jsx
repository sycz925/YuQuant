import React, { useState, useCallback } from 'react'
import { Table, Input, Button, Space, Tag, message, Select } from 'antd'
import { PlusOutlined, AlertOutlined, StarFilled } from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { watchlistApi } from '../api'

function WatchlistPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [addCode, setAddCode] = useState('')
  const [adding, setAdding] = useState(false)

  const keyword = searchParams.get('keyword') || ''
  const rpsRed = searchParams.get('rpsRed') || undefined
  const sortBy = searchParams.get('sortBy') || null
  const sortOrder = searchParams.get('sortOrder') || 'desc'

  const updateParam = useCallback((key, value) => {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      if (value === null || value === undefined || value === '') next.delete(key)
      else next.set(key, value)
      return next
    }, { replace: true })
  }, [setSearchParams])

  const { data = [], isFetching } = useQuery({
    queryKey: ['watchlist', keyword, rpsRed, sortBy, sortOrder],
    queryFn: () => {
      const params = {}
      if (keyword) params.keyword = keyword
      if (rpsRed) params.rps_red = rpsRed
      if (sortBy) { params.sort_by = sortBy; params.sort_order = sortOrder }
      return watchlistApi.getList(params).then(r => r.data || [])
    },
  })

  const handleAdd = async () => {
    const code = addCode.trim()
    if (!code) return
    if (adding) return
    setAdding(true)
    try {
      await watchlistApi.add(code)
      message.success(`已添加 ${code}`)
      setAddCode('')
      queryClient.invalidateQueries({ queryKey: ['watchlist'] })
    } catch (e) {
      message.error(e?.response?.data?.detail || '添加失败')
    } finally {
      setAdding(false)
    }
  }

  const handleDelete = async (code) => {
    try {
      await watchlistApi.remove(code)
      message.success(`已删除 ${code}`)
      queryClient.invalidateQueries({ queryKey: ['watchlist'] })
    } catch (e) {
      message.error(e?.response?.data?.detail || '删除失败')
    }
  }

  const [checking, setChecking] = useState(false)
  const handleCheckAlerts = async () => {
    if (checking) return
    setChecking(true)
    try {
      const res = await watchlistApi.checkAlerts()
      const n = res?.new_alerts || 0
      message.success(n > 0 ? `预警检查完成，新增 ${n} 条预警` : '预警检查完成，无新增预警')
    } catch (e) {
      message.error(e?.response?.data?.detail || '预警检查失败')
    } finally {
      setChecking(false)
    }
  }

  const renderChange = (value) => {
    if (value == null) return '-'
    const color = value >= 0 ? 'text-red-500' : 'text-green-500'
    return <span className={`font-mono ${color}`}>{value >= 0 ? '+' : ''}{value.toFixed(2)}%</span>
  }

  const renderRps = (v) => v != null
    ? <span className={`font-mono ${v >= 90 ? 'text-red-500 font-bold' : v >= 80 ? 'text-orange-500' : v <= 20 ? 'text-green-500' : ''}`}>{v}</span>
    : '-'

  const columns = [
    { title: '代码', dataIndex: 'code', key: 'code', width: 110,
      render: (v) => <span className="font-mono text-gray-500">{v}</span> },
    { title: '名称', dataIndex: 'name', key: 'name', width: 200,
      render: (v, r) => (
        <span className="font-medium text-blue-600 hover:text-blue-800 cursor-pointer"
          onClick={() => navigate(`/search?${r.type === 'etf' ? 'etf' : 'code'}=${r.code}&name=${encodeURIComponent(v)}`)}>
          {v}
        </span>
      ) },
    { title: '最新价', dataIndex: 'close', key: 'close', width: 100, sorter: true,
      render: (v) => v != null ? <span className="font-mono">{v.toFixed(3)}</span> : '-' },
    { title: '日涨幅', dataIndex: 'change_pct', key: 'change_pct', width: 100, sorter: true, render: renderChange },
    { title: '5日涨幅', dataIndex: 'chg_5d', key: 'chg_5d', width: 100, sorter: true, render: renderChange },
    { title: '10日涨幅', dataIndex: 'chg_10d', key: 'chg_10d', width: 100, sorter: true, render: renderChange },
    { title: '20日涨幅', dataIndex: 'chg_20d', key: 'chg_20d', width: 100, sorter: true, render: renderChange },
    { title: '50日涨幅', dataIndex: 'chg_50d', key: 'chg_50d', width: 100, sorter: true, render: renderChange },
    { title: '120日涨幅', dataIndex: 'chg_120d', key: 'chg_120d', width: 100, sorter: true, render: renderChange },
    { title: 'RPS10', dataIndex: 'rps_10', key: 'rps_10', width: 80, sorter: true, render: renderRps },
    { title: 'RPS20', dataIndex: 'rps_20', key: 'rps_20', width: 80, sorter: true, render: renderRps },
    { title: 'RPS50', dataIndex: 'rps_50', key: 'rps_50', width: 80, sorter: true, render: renderRps },
    { title: '操作', key: 'action', width: 80,
      render: (_, r) => (
        <Button size="small" danger type="link" onClick={() => handleDelete(r.code)}>删除</Button>
      ) },
  ]

  const handleTableChange = (pagination, filters, sorter) => {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      if (sorter.field) { next.set('sortBy', sorter.field); next.set('sortOrder', sorter.order === 'ascend' ? 'asc' : 'desc') }
      else { next.delete('sortBy'); next.delete('sortOrder') }
      return next
    }, { replace: true })
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <div className="flex items-center space-x-3">
          <h2 className="text-lg font-bold flex items-center"><StarFilled className="text-yellow-500 mr-1.5" />重点关注</h2>
          <Tag color="blue" className="text-xs">{data.length} 只</Tag>
        </div>
        <Space wrap>
          <Input.Search
            placeholder="输入代码(回车添加)"
            style={{ width: 220 }}
            value={addCode}
            onChange={(e) => setAddCode(e.target.value)}
            onSearch={handleAdd}
            loading={adding}
            enterButton={<PlusOutlined />}
          />
          <Select
            placeholder="RPS红筛选"
            allowClear
            style={{ width: 140 }}
            value={rpsRed}
            onChange={(v) => updateParam('rpsRed', v)}
            options={[
              { value: 'one', label: '一线红' },
              { value: 'two', label: '二线红' },
              { value: 'three', label: '三线红' },
            ]}
          />
          <Button icon={<AlertOutlined />} onClick={() => navigate('/watchlist/alerts')}>预警记录</Button>
          <Button type="primary" icon={<AlertOutlined />} loading={checking} onClick={handleCheckAlerts}>预警检查</Button>
        </Space>
      </div>

      <Table dataSource={data} columns={columns} rowKey="code" loading={isFetching}
        onChange={handleTableChange}
        pagination={{ pageSize: 50, showSizeChanger: true, showTotal: (t) => `共 ${t} 只` }}
        size="small" className="bg-white rounded-lg shadow-sm" />
    </div>
  )
}

export default WatchlistPage
