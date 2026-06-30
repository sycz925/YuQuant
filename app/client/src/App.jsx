import React, { useState, useEffect, useRef } from 'react'
import { Routes, Route, Link, useLocation } from 'react-router-dom'
import { Drawer, Button, Menu, message, Modal, Checkbox } from 'antd'
import { MenuOutlined, CameraOutlined } from '@ant-design/icons'
import { toPng } from 'html-to-image'
import MarketMonitor from './pages/MarketMonitor'
import StockAnalysis from './pages/StockAnalysis'
import TestIndexChart from './pages/TestIndexChart'
import Settings from './pages/Settings'
import MarketAnalysis from './pages/MarketAnalysis'
import ErrorBoundary from './components/ErrorBoundary'
import { healthApi } from './api'

export const ScreenshotContext = React.createContext(null)

function App() {
  const location = useLocation()
  const [isHealthy, setIsHealthy] = useState(true)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [screenshotLoading, setScreenshotLoading] = useState(false)
  const screenshotRef = useRef(null)

  // 截图选择弹窗状态
  const [screenshotModalOpen, setScreenshotModalOpen] = useState(false)
  const [screenshotSections, setScreenshotSections] = useState([])
  const [selectedSections, setSelectedSections] = useState([])

  useEffect(() => {
    checkHealth()
    const timer = setInterval(checkHealth, 30000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    setDrawerOpen(false)
  }, [location.pathname])

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
    { path: '/analysis', name: '行情分析', icon: '📈' },
    { path: '/settings', name: '数据管理', icon: '⚙️' }
  ]

  // 点击截图按钮 → 扫描当前页面区块 → 弹窗
  const handleScreenshot = () => {
    if (!screenshotRef.current) {
      message.warning('未找到截图区域')
      return
    }
    const sections = screenshotRef.current.querySelectorAll('[data-section]')
    if (sections.length === 0) {
      message.warning('当前页面没有可选区块')
      return
    }
    const sectionList = Array.from(sections).map(el => ({
      name: el.getAttribute('data-section'),
      el,
    }))
    setScreenshotSections(sectionList)
    setSelectedSections(sectionList.map(s => s.name))
    setScreenshotModalOpen(true)
  }

  // 弹窗确认 → 隐藏未选区块 → 截图 → 恢复
  const handleScreenshotConfirm = async () => {
    if (selectedSections.length === 0) {
      message.warning('请至少选择一个区块')
      return
    }
    setScreenshotModalOpen(false)
    setScreenshotLoading(true)

    const hiddenEls = []
    try {
      // 隐藏未选中的区块
      screenshotSections.forEach(s => {
        if (!selectedSections.includes(s.name)) {
          s.el.style.display = 'none'
          hiddenEls.push(s.el)
        }
      })

      await new Promise(resolve => setTimeout(resolve, 100))

      const element = screenshotRef.current
      const imageData = await toPng(element, {
        pixelRatio: 2,
        backgroundColor: '#ffffff',
        skipAutoScale: true,
        style: { overflow: 'visible' },
      })

      const res = await fetch('/api/screenshot/compress', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image_data: imageData, max_size_kb: 500 }),
      })

      if (!res.ok) throw new Error('压缩失败')

      const blob = await res.blob()
      const sizeKB = Math.round(blob.size / 1024)

      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      const date = new Date().toISOString().slice(0, 10).replace(/-/g, '')
      const pageName = location.pathname === '/' ? '市场监控' :
                       location.pathname === '/market-analysis' ? '市场分析' :
                       location.pathname === '/analysis' ? '行情分析' : '页面'
      link.download = `${pageName}_${date}.jpg`
      link.href = url
      link.click()
      URL.revokeObjectURL(url)

      message.success(`截图已保存 (${sizeKB}KB)`)
    } catch (err) {
      console.error('截图失败:', err)
      message.error('截图失败，请重试')
    } finally {
      // 恢复被隐藏的区块
      hiddenEls.forEach(el => { el.style.display = '' })
      setScreenshotLoading(false)
    }
  }

  const handleSelectAll = (checked) => {
    setSelectedSections(checked ? screenshotSections.map(s => s.name) : [])
  }

  return (
    <ScreenshotContext.Provider value={screenshotRef}>
    <div className="min-h-screen bg-gray-50">
      {/* 固定顶部导航栏 */}
      <nav className="fixed top-0 left-0 right-0 bg-gradient-to-r from-blue-600 to-blue-800 text-white shadow-lg z-50">
        <div className="max-w-7xl mx-auto px-3 md:px-4">
          <div className="flex items-center justify-between h-14 md:h-16">
            <div className="flex items-center space-x-2">
              <span className="text-xl md:text-2xl">📊</span>
              <span className="text-lg md:text-xl font-bold">A股量化系统</span>
              <Button
                type="text"
                icon={<CameraOutlined />}
                onClick={handleScreenshot}
                loading={screenshotLoading}
                className="text-white/80 hover:text-white hover:bg-white/10 ml-2"
                size="small"
              />
            </div>

            {/* 桌面端导航 */}
            <div className="hidden md:flex items-center space-x-1">
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
                  {isHealthy ? '在线' : '离线'}
                </span>
              </div>
            </div>

            {/* 移动端：汉堡菜单 + 状态指示 */}
            <div className="flex md:hidden items-center space-x-3">
              <div className={`flex items-center space-x-1 px-2 py-0.5 rounded-full text-xs ${
                isHealthy ? 'bg-green-500/20' : 'bg-red-500/20'
              }`}>
                <span className={`w-1.5 h-1.5 rounded-full ${
                  isHealthy ? 'bg-green-400' : 'bg-red-400'
                }`}></span>
                <span>{isHealthy ? '在线' : '离线'}</span>
              </div>
              <Button
                type="text"
                icon={<MenuOutlined />}
                onClick={() => setDrawerOpen(true)}
                className="text-white border-white/30 hover:bg-white/10"
              />
            </div>
          </div>
        </div>
      </nav>

      {/* 移动端抽屉导航 */}
      <Drawer
        title={
          <div className="flex items-center space-x-2">
            <span className="text-xl">📊</span>
            <span className="font-bold">A股量化系统</span>
          </div>
        }
        placement="right"
        onClose={() => setDrawerOpen(false)}
        open={drawerOpen}
        size="default"
        className="md:hidden"
      >
        <div className="space-y-2">
          {navItems.map(item => (
            <Link
              key={item.path}
              to={item.path}
              className={`flex items-center space-x-3 px-4 py-3 rounded-lg transition-colors ${
                location.pathname === item.path
                  ? 'bg-blue-50 text-blue-600 font-semibold'
                  : 'hover:bg-gray-50 text-gray-700'
              }`}
            >
              <span className="text-lg">{item.icon}</span>
              <span>{item.name}</span>
            </Link>
          ))}
        </div>
      </Drawer>

      {/* 截图选择弹窗 */}
      <Modal
        title="选择截图区块"
        open={screenshotModalOpen}
        onOk={handleScreenshotConfirm}
        onCancel={() => setScreenshotModalOpen(false)}
        okText="生成截图"
        cancelText="取消"
        destroyOnClose
      >
        <div className="py-2">
          <div className="mb-3 pb-2 border-b border-gray-100">
            <Checkbox
              checked={selectedSections.length === screenshotSections.length}
              indeterminate={selectedSections.length > 0 && selectedSections.length < screenshotSections.length}
              onChange={(e) => handleSelectAll(e.target.checked)}
            >
              全选
            </Checkbox>
          </div>
          <Checkbox.Group
            value={selectedSections}
            onChange={setSelectedSections}
            className="flex flex-col gap-2"
          >
            {screenshotSections.map(s => (
              <Checkbox key={s.name} value={s.name} className="text-sm">
                {s.name}
              </Checkbox>
            ))}
          </Checkbox.Group>
        </div>
      </Modal>

      {/* 主内容区 - 给顶部导航留出空间 */}
      <main className="max-w-7xl mx-auto px-3 md:px-4 pt-16 md:pt-24 pb-6 md:pb-8">
        <ErrorBoundary>
          <div ref={screenshotRef}>
            <Routes>
              <Route path="/" element={<MarketMonitor />} />
              <Route path="/market-analysis" element={<MarketAnalysis />} />
              <Route path="/analysis" element={<StockAnalysis />} />
              <Route path="/test-index" element={<TestIndexChart />} />
              <Route path="/settings" element={<Settings />} />
            </Routes>
          </div>
        </ErrorBoundary>
      </main>
    </div>
    </ScreenshotContext.Provider>
  )
}

export default App
