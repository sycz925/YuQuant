/**
 * usePolling - 通用轮询 Hook
 * 支持页面隐藏暂停、重试上限、自动清理
 */
import { useEffect, useRef, useCallback, useState } from 'react'

/**
 * 轮询 Hook
 * @param {Function} callback - 轮询回调函数
 * @param {number} interval - 轮询间隔（毫秒）
 * @param {boolean} enabled - 是否启用轮询
 * @param {Object} options - 配置选项
 * @param {boolean} options.pauseOnHidden - 页面隐藏时暂停（默认 true）
 * @param {number} options.maxRetries - 连续失败最大重试次数（默认 3）
 */
export function usePolling(callback, interval, enabled = true, options = {}) {
  const {
    pauseOnHidden = true,
    maxRetries = 3
  } = options

  // isPaused 需响应式（供外部消费），isPausedRef 供定时器回调内判断（避免 isPaused 变化重建定时器）
  const [isPaused, setIsPaused] = useState(false)
  const isPausedRef = useRef(false)
  const callbackRef = useRef(callback)
  const intervalRef = useRef(null)
  const retryCountRef = useRef(0)

  // 更新 callback ref，保证定时器始终调用最新回调
  useEffect(() => {
    callbackRef.current = callback
  }, [callback])

  // 页面可见性变化处理
  useEffect(() => {
    if (!pauseOnHidden) return

    const handleVisibilityChange = () => {
      isPausedRef.current = document.hidden
      setIsPaused(document.hidden)
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [pauseOnHidden])

  // 停止轮询
  const stop = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
  }, [])

  // 执行一次轮询
  const poll = useCallback(async () => {
    try {
      await callbackRef.current()
      retryCountRef.current = 0
    } catch (error) {
      retryCountRef.current++
      if (retryCountRef.current >= maxRetries) {
        stop()
      }
    }
  }, [maxRetries, stop])

  // 启动轮询（定时器回调内读 isPausedRef，isPaused 变化不重建定时器）
  const start = useCallback(() => {
    if (intervalRef.current) return
    intervalRef.current = setInterval(() => {
      if (!isPausedRef.current) poll()
    }, interval)
  }, [interval, poll])

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
    isPaused
  }
}

export default usePolling
