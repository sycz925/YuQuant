import React, { useState, useRef } from 'react'
import { Modal, Button, Typography, List, Tag, message } from 'antd'
import { UploadOutlined, FileExcelOutlined, FileTextOutlined, CheckCircleOutlined } from '@ant-design/icons'
import { factorApi } from '../../api'

const { Text } = Typography

const MODE_CONFIG = {
  sector: {
    title: '导入板块',
    accept: '.xlsx,.xls,.csv',
    icon: <FileExcelOutlined className="text-5xl text-green-600 mb-4" />,
    desc: '导入板块代码（Excel/CSV），成分股从 pytdx 自动匹配',
    example: '代码,名称\n880515,海峡西岸\n880513,海峡西岸',
  },
  sector_with_stocks: {
    title: '导入板块带成分股',
    accept: '.txt',
    icon: <FileTextOutlined className="text-5xl text-blue-600 mb-4" />,
    desc: '导入板块及成分股（txt），成分股来自文件',
    example: '板块代码;板块名称;成分股代码;成分股名称\n880515;海峡西岸;000408;藏格矿业\n880515;海峡西岸;000538;云南白药',
  },
}

/**
 * 导入板块弹窗：选文件 → 按 code 对比本地 → 预览（新增/重复跳过/无成分股/无效代码）→ 确认导入
 * mode: 'sector' 仅板块代码（Excel）| 'sector_with_stocks' 板块带成分股（txt）
 */
export default function ImportSectorModal({ open, mode = 'sector', onClose, onImported }) {
  const cfg = MODE_CONFIG[mode] || MODE_CONFIG.sector
  const fileInputRef = useRef(null)
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [importing, setImporting] = useState(false)

  const newCount = preview?.new_count || 0

  const handleSelectFile = () => fileInputRef.current?.click()

  const handleFileChange = async (e) => {
    const f = e.target.files[0]
    if (!f) return
    setFile(f)
    setPreview(null)
    setPreviewLoading(true)
    try {
      const formData = new FormData()
      formData.append('file', f)
      const res = await factorApi.importSectorCodes(formData, true) // 预览
      if (res?.success) {
        setPreview(res)
      } else {
        message.error(res?.message || '预览失败')
      }
    } catch (err) {
      message.error(err.response?.data?.detail || '预览失败')
    } finally {
      setPreviewLoading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleImport = async () => {
    if (!file || !preview || newCount === 0) return
    setImporting(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const res = await factorApi.importSectorCodes(formData, false) // 真正导入
      if (res?.success) {
        message.success(res.message)
        if (onImported) onImported()
        setFile(null)
        setPreview(null)
        onClose()
      } else {
        message.error(res?.message || '导入失败')
      }
    } catch (err) {
      message.error(err.response?.data?.detail || '导入失败')
    } finally {
      setImporting(false)
    }
  }

  const handleClose = () => {
    if (importing) return
    setFile(null)
    setPreview(null)
    onClose()
  }

  return (
    <Modal
      title={cfg.title}
      open={open}
      onCancel={handleClose}
      footer={null}
      width={640}
      destroyOnClose
    >
      <input
        type="file"
        ref={fileInputRef}
        accept={cfg.accept}
        onChange={handleFileChange}
        style={{ display: 'none' }}
      />

      {!preview ? (
        <div className="py-6">
          <div className="text-center">
            {cfg.icon}
            <p className="text-gray-500 mb-2">{cfg.desc}</p>
          </div>

          <div className="mb-4 p-3 bg-gray-50 rounded-lg">
            <Text type="secondary" className="text-xs font-medium">文件格式说明</Text>
            <pre className="text-xs text-gray-600 mt-1 mb-0 whitespace-pre-wrap font-mono bg-white p-2 rounded border border-gray-100">{cfg.example}</pre>
          </div>

          <div className="text-center">
            <Button
              type="primary"
              icon={<UploadOutlined />}
              loading={previewLoading}
              onClick={handleSelectFile}
            >
              选择文件
            </Button>
          </div>
        </div>
      ) : (
        <div>
          <div className="mb-4 p-4 bg-gray-50 rounded-lg">
            <div className="flex items-center justify-between text-sm mb-2">
              <Text className="font-medium">解析完成，与本地板块对比结果</Text>
              <Text type="secondary">{file?.name}</Text>
            </div>
            <div className="flex justify-between text-sm flex-wrap gap-1">
              <span className="text-green-600">新增: <strong>{preview.new_count}</strong></span>
              <span className="text-gray-500">重复跳过: <strong>{preview.skipped_count}</strong></span>
              <span className="text-orange-600">无成分股: <strong>{preview.no_data_count}</strong></span>
              {preview.invalid_count > 0 && (
                <span className="text-red-600">无效代码: <strong>{preview.invalid_count}</strong></span>
              )}
            </div>
            {preview.invalid_count > 0 && (
              <div className="mt-2 text-xs text-red-500">
                {preview.invalid_count} 个代码格式无效（非 6 位数字），无法通过 pytdx 拉取日线，已排除
              </div>
            )}
          </div>

          {newCount > 0 ? (
            <>
              <Text type="secondary" className="text-xs mb-2 block">
                以下板块本地不存在，将新增：
              </Text>
              <List
                size="small"
                bordered
                dataSource={preview.new_sectors}
                style={{ maxHeight: '360px', overflowY: 'auto' }}
                renderItem={(item) => (
                  <List.Item>
                    <span className="font-mono font-bold">{item.code}</span>
                    <span className="ml-2">{item.name}</span>
                    <span className="ml-2 text-gray-500">({item.stock_count}只成分股)</span>
                    <Tag color="green" className="ml-2">新增</Tag>
                  </List.Item>
                )}
              />
              <div className="mt-4 flex justify-end gap-2">
                <Button onClick={handleClose}>取消</Button>
                <Button type="primary" loading={importing} onClick={handleImport}>
                  确认导入 ({newCount})
                </Button>
              </div>
            </>
          ) : (
            <div className="text-center py-8 text-gray-500">
              <CheckCircleOutlined className="text-4xl text-green-500 mb-2" />
              <p>没有需要新增的板块</p>
              <Text type="secondary" className="text-xs">
                {preview.skipped_count > 0 && `${preview.skipped_count} 个 code 已存在，已跳过`}
                {preview.skipped_count > 0 && preview.no_data_count > 0 && '，'}
                {preview.no_data_count > 0 && `${preview.no_data_count} 个本地不存在但未拿到成分股`}
              </Text>
            </div>
          )}
        </div>
      )}
    </Modal>
  )
}
