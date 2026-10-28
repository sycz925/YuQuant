import React from 'react'
import { Tag, Popover } from 'antd'
import { CheckCircleFilled, CloseCircleFilled } from '@ant-design/icons'

/**
 * 二阶段单元格（Minervini Stage 2）
 * - true → 绿色标签（默认「是」，可传 labelPrefix 显示为「二阶段：是」）
 * - false → 灰色标签，点击弹出 8 条标准满足情况
 * - 无数据 → "-"
 */
const CHECK_LABELS = [
  ['c1_close_over_ma150_200', '股价 > MA150 且 > MA200'],
  ['c2_ma150_over_ma200', 'MA150 > MA200'],
  ['c3_ma200_rising', 'MA200 向上运行（约1个月）'],
  ['c4_ma50_over_ma150_200', 'MA50 > MA150 且 > MA200'],
  ['c5_close_over_ma50', '股价 > MA50'],
  ['c6_above_52w_low', '股价 ≥ 52周低点 × 1.25'],
  ['c7_near_52w_high', '股价 ≥ 52周高点 × 0.75'],
  ['c8_rps120_ge_90', 'RPS120 ≥ 90'],
]

const fmt = (v, digits = 2) => (v === null || v === undefined ? '-' : Number(v).toFixed(digits))

function Stage2Detail({ isStage2, detail }) {
  const checks = detail?.checks || {}
  const passed = CHECK_LABELS.filter(([k]) => checks[k]).length

  return (
    <div style={{ minWidth: 280 }} className="text-xs">
      <div className="flex items-center justify-between mb-2">
        <span className="font-bold">
          二阶段 8 条标准 {isStage2 ? '（全部满足）' : ''}
        </span>
        <span className="text-gray-500">满足 {passed}/8</span>
      </div>
      <div className="space-y-1">
        {CHECK_LABELS.map(([key, label]) => {
          const ok = !!checks[key]
          return (
            <div key={key} className="flex items-center justify-between gap-3">
              <span className={ok ? 'text-gray-700' : 'text-gray-400'}>{label}</span>
              {ok
                ? <CheckCircleFilled className="text-green-500" />
                : <CloseCircleFilled className="text-red-400" />}
            </div>
          )
        })}
      </div>
      {detail && (
        <div className="mt-2 pt-2 border-t border-gray-100 text-gray-500 leading-5">
          <div>股价 <b>{fmt(detail.close)}</b>　MA50 {fmt(detail.ma50)}　MA150 {fmt(detail.ma150)}　MA200 {fmt(detail.ma200)}</div>
          <div>MA200(20日前) {fmt(detail.ma200_prev20)}　52周低 {fmt(detail.low52)}　52周高 {fmt(detail.high52)}</div>
          <div>RPS120 <b>{detail.rps120 ?? '-'}</b></div>
        </div>
      )}
    </div>
  )
}

export default function Stage2Cell({ isStage2, detail, labelPrefix }) {
  if (isStage2 === undefined || isStage2 === null) {
    return <span className="text-gray-300">-</span>
  }

  const text = (suffix) => (labelPrefix ? `${labelPrefix}：${suffix}` : suffix)
  const content = <Stage2Detail isStage2={isStage2} detail={detail} />

  return (
    <Popover content={content} trigger="click" placement="bottomRight">
      <Tag
        color={isStage2 ? 'green' : 'default'}
        className="m-0 cursor-pointer"
      >
        {text(isStage2 ? '是' : '否')}
      </Tag>
    </Popover>
  )
}
