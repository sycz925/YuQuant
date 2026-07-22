# 功能分析: 数据同步

**分析日期**: 2026-07-22

---

## 基本信息
- **入口**: `app/client/src/pages/Settings.jsx`
- **涉及文件**:
  - 前端: Settings.jsx (837行), ManagementDialog.jsx (280行)
  - 后端: sync.py (335行), data/manager.py (703行)
- **调用链**: Settings → syncApi → sync.py → data_manager → 数据源

---

## 资源复用分析

### 后端基础设施使用
| 基础设施 | 当前使用 | 问题 | 建议 |
|----------|----------|------|------|
| 数据库 | get_db() | 10+ 次直接调用 | 使用 repository 层 |
| 任务管理 | tm ✅ | 无 | - |
| 数据源 | data_manager ✅ | 无 | - |
| 配置 | os.getenv ❌ | TDX_SERVERS 重复定义 | 使用 config.py |

---

## 重复实现检测

### 功能重复
| 功能 | 当前位置 | 重复位置 | 建议 |
|------|----------|----------|------|
| TDX_SERVERS 定义 | factor_service.py:32 | (曾有 stocks.py 重复) | 已统一到 config.py ✅ |
| 同步时间检查 | sync.py:20 | one_click_update.py:246 | 已统一到 sync_window.py ✅ |
| 获取启用股票代码 | sync.py:124 | one_click_update.py:140 | 应统一到 repository |

### 相似代码
| 代码块 | 位置 | 相似位置 | 建议 |
|--------|------|----------|------|
| 启用代码查询 | sync.py:124-129 | one_click_update.py:140-144 | 合并为 repository 方法 |

---

## 问题总结

| # | 问题类型 | 描述 | 位置 | 严重度 |
|---|----------|------|------|--------|
| 1 | 架构违规 | _run_sync_task 在路由层 | sync.py:111 | P0 |
| 2 | 资源未复用 | 启用股票代码查询重复 | sync.py, one_click_update.py | P1 |
| 3 | 代码过大 | Settings.jsx 837 行 | Settings.jsx | P1 |

---

## 重构任务

1. [M-010] _run_sync_task 迁移到 sync_service.py
2. [M-011] 建立 stock_repository，统一启用代码查询
3. [M-012] 拆分 Settings.jsx 为多个子组件
