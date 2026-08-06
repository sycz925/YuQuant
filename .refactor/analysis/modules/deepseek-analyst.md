# 模块分析: DeepSeek AI 分析（deepseek_analyst.py）

**文件**: `app/server/api/deepseek_analyst.py` (654行)
**路由数**: 0（无路由端点）| **类**: 1

---

## 基本信息
- 入口: `class DeepSeekAnalyst` (第99行)
- 架构状态: ⚠️ 类定义在 api/ 层，不是路由

---

## Vibe Coding 问题检测

### 1. 文件放置错误（核心问题）
- `deepseek_analyst.py` 放在 `api/` 目录，但**不包含任何路由端点**
- 整个文件是一个服务类 + 工具函数
- 应迁移到 `app/server/services/deepseek_service.py`

### 2. 类结构过大
| 内容 | 行数 | 问题 |
|------|------|------|
| SYSTEM_PROMPT 常量 | 34行 | 应提取到独立文件 |
| `is_market_open()` | 20行 | 工具函数 |
| `is_deepseek_available()` | 25行 | 混合了 get_db() 调用 |
| `DeepSeekAnalyst` 类 | ~550行 | 应拆分 |

### 3. get_db() 直接调用
- `is_deepseek_available()` 第43行：`db = get_db()`
- DeepSeekAnalyst 类内部也有 5 处 get_db() 调用

### 4. 错误处理
- 6 处 `except Exception: pass` - 静默吞掉异常

---

## 迁移方案

| 新文件 | 职责 |
|--------|------|
| `services/deepseek_service.py` | DeepSeekAnalyst 类 |
| `services/deepseek_prompt.py` | SYSTEM_PROMPT 常量 |
| `utils/deepseek_helpers.py` | `is_market_open()` 等工具函数 |

---

## 重构任务
| 编号 | 任务 | 优先级 |
|------|------|--------|
| M-DS-01 | 迁移 deepseek_analyst.py 到 services/ | P1 |
| M-DS-02 | 提取 SYSTEM_PROMPT 到独立文件 | P2 |
| M-DS-03 | 6处 get_db() 替换为 repository | P1 |
| M-DS-04 | 修复静默异常吞没 | P1 |