import React from 'react'
import { Card, Button, Typography, Space } from 'antd'

const { Title, Text } = Typography

/**
 * 可复用的实体管理卡片
 * 用于指数/个股/板块的管理界面
 */
export default function EntityCard({
  icon,
  iconBg,
  iconColor,
  title,
  description,
  buttons,
  onManage,
  onCardClick,
}) {
  return (
    <Card
      className="rounded-2xl shadow-sm border-gray-100 cursor-pointer hover:shadow-md transition-shadow"
      onClick={onCardClick}
    >
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center space-x-2">
          <div className={`p-3 rounded-xl`} style={{ backgroundColor: iconBg }}>
            {icon}
          </div>
          <div>
            <Title level={5} className="!mb-0">{title}</Title>
            <Text type="secondary" className="text-xs">{description}</Text>
          </div>
        </div>
        <Button size="small" onClick={(e) => { e.stopPropagation(); onManage() }}>
          管理
        </Button>
      </div>
      <Space direction="vertical" className="w-full">
        {buttons.map((btn, i) => (
          <Button
            key={i}
            block
            icon={btn.icon}
            onClick={(e) => { e.stopPropagation(); btn.onClick() }}
            loading={btn.loading}
            disabled={btn.disabled}
            className={`rounded-lg font-bold ${btn.className || ''}`}
          >
            {btn.label}
          </Button>
        ))}
      </Space>
    </Card>
  )
}