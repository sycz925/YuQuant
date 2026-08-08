import React, { useState, useEffect, useCallback } from 'react'
import { Table, DatePicker, Space, Tag, message, Card, Button } from 'antd'
import { AlertOutlined, ArrowLeftOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { watchlistApi } from '../api'

const { RangePicker } = DatePicker

function WatchlistAlertPage() {
  const navigate = useNavigate()
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [dateRange, setDateRange] = useState([null, null])

  const fetchData = useCallback(async (p = 1) => {
    setLoading(true)
    try {
      const params = { page: p, page_size: 50 }
      if (dateRange[0]) params.start_date = dateRange[0].format('YYYYMMDD')
      if (dateRange[1]) params.end_date = dateRange[1].format('YYYYMMDD')
      const res = await watchlistApi.getAlerts(params)
      setData(res.items || [])
      setTotal(res.total || 0)
    } catch (e) {
      message.error('获取预警记录失败')
    } finally {
      setLoading(false)
    }
  }, [dateRange])

  useEffect(() => { fetchData(page) }, [fetchData, page])

  const onDateChange = useCallback((dates) => {
    setDateRange(dates || [null, null])
    setPage(1)
  }, [])

  const columns = [
    {
      title: '代码',
      dataIndex: 'code',
      key: 'code',
      width: 100,
      render: (v) => <span className="font-mono text-gray-500">{v}</span>
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 200,
      render: (v, record) => {
        const isEtf = record.type === 'etf' || record.code.startsWith('5')
        return (
          <span
            className="font-medium text-blue-600 hover:text-blue-800 cursor-pointer"
            onClick={() => navigate(`/search?${isEtf ? 'etf' : 'code'}=${record.code}&name=${encodeURIComponent(v)}`)}
          >
            {v}
          </span>
        )
      }
    },
    {
      title: '日期',
      dataIndex: 'trade_date',
      key: 'trade_date',
      width: 110,
      render: (v) => <span className="font-mono">{v}</span>
    },
    {
      title: '收盘价',
      dataIndex: 'close',
      key: 'close',
      width: 110,
      render: (v) => <span className="font-mono">{v?.toFixed(3)}</span>
    },
    {
      title: '当日涨幅',
      dataIndex: 'chg_pct',
      key: 'chg_pct',
      width: 100,
      render: (v) => {
        if (v == null) return '-'
        const color = v >= 0 ? 'text-red-500' : 'text-green-500'
        return <span className={`font-mono ${color}`}>{v >= 0 ? '+' : ''}{v.toFixed(2)}%</span>
      }
    },
    {
      title: '原因',
      dataIndex: 'reason',
      key: 'reason',
      render: (v) => (
        <Tag color={v.includes('跌破') ? 'red' : 'blue'} className="text-xs whitespace-normal break-all">
          <AlertOutlined className="mr-1" />{v}
        </Tag>
      )
    },
    {
      title: '触发时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (v) => {
        if (!v) return '-'
        const d = new Date(v + 'Z')
        return <span className="font-mono text-xs">{d.toLocaleString('zh-CN')}</span>
      }
    },
  ]

  return (
    <div>
      <Card title={<span><AlertOutlined className="mr-2 text-red-500" />关注列表均线预警</span>}
        extra={<Space><Button size="small" icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)}>返回</Button><Tag color="blue">共 {total} 条</Tag></Space>}
        className="bg-white rounded-lg shadow-sm">
        <div className="mb-4">
          <Space>
            <RangePicker
              onChange={onDateChange}
              allowClear
              placeholder={['开始日期', '结束日期']}
            />
          </Space>
        </div>
        <Table
          dataSource={data}
          columns={columns}
          rowKey={(r) => `${r.code}_${r.trade_date}_${r.reason}`}
          loading={loading}
          pagination={{
            current: page,
            pageSize: 50,
            total,
            onChange: setPage,
            showTotal: (t) => `共 ${t} 条`,
          }}
          size="small"
        />
      </Card>
    </div>
  )
}

export default WatchlistAlertPage
