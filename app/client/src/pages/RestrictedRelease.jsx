import { useState, useEffect } from 'react'
import { Spin, message, notification, Button, Tooltip } from 'antd'
import { ReloadOutlined, CalendarOutlined, SyncOutlined, InfoCircleOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { restrictedReleaseApi } from '../api'
import ReleaseDetailModal from '../components/restricted-release/ReleaseDetailModal'

// 热力图颜色映射 - 使用渐变色阶
const getColorByValue = (value) => {
  if (value === 0) return { bg: 'bg-slate-50', text: 'text-slate-400', border: 'border-slate-100' }
  if (value < 500) return { bg: 'bg-emerald-50', text: 'text-emerald-600', border: 'border-emerald-200' }
  if (value < 1000) return { bg: 'bg-teal-50', text: 'text-teal-600', border: 'border-teal-200' }
  if (value < 2000) return { bg: 'bg-amber-50', text: 'text-amber-600', border: 'border-amber-200' }
  if (value < 3500) return { bg: 'bg-orange-50', text: 'text-orange-600', border: 'border-orange-200' }
  return { bg: 'bg-rose-50', text: 'text-rose-600', border: 'border-rose-200' }
}

// 格式化金额
const formatValue = (value) => {
  if (value === 0) return '---'
  if (value >= 10000) return `${(value / 10000).toFixed(1)}万亿`
  if (value >= 1000) return `${value.toFixed(0)}亿`
  return `${value.toFixed(1)}亿`
}

// 市场板块颜色
const MARKET_COLORS = {
  '上证': '#3B82F6',   // blue
  '深综': '#10B981',   // emerald
  '创业板': '#F59E0B', // amber
  '科创板': '#8B5CF6',  // purple
}

export default function RestrictedRelease() {
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [year, setYear] = useState(dayjs().year())
  const [monthsData, setMonthsData] = useState([])
  const [modalVisible, setModalVisible] = useState(false)
  const [selectedMonth, setSelectedMonth] = useState(null)

  // 加载月度汇总数据
  const loadData = async () => {
    setLoading(true)
    try {
      const data = await restrictedReleaseApi.getSummary(year)
      setMonthsData(data.months || [])
    } catch (err) {
      message.error('加载数据失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [year])

  // 同步数据
  const handleSync = async () => {
    setSyncing(true)
    const notificationKey = `sync-${Date.now()}`
    notification.open({
      message: '同步中...',
      description: `正在同步 ${year} 年解禁数据`,
      duration: 0,
      key: notificationKey,
    })
    
    try {
      const result = await restrictedReleaseApi.sync(year)
      notification.success({
        message: '同步成功',
        description: `共同步 ${result.total_count} 条记录`,
        key: notificationKey,
        duration: 3,
      })
      loadData()
    } catch (err) {
      notification.error({
        message: '同步失败',
        description: err.message || '请稍后重试',
        key: notificationKey,
        duration: 5,
      })
    } finally {
      setSyncing(false)
    }
  }

  // 点击月份查看详情
  const handleMonthClick = (month) => {
    setSelectedMonth(month)
    setModalVisible(true)
  }

  // 计算年度统计
  const yearStats = monthsData.reduce((acc, item) => ({
    totalValue: acc.totalValue + item.total_value,
    totalStocks: acc.totalStocks + item.stock_count,
    activeMonths: acc.activeMonths + (item.stock_count > 0 ? 1 : 0)
  }), { totalValue: 0, totalStocks: 0, activeMonths: 0 })

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* 标题栏 */}
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-2">
            <div className="p-2 bg-blue-100 rounded-lg">
              <CalendarOutlined className="text-xl text-blue-600" />
            </div>
            <h1 className="text-2xl sm:text-3xl font-bold text-slate-800">
              限售股解禁日历
            </h1>
          </div>
          <p className="text-slate-500 ml-12">全市场解禁数据概览，点击月份查看详情</p>
        </div>

        {/* 统计卡片 */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
          <div className="bg-white rounded-xl p-4 shadow-sm border border-slate-100">
            <div className="text-sm text-slate-500 mb-1">年度解禁总额</div>
            <div className="text-2xl font-bold text-slate-800">{formatValue(yearStats.totalValue)}</div>
          </div>
          <div className="bg-white rounded-xl p-4 shadow-sm border border-slate-100">
            <div className="text-sm text-slate-500 mb-1">涉及股票数</div>
            <div className="text-2xl font-bold text-slate-800">{yearStats.totalStocks}</div>
          </div>
          <div className="bg-white rounded-xl p-4 shadow-sm border border-slate-100">
            <div className="text-sm text-slate-500 mb-1">有解禁月份</div>
            <div className="text-2xl font-bold text-slate-800">{yearStats.activeMonths}/12</div>
          </div>
          <div className="bg-white rounded-xl p-4 shadow-sm border border-slate-100">
            <div className="text-sm text-slate-500 mb-1">日均解禁</div>
            <div className="text-2xl font-bold text-slate-800">
              {yearStats.totalValue > 0 ? formatValue(yearStats.totalValue / 365) : '---'}
            </div>
          </div>
        </div>

        {/* 操作栏 */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
          {/* 年份选择器 */}
          <div className="flex items-center gap-2">
            <span className="text-sm text-slate-500 mr-2">选择年份：</span>
            <div className="flex bg-white rounded-lg p-1 shadow-sm border border-slate-200">
              {[year - 1, year, year + 1].map((y) => (
                <button
                  key={y}
                  onClick={() => setYear(y)}
                  className={`px-4 py-2 rounded-md text-sm font-medium transition-all duration-200
                    ${y === year 
                      ? 'bg-blue-600 text-white shadow-sm' 
                      : 'text-slate-600 hover:bg-slate-100'
                    }`}
                >
                  {y}年
                </button>
              ))}
            </div>
          </div>

          {/* 同步按钮 */}
          <Button
            type="primary"
            icon={<SyncOutlined spin={syncing} />}
            onClick={handleSync}
            loading={syncing}
            className="bg-blue-600 hover:bg-blue-700"
          >
            {syncing ? '同步中...' : '同步数据'}
          </Button>
        </div>

        {/* 图例 */}
        <div className="flex flex-col sm:flex-row flex-wrap items-start sm:items-center gap-4 mb-6 p-3 bg-white rounded-lg shadow-sm border border-slate-100">
          <div className="flex flex-wrap items-center gap-4">
            <span className="text-sm font-medium text-slate-600">解禁规模：</span>
            {[
              { label: '无解禁', color: 'bg-slate-50 border-slate-200' },
              { label: '<500亿', color: 'bg-emerald-50 border-emerald-200' },
              { label: '500-1000亿', color: 'bg-teal-50 border-teal-200' },
              { label: '1000-2000亿', color: 'bg-amber-50 border-amber-200' },
              { label: '2000-3500亿', color: 'bg-orange-50 border-orange-200' },
              { label: '>3500亿', color: 'bg-rose-50 border-rose-200' },
            ].map((item, idx) => (
              <div key={idx} className="flex items-center gap-1.5">
                <div className={`w-4 h-4 rounded ${item.color} border`} />
                <span className="text-xs text-slate-500">{item.label}</span>
              </div>
            ))}
          </div>
          <div className="w-px h-4 bg-slate-200 hidden sm:block" />
          <div className="flex flex-wrap items-center gap-4">
            <span className="text-sm font-medium text-slate-600">板块：</span>
            {Object.entries(MARKET_COLORS).map(([market, color]) => (
              <div key={market} className="flex items-center gap-1.5">
                <div className="w-3 h-3 rounded-full" style={{ backgroundColor: color }} />
                <span className="text-xs text-slate-500">{market}</span>
              </div>
            ))}
          </div>
        </div>

        {/* 热力图矩阵 */}
        <Spin spinning={loading}>
          <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 gap-3 sm:gap-4">
            {monthsData.map((item) => {
              const colors = getColorByValue(item.total_value)
              const isClickable = item.stock_count > 0
              const marketRatio = item.market_ratio || {}
              
              return (
                <Tooltip
                  key={item.month}
                  title={
                    <div className="text-center min-w-[120px]">
                      <div className="font-semibold mb-1">{year}年{item.month}月</div>
                      <div className="text-sm">{formatValue(item.total_value)} | {item.stock_count}家</div>
                      <div className="mt-2 text-xs">
                        {Object.entries(marketRatio).map(([market, ratio]) => (
                          ratio > 0 && <div key={market}>{market}: {ratio}%</div>
                        ))}
                      </div>
                    </div>
                  }
                  placement="top"
                >
                  <div
                    className={`
                      ${colors.bg} ${colors.text} ${colors.border}
                      rounded-xl p-4 border
                      ${isClickable 
                        ? 'cursor-pointer hover:shadow-md hover:scale-[1.02] active:scale-[0.98] transition-all duration-200' 
                        : 'cursor-default opacity-60'
                      }
                    `}
                    onClick={() => isClickable && handleMonthClick(item.month)}
                  >
                    <div className="text-base sm:text-lg font-bold mb-1">
                      {item.month}月
                    </div>
                    <div className="text-sm sm:text-base font-semibold">
                      {formatValue(item.total_value)}
                    </div>
                    <div className="text-xs opacity-75 mt-1">
                      {item.stock_count > 0 ? `${item.stock_count}家` : '无解禁'}
                    </div>
                    
                    {/* 板块比例条 */}
                    {item.total_value > 0 && (
                      <div className="mt-2">
                        {/* 进度条 */}
                        <div className="h-1.5 bg-white/50 rounded-full overflow-hidden flex">
                          {['上证', '深综', '创业板', '科创板'].map((market) => {
                            const ratio = marketRatio[market] || 0
                            if (ratio <= 0) return null
                            return (
                              <div
                                key={market}
                                style={{ 
                                  width: `${ratio}%`,
                                  backgroundColor: MARKET_COLORS[market]
                                }}
                                className="h-full"
                              />
                            )
                          })}
                        </div>
                        {/* 图例 */}
                        <div className="flex flex-wrap gap-x-2 gap-y-0.5 mt-1.5">
                          {['上证', '深综', '创业板', '科创板'].map((market) => {
                            const ratio = marketRatio[market] || 0
                            if (ratio <= 0) return null
                            return (
                              <div key={market} className="flex items-center gap-1">
                                <div 
                                  className="w-1.5 h-1.5 rounded-full" 
                                  style={{ backgroundColor: MARKET_COLORS[market] }}
                                />
                                <span className="text-[9px] opacity-80">{market}</span>
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    )}
                  </div>
                </Tooltip>
              )
            })}
          </div>
        </Spin>

        {/* 底部提示 */}
        <div className="mt-6 flex items-center gap-2 text-sm text-slate-400">
          <InfoCircleOutlined />
          <span>点击有色月份查看解禁股票详情，数据来源：东方财富</span>
        </div>
      </div>

      {/* 详情弹窗 */}
      <ReleaseDetailModal
        visible={modalVisible}
        year={year}
        month={selectedMonth}
        onClose={() => {
          setModalVisible(false)
          setSelectedMonth(null)
        }}
      />
    </div>
  )
}
