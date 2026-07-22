# 功能分析: 日历复盘

**分析日期**: 2026-07-22

---

## 基本信息
- **入口**: `app/client/src/pages/CalendarReview.jsx`
- **涉及文件**:
  - 前端: CalendarReview.jsx (1312行), ReviewDetail.jsx (406行)
  - 后端: calendar.py (1546行), market_review.py
- **调用链**: CalendarReview → calendarApi → calendar.py → MongoDB

---

## 资源复用分析

### 前端组件使用
| 组件 | 来源 | 问题 | 建议 |
|------|------|------|------|
| Modal | antd ✅ | 无 | - |
| DatePicker | antd ✅ | 无 | - |
| ConfigProvider | antd ✅ | 无 | - |
| notification | antd ✅ | 无 | - |
| message | antd ✅ | 无 | - |

### 前端 Hooks 使用
| Hook | 来源 | 问题 | 建议 |
|------|------|------|------|
| useState | React ✅ | 无 | - |
| useEffect | React ✅ | 无 | - |
| useCallback | React ✅ | 无 | - |
| 无自定义 hook | - | ⚠️ 大量轮询逻辑内联 | 抽取 usePolling, useTaskPolling |

### 后端基础设施使用
| 基础设施 | 当前使用 | 问题 | 建议 |
|----------|----------|------|------|
| 日志 | logger ✅ | 无 | - |
| 任务管理 | tm ✅ | 无 | - |
| 数据库 | get_db() ❌ | 30+ 次直接调用 | 使用 repository 层 |
| 缓存 | 无 | ⚠️ 无缓存 | 添加 Redis 缓存 |

---

## 重复实现检测

### 功能重复
| 功能 | 当前位置 | 重复位置 | 建议 |
|------|----------|----------|------|
| 轮询任务状态 | CalendarReview.jsx:498 | ReviewDetail.jsx:251 | 统一到 useTaskPolling hook |
| 截图功能 | CalendarReview.jsx:254 | ReviewDetail.jsx:153 | 抽取 useScreenshot hook |
| 生成周/月总结 | calendar.py:853, 1217 | calendar.py:1294, 1444 | 可抽取通用任务启动函数 |

### 相似代码
| 代码块 | 位置 | 相似位置 | 建议 |
|--------|------|----------|------|
| 轮询逻辑 | CalendarReview.jsx:490-505 | ReviewDetail.jsx:245-260 | 合并为通用轮询 hook |
| 任务启动 | CalendarReview.jsx:218 | CalendarReview.jsx:322 | 合并为通用任务启动函数 |

---

## 模式一致性检测

| 模式类型 | 本功能使用 | 项目标准 | 一致 | 建议 |
|----------|-----------|----------|------|------|
| API 调用 | Axios | Axios | ✅ | - |
| 错误处理 | try-catch + console.error | 混合 | ⚠️ | 统一错误处理 |
| 状态管理 | useState (8个) | useState | ✅ | 考虑 useReducer |
| 任务启动 | threading.Thread | threading.Thread | ✅ | 应迁移到任务队列 |

---

## 问题总结

| # | 问题类型 | 描述 | 位置 | 严重度 |
|---|----------|------|------|--------|
| 1 | 资源未复用 | 轮询逻辑重复 3 次 | CalendarReview, ReviewDetail | P1 |
| 2 | 资源未复用 | 截图功能重复 2 次 | CalendarReview, ReviewDetail | P1 |
| 3 | 重复实现 | 任务启动模式重复 4 次 | calendar.py | P1 |
| 4 | 架构违规 | 30+ 次 get_db() 直接调用 | calendar.py | P0 |
| 5 | 代码过大 | CalendarReview.jsx 1312 行 | CalendarReview.jsx | P1 |

---

## 重构任务

1. [M-005] 抽取 usePolling hook（支持页面隐藏暂停）
2. [M-006] 抽取 useTaskPolling hook（任务状态轮询）
3. [M-007] 抽取 useScreenshot hook
4. [M-008] calendar.py 建立 repository 层，消除 get_db()
5. [M-009] 拆分 CalendarReview.jsx 为多个子组件
