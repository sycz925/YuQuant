import React, { useState, useEffect, useRef } from 'react'
import { Input, Spin, Empty, Modal } from 'antd'
import { SearchOutlined, ArrowLeftOutlined, AppstoreOutlined } from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { searchApi, marketReviewApi } from '../api'
import StockAnalysis from './StockAnalysis'

function SearchPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [keyword, setKeyword] = useState('')
  const [searching, setSearching] = useState(false)
  const [results, setResults] = useState({ stocks: [], sectors: [] })
  const [selectedItem, setSelectedItem] = useState(null)
  const inputRef = useRef(null)
  
  // 板块详情 Modal 状态
  const [sectorDetailVisible, setSectorDetailVisible] = useState(false)
  const [sectorDetailLoading, setSectorDetailLoading] = useState(false)
  const [sectorDetail, setSectorDetail] = useState(null)

  // 从URL参数恢复状态
  useEffect(() => {
    const code = searchParams.get('code')
    const sector = searchParams.get('sector')
    const name = searchParams.get('name')
    const keywordParam = searchParams.get('keyword')
    if (code) {
      setSelectedItem({ type: 'stock', code, name: name || code })
    } else if (sector) {
      setSelectedItem({ type: 'sector', code: sector, name: name || sector })
    } else if (keywordParam) {
      // 如果有keyword参数，设置搜索关键词并触发搜索
      setKeyword(keywordParam)
      setSelectedItem(null)
    } else {
      setSelectedItem(null)
    }
  }, [searchParams])

  useEffect(() => {
    if (!selectedItem) {
      inputRef.current?.focus()
    }
  }, [selectedItem])

  useEffect(() => {
    if (keyword.trim()) {
      const timer = setTimeout(() => {
        handleSearch(keyword)
      }, 300)
      return () => clearTimeout(timer)
    } else {
      setResults({ stocks: [], sectors: [] })
    }
  }, [keyword])

  const handleSearch = async (value) => {
    const kw = (value || keyword).trim()
    if (!kw) {
      setResults({ stocks: [], sectors: [] })
      return
    }
    setSearching(true)
    try {
      const res = await searchApi.search(kw)
      if (res?.success && res?.data) {
        setResults(res.data)
      } else {
        setResults({ stocks: [], sectors: [] })
      }
    } catch (e) {
      console.error('搜索失败:', e)
      setResults({ stocks: [], sectors: [] })
    } finally {
      setSearching(false)
    }
  }

  const handleSelect = (item) => {
    setSelectedItem(item)
    setResults({ stocks: [], sectors: [] })
    setKeyword('')
    if (item.type === 'stock') {
      navigate(`/search?code=${item.code}&name=${encodeURIComponent(item.name)}`, { replace: true })
    } else {
      navigate(`/search?sector=${item.code}&name=${encodeURIComponent(item.name)}`, { replace: true })
    }
  }

  const handleBack = () => {
    navigate('/search', { replace: true })
    setTimeout(() => inputRef.current?.focus(), 100)
  }

  // 获取板块详情
  const handleShowSectorDetail = async () => {
    if (!selectedItem || selectedItem.type !== 'sector') return
    
    setSectorDetailVisible(true)
    setSectorDetailLoading(true)
    try {
      const res = await marketReviewApi.getSectorDetail(selectedItem.code)
      if (res?.success) {
        setSectorDetail(res)
      } else {
        setSectorDetail(null)
      }
    } catch (e) {
      console.error('获取板块详情失败:', e)
      setSectorDetail(null)
    } finally {
      setSectorDetailLoading(false)
    }
  }

  const hasResults = results.stocks.length > 0 || results.sectors.length > 0

  // 如果已选中某个股票/板块，显示选中状态和行情分析
  if (selectedItem) {
    return (
      <div className="max-w-7xl mx-auto">
        <div className="bg-white rounded-2xl shadow-sm p-4 mb-4">
          <div className="flex items-center space-x-3">
            <button 
              onClick={handleBack}
              className="flex items-center text-gray-600 hover:text-blue-600 transition-colors"
            >
              <ArrowLeftOutlined className="mr-1" />
              <span className="text-sm">返回搜索</span>
            </button>
            <span className="text-gray-300">|</span>
            <span className={`text-xs px-2 py-0.5 rounded font-bold ${
              selectedItem.type === 'stock' 
                ? 'bg-blue-100 text-blue-600' 
                : 'bg-purple-100 text-purple-600'
            }`}>
              {selectedItem.type === 'stock' ? '个股' : '板块'}
            </span>
            <span className="text-sm font-medium text-gray-700">
              {selectedItem.name}
            </span>
            {/* 板块情况按钮 */}
            {selectedItem.type === 'sector' && (
              <button 
                onClick={handleShowSectorDetail}
                className="ml-auto flex items-center px-3 py-1.5 text-xs font-medium text-purple-600 bg-purple-50 rounded-lg hover:bg-purple-100 transition-colors"
              >
                <AppstoreOutlined className="mr-1" />
                板块情况
              </button>
            )}
          </div>
        </div>
        
        {/* 行情分析组件 */}
        <StockAnalysis 
          initialCode={selectedItem.code} 
          initialType={selectedItem.type}
        />

        {/* 板块详情 Modal */}
        <Modal
          title={`${selectedItem.name} - 先锋·中军·后排`}
          open={sectorDetailVisible}
          onCancel={() => setSectorDetailVisible(false)}
          footer={null}
          width={600}
        >
          {sectorDetailLoading ? (
            <div className="p-8 text-center">
              <Spin size="large" />
              <p className="mt-4 text-sm text-gray-500">加载中...</p>
            </div>
          ) : sectorDetail ? (
            <div className="space-y-4">
              <div className="text-xs text-gray-400">
                数据日期: {sectorDetail.trade_date}
              </div>
              
              {/* 先锋 */}
              <div>
                <div className="flex items-center space-x-2 mb-2">
                  <span className="text-sm font-bold text-amber-600">🔥 先锋</span>
                  <span className="text-xs text-gray-400">50日涨幅最高的3只</span>
                </div>
                <div className="space-y-1">
                  {(sectorDetail.pioneer || []).map((stock, idx) => (
                    <div key={idx} className="px-3 py-2 bg-amber-50 rounded-lg text-sm text-amber-800">
                      {stock}
                    </div>
                  ))}
                  {(!sectorDetail.pioneer || sectorDetail.pioneer.length === 0) && (
                    <div className="text-xs text-gray-400">暂无数据</div>
                  )}
                </div>
              </div>

              {/* 中军 */}
              <div>
                <div className="flex items-center space-x-2 mb-2">
                  <span className="text-sm font-bold text-blue-600">🎯 中军</span>
                  <span className="text-xs text-gray-400">流通市值Top10中50日涨幅最高</span>
                </div>
                <div className="space-y-1">
                  {(sectorDetail.main_force || []).map((stock, idx) => (
                    <div key={idx} className="px-3 py-2 bg-blue-50 rounded-lg text-sm text-blue-800">
                      {stock}
                    </div>
                  ))}
                  {(!sectorDetail.main_force || sectorDetail.main_force.length === 0) && (
                    <div className="text-xs text-gray-400">暂无数据</div>
                  )}
                </div>
              </div>

              {/* 后排 */}
              <div>
                <div className="flex items-center space-x-2 mb-2">
                  <span className="text-sm font-bold text-gray-600">📌 后排</span>
                  <span className="text-xs text-gray-400">小市值中当天涨幅最高</span>
                </div>
                <div className="space-y-1">
                  {(sectorDetail.followers || []).map((stock, idx) => (
                    <div key={idx} className="px-3 py-2 bg-gray-50 rounded-lg text-sm text-gray-700">
                      {stock}
                    </div>
                  ))}
                  {(!sectorDetail.followers || sectorDetail.followers.length === 0) && (
                    <div className="text-xs text-gray-400">暂无数据</div>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div className="p-8 text-center text-gray-400">
              暂无该板块数据
            </div>
          )}
        </Modal>
      </div>
    )
  }

  // 搜索页面
  return (
    <div className="space-y-4">
      {/* 搜索栏 */}
      <div className="bg-white rounded-2xl shadow-sm p-4 mb-4">
        <Input
          ref={inputRef}
          prefix={<SearchOutlined className="text-gray-400" />}
          placeholder="输入股票代码、名称或板块关键词"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onPressEnter={() => handleSearch(keyword)}
          size="large"
          allowClear
        />
      </div>

      {/* 搜索结果 */}
      <div className="bg-white rounded-2xl shadow-sm overflow-hidden">
        {searching ? (
          <div className="p-12 flex flex-col items-center justify-center">
            <Spin size="large" />
            <p className="mt-4 text-sm text-gray-500">搜索中...</p>
          </div>
        ) : hasResults ? (
          <div>
            {results.stocks.length > 0 && (
              <div>
                <div className="px-4 py-2 bg-gray-50 text-xs font-bold text-gray-500 uppercase">
                  股票 ({results.stocks.length})
                </div>
                <div className="divide-y divide-gray-100">
                  {results.stocks.map((item, index) => (
                    <div
                      key={`stock-${index}`}
                      className="px-4 py-3 hover:bg-blue-50 cursor-pointer flex items-center justify-between transition-colors"
                      onClick={() => handleSelect({ type: 'stock', code: item.code, name: item.name })}
                    >
                      <div className="flex items-center space-x-3">
                        <span className="text-[10px] px-2 py-1 rounded font-bold bg-blue-100 text-blue-600">股票</span>
                        <div>
                          <div className="text-sm font-medium text-gray-800">{item.name}</div>
                          <div className="text-xs text-gray-500">{item.code}</div>
                        </div>
                      </div>
                      <span className="text-gray-400 text-sm">→</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {results.sectors.length > 0 && (
              <div>
                <div className="px-4 py-2 bg-gray-50 text-xs font-bold text-gray-500 uppercase">
                  板块 ({results.sectors.length})
                </div>
                <div className="divide-y divide-gray-100">
                  {results.sectors.map((item, index) => (
                    <div
                      key={`sector-${index}`}
                      className="px-4 py-3 hover:bg-blue-50 cursor-pointer flex items-center justify-between transition-colors"
                      onClick={() => handleSelect({ type: 'sector', code: item.code, name: item.name })}
                    >
                      <div className="flex items-center space-x-3">
                        <span className="text-[10px] px-2 py-1 rounded font-bold bg-purple-100 text-purple-600">板块</span>
                        <div>
                          <div className="text-sm font-medium text-gray-800">{item.name}</div>
                        </div>
                      </div>
                      <span className="text-gray-400 text-sm">→</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : keyword ? (
          <div className="p-12">
            <Empty description="未找到匹配结果" />
          </div>
        ) : (
          <div className="p-12 text-center text-gray-400 text-sm">
            输入股票代码、名称或板块关键词进行搜索
          </div>
        )}
      </div>
    </div>
  )
}

export default SearchPage
