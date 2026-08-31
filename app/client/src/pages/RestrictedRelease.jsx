import { useState, useEffect } from 'react'
import { Spin, message, notification, Button } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { restrictedReleaseApi } from '../api'
import ReleaseDetailModal from '../components/restricted-release/ReleaseDetailModal'

// 热力图颜色映射
const getColorByValue = (value) => {
  if (value === 0) return 'bg-gray-100'
  if (value < 500) return 'bg-green-200'
  if (value < 2000) return 'bg-yellow-200'
  if (value < 5000) return 'bg-orange-300'
  return 'bg-red-400'
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
    const notificationKey = notification.open({
      message: '同步中...',
      description: `正在同步 ${year} 年解禁数据`,
      duration: 0,
    })
    
    try {
      const result = await restrictedReleaseApi.sync(year)
      notification.success({
        message: '同步成功',
        description: `共同步 ${result.total_count} 条记录`,
        key: notificationKey,
      })
      loadData()
    } catch (err) {
      notification.error({
        message: '同步失败',
        description: err.message || '请稍后重试',
        key: notificationKey,
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

  return (
    <div className="max-w-7xl mx-auto px-4 py-6">
      {/* 标题栏 */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-800">
          {year}年 限售股解禁日历
        </h1>
        <Button
          type="primary"
          icon={<ReloadOutlined />}
          onClick={handleSync}
          loading={syncing}
        >
          同步数据
        </Button>
      </div>

      {/* 年份选择器 */}
      <div className="flex gap-2 mb-6">
        {[year - 1, year, year + 1].map((y) => (
          <Button
            key={y}
            type={y === year ? 'primary' : 'default'}
            onClick={() => setYear(y)}
          >
            {y}年
          </Button>
        ))}
      </div>

      {/* 热力图矩阵 */}
      <Spin spinning={loading}>
        <div className="grid grid-cols-6 gap-4">
          {monthsData.map((item) => (
            <div
              key={item.month}
              className={`${getColorByValue(item.total_value)} 
                p-4 rounded-lg cursor-pointer hover:opacity-80 transition-opacity
                ${item.stock_count === 0 ? 'cursor-not-allowed' : ''}`}
              onClick={() => item.stock_count > 0 && handleMonthClick(item.month)}
            >
              <div className="text-lg font-bold text-gray-800">
                {item.month}月
              </div>
              <div className="text-sm text-gray-600">
                {item.total_value > 0 ? `${item.total_value.toFixed(0)}亿` : '---'}
              </div>
              <div className="text-xs text-gray-500">
                {item.stock_count > 0 ? `${item.stock_count}家` : '0家'}
              </div>
            </div>
          ))}
        </div>
      </Spin>

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
