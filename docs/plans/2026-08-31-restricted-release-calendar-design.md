# 限售股解禁日历功能设计

## 概述

在 A股量化系统中新增"解禁日历"功能，以热力图矩阵形式展示全市场每月解禁金额，支持按年切换、点击月份查看解禁股票详情。

## 需求总结

| 需求项 | 决策 |
|--------|------|
| 入口位置 | 左侧导航链接区域（与板块、ETF、关注并列） |
| 日历形式 | 热力图矩阵（12个月并排，颜色深浅代表解禁规模） |
| 现价数据 | 使用缓存的日线数据（非实时） |
| 数据存储 | MongoDB 持久化 |
| 显示范围 | 默认当前年 + 可切换历史年份 |
| 类型筛选 | 支持按解禁类型筛选 |
| 同步模式 | 直接同步（非任务模式，预估 5-8 秒） |

## 技术栈

- **前端**: React 18 + Ant Design 6 + Tailwind CSS
- **后端**: FastAPI + MongoDB
- **数据源**: AkShare (`stock_restricted_release_summary_em`, `stock_restricted_release_detail_em`)

---

## 一、数据模型

### MongoDB Collection: `stock_restricted_release`

```json
{
  "_id": ObjectId,
  "stock_code": "600000",           // 股票代码
  "stock_name": "浦发银行",         // 股票名称
  "release_date": "2026-09-04",     // 解禁日期
  "release_type": "定向增发机构配售股份", // 解禁类型
  "release_shares": 124831.65,      // 解禁数量（万股）
  "release_market_value": 128.57,   // 解禁市值（亿元）
  "float_ratio": 0.05,             // 占解禁前流通市值比例
  "close_price": 10.25,            // 解禁前一交易日收盘价
  "created_at": ISODate,
  "updated_at": ISODate
}
```

### 索引

```javascript
// 按年份+日期查询
db.stock_restricted_release.createIndex({ "release_date": 1, "stock_code": 1 })

// 唯一索引防止重复
db.stock_restricted_release.createIndex(
  { "stock_code": 1, "release_date": 1, "release_type": 1 },
  { unique: true }
)
```

---

## 二、后端 API

### 新增文件

```
app/server/api/restricted_release.py                    # 路由
app/server/repositories/restricted_release_repository.py # Repository
app/server/services/restricted_release_service.py        # Service
```

### API 端点

| 方法 | 路径 | 功能 | 参数 |
|------|------|------|------|
| `GET` | `/api/restricted-release/summary` | 获取月度汇总 | `year` |
| `GET` | `/api/restricted-release/detail` | 获取月度详情 | `year, month` |
| `POST` | `/api/restricted-release/sync` | 同步指定年份数据 | `year` |

### 响应格式

```json
// GET /api/restricted-release/summary?year=2026
{
  "year": 2026,
  "months": [
    { "month": 1, "total_value": 2857.95, "stock_count": 109 },
    { "month": 2, "total_value": 2146.23, "stock_count": 90 }
  ]
}

// GET /api/restricted-release/detail?year=2026&month=9
{
  "year": 2026,
  "month": 9,
  "stocks": [
    {
      "stock_code": "600000",
      "stock_name": "浦发银行",
      "release_date": "2026-09-04",
      "release_type": "定向增发机构配售股份",
      "release_shares": 124831.65,
      "release_market_value": 128.57,
      "float_ratio": 0.05,
      "close_price": 10.25
    }
  ]
}
```

---

## 三、前端页面

### 新增文件

```
app/client/src/pages/RestrictedRelease.jsx              # 页面组件
app/client/src/components/restricted-release/
  └── ReleaseDetailModal.jsx                            # 解禁详情弹窗
```

### 页面布局

```
┌─────────────────────────────────────────────────────────┐
│  A股量化  [板块] [ETF] [关注] [解禁]                     │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │  2026年 限售股解禁日历                    [同步数据]│  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
│  ┌──────┬──────┬──────┬──────┬──────┬──────┐           │
│  │  1月  │  2月  │  3月  │  4月  │  5月  │  6月  │       │
│  │2857亿│2146亿│ ---  │ ---  │ ---  │ ---  │      │
│  │ 109家│ 90家 │  0家 │  0家 │  0家 │  0家 │      │
│  └──────┴──────┴──────┴──────┴──────┴──────┘           │
│                                                         │
│  ┌──────┬──────┬──────┬──────┬──────┬──────┐           │
│  │  7月  │  8月  │  9月  │ 10月  │ 11月  │ 12月  │       │
│  │ ---  │73亿 │2449亿│3456亿│1360亿│5875亿│       │
│  │  0家 │ 10家│ 189家│ 131家│ 138家│ 162家│       │
│  └──────┴──────┴──────┴──────┴──────┴──────┘           │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 热力图颜色规则

| 解禁金额 | 颜色 | 含义 |
|----------|------|------|
| 0 | 灰色 | 无解禁 |
| < 500亿 | 浅绿色 | 低压力 |
| 500-2000亿 | 黄色 | 中等压力 |
| 2000-5000亿 | 橙色 | 较高压力 |
| > 5000亿 | 红色 | 高压力 |

### 弹窗内容

点击月份后弹出 Modal：
- 顶部：类型筛选器（多选框）
- 表格列：代码、名称、现价、解禁成本、解禁比例、解禁股数、解禁金额、解禁类型、解禁日期

---

## 四、数据同步

### 同步流程

```
用户点击 [同步数据] 按钮
        ↓
显示同步进度通知 (antd notification)
        ↓
POST /api/restricted-release/sync { year: 2026 }
        ↓
后端执行：
  1. 调用 ak.stock_restricted_release_summary_em()
  2. 调用 ak.stock_restricted_release_detail_em()
  3. 数据清洗 + 存入 MongoDB
  4. 返回同步结果
        ↓
前端刷新数据
```

### 错误处理

| 场景 | 处理方式 |
|------|----------|
| 网络请求失败 | antd message.error 提示 + 重试按钮 |
| 数据为空 | 显示"暂无数据"+ 同步按钮 |
| 同步失败 | notification.error 显示具体原因 |
| 部分月份无数据 | 灰色显示，无点击事件 |

---

## 五、性能优化

1. **缓存策略**：首次加载后缓存到前端 state，切换年份时优先读缓存
2. **懒加载**：弹窗内容在点击月份时才请求详情数据
3. **防抖**：同步按钮点击后禁用 3 秒，防止重复提交

---

## 六、修改现有文件

| 文件 | 修改内容 |
|------|----------|
| `app/client/src/App.jsx` | 添加导航链接 + 路由 |
| `app/server/main.py` | 注册新路由 |
