import React, { useState, useRef, useEffect, useCallback } from 'react'
import { Table, Input, Button, Space, Tag, message, notification, Select } from 'antd'
import { SearchOutlined, ReloadOutlined, SyncOutlined, AlertOutlined } from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { etfApi, taskApi } from '../api'

function ETFPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const pollingRef = useRef(null)
  const [searchParams, setSearchParams] = useSearchParams()

  // 从 URL 参数读取筛选状态（返回时自动恢复）
  const keyword = searchParams.get('keyword') || ''
  const rpsRed = searchParams.get('rpsRed') || undefined
  const sortBy = searchParams.get('sortBy') || null
  const sortOrder = searchParams.get('sortOrder') || 'desc'

  // 更新 URL 参数（保留现有参数，只更新指定 key）
  const updateParam = useCallback((key, value) => {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      if (value === null || value === undefined || value === '') {
        next.delete(key)
      } else {
        next.set(key, value)
      }
      return next
    }, { replace: true })
  }, [setSearchParams])

  const [syncing, setSyncing] = useState(false)

  const { data = [], isFetching } = useQuery({
    queryKey: ['etf_list', keyword, rpsRed, sortBy, sortOrder],
    queryFn: () => {
      const params = {}
      if (keyword) params.keyword = keyword
      if (rpsRed) params.rps_red = rpsRed
      if (sortBy) {
        params.sort_by = sortBy
        params.sort_order = sortOrder
      }
      return etfApi.getList(params).then(r => r.data || [])
    },
  })

  useEffect(() => {
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current)
    }
  }, [])

  const handleSync = async () => {
    if (syncing) return
    setSyncing(true)
    try {
      const res = await etfApi.sync()
      if (!res?.success) {
        message.warning(res?.message || '无法启动同步')
        setSyncing(false)
        return
      }
      notification.info({
        message: 'ETF同步(0/3)',
        description: '正在准备...',
        duration: 0,
        key: 'etf-sync',
        closable: false,
      })
      startPolling(res.task_id)
    } catch (e) {
      message.error('启动同步失败')
      setSyncing(false)
    }
  }

  const startPolling = (taskId) => {
    const key = 'etf-sync'
    pollingRef.current = setInterval(async () => {
      try {
        const status = await taskApi.getTaskStatus(taskId)
        if (status.status === 'failed') {
          notification.error({
            message: 'ETF同步失败',
            description: status.message || status.error || '未知错误',
            duration: 0, key, closable: true,
          })
          clearInterval(pollingRef.current)
          pollingRef.current = null
          setSyncing(false)
          return
        }
        if (status.status === 'completed') {
          notification.success({
            message: 'ETF同步完成',
            description: '基础信息 | 日线 | RPS | ENE预警 全部完成',
            duration: 0, key, closable: true,
          })
          clearInterval(pollingRef.current)
          pollingRef.current = null
          setSyncing(false)
          queryClient.invalidateQueries({ queryKey: ['etf_list'] })
          return
        }
        if (status.status === 'running') {
          const steps = status.steps || []
          const totalSteps = steps.length
          const currentStep = steps[status.current_step]
          const stepDesc = currentStep
            ? `${currentStep.name}(${currentStep.completed_count || 0}/${currentStep.total_count || 1})`
            : '处理中...'
          notification.info({
            message: `ETF同步(${(status.current_step || 0) + 1}/${totalSteps})`,
            description: stepDesc,
            duration: 0, key, closable: false,
          })
        }
      } catch (e) {
        console.error('[ETF Polling]', e)
      }
    }, 3000)
  }

  const handleTableChange = (pagination, filters, sorter) => {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      if (sorter.field) {
        next.set('sortBy', sorter.field)
        next.set('sortOrder', sorter.order === 'ascend' ? 'asc' : 'desc')
      } else {
        next.delete('sortBy')
        next.delete('sortOrder')
      }
      return next
    }, { replace: true })
  }

  const renderChange = (value) => {
    if (value == null) return '-'
    const color = value >= 0 ? 'text-red-500' : 'text-green-500'
    return <span className={`font-mono ${color}`}>{value >= 0 ? '+' : ''}{value.toFixed(2)}%</span>
  }

  const columns = [
    {
      title: '代码',
      dataIndex: 'code',
      key: 'code',
      width: 110,
      render: (v) => <span className="font-mono text-gray-500">{v}</span>
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 200,
      render: (v, record) => (
        <span
          className="font-medium text-blue-600 hover:text-blue-800 cursor-pointer"
          onClick={() => navigate(`/search?etf=${record.code}&name=${encodeURIComponent(v)}`)}
        >
          {v}
        </span>
      )
    },
    {
      title: '最新价',
      dataIndex: 'close',
      key: 'close',
      width: 100,
      sorter: true,
      render: (v) => v != null ? <span className="font-mono">{v.toFixed(3)}</span> : '-'
    },
    {
      title: '日涨幅',
      dataIndex: 'change_pct',
      key: 'change_pct',
      width: 100,
      sorter: true,
      render: renderChange
    },
    {
      title: '5日涨幅',
      dataIndex: 'chg_5d',
      key: 'chg_5d',
      width: 100,
      sorter: true,
      render: renderChange
    },
    {
      title: '10日涨幅',
      dataIndex: 'chg_10d',
      key: 'chg_10d',
      width: 100,
      sorter: true,
      render: renderChange
    },
    {
      title: '20日涨幅',
      dataIndex: 'chg_20d',
      key: 'chg_20d',
      width: 100,
      sorter: true,
      render: renderChange
    },
    {
      title: '50日涨幅',
      dataIndex: 'chg_50d',
      key: 'chg_50d',
      width: 100,
      sorter: true,
      render: renderChange
    },
    {
      title: '120日涨幅',
      dataIndex: 'chg_120d',
      key: 'chg_120d',
      width: 100,
      sorter: true,
      render: renderChange
    },
    {
      title: 'RPS10',
      dataIndex: 'rps_10',
      key: 'rps_10',
      width: 80,
      sorter: true,
      render: (v) => v != null
        ? <span className={`font-mono ${v >= 90 ? 'text-red-500 font-bold' : v >= 80 ? 'text-orange-500' : v <= 20 ? 'text-green-500' : ''}`}>{v}</span>
        : '-'
    },
    {
      title: 'RPS20',
      dataIndex: 'rps_20',
      key: 'rps_20',
      width: 80,
      sorter: true,
      render: (v) => v != null
        ? <span className={`font-mono ${v >= 90 ? 'text-red-500 font-bold' : v >= 80 ? 'text-orange-500' : v <= 20 ? 'text-green-500' : ''}`}>{v}</span>
        : '-'
    },
    {
      title: 'RPS50',
      dataIndex: 'rps_50',
      key: 'rps_50',
      width: 80,
      sorter: true,
      render: (v) => v != null
        ? <span className={`font-mono ${v >= 90 ? 'text-red-500 font-bold' : v >= 80 ? 'text-orange-500' : v <= 20 ? 'text-green-500' : ''}`}>{v}</span>
        : '-'
    },
  ]

  return (
    <div>
      {/* 操作栏 */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center space-x-3">
          <h2 className="text-lg font-bold">ETF列表</h2>
          <Tag color="blue" className="text-xs">{data.length} 只</Tag>
        </div>
        <Space>
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
          <Button icon={<AlertOutlined />} onClick={() => navigate('/etf/alerts')}>
            预警记录
          </Button>
          <Button type="primary" icon={<SyncOutlined />} onClick={handleSync} loading={syncing}>
            {syncing ? '同步中...' : '同步数据'}
          </Button>
        </Space>
      </div>

      {/* ETF表格 */}
      <Table
        dataSource={data}
        columns={columns}
        rowKey="code"
        loading={isFetching}
        onChange={handleTableChange}
        pagination={{ pageSize: 50, showSizeChanger: true, showTotal: (t) => `共 ${t} 只` }}
        size="small"
        className="bg-white rounded-lg shadow-sm"
      />
    </div>
  )
}

export default ETFPage
