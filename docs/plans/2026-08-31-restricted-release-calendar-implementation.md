# 限售股解禁日历功能实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 A股量化系统中新增解禁日历功能，以热力图矩阵展示全市场每月解禁金额，支持按年切换、点击月份查看解禁股票详情。

**Architecture:** 后端新增 3 个 API 端点（summary/detail/sync），使用 AkShare 获取解禁数据并存入 MongoDB；前端新增独立页面组件，使用 antd Modal 展示详情弹窗，热力图矩阵使用 Tailwind CSS 实现。

**Tech Stack:** React 18 + Ant Design 6 + Tailwind CSS + FastAPI + MongoDB + AkShare

---

### Task 1: 后端 - 创建 Repository 层

**Files:**
- Create: `app/server/repositories/restricted_release_repository.py`
- Test: N/A（Repository 层通过集成测试验证）

**Step 1: 创建 Repository 文件**

```python
# app/server/repositories/restricted_release_repository.py
"""限售股解禁数据 Repository"""

from typing import List, Dict, Any
from datetime import datetime
from app.data.db import get_db


class RestrictedReleaseRepository:
    """限售股解禁数据仓储层"""

    def __init__(self):
        self.collection = get_db()['stock_restricted_release']

    def get_monthly_summary(self, year: int) -> List[Dict[str, Any]]:
        """获取指定年份的月度汇总"""
        pipeline = [
            {
                "$match": {
                    "release_date": {
                        "$gte": f"{year}-01-01",
                        "$lte": f"{year}-12-31"
                    }
                }
            },
            {
                "$group": {
                    "_id": {"$substr": ["$release_date", 5, 2]},
                    "total_value": {"$sum": "$release_market_value"},
                    "stock_count": {"$sum": 1}
                }
            },
            {"$sort": {"_id": 1}}
        ]
        
        results = list(self.collection.aggregate(pipeline))
        return [
            {
                "month": int(r["_id"]),
                "total_value": round(r["total_value"], 2),
                "stock_count": r["stock_count"]
            }
            for r in results
        ]

    def get_monthly_detail(self, year: int, month: int) -> List[Dict[str, Any]]:
        """获取指定月份的解禁详情"""
        month_str = f"{month:02d}"
        start_date = f"{year}-{month_str}-01"
        end_date = f"{year}-{month_str}-31"
        
        results = self.collection.find(
            {"release_date": {"$gte": start_date, "$lte": end_date}},
            {"_id": 0}
        ).sort("release_date", 1)
        
        return list(results)

    def upsert_many(self, records: List[Dict[str, Any]]) -> int:
        """批量插入或更新解禁数据"""
        count = 0
        for record in records:
            try:
                self.collection.update_one(
                    {
                        "stock_code": record["stock_code"],
                        "release_date": record["release_date"],
                        "release_type": record["release_type"]
                    },
                    {"$set": record},
                    upsert=True
                )
                count += 1
            except Exception as e:
                print(f"插入失败 {record.get('stock_code')}: {e}")
        return count

    def delete_by_year(self, year: int) -> int:
        """删除指定年份的数据（重新同步时使用）"""
        result = self.collection.delete_many(
            {"release_date": {"$regex": f"^{year}-"}}
        )
        return result.deleted_count


# 单例
_repo_instance = None

def get_restricted_release_repository() -> RestrictedReleaseRepository:
    global _repo_instance
    if _repo_instance is None:
        _repo_instance = RestrictedReleaseRepository()
    return _repo_instance
```

**Step 2: 提交代码**

```bash
git add app/server/repositories/restricted_release_repository.py
git commit -m "feat(restricted-release): add repository layer for restricted release data"
```

---

### Task 2: 后端 - 创建 Service 层

**Files:**
- Create: `app/server/services/restricted_release_service.py`
- Test: N/A

**Step 1: 创建 Service 文件**

```python
# app/server/services/restricted_release_service.py
"""限售股解禁数据 Service"""

from typing import List, Dict, Any
import akshare as ak
import pandas as pd
from app.server.repositories.restricted_release_repository import (
    get_restricted_release_repository
)


class RestrictedReleaseService:
    """限售股解禁数据服务层"""

    def __init__(self):
        self.repo = get_restricted_release_repository()

    def get_monthly_summary(self, year: int) -> Dict[str, Any]:
        """获取指定年份的月度汇总"""
        months = self.repo.get_monthly_summary(year)
        
        # 补充12个月，没有数据的月份显示为0
        month_map = {m["month"]: m for m in months}
        full_months = []
        for m in range(1, 13):
            if m in month_map:
                full_months.append(month_map[m])
            else:
                full_months.append({"month": m, "total_value": 0, "stock_count": 0})
        
        return {"year": year, "months": full_months}

    def get_monthly_detail(self, year: int, month: int) -> Dict[str, Any]:
        """获取指定月份的解禁详情"""
        stocks = self.repo.get_monthly_detail(year, month)
        return {"year": year, "month": month, "stocks": stocks}

    def sync_year_data(self, year: int) -> Dict[str, Any]:
        """同步指定年份的解禁数据"""
        try:
            # 获取汇总数据
            start_date = f"{year}0101"
            end_date = f"{year}1231"
            
            # 调用 akshare 获取全市场解禁汇总
            summary_df = ak.stock_restricted_release_summary_em(
                symbol="全部股票",
                start_date=start_date,
                end_date=end_date
            )
            
            if summary_df is None or len(summary_df) == 0:
                return {"success": False, "message": "未获取到数据"}
            
            # 获取详情数据
            detail_df = ak.stock_restricted_release_detail_em(
                start_date=start_date,
                end_date=end_date
            )
            
            # 转换为字典列表
            records = []
            if detail_df is not None and len(detail_df) > 0:
                for _, row in detail_df.iterrows():
                    record = {
                        "stock_code": str(row.get("股票代码", "")),
                        "stock_name": str(row.get("股票简称", "")),
                        "release_date": str(row.get("解禁时间", "")),
                        "release_type": str(row.get("限售股类型", "")),
                        "release_shares": float(row.get("解禁数量", 0)) / 10000,  # 转换为万股
                        "release_market_value": float(row.get("实际解禁市值", 0)) / 1e8,  # 转换为亿元
                        "float_ratio": float(row.get("占解禁前流通市值比例", 0)),
                        "close_price": float(row.get("解禁前一交易日收盘价", 0)),
                        "created_at": pd.Timestamp.now(),
                        "updated_at": pd.Timestamp.now()
                    }
                    records.append(record)
            
            # 先删除旧数据，再插入新数据
            self.repo.delete_by_year(year)
            inserted_count = self.repo.upsert_many(records)
            
            return {
                "success": True,
                "message": f"同步成功",
                "year": year,
                "total_count": len(records),
                "inserted_count": inserted_count
            }
            
        except Exception as e:
            return {"success": False, "message": str(e)}


# 单例
_service_instance = None

def get_restricted_release_service() -> RestrictedReleaseService:
    global _service_instance
    if _service_instance is None:
        _service_instance = RestrictedReleaseService()
    return _service_instance
```

**Step 2: 提交代码**

```bash
git add app/server/services/restricted_release_service.py
git commit -m "feat(restricted-release): add service layer with akshare integration"
```

---

### Task 3: 后端 - 创建 API 路由

**Files:**
- Create: `app/server/api/restricted_release.py`
- Modify: `app/server/main.py`

**Step 1: 创建路由文件**

```python
# app/server/api/restricted_release.py
"""限售股解禁 API 路由"""

from fastapi import APIRouter, HTTPException, Query
from app.server.services.restricted_release_service import (
    get_restricted_release_service
)

router = APIRouter(prefix="/api/restricted-release", tags=["restricted-release"])


@router.get("/summary")
async def get_summary(year: int = Query(..., ge=2010, le=2030)):
    """获取指定年份的月度解禁汇总"""
    try:
        service = get_restricted_release_service()
        result = service.get_monthly_summary(year)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/detail")
async def get_detail(
    year: int = Query(..., ge=2010, le=2030),
    month: int = Query(..., ge=1, le=12)
):
    """获取指定月份的解禁详情"""
    try:
        service = get_restricted_release_service()
        result = service.get_monthly_detail(year, month)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync")
async def sync_data(year: int = Query(..., ge=2010, le=2030)):
    """同步指定年份的解禁数据"""
    try:
        service = get_restricted_release_service()
        result = service.sync_year_data(year)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["message"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

**Step 2: 修改 main.py 注册路由**

```python
# 在 app/server/main.py 中添加
from app.server.api.restricted_release import router as restricted_release_router

# 在 include_router 部分添加
app.include_router(restricted_release_router)
```

**Step 3: 提交代码**

```bash
git add app/server/api/restricted_release.py app/server/main.py
git commit -m "feat(restricted-release): add API routes for summary, detail and sync"
```

---

### Task 4: 后端 - 测试 API 端点

**Files:**
- Test: 手动测试或创建 `tests/test_restricted_release.py`

**Step 1: 启动后端服务并测试**

```bash
# 测试 summary 端点
curl "http://localhost:8000/api/restricted-release/summary?year=2026"

# 测试 detail 端点
curl "http://localhost:8000/api/restricted-release/detail?year=2026&month=9"

# 测试 sync 端点
curl -X POST "http://localhost:8000/api/restricted-release/sync?year=2026"
```

**Step 2: 验证响应格式**

确认返回的 JSON 格式符合设计文档中的响应格式。

**Step 3: 提交测试（可选）**

```bash
git add tests/test_restricted_release.py
git commit -m "test(restricted-release): add integration tests for API endpoints"
```

---

### Task 5: 前端 - 创建页面组件

**Files:**
- Create: `app/client/src/pages/RestrictedRelease.jsx`
- Modify: `app/client/src/App.jsx`（添加路由和导航）

**Step 1: 创建页面组件**

```jsx
// app/client/src/pages/RestrictedRelease.jsx
import { useState, useEffect } from 'react'
import { Spin, message, notification, Button } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { restrictedReleaseApi } from '../api'
import ReleaseDetailModal from '../components/restricted-release/ReleaseDetailModal'

// 热力图颜色映射
const getColorByValue = (value) => {
  if (value === 0) return 'bg-gray-100'
  if (value < 500) return 'bg-green-200'
  if (value < 2000) return 'bg-yellow-200'
  if (value < 5000) return 'bg-orange-300'
  return 'bg-red-400'
}

export default function RestrictedRelease() {
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [year, setYear] = useState(dayjs().year())
  const [monthsData, setMonthsData] = useState([])
  const [modalVisible, setModalVisible] = useState(false)
  const [selectedMonth, setSelectedMonth] = useState(null)

  // 加载月度汇总数据
  const loadData = async () => {
    setLoading(true)
    try {
      const data = await restrictedReleaseApi.getSummary(year)
      setMonthsData(data.months || [])
    } catch (err) {
      message.error('加载数据失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [year])

  // 同步数据
  const handleSync = async () => {
    setSyncing(true)
    const notificationKey = notification.open({
      message: '同步中...',
      description: `正在同步 ${year} 年解禁数据`,
      duration: 0,
    })
    
    try {
      const result = await restrictedReleaseApi.sync(year)
      notification.success({
        message: '同步成功',
        description: `共同步 ${result.total_count} 条记录`,
        key: notificationKey,
      })
      loadData()
    } catch (err) {
      notification.error({
        message: '同步失败',
        description: err.message || '请稍后重试',
        key: notificationKey,
      })
    } finally {
      setSyncing(false)
    }
  }

  // 点击月份查看详情
  const handleMonthClick = (month) => {
    setSelectedMonth(month)
    setModalVisible(true)
  }

  return (
    <div className="max-w-7xl mx-auto px-4 py-6">
      {/* 标题栏 */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-800">
          {year}年 限售股解禁日历
        </h1>
        <Button
          type="primary"
          icon={<ReloadOutlined />}
          onClick={handleSync}
          loading={syncing}
        >
          同步数据
        </Button>
      </div>

      {/* 年份选择器 */}
      <div className="flex gap-2 mb-6">
        {[year - 1, year, year + 1].map((y) => (
          <Button
            key={y}
            type={y === year ? 'primary' : 'default'}
            onClick={() => setYear(y)}
          >
            {y}年
          </Button>
        ))}
      </div>

      {/* 热力图矩阵 */}
      <Spin spinning={loading}>
        <div className="grid grid-cols-6 gap-4">
          {monthsData.map((item) => (
            <div
              key={item.month}
              className={`${getColorByValue(item.total_value)} 
                p-4 rounded-lg cursor-pointer hover:opacity-80 transition-opacity
                ${item.stock_count === 0 ? 'cursor-not-allowed' : ''}`}
              onClick={() => item.stock_count > 0 && handleMonthClick(item.month)}
            >
              <div className="text-lg font-bold text-gray-800">
                {item.month}月
              </div>
              <div className="text-sm text-gray-600">
                {item.total_value > 0 ? `${item.total_value.toFixed(0)}亿` : '---'}
              </div>
              <div className="text-xs text-gray-500">
                {item.stock_count > 0 ? `${item.stock_count}家` : '0家'}
              </div>
            </div>
          ))}
        </div>
      </Spin>

      {/* 详情弹窗 */}
      <ReleaseDetailModal
        visible={modalVisible}
        year={year}
        month={selectedMonth}
        onClose={() => {
          setModalVisible(false)
          setSelectedMonth(null)
        }}
      />
    </div>
  )
}
```

**Step 2: 提交代码**

```bash
git add app/client/src/pages/RestrictedRelease.jsx
git commit -m "feat(restricted-release): add calendar page with heatmap UI"
```

---

### Task 6: 前端 - 创建详情弹窗组件

**Files:**
- Create: `app/client/src/components/restricted-release/ReleaseDetailModal.jsx`

**Step 1: 创建详情弹窗组件**

```jsx
// app/client/src/components/restricted-release/ReleaseDetailModal.jsx
import { useState, useEffect } from 'react'
import { Modal, Table, Checkbox, Spin, Empty } from 'antd'
import dayjs from 'dayjs'
import { restrictedReleaseApi } from '../../api'

// 解禁类型选项
const RELEASE_TYPES = [
  '首发原股东限售股份',
  '定向增发机构配售股份',
  '股权激励限售股份',
  '股权分置限售股份',
  '首发机构配售股份',
]

export default function ReleaseDetailModal({ visible, year, month, onClose }) {
  const [loading, setLoading] = useState(false)
  const [stocks, setStocks] = useState([])
  const [selectedTypes, setSelectedTypes] = useState(RELEASE_TYPES)

  // 加载详情数据
  const loadData = async () => {
    if (!year || !month) return
    
    setLoading(true)
    try {
      const data = await restrictedReleaseApi.getDetail(year, month)
      setStocks(data.stocks || [])
    } catch (err) {
      console.error('加载详情失败:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (visible) {
      loadData()
    }
  }, [visible, year, month])

  // 按类型筛选
  const filteredStocks = stocks.filter((s) =>
    selectedTypes.includes(s.release_type)
  )

  // 表格列定义
  const columns = [
    { title: '代码', dataIndex: 'stock_code', width: 80 },
    { title: '名称', dataIndex: 'stock_name', width: 100 },
    {
      title: '现价',
      dataIndex: 'close_price',
      width: 80,
      render: (v) => (v ? `¥${v.toFixed(2)}` : '---'),
    },
    {
      title: '解禁成本',
      dataIndex: 'close_price',
      width: 80,
      render: (v) => (v ? `¥${v.toFixed(2)}` : '---'),
    },
    {
      title: '解禁比例',
      dataIndex: 'float_ratio',
      width: 90,
      render: (v) => (v ? `${(v * 100).toFixed(2)}%` : '---'),
    },
    {
      title: '解禁股数(万)',
      dataIndex: 'release_shares',
      width: 110,
      render: (v) => (v ? v.toFixed(2) : '---'),
    },
    {
      title: '解禁金额(亿)',
      dataIndex: 'release_market_value',
      width: 110,
      render: (v) => (v ? v.toFixed(2) : '---'),
    },
    { title: '解禁类型', dataIndex: 'release_type', width: 150 },
    {
      title: '解禁日期',
      dataIndex: 'release_date',
      width: 100,
    },
  ]

  return (
    <Modal
      title={`${year}年${month}月 限售股解禁详情`}
      open={visible}
      onCancel={onClose}
      footer={null}
      width={1000}
      styles={{ body: { maxHeight: '60vh', overflowY: 'auto' } }}
    >
      {/* 类型筛选器 */}
      <div className="mb-4 p-3 bg-gray-50 rounded">
        <span className="mr-4 font-medium">解禁类型筛选：</span>
        <Checkbox.Group
          options={RELEASE_TYPES}
          value={selectedTypes}
          onChange={setSelectedTypes}
        />
      </div>

      {/* 数据表格 */}
      <Spin spinning={loading}>
        {filteredStocks.length > 0 ? (
          <Table
            dataSource={filteredStocks}
            columns={columns}
            rowKey={(r) => `${r.stock_code}-${r.release_date}-${r.release_type}`}
            size="small"
            pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 条` }}
            scroll={{ x: 900 }}
          />
        ) : (
          <Empty description="暂无数据" />
        )}
      </Spin>
    </Modal>
  )
}
```

**Step 2: 提交代码**

```bash
git add app/client/src/components/restricted-release/ReleaseDetailModal.jsx
git commit -m "feat(restricted-release): add detail modal with type filter"
```

---

### Task 7: 前端 - 添加 API 封装和路由

**Files:**
- Modify: `app/client/src/api.js`（添加 restrictedReleaseApi）
- Modify: `app/client/src/App.jsx`（添加导航和路由）

**Step 1: 在 api.js 中添加 restrictedReleaseApi**

```javascript
// 在 app/client/src/api.js 中添加

export const restrictedReleaseApi = {
  getSummary: (year) => api.get(`/restricted-release/summary?year=${year}`),
  getDetail: (year, month) =>
    api.get(`/restricted-release/detail?year=${year}&month=${month}`),
  sync: (year) => api.post(`/restricted-release/sync?year=${year}`),
}
```

**Step 2: 在 App.jsx 中添加导航链接**

```jsx
// 在导航链接区域添加
<NavLink to="/restricted-release" className={({ isActive }) => 
  `px-3 py-1 rounded text-sm ${isActive ? 'bg-white/20' : 'hover:bg-white/10'}`
}>
  解禁
</NavLink>
```

**Step 3: 在 App.jsx 中添加路由**

```jsx
import RestrictedRelease from './pages/RestrictedRelease'

// 在 Routes 中添加
<Route path="/restricted-release" element={<RestrictedRelease />} />
```

**Step 4: 提交代码**

```bash
git add app/client/src/api.js app/client/src/App.jsx
git commit -m "feat(restricted-release): add API wrapper and navigation route"
```

---

### Task 8: 前端 - 测试和调优

**Files:**
- Test: 手动测试页面交互

**Step 1: 启动前端服务并测试**

```bash
cd app/client && npm run dev
```

**Step 2: 测试功能点**

1. 访问 `/restricted-release` 页面
2. 切换年份
3. 点击月份查看弹窗
4. 使用类型筛选器
5. 点击同步按钮

**Step 3: 修复发现的问题**

根据测试结果调整样式或逻辑。

**Step 4: 最终提交**

```bash
git add -A
git commit -m "feat(restricted-release): complete implementation with testing"
```

---

## 任务依赖关系

```
Task 1 (Repository) → Task 2 (Service) → Task 3 (API) → Task 4 (测试后端)
                                                          ↓
Task 5 (页面组件) → Task 6 (弹窗组件) → Task 7 (API+路由) → Task 8 (测试前端)
```

## 预估工时

| 任务 | 预估时间 |
|------|----------|
| Task 1-3: 后端开发 | 30-45 分钟 |
| Task 4: 后端测试 | 10-15 分钟 |
| Task 5-7: 前端开发 | 45-60 分钟 |
| Task 8: 前端测试 | 15-20 分钟 |
| **总计** | **100-140 分钟** |
