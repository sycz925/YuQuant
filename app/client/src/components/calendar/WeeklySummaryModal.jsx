import React from 'react'
import { Modal } from 'antd'

const DESIGN = {
  colors: {
    foreground: '#0F172A',
    border: '#E6E8EA',
  }
}

/**
 * 周总结 Modal
 * 显示/生成/截图周度 AI 总结
 */
export default function WeeklySummaryModal({
  visible,
  onClose,
  weeklyMeta,
  weeklySummary,
  weeklyLoading,
  weeklyScreenshotRef,
  weeklyScreenshotLoading,
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
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#6366f1" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2Z"/>
            <path d="M12 6v6l4 2"/>
          </svg>
          <span style={{fontFamily: 'Fira Sans', fontWeight: 600}}>
            {weeklyMeta ? `第${weeklyMeta.week_index}周 AI 总结` : '周总结'}
          </span>
        </div>
      }
      open={visible}
      onCancel={onClose}
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
            onClick={onGenerate}
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
            onClick={onViewInput}
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
            >
              {renderBoldText(weeklySummary)}
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
  )
}