import React from 'react'
import { Modal, Button, Typography, Tag, List, message, Alert } from 'antd'
import { SyncOutlined, CheckCircleOutlined } from '@ant-design/icons'
import { factorApi } from '../../api'

const { Text } = Typography

/**
 * 数据对比弹窗
 * - 次新股对比：本地 vs pytdx 次新股板块，展示本地缺失的次新股并支持导入
 * - 板块对比：本地 vs pytdx 概念板块，区分「新增板块」（缺代码，需 Excel 导入）与「待更新板块」（成分股变化，可导入）
 * 注：任务轮询由父组件 Settings.jsx 统一管理（comparePollRef）
 */
export default function CompareDataModal({ compareModal, onClose, onImportSuccess }) {
  const data = compareModal.data
  const isStock = compareModal.type === 'stock'

  // 个股：new_stocks；板块：新增 + 待更新合并展示
  const listItems = isStock
    ? (data?.new_stocks || [])
    : [...(data?.new_sectors || []), ...(data?.update_sectors || [])]

  // 可导入数量：个股=新增数；板块=待更新数（新增板块缺代码不能导入）
  const importableCount = isStock ? (data?.new_count || 0) : (data?.update_count || 0)

  const handleImport = async () => {
    if (!data) return

    let items
    let apiCall
    if (isStock) {
      items = data.new_stocks
      apiCall = () => factorApi.importStocks(items)
    } else {
      items = data.update_sectors // 只导入有 code 的待更新板块
      apiCall = () => factorApi.importSectors(items)
    }

    if (!items || items.length === 0) {
      message.warning('没有可导入的数据')
      return
    }

    try {
      const res = await apiCall()
      if (res?.success) {
        message.success(res.message)
        if (onImportSuccess) onImportSuccess()
      } else {
        message.error(res?.message || '导入失败')
      }
    } catch (e) {
      console.error('导入失败:', e)
      message.error('导入失败')
    }
  }

  const handleClose = () => onClose()

  return (
    <Modal
      title={isStock ? '次新股对比' : '板块对比'}
      open={compareModal.open}
      onCancel={handleClose}
      footer={null}
      width={600}
    >
      {compareModal.loading ? (
        <div className="text-center py-8">
          <SyncOutlined spin className="text-2xl text-blue-500" />
          <p className="mt-2 text-gray-500">{compareModal.taskStep || '正在连接 pytdx 获取数据...'}</p>
        </div>
      ) : data ? (
        <div>
          <div className="mb-4 p-4 bg-gray-50 rounded-lg">
            <div className="flex justify-between text-sm">
              <span>本地数据: <strong>{data.local_count}</strong></span>
              <span>远程数据: <strong>{data.remote_count}</strong></span>
              {isStock ? (
                <span className="text-orange-600">缺失: <strong>{data.new_count}</strong></span>
              ) : (
                <>
                  <span className="text-green-600">新增: <strong>{data.new_count}</strong></span>
                  <span className="text-orange-600">待更新: <strong>{data.update_count}</strong></span>
                </>
              )}
            </div>
          </div>

          {listItems.length > 0 ? (
            <div>
              <Text type="secondary" className="text-xs mb-2 block">
                {isStock ? '以下是次新股板块中本地缺失的个股：' : '以下是 pytdx 与本地有差异的板块：'}
              </Text>
              <List
                size="small"
                bordered
                dataSource={listItems}
                renderItem={(item) => (
                  <List.Item>
                    {isStock ? (
                      <div>
                        <span className="font-mono font-bold">{item.stock_code}</span>
                        <span className="ml-2">{item.stock_name}</span>
                        <Tag color={item.market === 1 ? 'blue' : 'green'} className="ml-2">
                          {item.market === 1 ? '沪' : '深'}
                        </Tag>
                      </div>
                    ) : (
                      <div>
                        {item.code && <span className="font-mono text-xs text-gray-400 mr-2">{item.code}</span>}
                        <span className="font-bold">{item.name}</span>
                        <span className="ml-2 text-gray-500">({item.stock_count}只成分股)</span>
                      </div>
                    )}
                    {!isStock && (
                      <Tag color={item.status === '新增' ? 'green' : 'orange'}>{item.status}</Tag>
                    )}
                  </List.Item>
                )}
                style={{ maxHeight: '400px', overflowY: 'auto' }}
              />

              {!isStock && (data.new_count > 0) && importableCount === 0 && (
                <Alert
                  className="mt-4"
                  type="info"
                  showIcon
                  message="新增板块缺少通达信代码（885xxx），无法直接导入"
                  description="请使用「管理板块 → 导入板块代码」通过 Excel 提供代码后导入。"
                />
              )}

              {importableCount > 0 && (
                <div className="mt-4 flex justify-end gap-2">
                  <Button
                    type="primary"
                    onClick={handleImport}
                    className="bg-blue-500 hover:bg-blue-600"
                  >
                    {isStock ? `全部导入 (${importableCount})` : `导入更新 (${importableCount})`}
                  </Button>
                </div>
              )}
            </div>
          ) : (
            <div className="text-center py-8 text-gray-500">
              <CheckCircleOutlined className="text-4xl text-green-500 mb-2" />
              <p>本地数据已是最新的，没有发现差异</p>
            </div>
          )}
        </div>
      ) : null}
    </Modal>
  )
}
