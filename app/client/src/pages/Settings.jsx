import React, { useState, useEffect, useRef, useCallback } from 'react'
import { ConfigProvider, Card, Button, Space, Typography, Select, Tag, message, Modal, List, Checkbox } from 'antd'
import {
  DatabaseOutlined,
  SyncOutlined,
  SettingOutlined,
  HistoryOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  BarChartOutlined,
  StockOutlined,
  AppstoreOutlined,
  CalculatorOutlined,
  DeleteOutlined,
  SwapOutlined
} from '@ant-design/icons'
import zhCN from 'antd/locale/zh_CN'
import 'dayjs/locale/zh-cn'
import dayjs from 'dayjs'
import { factorApi, syncApi } from '../api'
import ManagementDialog from '../components/ManagementDialog'

const { Title, Text } = Typography
dayjs.locale('zh-cn')

function Settings() {
  const [threadCount, setThreadCount] = useState(24)

  // 管理对话框状态
  const [manageDialog, setManageDialog] = useState({ open: false, category: '', title: '' })

  // 同步时间窗口检查
  const checkSyncTime = () => {
    const now = dayjs()
    const t = now.hour() * 60 + now.minute()
    return (t >= 690 && t < 780) || (t >= 930 && t <= 1439)
  }
  const [syncTimeOk, setSyncTimeOk] = useState(checkSyncTime)
  const [syncTimeMsg, setSyncTimeMsg] = useState('')
  useEffect(() => {
    const timer = setInterval(() => {
      const ok = checkSyncTime()
      setSyncTimeOk(ok)
      if (!ok) {
        const now = dayjs()
        const t = now.hour() * 60 + now.minute()
        if (t < 690) setSyncTimeMsg(`盘中同步 11:30 开放`)
        else if (t < 930) setSyncTimeMsg(`盘后同步 15:30 开放`)
        else setSyncTimeMsg(`明日同步 11:30 开放`)
      } else {
        setSyncTimeMsg('')
      }
    }, 30000)
    return () => clearInterval(timer)
  }, [])

  // 同步状态集
  const [activeTasks, setActiveTasks] = useState({})
  const [cancelling, setCancelling] = useState({})
  const [indicesResult, setIndicesResult] = useState(null)
  const [taskProgress, setTaskProgress] = useState({})
  const [taskStartTimes, setTaskStartTimes] = useState({})

  // 对比数据状态
  const [compareModal, setCompareModal] = useState({ open: false, type: '', data: null, loading: false })

  // DeepSeek 时间窗口配置
  const [deepseekTimeLimit, setDeepseekTimeLimit] = useState(true)

  useEffect(() => {
    loadDeepseekConfig()
  }, [])

  const loadDeepseekConfig = async () => {
    try {
      const res = await factorApi.getDeepseekTimeLimit()
      if (res?.success) {
        setDeepseekTimeLimit(res.enabled)
      }
    } catch (e) {
      console.error('加载配置失败:', e)
    }
  }

  const handleToggleDeepseekTimeLimit = async () => {
    const newValue = !deepseekTimeLimit
    try {
      const res = await factorApi.setDeepseekTimeLimit(newValue)
      if (res?.success) {
        setDeepseekTimeLimit(newValue)
        message.success(`已${newValue ? '启用' : '禁用'}时间窗口限制`)
      }
    } catch (e) {
      console.error('设置配置失败:', e)
      message.error('设置失败')
    }
  }

  const pollRefs = useRef({})
  const cancellingRef = useRef({})

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

  const handleSyncIndices = () => startTask(() => factorApi.syncIndices({ max_workers: threadCount }), 'indices')
  const handleSyncAllDaily = () => startTask(() => syncApi.syncAllDaily({ max_workers: threadCount, min_days: 200 }), 'daily')
  const handleCalculateRPS = () => startTask(() => factorApi.calculateRPS({ max_workers: threadCount, min_days: 200, target: 'stock' }), 'rps')
  const handleSyncSectors = () => startTask(() => factorApi.syncSectors({ max_workers: threadCount, min_days: 20 }), 'sectors')
  const handleCalculateSectorRPS = () => startTask(() => factorApi.calculateRPS({ target: 'sector', max_workers: threadCount, min_days: 20 }), 'sector_rps')
  const handleSyncIndexPE = () => {
    const savedToken = localStorage.getItem('legulegu_token')
    if (!savedToken) {
      message.warning('请先在设置中配置乐咕乐股 Token')
      return
    }
    startTask(() => factorApi.syncIndexPE(savedToken), 'index_pe')
  }
  const handleSyncBaseData = () => startTask(() => factorApi.precomputeBase(), 'precompute_base')

  // 等待任务完成的辅助函数
  const waitForTask = (type) => {
    return new Promise(resolve => {
      const check = () => {
        if (!activeTasks[type]) resolve()
        else setTimeout(check, 1000)
      }
      check()
    })
  }

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

  // 对比数据处理（任务模式）
  const comparePollRef = useRef(null)

  const handleCompare = async (type) => {
    setCompareModal({ open: true, type, data: null, loading: true, taskStep: '启动中...' })
    try {
      const res = type === 'stock'
        ? await factorApi.compareStocksStart()
        : await factorApi.compareSectorsStart()

      if (!res?.task_id) {
        message.error('启动对比任务失败')
        setCompareModal({ open: false, type: '', data: null, loading: false })
        return
      }

      // 轮询任务状态
      comparePollRef.current = setInterval(async () => {
        try {
          const status = await factorApi.compareStatus(res.task_id)
          if (status.status === 'completed') {
            clearInterval(comparePollRef.current)
            setCompareModal({
              open: true,
              type,
              data: status.result,
              loading: false,
              taskStep: null
            })
          } else if (status.status === 'failed') {
            clearInterval(comparePollRef.current)
            message.error('对比任务失败: ' + (status.error || '未知错误'))
            setCompareModal({ open: false, type: '', data: null, loading: false })
          } else {
            setCompareModal(prev => ({
              ...prev,
              taskStep: status.step || '处理中...'
            }))
          }
        } catch (e) {
          console.error('轮询对比状态失败:', e)
        }
      }, 2000)
    } catch (e) {
      console.error('启动对比任务失败:', e)
      message.error('启动对比任务失败')
      setCompareModal({ open: false, type: '', data: null, loading: false })
    }
  }


  // 导入数据
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
        // 更新弹窗数据
        setCompareModal(prev => ({
          ...prev,
          data: { ...prev.data, new_count: 0 }
        }))
      } else {
        message.error(res?.message || '导入失败')
      }
    } catch (e) {
      console.error('导入失败:', e)
      message.error('导入失败')
    }
  }

  // 关闭弹窗时清除轮询
  const handleCloseCompareModal = () => {
    if (comparePollRef.current) {
      clearInterval(comparePollRef.current)
    }
    setCompareModal({ open: false, type: '', data: null, loading: false })
  }

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
              <Title level={2} style={{ margin: 0, fontWeight: 900, letterSpacing: '-0.5px' }}>一键更新</Title>
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
          </Space>
        </header>

        {/* 同步说明 */}
        <Card className="rounded-3xl shadow-sm border-none bg-blue-600 text-white overflow-hidden relative">
           <div className="absolute top-0 right-0 p-8 opacity-10">
              <DatabaseOutlined style={{ fontSize: '100px' }} />
           </div>
           <Title level={4} className="!text-white !mb-2 flex items-center">
              <HistoryOutlined className="mr-2" /> 同步说明
           </Title>
           <Text className="!text-white/80 text-sm">
              逐天回溯同步：从最新交易日往前逐天检查，找到 is_final 收盘数据 ≥ 95% 的那天即停止。最早追溯10年。
           </Text>
        </Card>

        {/* DeepSeek 配置 */}
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
              <Text className="text-sm" type={deepseekTimeLimit ? 'secondary' : 'success'}>
                {deepseekTimeLimit ? '已启用' : '已禁用'}
              </Text>
              <button
                onClick={handleToggleDeepseekTimeLimit}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  deepseekTimeLimit ? 'bg-blue-600' : 'bg-gray-300'
                }`}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    deepseekTimeLimit ? 'translate-x-6' : 'translate-x-1'
                  }`}
                />
              </button>
            </div>
          </div>
          <Text type="secondary" className="text-xs mt-2 block">
            关闭后可在任何时间调用 DeepSeek API 生成分析，不受时间窗口限制
          </Text>
        </Card>

        {/* 清除任务记录 */}
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
              onClick={() => {
                Modal.confirm({
                  title: '确认清除',
                  content: '确定要清除所有任务记录吗？此操作不可恢复。',
                  okText: '确定清除',
                  cancelText: '取消',
                  onOk: async () => {
                    try {
                      const res = await factorApi.clearSyncTasks()
                      if (res?.success) {
                        message.success(res.message || '清除成功')
                      } else {
                        message.error('清除失败')
                      }
                    } catch (e) {
                      message.error('清除失败: ' + (e.response?.data?.detail || e.message))
                    }
                  }
                })
              }}
              className="rounded-lg"
            >
              清除记录
            </Button>
          </div>
        </Card>

        {/* 管理指数、个股、板块 */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Card 
            className="rounded-2xl shadow-sm border-gray-100 cursor-pointer hover:shadow-md transition-shadow"
            onClick={() => setManageDialog({ open: true, category: 'index', title: '管理指数' })}
          >
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center space-x-2">
                <div className="p-3 bg-blue-100 rounded-xl">
                  <BarChartOutlined className="text-blue-600 text-xl" />
                </div>
                <div>
                  <Title level={5} className="!mb-0">指数</Title>
                  <Text type="secondary" className="text-xs">同步大盘指数日线数据</Text>
                </div>
              </div>
              <Button size="small" onClick={(e) => { e.stopPropagation(); setManageDialog({ open: true, category: 'index', title: '管理指数' }) }}>
                管理
              </Button>
            </div>
            <Space direction="vertical" className="w-full">
              <Button
                block
                icon={<SyncOutlined />}
                onClick={(e) => { e.stopPropagation(); handleSyncIndices() }}
                loading={activeTasks.indices || cancelling.indices}
                disabled={activeTasks.indices || cancelling.indices}
                className="rounded-lg font-bold"
              >
                同步指数
              </Button>
              <Button
                block
                icon={<CalculatorOutlined />}
                onClick={(e) => { e.stopPropagation(); handleSyncIndexPE() }}
                loading={activeTasks.index_pe || cancelling.index_pe}
                disabled={activeTasks.index_pe || cancelling.index_pe}
                className="rounded-lg font-bold !border-purple-500 !text-purple-600 hover:!bg-purple-50"
              >
                计算 PE
              </Button>
              <Button
                block
                icon={<DatabaseOutlined />}
                onClick={(e) => { e.stopPropagation(); handleSyncBaseData() }}
                loading={activeTasks.precompute_base || cancelling.precompute_base}
                disabled={activeTasks.precompute_base || cancelling.precompute_base}
                className="rounded-lg font-bold !border-green-500 !text-green-600 hover:!bg-green-50"
              >
                同步基础数据
              </Button>
            </Space>
          </Card>

          <Card 
            className="rounded-2xl shadow-sm border-gray-100 cursor-pointer hover:shadow-md transition-shadow"
            onClick={() => setManageDialog({ open: true, category: 'stock', title: '管理个股' })}
          >
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center space-x-2">
                <div className="p-3 bg-green-100 rounded-xl">
                  <StockOutlined className="text-green-600 text-xl" />
                </div>
                <div>
                  <Title level={5} className="!mb-0">个股</Title>
                  <Text type="secondary" className="text-xs">同步全部 A 股日线数据</Text>
                </div>
              </div>
              <Button size="small" onClick={(e) => { e.stopPropagation(); setManageDialog({ open: true, category: 'stock', title: '管理个股' }) }}>
                管理
              </Button>
            </div>
            <Space direction="vertical" className="w-full">
              <Button
                block
                icon={<SyncOutlined />}
                onClick={(e) => { e.stopPropagation(); handleSyncAllDaily() }}
                loading={activeTasks.daily || cancelling.daily}
                disabled={activeTasks.daily || cancelling.daily}
                className="rounded-lg font-bold"
              >
                同步数据
              </Button>
              <Button
                block
                icon={<CalculatorOutlined />}
                onClick={(e) => { e.stopPropagation(); handleCalculateRPS() }}
                loading={activeTasks.rps || cancelling.rps}
                disabled={activeTasks.daily || activeTasks.rps || cancelling.daily || cancelling.rps}
                className="rounded-lg font-bold !border-purple-500 !text-purple-600 hover:!bg-purple-50"
              >
                计算 RPS
              </Button>
              <Button
                block
                icon={<SwapOutlined />}
                onClick={(e) => { e.stopPropagation(); handleCompare('stock') }}
                className="rounded-lg font-bold !border-orange-500 !text-orange-600 hover:!bg-orange-50"
              >
                对比数据
              </Button>
            </Space>
          </Card>

          <Card
            className="rounded-2xl shadow-sm border-gray-100 cursor-pointer hover:shadow-md transition-shadow"
            onClick={() => setManageDialog({ open: true, category: 'sector', title: '管理板块' })}
          >
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center space-x-2">
                <div className="p-3 bg-purple-100 rounded-xl">
                  <AppstoreOutlined className="text-purple-600 text-xl" />
                </div>
                <div>
                  <Title level={5} className="!mb-0">板块</Title>
                  <Text type="secondary" className="text-xs">同步通达信板块概念并聚合</Text>
                </div>
              </div>
              <Button size="small" onClick={(e) => { e.stopPropagation(); setManageDialog({ open: true, category: 'sector', title: '管理板块' }) }}>
                管理
              </Button>
            </div>
            <Space direction="vertical" className="w-full">
              <Button
                block
                icon={<SyncOutlined />}
                onClick={(e) => { e.stopPropagation(); handleSyncSectors() }}
                loading={activeTasks.sectors || cancelling.sectors}
                disabled={activeTasks.sectors || cancelling.sectors}
                className="rounded-lg font-bold"
              >
                同步数据
              </Button>
              <Button
                block
                icon={<CalculatorOutlined />}
                onClick={(e) => { e.stopPropagation(); handleCalculateSectorRPS() }}
                loading={activeTasks.sector_rps || cancelling.sector_rps}
                disabled={activeTasks.sectors || activeTasks.sector_rps || cancelling.sectors || cancelling.sector_rps}
                className="rounded-lg font-bold !border-purple-500 !text-purple-600 hover:!bg-purple-50"
              >
                计算 RPS
              </Button>
              <Button
                block
                icon={<SwapOutlined />}
                onClick={(e) => { e.stopPropagation(); handleCompare('sector') }}
                className="rounded-lg font-bold !border-orange-500 !text-orange-600 hover:!bg-orange-50"
              >
                对比数据
              </Button>
            </Space>
          </Card>
        </div>

        {syncTimeMsg && <Text type="warning" className="text-sm">{syncTimeMsg}</Text>}

        {/* 任务进度 */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <TaskProgress type="indices" title="指数数据" />
          <TaskProgress type="daily" title="个股日线" />
          <TaskProgress type="sectors" title="板块数据" />
          <TaskProgress type="rps" title="个股 RPS" />
          <TaskProgress type="sector_rps" title="板块 RPS" />
          <TaskProgress type="index_pe" title="指数 PE" />
          <TaskProgress type="precompute_base" title="基础数据" />
        </div>
      </div>

      {/* 管理对话框 */}
      <ManagementDialog
        open={manageDialog.open}
        onClose={() => setManageDialog({ open: false, category: '', title: '' })}
        category={manageDialog.category}
        title={manageDialog.title}
        fetchData={
          manageDialog.category === 'index' ? factorApi.getIndices :
          manageDialog.category === 'stock' ? factorApi.getSectors :
          factorApi.getSectors
        }
      />

      {/* 对比数据弹窗 */}
      <Modal
        title={compareModal.type === 'stock' ? '个股对比' : '板块对比'}
        open={compareModal.open}
        onCancel={handleCloseCompareModal}
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
    </ConfigProvider>
  )
}

export default Settings
