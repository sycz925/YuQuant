import React from 'react'
import { Badge, Button, Popover, Progress, Tooltip } from 'antd'
import { LoadingOutlined } from '@ant-design/icons'
import { useTaskCenter } from '../contexts/TaskCenter'

/**
 * 顶栏「进行中的任务」指示器
 * 与右上角 notification 互补：通知被手动关闭后，仍能从这里看到任务进度。
 */
export default function TaskIndicator() {
  const { activeTasks } = useTaskCenter()
  if (!activeTasks.length) return null

  const content = (
    <div style={{ width: 300 }} className="space-y-3">
      {activeTasks.map(t => {
        const steps = t.steps || []
        const total = steps.length || 1
        const idx = Math.min(t.current_step || 0, total - 1)
        const cur = steps[idx]
        const inner = cur?.total_count
          ? (cur.completed_count || 0) / cur.total_count
          : 0
        const percent = Math.min(100, Math.round(((idx + inner) / total) * 100))
        return (
          <div key={t.task_id}>
            <div className="flex items-center justify-between text-xs mb-1">
              <span className="font-medium text-gray-800">{t.name || '任务'}</span>
              <span className="text-gray-400 tabular-nums">{Math.min(idx + 1, total)}/{total}</span>
            </div>
            <Progress percent={percent} size="small" status="active" showInfo={false} />
            <div className="text-[11px] text-gray-500 leading-4 mt-0.5">
              {cur
                ? `${cur.name}（${cur.completed_count || 0}/${cur.total_count || 1}）`
                : (t.message || '处理中...')}
            </div>
          </div>
        )
      })}
    </div>
  )

  return (
    <Popover content={content} title="进行中的任务" trigger="click" placement="bottomRight">
      <Tooltip title={`${activeTasks.length} 个任务进行中`}>
        <Badge count={activeTasks.length} size="small" offset={[-2, 2]}>
          <Button
            type="text"
            icon={<LoadingOutlined spin />}
            className="text-white/80 hover:text-white hover:bg-white/10"
            size="small"
          />
        </Badge>
      </Tooltip>
    </Popover>
  )
}
