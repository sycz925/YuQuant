import React, { useState } from 'react'
import { Card, Form, InputNumber, DatePicker, Button, Typography, Table, Tag, Spin, Input } from 'antd'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import { RocketOutlined } from '@ant-design/icons'
import { backtestApi } from '../api'
import dayjs from 'dayjs'

const { Title, Text } = Typography
const { RangePicker } = DatePicker

function Backtest() {
  const [form] = Form.useForm()
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)

  const initialValues = {
    initialCapital: 100000,
    dateRange: [dayjs('2024-01-01'), dayjs('2024-12-31')],
    stockCodes: '600000, 000001, 688279'
  }

  const handleSubmit = async (values) => {
    setLoading(true)
    try {
      const stockCodes = values.stockCodes
        .split(/[,，\s]+/)
        .map(s => s.trim())
        .filter(s => s)

      const params = {
        initialCapital: values.initialCapital,
        startDate: values.dateRange[0].format('YYYYMMDD'),
        endDate: values.dateRange[1].format('YYYYMMDD'),
        stockCodes
      }

      const res = await backtestApi.runBacktest(params)
      setResult(res.data)
    } catch (e) {
      console.error('回测失败:', e)
    } finally {
      setLoading(false)
    }
  }

  const columns = [
    {
      title: '日期',
      dataIndex: 'trade_date',
      key: 'trade_date',
      width: 120
    },
    {
      title: '股票',
      dataIndex: 'stock_code',
      key: 'stock_code',
      width: 100
    },
    {
      title: '方向',
      dataIndex: 'action',
      key: 'action',
      width: 80,
      render: (action) => (
        <Tag color={action === 'BUY' ? 'red' : 'green'}>
          {action === 'BUY' ? '买入' : '卖出'}
        </Tag>
      )
    },
    {
      title: '数量',
      dataIndex: 'quantity',
      key: 'quantity',
      width: 100,
      render: (val) => val.toLocaleString()
    },
    {
      title: '价格',
      dataIndex: 'price',
      key: 'price',
      width: 100,
      render: (val) => val.toFixed(2)
    }
  ]

  return (
    <div className="space-y-6">
      {/* 标题 */}
      <Card className="rounded-2xl shadow-sm border-gray-100">
        <div className="flex items-center space-x-4">
          <div className="p-3 bg-gradient-to-br from-green-500 to-emerald-600 rounded-2xl text-white">
            <RocketOutlined style={{ fontSize: '24px' }} />
          </div>
          <div>
            <Title level={4} style={{ margin: 0 }}>策略回测</Title>
            <Text type="secondary" className="text-xs">配置参数并运行回测模拟</Text>
          </div>
        </div>
      </Card>

      {/* 回测配置 */}
      <Card className="rounded-2xl shadow-sm border-gray-100">
        <Title level={5} className="mb-4">回测参数配置</Title>
        <Form
          form={form}
          initialValues={initialValues}
          onFinish={handleSubmit}
          layout="vertical"
        >
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Form.Item
              label="初始资金"
              name="initialCapital"
              rules={[{ required: true, message: '请输入初始资金' }]}
            >
              <InputNumber
                min={10000}
                step={10000}
                style={{ width: '100%' }}
                formatter={value => `${value}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
                parser={value => value.replace(/,/g, '')}
              />
            </Form.Item>

            <Form.Item
              label="回测周期"
              name="dateRange"
              rules={[{ required: true, message: '请选择回测周期' }]}
            >
              <RangePicker style={{ width: '100%' }} />
            </Form.Item>

            <Form.Item className="flex items-end">
              <Button
                type="primary"
                htmlType="submit"
                icon={<RocketOutlined />}
                loading={loading}
                block
                size="large"
              >
                运行回测
              </Button>
            </Form.Item>
          </div>

          <Form.Item
            label="股票代码（逗号分隔）"
            name="stockCodes"
            rules={[{ required: true, message: '请输入股票代码' }]}
          >
            <Input placeholder="例如：600000, 000001, 688279" />
          </Form.Item>
        </Form>
      </Card>

      {/* 回测结果 */}
      {loading && (
        <Card className="rounded-2xl shadow-sm border-gray-100">
          <div className="flex flex-col items-center justify-center py-12">
            <Spin size="large" />
            <Text type="secondary" className="mt-4">回测计算中，请稍候...</Text>
          </div>
        </Card>
      )}

      {result && !loading && (
        <>
          {/* 指标卡 */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <Card className="rounded-2xl shadow-sm border-t-4 border-t-green-500">
              <Text type="secondary" className="text-sm">总收益率</Text>
              <div className={`text-3xl font-bold mt-1 ${result.totalReturn >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                {(result.totalReturn * 100).toFixed(2)}%
              </div>
            </Card>
            <Card className="rounded-2xl shadow-sm border-t-4 border-t-blue-500">
              <Text type="secondary" className="text-sm">年化收益率</Text>
              <div className={`text-3xl font-bold mt-1 ${result.annualReturn >= 0 ? 'text-blue-600' : 'text-red-600'}`}>
                {(result.annualReturn * 100).toFixed(2)}%
              </div>
            </Card>
            <Card className="rounded-2xl shadow-sm border-t-4 border-t-red-500">
              <Text type="secondary" className="text-sm">最大回撤</Text>
              <div className="text-3xl font-bold mt-1 text-red-600">
                {(result.maxDrawdown * 100).toFixed(2)}%
              </div>
            </Card>
            <Card className="rounded-2xl shadow-sm border-t-4 border-t-purple-500">
              <Text type="secondary" className="text-sm">夏普比率</Text>
              <div className="text-3xl font-bold mt-1 text-purple-600">
                {result.sharpeRatio.toFixed(2)}
              </div>
            </Card>
          </div>

          {/* 资金曲线图 */}
          <Card className="rounded-2xl shadow-sm border-gray-100">
            <Title level={5} className="mb-4">资金曲线</Title>
            <ResponsiveContainer width="100%" height={350}>
              <LineChart data={result.equity_curve.map(e => ({ date: e.trade_date, equity: e.equity }))}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} interval={Math.floor(result.equity_curve.length / 10)} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip
                  formatter={(value) => [value.toLocaleString(), '资金']}
                  contentStyle={{ borderRadius: '8px' }}
                />
                <Legend />
                <Line type="monotone" dataKey="equity" stroke="#22c55e" strokeWidth={2} dot={false} name="资金" />
              </LineChart>
            </ResponsiveContainer>
          </Card>

          {/* 交易记录 */}
          <Card className="rounded-2xl shadow-sm border-gray-100">
            <Title level={5} className="mb-4">交易记录</Title>
            <Table
              columns={columns}
              dataSource={result.trades}
              rowKey={(record, index) => index}
              pagination={{ pageSize: 10 }}
              size="small"
            />
          </Card>
        </>
      )}
    </div>
  )
}

export default Backtest
