import React, { useState, useEffect } from 'react'
import { Spin, Modal, Table, Button, Tooltip } from 'antd'
import { useNavigate } from 'react-router-dom'
import { marketReviewApi } from '../api'
import { DownOutlined, UpOutlined } from '@ant-design/icons'

// 从股票字符串解析当日涨幅，返回颜色class
// 涨幅>5%红、涨幅<-2%绿、其他蓝
const getStockColor = (stock) => {
  if (!stock) return 'bg-blue-50 text-blue-700 border-blue-200'
  // 匹配 "今日+13.3%" 或 "(+20.0%)" 中的最后一个数字
  const match = stock.match(/今日([+-]?\d+\.?\d*)%/) || stock.match(/\(([+-]?\d+\.?\d*)%\)/)
  if (match) {
    const chg = parseFloat(match[1])
    if (chg > 5) return 'bg-red-50 text-red-700 border-red-200'
    if (chg < -2) return 'bg-green-50 text-green-700 border-green-200'
  }
  return 'bg-blue-50 text-blue-700 border-blue-200'
}

// 从股票字符串中提取股票代码
const extractStockCode = (stock) => {
  if (!stock) return null
  // 匹配括号中的数字代码，如 "平安银行(000001)" 或 "平安银行(000001 今日+1.5%)"
  const match = stock.match(/\((\d{6})/)
  return match ? match[1] : null
}

// 从股票字符串中提取股票名称
const extractStockName = (stock) => {
  if (!stock) return null
  // 匹配括号前的名称
  const match = stock.match(/^(.+?)\(/)
  return match ? match[1] : stock
}

const StockTag = ({ stock, className = '' }) => {
  const navigate = useNavigate()
  const stockCode = extractStockCode(stock)
  const stockName = extractStockName(stock)
  
  const handleClick = () => {
    if (stockCode) {
      // 如果有股票代码，直接用代码搜索
      navigate(`/search?code=${stockCode}&name=${encodeURIComponent(stockName || stockCode)}`)
    } else if (stockName) {
      // 如果没有股票代码但有名称，用关键词搜索
      navigate(`/search?keyword=${encodeURIComponent(stockName)}`)
    }
  }
  
  return (
    <span 
      className={`font-mono text-[11px] px-1.5 py-0.5 rounded border mr-1 mb-1 inline-block whitespace-nowrap ${getStockColor(stock)} ${(stockCode || stockName) ? 'cursor-pointer hover:opacity-80' : ''} ${className}`}
      onClick={handleClick}
    >
      {stock}
    </span>
  )
}

function MarketSignals({ date }) {
  const navigate = useNavigate()
  const [signalsData, setSignalsData] = useState(null)
  const [blocksData, setBlocksData] = useState(null)
  const [lpsData, setLpsData] = useState(null)
  const [activeData, setActiveData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [modalVisible, setModalVisible] = useState(false)
  const [modalTitle, setModalTitle] = useState('')
  const [modalData, setModalData] = useState([])
  const [clustersExpanded, setClustersExpanded] = useState(false)

  useEffect(() => {
    loadData()
  }, [date])

  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      const [signalsRes, blocksRes, lpsRes, activeRes] = await Promise.all([
        marketReviewApi.getSignals(date),
        marketReviewApi.getNewHighBlocks(date),
        marketReviewApi.getLowPositionSectors(date),
        marketReviewApi.getActiveSectors(date)
      ])
      setSignalsData(signalsRes)
      setBlocksData(blocksRes)
      setLpsData(lpsRes)
      setActiveData(activeRes)
    } catch (e) {
      console.error('加载市场数据失败:', e)
      setError(e.response?.data?.detail || '加载失败')
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-12 flex flex-col items-center justify-center">
        <Spin size="large" />
        <p className="mt-4 text-sm text-gray-500 font-medium">分析市场状态...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-8 text-center">
        <p className="text-red-500 text-sm">{error}</p>
      </div>
    )
  }

  if (!signalsData || !blocksData) return null

  const { indicators, interpretation, trade_date } = signalsData
  const { industry_clusters } = blocksData || {}
  const lps_sectors = lpsData?.sectors || []
  const active_sectors = activeData?.sectors || []

  const formatDate = (d) => {
    if (!d || d.length !== 8) return d
    return `${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6,8)}`
  }

  const getSignalColor = (signal) => {
    if (signal.includes('极强') || signal.includes('结构性')) return 'text-indigo-600 font-bold'
    if (signal.includes('最强')) return 'text-orange-500 font-bold'
    if (signal.includes('弱势') || signal.includes('偏离')) return 'text-green-600'
    return 'text-gray-600'
  }

  const getIndicatorBar = (value, max) => {
    if (!max) return null
    const pct = Math.min((value / max) * 100, 100)
    let color = 'bg-gray-300'
    if (pct > 70) color = 'bg-green-500'
    else if (pct > 50) color = 'bg-blue-500'
    else if (pct > 30) color = 'bg-amber-500'
    else color = 'bg-red-400'
    return (
      <div className="w-full bg-gray-100 rounded-full h-1.5 mt-1.5 overflow-hidden">
        <div className={`${color} h-full rounded-full transition-all`} style={{ width: `${pct}%` }} />
      </div>
    )
  }

  const getChgColor = (v) => {
    if (v > 0) return 'text-red-500'
    if (v < 0) return 'text-green-500'
    return 'text-gray-400'
  }

  const showStockModal = (title, stocks) => {
    setModalTitle(title)
    setModalData(stocks || [])
    setModalVisible(true)
  }

  const stockColumns = [
    { title: '代码', dataIndex: 'code', key: 'code', width: 80, render: (v) => <span className="font-mono text-xs">{v}</span> },
    { title: '名称', dataIndex: 'name', key: 'name', width: 100 },
    { title: '涨跌幅', dataIndex: 'pct_chg', key: 'pct_chg', width: 80, render: (v) => <span className={`font-mono text-xs ${getChgColor(v)}`}>{v > 0 ? '+' : ''}{v}%</span> },
    { title: '收盘价', dataIndex: 'close', key: 'close', width: 80, render: (v) => <span className="font-mono text-xs">{v?.toFixed(2)}</span> },
  ]

  const renderHighlightedText = (text) => {
    if (!text) return null
    const parts = text.split(/(\d+%|消费电子|光伏|国防军工|锂电池|汽车电子|半导体|芯片|新能源|医疗|白酒|银行)/g)
    return parts.map((part, i) => {
      if (part.match(/\d+%/)) {
        return <span key={i} className="text-amber-700 font-bold">{part}</span>
      }
      if (part.match(/消费电子|光伏|国防军工|锂电池|汽车电子|半导体|芯片|新能源|医疗|白酒|银行/)) {
        return <span key={i} className="text-amber-700 font-bold">{part}</span>
      }
      return <span key={i}>{part}</span>
    })
  }

  // 使用后端生成的综合分析文案
  const combinedInterpretation = interpretation

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
      {/* 标题栏 */}
      <div className="px-3 md:px-6 py-3 md:py-4 border-b border-gray-100 flex items-center justify-between">
        <div className="flex items-center space-x-2 md:space-x-3">
          <div className="w-1 h-4 md:h-5 bg-emerald-500 rounded-full"></div>
          <h2 className="text-xs md:text-base font-black text-gray-900 tracking-tight">A股运行状态与板块效应</h2>
        </div>
        <div className="flex items-center space-x-2 md:space-x-3">
          <span className="text-[10px] md:text-xs text-gray-400 font-mono">{formatDate(trade_date)}</span>
        </div>
      </div>

      {/* 第二部分：板块效应聚类 - 收起展开效果 */}
      {industry_clusters && industry_clusters.length > 0 && (
        <div className="p-3 md:p-6 border-b border-gray-100">
          <div className="flex items-center justify-between mb-2 md:mb-4">
            <div className="flex items-center space-x-1.5 md:space-x-2">
              <div className="w-1 h-3 md:h-4 bg-amber-500 rounded-full"></div>
              <h3 className="text-xs md:text-sm font-bold text-gray-700">新高强力板块</h3>
              <Tooltip title="筛选规则：先筛选RPS10/RPS20/RPS50其中之一>90的板块，再在这些板块中取当日收盘价创历史新高的个股，按行业聚类统计数量，取Top5">
                <span className="text-[10px] md:text-xs text-gray-400 cursor-help">({industry_clusters.length}个)</span>
              </Tooltip>
            </div>
            {industry_clusters.length > 5 && (
              <Button
                type="text"
                size="small"
                onClick={() => setClustersExpanded(!clustersExpanded)}
                className="text-xs text-gray-500 hover:text-amber-600"
              >
                {clustersExpanded ? '收起' : '展开全部'}
                {clustersExpanded ? <UpOutlined className="ml-1" /> : <DownOutlined className="ml-1" />}
              </Button>
            )}
          </div>
          
          {/* 移动端：紧凑卡片列表 */}
          <div className="md:hidden space-y-3">
            {(clustersExpanded ? industry_clusters : industry_clusters.slice(0, 5)).map((item, idx) => {
              const originalIdx = clustersExpanded ? idx : idx
              return (
                <div
                  key={idx}
                  className={`p-3 rounded-xl border ${
                    originalIdx === 0 ? 'bg-amber-50/50 border-amber-200' : 'bg-gray-50/50 border-gray-100'
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center space-x-1.5">
                      {originalIdx === 0 && <span className="text-amber-500 text-xs">👑</span>}
                      <span 
                        className={`text-sm font-bold cursor-pointer hover:underline ${originalIdx === 0 ? 'text-amber-700' : 'text-gray-900'}`}
                        onClick={() => navigate(`/search?keyword=${encodeURIComponent(item.industry)}`)}
                      >
                        {item.industry}
                      </span>
                    </div>
                    <div className="flex items-center space-x-2">
                      <span 
                        className={`text-sm font-mono font-black cursor-pointer ${
                          originalIdx === 0 ? 'text-amber-600' : 'text-gray-900'
                        }`}
                        onClick={() => showStockModal(item.industry + '新高个股', item.stocks)}
                      >
                        {item.count}只
                      </span>
                      <span className={`text-xs font-mono font-bold ${
                        (item.chg_pct || item.chg || 0) > 0 ? 'text-red-500' : (item.chg_pct || item.chg || 0) < 0 ? 'text-green-500' : 'text-gray-500'
                      }`}>
                        {(item.chg_pct || item.chg || 0) > 0 ? '+' : ''}{(item.chg_pct || item.chg || 0)}%
                      </span>
                    </div>
                  </div>
                  <div style={{ lineHeight: '28px' }}>
                    {(item.pioneer || item.representative_stocks || item.representative || []).slice(0, 3).map((stock, si) => (
                      <StockTag key={si} stock={stock} />
                    ))}
                    {(item.main_force || item.core_stocks || item.core || []).slice(0, 2).map((stock, si) => (
                      <StockTag key={`core-${si}`} stock={stock} />
                    ))}
                  </div>
                </div>
              )
            })}
          </div>

          {/* 桌面端：完整表格 */}
          <div className="hidden md:block overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="text-left text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3">板块方向</th>
                  <th className="text-center text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3 w-24">新高个股</th>
                  <th className="text-center text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3 w-24">涨幅</th>
                  <th className="text-left text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3">先锋</th>
                  <th className="text-left text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3">中军</th>
                  <th className="text-left text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3">后排</th>
                </tr>
              </thead>
              <tbody>
                {(clustersExpanded ? industry_clusters : industry_clusters.slice(0, 5)).map((item, idx) => {
                  const originalIdx = clustersExpanded ? idx : idx
                  return (
                    <tr
                      key={idx}
                      className={`border-b border-gray-50 last:border-0 hover:bg-gray-50/50 transition-colors ${
                        originalIdx === 0 ? 'bg-amber-50/30' : ''
                      }`}
                    >
                      <td className="py-3">
                        <div className="flex items-center space-x-2">
                          {originalIdx === 0 && <span className="text-amber-500 text-xs">👑</span>}
                          <span 
                            className={`text-sm font-bold cursor-pointer hover:underline ${originalIdx === 0 ? 'text-amber-700' : 'text-gray-900'}`}
                            onClick={() => navigate(`/search?keyword=${encodeURIComponent(item.industry)}`)}
                          >
                            {item.industry}
                          </span>
                        </div>
                      </td>
                      <td className="py-3 text-center">
                        <span 
                          className={`text-base font-mono font-black cursor-pointer hover:text-indigo-600 transition-colors ${
                            originalIdx === 0 ? 'text-amber-600' : 'text-gray-900'
                          }`}
                          onClick={() => showStockModal(item.industry + '新高个股', item.stocks)}
                        >
                          {item.count}
                        </span>
                        <span className="text-[10px] text-gray-400 ml-0.5">只</span>
                        <div className="text-[10px] text-gray-400 mt-0.5">{item.pct}%</div>
                      </td>
                      <td className="py-3 text-center">
                        <span className={`text-sm font-mono font-bold ${
                          (item.chg_pct || item.chg || 0) > 0 ? 'text-red-500' : (item.chg_pct || item.chg || 0) < 0 ? 'text-green-500' : 'text-gray-500'
                        }`}>
                          {(item.chg_pct || item.chg || 0) > 0 ? '+' : ''}{(item.chg_pct || item.chg || 0)}%
                        </span>
                      </td>
                       <td className="py-3">
                        <div style={{ lineHeight: '24px' }}>
                          {(item.pioneer || item.representative_stocks || item.representative || []).map((stock, si) => (
                            <StockTag key={si} stock={stock} />
                          ))}
                        </div>
                      </td>
                      <td className="py-3">
                        <div style={{ lineHeight: '24px' }}>
                          {(item.main_force || item.core_stocks || item.core || []).map((stock, si) => (
                            <StockTag key={si} stock={stock} />
                          ))}
                        </div>
                      </td>
                      <td className="py-3">
                        <div style={{ lineHeight: '24px' }}>
                          {(item.followers || []).map((stock, si) => (
                            <StockTag key={si} stock={stock} />
                          ))}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 低位潜力板块 */}
      {lps_sectors.length > 0 && (
        <div className="p-3 md:p-6 border-b border-gray-100">
          <div className="flex items-center space-x-1.5 md:space-x-2 mb-2 md:mb-4">
            <div className="w-1 h-3 md:h-4 bg-emerald-500 rounded-full"></div>
            <h3 className="text-xs md:text-sm font-bold text-gray-700">低位潜力板块</h3>
            <Tooltip title="筛选规则：板块涨幅>2% + MA10>MA20 + RPS10>85(短线爆发力) + RPS50<70(长线低位) + 近3天有1天以上≥15%个股创20日新高 + 近5天有4天净新高>-10">
              <span className="text-[10px] md:text-xs text-gray-400 cursor-help">({lps_sectors.length}个)</span>
            </Tooltip>
          </div>

          {/* 桌面端表格 */}
          <div className="hidden md:block overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="text-left text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3">板块方向</th>
                  <th className="text-center text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3 w-24">新高个股</th>
                  <th className="text-center text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3 w-24">涨幅</th>
                  <th className="text-left text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3">先锋</th>
                  <th className="text-left text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3">中军</th>
                  <th className="text-left text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3">后排</th>
                </tr>
              </thead>
              <tbody>
                {lps_sectors.map((item, idx) => (
                  <tr key={idx} className="border-b border-gray-50 last:border-0 hover:bg-gray-50/50 transition-colors">
                    <td className="py-3">
                      <div className="flex items-center space-x-2">
                        <span 
                          className="text-sm font-bold text-gray-900 cursor-pointer hover:underline"
                          onClick={() => navigate(`/search?keyword=${encodeURIComponent(item.name)}`)}
                        >
                          {item.name}
                        </span>
                      </div>
                    </td>
                    <td className="py-3 text-center">
                      <span
                        className="text-base font-mono font-black text-gray-900 cursor-pointer hover:text-indigo-600 transition-colors"
                        onClick={() => showStockModal(item.name + '符合条件近新高个股', item.stocks)}
                      >
                        {item.count}
                      </span>
                      <span className="text-[10px] text-gray-400 ml-0.5">只</span>
                      <div className="text-[10px] text-gray-400 mt-0.5">{item.pct}%</div>
                    </td>
                    <td className="py-3 text-center">
                      <span className={`text-sm font-mono font-bold ${item.chg_pct > 0 ? 'text-red-500' : item.chg_pct < 0 ? 'text-green-500' : 'text-gray-500'}`}>
                        {item.chg_pct > 0 ? '+' : ''}{item.chg_pct}%
                      </span>
                    </td>
                    <td className="py-3">
                      <div style={{ lineHeight: '24px' }}>
                                                  {(item.pioneer || []).map((stock, si) => (
                          <StockTag key={si} stock={stock} />
                        ))}
                      </div>
                    </td>
                    <td className="py-3">
                      <div style={{ lineHeight: '24px' }}>
                        {(item.main_force || []).map((stock, si) => (
                          <StockTag key={si} stock={stock} />
                        ))}
                      </div>
                    </td>
                    <td className="py-3">
                      <div style={{ lineHeight: '24px' }}>
                        {(item.followers || []).map((stock, si) => (
                          <StockTag key={si} stock={stock} />
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* 移动端卡片 */}
          <div className="md:hidden space-y-3">
            {lps_sectors.map((item, idx) => (
              <div key={idx} className="p-3 rounded-xl border bg-emerald-50/50 border-emerald-100">
                <div className="flex items-center justify-between mb-2">
                  <span 
                    className="text-sm font-bold text-gray-900 cursor-pointer hover:underline"
                    onClick={() => navigate(`/search?keyword=${encodeURIComponent(item.name)}`)}
                  >
                    {item.name}
                  </span>
                  <div className="flex items-center space-x-2">
                    <span
                      className="text-sm font-mono font-black text-gray-900 cursor-pointer hover:text-indigo-600 transition-colors"
                      onClick={() => showStockModal(item.name + '符合条件近新高个股', item.stocks)}
                    >
                      {item.count}只
                    </span>
                    <span className={`text-sm font-mono font-bold ${item.chg_pct > 0 ? 'text-red-500' : item.chg_pct < 0 ? 'text-green-500' : 'text-gray-500'}`}>
                      {item.chg_pct > 0 ? '+' : ''}{item.chg_pct}%
                    </span>
                  </div>
                </div>
                <div style={{ lineHeight: '28px' }}>
                  {(item.pioneer || []).slice(0, 3).map((stock, si) => (
                    <StockTag key={si} stock={stock} />
                  ))}
                  {(item.main_force || []).slice(0, 2).map((stock, si) => (
                    <StockTag key={`core-${si}`} stock={stock} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 异动活跃板块 */}
      {active_sectors.length > 0 && (
        <div className="p-3 md:p-6 border-b border-gray-100">
          <div className="flex items-center space-x-1.5 md:space-x-2 mb-2 md:mb-4">
            <div className="w-1 h-3 md:h-4 bg-orange-500 rounded-full"></div>
            <h3 className="text-xs md:text-sm font-bold text-gray-700">异动活跃板块</h3>
            <Tooltip title="筛选规则：板块内流通市值>200亿且涨幅>5%的个股≥10只 + 其中RPS10+20+50>250占比>30% + 板块RPS10+20+50≤250 + 板块当日涨幅>2%">
              <span className="text-[10px] md:text-xs text-gray-400 cursor-help">({active_sectors.length}个)</span>
            </Tooltip>
          </div>

          {/* 桌面端表格 */}
          <div className="hidden md:block overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="text-left text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3">板块方向</th>
                  <th className="text-center text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3 w-24">符合条件</th>
                  <th className="text-center text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3 w-24">涨幅</th>
                  <th className="text-left text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3">先锋</th>
                  <th className="text-left text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3">中军</th>
                  <th className="text-left text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3">后排</th>
                </tr>
              </thead>
              <tbody>
                {active_sectors.map((item, idx) => (
                  <tr key={idx} className="border-b border-gray-50 last:border-0 hover:bg-gray-50/50 transition-colors">
                    <td className="py-3">
                      <div className="flex items-center space-x-2">
                        <span
                          className="text-sm font-bold text-gray-900 cursor-pointer hover:underline"
                          onClick={() => navigate(`/search?keyword=${encodeURIComponent(item.name)}`)}
                        >
                          {item.name}
                        </span>
                      </div>
                    </td>
                    <td className="py-3 text-center">
                      <span
                        className="text-base font-mono font-black text-gray-900 cursor-pointer hover:text-indigo-600 transition-colors"
                        onClick={() => showStockModal(item.name + '符合条件个股', item.stocks)}
                      >
                        {item.count}
                      </span>
                      <span className="text-[10px] text-gray-400 ml-0.5">只</span>
                      <div className="text-[10px] text-gray-400 mt-0.5">{item.pct}%</div>
                    </td>
                    <td className="py-3 text-center">
                      <span className={`text-sm font-mono font-bold ${item.chg_pct > 0 ? 'text-red-500' : item.chg_pct < 0 ? 'text-green-500' : 'text-gray-500'}`}>
                        {item.chg_pct > 0 ? '+' : ''}{item.chg_pct}%
                      </span>
                    </td>
                    <td className="py-3">
                      <div style={{ lineHeight: '24px' }}>
                        {(item.pioneer || []).map((stock, si) => (
                          <StockTag key={si} stock={stock} />
                        ))}
                      </div>
                    </td>
                    <td className="py-3">
                      <div style={{ lineHeight: '24px' }}>
                        {(item.main_force || []).map((stock, si) => (
                          <StockTag key={si} stock={stock} />
                        ))}
                      </div>
                    </td>
                    <td className="py-3">
                      <div style={{ lineHeight: '24px' }}>
                        {(item.followers || []).map((stock, si) => (
                          <StockTag key={si} stock={stock} />
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* 移动端卡片 */}
          <div className="md:hidden space-y-3">
            {active_sectors.map((item, idx) => (
              <div key={idx} className="p-3 rounded-xl border bg-orange-50/50 border-orange-100">
                <div className="flex items-center justify-between mb-2">
                  <span
                    className="text-sm font-bold text-gray-900 cursor-pointer hover:underline"
                    onClick={() => navigate(`/search?keyword=${encodeURIComponent(item.name)}`)}
                  >
                    {item.name}
                  </span>
                  <div className="flex items-center space-x-2">
                    <span
                      className="text-sm font-mono font-black text-gray-900 cursor-pointer hover:text-indigo-600 transition-colors"
                      onClick={() => showStockModal(item.name + '符合条件个股', item.stocks)}
                    >
                      {item.count}只
                    </span>
                    <span className={`text-sm font-mono font-bold ${item.chg_pct > 0 ? 'text-red-500' : item.chg_pct < 0 ? 'text-green-500' : 'text-gray-500'}`}>
                      {item.chg_pct > 0 ? '+' : ''}{item.chg_pct}%
                    </span>
                  </div>
                </div>
                <div style={{ lineHeight: '28px' }}>
                  {(item.pioneer || []).slice(0, 3).map((stock, si) => (
                    <StockTag key={`pioneer-${si}`} stock={stock} />
                  ))}
                </div>
                <div className="mt-1.5">
                  <div className="text-[10px] text-gray-400 mb-1">中军</div>
                  <div style={{ lineHeight: '28px' }}>
                    {(item.main_force || []).slice(0, 2).map((stock, si) => (
                      <StockTag key={`core-${si}`} stock={stock} />
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Modal */}
      <Modal
        title={modalTitle}
        open={modalVisible}
        onCancel={() => setModalVisible(false)}
        footer={null}
        width={600}
        className="max-w-[90vw]"
      >
        <Table
          dataSource={modalData}
          columns={stockColumns}
          rowKey="code"
          size="small"
          pagination={{ pageSize: 10 }}
          bordered
          scroll={{ x: 400 }}
        />
      </Modal>
    </div>
  )
}

export default MarketSignals
