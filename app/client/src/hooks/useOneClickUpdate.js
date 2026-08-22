/**
 * useOneClickUpdate - 一键更新 Hook
 * 封装一键更新的启动、轮询、通知逻辑
 *
 * 注意：一键更新的轮询为独立实现（不复用 useTaskPolling）。
 * 因一键更新任务在后台异步执行，启动后需立即用闭包参数 taskId 轮询，
 * 若改用 useTaskPolling 的 state 驱动轮询，会引入 state 更新时序差异导致进度异常。
 */
import { useState, useCallback, useRef } from 'react'
import { message, notification } from 'antd'
import { oneClickUpdateApi, taskApi } from '../api'

/**
 * 一键更新 Hook
 * @param {Object} options - 配置选项
 * @param {Function} options.onComplete - 更新完成回调
 * @param {Function} options.onFailed - 更新失败回调
 */
export function useOneClickUpdate(options = {}) {
  const { onComplete, onFailed } = options

  const [isRunning, setIsRunning] = useState(false)
  const [currentTaskId, setCurrentTaskId] = useState(null)
  const intervalRef = useRef(null)
  const callbacksRef = useRef({ onComplete, onFailed })

  // 更新 callbacks ref
  callbacksRef.current = { onComplete, onFailed }

  // 停止轮询
  const stopPolling = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
  }, [])

  // 开始轮询任务状态（taskId 通过闭包参数传入，避免依赖 state 更新时序）
  const startPolling = useCallback((taskId) => {
    if (intervalRef.current) return

    const key = 'update-progress'

    intervalRef.current = setInterval(async () => {
      try {
        const status = await taskApi.getStatus(taskId)

        // 任务失败
        if (status.status === 'failed') {
          notification.error({
            message: `${status.name || '一键更新'}失败`,
            description: status.message || '未知错误',
            duration: 0,
            key,
            closable: true,
          })
          stopPolling()
          setIsRunning(false)
          if (callbacksRef.current.onFailed) {
            callbacksRef.current.onFailed(status)
          }
          return
        }

        // 任务完成
        if (status.status === 'completed') {
          notification.success({
            message: `${status.name || '一键更新'}完成`,
            description: '数据已同步，RPS/PE已计算，基础数据已更新，请手动刷新页面',
            duration: 0,
            key,
            closable: true,
          })
          stopPolling()
          setIsRunning(false)
          if (callbacksRef.current.onComplete) {
            callbacksRef.current.onComplete(status)
          }
          return
        }

        // 任务进行中
        if (status.status === 'running') {
          const steps = status.steps || []
          const totalSteps = steps.length
          const currentStep = steps[status.current_step]
          const stepDesc = currentStep ? `${currentStep.name}(${currentStep.completed_count || 0}/${currentStep.total_count || 1})` : '处理中...'

          notification.info({
            message: `${status.name || '一键更新'}(${status.current_step || 0}/${totalSteps})`,
            description: stepDesc,
            duration: 0,
            key,
            closable: false,
          })
        }
      } catch (error) {
        console.error('[useOneClickUpdate] 轮询失败:', error)
      }
    }, 3000)
  }, [stopPolling])

  // 启动一键更新
  const start = useCallback(async () => {
    if (isRunning) return

    try {
      const res = await oneClickUpdateApi.start()

      if (!res?.success) {
        message.warning(res?.message || '无法启动更新')
        return
      }

      setIsRunning(true)
      setCurrentTaskId(res.task_id)

      const key = 'update-progress'

      // 如果任务已在运行
      if (res.already_running) {
        const taskStatus = await taskApi.getStatus(res.task_id)
        const steps = taskStatus.steps || []
        const currentStep = steps[taskStatus.current_step]
        const stepDesc = currentStep ? `${currentStep.name}(${currentStep.completed_count || 0}/${currentStep.total_count || 1})` : '处理中...'

        notification.info({
          message: `${taskStatus.name || '一键更新'}(${taskStatus.current_step || 0}/${steps.length})`,
          description: stepDesc,
          duration: 0,
          key,
          closable: false,
        })
      } else {
        notification.info({
          message: `一键更新(0/0)`,
          description: '正在准备...',
          duration: 0,
          key,
          closable: false,
        })
      }

      // 开始轮询
      startPolling(res.task_id)
    } catch (error) {
      console.error('[useOneClickUpdate] 启动失败:', error)
      message.error('启动更新失败')
      setIsRunning(false)
    }
  }, [isRunning, startPolling])

  // 取消更新
  const cancel = useCallback(() => {
    stopPolling()
    setIsRunning(false)
    setCurrentTaskId(null)
    notification.destroy('update-progress')
  }, [stopPolling])

  return {
    isRunning,
    currentTaskId,
    start,
    cancel
  }
}

export default useOneClickUpdate
