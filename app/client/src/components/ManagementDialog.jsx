import React, { useState, useEffect, useRef, useCallback } from 'react'
import { Modal, Table, Switch, Button, Space, Input, Typography, message, Tooltip, Select } from 'antd'
import { SearchOutlined, ReloadOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons'
import { exclusionApi, stockApi, factorApi } from '../api'

const { Text } = Typography

export default function ManagementDialog({ open, onClose, category, title, fetchData }) {
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState([])
  const [total, setTotal] = useState(0)
  const [exclusions, setExclusions] = useState({})
  const [searchText, setSearchText] = useState('')
  const [saving, setSaving] = useState(false)
  const [showAdd, setShowAdd] = useState(false)
  const [addKeyword, setAddKeyword] = useState('')
  const [addResults, setAddResults] = useState([])
  const [addLoading, setAddLoading] = useState(false)
  const [pageSize, setPageSize] = useState(50)
  const [currentPage, setCurrentPage] = useState(1)
  const [importLoading, setImportLoading] = useState(false)
  const [scanLoading, setScanLoading] = useState(false)
  const [filterMode, setFilterMode] = useState('enabled')
  const [committedFilter, setCommittedFilter] = useState('enabled')
  const [committedKeyword, setCommittedKeyword] = useState('')
  const fileInputRef = useRef(null)

  useEffect(() => {
    if (open) {
      setCurrentPage(1)
      setSearchText('')
      setCommittedKeyword('')
      setFilterMode('enabled')
      setCommittedFilter('enabled')
      setShowAdd(false)
      setAddKeyword('')
      setAddResults([])
    }
  }, [open, category])

  useEffect(() => {
    if (open) {
      loadData(1, pageSize, '', 'enabled')
    }
  }, [open, category])

  const loadData = useCallback(async (page, size, keyword, filter) => {
    setLoading(true)
    try {
      const params = { page, page_size: size }
      if (keyword) params.keyword = keyword
      if (filter && filter !== 'all') params.filter_mode = filter
      const res = await fetchData(params)
      let items = []
      let serverTotal = 0
      if (category === 'index') {
        items = res?.indices || []
        serverTotal = res?.total || items.length
      } else if (category === 'sector') {
        items = res?.items || []
        serverTotal = res?.total || items.length
      } else {
        items = res?.data || []
        serverTotal = res?.total || items.length
      }
      setData(items)
      setTotal(serverTotal)

      const exclRes = await exclusionApi.getExclusions({ category })
      const exclMap = {}
      ;(exclRes?.items || []).forEach(item => {
        if (!item.code) return
        exclMap[item.code] = {
          code: item.code,
          name: item.name || item.code,
          disabled: item.exclude_sync || item.exclude_rps || item.exclude_display || false,
        }
      })
      setExclusions(exclMap)
    } catch (e) {
      console.error('加载数据失败:', e)
      message.error('加载数据失败')
    } finally {
      setLoading(false)
    }
  }, [category, fetchData, pageSize])

  const handleImportCodes = async (file) => {
    if (!file) return
    setImportLoading(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const res = await factorApi.importSectorCodes(formData)
      if (res?.success) {
        message.success(res.message)
        loadData(currentPage, pageSize, committedKeyword, committedFilter)
      } else {
        message.error(res?.message || '导入失败')
      }
    } catch (e) {
      console.error('导入失败:', e)
      message.error('导入失败')
    } finally {
      setImportLoading(false)
    }
  }

  const handleScan = async () => {
    setScanLoading(true)
    try {
      const res = await stockApi.scanNewStocks()
      if (res?.success) {
        const count = res.new_count || 0
        if (count > 0) {
          message.success(`发现 ${count} 只新股票`)
          loadData(currentPage, pageSize, committedKeyword, committedFilter)
        } else {
          message.info('没有发现新股票')
        }
      } else {
        message.error(res?.message || '扫描失败')
      }
    } catch (e) {
      console.error('扫描失败:', e)
      message.error('扫描失败')
    } finally {
      setScanLoading(false)
    }
  }

  const isDisabled = (code) => {
    const e = exclusions[code]
    return e && e.disabled
  }

  const handleToggleDisabled = (code, name, disabled) => {
    setExclusions(prev => ({
      ...prev,
      [code]: { code, name, disabled }
    }))
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      const items = Object.values(exclusions)
        .filter(item => item.code)
        .map(item => ({
          code: item.code,
          name: item.name || item.code,
          category,
          exclude_sync: item.disabled || false,
          exclude_rps: item.disabled || false,
          exclude_display: item.disabled || false,
        }))
      await exclusionApi.updateExclusions(items)
      message.success('保存成功')
      onClose()
    } catch (e) {
      console.error('保存失败:', e)
      message.error('保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleAddItem = (item) => {
    const code = item.code || item.stock_code
    const name = item.name || item.stock_name
    if (!code) return
    if (data.some(d => (d.code || d.stock_code) === code)) {
      message.info('该品种已存在')
      return
    }
    setData(prev => [...prev, { code, name }])
    setExclusions(prev => ({
      ...prev,
      [code]: { code, name, disabled: false }
    }))
    message.success(`已添加 ${name}`)
  }

  const handleSearchAdd = async () => {
    if (!addKeyword.trim()) return
    setAddLoading(true)
    try {
      let results = []
      if (category === 'stock') {
        const res = await stockApi.searchStocks(addKeyword.trim())
        results = (res?.data || res?.items || []).map(s => ({
          code: s.code || s.stock_code, name: s.name || s.stock_name
        }))
      } else if (category === 'index') {
        const res = await factorApi.searchIndices(addKeyword.trim())
        results = (res?.data || []).map(i => ({ code: i.code, name: i.name }))
      } else if (category === 'sector') {
        const res = await factorApi.getSectors({ keyword: addKeyword.trim(), limit: 500 })
        results = (res?.items || []).map(s => ({ code: s.code, name: s.name }))
      }
      setAddResults(results.filter(r => r.code))
    } catch (e) {
      message.error('搜索失败')
    } finally {
      setAddLoading(false)
    }
  }

  const handleToggleAll = (disabled) => {
    const newExclusions = { ...exclusions }
    data.forEach(item => {
      const code = item.code || item.stock_code
      if (!code) return
      newExclusions[code] = {
        code,
        name: item.name || item.stock_name || code,
        disabled,
      }
    })
    setExclusions(newExclusions)
  }

  const disabledCount = data.filter(item => {
    const code = item.code || item.stock_code
    return isDisabled(code)
  }).length

  const allDisabled = data.length > 0 && data.every(item => {
    const code = item.code || item.stock_code
    return isDisabled(code)
  })

  const columns = [
    {
      title: '代码',
      dataIndex: 'code',
      key: 'code',
      width: 100,
      render: (text) => <span className="font-mono text-xs">{text}</span>
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 100,
    },
    ...(category === 'sector' ? [
      {
        title: 'RPS10',
        dataIndex: 'rps_10',
        key: 'rps_10',
        width: 70,
        sorter: (a, b) => (a.rps_10 || 0) - (b.rps_10 || 0),
        render: (val) => val != null ? <span className="text-xs font-mono">{val}</span> : <span className="text-xs text-gray-300">-</span>
      },
      {
        title: 'RPS20',
        dataIndex: 'rps_20',
        key: 'rps_20',
        width: 70,
        sorter: (a, b) => (a.rps_20 || 0) - (b.rps_20 || 0),
        render: (val) => val != null ? <span className="text-xs font-mono">{val}</span> : <span className="text-xs text-gray-300">-</span>
      },
      {
        title: 'RPS50',
        dataIndex: 'rps_50',
        key: 'rps_50',
        width: 70,
        sorter: (a, b) => (a.rps_50 || 0) - (b.rps_50 || 0),
        render: (val) => val != null ? <span className="text-xs font-mono">{val}</span> : <span className="text-xs text-gray-300">-</span>
      },
    ] : []),
    {
      title: (
        <Tooltip title="切换所有">
          <span
            className="cursor-pointer select-none"
            onClick={() => handleToggleAll(!allDisabled)}
          >
            禁用 {allDisabled ? '✓' : ''}
          </span>
        </Tooltip>
      ),
      key: 'disabled',
      width: 70,
      align: 'center',
      render: (_, record) => {
        const code = record.code || record.stock_code
        return (
          <Switch
            size="small"
            checked={isDisabled(code)}
            onChange={(v) => handleToggleDisabled(code, record.name, v)}
          />
        )
      }
    },
  ]

  const handleSearch = () => {
    setCurrentPage(1)
    setCommittedKeyword(searchText)
    setCommittedFilter(filterMode)
    loadData(1, pageSize, searchText, filterMode)
  }

  const handleSearchClear = () => {
    setSearchText('')
    setCurrentPage(1)
    setCommittedKeyword('')
    setCommittedFilter(filterMode)
    loadData(1, pageSize, '', filterMode)
  }

  const handleTableChange = (pagination) => {
    const newPage = pagination.current
    const newSize = pagination.pageSize
    setCurrentPage(newPage)
    setPageSize(newSize)
    loadData(newPage, newSize, committedKeyword, committedFilter)
  }

  return (
    <Modal
      title={
        <div className="flex items-center justify-between">
          <span>
            {title} 管理
            {disabledCount > 0 && (
              <Text type="warning" className="ml-2 text-sm">
                (禁用: {disabledCount}项)
              </Text>
            )}
          </span>
          <Space size={4} className="mr-8">
            {category === 'stock' && (
              <Button
                type="link"
                size="small"
                loading={scanLoading}
                onClick={handleScan}
              >
                检索
              </Button>
            )}
            {category === 'sector' && (
              <Button
                type="link"
                size="small"
                icon={<UploadOutlined />}
                loading={importLoading}
                onClick={() => fileInputRef.current?.click()}
              >
                导入代码
              </Button>
            )}
            <Button type="link" size="small" icon={<PlusOutlined />} onClick={() => setShowAdd(!showAdd)}>
              新增
            </Button>
            <Button type="link" size="small" icon={<ReloadOutlined />} onClick={() => loadData(currentPage, pageSize, committedKeyword, committedFilter)}>
              刷新
            </Button>
          </Space>
        </div>
      }
      open={open}
      onCancel={onClose}
      width={650}
      footer={[
        <Button key="cancel" onClick={onClose}>
          取消
        </Button>,
        <Button key="save" type="primary" onClick={handleSave} loading={saving}>
          保存配置
        </Button>,
      ]}
    >
      <input
        ref={fileInputRef}
        type="file"
        accept=".xlsx,.xls,.csv"
        style={{ display: 'none' }}
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) handleImportCodes(file)
          e.target.value = ''
        }}
      />
      {showAdd && (
        <div className="mb-3 p-3 bg-gray-50 rounded-lg border border-gray-200">
          <div className="flex items-center space-x-2">
            <Input
              placeholder={category === 'stock' ? '搜索股票代码或名称...' : '搜索代码或名称...'}
              value={addKeyword}
              onChange={(e) => setAddKeyword(e.target.value)}
              onPressEnter={handleSearchAdd}
              style={{ flex: 1 }}
              size="small"
            />
            <Button size="small" onClick={handleSearchAdd} loading={addLoading}>
              搜索
            </Button>
          </div>
          {addResults.length > 0 && (
            <div className="mt-2 max-h-32 overflow-y-auto">
              {addResults.map(item => {
                const alreadyExists = data.some(d => (d.code || d.stock_code) === item.code)
                return (
                  <div key={item.code} className="flex items-center justify-between py-1 px-2 hover:bg-white rounded">
                    <span className="text-xs">
                      <span className="font-mono mr-2">{item.code}</span>
                      {item.name}
                    </span>
                    {alreadyExists ? (
                      <Text type="secondary" className="text-xs">已存在</Text>
                    ) : (
                      <Button type="link" size="small" onClick={() => handleAddItem(item)}>
                        添加
                      </Button>
                    )}
                  </div>
                )
              })}
            </div>
          )}
          {addKeyword && addResults.length === 0 && !addLoading && (
            <Text type="secondary" className="text-xs mt-2 block">未找到匹配结果</Text>
          )}
        </div>
      )}

      <div className="mb-4 flex items-center gap-2">
        <Select
          size="small"
          value={filterMode}
          onChange={(v) => setFilterMode(v)}
          style={{ width: 90 }}
          options={[
            { value: 'enabled', label: '启用' },
            { value: 'disabled', label: '禁用' },
            { value: 'all', label: '全部' },
          ]}
        />
        <Input
          placeholder="搜索代码或名称..."
          prefix={<SearchOutlined />}
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          onPressEnter={handleSearch}
          allowClear
          onClear={handleSearchClear}
          size="small"
          style={{ flex: 1 }}
        />
        <Button size="small" type="primary" onClick={handleSearch}>搜索</Button>
        <span className="text-xs text-gray-400 whitespace-nowrap">共 {total} 项</span>
      </div>
      
      <div className="mb-3 text-xs text-gray-500">
        打开开关后将禁用（不同步、不计算、不显示）
      </div>

      <Table
        dataSource={data}
        columns={columns}
        rowKey={(record) => record.code || record.stock_code}
        loading={loading}
        size="small"
        pagination={{
          current: currentPage,
          pageSize: pageSize,
          total: total,
          showSizeChanger: true,
          pageSizeOptions: ['50', '100', '200'],
          showTotal: (t) => `共 ${t} 项`,
        }}
        onChange={handleTableChange}
        bordered
        scroll={{ y: 400 }}
      />
    </Modal>
  )
}
