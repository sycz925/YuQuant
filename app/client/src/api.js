import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_BASE || '/api'

const api = axios.create({
  baseURL: API_BASE,
  timeout: 30000
})

api.interceptors.response.use(
  res => res,
  err => {
    const msg = err.response?.data?.detail || err.message || '请求失败'
    console.error('[API Error]', msg)
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
  getIndices: (params = {}) =>
    api.get('/factors/indices', { params }),
  searchIndices: (keyword) =>
    api.get('/factors/indices/search', { params: { keyword } }),
  syncSectors: (params = {}) =>
    api.post('/factors/sync-sectors', {}, { params }),
  getSectors: (params = {}) =>
    api.get('/factors/sectors', { params: { min_stock_count: 5, ...params } }),
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

export const backtestApi = {
  runBacktest: (data) => api.post('/backtest/run', data)
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
  getMaBreadth: (params = {}) => api.get('/market-review/ma-breadth', { params }),
  getReview: () => api.get('/market-review')
}

export const exclusionApi = {
  getExclusions: (params = {}) => api.get('/exclusions', { params }),
  updateExclusions: (items) => api.post('/exclusions', { items }),
  deleteExclusion: (code) => api.delete(`/exclusions/${code}`),
  getExcluded: (params = {}) => api.get('/exclusions/excluded', { params })
}

export default api
