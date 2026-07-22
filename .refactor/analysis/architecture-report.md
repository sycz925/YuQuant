# Phase 2: 架构层分析报告

**分析日期**: 2026-07-22

---

## 1. 分层依赖检查

### 正确的依赖方向
```
UI Layer (pages/, components/)
    ↓
Application Layer (hooks/, services/)
    ↓
Infrastructure Layer (api/, utils/)
    ↓
Core Layer (types/, constants/)
```

### 实际依赖情况

| 违规位置 | 错误依赖 | 严重度 | 修复建议 |
|----------|----------|--------|----------|
| `api/factors.py` | 直接调用 `data_manager`、`factor_engine` | 高 | 应通过 service 层调用 |
| `api/one_click_update.py` | 直接调用 `factor_service`、`data_manager`、`factor_engine` | 高 | 应通过编排器调用 |
| `api/calendar.py` | 直接调用 `get_db()` 30+ 次 | 高 | 应通过 repository 层 |
| `api/market_review.py` | 直接调用 `get_db()` 30+ 次 | 高 | 应通过 repository 层 |
| `api/sync.py` | 直接调用 `data_manager`、`task_manager` | 中 | 应通过 service 层 |

### 层级违规统计
| 违规类型 | 数量 | 影响 |
|----------|------|------|
| 路由层直接访问数据层 | 142次 get_db() | 无法单元测试，查询逻辑分散 |
| 路由层直接启动后台任务 | 23处 threading.Thread | 任务管理不统一 |
| 路由层包含业务逻辑 | 5个 _run_* 函数 | 违反单一职责 |

---

## 2. 循环依赖检测

| 模块 A | 模块 B | 涉及文件 | 修复建议 |
|--------|--------|----------|----------|
| 无明显循环依赖 | - | - | - |

---

## 3. 目录结构评估

### 问题 1: 路由层文件过大
| 文件 | 行数 | 问题 |
|------|------|------|
| market_review.py | 3115 | 职责过多，混合了市场复盘、AI分析、板块详情 |
| factors.py | 1915 | 混合了因子计算、指数管理、板块管理、RPS计算 |
| calendar.py | 1546 | 混合了日历快照、周总结、月总结、重算 |

### 问题 2: 缺少关键目录
| 缺失目录 | 应有职责 |
|----------|----------|
| `app/server/repositories/` | 数据访问层，封装 MongoDB 查询 |
| `app/server/factories/` | 工厂层，按数据域内聚 |
| `app/server/orchestrators/` | 编排层，组合工厂能力 |
| `app/client/src/hooks/` | 自定义 hooks |
| `app/client/src/types/` | TypeScript 类型定义 |

### 问题 3: 服务层单薄
- 仅有 `factor_service.py` (1295行)
- 缺少独立的：
  - sync_service.py
  - market_service.py
  - calendar_service.py

---

## 4. 架构层重构任务

| 编号 | 任务 | 优先级 |
|------|------|--------|
| A-001 | 建立 repository 层，封装 142 处 get_db() 调用 | P0 |
| A-002 | 拆分过大路由文件（market_review, factors, calendar） | P0 |
| A-003 | 建立工厂层，按数据域内聚 | P1 |
| A-004 | 建立编排层，统一任务启动方式 | P1 |
| A-005 | 补充服务层，分离业务逻辑 | P1 |
| A-006 | 前端建立 hooks 目录，抽取公共逻辑 | P2 |
| A-007 | 前端建立 types 目录，引入 TypeScript | P2 |

---

## 5. 架构层问题总结

### P0 (阻塞性)
- [ ] 142处 get_db() 直接调用，无数据访问层
- [ ] 3个路由文件超过1000行，职责混乱

### P1 (高优先级)
- [ ] 23处 threading.Thread 散落在路由层
- [ ] 5个 _run_* 业务函数混在路由层
- [ ] 缺少工厂层和编排层

### P2 (中优先级)
- [ ] 前端无自定义 hooks
- [ ] 前端无类型系统
- [ ] 无测试覆盖
