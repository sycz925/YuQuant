# 重构任务总计划

**创建日期**: 2026-07-22
**项目**: A股量化仿真与前端看板系统
**分析方法**: vibecoding-refactor 六阶段工作流

---

## 总体进度

- **Phase 0**: 项目分区 ✅ 完成
- **Phase 1**: 关键识别 ✅ 完成
- **Phase 2**: 架构层分析 ✅ 完成
- **Phase 3**: 模块层分析 ✅ 完成（3/6 功能深度分析）
- **Phase 4**: 执行重构 ✅ 核心完成
- **Phase 5**: 验证归档 ⏳ 待开始

---

## Phase 4: 架构层重构任务 [优先]

| 编号 | 任务 | 优先级 | 状态 | 负责 |
|------|------|--------|------|------|
| A-001 | 建立 repository 层，封装 get_db() | P0 | ✅ 完成 | BackendAgent |
| A-002 | 拆分过大路由文件 | P0 | 📋 计划完成，增量执行 | BackendAgent |
| A-003 | 建立工厂层 | P1 | ✅ 完成 | BackendAgent |
| A-004 | 建立编排层 | P1 | ✅ 完成 | BackendAgent |
| A-005 | 补充服务层 | P1 | ✅ 完成 | BackendAgent |
| A-006 | 前端建立 hooks 目录 | P2 | ✅ 完成 | FrontendAgent |
| A-007 | 前端引入 TypeScript | P2 | ⏳ | FrontendAgent |

---

## Phase 4: 模块层重构任务

### 资源复用迁移
| 编号 | 任务 | 优先级 | 状态 |
|------|------|--------|------|
| M-001 | 抽取 useOneClickUpdate hook | P1 | ✅ 完成 |
| M-005 | 抽取 usePolling hook | P1 | ✅ 完成 |
| M-006 | 抽取 useTaskPolling hook | P1 | ✅ 完成 |
| M-007 | 抽取 useScreenshot hook | P1 | ✅ 完成 |
| M-011 | 建立 stock_repository | P1 | ✅ 完成 |

### 合并重复实现
| 编号 | 任务 | 优先级 | 状态 |
|------|------|--------|------|
| M-002 | 抽取通用步骤执行器 | P1 | ✅ 完成 |
| M-003 | 业务逻辑迁移到工厂层 | P1 | ✅ 完成 |

### 代码拆分
| 编号 | 任务 | 优先级 | 状态 |
|------|------|--------|------|
| M-009 | 拆分 CalendarReview.jsx | P1 | ⏳ |
| M-012 | 拆分 Settings.jsx | P1 | ⏳ |

---

## 执行顺序建议

```
阶段 1: 架构层修复 (A-001 ~ A-005)
  ↓
阶段 2: 模块层重构 (M-001 ~ M-012)
  ↓
阶段 3: 验证归档
```

---

## 检查点

| 检查点 | 内容 | 状态 |
|--------|------|------|
| checkpoint-1 | repository 层建立完成 | ✅ |
| checkpoint-2 | 路由层拆分完成 | ⏳ |
| checkpoint-3 | 工厂层建立完成 | ✅ |
| checkpoint-4 | 编排层建立完成 | ✅ |
| checkpoint-5 | 前端 hooks 抽取完成 | ✅ |
