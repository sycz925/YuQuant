import React from 'react'
import { Card, Typography } from 'antd'
import { RightOutlined } from '@ant-design/icons'

const { Title, Text } = Typography

/**
 * 实体管理入口卡
 * 点击整卡打开对应的实体管理对话框（指数/个股/板块）
 */
export default function EntityCard({ icon, iconBg, title, description, onManage }) {
  return (
    <Card hoverable className="rounded-2xl shadow-sm border-gray-100" onClick={onManage}>
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <div className="p-3 rounded-xl" style={{ backgroundColor: iconBg }}>
            {icon}
          </div>
          <div>
            <Title level={5} className="!mb-0">{title}</Title>
            <Text type="secondary" className="text-xs">{description}</Text>
          </div>
        </div>
        <RightOutlined className="text-gray-300" />
      </div>
    </Card>
  )
}
