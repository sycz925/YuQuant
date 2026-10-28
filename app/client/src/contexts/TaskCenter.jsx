/**
 * 全局任务中心
 *
 * 背景：此前各页面把任务轮询写在组件内（setInterval / useTaskPolling），
 * 切换页面时组件卸载、轮询被清理，右上角进度永久卡住；刷新页面更是完全失联。
 * 任务本质是服务端长任务，生命周期与页面无关，因此统一提升到 App 根：
 *   - 单一全局轮询（2s），只轮询活跃任务
 *   - 切换页面 / 刷新页面后自动接管仍在执行的任务（GET /calendar/tasks/running）
 *   - 右上角 notification 与顶栏指示器都由这里统一驱动
 */
import React, {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from 'react'
import { notification } from 'antd'
import { taskApi } from '../api'

const TaskCenterContext = createContext(null)

const POLL_INTERVAL = 2000
const ACTIVE_STATUS = new Set(['pending', 'running', 'idle'])

export function TaskCenterProvider({ children }) {
  const [tasks, setTasks] = useState({})     // taskId -> 任务对象
  const tasksRef = useRef({})
  const callbacksRef = useRef({})            // taskId -> { title, kind, onDone, onFailed, onProgress }

  useEffect(() => { tasksRef.current = tasks }, [tasks])

  const titleOf = useCallback((taskId, fallback) => {
    return callbacksRef.current[taskId]?.title || fallback || '任务'
  }, [])

  const invoke = useCallback((taskId, name, payload) => {
    const fn = callbacksRef.current[taskId]?.[name]
    if (typeof fn === 'function') {
      try { fn(payload) } catch (e) { console.error('[TaskCenter] 回调异常', name, e) }
    }
  }, [])

  const dropTask = useCallback((taskId, delay = 0) => {
    const remove = () => setTasks(prev => {
      if (!prev[taskId]) return prev
      const next = { ...prev }
      delete next[taskId]
      return next
    })
    if (delay > 0) setTimeout(remove, delay)
    else remove()
    // 回调稍后清理，确保收尾通知/回调仍能取到标题
    setTimeout(() => { delete callbacksRef.current[taskId] }, 1500)
  }, [])

  /** 注册任务：页面调用启动接口拿到 task_id 后调用 */
  const startTask = useCallback((taskId, meta = {}) => {
    if (!taskId) return
    callbacksRef.current[taskId] = { ...callbacksRef.current[taskId], ...meta }
    setTasks(prev => ({
      ...prev,
      [taskId]: {
        task_id: taskId,
        status: 'running',
        name: meta.title || '',
        kind: meta.kind || '',
        message: meta.message || '正在准备...',
        current_step: 0,
        steps: [],
      },
    }))
    notification.info({
      key: taskId,
      message: meta.title || '任务',
      description: meta.message || '正在准备...',
      duration: 0,
      closable: false,
    })
  }, [])

  /** 手动关闭某个任务通知 */
  const dismissTask = useCallback((taskId) => {
    dropTask(taskId, 0)
    notification.destroy(taskId)
  }, [dropTask])

  const pollOne = useCallback(async (taskId) => {
    let status
    try {
      status = await taskApi.getStatus(taskId)
    } catch (e) {
      return  // 网络抖动：下个周期重试，不移除任务
    }
    const title = titleOf(taskId, tasksRef.current[taskId]?.name)

    if (!status || status.status === 'not_found') {
      notification.warning({
        key: taskId,
        message: `${title}已失效`,
        description: '后端任务不存在（可能服务已重启）',
        duration: 4,
        closable: true,
      })
      dropTask(taskId, 1200)
      return
    }

    if (status.status === 'failed') {
      notification.error({
        key: taskId,
        message: `${title}失败`,
        description: status.message || status.error || '未知错误',
        duration: 0,
        closable: true,
      })
      invoke(taskId, 'onFailed', status)
      dropTask(taskId, 0)
      return
    }

    if (status.status === 'completed') {
      notification.success({
        key: taskId,
        message: `${title}完成`,
        description: status.message || '',
        duration: 6,
        closable: true,
      })
      invoke(taskId, 'onDone', status)
      dropTask(taskId, 0)
      return
    }

    // running / pending
    const steps = status.steps || []
    const total = steps.length || 1
    const idx = Math.min(status.current_step || 0, total - 1)
    const cur = steps[idx]
    const desc = cur
      ? `${cur.name}(${cur.completed_count || 0}/${cur.total_count || 1})${status.current_stock_name ? ` · ${status.current_stock_name}` : ''}`
      : (status.message || '处理中...')

    notification.info({
      key: taskId,
      message: `${title}(${Math.min(idx + 1, total)}/${total})`,
      description: desc,
      duration: 0,
      closable: false,
    })
    invoke(taskId, 'onProgress', status)
    setTasks(prev => (prev[taskId] ? { ...prev, [taskId]: { ...prev[taskId], ...status } } : prev))
  }, [dropTask, invoke, titleOf])

  // 单一全局轮询：无论用户切到哪个页面都持续工作
  useEffect(() => {
    const timer = setInterval(() => {
      const active = Object.values(tasksRef.current).filter(t => ACTIVE_STATUS.has(t.status))
      active.forEach(t => { pollOne(t.task_id) })
    }, POLL_INTERVAL)
    return () => clearInterval(timer)
  }, [pollOne])

  // 挂载时接管后端仍在运行的任务（刷新页面 / 首次进入也能续上进度）
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await taskApi.getRunning()
        const list = res?.data || []
        if (cancelled || !list.length) return
        const seeded = {}
        list.forEach(t => {
          if (!t?.task_id) return
          seeded[t.task_id] = t
          notification.info({
            key: t.task_id,
            message: t.name || '任务',
            description: t.message || '进行中...',
            duration: 0,
            closable: false,
          })
        })
        if (Object.keys(seeded).length) {
          setTasks(prev => ({ ...seeded, ...prev }))
        }
      } catch (e) {
        // 后端不可用时静默：用户下次启动任务会重新注册
      }
    })()
    return () => { cancelled = true }
  }, [])

  const activeTasks = useMemo(
    () => Object.values(tasks).filter(t => ACTIVE_STATUS.has(t.status)),
    [tasks],
  )

  const value = useMemo(
    () => ({ tasks, activeTasks, startTask, dismissTask }),
    [tasks, activeTasks, startTask, dismissTask],
  )

  return <TaskCenterContext.Provider value={value}>{children}</TaskCenterContext.Provider>
}

export function useTaskCenter() {
  const ctx = useContext(TaskCenterContext)
  if (!ctx) {
    throw new Error('useTaskCenter 必须在 TaskCenterProvider 内使用')
  }
  return ctx
}
