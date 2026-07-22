/**
 * useOneClickUpdate - 一键更新 Hook
 * 封装一键更新的启动、轮询、通知逻辑
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
        const taskStatus = await taskApi.getTaskStatus(res.task_id)
        const stepText = taskStatus.total_count > 0
          ? `[${taskStatus.completed_count}/${taskStatus.total_count}]`
          : ''

        notification.info({
          message: '更新任务正在进行中',
          description: `${stepText} ${taskStatus.current_stock_name || '处理中...'}`,
          duration: 0,
          key,
          closable: false,
        })
      } else {
        notification.info({
          message: '一键更新已启动',
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
  }, [isRunning])

  // 开始轮询任务状态
  const startPolling = useCallback((taskId) => {
    if (intervalRef.current) return

    const key = 'update-progress'

    intervalRef.current = setInterval(async () => {
      try {
        const status = await taskApi.getTaskStatus(taskId)

        // 任务失败
        if (status.status === 'failed') {
          notification.error({
            message: '更新失败',
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
            message: '一键更新完成',
            description: '数据已同步，RPS/PE已计算，基础数据已更新',
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
          const completedSteps = steps.filter(s => s.status === 'completed').length
          const stepText = totalSteps > 0 ? `[${completedSteps}/${totalSteps}]` : ''
          const currentStep = steps[status.current_step]
          const stepName = currentStep ? currentStep.name : '处理中...'

          notification.info({
            message: `一键更新 ${stepText}`,
            description: stepName,
            duration: 0,
            key,
            closable: false,
          })
        }
      } catch (error) {
        console.error('[useOneClickUpdate] 轮询失败:', error)
      }
    }, 3000)
  }, [])

  // 停止轮询
  const stopPolling = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
  }, [])

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
