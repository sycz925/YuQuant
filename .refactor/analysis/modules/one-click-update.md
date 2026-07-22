# 功能分析: 一键更新

**分析日期**: 2026-07-22

---

## 基本信息
- **入口**: `app/client/src/App.jsx:65` (handleOneClickUpdate)
- **涉及文件**:
  - 前端: App.jsx, api.js
  - 后端: one_click_update.py, factor_service.py, sync.py, factors.py, data_manager.py, factor_engine.py
- **调用链**: App → API → one_click_update → factor_service/data_manager/factor_engine

---

## 资源复用分析

### 前端组件使用
| 组件 | 来源 | 问题 | 建议 |
|------|------|------|------|
| Button | antd ✅ | 无 | - |
| notification | antd ✅ | 无 | - |
| message | antd ✅ | 无 | - |
| Tooltip | antd ✅ | 无 | - |

### 前端 Hooks 使用
| Hook | 来源 | 问题 | 建议 |
|------|------|------|------|
| useState | React ✅ | 无 | - |
| useEffect | React ✅ | 无 | - |
| useCallback | React ✅ | 无 | - |
| 无自定义 hook | - | ⚠️ 逻辑内联 | 抽取 useOneClickUpdate |

### 后端基础设施使用
| 基础设施 | 当前使用 | 问题 | 建议 |
|----------|----------|------|------|
| 日志 | logger ✅ | 无 | - |
| 任务管理 | tm ✅ | 无 | - |
| 配置 | os.getenv ❌ | 硬编码 | 使用 config.py |
| 缓存 | 无 | 无 | - |

---

## 重复实现检测

### 功能重复
| 功能 | 当前位置 | 重复位置 | 建议 |
|------|----------|----------|------|
| 同步时间检查 | one_click_update.py:246 | sync.py:20 | 已统一到 sync_window.py ✅ |
| 任务状态查询 | one_click_update.py:37 | api.js:183 taskApi | 无重复 |
| RPS 计算 | one_click_update.py:167 | factors.py (多处) | 应统一到工厂层 |

### 相似代码
| 代码块 | 位置 | 相似位置 | 建议 |
|--------|------|----------|------|
| 步骤执行模式 | one_click_update.py:77-97 | one_click_update.py:100-132 | 可抽取为通用步骤执行器 |

---

## 模式一致性检测

| 模式类型 | 本功能使用 | 项目标准 | 一致 | 建议 |
|----------|-----------|----------|------|------|
| API 调用 | Axios | Axios | ✅ | - |
| 错误处理 | try-catch + return dict | 混合 | ⚠️ | 统一为 HTTPException |
| 状态管理 | useState | useState | ✅ | - |
| 任务启动 | threading.Thread | threading.Thread | ✅ | 应迁移到任务队列 |

---

## 问题总结

| # | 问题类型 | 描述 | 位置 | 严重度 |
|---|----------|------|------|--------|
| 1 | 资源未复用 | 逻辑内联在 App.jsx，未抽取 hook | App.jsx:65-166 | P1 |
| 2 | 重复实现 | 步骤执行模式重复 7 次 | one_click_update.py | P1 |
| 3 | 架构违规 | 业务函数 _run_update_task 在路由层 | one_click_update.py:59 | P0 |
| 4 | 模式不一致 | 错误处理混合 HTTPException 和 return dict | one_click_update.py | P2 |

---

## 重构任务

1. [M-001] 抽取 useOneClickUpdate hook
2. [M-002] 抽取通用步骤执行器
3. [M-003] 业务逻辑迁移到工厂层/编排层
4. [M-004] 统一错误处理模式
