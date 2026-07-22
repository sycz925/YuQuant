import React, { useState, useEffect, useCallback } from 'react'
import { Routes, Route, Link, useLocation, useNavigate } from 'react-router-dom'
import { Button, message, Tag, Tooltip, notification } from 'antd'
import { SearchOutlined, SyncOutlined, HomeOutlined, BarChartOutlined, SettingOutlined } from '@ant-design/icons'
import CalendarReview from './pages/CalendarReview'
import ReviewDetail from './pages/ReviewDetail'
import StockAnalysis from './pages/StockAnalysis'
import SearchPage from './pages/SearchPage'
import TestIndexChart from './pages/TestIndexChart'
import Settings from './pages/Settings'
import MarketAnalysis from './pages/MarketAnalysis'
import MarketMonitor from './pages/MarketMonitor'
import ErrorBoundary from './components/ErrorBoundary'
import { healthApi, oneClickUpdateApi, taskApi } from './api'

function App() {
  const location = useLocation()
  const navigate = useNavigate()
  const [isHealthy, setIsHealthy] = useState(false)

  // 一键更新状态
  const [oneClickRunning, setOneClickRunning] = useState(false)
  const [latestTradeDate, setLatestTradeDate] = useState(null)

  // 从后端检查是否允许同步
  const [updateAllowed, setUpdateAllowed] = useState(true)
  const [syncTimeMessage, setSyncTimeMessage] = useState('')

  const checkSyncTime = async () => {
    try {
      const res = await oneClickUpdateApi.checkSyncTime()
      setUpdateAllowed(res.allowed)
      setSyncTimeMessage(res.message || '')
    } catch (e) {
      setUpdateAllowed(false)
      setSyncTimeMessage('检查同步时间失败')
    }
  }

  useEffect(() => {
    checkSyncTime()
    const timer = setInterval(checkSyncTime, 60000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    checkHealth()
    const timer = setInterval(checkHealth, 30000)
    return () => clearInterval(timer)
  }, [])

  const checkHealth = async () => {
    try {
      const res = await healthApi.check()
      setIsHealthy(true)
      if (res?.latest_trade_date) {
        setLatestTradeDate(res.latest_trade_date)
      }
    } catch (e) {
      setIsHealthy(false)
    }
  }

  // 一键更新：使用统一任务接口 + notification显示进度
  const handleOneClickUpdate = async () => {
    if (oneClickRunning) return
    
    // 启动更新
    try {
      const res = await oneClickUpdateApi.start()
      if (!res?.success) {
        message.warning(res?.message || '无法启动更新')
        return
      }
      
      setOneClickRunning(true)
      
      // 如果任务已在运行，直接显示当前进度
      const key = 'update-progress'
      if (res.already_running) {
        // 使用统一任务查询获取当前状态
        const taskStatus = await taskApi.getTaskStatus(res.task_id)
        const stepText = taskStatus.total_count > 0 ? `[${taskStatus.completed_count}/${taskStatus.total_count}]` : ''
        notification.info({
          message: '更新任务正在进行中',
          description: `${stepText} ${taskStatus.current_stock_name || '处理中...'}`,
          duration: 0,
          key,
          closable: false,
        })
      } else {
        // 显示开始通知
        notification.info({
          message: '一键更新已启动',
          description: '正在准备...',
          duration: 0,
          key,
          closable: false,
        })
      }

      // 轮询进度
      const pollInterval = setInterval(async () => {
        try {
          const status = await taskApi.getTaskStatus(res.task_id)

          if (status.status === 'failed') {
            notification.error({
              message: '更新失败',
              description: status.message || '未知错误',
              duration: 0,
              key,
              closable: true,
            })
            clearInterval(pollInterval)
            setOneClickRunning(false)
            return
          }

          if (status.status === 'completed') {
            notification.success({
              message: '一键更新完成',
              description: '数据已同步，RPS/PE已计算，基础数据已更新，请手动刷新页面',
              duration: 0,
              key,
              closable: true,
            })
            clearInterval(pollInterval)
            setOneClickRunning(false)
            checkHealth()
            return
          }

          if (status.status !== 'running') {
            clearInterval(pollInterval)
            setOneClickRunning(false)
            return
          }

          // 更新进度通知（进行中不显示关闭按钮）
          // 从 steps 数组计算进度
          const steps2 = status.steps || []
          const totalSteps2 = steps2.length
          const completedSteps2 = steps2.filter(s => s.status === 'completed').length
          const stepText2 = totalSteps2 > 0 ? `[${completedSteps2}/${totalSteps2}]` : ''
          const currentStep2 = steps2[status.current_step]
          const stepName2 = currentStep2 ? currentStep2.name : '处理中...'
          notification.info({
            message: `一键更新 ${stepText2}`,
            description: stepName2,
            duration: 0,
            key,
            closable: false,
          })
          
        } catch (e) {
          console.error('轮询进度失败:', e)
        }
      }, 3000)
      
    } catch (e) {
      console.error('启动更新失败:', e)
      message.error('启动更新失败')
      setOneClickRunning(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* 固定顶部导航栏 */}
      <nav className="fixed top-0 left-0 right-0 bg-gradient-to-r from-blue-600 to-blue-800 text-white shadow-lg z-50">
        <div className="max-w-7xl mx-auto px-3 md:px-4">
          <div className="flex items-center justify-between h-12 sm:h-14 md:h-16">
            {/* 左侧：Logo */}
            <div className="flex items-center space-x-2">
              <Link to="/" className="flex items-center space-x-1.5 sm:space-x-2 hover:opacity-80 transition-opacity">
                <span className="text-lg sm:text-xl md:text-2xl">📊</span>
                <span className="text-base sm:text-lg md:text-xl font-bold">A股量化</span>
              </Link>
            </div>

            {/* 右侧：搜索 + 设置 + 一键更新 + 状态 */}
            <div className="flex items-center space-x-1 sm:space-x-2 md:space-x-3">
              {/* 搜索图标按钮 */}
              <Button
                type="text"
                icon={<SearchOutlined />}
                onClick={() => navigate('/search')}
                className="text-white/80 hover:text-white hover:bg-white/10"
                size="small"
              />

              {/* 设置按钮 */}
              <Tooltip title="管理指数、个股和板块">
                <Button
                  type="text"
                  icon={<SettingOutlined />}
                  onClick={() => navigate('/settings')}
                  className="text-white/80 hover:text-white hover:bg-white/10"
                  size="small"
                >
                  <span className="hidden md:inline">设置</span>
                </Button>
              </Tooltip>

              {/* 一键更新按钮 */}
              <Tooltip title={
                oneClickRunning ? '更新进行中...' :
                !updateAllowed ? syncTimeMessage || '当前不在同步时间窗口' :
                '同步数据 → 计算RPS/PE → 同步基础数据'
              }>
                <Button
                  type="primary"
                  icon={<SyncOutlined />}
                  loading={oneClickRunning}
                  disabled={!updateAllowed && !oneClickRunning}
                  onClick={handleOneClickUpdate}
                  className={`!bg-white/20 !border-white/30 hover:!bg-white/30 !px-2 sm:!px-4 ${!updateAllowed && !oneClickRunning ? 'opacity-40 cursor-not-allowed' : ''}`}
                  size="small"
                >
                  <span className="hidden md:inline">{oneClickRunning ? '更新中...' : '一键更新'}</span>
                </Button>
              </Tooltip>

              {/* 健康状态 - 移动端只显示圆点 */}
              <div className={`flex items-center space-x-1 px-1.5 sm:px-2 md:px-3 py-0.5 md:py-1 rounded-full text-xs md:text-sm ${
                isHealthy ? 'bg-green-500/20' : 'bg-red-500/20'
              }`}>
                <span className={`w-1.5 md:w-2 h-1.5 md:h-2 rounded-full ${
                  isHealthy ? 'bg-green-400' : 'bg-red-400'
                }`}></span>
                <span className="hidden md:inline">{isHealthy ? '在线' : '离线'}</span>
              </div>
            </div>
          </div>
        </div>
      </nav>

      {/* 主内容区 - 给顶部导航留出空间 */}
      <main className="max-w-7xl mx-auto px-2 sm:px-3 md:px-4 pt-14 sm:pt-16 md:pt-20 pb-6 md:pb-8">
        <ErrorBoundary>
          <Routes>
            <Route path="/" element={<CalendarReview latestTradeDate={latestTradeDate} />} />
            <Route path="/review/:date" element={<ReviewDetail latestTradeDate={latestTradeDate} />} />
            <Route path="/analysis" element={<StockAnalysis />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/market-monitor" element={<MarketMonitor />} />
            <Route path="/market-analysis" element={<MarketAnalysis />} />
            <Route path="/test-index" element={<TestIndexChart />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </ErrorBoundary>
      </main>
    </div>
  )
}

export default App
