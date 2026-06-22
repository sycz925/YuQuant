import React, { useState, useEffect, useRef, useCallback } from 'react'
import { ConfigProvider, DatePicker, Card, Button, Space, Dropdown, Tag, Typography, Divider, Select, Modal, App as AntApp } from 'antd'
import {
  DatabaseOutlined,
  SyncOutlined,
  CalculatorOutlined,
  DeleteOutlined,
  SettingOutlined,
  DownOutlined,
  HistoryOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ExclamationCircleOutlined,
  TeamOutlined,
  StockOutlined,
  AppstoreOutlined
} from '@ant-design/icons'
import zhCN from 'antd/locale/zh_CN'
import 'dayjs/locale/zh-cn'
import dayjs from 'dayjs'
import { factorApi, syncApi, stockApi } from '../api'
import ManagementDialog from '../components/ManagementDialog'

const { Title, Text } = Typography
dayjs.locale('zh-cn')

function Settings() {
  const [dateRange, setDateRange] = useState([dayjs('2018-01-01'), dayjs()])
  const [threadCount, setThreadCount] = useState(16)
  const [minStockDays, setMinStockDays] = useState(200) // 个股最小上市天数
  const [minSectorDays, setMinSectorDays] = useState(20) // 板块最小天数

  // 管理弹窗状态
  const [indexDialogOpen, setIndexDialogOpen] = useState(false)
  const [stockDialogOpen, setStockDialogOpen] = useState(false)
  const [sectorDialogOpen, setSectorDialogOpen] = useState(false)

  const formatYmd = (d) => (d ? d.format('YYYYMMDD') : '')
  const startDate = formatYmd(dateRange?.[0])
  const endDate = formatYmd(dateRange?.[1])

  // 同步状态集 - 支持多个任务同时运行
  const [activeTasks, setActiveTasks] = useState({}) // { type: true } 记录哪些任务在运行
  const [cancelling, setCancelling] = useState({}) // { type: true } 记录哪些任务正在取消中
  const [indicesResult, setIndicesResult] = useState(null)
  const [taskProgress, setTaskProgress] = useState({}) // taskId -> progress
  const [taskStartTimes, setTaskStartTimes] = useState({})

  const pollRefs = useRef({})
  const cancellingRef = useRef({}) // 同步 cancelling 状态到 ref，用于 startTask 中判断

  const pollTaskStatus = useCallback(async (taskId, type, onFinish) => {
    try {
      const res = await syncApi.getTaskStatus(taskId)
      setTaskProgress(prev => ({ ...prev, [type]: res }))
      if (res.status === 'completed' || res.status === 'failed' || res.status === 'cancelled') {
        if (pollRefs.current[type]) {
          clearInterval(pollRefs.current[type])
          delete pollRefs.current[type]
        }
        if (onFinish) onFinish(res.status)
      }
    } catch (e) {
      console.error(`轮询任务 ${type} 失败:`, e)
    }
  }, [])

  useEffect(() => {
    return () => {
      Object.values(pollRefs.current).forEach(clearInterval)
    }
  }, [])

  // 通用启动任务
  const startTask = async (apiCall, type) => {
    // 如果该类型正在取消中，不允许启动新任务
    if (cancellingRef.current[type]) return
    setActiveTasks(prev => ({ ...prev, [type]: true }))
    setTaskProgress(prev => ({ ...prev, [type]: null }))
    setTaskStartTimes(prev => ({ ...prev, [type]: Date.now() }))
    try {
      const res = await apiCall()
      const taskId = res.task_id
      if (taskId) {
        pollRefs.current[type] = setInterval(() => {
          pollTaskStatus(taskId, type, () => {
            setActiveTasks(prev => {
              const next = { ...prev }
              delete next[type]
              return next
            })
          })
        }, 2000)
      } else {
        // 直接完成（如同步指数）
        if (type === 'indices') {
          setIndicesResult({ success: true, message: res.message })
        }
        setActiveTasks(prev => {
          const next = { ...prev }
          delete next[type]
          return next
        })
      }
    } catch (e) {
      setTaskProgress(prev => ({ ...prev, [type]: { status: 'failed', message: e.response?.data?.detail || '启动失败' } }))
      setActiveTasks(prev => {
        const next = { ...prev }
        delete next[type]
        return next
      })
    }
  }

  const handleSyncIndices = () => startTask(() => factorApi.syncIndices({ start_date: startDate, end_date: endDate, max_workers: threadCount }), 'indices')
  const handleSyncAllDaily = () => startTask(() => syncApi.syncAllDaily({ start_date: startDate, end_date: endDate, max_workers: threadCount, min_days: minStockDays }), 'daily')
  const handleSyncSectors = () => startTask(() => factorApi.syncSectors({ start_date: startDate, end_date: endDate, max_workers: threadCount, min_days: minSectorDays }), 'sectors')
  const handleCalculateRPS = () => startTask(() => factorApi.calculateRPS({ start_date: startDate, end_date: endDate, max_workers: threadCount, min_days: minStockDays, target: 'stock' }), 'rps')
  const handleCalculateSectorRPS = () => startTask(() => factorApi.calculateRPS({ start_date: startDate, end_date: endDate, target: 'sector', max_workers: threadCount, min_days: minSectorDays }), 'sector_rps')

  const clearTask = async (type) => {
    // 标记为取消中，禁止重复点击和新任务启动
    setCancelling(prev => ({ ...prev, [type]: true }))
    cancellingRef.current[type] = true
    // 清除轮询
    if (pollRefs.current[type]) {
      clearInterval(pollRefs.current[type])
      delete pollRefs.current[type]
    }
    // 向后端发送取消请求并等待完成
    const progress = taskProgress[type]
    if (progress && progress.task_id && (progress.status === 'running' || progress.status === 'pending')) {
      try {
        await syncApi.cancelTask(progress.task_id)
      } catch (e) {
        console.error('取消任务失败:', e)
      }
    }
    // 清除前端状态
    setTaskProgress(prev => {
      const next = { ...prev }
      delete next[type]
      return next
    })
    setActiveTasks(prev => {
      const next = { ...prev }
      delete next[type]
      return next
    })
    setCancelling(prev => {
      const next = { ...prev }
      delete next[type]
      return next
    })
    cancellingRef.current[type] = false
    if (type === 'indices') setIndicesResult(null)
  }

  // 危险操作菜单
  const cleanupItems = [
    {
      key: 'patch',
      label: '修复 is_final 标记',
      icon: <HistoryOutlined />,
      onClick: async () => {
        const res = await syncApi.patchIsFinal()
        alert(`完成：${res.message}`)
      }
    },
    { type: 'divider' },
    {
      key: 'clear_tasks',
      label: '清除所有任务状态',
      danger: true,
      onClick: async () => {
        // 先清除所有轮询
        Object.keys(pollRefs.current).forEach(type => {
          clearInterval(pollRefs.current[type])
          delete pollRefs.current[type]
        })
        // 向后端发送取消请求并等待全部完成
        const cancelPromises = Object.keys(taskProgress).map(type => {
          const progress = taskProgress[type]
          if (progress && progress.task_id && (progress.status === 'running' || progress.status === 'pending')) {
            return syncApi.cancelTask(progress.task_id).catch(() => {})
          }
          return Promise.resolve()
        })
        await Promise.all(cancelPromises)
        await factorApi.clearTasks()
        setTaskProgress({})
        setActiveTasks({})
        setCancelling({})
        alert('已重置')
      }
    },
    {
      key: 'clear_rps_stock',
      label: '清除个股 RPS',
      danger: true,
      onClick: async () => {
        if (confirm('确认清除？')) await factorApi.clearRps({ target: 'stock' })
      }
    },
    {
      key: 'clear_rps_sector',
      label: '清除板块 RPS',
      danger: true,
      onClick: async () => {
        if (confirm('确认清除？')) await factorApi.clearRps({ target: 'sector' })
      }
    }
  ]

  const TaskProgress = ({ type, title }) => {
    const progress = taskProgress[type] || (type === 'indices' ? indicesResult : null)
    const [showErrors, setShowErrors] = useState(false)

    if (!progress) return null

    const isPending = progress.status === 'pending'
    const isRunning = progress.status === 'running' || activeTasks[type]
    const isCompleted = progress.status === 'completed' || progress.success
    const isFailed = progress.status === 'failed' || (progress.success === false)

    const startTime = taskStartTimes[type]
    const elapsed = startTime ? (Date.now() - startTime) / 1000 : 0
    const doneCount = (progress.completed_count || 0) + (progress.skipped_count || 0)
    const speed = doneCount > 0 && elapsed > 0
      ? (doneCount / elapsed).toFixed(1)
      : 0

    return (
      <div className={`mt-4 p-4 rounded-2xl border transition-all ${
        isCompleted ? 'bg-green-50/50 border-green-100' :
        isFailed ? 'bg-red-50/50 border-red-100' : 'bg-blue-50/50 border-blue-100 animate-in fade-in'
      }`}>
        <div className="flex items-center justify-between mb-2">
          <Space>
            {isRunning ? <SyncOutlined spin className="text-blue-500" /> :
             isPending ? <SyncOutlined spin className="text-blue-400" /> :
             isCompleted ? <CheckCircleOutlined className="text-green-500" /> :
             <CloseCircleOutlined className="text-red-500" />}
            <Text strong className="text-xs uppercase tracking-wider">
              {title} {isPending ? '初始化中' : isRunning ? '处理中' : isCompleted ? '成功' : '失败'}
            </Text>
          </Space>
          <Button type="text" size="small" icon={<DeleteOutlined />} onClick={() => clearTask(type)} />
        </div>

        {isPending && (
          <div className="space-y-3">
            <Text type="secondary" italic className="text-[10px]">正在初始化任务...</Text>
          </div>
        )}

        {isRunning && (
          <div className="space-y-3">
            {type === 'daily' && (
              <Text type="secondary" className="text-[10px]">使用 {threadCount} 线程并行同步</Text>
            )}
            {progress.total_count > 0 ? (
              <>
                <div className="w-full bg-gray-200/50 rounded-full h-1.5 overflow-hidden">
                  <div
                    className="bg-blue-600 h-full transition-all duration-500"
                    style={{ width: `${Math.round((doneCount / progress.total_count) * 100)}%` }}
                  />
                </div>
                <div className="flex justify-between text-[10px] font-bold text-gray-400 font-mono">
                  <Space size="middle">
                    <span>{doneCount} / {progress.total_count}</span>
                    <span className="text-blue-500">{speed} items/s</span>
                  </Space>
                  <span>{Math.round((doneCount / progress.total_count) * 100)}%</span>
                </div>
              </>
            ) : (
              <Text type="secondary" italic className="text-[10px]">{progress.current_stock_name || '正在初始化...'}</Text>
            )}

            {progress.current_stock_name && (
              <div className="flex items-center space-x-2">
                <Tag color="blue" className="!m-0 text-[10px] border-none font-bold">
                  {progress.status === 'running' && type.includes('rps') ? 'CALC' : (progress.current_stock || 'SYS')}
                </Tag>
                <Text className="text-[10px] font-medium text-blue-600 truncate">{progress.current_stock_name}</Text>
              </div>
            )}

            {isRunning && progress.current_stock_name && type.includes('rps') && (
              <div className="mt-2 p-2 bg-blue-50/80 rounded-lg border border-blue-100">
                <div className="flex items-center space-x-2">
                  <div className="w-2 h-2 bg-blue-500 rounded-full animate-pulse" />
                  <Text className="text-[10px] font-medium text-blue-700">
                    {progress.current_stock_name}
                  </Text>
                </div>
              </div>
            )}
          </div>
        )}

        {(isCompleted || isFailed) && (
          <div className="space-y-2">
            <Text size="small" type={isCompleted ? "success" : "danger"} className="block text-xs italic">
              {progress.message || progress.error || (isCompleted ? '操作已成功完成' : '发生未知错误')}
            </Text>

            {progress.failed_stocks && progress.failed_stocks.length > 0 && (
              <div>
                <Button
                  type="link"
                  size="small"
                  danger
                  className="p-0 h-auto text-[10px] font-bold"
                  onClick={() => setShowErrors(true)}
                >
                  查看 {progress.failed_stocks.length} 条失败记录
                </Button>
                <Modal
                  title="失败记录"
                  open={showErrors}
                  onCancel={() => setShowErrors(false)}
                  footer={null}
                  width={600}
                  styles={{ body: { maxHeight: '60vh', overflowY: 'auto' } }}
                >
                  {progress.failed_stocks.map((fs, idx) => (
                    <div key={idx} className="text-xs flex justify-between py-2 border-b last:border-0">
                      <span className="font-bold text-red-600">{fs.stock_code} {fs.stock_name}</span>
                      <span className="text-gray-400 truncate ml-4 max-w-[300px]">{fs.error}</span>
                    </div>
                  ))}
                </Modal>
              </div>
            )}
          </div>
        )}
      </div>
    )
  }

  return (
    <ConfigProvider locale={zhCN}>
      <div className="max-w-4xl mx-auto space-y-8 pb-12">
        <header className="flex items-center justify-between">
          <Space size="middle">
            <div className="p-3 bg-gray-900 rounded-2xl text-white">
              <SettingOutlined style={{ fontSize: '24px' }} />
            </div>
            <div>
              <Title level={2} style={{ margin: 0, fontWeight: 900, letterSpacing: '-0.5px' }}>数据管理</Title>
              <Text type="secondary" className="text-xs font-bold uppercase tracking-widest">System Configuration & Data Sync</Text>
            </div>
          </Space>

          <Space size="middle">
            <div className="flex items-center space-x-2">
              <Text className="text-sm font-medium text-gray-600">并发线程</Text>
              <Select
                value={threadCount}
                onChange={setThreadCount}
                style={{ width: 100 }}
                size="large"
              >
                <Select.Option value={4}>4</Select.Option>
                <Select.Option value={8}>8</Select.Option>
                <Select.Option value={16}>16</Select.Option>
                <Select.Option value={24}>24</Select.Option>
                <Select.Option value={32}>32</Select.Option>
              </Select>
            </div>
            <Dropdown menu={{ items: cleanupItems }} placement="bottomRight">
              <Button icon={<ExclamationCircleOutlined />} size="large" className="rounded-xl font-bold">
                更多工具 <DownOutlined />
              </Button>
            </Dropdown>
          </Space>
        </header>

        {/* 全局日期选择 */}
        <Card className="rounded-3xl shadow-sm border-none bg-blue-600 text-white overflow-hidden relative">
           <div className="absolute top-0 right-0 p-8 opacity-10">
              <DatabaseOutlined style={{ fontSize: '100px' }} />
           </div>
           <Title level={4} className="!text-white !mb-4 flex items-center">
              <HistoryOutlined className="mr-2" /> 同步时间范围
           </Title>
           <div className="flex flex-wrap items-center gap-6">
              <DatePicker.RangePicker
                value={dateRange}
                onChange={setDateRange}
                size="large"
                className="!rounded-xl !border-none !shadow-inner !bg-white/20 !text-white"
                allowClear={false}
              />
              <div className="px-4 py-2 bg-white/10 rounded-xl backdrop-blur-md border border-white/20">
                 <Text className="!text-white font-mono font-bold tracking-tight">
                    {startDate} <span className="mx-2 opacity-50">→</span> {endDate}
                 </Text>
              </div>
           </div>
        </Card>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* 指数 */}
          <Card className="rounded-2xl border-gray-100 shadow-sm hover:shadow-md transition-shadow">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center space-x-2">
                <TeamOutlined className="text-blue-500" />
                <Text strong className="text-gray-900 text-base">指数</Text>
              </div>
              <Button size="small" onClick={() => setIndexDialogOpen(true)}>
                管理
              </Button>
            </div>
            <Text type="secondary" className="text-xs block mb-3">同步大盘指数日线数据</Text>
            <Button
              type="primary"
              block
              icon={<SyncOutlined />}
              onClick={handleSyncIndices}
              loading={activeTasks.indices || cancelling.indices}
              disabled={activeTasks.indices || cancelling.indices}
              className="rounded-lg font-bold"
            >
              同步指数
            </Button>
            <TaskProgress type="indices" title="指数数据" />
          </Card>

          {/* 个股 */}
          <Card className="rounded-2xl border-gray-100 shadow-sm hover:shadow-md transition-shadow">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center space-x-2">
                <StockOutlined className="text-green-500" />
                <Text strong className="text-gray-900 text-base">个股</Text>
              </div>
              <div className="flex items-center space-x-2">
                <Select
                  value={minStockDays}
                  onChange={setMinStockDays}
                  style={{ width: 90 }}
                  size="small"
                >
                  <Select.Option value={50}>50天</Select.Option>
                  <Select.Option value={100}>100天</Select.Option>
                  <Select.Option value={150}>150天</Select.Option>
                  <Select.Option value={200}>200天</Select.Option>
                  <Select.Option value={250}>250天</Select.Option>
                </Select>
                <Button size="small" onClick={() => setStockDialogOpen(true)}>
                  管理
                </Button>
              </div>
            </div>
            <Text type="secondary" className="text-xs block mb-3">同步全部 A 股日线数据</Text>
            <Space direction="vertical" className="w-full">
              <Button
                block
                icon={<SyncOutlined />}
                onClick={handleSyncAllDaily}
                loading={activeTasks.daily || cancelling.daily}
                disabled={activeTasks.daily || cancelling.daily}
                className="rounded-lg font-bold"
              >
                同步数据
              </Button>
              <Button
                block
                icon={<CalculatorOutlined />}
                onClick={handleCalculateRPS}
                loading={activeTasks.rps || cancelling.rps}
                disabled={activeTasks.daily || activeTasks.rps || cancelling.daily || cancelling.rps}
                className="rounded-lg font-bold !border-purple-500 !text-purple-600 hover:!bg-purple-50"
              >
                计算 RPS
              </Button>
            </Space>
            <TaskProgress type="daily" title="个股日线" />
            <TaskProgress type="rps" title="个股 RPS" />
          </Card>

          {/* 板块 */}
          <Card className="rounded-2xl border-gray-100 shadow-sm hover:shadow-md transition-shadow">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center space-x-2">
                <AppstoreOutlined className="text-purple-500" />
                <Text strong className="text-gray-900 text-base">板块</Text>
              </div>
              <div className="flex items-center space-x-2">
                <Select
                  value={minSectorDays}
                  onChange={setMinSectorDays}
                  style={{ width: 90 }}
                  size="small"
                >
                  <Select.Option value={10}>10天</Select.Option>
                  <Select.Option value={20}>20天</Select.Option>
                  <Select.Option value={30}>30天</Select.Option>
                  <Select.Option value={40}>40天</Select.Option>
                  <Select.Option value={50}>50天</Select.Option>
                </Select>
                <Button size="small" onClick={() => setSectorDialogOpen(true)}>
                  管理
                </Button>
              </div>
            </div>
            <Text type="secondary" className="text-xs block mb-3">同步通达信板块概念并聚合</Text>
            <Space direction="vertical" className="w-full">
              <Button
                block
                icon={<SyncOutlined />}
                onClick={handleSyncSectors}
                loading={activeTasks.sectors || cancelling.sectors}
                disabled={activeTasks.sectors || cancelling.sectors}
                className="rounded-lg font-bold"
              >
                同步数据
              </Button>
              <Button
                block
                icon={<CalculatorOutlined />}
                onClick={handleCalculateSectorRPS}
                loading={activeTasks.sector_rps || cancelling.sector_rps}
                disabled={activeTasks.sectors || activeTasks.sector_rps || cancelling.sectors || cancelling.sector_rps}
                className="rounded-lg font-bold !border-purple-500 !text-purple-600 hover:!bg-purple-50"
              >
                计算 RPS
              </Button>
            </Space>
            <TaskProgress type="sectors" title="板块数据" />
            <TaskProgress type="sector_rps" title="板块 RPS" />
          </Card>
        </div>
      </div>

      {/* 管理弹窗 */}
      <ManagementDialog
        open={indexDialogOpen}
        onClose={() => setIndexDialogOpen(false)}
        category="index"
        title="指数"
        fetchData={(params) => factorApi.getIndices(params)}
      />
      <ManagementDialog
        open={stockDialogOpen}
        onClose={() => setStockDialogOpen(false)}
        category="stock"
        title="个股"
        fetchData={(params) => stockApi.getStockList(params)}
      />
      <ManagementDialog
        open={sectorDialogOpen}
        onClose={() => setSectorDialogOpen(false)}
        category="sector"
        title="板块"
        fetchData={(params) => factorApi.getSectors({ min_stock_count: 0, ...params })}
      />
    </ConfigProvider>
  )
}

export default Settings
