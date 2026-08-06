import React from 'react'
import { Modal } from 'antd'

const DESIGN = {
  colors: {
    foreground: '#0F172A',
    border: '#E6E8EA',
  }
}

/**
 * 月总结 Modal
 * 显示/生成/截图月度 AI 总结
 */
export default function MonthlySummaryModal({
  visible,
  onClose,
  monthLabel,
  monthlySummary,
  monthlyLoading,
  monthlyScreenshotRef,
  monthlyScreenshotLoading,
  onGenerate,
  onViewInput,
  onScreenshot,
}) {
  // 渲染加粗文本
  const renderBoldText = (text) => {
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

  return (
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
            {monthLabel} AI 月总结
          </span>
        </div>
      }
      open={visible}
      onCancel={onClose}
      footer={null}
      width={720}
      styles={{body: {maxHeight: '65vh', overflowY: 'auto', padding: '16px 24px'}}}
    >
      {/* 生成按钮 - 未生成时显示 */}
      {!monthlySummary && !monthlyLoading && (
        <div className="flex flex-col items-center justify-center py-8">
          <button
            onClick={onGenerate}
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
            onClick={onViewInput}
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
              {monthLabel} AI 月总结
            </div>
            <div
              className="text-[13px] leading-relaxed"
              style={{color: DESIGN.colors.foreground, fontFamily: 'Fira Sans', whiteSpace: 'pre-wrap'}}
            >
              {renderBoldText(monthlySummary)}
            </div>
          </div>
          <div className="mt-4 pt-3 flex items-center gap-2" style={{borderTop: `1px solid ${DESIGN.colors.border}`}}>
            <button
              onClick={onViewInput}
              className="text-[11px] px-3 py-1 rounded border transition-all active:bg-gray-100"
              style={{borderColor: DESIGN.colors.border, color: '#64748b', fontFamily: 'Fira Sans', fontWeight: 600}}
            >
              查看输入数据
            </button>
            <button
              onClick={onScreenshot}
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
  )
}