import React, { useState, useEffect } from 'react'
import { Spin } from 'antd'
import { marketReviewApi } from '../api'

function MarketOverview({ date }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    loadData()
  }, [date])

  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await marketReviewApi.getOverview(date)
      setData(res)
    } catch (e) {
      console.error('加载市场概览失败:', e)
      setError(e.response?.data?.detail || '加载失败')
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-12 flex flex-col items-center justify-center">
        <Spin size="large" />
        <p className="mt-4 text-sm text-gray-500 font-medium">加载市场数据...</p>
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

  if (!data || !data.indices || data.indices.length === 0) return null

  const { indices, conclusion, trade_date } = data

  const formatDate = (d) => {
    if (!d || d.length !== 8) return d
    return `${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6,8)}`
  }

  const getChgColor = (v) => {
    if (v > 0) return 'text-red-600'
    if (v < 0) return 'text-green-600'
    return 'text-gray-500'
  }

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
      {/* 标题栏 */}
      <div className="px-3 md:px-6 py-3 md:py-4 border-b border-gray-100 flex items-center justify-between">
        <div className="flex items-center space-x-2 md:space-x-3">
          <div className="w-1 h-4 md:h-5 bg-indigo-500 rounded-full"></div>
          <h2 className="text-sm md:text-base font-black text-gray-900 tracking-tight">主要大盘指数涨跌幅</h2>
        </div>
        <span className="text-[10px] md:text-xs text-gray-400 font-mono">{formatDate(trade_date)}</span>
      </div>

      {/* 指数列表 */}
      <div className="p-3 md:p-6">
        {/* 移动端：紧凑卡片列表 */}
        <div className="md:hidden space-y-2">
          {indices.map((item, idx) => (
            <div
              key={item.code}
              className={`flex items-center justify-between py-2 px-3 rounded-lg ${
                idx === 0 ? 'bg-indigo-50/50' : 'bg-gray-50/30'
              }`}
            >
              <div className="flex items-center space-x-2 min-w-0">
                <span className={`text-xs font-bold truncate ${idx === 0 ? 'text-indigo-600' : 'text-gray-900'}`}>
                  {item.name}
                </span>
              </div>
              <div className="flex items-center space-x-3 flex-shrink-0">
                <span className="text-xs font-mono font-bold text-gray-600">
                  {item.close?.toFixed(2)}
                </span>
                <span className={`text-xs font-mono font-bold min-w-[60px] text-right ${getChgColor(item.pct_chg)}`}>
                  {item.pct_chg > 0 ? '+' : ''}{item.pct_chg?.toFixed(2)}%
                </span>
                {item.pe_ttm && <span className="text-[10px] font-mono text-gray-400">PE:{item.pe_ttm.toFixed(1)}</span>}
              </div>
            </div>
          ))}
        </div>

        {/* 桌面端：完整表格 */}
        <table className="hidden md:table w-full">
          <thead>
            <tr className="border-b border-gray-100">
              <th className="text-left text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3">指数名称</th>
              <th className="text-left text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3">代码</th>
              <th className="text-right text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3">最新价</th>
              <th className="text-right text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3">涨跌幅</th>
              <th className="text-right text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3">PE_TTM</th>
              <th className="text-left text-[10px] font-bold text-gray-400 uppercase tracking-wider pb-3 pl-4">点评</th>
            </tr>
          </thead>
          <tbody>
            {indices.map((item, idx) => (
              <tr
                key={item.code}
                className={`border-b border-gray-50 last:border-0 hover:bg-gray-50/50 transition-colors ${
                  idx === 0 ? 'bg-indigo-50/30' : ''
                }`}
              >
                <td className="py-3">
                  <span className={`text-sm font-bold ${idx === 0 ? 'text-indigo-600' : 'text-gray-900'}`}>
                    {item.name}
                  </span>
                </td>
                <td className="py-3">
                  <span className="text-xs font-mono text-gray-400">{item.code}</span>
                </td>
                <td className="py-3 text-right">
                  <span className="text-sm font-mono font-bold text-gray-700">
                    {item.close?.toFixed(2)}
                  </span>
                </td>
                <td className="py-3 text-right">
                  <span className={`text-sm font-mono font-bold ${getChgColor(item.pct_chg)}`}>
                    {item.pct_chg > 0 ? '+' : ''}{item.pct_chg?.toFixed(2)}%
                  </span>
                </td>
                <td className="py-3 text-right">
                  <span className="text-xs font-mono text-gray-500">
                    {item.pe_ttm ? item.pe_ttm.toFixed(2) : '-'}
                  </span>
                </td>
                <td className="py-3 pl-4">
                  <span className={`text-xs font-medium ${
                    (item.comment || '').includes('爆发') ? 'text-orange-500' :
                    (item.comment || '').includes('最强') ? 'text-indigo-500' :
                    (item.comment || '').includes('偏强') ? 'text-red-500' :
                    (item.comment || '').includes('调整') ? 'text-green-500' :
                    'text-gray-500'
                  }`}>
                    {item.comment || '-'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default MarketOverview
