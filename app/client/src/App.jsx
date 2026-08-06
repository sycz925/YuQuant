import React, { useState, useEffect, useCallback, useRef } from 'react'
import { Routes, Route, Link, useLocation, useNavigate } from 'react-router-dom'
import { Button, Tag, Tooltip, notification } from 'antd'
import { SearchOutlined, SyncOutlined, HomeOutlined, BarChartOutlined, SettingOutlined, FundOutlined, AlertOutlined, StarOutlined } from '@ant-design/icons'
import CalendarReview from './pages/CalendarReview'
import ReviewDetail from './pages/ReviewDetail'
import StockAnalysis from './pages/StockAnalysis'
import SearchPage from './pages/SearchPage'
import TestIndexChart from './pages/TestIndexChart'
import Settings from './pages/Settings'
import MarketAnalysis from './pages/MarketAnalysis'
import MarketMonitor from './pages/MarketMonitor'
import ETFPage from './pages/ETFPage'
import ETFAlertPage from './pages/ETFAlertPage'
import WatchlistPage from './pages/WatchlistPage'
import SectorDetail from './pages/SectorDetail'
import ErrorBoundary from './components/ErrorBoundary'
import { healthApi, oneClickUpdateApi, alertApi } from './api'
import useOneClickUpdate from './hooks/useOneClickUpdate'

function App() {
  const location = useLocation()
  const navigate = useNavigate()
  const [isHealthy, setIsHealthy] = useState(false)

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

  const { isRunning: oneClickRunning, start: handleOneClickUpdate } = useOneClickUpdate({
    onComplete: () => checkHealth()
  })

  // ---- ETF预警轮询 ----
  const [lastAlertCheck, setLastAlertCheck] = useState(null)
  const unreadCountRef = useRef(0)

  useEffect(() => {
    const checkAlerts = async () => {
      try {
        const params = {}
        if (lastAlertCheck) params.since = lastAlertCheck
        const res = await alertApi.getRecent(params)
        const items = res || []
        if (items.length > 0) {
          unreadCountRef.current += items.length
          const recent = items.slice(0, 3)
          const desc = recent.map(r => r.reason).join('\n')
          const more = items.length > 3 ? `\n...还有${items.length - 3}条` : ''
          notification.warning({
            message: `ETF下轨击穿预警 (${items.length}条)`,
            description: desc + more,
            duration: 8,
            onClick: () => { navigate('/etf/alerts'); notification.destroy() },
            style: { cursor: 'pointer' },
          })
        }
        setLastAlertCheck(new Date().toISOString())
      } catch (e) { /* 静默 */ }
    }
    const timer = setInterval(checkAlerts, 30000)
    return () => clearInterval(timer)
  }, [lastAlertCheck])

  return (
    <div className="min-h-screen bg-gray-50">
      {/* 固定顶部导航栏 */}
      <nav className="fixed top-0 left-0 right-0 bg-gradient-to-r from-blue-600 to-blue-800 text-white shadow-lg z-50">
        <div className="max-w-7xl mx-auto px-3 md:px-4">
          <div className="flex items-center justify-between h-12 sm:h-14 md:h-16">
            {/* 左侧：Logo + 导航 */}
            <div className="flex items-center space-x-2">
              <Link to="/" className="flex items-center space-x-1.5 sm:space-x-2 hover:opacity-80 transition-opacity">
                <span className="text-lg sm:text-xl md:text-2xl">📊</span>
                <span className="text-base sm:text-lg md:text-xl font-bold">A股量化</span>
              </Link>
              <Link to="/etf" className="flex items-center space-x-1 px-2 py-0.5 rounded text-xs sm:text-sm text-white/70 hover:text-white hover:bg-white/10 transition-colors ml-1">
                <FundOutlined />
                <span>ETF</span>
              </Link>
              <Link to="/watchlist" className="flex items-center space-x-1 px-2 py-0.5 rounded text-xs sm:text-sm text-white/70 hover:text-white hover:bg-white/10 transition-colors ml-1">
                <StarOutlined />
                <span>关注</span>
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
            <Route path="/etf" element={<ETFPage />} />
            <Route path="/etf/alerts" element={<ETFAlertPage />} />
            <Route path="/watchlist" element={<WatchlistPage />} />
            <Route path="/sector/:code" element={<SectorDetail />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </ErrorBoundary>
      </main>
    </div>
  )
}

export default App
