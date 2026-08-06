import React, { useState, useEffect, useRef } from 'react'
import { ConfigProvider, Card, Button, Space, Typography, Select, message, notification } from 'antd'
import {
  DatabaseOutlined,
  SyncOutlined,
  SettingOutlined,
  HistoryOutlined,
  CheckCircleOutlined,
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
import { useTaskPolling } from '../hooks/useTaskPolling'
import ManagementDialog from '../components/ManagementDialog'
import DeepSeekConfigCard from '../components/settings/DeepSeekConfigCard'
import ClearTaskCard from '../components/settings/ClearTaskCard'
import CompareDataModal from '../components/settings/CompareDataModal'
import EntityCard from '../components/settings/EntityCard'

const { Title, Text } = Typography
dayjs.locale('zh-cn')

const taskNames = {
  indices: '同步指数',
  daily: '同步个股',
  sectors: '同步板块',
  rps: '计算个股RPS',
  sector_rps: '计算板块RPS',
  index_pe: '更新PE',
  precompute_base: '预计算基础数据',
}

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
  const [taskIds, setTaskIds] = useState({})

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

  // 任务轮询子组件
  function TaskItem({ type, taskId }) {
    useTaskPolling(taskId, {
      interval: 2000,
      onProgress: (status) => {
        const key = `settings-${type}`
        const steps = status.steps || []
        const step = steps[status.current_step ?? 0]
        if (status.status === 'running' || status.status === 'pending') {
          const stepDesc = step ? `${step.name}(${step.completed_count || 0}/${step.total_count || 1})` : (status.current_stock_name || '处理中...')
          notification.info({ key, message: `${status.name || taskNames[type]}(${status.current_step ?? 0}/${steps.length})`, description: stepDesc, duration: 0 })
        }
      },
      onComplete: (status) => {
        const key = `settings-${type}`
        notification.success({ key, message: `${status.name || taskNames[type]}完成`, description: status.message || '完成', duration: 4 })
        setActiveTasks(prev => { const next = { ...prev }; delete next[type]; return next })
        setTaskIds(prev => { const next = { ...prev }; delete next[type]; return next })
      },
      onFailed: (status) => {
        const key = `settings-${type}`
        notification.error({ key, message: `${status.name || taskNames[type]}失败`, description: status.error || status.message || '失败', duration: 0 })
        setActiveTasks(prev => { const next = { ...prev }; delete next[type]; return next })
        setTaskIds(prev => { const next = { ...prev }; delete next[type]; return next })
      },
    })
    return null
  }

  // 通用启动任务
  const startTask = async (apiCall, type) => {
    if (activeTasks[type]) return
    setActiveTasks(prev => ({ ...prev, [type]: true }))
    try {
      const res = await apiCall()
      const taskId = res.task_id
      if (taskId) {
        notification.info({
          key: `settings-${type}`,
          message: `${taskNames[type] || type}`,
          description: '启动中...',
          duration: 0,
        })
        setTaskIds(prev => ({ ...prev, [type]: taskId }))
      } else {
        notification.success({
          key: `settings-${type}`,
          message: `${taskNames[type] || type}完成`,
          description: res.message || '完成',
          duration: 4,
        })
        setActiveTasks(prev => { const next = { ...prev }; delete next[type]; return next })
      }
    } catch (e) {
      notification.error({
        key: `settings-${type}`,
        message: `${taskNames[type] || type}启动失败`,
        description: e.response?.data?.detail || '启动失败',
        duration: 0,
      })
      setActiveTasks(prev => { const next = { ...prev }; delete next[type]; return next })
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

  // 关闭弹窗时清除轮询
  const handleCloseCompareModal = () => {
    if (comparePollRef.current) {
      clearInterval(comparePollRef.current)
    }
    setCompareModal({ open: false, type: '', data: null, loading: false })
  }

  const handleImportSuccess = () => {
    setCompareModal(prev => ({
      ...prev,
      data: { ...prev.data, new_count: 0 }
    }))
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
        <DeepSeekConfigCard
          enabled={deepseekTimeLimit}
          onToggle={handleToggleDeepseekTimeLimit}
        />

        {/* 清除任务记录 */}
        <ClearTaskCard
          onClear={async () => {
            const res = await factorApi.clearSyncTasks()
            if (res?.success) {
              message.success(res.message || '清除成功')
            } else {
              throw new Error('清除失败')
            }
          }}
        />

        {/* 管理指数、个股、板块 */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <EntityCard
            icon={<BarChartOutlined className="text-blue-600 text-xl" />}
            iconBg="#dbeafe"
            title="指数"
            description="同步大盘指数日线数据"
            buttons={[
              { icon: <SyncOutlined />, label: '同步指数', onClick: handleSyncIndices, loading: activeTasks.indices, disabled: activeTasks.indices },
              { icon: <CalculatorOutlined />, label: '计算 PE', onClick: handleSyncIndexPE, loading: activeTasks.index_pe, disabled: activeTasks.index_pe, className: '!border-purple-500 !text-purple-600 hover:!bg-purple-50' },
              { icon: <DatabaseOutlined />, label: '同步基础数据', onClick: handleSyncBaseData, loading: activeTasks.precompute_base, disabled: activeTasks.precompute_base, className: '!border-green-500 !text-green-600 hover:!bg-green-50' },
            ]}
            onManage={() => setManageDialog({ open: true, category: 'index', title: '管理指数' })}
            onCardClick={() => setManageDialog({ open: true, category: 'index', title: '管理指数' })}
          />

          <EntityCard
            icon={<StockOutlined className="text-green-600 text-xl" />}
            iconBg="#dcfce7"
            title="个股"
            description="同步全部 A 股日线数据"
            buttons={[
              { icon: <SyncOutlined />, label: '同步数据', onClick: handleSyncAllDaily, loading: activeTasks.daily, disabled: activeTasks.daily },
              { icon: <CalculatorOutlined />, label: '计算 RPS', onClick: handleCalculateRPS, loading: activeTasks.rps, disabled: activeTasks.daily || activeTasks.rps, className: '!border-purple-500 !text-purple-600 hover:!bg-purple-50' },
              { icon: <SwapOutlined />, label: '对比数据', onClick: () => handleCompare('stock'), className: '!border-orange-500 !text-orange-600 hover:!bg-orange-50' },
            ]}
            onManage={() => setManageDialog({ open: true, category: 'stock', title: '管理个股' })}
            onCardClick={() => setManageDialog({ open: true, category: 'stock', title: '管理个股' })}
          />

          <EntityCard
            icon={<AppstoreOutlined className="text-purple-600 text-xl" />}
            iconBg="#f3e8ff"
            title="板块"
            description="同步通达信板块概念并聚合"
            buttons={[
              { icon: <SyncOutlined />, label: '同步数据', onClick: handleSyncSectors, loading: activeTasks.sectors, disabled: activeTasks.sectors },
              { icon: <CalculatorOutlined />, label: '计算 RPS', onClick: handleCalculateSectorRPS, loading: activeTasks.sector_rps, disabled: activeTasks.sectors || activeTasks.sector_rps, className: '!border-purple-500 !text-purple-600 hover:!bg-purple-50' },
              { icon: <SwapOutlined />, label: '对比数据', onClick: () => handleCompare('sector'), className: '!border-orange-500 !text-orange-600 hover:!bg-orange-50' },
            ]}
            onManage={() => setManageDialog({ open: true, category: 'sector', title: '管理板块' })}
            onCardClick={() => setManageDialog({ open: true, category: 'sector', title: '管理板块' })}
          />
        </div>

        {syncTimeMsg && <Text type="warning" className="text-sm">{syncTimeMsg}</Text>}

        {Object.entries(taskIds).map(([type, taskId]) => (
          <TaskItem key={type} type={type} taskId={taskId} />
        ))}
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

      <CompareDataModal
        compareModal={compareModal}
        onClose={handleCloseCompareModal}
        onImportSuccess={handleImportSuccess}
      />
    </ConfigProvider>
  )
}

export default Settings
