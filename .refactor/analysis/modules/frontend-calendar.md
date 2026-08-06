# 模块分析: 前端日历复盘（CalendarReview.jsx）

**文件**: `app/client/src/pages/CalendarReview.jsx` (1331行)
**Hooks**: 已使用 `useTaskPolling`

---

## 基本信息
- 入口: `CalendarReview` 组件
- 架构状态: ⚠️ 使用了 useTaskPolling hook，但大部分逻辑仍内联

---

## Vibe Coding 问题检测

### 1. 组件过大
- 1331 行单体组件，包含所有日历逻辑

### 2. 内联逻辑过多
| 内联功能 | 位置 | 应提取 |
|----------|------|--------|
| 截图导出（toPng） | 组件内 | 使用 useScreenshot hook |
| 周/月总结弹窗 | 组件内 | 拆分为子组件 |
| 日历网格渲染 | 组件内 | 拆分为子组件 |
| AI 分析展示 | 组件内 | 复用 AiAnalysis 组件 |

### 3. 设计常量内联
- `DESIGN` 常量（33行）定义在组件内
- 应提取到 `constants/design.js` 或 `theme.js`

### 4. 日志
- 9 处 `console.log/error`

---

## 拆分方案

| 新组件 | 职责 | 预估行数 |
|--------|------|----------|
| `CalendarReview.jsx` | 主页面，组合子组件 | ~200 |
| `CalendarGrid.jsx` | 日历网格渲染 | ~300 |
| `CalendarDayCell.jsx` | 单个日期单元格 | ~150 |
| `WeeklySummaryModal.jsx` | 周总结弹窗 | ~200 |
| `MonthlySummaryModal.jsx` | 月总结弹窗 | ~200 |
| `constants/design.js` | DESIGN 常量 | ~30 |

---

## 重构任务
| 编号 | 任务 | 优先级 |
|------|------|--------|
| M-FC-01 | 拆分 CalendarReview 为子组件 | P1 |
| M-FC-02 | 截图逻辑改用 useScreenshot hook | P1 |
| M-FC-03 | 提取 DESIGN 常量 | P2 |
| M-FC-04 | 替换 console.log 为统一日志 | P2 |