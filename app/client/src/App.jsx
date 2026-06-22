import React, { useState, useEffect } from 'react'
import { Routes, Route, Link, useLocation } from 'react-router-dom'
import MarketMonitor from './pages/MarketMonitor'
import StockAnalysis from './pages/StockAnalysis'
import Backtest from './pages/Backtest'
import TestIndexChart from './pages/TestIndexChart'
import Settings from './pages/Settings'
import MarketAnalysis from './pages/MarketAnalysis'
import { healthApi } from './api'

function App() {
  const location = useLocation()
  const [isHealthy, setIsHealthy] = useState(true)

  useEffect(() => {
    checkHealth()
  }, [])

  const checkHealth = async () => {
    try {
      await healthApi.check()
      setIsHealthy(true)
    } catch (e) {
      setIsHealthy(false)
    }
  }

  const navItems = [
    { path: '/', name: '市场监控', icon: '📊' },
    { path: '/market-analysis', name: '市场分析', icon: '🔬' },
    { path: '/analysis', name: '个股分析', icon: '📈' },
    { path: '/backtest', name: '策略回测', icon: '🤖' },
    { path: '/settings', name: '数据管理', icon: '⚙️' }
  ]

  return (
    <div className="min-h-screen bg-gray-50">
      {/* 固定顶部导航栏 */}
      <nav className="fixed top-0 left-0 right-0 bg-gradient-to-r from-blue-600 to-blue-800 text-white shadow-lg z-50">
        <div className="max-w-7xl mx-auto px-4">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center space-x-2">
              <span className="text-2xl">📊</span>
              <span className="text-xl font-bold">A股量化回测系统</span>
            </div>
            <div className="flex items-center space-x-1">
              {navItems.map(item => (
                <Link
                  key={item.path}
                  to={item.path}
                  className={`px-4 py-2 rounded-lg transition-colors flex items-center space-x-1 ${
                    location.pathname === item.path
                      ? 'bg-white/20 text-white'
                      : 'hover:bg-white/10'
                  }`}
                >
                  <span>{item.icon}</span>
                  <span>{item.name}</span>
                </Link>
              ))}
              <div className={`ml-4 flex items-center space-x-1 px-3 py-1 rounded-full ${
                isHealthy ? 'bg-green-500/20' : 'bg-red-500/20'
              }`}>
                <span className={`w-2 h-2 rounded-full ${
                  isHealthy ? 'bg-green-400' : 'bg-red-400'
                }`}></span>
                <span className="text-sm">
                  {isHealthy ? '后端在线' : '后端离线'}
                </span>
              </div>
            </div>
          </div>
        </div>
      </nav>

      {/* 主内容区 - 给顶部导航留出空间 */}
      <main className="max-w-7xl mx-auto px-4 pt-24 pb-8">
        <Routes>
          <Route path="/" element={<MarketMonitor />} />
          <Route path="/market-analysis" element={<MarketAnalysis />} />
          <Route path="/analysis" element={<StockAnalysis />} />
          <Route path="/backtest" element={<Backtest />} />
          <Route path="/test-index" element={<TestIndexChart />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
