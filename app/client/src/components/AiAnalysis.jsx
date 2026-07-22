import React, { useState, useEffect, useRef } from 'react'
import { Spin, Tag, Modal, Button, message } from 'antd'
import { CameraOutlined } from '@ant-design/icons'
import { toPng } from 'html-to-image'
import { marketReviewApi, factorApi } from '../api'
import TacticalAllocationCard from './TacticalAllocationCard'

// 风险等级颜色映射
const riskColors = {
  '低': { bg: 'bg-green-100 text-green-600', label: '🟢 低风险' },
  '中低': { bg: 'bg-blue-100 text-blue-600', label: '低风险' },
  '中': { bg: 'bg-amber-100 text-amber-600', label: '⚠️ 中等' },
  '中高': { bg: 'bg-orange-100 text-orange-600', label: '⚠️ 中高风险' },
  '高': { bg: 'bg-red-100 text-red-600 animate-pulse', label: '🔴 高风险' },
}

// 解析 DeepSeek 返回的 Markdown 加粗标记，渲染高亮
const renderAIHighlightedText = (text) => {
  if (!text) return null
  const parts = text.split(/\*\*(.*?)\*\*/g)
  return parts.map((part, i) => {
    if (i % 2 === 1) {
      // 奇数项 = 被 ** 包裹的内容 → 高亮
      return (
        <span key={i} className="text-amber-500 font-bold bg-amber-50 px-1 py-0.5 rounded mx-0.5">
          {part}
        </span>
      )
    }
    return part
  })
}

// 从后端检查 DeepSeek 是否可用
const checkDeepseekAvailable = async () => {
  try {
    const res = await factorApi.getDeepseekTimeLimit()
    return res?.available !== false
  } catch (e) {
    return true
  }
}

function AiAnalysis({ date }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [taskStatus, setTaskStatus] = useState(null) // 'generating' | null
  const [taskMessage, setTaskMessage] = useState('')
  const [error, setError] = useState(null)
  const [lastError, setLastError] = useState(null) // 上次失败的错误信息
  const [inputDataVisible, setInputDataVisible] = useState(false)
  const [inputDataLoading, setInputDataLoading] = useState(false)
  const [inputDataContent, setInputDataContent] = useState('')
  const pollingRef = useRef(null)
  const [updateAllowed, setUpdateAllowed] = useState(true)
  const [screenshotLoading, setScreenshotLoading] = useState(false)
  const screenshotRef = useRef(null)

  useEffect(() => {
    if (date) loadData(date)
    checkAvailability()
    return () => { if (pollingRef.current) clearInterval(pollingRef.current) }
  }, [date])

  // 定时检查 DeepSeek 可用性
  useEffect(() => {
    const timer = setInterval(checkAvailability, 60000)
    return () => clearInterval(timer)
  }, [])

  const checkAvailability = async () => {
    const allowed = await checkDeepseekAvailable()
    setUpdateAllowed(allowed)
  }

  const loadData = async (tradeDate) => {
    setLoading(true)
    setError(null)
    setTaskStatus(null)
    setLastError(null)
    try {
      const res = await marketReviewApi.getAiAnalysis(tradeDate)
      // need_generate: 无缓存需要生成
      // is_final: 盘后数据
      // market_phase_diagnosis: 有AI分析结果
      // last_error: 上次生成失败的错误信息
      setData(res || {})
      if (res?.last_error) {
        setLastError(res.last_error)
      }
    } catch (e) {
      console.error('[AI] 加载失败:', e)
      const errMsg = e.response?.data?.detail || e.message || '加载失败'
      setError(errMsg)
    } finally {
      setLoading(false)
    }
  }

  const startGenerate = async (tradeDate) => {
    try {
      setLastError(null) // 清除上次错误信息
      const res = await marketReviewApi.generateAiAnalysis(tradeDate)
      if (res?.is_cached) {
        // 启动时发现已有缓存（可能被其他请求抢先生成）
        setData(res)
        setTaskStatus(null)
        return
      }
      // 后端返回错误（如上次生成失败且无法重新生成）
      if (res?.error) {
        setLastError(res.error)
        setTaskStatus(null)
        return
      }
      const taskId = res?.task_id
      if (!taskId) {
        setError('未获取到任务ID')
        setTaskStatus(null)
        return
      }
      // 开始轮询（taskStatus可能已由handleGenerateFromInputData设置）
      if (!taskStatus) {
        setTaskStatus('generating')
        setTaskMessage('AI 正在分析市场数据...')
      }
      pollTask(taskId, tradeDate)
    } catch (e) {
      console.error('[AI] 启动生成失败:', e)
      setError(e.response?.data?.detail || '启动生成失败')
      setTaskStatus(null)
    }
  }

  const pollTask = (taskId, tradeDate) => {
    if (pollingRef.current) clearInterval(pollingRef.current)
    pollingRef.current = setInterval(async () => {
      try {
        const task = await marketReviewApi.getAiAnalysisTask(taskId)
        if (task?.current_stock_name) {
          setTaskMessage(task.current_stock_name)
        }
        if (task?.status === 'completed') {
          clearInterval(pollingRef.current)
          pollingRef.current = null
          setTaskStatus(null)
          // 重新加载数据
          const res = await marketReviewApi.getAiAnalysis(tradeDate)
          setData(res || {})
        } else if (task?.status === 'failed') {
          clearInterval(pollingRef.current)
          pollingRef.current = null
          setTaskStatus(null)
          setError(task?.error || 'AI分析失败')
        }
      } catch (e) {
        console.error('[AI] 轮询失败:', e)
      }
    }, 2000)
  }

  if (loading || taskStatus === 'generating') {
    return (
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-8 flex flex-col items-center justify-center">
        <Spin size="large" />
        <p className="mt-4 text-sm text-gray-500 font-medium">{taskMessage || 'AI 正在分析市场数据...'}</p>
        <p className="mt-1 text-xs text-gray-400">基于欧奈尔/米内尔维尼/利弗莫尔交易哲学</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
        <div className="flex items-center space-x-2 mb-2">
          <span className="text-red-500 text-sm">⚠️</span>
          <p className="text-red-500 text-sm font-medium">AI 分析服务暂时不可用</p>
        </div>
        <p className="text-gray-500 text-xs">{error}</p>
      </div>
    )
  }

  const handleShowInputData = async () => {
    setInputDataVisible(true)
    setInputDataLoading(true)
    setInputDataContent('')
    try {
      const res = await marketReviewApi.getAiInputData(date)
      if (res?.success && res?.input_data) {
        setInputDataContent(res.input_data)
      } else {
        setInputDataContent('暂无输入数据')
      }
    } catch (e) {
      console.error('获取输入数据失败:', e)
      setInputDataContent('获取失败: ' + (e.response?.data?.detail || e.message))
    } finally {
      setInputDataLoading(false)
    }
  }

  // 从输入数据弹窗生成AI分析
  const handleGenerateFromInputData = () => {
    // 检查是否已有AI分析数据（且没有上次失败的错误）
    // 只有盘后数据才提示"无需重复生成"，盘中数据允许重新生成
    // 盘后数据判断：is_final=true 或 生成时间在16:00之后
    const isPostMarket = (data?.generated_at && new Date(data.generated_at).getHours() >= 16)
    if (!lastError && data?.source === 'deepseek' && isPostMarket) {
      setInputDataVisible(false)
      message.info('已有盘后AI分析数据，无需重复生成')
      return
    }
    setInputDataVisible(false)
    // 先设置加载状态，再调用生成
    setTaskStatus('generating')
    setTaskMessage('AI 正在分析市场数据...')
    setLastError(null)
    startGenerate(date)
  }

  const handleScreenshot = async () => {
    if (!screenshotRef.current) {
      message.warning('未找到截图区域')
      return
    }
    setScreenshotLoading(true)
    try {
      const imageData = await toPng(screenshotRef.current, {
        pixelRatio: 2,
        backgroundColor: '#ffffff',
        skipAutoScale: true,
        style: { overflow: 'visible' },
      })
      const res = await fetch('/api/screenshot/compress', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image_data: imageData, max_size_kb: 500 }),
      })
      if (!res.ok) throw new Error('压缩失败')
      const blob = await res.blob()
      const sizeKB = Math.round(blob.size / 1024)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.download = `AI综合研判_${date || 'latest'}.jpg`
      link.href = url
      link.click()
      URL.revokeObjectURL(url)
      message.success(`截图已保存 (${sizeKB}KB)`)
    } catch (err) {
      console.error('AI截图失败:', err)
      message.error('截图失败，请重试')
    } finally {
      setScreenshotLoading(false)
    }
  }

  // 无AI分析数据显示生成按钮
  if (!data?.market_phase_diagnosis) {
    // 判断是否盘后
    const isFinal = data?.is_final === true

    // 如果正在生成，显示加载状态
    if (taskStatus === 'generating') {
      return (
        <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-8 flex flex-col items-center justify-center">
          <Spin size="large" />
          <p className="mt-4 text-sm text-gray-500 font-medium">{taskMessage || 'AI 正在分析市场数据...'}</p>
          <p className="mt-1 text-xs text-gray-400">基于欧奈尔/米内尔维尼/利弗莫尔交易哲学</p>
        </div>
      )
    }

    return (
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
        {/* 输入数据弹窗 */}
        <Modal
          title="AI 分析输入数据"
          open={inputDataVisible}
          onCancel={() => setInputDataVisible(false)}
          footer={[
            <Button key="generate" type="primary" onClick={handleGenerateFromInputData} disabled={inputDataLoading || taskStatus === 'generating' || !updateAllowed}>
              {taskStatus === 'generating' ? '生成中...' : '生成AI分析'}
            </Button>
          ]}
          width={700}
          styles={{ body: { maxHeight: '70vh', overflowY: 'auto' } }}
        >
          {inputDataLoading ? (
            <div className="p-12 text-center">
              <Spin size="large" />
              <p className="mt-4 text-sm text-gray-500">加载中...</p>
            </div>
          ) : (
            <pre className="text-xs text-gray-700 whitespace-pre-wrap font-mono bg-gray-50 p-4 rounded-lg">
              {inputDataContent || '暂无输入数据'}
            </pre>
          )}
        </Modal>

        <div className="flex items-center space-x-3">
          <div className="w-1 h-4 bg-gradient-to-b from-amber-400 to-orange-500 rounded-full"></div>
          <h3 className="text-sm font-bold text-gray-800">AI 综合研判</h3>
          <button 
            onClick={handleShowInputData}
            className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 hover:bg-gray-200 hover:text-gray-700 transition-colors cursor-pointer"
          >
            查看输入数据
          </button>
        </div>
        
        {/* 显示上次失败的错误信息 */}
        {lastError && (
          <div className="mt-3 p-3 bg-red-50 rounded-lg border border-red-200">
            <div className="flex items-center space-x-2 mb-1">
              <span className="text-red-500 text-xs">⚠️</span>
              <p className="text-red-600 text-xs font-medium">上次生成失败</p>
            </div>
            <p className="text-red-500 text-xs mb-2">{lastError}</p>
            <button 
              onClick={() => { setLastError(null); startGenerate(date); }}
              className="text-[10px] px-2 py-1 rounded bg-red-100 text-red-600 hover:bg-red-200 transition-colors cursor-pointer"
              disabled={taskStatus === 'generating' || !updateAllowed}
            >
              {taskStatus === 'generating' ? '生成中...' : '重新生成'}
            </button>
          </div>
        )}
        
        {!lastError && <p className="text-gray-500 text-xs mt-3">暂无AI分析数据</p>}
      </div>
    )
  }

  const source = data.source || 'local'
  const isFallback = data.is_fallback
  const generatedAt = data.generated_at || ''
  const riskLevel = data.allocation_and_focus_model?.market_risk_level || '中'
  const riskStyle = riskColors[riskLevel] || riskColors['中']

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden border-t-4 border-t-gray-300">
      {/* 输入数据弹窗 */}
      <Modal
        title="AI 分析输入数据"
        open={inputDataVisible}
        onCancel={() => setInputDataVisible(false)}
        footer={[
          <Button key="generate" type="primary" onClick={handleGenerateFromInputData} disabled={inputDataLoading || taskStatus === 'generating' || !updateAllowed}>
            {taskStatus === 'generating' ? '生成中...' : '生成AI分析'}
          </Button>
        ]}
        width={700}
        styles={{ body: { maxHeight: '70vh', overflowY: 'auto' } }}
      >
        {inputDataLoading ? (
          <div className="p-12 text-center">
            <Spin size="large" />
            <p className="mt-4 text-sm text-gray-500">加载中...</p>
          </div>
        ) : (
          <pre className="text-xs text-gray-700 whitespace-pre-wrap font-mono bg-gray-50 p-4 rounded-lg">
            {inputDataContent || '暂无输入数据'}
          </pre>
        )}
      </Modal>

      {/* 标题栏 */}
      <div className="px-3 md:px-6 py-3 md:py-4 border-b border-gray-100 flex items-center space-x-2 md:space-x-3 flex-wrap">
        <div className="w-1 h-4 md:h-5 bg-gradient-to-b from-amber-400 to-orange-500 rounded-full"></div>
        <h2 className="text-sm md:text-base font-black text-gray-900 tracking-tight">AI 综合研判</h2>
        <button
          onClick={handleShowInputData}
          className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 hover:bg-gray-200 hover:text-gray-700 transition-colors cursor-pointer"
        >
          查看输入数据
        </button>
        <button
          onClick={handleScreenshot}
          disabled={screenshotLoading}
          className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 hover:bg-gray-200 hover:text-gray-700 transition-colors cursor-pointer inline-flex items-center space-x-0.5"
        >
          <CameraOutlined className="text-[10px]" />
          <span>{screenshotLoading ? '截图中...' : '截图'}</span>
        </button>
        <span className={`inline-block px-1.5 md:px-2 py-0.5 rounded text-[8px] md:text-[10px] font-bold mr-1 leading-none ${
          source === 'deepseek' ? 'bg-orange-100 text-orange-600' : 'bg-blue-100 text-blue-600'
        }`}>
          {source === 'deepseek' ? 'DeepSeek' : '本地'}
        </span>
        {isFallback && (
          <span className="inline-block px-1.5 md:px-2 py-0.5 rounded bg-yellow-100 text-yellow-600 text-[8px] md:text-[10px] font-bold mr-1 leading-none">
            缓存
          </span>
        )}
        <span className="hidden sm:inline-block px-1.5 md:px-2 py-0.5 rounded bg-gray-100 text-gray-500 text-[8px] md:text-[10px] font-bold mr-1 leading-none">
          O'Neil + Minervini
        </span>
        <span className={`inline-block px-1.5 md:px-2 py-0.5 rounded text-[8px] md:text-[10px] font-bold leading-none ${
          riskLevel === '高' ? 'bg-red-100 text-red-600' :
          riskLevel === '中高' ? 'bg-orange-100 text-orange-600' :
          riskLevel === '中' ? 'bg-amber-100 text-amber-600' :
          riskLevel === '中低' ? 'bg-blue-100 text-blue-600' :
          'bg-green-100 text-green-600'
        }`}>
          {riskStyle.label}
        </span>
        {generatedAt && (
          <span className="text-[8px] md:text-[10px] text-gray-400 ml-auto">
            {new Date(generatedAt).toLocaleString('zh-CN')}
          </span>
        )}
      </div>

      <div ref={screenshotRef} className="p-3 md:p-6 space-y-3 md:space-y-5">
        {/* 市场阶段诊断 */}
        {data.market_phase_diagnosis && (
          <div>
            <div className="flex items-center space-x-1.5 md:space-x-2 mb-1.5 md:mb-2">
              <span className="text-sm md:text-lg">📊</span>
              <h3 className="text-xs md:text-sm font-bold text-gray-700">市场阶段诊断</h3>
            </div>
            <div className="bg-gray-50 rounded-xl p-2.5 md:p-4 border border-gray-100">
              <p className="text-xs md:text-sm text-gray-600 leading-relaxed">
                {renderAIHighlightedText(data.market_phase_diagnosis)}
              </p>
            </div>
          </div>
        )}

        {/* 行业集群评估 */}
        {data.industry_cluster_evaluation && (
          <div>
            <div className="flex items-center space-x-1.5 md:space-x-2 mb-1.5 md:mb-2">
              <span className="text-sm md:text-lg">🏭</span>
              <h3 className="text-xs md:text-sm font-bold text-gray-700">行业集群评估</h3>
            </div>
            <div className="bg-gray-50 rounded-xl p-2.5 md:p-4 border border-gray-100">
              <p className="text-xs md:text-sm text-gray-600 leading-relaxed">
                {renderAIHighlightedText(data.industry_cluster_evaluation)}
              </p>
            </div>
          </div>
        )}

        {/* 执行策略建议 */}
        {data.execution_strategy_advice && data.execution_strategy_advice.length > 0 && (
          <div>
            <div className="flex items-center space-x-1.5 md:space-x-2 mb-1.5 md:mb-2">
              <span className="text-sm md:text-lg">⚡</span>
              <h3 className="text-xs md:text-sm font-bold text-gray-700">明日执行策略</h3>
            </div>
            <div className="bg-gray-50 rounded-xl p-2.5 md:p-4 border border-gray-100">
              <ul className="space-y-1.5 md:space-y-2">
                {data.execution_strategy_advice.map((advice, idx) => (
                  <li key={idx} className="flex items-start space-x-1.5 md:space-x-2">
                    <span className="text-[10px] md:text-xs mt-0.5">
                      {idx === 0 ? '🟢' : idx < data.execution_strategy_advice.length - 1 ? '⚠️' : '🔴'}
                    </span>
                    <span className="text-xs md:text-sm text-gray-600 leading-relaxed">
                      {renderAIHighlightedText(advice)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
        {/* 战术仓位配置 */}
        {data.allocation_and_focus_model && (
          <div className="px-3 md:px-6 pb-3 md:pb-6">
            <TacticalAllocationCard data={data} />
          </div>
        )}
      </div>
    </div>
  )
}

export default AiAnalysis
