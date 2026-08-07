import React, { useRef } from 'react'
import { Modal, Button, Typography, Tag, List, message } from 'antd'
import { SyncOutlined, CheckCircleOutlined } from '@ant-design/icons'
import { factorApi } from '../../api'

const { Text } = Typography

/**
 * 数据对比弹窗
 * 对比本地数据与 pytdx 远程数据，展示差异并支持导入
 */
export default function CompareDataModal({ compareModal, onClose, onImportSuccess }) {
  const comparePollRef = useRef(null)

  const handleImport = async () => {
    if (!compareModal.data) return

    const items = compareModal.type === 'stock'
      ? compareModal.data.new_stocks
      : compareModal.data.new_sectors

    if (!items || items.length === 0) {
      message.warning('没有可导入的数据')
      return
    }

    try {
      const res = compareModal.type === 'stock'
        ? await factorApi.importStocks(items)
        : await factorApi.importSectors(items)

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

  const handleImportOne = async (item) => {
    try {
      const res = await factorApi.importSectors([item])
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

  const handleClose = () => {
    if (comparePollRef.current) {
      clearInterval(comparePollRef.current)
    }
    onClose()
  }

  return (
    <Modal
      title={compareModal.type === 'stock' ? '个股对比' : '板块对比'}
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
      ) : compareModal.data ? (
        <div>
          <div className="mb-4 p-4 bg-gray-50 rounded-lg">
            <div className="flex justify-between text-sm">
              <span>本地数据: <strong>{compareModal.data.local_count}</strong></span>
              <span>远程数据: <strong>{compareModal.data.remote_count}</strong></span>
              <span className="text-orange-600">新增: <strong>{compareModal.data.new_count}</strong></span>
            </div>
          </div>
          {compareModal.data.new_count > 0 ? (
            <div>
              <Text type="secondary" className="text-xs mb-2 block">
                以下是 {compareModal.type === 'stock' ? 'pytdx 中存在但本地没有的个股' : 'pytdx 中存在但本地没有的板块'}：
              </Text>
              <List
                size="small"
                bordered
                dataSource={compareModal.data.new_count > 0
                  ? (compareModal.type === 'stock' ? compareModal.data.new_stocks : compareModal.data.new_sectors)
                  : []
                }
                renderItem={(item) => (
                  <List.Item>
                    {compareModal.type === 'stock' ? (
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
                    {compareModal.type === 'sector' && item.code && (
                      <Button
                        size="small"
                        type="primary"
                        className="bg-blue-500 hover:bg-blue-600"
                        onClick={() => handleImportOne(item)}
                      >
                        加入
                      </Button>
                    )}
                  </List.Item>
                )}
                style={{ maxHeight: '400px', overflowY: 'auto' }}
              />
              {compareModal.data.new_count > 0 && (
                <div className="mt-4 flex justify-end gap-2">
                  <Button
                    type="primary"
                    onClick={handleImport}
                    className="bg-blue-500 hover:bg-blue-600"
                  >
                    全部导入 ({compareModal.data.new_count})
                  </Button>
                </div>
              )}
            </div>
          ) : (
            <div className="text-center py-8 text-gray-500">
              <CheckCircleOutlined className="text-4xl text-green-500 mb-2" />
              <p>本地数据已是最新的，没有发现新增的{compareModal.type === 'stock' ? '个股' : '板块'}</p>
            </div>
          )}
        </div>
      ) : null}
    </Modal>
  )
}