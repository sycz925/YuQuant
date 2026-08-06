import React from 'react'
import { Modal } from 'antd'

const DESIGN = {
  colors: {
    foreground: '#0F172A',
    border: '#E6E8EA',
  }
}

/**
 * 通用输入数据查看 Modal
 * 用于周总结和月总结的输入数据预览
 */
export default function InputDataModal({ visible, onClose, title, data, icon }) {
  return (
    <Modal
      title={
        <div className="flex items-center gap-2">
          {icon || (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#64748b" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/>
              <path d="M14 2v6h6M16 13H8M16 17H8M10 9H8"/>
            </svg>
          )}
          <span style={{fontFamily: 'Fira Sans', fontWeight: 600}}>
            {title}
          </span>
        </div>
      }
      open={visible}
      onCancel={onClose}
      footer={null}
      width={680}
      styles={{body: {maxHeight: '65vh', overflowY: 'auto', padding: '16px 24px'}}}
    >
      {data ? (
        <pre className="text-[12px] leading-relaxed whitespace-pre-wrap" style={{color: DESIGN.colors.foreground, fontFamily: 'Fira Code', background: '#f8fafc', padding: '12px', borderRadius: '8px', border: `1px solid ${DESIGN.colors.border}`}}>
          {data}
        </pre>
      ) : (
        <div className="flex items-center justify-center py-8">
          <span className="text-xs" style={{color: '#94a3b8'}}>加载中...</span>
        </div>
      )}
    </Modal>
  )
}