# Phase 2: 架构层分析报告

**分析日期**: 2026-07-25（重新全量分析）

---

## 1. 分层依赖检查

### 正确的依赖方向
```
API Layer (routes)
    ↓
Orchestrator Layer (编排)
    ↓
Factory Layer (工厂)
    ↓
Repository Layer (数据访问)
    ↓
Data Layer (data/db.py)
```

### 实际依赖检测

| 违规位置 | 错误依赖 | 严重度 | 修复建议 |
|----------|----------|--------|----------|
| `api/calendar.py` | 直接调用 `get_db()` 17次 | **高** | 应通过 CalendarService → repository |
| `api/market_review.py` | 直接调用 `get_db()` 28次 | **高** | 应通过 MarketService → repository |
| `api/factors.py` | 直接调用 `get_db()` 13次，同时混用 factories | **高** | 统一使用 factories |
| `api/deepseek_analyst.py` | 直接调用 `get_db()` 6次，且是类定义在 api 层 | **高** | 迁移到 services/，使用 repository |
| `api/sync.py` | 直接调用 `data_manager`、`task_manager` | **中** | 应通过 SettingsOrchestrator |
| `api/stocks.py` | 直接调用 `get_db()` 3次 | **中** | 应通过 StockRepository |
| `api/market_analysis.py` | 直接调用 `get_db()` 3次 | **中** | 应通过 MarketRepository |
| `orchestrators/one_click_orchestrator.py` | 直接调用 `get_db()` 4次 | **中** | 应通过 factory |
| `factories/stock_factory.py` | 直接调用 `get_db()` 2次 | **低** | 已使用 repository，仅边缘逻辑 |
| `factories/index_factory.py` | 直接调用 `get_db()` 5次 | **低** | 已使用 repository，仅边缘逻辑 |

### 层级违规统计
| 违规类型 | 数量 | 影响 |
|----------|------|------|
| API 层直接访问数据层 | 72次 get_db() | 无法单元测试，查询逻辑分散 |
| API 层包含业务逻辑类 | 1个 (DeepSeekAnalyst) | 违反分层原则 |
| API 层直接启动后台任务 | 9处 threading.Thread | 任务管理不统一 |
| 工厂层直接访问数据层 | 13次 get_db() | 部分未完全迁移到 repository |

---

## 2. 循环依赖检测

| 模块 A | 模块 B | 状态 |
|--------|--------|------|
| 无明显循环依赖 | - | ✅ |

---

## 3. 目录结构评估

### 问题 1: 路由层文件过大
| 文件 | 行数 | 路由数 | 函数数 | 问题 |
|------|------|--------|--------|------|
| **market_review.py** | 3095 | 10 | 40+ | 数据计算、信号分析、AI分析全部混在一起 |
| **calendar.py** | 1584 | 15 | 20+ | 日历快照、周总结、月总结、重算、AI补全 |
| **factors.py** | 1428 | 20 | 30+ | CR5、指数、板块、RPS、对比、导入导出 |

### 问题 2: 文件放置不当
| 文件 | 当前位置 | 应放置 | 原因 |
|------|----------|--------|------|
| deepseek_analyst.py | `api/` | `services/` | 是业务逻辑类，不是路由 |
| factors.py 中的 _run_* 函数 | `api/` | `factories/` 或 `orchestrators/` | 包含业务逻辑 |

### 问题 3: 新旧架构混用
| 文件 | 问题 |
|------|------|
| factors.py | 同时使用 `get_index_factory()` 新架构和 `get_db()` 旧架构 |
| calendar.py | 完全未使用新架构，17处 get_db() |
| market_review.py | 完全未使用新架构，28处 get_db() |
| stocks.py | 完全未使用新架构，3处 get_db() |

### 问题 4: scripts 目录膨胀
- 20个脚本文件，包含大量一次性修复脚本（fix_*, debug_*, backfill_*）
- 建议归档或删除一次性脚本，保留核心运维脚本

---

## 4. 代码质量检测

### 4.1 异常处理
| 指标 | 数值 | 问题 |
|------|------|------|
| `except Exception` | 168处 | 裸异常捕获，可能隐藏错误 |
| 分布 | 23个文件 | 几乎所有文件都有 |

### 4.2 类型安全
| 指标 | 数值 | 问题 |
|------|------|------|
| `: Any` 类型注解 | 1处 | 后端正逐步减少（从上次分析中大幅改善） |
| 前端 TypeScript | 0% | 全部 JSX |

### 4.3 前端日志
| 指标 | 数值 | 问题 |
|------|------|------|
| `console.log/error/warn` | 55处 | 分散在20个文件，无统一日志 |

---

## 5. 架构层重构任务

| 编号 | 任务 | 优先级 | 说明 |
|------|------|--------|------|
| **A-001** | API 层 get_db() 迁移到 repository | **P0** | 72处调用需迁移，最高优先级 |
| **A-002** | 拆分过大路由文件 | **P0** | market_review.py(3095), calendar.py(1584), factors.py(1428) |
| **A-003** | deepseek_analyst.py 迁移到 services | **P1** | 类定义应在服务层 |
| **A-004** | 统一异常处理模式 | **P1** | 168处 bare except 需规范 |
| **A-005** | 前端统一日志方案 | **P2** | 55处 console 调用 |
| **A-006** | 清理 scripts 一次性脚本 | **P2** | 20个脚本，归档或删除 |
| **A-007** | 前端引入 TypeScript | **P2** | 长期目标 |

---

## 6. 架构层问题总结

### P0 (阻塞性 - 必须修复)
- [ ] **72处 API 层 get_db() 直接调用** - 新架构已建立但未全面应用
- [ ] **3个路由文件超过1400行** - 职责混乱，难以维护

### P1 (高优先级)
- [ ] deepseek_analyst.py 类在 api 层（654行）
- [ ] 168处 bare except Exception
- [ ] 新旧架构混用（factors.py 同时使用 factory 和 get_db()）

### P2 (中优先级)
- [ ] 前端 55处 console.log
- [ ] 20个 scripts 脚本残留
- [ ] 前端无 TypeScript
- [ ] 无测试覆盖