import React from 'react'
import { Card, Typography } from 'antd'
import { SettingOutlined } from '@ant-design/icons'

const { Title, Text } = Typography

/**
 * DeepSeek API 时间窗口配置卡片
 */
export default function DeepSeekConfigCard({ enabled, onToggle }) {
  return (
    <Card className="rounded-2xl shadow-sm border-gray-100">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <div className="p-3 bg-purple-100 rounded-xl">
            <SettingOutlined className="text-purple-600 text-xl" />
          </div>
          <div>
            <Title level={5} className="!mb-0">DeepSeek API 时间窗口</Title>
            <Text type="secondary" className="text-xs">可用时间：12:00-13:00 或 18:00-23:59</Text>
          </div>
        </div>
        <div className="flex items-center space-x-2">
          <Text className="text-sm" type={enabled ? 'secondary' : 'success'}>
            {enabled ? '已启用' : '已禁用'}
          </Text>
          <button
            onClick={onToggle}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
              enabled ? 'bg-blue-600' : 'bg-gray-300'
            }`}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                enabled ? 'translate-x-6' : 'translate-x-1'
              }`}
            />
          </button>
        </div>
      </div>
      <Text type="secondary" className="text-xs mt-2 block">
        关闭后可在任何时间调用 DeepSeek API 生成分析，不受时间窗口限制
      </Text>
    </Card>
  )
}