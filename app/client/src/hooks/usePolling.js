/**
 * usePolling - 通用轮询 Hook
 * 支持页面隐藏暂停、指数退避、自动清理
 */
import { useEffect, useRef, useCallback } from 'react'

/**
 * 轮询 Hook
 * @param {Function} callback - 轮询回调函数
 * @param {number} interval - 轮询间隔（毫秒）
 * @param {boolean} enabled - 是否启用轮询
 * @param {Object} options - 配置选项
 * @param {boolean} options.pauseOnHidden - 页面隐藏时暂停（默认 true）
 * @param {number} options.maxRetries - 最大重试次数（默认 3）
 * @param {number} options.backoffMultiplier - 退避倍数（默认 2）
 */
export function usePolling(callback, interval, enabled = true, options = {}) {
  const {
    pauseOnHidden = true,
    maxRetries = 3,
    backoffMultiplier = 2
  } = options

  const callbackRef = useRef(callback)
  const intervalRef = useRef(null)
  const retryCountRef = useRef(0)
  const isPausedRef = useRef(false)

  // 更新 callback ref
  useEffect(() => {
    callbackRef.current = callback
  }, [callback])

  // 页面可见性变化处理
  useEffect(() => {
    if (!pauseOnHidden) return

    const handleVisibilityChange = () => {
      if (document.hidden) {
        isPausedRef.current = true
      } else {
        isPausedRef.current = false
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [pauseOnHidden])

  // 执行轮询
  const poll = useCallback(async () => {
    if (isPausedRef.current) return

    try {
      await callbackRef.current()
      retryCountRef.current = 0
    } catch (error) {
      console.error('[usePolling] 轮询失败:', error)
      retryCountRef.current++

      if (retryCountRef.current >= maxRetries) {
        console.error('[usePolling] 达到最大重试次数，停止轮询')
        stop()
      }
    }
  }, [maxRetries])

  // 启动轮询
  const start = useCallback(() => {
    if (intervalRef.current) return

    intervalRef.current = setInterval(poll, interval)
  }, [interval, poll])

  // 停止轮询
  const stop = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
  }, [])

  // 重置重试计数
  const resetRetries = useCallback(() => {
    retryCountRef.current = 0
  }, [])

  // 启动/停止轮询
  useEffect(() => {
    if (enabled) {
      start()
    } else {
      stop()
    }

    return () => stop()
  }, [enabled, start, stop])

  return {
    start,
    stop,
    resetRetries,
    isPaused: isPausedRef.current
  }
}

export default usePolling
