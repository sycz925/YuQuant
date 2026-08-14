import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { Select, Card, Typography, Spin, Button, Space, Segmented } from 'antd'
import {
  SearchOutlined,
  BarChartOutlined,
  CloseCircleOutlined,
  LeftOutlined,
  RightOutlined
} from '@ant-design/icons'
import { stockApi, factorApi, etfApi } from '../api'
import TradingViewChart from '../components/TradingViewChart'

const { Title, Text } = Typography

// 防抖函数
const debounce = (fn, delay) => {
  let timer = null
  return (...args) => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => fn(...args), delay)
  }
}

function StockAnalysis({ initialCode, initialType }) {
  const [marketType, setMarketType] = useState(
    initialType === 'sector' ? 'sector' : initialType === 'etf' ? 'etf' : 'stock'
  )
  const [selectedCode, setSelectedCode] = useState(initialCode || '688279')
  const [allData, setAllData] = useState([]) // 全部数据
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [currentIndex, setCurrentIndex] = useState(0)
  const [loadingMore, setLoadingMore] = useState(false)

  // 搜索相关
  const [searchOptions, setSearchOptions] = useState([])
  const [searching, setSearching] = useState(false)
  const [searchValue, setSearchValue] = useState('')

  // 搜索
  const searchItems = useCallback(async (keyword) => {
    if (!keyword || keyword.length < 1) {
      setSearchOptions([])
      return
    }
    setSearching(true)
    try {
      if (marketType === 'stock') {
        const res = await stockApi.searchStocks(keyword)
        setSearchOptions(res.data || [])
      } else {
        const res = await factorApi.getSectors({ keyword, limit: 20 })
        setSearchOptions(res.items || [])
      }
    } catch (e) {
      console.error('搜索失败:', e)
      setSearchOptions([])
    } finally {
      setSearching(false)
    }
  }, [marketType])

  const debouncedSearch = useMemo(() => debounce(searchItems, 300), [searchItems])

  const handleSearch = (value) => {
    setSearchValue(value)
    debouncedSearch(value)
  }

  const handleSelect = (value) => {
    setSelectedCode(value)
    setSearchValue('')
    setCurrentIndex(0) // 重置索引
  }

  // 切换市场类型时清空搜索和选中
  useEffect(() => {
    setSearchOptions([])
    setSearchValue('')
  }, [marketType])

  // 当选中股票改变时加载数据
  useEffect(() => {
    if (selectedCode) {
      loadInitialData()
    }
  }, [selectedCode])

  const calculateEMA = (data, period, field = 'close') => {
    const result = []
    const k = 2 / (period + 1)
    let ema = null
    data.forEach((d, i) => {
      if (i < period - 1) {
        result.push(null)
      } else {
        ema = ema === null ? d[field] : (d[field] - ema) * k + ema
        result.push(ema)
      }
    })
    return result
  }

  const calculateMACD = (data) => {
    const ema12 = calculateEMA(data, 12)
    const ema26 = calculateEMA(data, 26)
    const dif = data.map((_, i) => (ema12[i] !== null && ema26[i] !== null) ? (ema12[i] - ema26[i]) : null)

    const dea = []
    let ema9 = null
    const k = 2 / (9 + 1)
    dif.forEach((d, i) => {
      if (d === null) {
        dea.push(null)
      } else {
        ema9 = ema9 === null ? d : (d - ema9) * k + ema9
        dea.push(ema9)
      }
    })

    const macd = data.map((_, i) => (dif[i] !== null && dea[i] !== null) ? (dif[i] - dea[i]) * 2 : null)

    return { dif, dea, macd }
  }

  // 初始加载（最近200条）
  const loadingRef = useRef(false)
  const loadInitialData = async () => {
    if (loadingRef.current) return // 防止重复调用
    loadingRef.current = true
    setLoading(true)
    setError('')
    setCurrentIndex(0)
    try {
      let dailyRes
      let rpsMap = {}
      if (marketType === 'stock') {
        // 个股：加载日线 + RPS
        const [stockDaily, rpsRes] = await Promise.all([
          stockApi.getDailyData(selectedCode, undefined, undefined, 200),
          factorApi.getStockRPS(selectedCode, { period: 'day' }).catch(() => ({ data: [] }))
        ])
        dailyRes = stockDaily

        // 构建RPS日期索引
        if (rpsRes && rpsRes.data) {
          rpsRes.data.forEach(item => {
            rpsMap[item.date] = {
              rps_10: item.rps_10,
              rps_20: item.rps_20,
              rps_50: item.rps_50,
              rps_120: item.rps_120,
              rps_250: item.rps_250
            }
          })
        }
      } else if (marketType === 'etf') {
        dailyRes = await etfApi.getDailyData(selectedCode, undefined, undefined, 200)
      } else {
        // 板块：日线已包含 RPS 数据
        dailyRes = await factorApi.getSectorDaily(selectedCode, undefined, undefined, 200)
      }

      let data = dailyRes.data.map(item => {
        if (marketType === 'stock') {
          const rps = rpsMap[item.trade_date] || {}
          return {
            date: item.trade_date,
            open: item.open,
            high: item.high,
            low: item.low,
            close: item.close,
            volume: item.volume,
            ma10: item.ma10,
            ma20: item.ma20,
            ma50: item.ma50,
            ma120: item.ma120,
            vol_ma5: item.vol_ma5,
            vol_ma10: item.vol_ma10,
            vol_ma20: item.vol_ma20,
            vol_ma50: item.vol_ma50,
            rps_10: rps.rps_10,
            rps_20: rps.rps_20,
            rps_50: rps.rps_50,
            rps_120: rps.rps_120,
            rps_250: rps.rps_250
          }
        } else if (marketType === 'etf') {
          return {
            date: item.trade_date,
            open: item.open,
            high: item.high,
            low: item.low,
            close: item.close,
            volume: item.volume,
            ma10: item.ma10,
            ma20: item.ma20,
            ma50: item.ma50,
            ma120: item.ma120,
            vol_ma5: item.vol_ma5,
            vol_ma10: item.vol_ma10,
            vol_ma20: item.vol_ma20,
            vol_ma50: item.vol_ma50,
            rps_10: item.rps_10,
            rps_20: item.rps_20,
            rps_50: item.rps_50,
            rps_120: item.rps_120,
            rps_250: item.rps_250,
          }
        } else {
          return {
            date: item.trade_date,
            open: item.open,
            high: item.high,
            low: item.low,
            close: item.close,
            volume: item.volume,
            vol_ma5: item.vol_ma5,
            vol_ma10: item.vol_ma10,
            vol_ma20: item.vol_ma20,
            vol_ma50: item.vol_ma50,
            rps_10: item.rps_10,
            rps_20: item.rps_20,
            rps_50: item.rps_50,
            rps_120: item.rps_120,
            rps_250: item.rps_250
          }
        }
      })

      setAllData(data)
    } catch (e) {
      console.error('加载日线数据失败:', e)
      setError(e.response?.data?.detail || '加载数据失败，请先同步数据')
      setAllData([])
    } finally {
      setLoading(false)
      loadingRef.current = false
    }
  }

  // 加载更多历史数据（左移时调用）
  const loadMoreData = async () => {
    if (loadingMore || allData.length === 0) return

    setLoadingMore(true)
    try {
      // 获取当前最早日期
      const earliestDate = allData[0]?.date
      if (!earliestDate) return

      // 计算更早的开始日期（往前推1年）
      const year = parseInt(earliestDate.slice(0, 4)) - 1
      const startDate = `${year}${earliestDate.slice(4)}`

      let dailyRes
      let rpsMap = {}
      if (marketType === 'stock') {
        // 个股：加载日线 + RPS
        const [stockDaily, rpsRes] = await Promise.all([
          stockApi.getDailyData(selectedCode, startDate, earliestDate, 200),
          factorApi.getStockRPS(selectedCode, { period: 'day' }).catch(() => ({ data: [] }))
        ])
        dailyRes = stockDaily

        // 构建RPS日期索引
        if (rpsRes && rpsRes.data) {
          rpsRes.data.forEach(item => {
            rpsMap[item.date] = {
              rps_10: item.rps_10,
              rps_20: item.rps_20,
              rps_50: item.rps_50,
              rps_120: item.rps_120,
              rps_250: item.rps_250
            }
          })
        }
      } else if (marketType === 'etf') {
        dailyRes = await etfApi.getDailyData(selectedCode, startDate, earliestDate, 200)
      } else {
        // 板块：日线已包含 RPS 数据
        dailyRes = await factorApi.getSectorDaily(selectedCode, startDate, earliestDate, 200)
      }

      let newData = dailyRes.data.map(item => {
        if (marketType === 'stock') {
          const rps = rpsMap[item.trade_date] || {}
          return {
            date: item.trade_date,
            open: item.open,
            high: item.high,
            low: item.low,
            close: item.close,
            volume: item.volume,
            ma10: item.ma10,
            ma20: item.ma20,
            ma50: item.ma50,
            ma120: item.ma120,
            vol_ma5: item.vol_ma5,
            vol_ma10: item.vol_ma10,
            vol_ma20: item.vol_ma20,
            vol_ma50: item.vol_ma50,
            rps_10: rps.rps_10,
            rps_20: rps.rps_20,
            rps_50: rps.rps_50,
            rps_120: rps.rps_120,
            rps_250: rps.rps_250
          }
        } else if (marketType === 'etf') {
          return {
            date: item.trade_date,
            open: item.open,
            high: item.high,
            low: item.low,
            close: item.close,
            volume: item.volume,
            ma10: item.ma10,
            ma20: item.ma20,
            ma50: item.ma50,
            ma120: item.ma120,
            vol_ma5: item.vol_ma5,
            vol_ma10: item.vol_ma10,
            vol_ma20: item.vol_ma20,
            vol_ma50: item.vol_ma50,
            rps_10: item.rps_10,
            rps_20: item.rps_20,
            rps_50: item.rps_50,
            rps_120: item.rps_120,
            rps_250: item.rps_250,
          }
        } else {
          // 板块：RPS 已在数据中
          return {
            date: item.trade_date,
            open: item.open,
            high: item.high,
            low: item.low,
            close: item.close,
            volume: item.volume,
            vol_ma5: item.vol_ma5,
            vol_ma10: item.vol_ma10,
            vol_ma20: item.vol_ma20,
            vol_ma50: item.vol_ma50,
            rps_10: item.rps_10,
            rps_20: item.rps_20,
            rps_50: item.rps_50,
            rps_120: item.rps_120,
            rps_250: item.rps_250
          }
        }
      })

      // 过滤掉已有的数据
      const existingDates = new Set(allData.map(d => d.date))
      const uniqueNewData = newData.filter(d => !existingDates.has(d.date))

      if (uniqueNewData.length > 0) {
        // 合并数据（新数据在前）
        const mergedData = [...uniqueNewData, ...allData]

        setAllData(mergedData)

        // 更新索引以保持当前显示位置
        setCurrentIndex(prev => prev + uniqueNewData.length)
      }
    } catch (e) {
      console.error('加载更多数据失败:', e)
    } finally {
      setLoadingMore(false)
    }
  }

  // 获取显示的数据
  const displayData = useMemo(() => {
    if (allData.length === 0) return []

    const displayCount = 120
    const startIdx = Math.max(0, allData.length - displayCount - currentIndex)
    const endIdx = Math.max(0, allData.length - currentIndex)
    return allData.slice(startIdx, endIdx)
  }, [allData, currentIndex])

  // 左移（显示更早的数据）
  const handleMoveLeft = useCallback(() => {
    const displayCount = 120
    const maxIndex = allData.length - displayCount

    // 如果接近边界，加载更多数据
    if (currentIndex + 20 >= maxIndex - 50) {
      loadMoreData()
    }

    setCurrentIndex(prev => Math.min(prev + 20, maxIndex))
  }, [allData.length, currentIndex])

  // 右移（显示更新的数据）
  const handleMoveRight = useCallback(() => {
    setCurrentIndex(prev => Math.max(prev - 20, 0))
  }, [])

  return (
    <div className="space-y-3 md:space-y-4">
      {/* 顶部标题和股票选择 - 仅在非搜索页面调用时显示 */}
      {!initialCode && (
        <Card className="rounded-2xl shadow-sm border-gray-100">
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
            <div className="flex items-center space-x-3">
              <div className="p-2 md:p-3 bg-gradient-to-br from-blue-500 to-purple-600 rounded-xl md:rounded-2xl text-white">
                <BarChartOutlined style={{ fontSize: '18px' }} className="md:!text-2xl" />
              </div>
              <div>
                <Title level={5} style={{ margin: 0 }} className="!text-sm md:!text-lg">行情分析</Title>
                <Text type="secondary" className="text-[10px] md:text-xs">
                  {selectedCode || (marketType === 'stock' ? '选择股票开始分析' : '选择板块开始分析')}
                </Text>
              </div>
            </div>

            <div className="flex flex-col md:flex-row md:items-center gap-2 md:space-x-4">
              <Segmented
                options={[
                  { label: '个股', value: 'stock' },
                  { label: '板块', value: 'sector' }
                ]}
                value={marketType}
                onChange={setMarketType}
                size="small"
              />
              <Select
                showSearch
                placeholder={marketType === 'stock' ? '输入代码/名称搜索' : '输入板块名称搜索'}
                className="w-full md:w-64"
                value={selectedCode}
                onChange={handleSelect}
                onSearch={handleSearch}
                filterOption={false}
                loading={searching}
                notFoundContent={searching ? <Spin size="small" /> : <Text type="secondary">输入关键词搜索</Text>}
                suffixIcon={<SearchOutlined />}
                allowClear
                size="small"
              >
                {searchOptions.map(s => (
                  <Select.Option key={s.code} value={s.code}>
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-xs">{s.code}</span>
                      <span className="text-gray-500 ml-2 text-xs">{s.name}</span>
                    </div>
                  </Select.Option>
                ))}
              </Select>

              <Space size="small">
                <Button
                  icon={<LeftOutlined />}
                  onClick={handleMoveLeft}
                  loading={loadingMore}
                  size="small"
                />
                <Button
                  icon={<RightOutlined />}
                  onClick={handleMoveRight}
                  disabled={currentIndex <= 0}
                  size="small"
                />
              </Space>
          </div>
        </div>
      </Card>
      )}

      {/* 图表区域 */}
      <Card className="rounded-2xl shadow-sm border-gray-100 p-0 overflow-hidden">
        {loading ? (
          <div className="flex justify-center items-center h-64 md:h-96">
            <Spin size="large" description="加载数据中..." />
          </div>
        ) : error ? (
          <div className="flex flex-col justify-center items-center h-64 md:h-96">
            <CloseCircleOutlined className="text-red-500 text-3xl md:text-4xl mb-3 md:mb-4" />
            <Text type="danger" className="text-sm md:text-lg">{error}</Text>
            <Button type="primary" onClick={loadInitialData} className="mt-3 md:mt-4" size="small">
              重新加载
            </Button>
          </div>
        ) : displayData.length === 0 ? (
          <div className="flex flex-col justify-center items-center h-64 md:h-96">
            <BarChartOutlined className="text-gray-300 text-4xl md:text-5xl mb-3 md:mb-4" />
            <Text type="secondary" className="text-sm md:text-lg">暂无数据</Text>
            <Text type="secondary" className="text-[10px] md:text-sm">请先在数据管理页面同步该股票的数据</Text>
          </div>
        ) : (
          <TradingViewChart data={displayData} height={window.innerWidth < 768 ? 500 : 800} stockCode={selectedCode} marketType={marketType} />
        )}
      </Card>
    </div>
  )
}

export default StockAnalysis
