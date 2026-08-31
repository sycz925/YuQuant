import { useState, useEffect } from 'react'
import { Modal, Table, Checkbox, Spin, Empty } from 'antd'
import dayjs from 'dayjs'
import { restrictedReleaseApi } from '../../api'

const RELEASE_TYPES = [
  '首发原股东限售股份',
  '定向增发机构配售股份',
  '股权激励限售股份',
  '股权分置限售股份',
  '首发机构配售股份',
]

export default function ReleaseDetailModal({ visible, year, month, onClose }) {
  const [loading, setLoading] = useState(false)
  const [stocks, setStocks] = useState([])
  const [selectedTypes, setSelectedTypes] = useState(RELEASE_TYPES)

  const loadData = async () => {
    if (!year || !month) return

    setLoading(true)
    try {
      const data = await restrictedReleaseApi.getDetail(year, month)
      setStocks(data.stocks || [])
    } catch (err) {
      console.error('加载详情失败:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (visible) {
      loadData()
    }
  }, [visible, year, month])

  const filteredStocks = stocks.filter((s) =>
    selectedTypes.includes(s.release_type)
  )

  const columns = [
    { title: '代码', dataIndex: 'stock_code', width: 80 },
    { title: '名称', dataIndex: 'stock_name', width: 100 },
    {
      title: '现价',
      dataIndex: 'close_price',
      width: 80,
      render: (v) => (v ? `¥${v.toFixed(2)}` : '---'),
    },
    {
      title: '解禁成本',
      dataIndex: 'close_price',
      width: 80,
      render: (v) => (v ? `¥${v.toFixed(2)}` : '---'),
    },
    {
      title: '解禁比例',
      dataIndex: 'float_ratio',
      width: 90,
      render: (v) => (v ? `${(v * 100).toFixed(2)}%` : '---'),
    },
    {
      title: '解禁股数(万)',
      dataIndex: 'release_shares',
      width: 110,
      render: (v) => (v ? v.toFixed(2) : '---'),
    },
    {
      title: '解禁金额(亿)',
      dataIndex: 'release_market_value',
      width: 110,
      render: (v) => (v ? v.toFixed(2) : '---'),
    },
    { title: '解禁类型', dataIndex: 'release_type', width: 150 },
    {
      title: '解禁日期',
      dataIndex: 'release_date',
      width: 100,
    },
  ]

  return (
    <Modal
      title={`${year}年${month}月 限售股解禁详情`}
      open={visible}
      onCancel={onClose}
      footer={null}
      width={1000}
      styles={{ body: { maxHeight: '60vh', overflowY: 'auto' } }}
    >
      <div className="mb-4 p-3 bg-gray-50 rounded">
        <span className="mr-4 font-medium">解禁类型筛选：</span>
        <Checkbox.Group
          options={RELEASE_TYPES}
          value={selectedTypes}
          onChange={setSelectedTypes}
        />
      </div>

      <Spin spinning={loading}>
        {filteredStocks.length > 0 ? (
          <Table
            dataSource={filteredStocks}
            columns={columns}
            rowKey={(r) => `${r.stock_code}-${r.release_date}-${r.release_type}`}
            size="small"
            pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 条` }}
            scroll={{ x: 900 }}
          />
        ) : (
          <Empty description="暂无数据" />
        )}
      </Spin>
    </Modal>
  )
}
