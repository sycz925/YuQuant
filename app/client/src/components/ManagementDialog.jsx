import React, { useState, useEffect, useRef } from 'react'
import { Modal, Table, Switch, Button, Space, Input, Select, message, Form } from 'antd'
import { SearchOutlined, ReloadOutlined, PlusOutlined } from '@ant-design/icons'
import { stockApi, factorApi } from '../api'

export default function ManagementDialog({ open, onClose, category, title }) {
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState([])
  const [total, setTotal] = useState(0)
  const [searchText, setSearchText] = useState('')
  const [saving, setSaving] = useState(false)
  const [pageSize, setPageSize] = useState(10)
  const [currentPage, setCurrentPage] = useState(1)
  const [importLoading, setImportLoading] = useState(false)
  const [filterMode, setFilterMode] = useState('enabled')
  const [changedItems, setChangedItems] = useState({})
  const [addVisible, setAddVisible] = useState(false)
  const [addLoading, setAddLoading] = useState(false)
  const [addForm] = Form.useForm()
  const fileInputRef = useRef(null)
  const [importExcelLoading, setImportExcelLoading] = useState(false)

  const resetConditions = () => {
    setSearchText('')
    setFilterMode('enabled')
    setCurrentPage(1)
    setChangedItems({})
    setData([])
    setTotal(0)
  }

  const handleClose = () => {
    resetConditions()
    onClose()
  }

  useEffect(() => {
    if (open) {
      setCurrentPage(1)
      setChangedItems({})
      loadData(1, pageSize, '', 'enabled')
    }
  }, [open])

  useEffect(() => {
    // 切换分类时清空数据，但不自动加载
    setData([])
    setTotal(0)
    setCurrentPage(1)
    setChangedItems({})
  }, [category])

  const loadData = async (page, size, keyword, filter) => {
    setLoading(true)
    try {
      let res
      if (category === 'index') {
        res = await factorApi.getIndices({ page, page_size: size, keyword, filter_mode: filter })
      } else if (category === 'sector') {
        res = await factorApi.getSectors({ page, page_size: size, keyword, filter_mode: filter, min_stock_count: 5 })
      } else if (category === 'stock') {
        res = await factorApi.getStockList({ page, page_size: size, keyword, filter_mode: filter })
      }
      setData(res?.items || res?.data || [])
      setTotal(res?.total || 0)
    } catch (e) {
      console.error('加载数据失败:', e)
      message.error('加载数据失败')
    } finally {
      setLoading(false)
    }
  }

  const handleSave = async () => {
    if (Object.keys(changedItems).length === 0) {
      message.info('没有需要保存的修改')
      return
    }
    setSaving(true)
    try {
      const items = Object.entries(changedItems).map(([code, disabled]) => ({
        code,
        category,
        disabled
      }))
      await factorApi.updateDisableStatus(items)
      message.success(`保存成功`)
      setChangedItems({})
      loadData(currentPage, pageSize, '', filterMode)
    } catch (e) {
      console.error('保存失败:', e)
      message.error('保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleSearch = () => {
    setCurrentPage(1)
    loadData(1, pageSize, searchText, filterMode)
  }

  const handleFilterChange = (value) => {
    setFilterMode(value)
    setCurrentPage(1)
  }

  const handleImportExcel = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    
    setImportExcelLoading(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      
      const res = await factorApi.importSectorCodes(formData)
      if (res?.success) {
        message.success(res.message)
        loadData(currentPage, pageSize, searchText, filterMode)
      } else {
        message.error(res?.message || '导入失败')
      }
    } catch (e) {
      console.error('导入失败:', e)
      message.error(e.response?.data?.detail || '导入失败')
    } finally {
      setImportExcelLoading(false)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  const handleAdd = async () => {
    try {
      const values = await addForm.validateFields()
      setAddLoading(true)
      const res = await factorApi.createItem({
        category,
        code: values.code,
        name: values.name,
        source: values.source || '手动新增',
      })
      if (res?.success) {
        message.success(res.message)
        setAddVisible(false)
        addForm.resetFields()
        loadData(currentPage, pageSize, searchText, filterMode)
      } else {
        message.error(res?.message || '新增失败')
      }
    } catch (e) {
      if (e.errorFields) return
      message.error(e.response?.data?.detail || '新增失败')
    } finally {
      setAddLoading(false)
    }
  }

  const columns = [
    {
      title: '代码',
      dataIndex: 'code',
      key: 'code',
      width: 120,
      render: (text) => <span className="font-mono text-xs">{text}</span>
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (text, record) => record.stock_name || record.name || text
    },
    ...(category === 'sector' ? [
      { title: '数据源', dataIndex: 'source', key: 'source', width: 110, render: (t) => <span className="text-xs text-gray-500">{t || '-'}</span> },
      { title: '成分股数', dataIndex: 'stock_count', key: 'stock_count', width: 100 },
    ] : []),
    ...(category === 'index' ? [{ title: 'TDX代码', dataIndex: 'tdx_code', key: 'tdx_code', width: 100, render: (t) => <span className="font-mono text-xs">{t}</span> }] : []),
    {
      title: '禁用',
      key: 'disabled',
      width: 80,
      render: (_, record) => {
        const code = record.code || record.stock_code
        const isChanged = changedItems[code] !== undefined
        const disabled = isChanged ? changedItems[code] : (record.exclude_sync || false)
        return (
          <Switch
            size="small"
            checked={disabled}
            onChange={(checked) => setChangedItems(prev => ({ ...prev, [code]: checked }))}
          />
        )
      }
    }
  ]

  return (
    <Modal title={title} open={open} onCancel={handleClose} width={900} footer={null} destroyOnClose>
      <div className="mb-4">
        <div className="flex items-center justify-between mb-4">
          <Space>
            <Input prefix={<SearchOutlined />} placeholder="搜索..." value={searchText} onChange={(e) => setSearchText(e.target.value)} onPressEnter={handleSearch} style={{ width: 200 }} size="small" />
            <Select value={filterMode} onChange={handleFilterChange} size="small" style={{ width: 100 }}>
              <Select.Option value="enabled">已启用</Select.Option>
              <Select.Option value="disabled">已禁用</Select.Option>
            </Select>
            <Button size="small" onClick={handleSearch}>搜索</Button>
            <Button size="small" icon={<ReloadOutlined />} onClick={() => loadData(currentPage, pageSize, searchText, filterMode)} />
          </Space>
          <Space>
            {category === 'sector' && (
              <>
                <input
                  type="file"
                  ref={fileInputRef}
                  accept=".xlsx,.xls,.csv"
                  onChange={handleImportExcel}
                  style={{ display: 'none' }}
                />
                <Button 
                  size="small" 
                  loading={importExcelLoading}
                  onClick={() => fileInputRef.current?.click()}
                >
                  导入板块代码
                </Button>
              </>
            )}
            {(category === 'sector' || category === 'index') && (
              <Button size="small" icon={<PlusOutlined />} onClick={() => setAddVisible(true)}>
                新增
              </Button>
            )}
            {Object.keys(changedItems).length > 0 && (
              <Button type="primary" size="small" loading={saving} onClick={handleSave}>
                保存 ({Object.keys(changedItems).length})
              </Button>
            )}
          </Space>
        </div>

        <Table columns={columns} dataSource={data} rowKey={(r) => r.code || r.stock_code} loading={loading} size="small"
          pagination={{ current: currentPage, pageSize, total, onChange: (p, s) => { setCurrentPage(p); setPageSize(s); loadData(p, s, searchText, filterMode) } }}
        />
      </div>

      {/* 新增弹窗 */}
      <Modal
        title={`新增${category === 'sector' ? '板块' : '指数'}`}
        open={addVisible}
        onCancel={() => { setAddVisible(false); addForm.resetFields() }}
        onOk={handleAdd}
        confirmLoading={addLoading}
        destroyOnClose
        width={400}
      >
        <Form form={addForm} layout="vertical" preserve={false}>
          <Form.Item name="code" label="代码" rules={[{ required: true, message: '请输入代码' }]}>
            <Input placeholder={category === 'sector' ? '如 885955' : '如 000300'} />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder={category === 'sector' ? '如 人工智能' : '如 沪深300'} />
          </Form.Item>
          {category === 'sector' && (
            <Form.Item name="source" label="数据源" initialValue="手动新增">
              <Select>
                <Select.Option value="手动新增">手动新增</Select.Option>
                <Select.Option value="通达信概念">通达信概念</Select.Option>
                <Select.Option value="通达信行业">通达信行业</Select.Option>
                <Select.Option value="同花顺">同花顺</Select.Option>
              </Select>
            </Form.Item>
          )}
        </Form>
      </Modal>
    </Modal>
  )
}
