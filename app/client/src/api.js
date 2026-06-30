import axios from 'axios'
import { message } from 'antd'

const API_BASE = import.meta.env.VITE_API_BASE || '/api'

const api = axios.create({
  baseURL: API_BASE,
  timeout: 30000
})

// ---- 错误 Toast 防抖 ----
let _lastToastTime = 0
const TOAST_DEBOUNCE_MS = 2000

function showErrorToast(msg) {
  const now = Date.now()
  if (now - _lastToastTime < TOAST_DEBOUNCE_MS) return
  _lastToastTime = now
  message.error(msg)
}

// ---- 响应拦截器 ----
api.interceptors.response.use(
  res => res.data,
  err => {
    const url = err.config?.url || ''
    const isHealthCheck = url.includes('/health')

    const msg = err.response?.data?.detail || err.message || '请求失败'

    if (isHealthCheck) {
      console.warn('[Health Check]', msg)
    } else {
      console.error('[API Error]', msg)
      showErrorToast(msg)
    }

    return Promise.reject(err)
  }
)

export const stockApi = {
  getStockList: (params = {}) => api.get('/stocks', { params }),
  searchStocks: (keyword) => api.get('/stocks/search', { params: { keyword } }),
  scanNewStocks: () => api.post('/stocks/scan'),
  getStockDetail: (code) => api.get(`/stocks/${code}`),
  getDailyData: (code, startDate, endDate, limit) =>
    api.get(`/stocks/${code}/daily`, { params: { startDate, endDate, limit } })
}

export const factorApi = {
  getCr5: (params = {}) =>
    api.get('/factors/cr5', { params }),
  syncIndices: (params = {}) =>
    api.post('/factors/sync-indices', {}, { params }),
  syncIndexPE: (token) =>
    api.post('/factors/sync-index-pe', {}, { params: { token } }),
  precomputeBase: () =>
    api.post('/factors/precompute-base'),
  getIndices: (params = {}) =>
    api.get('/factors/indices', { params }),
  searchIndices: (keyword) =>
    api.get('/factors/indices/search', { params: { keyword } }),
  syncSectors: (params = {}) =>
    api.post('/factors/sync-sectors', {}, { params }),
  getSectors: (params = {}) =>
    api.get('/factors/sectors', { params: { min_stock_count: 5, ...params } }),
  getSectorDaily: (code, startDate, endDate, limit) =>
    api.get(`/factors/sectors/${code}/daily`, { params: { start_date: startDate, end_date: endDate, limit } }),
  importSectorCodes: (formData) =>
    api.post('/factors/sectors/import-codes', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    }),
  calculateRPS: (params = {}) =>
    api.post('/factors/rps/calculate', {}, { params }),
  clearTasks: () =>
    api.post('/factors/tasks/clear'),
  clearRps: (params = {}) =>
    api.delete('/factors/rps', { params }),
  getStockRPS: (code, params = {}) =>
    api.get(`/factors/rps/${code}`, { params }),
  getRPSByDate: (date, params = {}) =>
    api.get('/factors/rps', { params: { trade_date: date, ...params } })
}

export const syncApi = {
  syncBasics: () => api.post('/sync/basics'),
  syncDaily: (data) => api.post('/sync/daily', data),
  syncAllDaily: (data) => api.post('/sync/daily/all', data),
  getTaskStatus: (taskId) => api.get(`/sync/task/${taskId}`),
  cancelTask: (taskId) => api.delete(`/sync/task/${taskId}`),
  patchIsFinal: () => api.post('/sync/patch_is_final')
}

export const healthApi = {
  check: () => api.get('/health')
}

export const marketAnalysisApi = {
  getAnalysis: (params = {}) => api.get('/market_analysis', { params }),
  getBubble: (params = {}) => api.get('/market_analysis/bubble', { params }),
  getActivePool: (params = {}) => api.get('/market_analysis/active_pool', { params })
}

export const marketReviewApi = {
  getOverview: (date) => api.get('/market-review/overview', { params: { date } }),
  getSignals: (date) => api.get('/market-review/signals', { params: { date } }),
  getNewHighBlocks: (date) => api.get('/market-review/new-high-blocks', { params: { date } }),
  getLowPositionSectors: (date) => api.get('/market-review/low-position-sectors', { params: { date } }),
  getBaseData: (params = {}) => api.get('/market-review/base-data', { params }),
  getAiAnalysis: (date) => api.get('/market-review/ai-analysis', { params: { date } }),
  generateAiAnalysis: (date) => api.post('/market-review/ai-analysis/generate', null, { params: { date } }),
  getAiAnalysisTask: (taskId) => api.get(`/market-review/ai-analysis/task/${taskId}`),
  getReview: () => api.get('/market-review')
}

export const exclusionApi = {
  getExclusions: (params = {}) => api.get('/exclusions', { params }),
  updateExclusions: (items) => api.post('/exclusions', { items }),
  deleteExclusion: (code) => api.delete(`/exclusions/${code}`),
  getExcluded: (params = {}) => api.get('/exclusions/excluded', { params })
}

export default api
