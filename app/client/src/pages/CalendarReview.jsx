import React, { useState, useEffect, useMemo, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { message, Modal, notification, DatePicker, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import 'dayjs/locale/zh-cn'
import { toPng } from 'html-to-image'
import dayjs from 'dayjs'
import { calendarApi, taskApi } from '../api'

// 设置 dayjs 中文 locale
dayjs.locale('zh-cn')

// 设计系统：Slate灰 + 股票绿
const DESIGN = {
  colors: {
    primary: '#334155',
    accent: '#059669',
    accentLight: '#d1fae5',
    background: '#F8FAFC',
    foreground: '#0F172A',
    muted: '#F2F3F4',
    border: '#E6E8EA',
    red: '#DC2626',
    redLight: '#fef2f2',
    redBorder: '#fca5a5',
    green: '#059669',
    greenLight: '#f0fdf4',
    greenBorder: '#86efac',
    gray: '#9CA3AF',
    grayLight: '#F3F4F6',
  }
}

// 星期标题（只显示工作日）
const WEEKDAYS = ['周一', '周二', '周三', '周四', '周五']

function CalendarReview({ latestTradeDate }) {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [calendarData, setCalendarData] = useState({})
  const [currentDate, setCurrentDate] = useState(dayjs())
  const [generatingSnapshot, setGeneratingSnapshot] = useState(false)
  const [weekStatus, setWeekStatus] = useState([])
  const [weeklyModalVisible, setWeeklyModalVisible] = useState(false)
  const [weeklySummary, setWeeklySummary] = useState('')
  const [weeklyLoading, setWeeklyLoading] = useState(false)
  const [weeklyMeta, setWeeklyMeta] = useState(null) // { week_index, dates }
  const [weeklyInputData, setWeeklyInputData] = useState('')
  const [weeklyInputVisible, setWeeklyInputVisible] = useState(false)
  const [monthlySummary, setMonthlySummary] = useState('')
  const [monthlyLoading, setMonthlyLoading] = useState(false)
  const [monthlyModalVisible, setMonthlyModalVisible] = useState(false)
  const [monthlyInputData, setMonthlyInputData] = useState('')
  const [monthlyInputVisible, setMonthlyInputVisible] = useState(false)
  const weeklyScreenshotRef = useRef(null)
  const monthlyScreenshotRef = useRef(null)
  const [weeklyScreenshotLoading, setWeeklyScreenshotLoading] = useState(false)
  const [monthlyScreenshotLoading, setMonthlyScreenshotLoading] = useState(false)
  // 月度重算状态
  const [monthlyRecalcRunning, setMonthlyRecalcRunning] = useState(false)
  // AI分析补全状态
  const [monthlyAiRunning, setMonthlyAiRunning] = useState(false)

  useEffect(() => {
    const y = currentDate.year()
    const m = currentDate.month() + 1
    loadCalendarData(y, m)
    loadWeekStatus(y, m)
  }, [currentDate])

  const loadCalendarData = async (year, month) => {
    setLoading(true)
    try {
      const res = await calendarApi.getDailySummary(year, month)
      if (res?.success && res?.data) {
        // 转换为以date为key的对象
        const dataMap = {}
        let prevAmount = null
        
        res.data.forEach(item => {
          // 计算成交额变化百分比（相对前一天）
          let amountPct = 0
          if (prevAmount !== null && prevAmount > 0) {
            amountPct = ((item.total_amount - prevAmount) / prevAmount * 100)
          }
          
          dataMap[item.date] = {
            ...item,
            amount_pct: amountPct,
            market_change_pct: item.market_change_pct || 0,
            is_weekend: !item.is_trading_day
          }
          
          if (item.total_amount > 0) {
            prevAmount = item.total_amount
          }
        })
        setCalendarData(dataMap)
      }
    } catch (e) {
      console.error('加载日历数据失败:', e)
      setCalendarData({})
    } finally {
      setLoading(false)
    }
  }

  const loadWeekStatus = async (year, month) => {
    try {
      const res = await calendarApi.getWeekStatus(year, month)
      if (res?.success && res?.weeks) {
        setWeekStatus(res.weeks)
      }
    } catch (e) {
      console.error('加载周状态失败:', e)
      setWeekStatus([])
    }
  }

  const handleWeekClick = async (week) => {
    setWeeklyMeta({ week_index: week.week_index, dates: week.dates })
    setWeeklyModalVisible(true)
    // 先查缓存
    setWeeklyLoading(true)
    setWeeklySummary('')
    try {
      const y = currentDate.year()
      const m = currentDate.month() + 1
      const res = await calendarApi.getWeeklyCached(y, m, week.week_index)
      if (res?.success && res?.summary) {
        setWeeklySummary(res.summary)
      }
    } catch (e) {
      console.error('查询缓存失败:', e)
    } finally {
      setWeeklyLoading(false)
    }
  }

  const handleMonthlyClick = async () => {
    const y = currentDate.year()
    const m = currentDate.month() + 1
    setMonthlyModalVisible(true)
    setMonthlyLoading(true)
    setMonthlySummary('')
    // 先查缓存
    try {
      const res = await calendarApi.getMonthlyCached(y, m)
      if (res?.success && res?.summary) {
        setMonthlySummary(res.summary)
      }
    } catch (e) {
      console.error('查询月总结缓存失败:', e)
    } finally {
      setMonthlyLoading(false)
    }
  }

  const handleViewMonthlyInput = async () => {
    const y = currentDate.year()
    const m = currentDate.month() + 1
    setMonthlyInputVisible(true)
    setMonthlyInputData('')
    try {
      const res = await calendarApi.getMonthlyInputData(y, m)
      if (res?.success) {
        setMonthlyInputData(res.user_message)
      } else {
        setMonthlyInputData('获取失败')
      }
    } catch (e) {
      setMonthlyInputData('获取失败: ' + (e?.response?.data?.detail || e.message))
    }
  }

  const handleGenerateMonthly = async () => {
    const y = currentDate.year()
    const m = currentDate.month() + 1
    setMonthlyLoading(true)
    setMonthlySummary('')
    try {
      const res = await calendarApi.getMonthlySummary(y, m)
      // 缓存命中，直接显示
      if (res?.is_cached && res?.summary) {
        setMonthlySummary(res.summary)
        setMonthlyLoading(false)
        return
      }
      // 启动了任务，开始轮询
      const taskId = res?.task_id
      if (!taskId) {
        setMonthlySummary('生成失败：未获得任务ID')
        setMonthlyLoading(false)
        return
      }
      const poll = async () => {
        try {
          const task = await calendarApi.getMonthlyTask(taskId)
          if (task?.status === 'completed') {
            // 任务完成，读取缓存
            const cached = await calendarApi.getMonthlyCached(y, m)
            setMonthlySummary(cached?.summary || '生成完成但读取失败')
            setMonthlyLoading(false)
          } else if (task?.status === 'failed') {
            setMonthlySummary(`生成失败: ${task?.error || '未知错误'}`)
            setMonthlyLoading(false)
          } else {
            // 进行中，3秒后重试
            setTimeout(poll, 3000)
          }
        } catch (err) {
          setMonthlySummary('轮询任务状态失败')
          setMonthlyLoading(false)
        }
      }
      poll()
    } catch (e) {
      console.error('启动月总结任务失败:', e)
      const detail = e?.response?.data?.detail || '启动失败'
      setMonthlySummary(`生成失败: ${detail}`)
      setMonthlyLoading(false)
    }
  }

  const handleScreenshot = async (ref, setLoading, filename) => {
    if (!ref.current) {
      message.warning('未找到截图区域')
      return
    }
    setLoading(true)
    try {
      const imageData = await toPng(ref.current, {
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
      link.download = filename
      link.href = url
      link.click()
      URL.revokeObjectURL(url)
      message.success(`截图已保存 (${sizeKB}KB)`)
    } catch (err) {
      console.error('截图失败:', err)
      message.error('截图失败，请重试')
    } finally {
      setLoading(false)
    }
  }

  const handleViewInputData = async () => {
    if (!weeklyMeta) return
    const y = currentDate.year()
    const m = currentDate.month() + 1
    setWeeklyInputVisible(true)
    setWeeklyInputData('')
    try {
      const res = await calendarApi.getWeeklyInputData(y, m, weeklyMeta.week_index)
      if (res?.success) {
        setWeeklyInputData(res.user_message)
      } else {
        setWeeklyInputData('获取失败')
      }
    } catch (e) {
      setWeeklyInputData('获取失败: ' + (e?.response?.data?.detail || e.message))
    }
  }

  const handleGenerateWeekly = async () => {
    if (!weeklyMeta) return
    const y = currentDate.year()
    const m = currentDate.month() + 1
    setWeeklyLoading(true)
    setWeeklySummary('')
    try {
      const res = await calendarApi.getWeeklySummary(y, m, weeklyMeta.week_index)
      // 缓存命中，直接显示
      if (res?.is_cached && res?.summary) {
        setWeeklySummary(res.summary)
        setWeeklyLoading(false)
        return
      }
      // 启动了任务，开始轮询
      const taskId = res?.task_id
      if (!taskId) {
        setWeeklySummary('生成失败：未获得任务ID')
        setWeeklyLoading(false)
        return
      }
      const poll = async () => {
        try {
          const task = await calendarApi.getWeeklyTask(taskId)
          if (task?.status === 'completed') {
            // 任务完成，读取缓存
            const cached = await calendarApi.getWeeklyCached(y, m, weeklyMeta.week_index)
            setWeeklySummary(cached?.summary || '生成完成但读取失败')
            setWeeklyLoading(false)
          } else if (task?.status === 'failed') {
            setWeeklySummary(`生成失败: ${task?.error || '未知错误'}`)
            setWeeklyLoading(false)
          } else {
            // 进行中，3秒后重试
            setTimeout(poll, 3000)
          }
        } catch (err) {
          setWeeklySummary('轮询任务状态失败')
          setWeeklyLoading(false)
        }
      }
      poll()
    } catch (e) {
      console.error('启动周总结任务失败:', e)
      const detail = e?.response?.data?.detail || '启动失败'
      setWeeklySummary(`生成失败: ${detail}`)
      setWeeklyLoading(false)
    }
  }

  // 计算日历网格（只显示工作日）
  const calendarDays = useMemo(() => {
    const year = currentDate.year()
    const month = currentDate.month()
    const firstDay = dayjs(`${year}-${(month + 1).toString().padStart(2, '0')}-01`)
    const daysInMonth = firstDay.daysInMonth()
    
    let startWeekday = firstDay.day()
    if (startWeekday === 0) startWeekday = 7
    
    const days = []
    
    // 填充月初空白（只计算工作日）
    let emptyCount = 0
    for (let i = 1; i < startWeekday; i++) {
      if (i !== 6 && i !== 7) { // 跳过周六周日
        emptyCount++
      }
    }
    for (let i = 0; i < emptyCount; i++) {
      days.push({ day: null, isCurrentMonth: false })
    }
    
    // 添加当月日期（跳过周末）
    for (let day = 1; day <= daysInMonth; day++) {
      const date = dayjs(`${year}-${(month + 1).toString().padStart(2, '0')}-${day.toString().padStart(2, '0')}`)
      const weekday = date.day()
      if (weekday === 0 || weekday === 6) continue // 跳过周末
      
      const dateStr = `${year}${(month + 1).toString().padStart(2, '0')}${day.toString().padStart(2, '0')}`
      days.push({
        day,
        dateStr,
        isCurrentMonth: true,
        isWeekend: false,
      })
    }
    
    // 填充月末空白使每行都是5列
    const remaining = (5 - (days.length % 5)) % 5
    for (let i = 1; i <= remaining; i++) {
      days.push({ day: i, isCurrentMonth: false })
    }
    
    return days
  }, [currentDate])

  const handlePrevMonth = () => {
    setCurrentDate(currentDate.subtract(1, 'month'))
  }

  const handleNextMonth = () => {
    // 限制不能切换到未来月份
    const now = dayjs()
    const nextMonth = currentDate.add(1, 'month')
    // 如果下一个月的年月大于当前年月，则不允许切换
    if (nextMonth.year() > now.year() || (nextMonth.year() === now.year() && nextMonth.month() > now.month())) {
      return
    }
    setCurrentDate(nextMonth)
  }

  const handleGenerateSnapshot = async () => {
    const year = currentDate.year()
    const month = currentDate.month() + 1

    setGeneratingSnapshot(true)
    try {
      const res = await fetch(`/api/calendar/generate-snapshots?year=${year}&month=${month}`, {
        method: 'POST'
      })
      const data = await res.json()
      if (data.success) {
        message.success(`生成 ${year}-${String(month).padStart(2, '0')} 快照完成，共 ${data.count} 天`)
        // 重新加载日历数据
        loadCalendarData(year, month)
      } else {
        message.error(data.detail || '生成快照失败')
      }
    } catch (e) {
      message.error('生成快照失败')
    } finally {
      setGeneratingSnapshot(false)
    }
  }

  // 月度重算：逐日重算RPS+基础数据
  const handleMonthlyRecalc = async () => {
    if (monthlyRecalcRunning) return

    const year = currentDate.year()
    const month = currentDate.month() + 1

    try {
      const res = await calendarApi.recalculateMonth(year, month)
      if (!res?.success) {
        message.warning(res?.message || '无法启动月度重算')
        return
      }

      setMonthlyRecalcRunning(true)

      const key = `monthly-recalc-${year}-${month}`
      if (res.already_running) {
        notification.info({
          message: '月度重算任务正在进行中',
          description: `正在处理中...`,
          duration: 0,
          key,
          closable: false,
        })
      } else {
        notification.info({
          message: `${year}-${String(month).padStart(2, '0')} 月度重算已启动`,
          description: '正在逐日计算RPS和基础数据...',
          duration: 0,
          key,
          closable: false,
        })
      }

      // 轮询进度
      const pollInterval = setInterval(async () => {
        try {
          const status = await calendarApi.getTaskStatus(res.task_id)

          if (status.error) {
            notification.error({
              message: '月度重算失败',
              description: status.error,
              duration: 0,
              key,
              closable: true,
            })
            clearInterval(pollInterval)
            setMonthlyRecalcRunning(false)
            return
          }

          if (status.status === 'completed') {
            notification.success({
              message: `${year}-${String(month).padStart(2, '0')} 月度重算完成`,
              description: status.current_stock_name || '完成',
              duration: 0,
              key,
              closable: true,
            })
            clearInterval(pollInterval)
            setMonthlyRecalcRunning(false)
            loadCalendarData(year, month)
            return
          }

          if (status.status === 'completed' || status.status === 'failed') {
            clearInterval(pollInterval)
            setMonthlyRecalcRunning(false)
            return
          }

          const stepText = status.total_count > 0 ? `[${status.completed_count}/${status.total_count}]` : ''
          notification.info({
            message: `月度重算 ${stepText}`,
            description: status.current_stock_name || '处理中...',
            duration: 0,
            key,
            closable: false,
          })

        } catch (e) {
          console.error('轮询月度重算进度失败:', e)
        }
      }, 3000)

    } catch (e) {
      console.error('启动月度重算失败:', e)
      message.error('启动月度重算失败')
      setMonthlyRecalcRunning(false)
    }
  }

  // AI分析补全：只为没有AI分析的日期生成
  const handleMonthlyAiFill = async () => {
    if (monthlyAiRunning) return

    const year = currentDate.year()
    const month = currentDate.month() + 1

    try {
      const res = await calendarApi.fillAiAnalysis(year, month)
      if (!res?.success) {
        message.warning(res?.message || '无法启动AI分析补全')
        return
      }

      setMonthlyAiRunning(true)

      const key = `monthly-ai-${year}-${month}`
      if (res.already_running) {
        notification.info({
          message: 'AI分析补全任务正在进行中',
          description: `正在处理中...`,
          duration: 0,
          key,
          closable: false,
        })
      } else {
        notification.info({
          message: `${year}-${String(month).padStart(2, '0')} AI分析补全已启动`,
          description: '正在为缺失AI分析的日期生成分析...',
          duration: 0,
          key,
          closable: false,
        })
      }

      // 轮询进度
      const pollInterval = setInterval(async () => {
        try {
          const status = await calendarApi.getTaskStatus(res.task_id)

          if (status.error) {
            notification.error({
              message: 'AI分析补全失败',
              description: status.error,
              duration: 0,
              key,
              closable: true,
            })
            clearInterval(pollInterval)
            setMonthlyAiRunning(false)
            return
          }

          if (status.status === 'completed') {
            notification.success({
              message: `${year}-${String(month).padStart(2, '0')} AI分析补全完成`,
              description: status.current_stock_name || '完成',
              duration: 0,
              key,
              closable: true,
            })
            clearInterval(pollInterval)
            setMonthlyAiRunning(false)
            loadCalendarData(year, month)
            return
          }

          if (status.status === 'completed' || status.status === 'failed') {
            clearInterval(pollInterval)
            setMonthlyAiRunning(false)
            return
          }

          const stepText = status.total_count > 0 ? `[${status.completed_count}/${status.total_count}]` : ''
          notification.info({
            message: `AI分析补全 ${stepText}`,
            description: status.current_stock_name || '处理中...',
            duration: 0,
            key,
            closable: false,
          })

        } catch (e) {
          console.error('轮询AI分析补全进度失败:', e)
        }
      }, 5000)

    } catch (e) {
      console.error('启动AI分析补全失败:', e)
      message.error('启动AI分析补全失败')
      setMonthlyAiRunning(false)
    }
  }

  const handleDateClick = (dateStr) => {
    if (dateStr) {
      navigate(`/review/${dateStr}`)
    }
  }

  const renderCellContent = (item) => {
    if (!item.day || !item.isCurrentMonth) {
      return <div className="h-full"></div>
    }

    const dayData = calendarData[item.dateStr]
    const isToday = dayjs(item.dateStr, 'YYYYMMDD').isSame(dayjs(), 'day')
    const isLatest = latestTradeDate && item.dateStr === latestTradeDate
    
    // 使用后端返回的is_trading_day字段判断非交易日（包括周末和节假日）
    const isNonTradingDay = dayData ? !dayData.is_trading_day : true

    // 非交易日（周末或节假日）
    if (isNonTradingDay) {
      return (
        <div className="h-full p-1 sm:p-1.5 rounded border" 
             style={{background: DESIGN.colors.grayLight, borderColor: DESIGN.colors.border}}>
          <div className="text-[10px] sm:text-[11px] font-medium" 
               style={{color: DESIGN.colors.gray, fontFamily: 'Fira Code'}}>
            {item.day}
          </div>
        </div>
      )
    }

    // 判断数据是否有效（有数据且不是全0）
    const isDataValid = dayData && (dayData.up_count > 0 || dayData.down_count > 0 || dayData.total_amount > 0)

    // 交易日但无数据或数据无效
    if (!isDataValid) {
      return (
        <div className="h-full p-1 sm:p-1.5 rounded border" 
             style={{
               background: isToday ? '#FFFBEB' : 'white', 
               borderColor: isToday ? '#FDE68A' : DESIGN.colors.border
             }}>
          <div className="text-[10px] sm:text-[11px] font-medium" 
               style={{color: DESIGN.colors.foreground, fontFamily: 'Fira Code'}}>
            {item.day}
          </div>
          <div className="flex items-center justify-center mt-1">
            <span className="text-[7px] sm:text-[8px] px-1 py-0.5 rounded" 
                  style={{
                    background: isToday ? '#FEF3C7' : '#F3F4F6',
                    color: isToday ? '#D97706' : '#9CA3AF',
                    fontFamily: 'Fira Sans'
                  }}>
              {isToday ? '待更新' : '无数据'}
            </span>
          </div>
        </div>
      )
    }

    // 交易日数据
    const marketChangePct = dayData.market_change_pct || 0
    let bgStyle = { background: 'white', borderColor: DESIGN.colors.border }
    
    if (marketChangePct >= 2) {
      bgStyle = { background: `linear-gradient(135deg, #fecaca 0%, #fca5a5 100%)`, borderColor: '#f87171' }
    } else if (marketChangePct >= 1) {
      bgStyle = { background: `linear-gradient(135deg, #fee2e2 0%, #fecdd3 100%)`, borderColor: '#fda4af' }
    } else if (marketChangePct >= 0.3) {
      bgStyle = { background: `linear-gradient(135deg, #fff5f5 0%, #ffe4e6 100%)`, borderColor: '#fecdd3' }
    } else if (marketChangePct > -0.3) {
      bgStyle = { background: 'white', borderColor: DESIGN.colors.border }
    } else if (marketChangePct > -1) {
      bgStyle = { background: `linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%)`, borderColor: '#86efac' }
    } else if (marketChangePct > -2) {
      bgStyle = { background: `linear-gradient(135deg, #dcfce7 0%, #bbf7d0 100%)`, borderColor: '#86efac' }
    } else {
      bgStyle = { background: `linear-gradient(135deg, #bbf7d0 0%, #86efac 100%)`, borderColor: '#4ade80' }
    }

    const amount = dayData.total_amount || 0
    const amountPct = dayData.amount_pct || 0

    // 状态标 - is_final=true为盘后，有数据但is_final!=true为盘中
    let statusTag = null
    if (dayData.is_final === true) {
      statusTag = (
        <span className="inline-flex items-center px-1 py-0.5 rounded text-[9px] sm:text-[11px]" 
              style={{background: '#F3F4F6', color: '#6B7280', fontFamily: 'Fira Sans'}}>
          盘后
        </span>
      )
    } else {
      statusTag = (
        <span className="text-[9px] sm:text-[11px]" style={{color: '#94a3b8', fontFamily: 'Fira Sans'}}>
          盘中
        </span>
      )
    }

    return (
      <div 
        className="h-full p-1 sm:p-1.5 md:p-2 rounded cursor-pointer border transition-all duration-200 active:scale-[0.97] sm:hover:shadow-md overflow-hidden"
        style={bgStyle}
        onClick={() => handleDateClick(item.dateStr)}
      >
        {/* ===== 移动端视图 ===== */}
        <div className="md:hidden">
          {/* 第一行：日期 + 仓位区间 + 涨跌幅 */}
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-1 min-w-0">
              <span className="text-[11px] font-bold"
                    style={{
                      fontFamily: 'Fira Code',
                      color: isToday ? DESIGN.colors.accent : DESIGN.colors.foreground,
                    }}>
                {item.day}
              </span>
              {dayData.recommended_position && (
                <span className="text-[9px] px-1 rounded" style={{color: '#6366f1', fontWeight: 600, backgroundColor: '#eef2ff'}}>
                  仓:{dayData.recommended_position}
                </span>
              )}
            </div>
            <span className="text-[11px] font-bold"
                  style={{
                    color: marketChangePct >= 0 ? DESIGN.colors.red : DESIGN.colors.green,
                    fontFamily: 'Fira Code'
                  }}>
              {marketChangePct >= 0 ? '+' : ''}{marketChangePct.toFixed(2)}%
            </span>
          </div>

          {/* 第二行：涨跌数 + 成交额 */}
          <div className="flex items-center justify-between text-[9px] mt-0.5" style={{fontFamily: 'Fira Code'}}>
            <div>
              <span style={{color: DESIGN.colors.red}}>{dayData.up_count || 0}</span>
              <span className="mx-px" style={{color: '#94a3b8'}}>/</span>
              <span style={{color: DESIGN.colors.green}}>{dayData.down_count || 0}</span>
            </div>
            <span style={{color: '#64748b'}}>{amount}亿</span>
          </div>

          {/* 第三行：核心目标板块 */}
          {dayData.core_target_sectors && dayData.core_target_sectors.length > 0 && (
            <div className="text-[9px] mt-0.5 truncate" style={{fontFamily: 'Fira Code', color: '#7c3aed'}}>
              {dayData.core_target_sectors.join('、')}
            </div>
          )}

          {/* 第四行：仓位管理说明 */}
          {(dayData.position_management_commentary || dayData.recommended_position) && (
            <div className="text-[9px] mt-0.5 line-clamp-3" style={{fontFamily: 'Fira Code', color: '#6366f1', fontWeight: 600}}>
              {dayData.position_management_commentary || dayData.recommended_position}
            </div>
          )}
        </div>

        {/* ===== 桌面端视图 ===== */}
        <div className="hidden md:block">
          {/* 第一行：日期 + 涨跌幅 */}
          {/* 第一行：日期 + 仓位区间 + 涨跌幅 */}
          <div className="flex items-center justify-between mb-0.5">
            <div className="flex items-center space-x-1 min-w-0">
              <span className="text-[14px] font-semibold"
                    style={{
                      fontFamily: 'Fira Code',
                      color: isToday ? DESIGN.colors.accent : DESIGN.colors.foreground,
                    }}>
                {item.day}
              </span>
              {dayData.recommended_position && (
                <span className="text-[10px] px-1.5 py-0.5 rounded" style={{color: '#6366f1', fontWeight: 600, backgroundColor: '#eef2ff'}}>
                  仓:{dayData.recommended_position}
                </span>
              )}
            </div>
            <span className="text-[13px] font-bold"
                  style={{
                    color: marketChangePct >= 0 ? DESIGN.colors.red : DESIGN.colors.green,
                    fontFamily: 'Fira Code'
                  }}>
              {marketChangePct >= 0 ? '+' : ''}{marketChangePct.toFixed(2)}%
            </span>
          </div>

          {/* 第二行：涨跌数 + 成交额 */}
          <div className="flex items-center justify-between text-[12px]" style={{fontFamily: 'Fira Code'}}>
            <div className="flex items-center">
              <span style={{color: DESIGN.colors.red}}>{dayData.up_count || 0}</span>
              <span className="mx-0.5" style={{color: '#94a3b8'}}>/</span>
              <span style={{color: DESIGN.colors.green}}>{dayData.down_count || 0}</span>
            </div>
            <div className="flex items-center" style={{color: '#64748b'}}>
              <span>{amount}亿</span>
            </div>
          </div>

          {/* 第三行：核心目标板块 */}
          {dayData.core_target_sectors && dayData.core_target_sectors.length > 0 && (
            <div className="text-[10px] mt-0.5 truncate" style={{fontFamily: 'Fira Code', color: '#7c3aed'}}>
              {dayData.core_target_sectors.join('、')}
            </div>
          )}

          {/* 第四行：仓位管理说明 */}
          {(dayData.position_management_commentary || dayData.recommended_position) && (
            <div className="text-[11px] mt-0.5 line-clamp-3" style={{fontFamily: 'Fira Code', color: '#6366f1', fontWeight: 600}}>
              {dayData.position_management_commentary || dayData.recommended_position}
            </div>
          )}
        </div>
      </div>
    )
  }

  const monthStr = currentDate.format('YYYY年 MM月')

  return (
    <ConfigProvider locale={zhCN}>
      <div className="rounded-2xl p-2 sm:p-4" 
           style={{background: 'white', boxShadow: '0 1px 3px rgba(15, 23, 42, 0.04), 0 1px 2px rgba(15, 23, 42, 0.06)'}}>
        
        {/* 月份切换 */}
        <div className="flex items-center justify-between mb-2 sm:mb-4">
        <button 
          onClick={handlePrevMonth} 
          className="w-9 h-9 sm:w-8 sm:h-8 flex items-center justify-center rounded-lg transition-all active:bg-gray-200 sm:hover:bg-gray-100"
          style={{color: DESIGN.colors.primary}}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M15 18l-6-6 6-6"/>
          </svg>
        </button>
        
        {/* 月份选择器 - 使用 Ant Design DatePicker */}
        <DatePicker
          picker="month"
          value={currentDate}
          onChange={(date) => {
            if (date) {
              setCurrentDate(date)
            }
          }}
          disabledDate={(current) => {
            // 禁用未来月份
            return current && current > dayjs().endOf('month')
          }}
          allowClear={false}
          className="month-picker"
          style={{width: 'auto'}}
          format="YYYY年 MM月"
        />
        
        <button 
          onClick={handleNextMonth} 
          className={`w-9 h-9 sm:w-8 sm:h-8 flex items-center justify-center rounded-lg transition-all ${
            (currentDate.year() > dayjs().year() || (currentDate.year() === dayjs().year() && currentDate.month() >= dayjs().month()))
              ? 'opacity-30 cursor-not-allowed' 
              : 'active:bg-gray-200 sm:hover:bg-gray-100'
          }`}
          style={{color: DESIGN.colors.primary}}
          disabled={currentDate.year() > dayjs().year() || (currentDate.year() === dayjs().year() && currentDate.month() >= dayjs().month())}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 18l6-6-6-6"/>
          </svg>
        </button>
      </div>

      {/* 图例 + 生成快照 + 月度重算 + AI补全 */}
      <div className="flex items-center justify-between mb-2 sm:mb-3">
        <div className="flex items-center space-x-2 sm:space-x-3 text-[9px] sm:text-[10px]" style={{color: '#64748b'}}>
          <div className="flex items-center">
            <div className="w-2 h-2 sm:w-2.5 sm:h-2.5 rounded-sm mr-1" style={{background: '#fecaca', border: '1px solid #f87171'}}></div>
            <span>涨</span>
          </div>
          <div className="flex items-center">
            <div className="w-2 h-2 sm:w-2.5 sm:h-2.5 rounded-sm mr-1" style={{background: '#bbf7d0', border: '1px solid #4ade80'}}></div>
            <span>跌</span>
          </div>
          <div className="flex items-center">
            <div className="w-2 h-2 sm:w-2.5 sm:h-2.5 rounded-sm mr-1" style={{background: DESIGN.colors.grayLight, border: `1px solid ${DESIGN.colors.border}`}}></div>
            <span>非交易日</span>
          </div>
        </div>
        <div className="flex items-center gap-1 sm:gap-1.5">
          <button
            onClick={handleGenerateSnapshot}
            disabled={generatingSnapshot}
            className="px-2 py-1 text-[9px] sm:text-[10px] rounded border transition-all active:bg-gray-100"
            style={{
              background: generatingSnapshot ? '#f3f4f6' : 'white',
              borderColor: generatingSnapshot ? '#d1d5db' : '#e5e7eb',
              color: generatingSnapshot ? '#9ca3af' : '#6366f1',
              cursor: generatingSnapshot ? 'not-allowed' : 'pointer'
            }}
          >
            {generatingSnapshot ? '生成中...' : '生成快照'}
          </button>
          <button
            onClick={handleMonthlyRecalc}
            disabled={monthlyRecalcRunning}
            className="px-2 py-1 text-[9px] sm:text-[10px] rounded border transition-all active:bg-gray-100"
            style={{
              background: monthlyRecalcRunning ? '#f3f4f6' : 'white',
              borderColor: monthlyRecalcRunning ? '#d1d5db' : '#e5e7eb',
              color: monthlyRecalcRunning ? '#9ca3af' : '#059669',
              cursor: monthlyRecalcRunning ? 'not-allowed' : 'pointer'
            }}
          >
            {monthlyRecalcRunning ? '重算中...' : '月度重算'}
          </button>
          <button
            onClick={handleMonthlyAiFill}
            disabled={monthlyAiRunning}
            className="px-2 py-1 text-[9px] sm:text-[10px] rounded border transition-all active:bg-gray-100"
            style={{
              background: monthlyAiRunning ? '#f3f4f6' : 'white',
              borderColor: monthlyAiRunning ? '#d1d5db' : '#e5e7eb',
              color: monthlyAiRunning ? '#9ca3af' : '#d97706',
              cursor: monthlyAiRunning ? 'not-allowed' : 'pointer'
            }}
          >
            {monthlyAiRunning ? '补全中...' : 'AI补全'}
          </button>
        </div>
      </div>

      {/* 星期标题 */}
      <div className="grid grid-cols-5 mb-1 sm:mb-2">
        {WEEKDAYS.map((weekday, index) => (
          <div key={weekday} 
               className="text-center text-[10px] sm:text-[11px] font-semibold py-1"
               style={{
                 color: DESIGN.colors.primary,
                 fontFamily: 'Fira Sans'
               }}>
            {weekday}
          </div>
        ))}
      </div>

      {/* 日历网格 */}
      <div className="grid grid-cols-5 gap-[3px] sm:gap-1">
        {calendarDays.map((item, index) => (
          <div key={index} className="min-h-[80px] sm:h-[120px]">
            {renderCellContent(item)}
          </div>
        ))}
      </div>

      {/* 周AI总结 */}
      {weekStatus.length > 0 && (
        <div className="mt-3 sm:mt-4 pt-3 sm:pt-4" style={{borderTop: `1px solid ${DESIGN.colors.border}`}}>
          <div className="flex items-center mb-2 sm:mb-3">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#6366f1" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mr-1.5">
              <path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2Z"/>
              <path d="M12 6v6l4 2"/>
            </svg>
            <span className="text-[11px] sm:text-xs font-semibold" style={{color: DESIGN.colors.primary, fontFamily: 'Fira Sans'}}>
              AI 周总结
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            {weekStatus.map((week) => {
              const isComplete = week.is_complete
              const hasSummary = week.has_summary
              const dateRange = `${week.dates[0]?.slice(4, 6)}.${week.dates[0]?.slice(6)} - ${week.dates[week.dates.length - 1]?.slice(4, 6)}.${week.dates[week.dates.length - 1]?.slice(6)}`
              return (
                <button
                  key={week.week_index}
                  onClick={() => isComplete && handleWeekClick(week)}
                  disabled={!isComplete}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] sm:text-xs transition-all"
                  style={{
                    background: isComplete ? 'linear-gradient(135deg, #eef2ff 0%, #e0e7ff 100%)' : '#f9fafb',
                    border: `1px solid ${isComplete ? '#c7d2fe' : DESIGN.colors.border}`,
                    color: isComplete ? '#4338ca' : '#9ca3af',
                    cursor: isComplete ? 'pointer' : 'not-allowed',
                    fontFamily: 'Fira Sans',
                    fontWeight: 600,
                  }}
                >
                  <span>第{week.week_index}周</span>
                  <span style={{color: isComplete ? '#6366f1' : '#d1d5db', fontSize: '10px'}}>{dateRange}</span>
                  {isComplete && hasSummary && (
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#059669" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M5 12h14M12 5l7 7-7 7"/>
                    </svg>
                  )}
                  {isComplete && !hasSummary && (
                    <span className="text-[9px]" style={{color: '#fbbf24'}}>待生成</span>
                  )}
                  {!isComplete && (
                    <span className="text-[9px]" style={{color: '#d1d5db'}}>{week.ai_ready_count}/{week.total_days}</span>
                  )}
                </button>
              )
            })}
          </div>
          {/* 月总结按钮 */}
          {(() => {
            // 月总结启用条件：所有周都有周总结（has_summary）
            const allWeeklySummaryDone = weekStatus.length > 0 && weekStatus.every(w => w.has_summary)
            return (
              <div className="mt-2 sm:mt-3">
                <button
                  onClick={() => allWeeklySummaryDone && handleMonthlyClick()}
                  disabled={!allWeeklySummaryDone}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] sm:text-xs transition-all"
                  style={{
                    background: allWeeklySummaryDone ? 'linear-gradient(135deg, #fef3c7 0%, #fde68a 100%)' : '#f9fafb',
                    border: `1px solid ${allWeeklySummaryDone ? '#fbbf24' : DESIGN.colors.border}`,
                    color: allWeeklySummaryDone ? '#92400e' : '#9ca3af',
                    cursor: allWeeklySummaryDone ? 'pointer' : 'not-allowed',
                    fontFamily: 'Fira Sans',
                    fontWeight: 600,
                  }}
                >
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
                    <line x1="16" y1="2" x2="16" y2="6"/>
                    <line x1="8" y1="2" x2="8" y2="6"/>
                    <line x1="3" y1="10" x2="21" y2="10"/>
                  </svg>
                  {currentDate.format('YYYY年MM月')} AI 月总结
                  {!allWeeklySummaryDone && weekStatus.length > 0 && (
                    <span className="text-[9px] ml-1" style={{color: '#d1d5db'}}>
                      ({weekStatus.filter(w => w.has_summary).length}/{weekStatus.length}周)
                    </span>
                  )}
                </button>
              </div>
            )
          })()}
        </div>
      )}

      {/* 周总结对话框 */}
      <Modal
        title={
          <div className="flex items-center gap-2">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#6366f1" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2Z"/>
              <path d="M12 6v6l4 2"/>
            </svg>
            <span style={{fontFamily: 'Fira Sans', fontWeight: 600}}>
              {weeklyMeta ? `第${weeklyMeta.week_index}周 AI 总结` : '周总结'}
            </span>
          </div>
        }
        open={weeklyModalVisible}
        onCancel={() => setWeeklyModalVisible(false)}
        footer={null}
        width={680}
        styles={{body: {maxHeight: '60vh', overflowY: 'auto', padding: '16px 24px'}}}
      >
        {weeklyMeta && (
          <div className="mb-3 text-[11px]" style={{color: '#64748b', fontFamily: 'Fira Code'}}>
            {weeklyMeta.dates.map(d => `${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6)}`).join(' → ')}
          </div>
        )}

        {/* 生成按钮 - 未生成时显示 */}
        {!weeklySummary && !weeklyLoading && (
          <div className="flex flex-col items-center justify-center py-8">
            <button
              onClick={handleGenerateWeekly}
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold transition-all active:scale-95"
              style={{
                background: 'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)',
                color: 'white',
                boxShadow: '0 2px 8px rgba(99, 102, 241, 0.3)',
                fontFamily: 'Fira Sans',
              }}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2Z"/>
                <path d="M12 8v8M8 12h8"/>
              </svg>
              生成周总结
            </button>
            <span className="text-[11px] mt-2" style={{color: '#94a3b8', fontFamily: 'Fira Sans'}}>
              将本周每日AI分析数据发送至 DeepSeek 生成周度报告
            </span>
            <button
              onClick={handleViewInputData}
              className="mt-3 text-[11px] px-3 py-1 rounded border transition-all active:bg-gray-100"
              style={{borderColor: DESIGN.colors.border, color: '#64748b', fontFamily: 'Fira Sans', fontWeight: 600}}
            >
              查看输入数据
            </button>
          </div>
        )}

        {/* 加载中 */}
        {weeklyLoading && (
          <div className="flex flex-col items-center justify-center py-10">
            <div className="animate-spin w-8 h-8 border-2 border-t-transparent rounded-full mb-3" style={{borderColor: '#c7d2fe', borderTopColor: '#6366f1'}}></div>
            <span className="text-xs" style={{color: '#94a3b8', fontFamily: 'Fira Sans'}}>DeepSeek 正在分析本周数据...</span>
          </div>
        )}

        {/* 生成结果 */}
        {weeklySummary && !weeklyLoading && (
          <div>
            <div ref={weeklyScreenshotRef} className="p-3 rounded-lg" style={{background: '#fafbfc'}}>
              <div className="text-[11px] mb-2 font-semibold" style={{color: '#6366f1', fontFamily: 'Fira Sans'}}>
                {weeklyMeta ? `第${weeklyMeta.week_index}周 AI 总结` : ''}
              </div>
              <div
                className="text-[13px] leading-relaxed"
                style={{color: DESIGN.colors.foreground, fontFamily: 'Fira Sans', whiteSpace: 'pre-wrap'}}
                dangerouslySetInnerHTML={{__html: weeklySummary.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')}}
              />
            </div>
            <div className="mt-4 pt-3 flex items-center gap-2" style={{borderTop: `1px solid ${DESIGN.colors.border}`}}>
              <button
                onClick={handleViewInputData}
                className="text-[11px] px-3 py-1 rounded border transition-all active:bg-gray-100"
                style={{borderColor: DESIGN.colors.border, color: '#64748b', fontFamily: 'Fira Sans', fontWeight: 600}}
              >
                查看输入数据
              </button>
              <button
                onClick={() => handleScreenshot(weeklyScreenshotRef, setWeeklyScreenshotLoading, `周总结_${currentDate.format('YYYYMM')}_第${weeklyMeta?.week_index}周.jpg`)}
                disabled={weeklyScreenshotLoading}
                className="text-[11px] px-3 py-1 rounded border transition-all active:bg-gray-100"
                style={{
                  borderColor: '#c7d2fe',
                  color: weeklyScreenshotLoading ? '#9ca3af' : '#6366f1',
                  fontFamily: 'Fira Sans',
                  fontWeight: 600,
                  cursor: weeklyScreenshotLoading ? 'not-allowed' : 'pointer',
                }}
              >
                {weeklyScreenshotLoading ? '截图中...' : '截图'}
              </button>
            </div>
          </div>
        )}
      </Modal>

      {/* 输入数据查看对话框 */}
      <Modal
        title={
          <div className="flex items-center gap-2">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#64748b" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/>
              <path d="M14 2v6h6M16 13H8M16 17H8M10 9H8"/>
            </svg>
            <span style={{fontFamily: 'Fira Sans', fontWeight: 600}}>
              DeepSeek 输入数据
            </span>
          </div>
        }
        open={weeklyInputVisible}
        onCancel={() => setWeeklyInputVisible(false)}
        footer={null}
        width={680}
        styles={{body: {maxHeight: '65vh', overflowY: 'auto', padding: '16px 24px'}}}
      >
        {weeklyInputData ? (
          <pre className="text-[12px] leading-relaxed whitespace-pre-wrap" style={{color: DESIGN.colors.foreground, fontFamily: 'Fira Code', background: '#f8fafc', padding: '12px', borderRadius: '8px', border: `1px solid ${DESIGN.colors.border}`}}>
            {weeklyInputData}
          </pre>
        ) : (
          <div className="flex items-center justify-center py-8">
            <span className="text-xs" style={{color: '#94a3b8'}}>加载中...</span>
          </div>
        )}
      </Modal>

      {/* 月总结对话框 */}
      <Modal
        title={
          <div className="flex items-center gap-2">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#d97706" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
              <line x1="16" y1="2" x2="16" y2="6"/>
              <line x1="8" y1="2" x2="8" y2="6"/>
              <line x1="3" y1="10" x2="21" y2="10"/>
            </svg>
            <span style={{fontFamily: 'Fira Sans', fontWeight: 600}}>
              {currentDate.format('YYYY年MM月')} AI 月总结
            </span>
          </div>
        }
        open={monthlyModalVisible}
        onCancel={() => setMonthlyModalVisible(false)}
        footer={null}
        width={720}
        styles={{body: {maxHeight: '65vh', overflowY: 'auto', padding: '16px 24px'}}}
      >
        {/* 生成按钮 - 未生成时显示 */}
        {!monthlySummary && !monthlyLoading && (
          <div className="flex flex-col items-center justify-center py-8">
            <button
              onClick={handleGenerateMonthly}
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold transition-all active:scale-95"
              style={{
                background: 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)',
                color: 'white',
                boxShadow: '0 2px 8px rgba(245, 158, 11, 0.3)',
                fontFamily: 'Fira Sans',
              }}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2Z"/>
                <path d="M12 8v8M8 12h8"/>
              </svg>
              生成月总结
            </button>
            <span className="text-[11px] mt-2" style={{color: '#94a3b8', fontFamily: 'Fira Sans'}}>
              将本月所有周AI总结发送至 DeepSeek 生成月度报告
            </span>
            <button
              onClick={handleViewMonthlyInput}
              className="mt-3 text-[11px] px-3 py-1 rounded border transition-all active:bg-gray-100"
              style={{borderColor: DESIGN.colors.border, color: '#64748b', fontFamily: 'Fira Sans', fontWeight: 600}}
            >
              查看输入数据
            </button>
          </div>
        )}

        {/* 加载中 */}
        {monthlyLoading && (
          <div className="flex flex-col items-center justify-center py-10">
            <div className="animate-spin w-8 h-8 border-2 border-t-transparent rounded-full mb-3" style={{borderColor: '#fde68a', borderTopColor: '#d97706'}}></div>
            <span className="text-xs" style={{color: '#94a3b8', fontFamily: 'Fira Sans'}}>DeepSeek 正在分析本月数据...</span>
          </div>
        )}

        {/* 生成结果 */}
        {monthlySummary && !monthlyLoading && (
          <div>
            <div ref={monthlyScreenshotRef} className="p-3 rounded-lg" style={{background: '#fafbfc'}}>
              <div className="text-[11px] mb-2 font-semibold" style={{color: '#d97706', fontFamily: 'Fira Sans'}}>
                {currentDate.format('YYYY年MM月')} AI 月总结
              </div>
              <div
                className="text-[13px] leading-relaxed"
                style={{color: DESIGN.colors.foreground, fontFamily: 'Fira Sans', whiteSpace: 'pre-wrap'}}
                dangerouslySetInnerHTML={{__html: monthlySummary.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')}}
              />
            </div>
            <div className="mt-4 pt-3 flex items-center gap-2" style={{borderTop: `1px solid ${DESIGN.colors.border}`}}>
              <button
                onClick={handleViewMonthlyInput}
                className="text-[11px] px-3 py-1 rounded border transition-all active:bg-gray-100"
                style={{borderColor: DESIGN.colors.border, color: '#64748b', fontFamily: 'Fira Sans', fontWeight: 600}}
              >
                查看输入数据
              </button>
              <button
                onClick={() => handleScreenshot(monthlyScreenshotRef, setMonthlyScreenshotLoading, `月总结_${currentDate.format('YYYYMM')}.jpg`)}
                disabled={monthlyScreenshotLoading}
                className="text-[11px] px-3 py-1 rounded border transition-all active:bg-gray-100"
                style={{
                  borderColor: '#fde68a',
                  color: monthlyScreenshotLoading ? '#9ca3af' : '#d97706',
                  fontFamily: 'Fira Sans',
                  fontWeight: 600,
                  cursor: monthlyScreenshotLoading ? 'not-allowed' : 'pointer',
                }}
              >
                {monthlyScreenshotLoading ? '截图中...' : '截图'}
              </button>
            </div>
          </div>
        )}
      </Modal>

      {/* 月总结输入数据查看对话框 */}
      <Modal
        title={
          <div className="flex items-center gap-2">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#64748b" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/>
              <path d="M14 2v6h6M16 13H8M16 17H8M10 9H8"/>
            </svg>
            <span style={{fontFamily: 'Fira Sans', fontWeight: 600}}>
              DeepSeek 月总结输入数据
            </span>
          </div>
        }
        open={monthlyInputVisible}
        onCancel={() => setMonthlyInputVisible(false)}
        footer={null}
        width={720}
        styles={{body: {maxHeight: '65vh', overflowY: 'auto', padding: '16px 24px'}}}
      >
        {monthlyInputData ? (
          <pre className="text-[12px] leading-relaxed whitespace-pre-wrap" style={{color: DESIGN.colors.foreground, fontFamily: 'Fira Code', background: '#f8fafc', padding: '12px', borderRadius: '8px', border: `1px solid ${DESIGN.colors.border}`}}>
            {monthlyInputData}
          </pre>
        ) : (
          <div className="flex items-center justify-center py-8">
            <span className="text-xs" style={{color: '#94a3b8'}}>加载中...</span>
          </div>
        )}
      </Modal>
      </div>
    </ConfigProvider>
  )
}

export default CalendarReview
