/**
 * useTaskPolling - 任务状态轮询 Hook
 * 专门用于轮询任务进度，支持完成/失败自动停止
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { taskApi } from '../api'

/**
 * 任务状态轮询 Hook
 * @param {string} taskId - 任务 ID
 * @param {Object} options - 配置选项
 * @param {number} options.interval - 轮询间隔（毫秒，默认 3000）
 * @param {Function} options.onProgress - 进度回调
 * @param {Function} options.onComplete - 完成回调
 * @param {Function} options.onFailed - 失败回调
 * @param {boolean} options.autoStart - 自动开始（默认 true）
 */
export function useTaskPolling(taskId, options = {}) {
  const {
    interval = 3000,
    onProgress,
    onComplete,
    onFailed,
    autoStart = true
  } = options

  const [status, setStatus] = useState(null)
  const [isPolling, setIsPolling] = useState(false)
  const intervalRef = useRef(null)
  const callbacksRef = useRef({ onProgress, onComplete, onFailed })

  // 更新 callbacks ref
  useEffect(() => {
    callbacksRef.current = { onProgress, onComplete, onFailed }
  }, [onProgress, onComplete, onFailed])

  // 轮询任务状态
  const poll = useCallback(async () => {
    if (!taskId) return

    try {
      const taskStatus = await taskApi.getTaskStatus(taskId)
      setStatus(taskStatus)

      // 调用进度回调
      if (callbacksRef.current.onProgress) {
        callbacksRef.current.onProgress(taskStatus)
      }

      // 任务完成
      if (taskStatus.status === 'completed') {
        stop()
        if (callbacksRef.current.onComplete) {
          callbacksRef.current.onComplete(taskStatus)
        }
        return
      }

      // 任务失败
      if (taskStatus.status === 'failed') {
        stop()
        if (callbacksRef.current.onFailed) {
          callbacksRef.current.onFailed(taskStatus)
        }
        return
      }
    } catch (error) {
      console.error('[useTaskPolling] 轮询失败:', error)
    }
  }, [taskId])

  // 启动轮询
  const start = useCallback(() => {
    if (intervalRef.current) return
    setIsPolling(true)
    intervalRef.current = setInterval(poll, interval)
  }, [interval, poll])

  // 停止轮询
  const stop = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
    setIsPolling(false)
  }, [])

  // 自动启动
  useEffect(() => {
    if (taskId && autoStart) {
      start()
    }

    return () => stop()
  }, [taskId, autoStart, start, stop])

  // taskId 变化时重新开始
  useEffect(() => {
    if (taskId && autoStart && isPolling) {
      stop()
      start()
    }
  }, [taskId])

  return {
    status,
    isPolling,
    start,
    stop
  }
}

export default useTaskPolling
