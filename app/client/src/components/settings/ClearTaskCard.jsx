import React from 'react'
import { Card, Button, Typography, Modal, message } from 'antd'
import { DeleteOutlined } from '@ant-design/icons'

const { Title, Text } = Typography

/**
 * 清除任务记录卡片
 */
export default function ClearTaskCard({ onClear }) {
  const handleClear = () => {
    Modal.confirm({
      title: '确认清除',
      content: '确定要清除所有任务记录吗？此操作不可恢复。',
      okText: '确定清除',
      cancelText: '取消',
      onOk: async () => {
        try {
          await onClear()
        } catch (e) {
          message.error('清除失败: ' + (e.response?.data?.detail || e.message))
        }
      }
    })
  }

  return (
    <Card className="rounded-2xl shadow-sm border-gray-100">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <div className="p-3 bg-red-100 rounded-xl">
            <DeleteOutlined className="text-red-600 text-xl" />
          </div>
          <div>
            <Title level={5} className="!mb-0">清除任务记录</Title>
            <Text type="secondary" className="text-xs">删除 sync_tasks 表中的所有历史任务记录</Text>
          </div>
        </div>
        <Button
          type="primary"
          danger
          icon={<DeleteOutlined />}
          onClick={handleClear}
          className="rounded-lg"
        >
          清除记录
        </Button>
      </div>
    </Card>
  )
}