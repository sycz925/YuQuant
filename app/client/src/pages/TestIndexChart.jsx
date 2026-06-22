import React, { useState, useEffect } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, Area, AreaChart, ReferenceLine } from 'recharts'
import { factorApi } from '../api'

const formatDate = (dateStr) => {
  if (!dateStr) return dateStr
  const s = String(dateStr)
  if (s.length === 8) {
    return `${s.slice(2, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`
  }
  return s
}

const TestIndexChart = () => {
  const [data, setData] = useState([])
  const [indexData, setIndexData] = useState({})
  const [indexConfig, setIndexConfig] = useState([
    { code: '000001', name: '上证指数' },
    { code: '399006', name: '创业板指' },
    { code: '000688', name: '科创50' },
    { code: '000905', name: '中证500' },
    { code: '399106', name: '深圳综指' },
    { code: '880003', name: '平均股价' },
  ])
  const [selectedIndex, setSelectedIndex] = useState('000001')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const loadData = async () => {
      try {
        const res = await factorApi.getCr5({ include_index: true })
        
        const cr5List = res.data
        
        // 保存指数配置和数据
        if (res.index_config) {
          setIndexConfig(res.index_config)
        }
        if (res.index_data) {
          setIndexData(res.index_data)
        }
        
        const indexList = res.index_data?.[selectedIndex] || []
        
        console.log('=== 调试信息 ===')
        console.log('CR5数据:', cr5List.length, '条')
        console.log('指数数据:', indexList.length, '条')
        
        // 创建日期映射
        const indexMap = {}
        indexList.forEach(item => {
          indexMap[item.trade_date] = item.value
        })
        
        // 合并数据
        const mergedData = cr5List.map(item => ({
          date: item.trade_date,
          cr5Value: item.value,
          shValue: indexMap[item.trade_date],
          normal: item.value < 50 ? item.value : 50,
          crowded: item.value >= 50 ? item.value : 50,
        }))
        
        console.log('合并后数据:', mergedData.length, '条')
        console.log('前3条数据:', mergedData.slice(0, 3))
        console.log('有指数值的数量:', mergedData.filter(d => d.shValue != null).length)
        
        setData(mergedData)
      } catch (e) {
        console.error('加载失败:', e)
      } finally {
        setLoading(false)
      }
    }

    loadData()
  }, [])

  const handleIndexChange = (indexCode) => {
    setSelectedIndex(indexCode)
    
    // 更新数据
    if (data.length > 0 && indexData[indexCode]) {
      const indexList = indexData[indexCode]
      const indexMap = {}
      indexList.forEach(item => {
        indexMap[item.trade_date] = item.value
      })
      
      const updatedData = data.map(item => ({
        ...item,
        shValue: indexMap[item.trade_date]
      }))
      
      setData(updatedData)
    }
  }
  
  // 获取当前选择的指数名称
  const selectedIndexName = indexConfig.find(c => c.code === selectedIndex)?.name || '上证指数'

  if (loading) {
    return (
      <div className="flex justify-center items-center h-96 text-gray-600">
        加载中...
      </div>
    )
  }

  return (
    <div className="p-6">
      <h1 className="text-3xl font-bold text-gray-800 mb-6">📊 指数叠加测试页面</h1>
      
      <div className="bg-white rounded-2xl shadow-lg p-6">
        <div className="flex items-center justify-between mb-4 flex-wrap gap-4">
          <h2 className="text-xl font-semibold">CR5% + 大盘指数</h2>
          <div className="flex items-center space-x-4 text-sm flex-wrap gap-4">
            <div className="flex items-center">
              <span className="w-3 h-3 rounded-full bg-blue-500 mr-2"></span>
              <span>CR5%</span>
            </div>
            <div className="flex items-center">
              <span className="w-3 h-3 rounded-full bg-orange-500 mr-2"></span>
              <span>大盘指数(归一化)</span>
            </div>
            {/* 指数选择器 */}
            {indexConfig.length > 0 && (
              <div className="flex items-center space-x-2">
                <label className="text-gray-600 font-medium">选择指数：</label>
                <select
                  value={selectedIndex}
                  onChange={(e) => handleIndexChange(e.target.value)}
                  className="px-3 py-1 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 bg-white"
                >
                  {indexConfig.map(config => (
                    <option key={config.code} value={config.code}>
                      {config.name}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>
        </div>
        
        <ResponsiveContainer width="100%" height={500}>
          <LineChart data={data} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="4 4" stroke="#e5e7eb" vertical={false}/>
            
            <XAxis 
              dataKey="date" 
              tick={{ fontSize: 12, fill: '#6b7280' }}
              tickFormatter={formatDate}
              interval={Math.floor(data.length / 12)}
              axisLine={{ stroke: '#e5e7eb' }}
              tickLine={false}
            />
            
            <YAxis 
              domain={[0, 100]} 
              tick={{ fontSize: 12, fill: '#6b7280' }}
              tickFormatter={(value) => `${value}%`}
              axisLine={{ stroke: '#e5e7eb' }}
              tickLine={false}
            />
            
            <Tooltip 
              content={({ active, payload }) => {
                if (active && payload && payload.length) {
                  return (
                    <div className="bg-white rounded-lg shadow-xl border border-gray-200 p-3">
                      {payload.map((entry, index) => (
                        <div key={index} className="mb-1">
                          <span style={{ color: entry.color }}>{entry.name}: </span>
                          <span className="font-semibold">{entry.value?.toFixed(2)}</span>
                        </div>
                      ))}
                    </div>
                  );
                }
                return null;
              }}
            />
            
            <Legend iconType="circle" />
            
            {/* 警戒线 */}
            <ReferenceLine 
              y={50} 
              stroke="#ef4444" 
              strokeDasharray="5 5"
              strokeWidth={2}
              label={{ 
                value: '警戒线', 
                position: 'top',
                fill: '#ef4444',
                fontSize: 12,
                fontWeight: 'bold'
              }} 
            />
            
            {/* CR5线 */}
            <Line 
              type="monotone" 
              dataKey="cr5Value" 
              stroke="#3b82f6" 
              strokeWidth={3}
              dot={false}
              activeDot={false}
              name="CR5%"
            />
            
            {/* 上证指数线 */}
            <Line 
              type="monotone" 
              dataKey="shValue" 
              stroke="#ff9800" 
              strokeWidth={2.5}
              dot={false}
              activeDot={false}
              name={selectedIndexName}
              strokeOpacity={0.9}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      
      <div className="mt-6 bg-gray-50 rounded-xl p-4">
        <h3 className="font-semibold mb-2">调试信息</h3>
        <p>数据总数: {data.length}</p>
        <p>有指数值的数量: {data.filter(d => d.shValue != null).length}</p>
        <p>日期范围: {data[0]?.date} ~ {data[data.length - 1]?.date}</p>
        
        <h3 className="font-semibold mt-4 mb-2">数据示例（前5条）</h3>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b">
                <th className="text-left py-1 px-2">日期</th>
                <th className="text-left py-1 px-2">CR5%</th>
                <th className="text-left py-1 px-2">上证指数(归一化)</th>
              </tr>
            </thead>
            <tbody>
              {data.slice(0, 5).map((item, i) => (
                <tr key={i} className="border-b border-gray-200">
                  <td className="py-1 px-2">{item.date}</td>
                  <td className="py-1 px-2">{item.cr5Value?.toFixed(2)}</td>
                  <td className="py-1 px-2">{item.shValue?.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

export default TestIndexChart
