# 重点关注列表（Watchlist）实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 新增"重点关注列表"，用户可通过 code 添加/删除个股与 ETF，列表字段对齐 /etf 页面并保留 RPS 红筛选。

**Architecture:** MongoDB 新集合 `watchlist` 存 (code, type)，后端新建 `/api/watchlist` 路由（GET 列表+最新行情 / POST 添加 / DELETE 删除），行情分别从 stock_daily / etf_daily 按 type 读取，字段统一。前端新增 `/watchlist` 页面 + 导航入口，接口封装到 api.js。

**Tech Stack:** FastAPI + MongoDB (+pymongo)、React (Vite + antd + react-query)、axios。

**设计文档:** `docs/plans/2026-08-05-watchlist-design.md`

**验证基线:** 本仓库无 pytest 测试框架，用 curl 调用 API 做端到端验证。

---

### Task 1: 数据库层（watchlist 集合 + 唯一索引）

**Files:**
- Modify: `app/data/db.py:64`（新增索引）

**Step 1: 添加 watchlist 唯一索引**

在 `_create_indexes` 内 `etf_basics` 索引之后追加：

```python
    # 重点关注列表索引（同一 code+type 只能存在一条）
    db['watchlist'].create_index([('code', ASCENDING), ('type', ASCENDING)], unique=True)
```

**Step 2: 验证**

Run: `source venv/bin/activate && python -c "from app.data.db import get_db; db=get_db(); print(db['watchlist'].index_information())"`
Expected: 输出包含 `code_1_type_1` 唯一索引

**Step 3: Commit**

```bash
git add app/data/db.py
git commit -m "feat: watchlist 集合唯一索引"
```

---

### Task 2: Pydantic 模型

**Files:**
- Modify: `app/server/models.py`（在 EtfListResponse 之后追加）

**Step 1: 添加模型**

```python
class WatchlistAddRequest(BaseModel):
    """添加重点关注请求"""
    code: str = Field(..., description="股票或ETF代码")

class WatchlistItem(BaseModel):
    """重点关注列表项(含最新行情)"""
    code: str = Field(..., description="代码")
    name: str = Field(..., description="名称")
    type: str = Field(..., description="类型: stock/etf")
    close: Optional[float] = Field(None, description="最新价")
    change_pct: Optional[float] = Field(None, description="日涨幅%")
    chg_5d: Optional[float] = Field(None, description="5日涨幅%")
    chg_10d: Optional[float] = Field(None, description="10日涨幅%")
    chg_20d: Optional[float] = Field(None, description="20日涨幅%")
    chg_50d: Optional[float] = Field(None, description="50日涨幅%")
    chg_120d: Optional[float] = Field(None, description="120日涨幅%")
    rps_10: Optional[int] = Field(None, description="RPS 10日")
    rps_20: Optional[int] = Field(None, description="RPS 20日")
    rps_50: Optional[int] = Field(None, description="RPS 50日")

class WatchlistResponse(BaseModel):
    """重点关注列表响应"""
    total: int = Field(..., description="总数")
    data: List[WatchlistItem] = Field(..., description="列表")
```

注意：`Optional`、`List`、`BaseModel`、`Field` 均已在 models.py 顶部 import。

**Step 3: 验证**

Run: `source venv/bin/activate && python -c "from app.server.models import WatchlistItem, WatchlistResponse; print('OK', WatchlistItem(code='1', name='x', type='stock'))"`
Expected: `OK code='1' name='x' type='stock' close=None ...` (正常实例化)

**Step 4: Commit**

```bash
git add app/server/models.py
git commit -m "feat: watchlist Pydantic 模型"
```

---

### Task 3: 后端 API watchlist.py

**Files:**
- Create: `app/server/api/watchlist.py`

**Step 1: 创建路由文件**（完整代码）

```python
"""
重点关注列表API
"""
import logging
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError

from app.data.db import get_db, get_collection
from app.server.models import WatchlistAddRequest, WatchlistItem, WatchlistResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])

# 列表行情字段投影（与 /etf 一致）
_QUOTE_FIELDS = {
    'close': 1, 'chg_pct': 1, 'chg_5d': 1, 'chg_10d': 1, 'chg_20d': 1,
    'chg_50d': 1, 'chg_120d': 1, 'rps_10': 1, 'rps_20': 1, 'rps_50': 1, '_id': 0,
}


def _resolve(entry: dict) -> WatchlistItem:
    """将 watchlist 条目解析为带行情与名称的列表项"""
    code = entry['code']
    typ = entry.get('type', 'etf')
    if typ == 'etf':
        basic = get_db()['etf_basics'].find_one({'code': code}, {'_id': 0, 'name': 1})
        name = basic['name'] if basic else code
        coll = get_collection('etf')
    else:
        basic = get_db()['stock_basics'].find_one({'stock_code': code}, {'_id': 0, 'stock_name': 1})
        name = basic['stock_name'] if basic else code
        coll = get_collection('stock')
    latest = coll.find_one(
        {'stock_code': code, 'close': {'$gt': 0}},
        sort=[('trade_date', -1)],
        projection=_QUOTE_FIELDS,
    )
    if latest:
        return WatchlistItem(code=code, name=name, type=typ, **{k: latest.get(k) for k in _QUOTE_FIELDS if k != '_id'})
    return WatchlistItem(code=code, name=name, type=typ)


@router.get("", response_model=WatchlistResponse)
def get_watchlist(
    keyword: Optional[str] = Query(None, description="搜索关键词"),
    sort_by: Optional[str] = Query(None, description="排序字段"),
    sort_order: Optional[str] = Query("desc", description="排序方向"),
    rps_red: Optional[str] = Query(None, description="RPS红筛选: one/two/three"),
):
    """获取重点关注列表（含最新行情）"""
    db = get_db()
    entries = list(db['watchlist'].find({}, {'_id': 0}).sort('created_at', 1))
    items = [_resolve(e) for e in entries]

    # 搜索过滤
    if keyword:
        kw = keyword.lower()
        items = [i for i in items if kw in i.code.lower() or kw in i.name.lower()]

    # RPS红筛选（阈值87，与 /etf 一致）
    if rps_red in ('one', 'two', 'three'):
        rps_threshold = 87
        filtered = []
        for item in items:
            rps_values = [v for v in (item.rps_10, item.rps_20, item.rps_50) if v is not None]
            red_count = sum(1 for v in rps_values if v > rps_threshold)
            if rps_red == 'one' and red_count >= 1:
                filtered.append(item)
            elif rps_red == 'two' and red_count >= 2:
                filtered.append(item)
            elif rps_red == 'three' and red_count >= 3:
                filtered.append(item)
        items = filtered

    # 排序
    if sort_by and sort_by in ('change_pct', 'chg_5d', 'chg_10d', 'chg_20d', 'chg_50d', 'chg_120d', 'close', 'rps_10', 'rps_20', 'rps_50'):
        reverse = sort_order != 'asc'
        items.sort(key=lambda x: getattr(x, sort_by) or 0, reverse=reverse)

    return WatchlistResponse(total=len(items), data=items)


@router.post("", status_code=201)
def add_watchlist(req: WatchlistAddRequest):
    """添加代码到重点关注（自动识别个股/ETF）"""
    code = req.code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="代码不能为空")
    db = get_db()
    if db['etf_basics'].find_one({'code': code}, {'_id': 1}):
        typ = 'etf'
    elif db['stock_basics'].find_one({'stock_code': code}, {'_id': 1}):
        typ = 'stock'
    else:
        raise HTTPException(status_code=400, detail="未找到该代码")
    try:
        db['watchlist'].insert_one({'code': code, 'type': typ, 'created_at': datetime.now()})
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="已在列表中")
    return {'success': True, 'code': code, 'type': typ}


@router.delete("/{code}")
def remove_watchlist(code: str):
    """从重点关关注删除"""
    db = get_db()
    r = db['watchlist'].delete_one({'code': code})
    if not r.deleted_count:
        raise HTTPException(status_code=404, detail="不在列表中")
    return {'success': True, 'code': code}
```

**Step 4: 注册路由**

Modify `app/server/main.py:141`（`settings_tasks.router` 之后）追加：

```python
from app.server.api import watchlist
app.include_router(watchlist.router)
```

**Step 5: 验证语法**

Run: `source venv/bin/activate && python -c "import app.server.api.watchlist as m; print('OK', m.router.prefix)"`
Expected: `OK /api/watchlist`（无语法/导入错误）

**Step 6: Commit**

```bash
git add app/server/api/watchlist.py app/server/main.py
git commit -m "feat: watchlist API (获取/添加/删除)"
```

---

### Task 5: 后端 curl 全链路验证

**Files:** 无（验证用）

**Step 1: 重启服务**

```bash
kill -9 $(lsof -ti:8000 -sTCP:LISTEN) 2>/dev/null; sleep 1
(source venv/bin/activate && nohup python -m uvicorn app.server.main:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 30 > logs/server.log 2>&1 &)
sleep 8
```

**Step 2: 添加有效 ETF 与个股，无效 code**

```bash
curl -s -X POST http://localhost:8000/api/watchlist -H 'Content-Type: application/json' -d '{"code":"510300"}'   # 期望 {"success":true,"code":"510300","type":"etf"}
curl -s -X POST http://localhost:8000/api/watchlist -H 'Content-Type: application/json' -d '{"code":"600519"}'   # 期望 type:stock
curl -s -X POST http://localhost:8000/api/watchlist -H 'Content-Type: application/json' -d '{"code":"999999"}'   # 期望 400 未找到该代码
curl -s -X POST http://localhost:8000/api/watchlist -H 'Content-Type: application/json' -d '{"code":"510300"}'   # 期望 409 已在列表中
```

**Step 3: 列表读取（含行情 + 红筛选）**

```bash
curl -s http://localhost:8000/api/watchlist          # 期望 data 含 code/name/type/close/rps_*
curl -s "http://localhost:8000/api/watchlist?rps_red=one"  # 期望只返回红筛选命中项
```

**Step 4: 删除**

```bash
curl -s -X DELETE http://localhost:8000/api/watchlist/600519   # 期望 success
curl -s -X DELETE http://localhost:8000/api/watchlist/600519   # 期望 404
```

**Step 5: 清空测试数据**

```bash
curl -s -X DELETE http://localhost:8000/api/watchlist/510300
```

**Step 6: Commit（无产物变更，跳过提交）**

---

### Task 6: 前端 api.js 封装 + WatchlistPage

**Files:**
- Modify: `app/client/src/api.js`（alertApi 之后追加）
- Create: `app/client/src/pages/WatchlistPage.jsx`

**Step 1: api.js 封装**

```javascript
export const watchlistApi = {
  getList: (params = {}) => api.get('/watchlist', { params }),
  add: (code) => api.post('/watchlist', { code }),
  remove: (code) => api.delete(`/watchlist/${code}`),
}
```

**Step 2: 创建 WatchlistPage.jsx**（完整代码，参考 ETFPage 结构）

```jsx
import React, { useState, useEffect, useCallback } from 'react'
import { Table, Input, Button, Space, Tag, message } from 'antd'
import { PlusOutlined, ReloadOutlined, StarFilled } from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { watchlistApi } from '../api'

function WatchlistPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [addCode, setAddCode] = useState('')
  const [adding, setAdding] = useState(false)

  const keyword = searchParams.get('keyword') || ''
  const rpsRed = searchParams.get('rpsRed') || undefined
  const sortBy = searchParams.get('sortBy') || null
  const sortOrder = searchParams.get('sortOrder') || 'desc'

  const updateParam = useCallback((key, value) => {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      if (value === null || value === undefined || value === '') next.delete(key)
      else next.set(key, value)
      return next
    }, { replace: true })
  }, [setSearchParams])

  const { data = [], isFetching } = useQuery({
    queryKey: ['watchlist', keyword, rpsRed, sortBy, sortOrder],
    queryFn: () => {
      const params = {}
      if (keyword) params.keyword = keyword
      if (rpsRed) params.rps_red = rpsRed
      if (sortBy) { params.sort_by = sortBy; params.sort_order = sortOrder }
      return watchlistApi.getList(params).then(r => r.data || [])
    },
  })

  const handleAdd = async () => {
    const code = addCode.trim()
    if (!code) return
    if (adding) return
    setAdding(true)
    try {
      await watchlistApi.add(code)
      message.success(`已添加 ${code}`)
      setAddCode('')
      queryClient.invalidateQueries({ queryKey: ['watchlist'] })
    } catch (e) {
      message.error(e?.response?.data?.detail || '添加失败')
    } finally {
      setAdding(false)
    }
  }

  const handleDelete = async (code) => {
    try {
      await watchlistApi.remove(code)
      message.success(`已删除 ${code}`)
      queryClient.invalidateQueries({ queryKey: ['watchlist'] })
    } catch (e) {
      message.error(e?.response?.data?.detail || '删除失败')
    }
  }

  const renderChange = (value) => {
    if (value == null) return '-'
    const color = value >= 0 ? 'text-red-500' : 'text-green-500'
    return <span className={`font-mono ${color}`}>{value >= 0 ? '+' : ''}{value.toFixed(2)}%</span>
  }

  const renderRps = (v) => v != null
    ? <span className={`font-mono ${v >= 90 ? 'text-red-500 font-bold' : v >= 80 ? 'text-orange-500' : v <= 20 ? 'text-green-500' : ''}`}>{v}</span>
    : '-'

  const columns = [
    { title: '代码', dataIndex: 'code', key: 'code', width: 110,
      render: (v) => <span className="font-mono text-gray-500">{v}</span> },
    { title: '名称', dataIndex: 'name', key: 'name', width: 200,
      render: (v, r) => (
        <span className="font-medium text-blue-600 hover:text-blue-800 cursor-pointer"
          onClick={() => navigate(`/search?${r.type === 'etf' ? 'etf' : 'code'}=${r.code}&name=${encodeURIComponent(v)}`)}>
          {v}
        </span>
      ) },
    { title: '类型', dataIndex: 'type', key: 'type', width: 80,
      render: (v) => v === 'etf' ? <Tag color="cyan">ETF</Tag> : <Tag color="blue">个股</Tag> },
    { title: '最新价', dataIndex: 'close', key: 'close', width: 100, sorter: true,
      render: (v) => v != null ? <span className="font-mono">{v.toFixed(3)}</span> : '-' },
    { title: '日涨幅', dataIndex: 'change_pct', key: 'change_pct', width: 100, sorter: true, render: renderChange },
    { title: '5日涨幅', dataIndex: 'chg_5d', key: 'chg_5d', width: 100, sorter: true, render: renderChange },
    { title: '10日涨幅', dataIndex: 'chg_10d', key: 'chg_10d', width: 100, sorter: true, render: renderChange },
    { title: '20日涨幅', dataIndex: 'chg_20d', key: 'chg_20d', width: 100, sorter: true, render: renderChange },
    { title: '50日涨幅', dataIndex: 'chg_50d', key: 'chg_50d', width: 100, sorter: true, render: renderChange },
    { title: '120日涨幅', dataIndex: 'chg_120d', key: 'chg_120d', width: 100, sorter: true, render: renderChange },
    { title: 'RPS10', dataIndex: 'rps_10', key: 'rps_10', width: 80, sorter: true, render: renderRps },
    { title: 'RPS20', dataIndex: 'rps_20', key: 'rps_20', width: 80, sorter: true, render: renderRps },
    { title: 'RPS50', dataIndex: 'rps_50', key: 'rps_50', width: 80, sorter: true, render: renderRps },
    { title: '操作', key: 'action', width: 80,
      render: (_, r) => (
        <Button size="small" danger type="link" onClick={() => handleDelete(r.code)}>删除</Button>
      ) },
  ]

  const handleTableChange = (pagination, filters, sorter) => {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      if (sorter.field) { next.set('sortBy', sorter.field); next.set('sortOrder', sorter.order === 'ascend' ? 'asc' : 'desc') }
      else { next.delete('sortBy'); next.delete('sortOrder') }
      return next
    }, { replace: true })
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <div className="flex items-center space-x-3">
          <h2 className="text-lg font-bold flex items-center"><StarFilled className="text-yellow-500 mr-1.5" />重点关注</h2>
          <Tag color="blue" className="text-xs">{data.length} 只</Tag>
        </div>
        <Space wrap>
          <Input.Search
            placeholder="输入代码(回车添加)"
            style={{ width: 220 }}
            value={addCode}
            onChange={(e) => setAddCode(e.target.value)}
            onSearch={handleAdd}
            loading={adding}
            enterButton={<PlusOutlined />}
          />
          <select value={rpsRed || ''} onChange={(e) => updateParam('rpsRed', e.target.value || undefined)}
            className="border rounded px-2 py-1 text-sm">
            <option value="">RPS红筛选</option>
            <option value="one">一线红</option>
            <option value="two">二线红</option>
            <option value="three">三线红</option>
          </select>
          <Button icon={<ReloadOutlined />} onClick={() => queryClient.invalidateQueries({ queryKey: ['watchlist'] })}>刷新</Button>
        </Space>
      </div>

      <Table dataSource={data} columns={columns} rowKey="code" loading={isFetching}
        onChange={handleTableChange}
        pagination={{ pageSize: 50, showSizeChanger: true, showTotal: (t) => `共 ${t} 只` }}
        size="small" className="bg-white rounded-lg shadow-sm" />
    </div>
  )
}

export default WatchlistPage
```

**Step 3: Commit**

```bash
git add app/client/src/api.js app/client/src/pages/WatchlistPage.jsx
git commit -m "feat: 前端重点关注列表页面"
```

---

### Task 7: 路由与导航入口

**Files:**
- Modify: `app/client/src/App.jsx`（顶部按钮 + 路由）

**Step 1: 导航入口**（App.jsx L113 ETF 链接之后追加）

```jsx
import { StarOutlined } from '@ant-design/icons'   // 合并到现有 icons import
import WatchlistPage from './pages/WatchlistPage'  // 合并到现有 import

<Link to="/watchlist" className="flex items-center space-x-1 px-2 py-0.5 rounded text-xs sm:text-sm text-white/70 hover:text-white hover:bg-white/10 transition-colors ml-1">
  <StarOutlined />
  <span>关注</span>
</Link>
```

**Step 2: 路由注册**（App.jsx L188 之后追加）

```jsx
<Route path="/watchlist" element={<WatchlistPage />} />
```

**Step 3: 前端构建**

```bash
cd app/client && npm run build
```

Expected: Vite 构建成功无报错

**Step 4: Commit**

```bash
git add app/client/src/App.jsx
git commit -m "feat: 重点关注页面路由与导航"
```

---

### Task 8: 端到端浏览器验证

**Files:** 无（验证用）

**Step 1: 后端重启 + 前端验证**

```bash
kill -9 $(lsof -ti:8000 -sTCP:LISTEN) 2>/dev/null; sleep 1
(source venv/bin/activate && nohup python -m uvicorn app.server.main:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 30 > logs/server.log 2>&1 &)
sleep 8
curl -s http://localhost:8000/api/health | head -c 80
```

**Step 2: 浏览器打开 /watchlist**

- 添加 510300（沪深300ETF）→ 成功，显示名称/类型ETF/行情
- 添加 600519（贵州茅台）→ 类型个股
- 添加 999999 → 提示"未找到该代码"
- 重复添加 510300 → 提示"已在列表中"
- RPS红筛选一/二/三线切换 → 列表变化
- 名称点击 → 跳转 /search 详情
- 删除 + 删除后 → 列表刷新

**Step 3: 提交（前端构建产物未纳入 git 则无需提交）**