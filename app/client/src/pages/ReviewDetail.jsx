import React, { useState, useEffect, useMemo, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Button, Tag, DatePicker, message, notification } from 'antd'
import { LeftOutlined, RightOutlined, CalendarOutlined, CameraOutlined, ReloadOutlined } from '@ant-design/icons'
import { toPng } from 'html-to-image'
import dayjs from 'dayjs'
import MarketMonitor from './MarketMonitor'
import MarketAnalysis from './MarketAnalysis'
import { calendarApi, marketReviewApi, oneClickUpdateApi, taskApi } from '../api'

const TABS = [
  { key: 'monitor', label: '市场监控', icon: '📊' },
  { key: 'analysis', label: '市场分析', icon: '🔬' },
]

function ReviewDetail({ latestTradeDate }) {
  const { date } = useParams()
  const navigate = useNavigate()

  const [currentDate, setCurrentDate] = useState(date)
  const [activeTab, setActiveTab] = useState('monitor')
  const [tradingDays, setTradingDays] = useState([])
  const [calendarOpen, setCalendarOpen] = useState(false)
  const [screenshotLoading, setScreenshotLoading] = useState(false)
  const screenshotRef = useRef(null)
  // 市场数据状态：hasData(有数据), isFinal(盘后)
  const [marketStatus, setMarketStatus] = useState({ hasData: false, isFinal: false })
  // 数据重算状态
  const [recalcRunning, setRecalcRunning] = useState(false)

  // 从后端获取交易日列表
  useEffect(() => {
    calendarApi.getTradingDays().then(res => {
      if (res.success && res.data) {
        setTradingDays(res.data)
      }
    }).catch(() => {})
  }, [])

  // 获取市场数据状态
  useEffect(() => {
    if (!currentDate) return
    marketReviewApi.getAiAnalysis(currentDate).then(res => {
      if (res && res.market_phase_diagnosis) {
        // 有AI分析数据，说明market_daily有数据
        setMarketStatus({ hasData: true, isFinal: res.is_final === true })
      } else if (res && res.need_generate) {
        // 有预计算数据但没有AI分析
        setMarketStatus({ hasData: true, isFinal: res.is_final === true })
      } else {
        setMarketStatus({ hasData: false, isFinal: false })
      }
    }).catch(() => {
      setMarketStatus({ hasData: false, isFinal: false })
    })
  }, [currentDate])

  const isLatestDate = useMemo(() => {
    return latestTradeDate && currentDate === latestTradeDate
  }, [currentDate, latestTradeDate])

  // 判断显示状态：盘中实时 / 盘后归档 / 数据待更新
  const getStatusTag = () => {
    if (!marketStatus.hasData) {
      return null // 不显示标签，让页面显示"数据待更新"
    }
    if (marketStatus.isFinal) {
      return <Tag color="success">盘后归档</Tag>
    }
    return <Tag color="processing" icon={<span className="animate-pulse">●</span>}>盘中实时</Tag>
  }

  const getPrevTradingDay = (currentDate) => {
    const sortedDays = [...tradingDays].sort().reverse()
    const idx = sortedDays.indexOf(currentDate)
    if (idx >= 0 && idx < sortedDays.length - 1) {
      return sortedDays[idx + 1]
    }
    return dayjs(currentDate, 'YYYYMMDD').subtract(1, 'day').format('YYYYMMDD')
  }

  const getNextTradingDay = (currentDate) => {
    const sortedDays = [...tradingDays].sort()
    const idx = sortedDays.indexOf(currentDate)
    if (idx >= 0 && idx < sortedDays.length - 1) {
      return sortedDays[idx + 1]
    }
    return dayjs(currentDate, 'YYYYMMDD').add(1, 'day').format('YYYYMMDD')
  }

  const prevDate = getPrevTradingDay(currentDate)
  const nextDate = getNextTradingDay(currentDate)

  const isRightDisabled = isLatestDate || 
    (latestTradeDate && nextDate > latestTradeDate)

  const handleDateChange = (newDate) => {
    setCurrentDate(newDate)
    navigate(`/review/${newDate}`, { replace: true })
  }

  const handleCalendarChange = (date, dateString) => {
    if (dateString) {
      const formatted = dayjs(dateString).format('YYYYMMDD')
      if (tradingDays.includes(formatted)) {
        handleDateChange(formatted)
      }
    }
    setCalendarOpen(false)
  }

  const handleBackToCalendar = () => {
    navigate('/')
  }

  const handleScreenshot = async () => {
    if (!screenshotRef.current) {
      message.warning('未找到截图区域')
      return
    }

    setScreenshotLoading(true)
    try {
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
      const tabName = activeTab === 'monitor' ? '市场监控' : '市场分析'
      link.download = `${tabName}_${currentDate}.jpg`
      link.href = url
      link.click()
      URL.revokeObjectURL(url)

      message.success(`截图已保存 (${sizeKB}KB)`)
    } catch (err) {
      console.error('截图失败:', err)
      message.error('截图失败，请重试')
    } finally {
      setScreenshotLoading(false)
    }
  }

  // 数据重算：只重算当前日期的数据
  const handleRecalculate = async () => {
    if (recalcRunning) return

    try {
      const res = await oneClickUpdateApi.recalculateDate(currentDate)
      if (!res?.success) {
        message.warning(res?.message || '无法启动重算')
        return
      }

      setRecalcRunning(true)

      const key = `recalc-${currentDate}`
      if (res.already_running) {
        // 使用统一任务查询获取当前状态
        const taskStatus = await taskApi.getTaskStatus(res.task_id)
        const stepText = taskStatus.total_count > 0 ? `[${taskStatus.completed_count}/${taskStatus.total_count}]` : ''
        notification.info({
          message: '重算任务正在进行中',
          description: `${stepText} ${taskStatus.current_stock_name || '处理中...'}`,
          duration: 0,
          key,
          closable: false,
        })
      } else {
        notification.info({
          message: `${currentDate} 数据重算已启动`,
          description: '正在计算RPS和基础数据...',
          duration: 0,
          key,
          closable: false,
        })
      }

      // 轮询进度
      const pollInterval = setInterval(async () => {
        try {
          const status = await taskApi.getTaskStatus(res.task_id)

          if (status.error) {
            notification.error({
              message: '重算失败',
              description: status.error,
              duration: 0,
              key,
              closable: true,
            })
            clearInterval(pollInterval)
            setRecalcRunning(false)
            return
          }

          if (status.status === 'completed') {
            notification.success({
              message: `${currentDate} 数据重算完成`,
              description: 'RPS和基础数据已更新',
              duration: 0,
              key,
              closable: true,
            })
            clearInterval(pollInterval)
            setRecalcRunning(false)
            return
          }

          if (status.status !== 'running') {
            clearInterval(pollInterval)
            setRecalcRunning(false)
            return
          }

          // 从 steps 数组计算进度
          const steps = status.steps || []
          const totalSteps = steps.length
          const completedSteps = steps.filter(s => s.status === 'completed').length
          const stepText = totalSteps > 0 ? `[${completedSteps}/${totalSteps}]` : ''
          
          // 获取当前步骤名称
          const currentStep = steps[status.current_step]
          const stepName = currentStep ? currentStep.name : '处理中...'
          
          notification.info({
            message: `数据重算 ${stepText}`,
            description: stepName,
            duration: 0,
            key,
            closable: false,
          })

        } catch (e) {
          console.error('轮询重算进度失败:', e)
        }
      }, 3000)

    } catch (e) {
      console.error('启动重算失败:', e)
      message.error('启动重算失败')
      setRecalcRunning(false)
    }
  }

  const formatDateDisplay = (dateStr) => {
    if (!dateStr) return ''
    return dayjs(dateStr, 'YYYYMMDD').format('YYYY-MM-DD')
  }

  const getDateStatusTag = () => {
    return getStatusTag()
  }

  return (
    <div className="space-y-3 sm:space-y-4">
      {/* 顶部日期切换条 */}
      <div data-section="日期切换" className="bg-white rounded-xl shadow-sm p-2 sm:p-4 sticky top-12 sm:top-16 md:top-20 z-40">
        <div className="flex items-center justify-between">
          <Button 
            type="text" 
            icon={<CalendarOutlined />}
            onClick={handleBackToCalendar}
            className="text-gray-600 hover:text-blue-500 !px-2 sm:!px-4"
            size="small"
          >
            <span className="hidden sm:inline">返回日历</span>
          </Button>

          <div className="flex items-center space-x-1 sm:space-x-4">
            <Button
              type="text"
              icon={<LeftOutlined />}
              onClick={() => handleDateChange(prevDate)}
              className="text-gray-600 hover:text-blue-500 !px-2 sm:!px-4"
              size="small"
            >
              <span className="hidden sm:inline">前一天</span>
            </Button>

            <div className="flex items-center space-x-1 sm:space-x-2 relative">
              <DatePicker
                open={calendarOpen}
                onOpenChange={setCalendarOpen}
                onChange={handleCalendarChange}
                disabledDate={(current) => {
                  if (!current) return false
                  // 禁用周末
                  const dayOfWeek = current.day()
                  if (dayOfWeek === 0 || dayOfWeek === 6) return true
                  // 禁用非交易日
                  const dateStr = current.format('YYYYMMDD')
                  return !tradingDays.includes(dateStr)
                }}
                allowClear={false}
                format="YYYY-MM-DD"
                className="absolute opacity-0 w-0 h-0"
                getPopupContainer={(trigger) => trigger.parentElement}
              />
              <span 
                className="text-sm sm:text-lg font-bold text-gray-800 cursor-pointer hover:text-blue-500 transition-colors"
                onClick={() => setCalendarOpen(true)}
              >
                {formatDateDisplay(currentDate)}
              </span>
              {getDateStatusTag()}
            </div>

            <Button
              type="text"
              icon={<RightOutlined />}
              onClick={() => handleDateChange(nextDate)}
              disabled={isRightDisabled}
              className={`!px-2 sm:!px-4 ${
                isRightDisabled
                  ? 'text-gray-300 cursor-not-allowed'
                  : 'text-gray-600 hover:text-blue-500'
              }`}
              size="small"
            >
              <span className="hidden sm:inline">后一天</span>
            </Button>
          </div>

          {/* 数据重算按钮 */}
          <Button
            type="primary"
            icon={<ReloadOutlined />}
            loading={recalcRunning}
            onClick={handleRecalculate}
            className="!bg-blue-500 hover:!bg-blue-600 !px-2 sm:!px-3"
            size="small"
          >
            <span className="hidden sm:inline">{recalcRunning ? '重算中...' : '重算'}</span>
          </Button>

          <div className="hidden sm:block w-24"></div>
        </div>
      </div>

      {/* Tab切换 - 胶囊样式 */}
      <div className="bg-white rounded-2xl shadow-sm p-1.5 mx-2 sm:mx-4">
        <div className="flex items-center space-x-2">
          <div className="flex flex-1 space-x-1">
            {TABS.map(tab => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={`flex-1 py-2 sm:py-2.5 px-3 sm:px-4 text-xs sm:text-sm font-semibold rounded-xl transition-all duration-200 ${
                  activeTab === tab.key
                    ? 'bg-[#334155] text-white shadow-md'
                    : 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'
                }`}
              >
                <span className="mr-1 sm:mr-1.5">{tab.icon}</span>
                {tab.label}
              </button>
            ))}
          </div>
          <Button
            type="text"
            icon={<CameraOutlined />}
            onClick={handleScreenshot}
            loading={screenshotLoading}
            className="text-gray-500 hover:text-blue-500 !px-2"
            size="small"
          >
            <span className="hidden sm:inline">截图</span>
          </Button>
        </div>
      </div>

      {/* 内容区域 */}
      <div className="px-2 sm:px-4" ref={screenshotRef}>
        {activeTab === 'monitor' && (
          <div data-section="市场监控">
            <MarketMonitor queryDate={currentDate} />
          </div>
        )}
        {activeTab === 'analysis' && (
          <div data-section="市场分析">
            <MarketAnalysis initialDate={currentDate} />
          </div>
        )}
      </div>
    </div>
  )
}

export default ReviewDetail
