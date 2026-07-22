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
    api.get('/factors/rps', { params: { trade_date: date, ...params } }),
  updateDisableStatus: (items) =>
    api.post('/factors/disable', items),
  createItem: (item) =>
    api.post('/factors/create', item),
  getStockList: (params = {}) =>
    api.get('/stocks', { params }),
  compareStocksStart: () =>
    api.post('/factors/compare-stocks'),
  compareSectorsStart: () =>
    api.post('/factors/compare-sectors'),
  compareStatus: (taskId) =>
    api.get(`/factors/compare-status/${taskId}`),
  getDeepseekTimeLimit: () =>
    api.get('/factors/config/deepseek-time-limit'),
  setDeepseekTimeLimit: (enabled) =>
    api.post(`/factors/config/deepseek-time-limit?enabled=${enabled}`),
  importStocks: (stocks) =>
    api.post('/factors/import-stocks', stocks),
  importSectors: (sectors) =>
    api.post('/factors/import-sectors', sectors),
  importSectorCodes: (formData) =>
    api.post('/factors/sectors/import-excel', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    }),
  clearSyncTasks: () => api.post('/factors/clear-sync-tasks')
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
  getActiveSectors: (date) => api.get('/market-review/active-sectors', { params: { date } }),
  getBaseData: (params = {}) => api.get('/market-review/base-data', { params }),
  getAiAnalysis: (date) => api.get('/market-review/ai-analysis', { params: { date } }),
  generateAiAnalysis: (date) => api.post('/market-review/ai-analysis/generate', null, { params: { date } }),
  getAiAnalysisTask: (taskId) => api.get(`/market-review/ai-analysis/task/${taskId}`),
  getAiInputData: (date) => api.get('/market-review/ai-analysis/input-data', { params: { date } }),
  getGroupStats: (date) => api.get('/market-review/group-stats', { params: { date } }),
  getSectorDetail: (sectorCode) => api.get('/market-review/sector-detail', { params: { sector_code: sectorCode } }),
  getReview: () => api.get('/market-review')
}

export const calendarApi = {
  getDailySummary: (year, month) => api.get('/calendar/daily-summary', { params: { year, month } }),
  getLatestTradeDate: () => api.get('/calendar/latest-trade-date'),
  getTradingDays: (startDate, endDate) => api.get('/calendar/trading-days', { params: { start_date: startDate, end_date: endDate } }),
  getWeekStatus: (year, month) => api.get('/calendar/week-status', { params: { year, month } }),
  getWeeklyCached: (year, month, weekIndex) => api.get('/calendar/weekly-cached', { params: { year, month, week_index: weekIndex } }),
  getWeeklySummary: (year, month, weekIndex) => api.post('/calendar/weekly-summary', null, { params: { year, month, week_index: weekIndex } }),
  getWeeklyTask: (taskId) => api.get(`/calendar/weekly-task/${taskId}`),
  getWeeklyInputData: (year, month, weekIndex) => api.get('/calendar/weekly-input-data', { params: { year, month, week_index: weekIndex } }),
  getMonthlyCached: (year, month) => api.get('/calendar/monthly-cached', { params: { year, month } }),
  getMonthlySummary: (year, month) => api.post('/calendar/monthly-summary', null, { params: { year, month } }),
  getMonthlyTask: (taskId) => api.get(`/calendar/monthly-task/${taskId}`),
  getMonthlyInputData: (year, month) => api.get('/calendar/monthly-input-data', { params: { year, month } }),
  // 月度重算
  recalculateMonth: (year, month) => api.post('/calendar/recalculate-month', null, { params: { year, month } }),
  getMonthlyRecalcStatus: () => api.get('/calendar/recalculate-month/status'),
  // AI分析补全
  fillAiAnalysis: (year, month) => api.post('/calendar/fill-ai-analysis', null, { params: { year, month } }),
  getMonthlyAiStatus: () => api.get('/calendar/fill-ai-analysis/status'),
  // 通用任务查询
  getTaskStatus: (taskId) => api.get(`/calendar/task/${taskId}`),
}

export const searchApi = {
  search: (keyword) => api.get('/search', { params: { keyword } })
}

export const oneClickUpdateApi = {
  start: () => api.post('/one-click-update/start'),
  checkSyncTime: () => api.get('/one-click-update/sync-time-check'),
  recalculateDate: (targetDate) => api.post('/one-click-update/recalculate-date', null, { params: { target_date: targetDate } }),
}

// 任务状态查询统一使用 taskApi

// 通用任务查询
export const taskApi = {
  getTaskStatus: (taskId) => api.get(`/calendar/task/${taskId}`)
}

export default api
