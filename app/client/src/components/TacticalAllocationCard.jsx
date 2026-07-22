import React from 'react'
import { Tag } from 'antd'

const renderAIHighlightedText = (text) => {
  if (!text) return null
  const parts = text.split(/\*\*(.*?)\*\*/g)
  return parts.map((part, i) => {
    if (i % 2 === 1) {
      return (
        <span key={i} className="text-amber-500 font-bold bg-amber-50 px-1 py-0.5 rounded mx-0.5">
          {part}
        </span>
      )
    }
    return part
  })
}

const riskColors = {
  '低': { bg: 'bg-green-100', text: 'text-green-700', border: 'border-green-300', bar: 'bg-green-500' },
  '中低': { bg: 'bg-blue-100', text: 'text-blue-700', border: 'border-blue-300', bar: 'bg-blue-500' },
  '中': { bg: 'bg-amber-100', text: 'text-amber-700', border: 'border-amber-300', bar: 'bg-amber-500' },
  '中高': { bg: 'bg-orange-100', text: 'text-orange-700', border: 'border-orange-300', bar: 'bg-orange-500' },
  '高': { bg: 'bg-red-100', text: 'text-red-700', border: 'border-red-300', bar: 'bg-red-500' },
}

function TacticalAllocationCard({ data }) {
  if (!data) return null

  const model = data.allocation_and_focus_model
  if (!model) return null

  const risk = model.market_risk_level || '中'
  const colors = riskColors[risk] || riskColors['中']

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
      {/* 标题栏 */}
      <div className="px-6 py-4 border-b border-gray-100 flex items-center space-x-3">
        <div className="w-1 h-5 bg-gradient-to-b from-indigo-500 to-purple-600 rounded-full"></div>
        <h2 className="text-base font-black text-gray-900 tracking-tight">战术仓位配置</h2>
        <span className="px-2 py-0.5 bg-indigo-100 text-indigo-600 text-[10px] font-bold rounded-full">
          基于SEPA系统推演
        </span>
      </div>

      <div className="p-6">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* 右侧：仓位仪表盘 */}
          <div className="lg:col-span-1">
            <div className={`${colors.bg} ${colors.border} border rounded-2xl p-5 text-center`}>
              <div className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-2">推荐总仓位</div>
              <div className={`font-mono text-3xl font-black ${colors.text} tracking-tight`}>
                {model.recommended_position_range || '-'}
              </div>
              <div className="mt-3 flex items-center justify-center space-x-2">
                <span className={`inline-block px-2 py-0.5 rounded text-[10px] font-bold leading-none ${
                  risk === '高' ? 'bg-red-100 text-red-600' :
                  risk === '中高' ? 'bg-orange-100 text-orange-600' :
                  risk === '中' ? 'bg-amber-100 text-amber-600' :
                  risk === '中低' ? 'bg-blue-100 text-blue-600' :
                  'bg-green-100 text-green-600'
                }`}>
                  风险: {risk}
                </span>
              </div>
              {/* 仓位管理说明 */}
              {model.position_management_commentary && (
                <div className="mt-3 text-xs text-gray-600 leading-relaxed text-left">
                  {renderAIHighlightedText(model.position_management_commentary)}
                </div>
              )}
              {/* 风险条 */}
              <div className="mt-3 w-full bg-gray-200 rounded-full h-1.5 overflow-hidden">
                <div className={`${colors.bar} h-full rounded-full transition-all`} style={{
                  width: risk === '低' ? '20%' : risk === '中低' ? '40%' : risk === '中' ? '60%' : risk === '中高' ? '80%' : '100%'
                }} />
              </div>
            </div>
          </div>

          {/* 左侧：核心板块 + 风控 */}
          <div className="lg:col-span-2 space-y-5">
            {/* 核心攻击板块 */}
            {model.core_target_sectors && model.core_target_sectors.length > 0 && (
              <div>
                <div className="flex items-center space-x-2 mb-3">
                  <span className="text-lg">🎯</span>
                  <h3 className="text-sm font-bold text-gray-700">资金集中攻击板块</h3>
                </div>
                <div style={{ lineHeight: '36px' }}>
                  {model.core_target_sectors.map((sector, idx) => (
                    <span
                      key={idx}
                      className="inline-block px-3 py-1 rounded-md text-sm font-bold bg-blue-50 text-blue-600 border border-blue-200 mr-2 mb-2 whitespace-nowrap leading-none"
                    >
                      {idx === 0 ? '🔥' : idx === 1 ? '🎯' : '📌'} {sector}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* 资金风控铁律 */}
            {model.capital_concentration_rule && (
              <div>
                <div className="flex items-center space-x-2 mb-3">
                  <span className="text-lg">🛡️</span>
                  <h3 className="text-sm font-bold text-gray-700">资金风控铁律</h3>
                </div>
                <div className="bg-amber-50 border border-amber-200 rounded-xl p-4">
                  <p className="text-sm text-amber-800 font-medium leading-relaxed">
                    {renderAIHighlightedText(model.capital_concentration_rule)}
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default TacticalAllocationCard
