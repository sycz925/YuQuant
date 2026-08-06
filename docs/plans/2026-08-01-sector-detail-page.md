# SectorDetail Page Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 新增板块详情页 `/sector/:code`，展示板块成分股列表（与 ETFPage 表格列一致），支持"队列概况"按钮显示先锋·中军·后排 Modal。

**Architecture:** 后端新增 `/api/factors/sectors/:code/stocks` 接口，从 `sector_basics.stock_codes` 获取成分股代码，批量查 `stock_daily` 获取行情+RPS数据。前端新建 SectorDetail 页面（参考 ETFPage 布局），复用 `marketReviewApi.getSectorDetail` 显示队列概况 Modal。SearchPage 中板块搜索结果跳转改为 `/sector/:code`。

**Tech Stack:** React + Ant Design + React Query + FastAPI + MongoDB

---

### Task 1: 后端 - 新增板块成分股 API

**Files:**
- Modify: `/app/server/api/factors.py`
- Modify: `/app/client/src/api.js`

**Step 1: 在 factors.py 中新增接口**

在 `@router.get("/sectors/{code}/daily")` 之后添加：

```python
@router.get("/sectors/{code}/stocks")
def get_sector_stocks(code: str):
    """获取板块成分股列表（含当日行情+RPS）"""
    try:
        db = get_db()

        sector_doc = db['sector_basics'].find_one(
            {'code': code},
            {'_id': 0, 'name': 1, 'stock_codes': 1, 'stock_count': 1}
        )
        if not sector_doc:
            raise HTTPException(status_code=404, detail="未找到该板块")

        stock_codes = sector_doc.get('stock_codes', [])
        if not stock_codes:
            return {
                'success': True,
                'sector_name': sector_doc.get('name', code),
                'stock_count': 0,
                'trade_date': None,
                'stocks': [],
            }

        # 获取最新交易日
        latest = db['stock_daily'].find_one(
            {'stock_code': {'$in': stock_codes[:1]},  # 用第一个代码探测
             'close': {'$gt': 0}},
            sort=[('trade_date', -1)],
            projection={'trade_date': 1, '_id': 0}
        )
        if not latest:
            return {
                'success': True,
                'sector_name': sector_doc.get('name', code),
                'stock_count': len(stock_codes),
                'trade_date': None,
                'stocks': [],
            }
        trade_date = latest['trade_date']

        # 批量查成分股行情
        cursor = db['stock_daily'].find(
            {
                'stock_code': {'$in': stock_codes},
                'trade_date': trade_date,
                'close': {'$gt': 0},
            },
            {
                '_id': 0,
                'stock_code': 1,
                'close': 1,
                'change_pct': 1,
                'chg_5d': 1,
                'chg_10d': 1,
                'chg_20d': 1,
                'chg_50d': 1,
                'chg_120d': 1,
                'rps_10': 1,
                'rps_20': 1,
                'rps_50': 1,
            }
        )

        # 查股票名称
        basics = {}
        for b in db['stock_basics'].find(
            {'stock_code': {'$in': stock_codes}},
            {'_id': 0, 'stock_code': 1, 'stock_name': 1}
        ):
            basics[b['stock_code']] = b.get('stock_name', '')

        stocks = []
        for doc in cursor:
            doc['name'] = basics.get(doc['stock_code'], doc['stock_code'])
            stocks.append(doc)

        # 按名称排序
        stocks.sort(key=lambda x: x.get('name', ''))

        return {
            'success': True,
            'sector_name': sector_doc.get('name', code),
            'stock_count': len(stock_codes),
            'trade_date': trade_date,
            'stocks': stocks,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取板块成分股失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)[:200]}")
```

**Step 2: 在 api.js 中添加前端 API 方法**

在 `getSectorDaily` 之后添加：

```javascript
getSectorStocks: (code) =>
    api.get(`/factors/sectors/${code}/stocks`),
```

**Step 3: 验证后端接口**

重启后端，测试：
```bash
curl -s "http://localhost:8000/api/factors/sectors/880579/stocks" | python3 -m json.tool
```
预期：返回 success=True, stocks 数组含成分股数据。

---

### Task 2: 前端 - 新建 SectorDetail 页面

**Files:**
- Create: `/app/client/src/pages/SectorDetail.jsx`

**Step 1: 创建 SectorDetail.jsx**

```jsx
import React, { useState } from 'react'
import { Table, Tag, Button, Modal, Spin, message } from 'antd'
import { ArrowLeftOutlined, TeamOutlined } from '@ant-design/icons'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { factorsApi, marketReviewApi } from '../api'

const COLORS = {
  red: '#ef4444',
  orange: '#f97316',
  green: '#22c55e',
  gray: '#9ca3af',
}

function rpsColor(v) {
  if (v >= 90) return COLORS.red
  if (v >= 80) return COLORS.orange
  if (v <= 20) return COLORS.green
  return COLORS.gray
}

function SectorDetail() {
  const navigate = useNavigate()
  const { code } = useParams()
  const [searchParams] = useSearchParams()
  const sectorName = searchParams.get('name') || code

  const [queueVisible, setQueueVisible] = useState(false)
  const [queueData, setQueueData] = useState(null)
  const [queueLoading, setQueueLoading] = useState(false)

  const { data, isFetching } = useQuery({
    queryKey: ['sector_stocks', code],
    queryFn: () => factorsApi.getSectorStocks(code).then(r => r.data || {}),
  })

  const stocks = data?.stocks || []
  const tradeDate = data?.trade_date || ''

  const handleShowQueue = async () => {
    setQueueVisible(true)
    setQueueLoading(true)
    try {
      const res = await marketReviewApi.getSectorDetail(code)
      setQueueData(res?.success ? res : null)
    } catch {
      setQueueData(null)
    } finally {
      setQueueLoading(false)
    }
  }

  const columns = [
    { title: '代码', dataIndex: 'stock_code', width: 100, render: v => <span className="font-mono text-gray-500 text-xs">{v}</span> },
    {
      title: '名称', dataIndex: 'name', width: 160,
      render: (v, r) => (
        <button onClick={() => navigate(`/search?stock=${r.stock_code}`)} className="text-blue-600 hover:text-blue-800 text-left text-sm">
          {v}
        </button>
      ),
    },
    {
      title: '最新价', dataIndex: 'close', width: 90, sorter: (a, b) => a.close - b.close,
      render: v => <span className="text-sm">{v?.toFixed(2)}</span>,
    },
    {
      title: '日涨幅', dataIndex: 'change_pct', width: 90, sorter: (a, b) => (a.change_pct || 0) - (b.change_pct || 0),
      render: v => <span style={{ color: v > 0 ? COLORS.red : v < 0 ? COLORS.green : COLORS.gray }}>{v > 0 ? '+' : ''}{v?.toFixed(2)}%</span>,
    },
    ...['5d', '10d', '20d', '50d', '120d'].map(d => ({
      title: `${d === '5d' ? '5' : d === '10d' ? '10' : d === '20d' ? '20' : d === '50d' ? '50' : '120'}日涨幅`,
      dataIndex: `chg_${d}`,
      width: 90,
      sorter: (a, b) => (a[`chg_${d}`] || 0) - (b[`chg_${d}`] || 0),
      render: v => v != null ? <span style={{ color: v > 0 ? COLORS.red : v < 0 ? COLORS.green : COLORS.gray }}>{v > 0 ? '+' : ''}{v.toFixed(2)}%</span> : '-',
    })),
    ...['10', '20', '50'].map(d => ({
      title: `RPS${d}`,
      dataIndex: `rps_${d}`,
      width: 75,
      sorter: (a, b) => (a[`rps_${d}`] || 0) - (b[`rps_${d}`] || 0),
      render: v => v != null ? <span className="text-xs font-bold" style={{ color: rpsColor(v) }}>{v}</span> : '-',
    })),
  ]

  return (
    <div className="max-w-7xl mx-auto space-y-4">
      {/* 顶部操作栏 */}
      <div className="bg-white rounded-2xl shadow-sm p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <button onClick={() => navigate(-1)} className="flex items-center text-gray-600 hover:text-blue-600 transition-colors">
              <ArrowLeftOutlined className="mr-1" />
              <span className="text-sm">返回</span>
            </button>
            <span className="text-gray-300">|</span>
            <span className="text-xs px-2 py-0.5 rounded font-bold bg-purple-100 text-purple-600">板块</span>
            <span className="text-base font-bold" style={{ fontFamily: 'Fira Sans' }}>{sectorName}</span>
            {tradeDate && <span className="text-xs text-gray-400">{tradeDate}</span>}
            {data?.stock_count > 0 && <Tag className="ml-1">{data.stock_count}只</Tag>}
          </div>
          <Button icon={<TeamOutlined />} onClick={handleShowQueue} size="small">队列概况</Button>
        </div>
      </div>

      {/* 成分股表格 */}
      <div className="bg-white rounded-2xl shadow-sm p-4">
        <Table
          dataSource={stocks}
          columns={columns}
          rowKey="stock_code"
          loading={isFetching}
          size="small"
          pagination={{ pageSize: 50, showSizeChanger: true, showTotal: t => `共 ${t} 只` }}
          scroll={{ x: 1200 }}
        />
      </div>

      {/* 队列概况 Modal */}
      <Modal
        title={`${sectorName} - 先锋·中军·后排`}
        open={queueVisible}
        onCancel={() => setQueueVisible(false)}
        footer={null}
        width={600}
      >
        {queueLoading ? (
          <div className="p-8 text-center"><Spin size="large" /><p className="mt-4 text-sm text-gray-500">加载中...</p></div>
        ) : queueData ? (
          <div className="space-y-4">
            <div className="text-xs text-gray-400">数据日期: {queueData.trade_date}</div>
            {[
              { key: 'pioneer', label: '🔥 先锋', desc: '50日涨幅最高的3只', color: 'amber' },
              { key: 'main_force', label: '🎯 中军', desc: '流通市值Top10中50日涨幅最高', color: 'blue' },
              { key: 'followers', label: '📌 后排', desc: '小市值中当天涨幅最高', color: 'gray' },
            ].map(({ key, label, desc, color }) => (
              <div key={key}>
                <div className="flex items-center space-x-2 mb-2">
                  <span className={`text-sm font-bold text-${color}-600`}>{label}</span>
                  <span className="text-xs text-gray-400">{desc}</span>
                </div>
                <div className="space-y-1">
                  {(queueData[key] || []).map((s, i) => (
                    <div key={i} className={`px-3 py-2 bg-${color}-50 rounded-lg text-sm text-${color}-800`}>{s}</div>
                  ))}
                  {(!queueData[key] || queueData[key].length === 0) && <div className="text-xs text-gray-400">暂无数据</div>}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="p-8 text-center text-gray-400">暂无该板块数据</div>
        )}
      </Modal>
    </div>
  )
}

export default SectorDetail
```

**Step 2: 验证页面可渲染（无需后端数据）**

前端编译无报错即可。

---

### Task 3: 前端 - 添加路由

**Files:**
- Modify: `/app/client/src/App.jsx`

**Step 1: 在 App.jsx 中添加 SectorDetail 导入和路由**

在 imports 区域添加：
```javascript
import SectorDetail from './pages/SectorDetail'
```

在路由配置中添加（在 `/etf` 路由之后）：
```jsx
<Route path="/sector/:code" element={<SectorDetail />} />
```

**Step 2: 验证路由生效**

访问 `http://localhost:3000/sector/880579?name=智谱AI`，页面应渲染（数据可能为空如果后端未启动）。

---

### Task 4: 修改 SearchPage - 板块跳转

**Files:**
- Modify: `/app/client/src/pages/SearchPage.jsx`

**Step 1: 修改 SearchPage 中板块结果的点击行为**

找到搜索结果中板块的点击处理，将打开 Modal 改为跳转：

搜索 `handleShowSectorDetail` 函数和调用处，将：
```jsx
<Button onClick={handleShowSectorDetail}>板块情况</Button>
```
改为：
```jsx
<Button onClick={() => navigate(`/sector/${item.code}?name=${encodeURIComponent(item.name)}`)}>板块情况</Button>
```

同时删除 `sectorDetailVisible`、`sectorDetail`、`sectorDetailLoading` 相关 state 和 Modal 代码（不再需要）。

**Step 2: 验证跳转**

在搜索框输入板块名（如"智谱AI"），点击搜索结果中的"板块情况"按钮，应跳转到 `/sector/880579?name=智谱AI`。

---

### Task 5: 整体验证

**Step 1: 启动前后端，完整流程测试**

1. 访问 `http://localhost:3000/`，点击7月日历
2. 点击某天（如7月31日），查看市场数据
3. 搜索"智谱AI"，点击板块结果 → 应跳转到 `/sector/880579?name=智谱AI`
4. 板块详情页显示成分股列表（代码、名称、最新价、涨幅、RPS）
5. 点击"队列概况"按钮 → 弹出先锋·中军·后排 Modal
6. 点击成分股名称 → 跳转到 `/search?stock=xxx`

**Step 2: 检查边界情况**

- 不存在的板块代码 → 显示"未找到该板块"
- 成分股为空的板块 → 显示空表格
- 无 RPS 数据的股票 → 显示 "-"

---

## Commit

完成后提交：
```bash
git add app/server/api/factors.py app/client/src/api.js app/client/src/pages/SectorDetail.jsx app/client/src/App.jsx app/client/src/pages/SearchPage.jsx
git commit -m "feat: 新增板块详情页/sector/:code，展示成分股列表+队列概况Modal"
```
