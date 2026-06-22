import React, { useState, useEffect } from 'react'
import { Spin, Modal, Table } from 'antd'
import { marketReviewApi } from '../api'

function MarketSignals({ date }) {
  const [signalsData, setSignalsData] = useState(null)
  const [blocksData, setBlocksData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [modalVisible, setModalVisible] = useState(false)
  const [modalTitle, setModalTitle] = useState('')
  const [modalData, setModalData] = useState([])

  useEffect(() => {
    loadData()
  }, [date])

  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      const [signalsRes, blocksRes] = await Promise.all([
        marketReviewApi.getSignals(date),
        marketReviewApi.getNewHighBlocks(date)
      ])
      setSignalsData(signalsRes.data)
      setBlocksData(blocksRes.data)
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

  if (!signalsData || !signalsData.indicators) return null

  const { indicators, interpretation, trade_date } = signalsData
  const { total_new_high_count, industry_clusters } = blocksData || {}

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
      <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <div className="w-1 h-5 bg-emerald-500 rounded-full"></div>
          <h2 className="text-base font-black text-gray-900 tracking-tight">A股运行状态与新高板块效应</h2>
        </div>
        <div className="flex items-center space-x-3">
          <span className="text-xs text-gray-400 font-mono">{formatDate(trade_date)}</span>
          {total_new_high_count > 0 && (
            <span className="px-2 py-0.5 bg-amber-100 text-amber-700 text-xs font-bold rounded-full">
              {total_new_high_count} 只新高
            </span>
          )}
        </div>
      </div>

      {/* 第一部分：量化指标 */}
      <div className="p-6 border-b border-gray-100">
        <div className="flex items-center space-x-2 mb-4">
          <div className="w-1 h-4 bg-emerald-500 rounded-full"></div>
          <h3 className="text-sm font-bold text-gray-700">量化指标</h3>
        </div>
        <table className="w-full">
          <thead>
            <tr className="border-b border-gray-100">
              <th className="text-left text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3 w-1/3">指标</th>
              <th className="text-left text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3 w-1/3">数据</th>
              <th className="text-left text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3 w-1/3 pl-4">信号解读</th>
            </tr>
          </thead>
          <tbody>
            {indicators.map((item, idx) => (
              <tr
                key={idx}
                className="border-b border-gray-50 last:border-0 hover:bg-gray-50/50 transition-colors"
              >
                <td className="py-3">
                  <span className="text-sm font-bold text-gray-800">{item.name}</span>
                </td>
                <td className="py-3">
                  <span 
                    className="text-base font-mono font-black text-gray-900 cursor-pointer hover:text-indigo-600 transition-colors"
                    onClick={() => {
                      const stocks = item.stocks || []
                      if (stocks.length > 0) {
                        showStockModal(item.name + '个股列表', stocks)
                      }
                    }}
                  >
                    {item.data}
                  </span>
                  {item.name.includes('50日线') && getIndicatorBar(item.data_value, 100)}
                </td>
                <td className="py-3 pl-4">
                  <span className={`text-xs ${getSignalColor(item.signal)}`}>{item.signal}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 第二部分：板块效应聚类 */}
      {industry_clusters && industry_clusters.length > 0 && (
        <div className="p-6 border-b border-gray-100">
          <div className="flex items-center space-x-2 mb-4">
            <div className="w-1 h-4 bg-amber-500 rounded-full"></div>
            <h3 className="text-sm font-bold text-gray-700">新高板块效应聚类</h3>
          </div>
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-100">
                <th className="text-left text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3">板块方向</th>
                <th className="text-center text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3 w-24">新高个股</th>
                <th className="text-center text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3 w-24">平均涨幅</th>
                <th className="text-left text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3">代表个股</th>
                <th className="text-left text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3 w-24 pl-4">特征</th>
              </tr>
            </thead>
            <tbody>
              {industry_clusters.map((item, idx) => (
                <tr
                  key={idx}
                  className={`border-b border-gray-50 last:border-0 hover:bg-gray-50/50 transition-colors ${
                    idx === 0 ? 'bg-amber-50/30' : ''
                  }`}
                >
                  <td className="py-3">
                    <div className="flex items-center space-x-2">
                      {idx === 0 && <span className="text-amber-500 text-xs">👑</span>}
                      <span className={`text-sm font-bold ${idx === 0 ? 'text-amber-700' : 'text-gray-900'}`}>
                        {item.industry}
                      </span>
                    </div>
                  </td>
                  <td className="py-3 text-center">
                    <span 
                      className={`text-base font-mono font-black cursor-pointer hover:text-indigo-600 transition-colors ${
                        idx === 0 ? 'text-amber-600' : 'text-gray-900'
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
                      item.avg_chg > 0 ? 'text-red-500' : item.avg_chg < 0 ? 'text-green-500' : 'text-gray-500'
                    }`}>
                      {item.avg_chg > 0 ? '+' : ''}{item.avg_chg}%
                    </span>
                  </td>
                  <td className="py-3">
                    <div className="flex flex-wrap gap-1">
                      {item.representative_stocks.map((stock, si) => (
                        <span
                          key={si}
                          className="font-mono text-[11px] bg-slate-100 px-1.5 py-0.5 rounded text-slate-700"
                        >
                          {stock}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="py-3 pl-4">
                    <span className={`text-[11px] font-bold ${
                      idx === 0 ? 'text-amber-600' : 'text-indigo-500'
                    }`}>
                      {idx === 0 ? '主线方向' : '机构共振'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Modal */}
      <Modal
        title={modalTitle}
        open={modalVisible}
        onCancel={() => setModalVisible(false)}
        footer={null}
        width={600}
      >
        <Table
          dataSource={modalData}
          columns={stockColumns}
          rowKey="code"
          size="small"
          pagination={{ pageSize: 10 }}
          bordered
        />
      </Modal>

      {/* 合并后的信号解读 */}
      {combinedInterpretation && (
        <div className="px-6 pb-6">
          <div className="border-l-4 border-emerald-500 bg-emerald-50/60 rounded-r-lg p-4">
            <div className="flex items-start space-x-2 mb-1">
              <span className="text-emerald-600 text-xs font-bold uppercase tracking-widest whitespace-nowrap mt-0.5">综合分析</span>
            </div>
            <p className="text-sm text-gray-700 font-medium leading-relaxed whitespace-pre-line">
              {renderHighlightedText(combinedInterpretation)}
            </p>
          </div>
        </div>
      )}
    </div>
  )
}

export default MarketSignals
