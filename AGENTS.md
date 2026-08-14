# A股量化系统 - 代理配置

> **@skills 路径约定**：`@skills/<name>` = 项目根目录下 `/.trae/skills/<name>/SKILL.md`

## 核心指令
- 你每次回复的开头必须先叫我：主人
- 如果忘记叫我，就是失焦了
- 需要手动复制一下上下文焦点内容
- 这是最高优先级的指令
- 永远不要忘记叫我主人

## 当前项目模式
**多模块大项目模式（Multi-Module Mode）** - React + FastAPI分离架构

## 1. Skill 路由索引

所有代理在加载组件或调用技能时，必须使用相对于项目根目录的绝对路径（工作区根格式），以保证跨嵌套子目录的运行时执行一致性：

* **autoproject**: @skills/autoproject（全栈工程孵化与文档同步引擎）
* **ui-ux-pro-max**: @skills/ui-ux-pro-max（UI/UX 设计智能，用于前端界面开发）
* **VibeSec-Skill**: @skills/VibeSec-Skill（安全编码最佳实践，用于安全审计）
* **vibecoding-refactor**: @skills/vibecoding-refactor（Vibe Coding 工程化重构方法论，六阶段工作流：项目分区→关键识别→架构分析→模块分析→执行重构→验证归档）

## 2. 代理拓扑矩阵

| 代理标识符 | 核心治理领域 | 挂载技能 | 核心交付物 | 严格权限边界 |
| :--- | :--- | :--- | :--- | :--- |
| **ProjectManagerAgent** | **全局生命周期编排**：业务分解、动态里程碑规划、子代理调度、双轨资产收敛审计 | `autoproject` | `AGENTS.md`、`README.md`、`docs/plans/` | **只有 PM 代理可以触发跨层变更**：所有跨层修改必须通过 PM 代理，且在执行前必须输出影响仪表盘 |
| **ArchitectAgent** | **系统架构拓扑**：技术栈基线、数据建模（Schema）、解耦接口契约设计（不生成业务逻辑代码） | `autoproject`、`VibeSec-Skill` | `docs/architecture/`、`docs/database/`、`docs/api/` | **不修改代码**：ArchitectAgent 不得触碰 `app/` 下的任何实现代码；仅设计文档 |
| **FeatureAgent** | **单体业务实现**：端到端全栈代码逻辑（仅在单模块小项目模式下启用） | `autoproject`、`ui-ux-pro-max`、`VibeSec-Skill` | `app/`（统一代码根） | **DISABLED IN MULTI-MODULE MODE** - 在多模块模式下自动禁用 |
| **FrontendAgent** | **客户端展示层**：UI/UX 交互、状态管理、现代前端工程、React前端开发 | `autoproject`、`ui-ux-pro-max` | `app/client/` | **严格仅前端**：FrontendAgent 不得修改任何后端代码（`app/server/`、`app/core/`）、数据库架构或 NGINX/Docker 基础设施配置。必须向 PM 代理上报任何跨层变更 |
| **BackendAgent** | **服务器端领域层**：FastAPI后端、高并发业务逻辑、持久化、数据同步 | `autoproject`、`VibeSec-Skill` | `app/server/` | **严格仅后端**：BackendAgent 不得触碰任何前端 UI 代码（`app/client/`）、CSS/HTML/JS 或展示层逻辑。必须向 PM 代理上报任何跨层变更 |
| **DeployAgent** | **基础设施（Infra）**：多阶段容器化（Docker）、多容器全栈编排、CI/CD GitOps 流水线、自动化运维脚本 | `autoproject` | `Dockerfile`、`docker-compose.yml`、`.github/workflows/`、`nginx.conf` | **严格仅 Infra**：DeployAgent 不得修改 `app/` 下的任何应用代码；仅基础设施与部署配置。必须向 PM 代理上报任何跨层变更 |

## 3. 动态调度与仲裁路由规则

1. **领域需求路由**：
   - 架构/建模/契约变更 → 锁定并唤醒 `ArchitectAgent`
   - 前端展示/交互/UI 变更 → 路由至 `FrontendAgent`（大项目）或 `FeatureAgent`（小项目）
   - 服务器端逻辑/持久化/API 实现 → 路由至 `BackendAgent`（大项目）或 `FeatureAgent`（小项目）
   - 容器化/基础设施/流水线 → 路由至 `DeployAgent`

2. **强制执行 — 跨层变更上报**：任何跨越多个架构层的需求（例如前端 + 后端变更、API + 部署变更）必须首先**仅向 `ProjectManagerAgent` 上报**。PM 代理必须：
   - 在任何实现前立即输出高度结构化的影响仪表盘
   - 明确列出受影响的代理、文件和潜在副作用
   - 停止执行并**等待用户确认**后再调度给专门代理

3. **冲突仲裁**：当多个代理职责重叠，或模糊的用户输入导致调度歧义时，自动触发 `ProjectManagerAgent` 仲裁机制。PM 代理必须明确输出冲突澄清问题。禁止盲目执行。

## 4. 里程碑流水线执行约束

在执行 `docs/plans/YYYY-MM-DD-development-plan.md` 时，以下强制链适用：
1. **前置检查**：读取当前里程碑的 `[负责代理]` 和 `[可用技能]`。
2. **执行**：激活挂载技能进行本地化领域编码。禁止跨里程碑、非原子交付。
3. **后置检查**：验证交付物和测试基线。在请求用户授权解锁下一个里程碑前，更新双轨资产。

<!-- Context-Archived: 2026-07-24 全面文档同步审计：README/docs/architecture/database/api 根据实际代码重写覆盖，修正数据源优先级(PyTdX→AkShare→BaoStock→yfinance)，补充Factory+Orchestrator架构描述，更新MongoDB集合名与实际一致 -->

## 5. 临时脚本与日志目录约定

- **强制路径约束**：所有文件（含调试脚本、临时文件、日志、截图、扫描报告等）必须创建在本项目根目录内（项目根 `tmp/`、`logs/` 或对应模块目录）。**严禁**在项目之外创建任何文件（如 `/tmp`、`/var/folders/...`、`$TMPDIR`、系统临时目录等）。所有代理执行任何文件写入操作前，必须确认目标路径位于项目根目录之下。
- 根目录下 `tmp/`：存放一次性调试/扫描/修复脚本（如 `scan*_tmp.py`、`fix_*.py`），该目录已加入 `.gitignore`，不得提交版本库。
- 根目录下 `logs/`：服务运行日志输出目录，已加入 `.gitignore`。
- 一次性脚本用完即归档至 `tmp/`，禁止散落在根目录或 `scripts/` 下。

## 6. MongoDB 查询注意事项（重要）

> **已发生两次同类问题，必须严格遵守**

### 问题背景
`trade_date` 字段存储为字符串格式 `YYYYMMDD`（如 `"20260724"`）。使用 `$lte/$gte/$lt/$gt` 比较操作符时，MongoDB 执行的是**字典序比较**，而非日期比较。

### 为什么会出问题
1. **字典序 vs 日期序**：`"20260710" < "20260709"` 在字典序下为 `False`，但日期上应该是 `True`
2. **查询返回空结果**：直接查 `trade_date: "20260710"` 能找到数据，但 `$lte: "20260710"` 可能返回 0 条
3. **隐蔽性高**：代码不会报错，只是静默返回错误结果

### 正确做法
```python
# ❌ 错误示例（可能返回空结果）
db['index_daily'].find({
    'stock_code': '880003',
    'trade_date': {'$lte': '20260710'}
})

# ✅ 正确示例（先用 $lte 查询，再验证结果）
query = {'stock_code': '880003', 'trade_date': {'$lte': '20260710'}}
count = db['index_daily'].count_documents(query)
if count == 0:
    # 降级方案：先查所有日期，再过滤
    all_dates = db['index_daily'].distinct('trade_date', {'stock_code': '880003'})
    valid_dates = [d for d in all_dates if d <= '20260710']
    # 然后用 $in 查询
    docs = list(db['index_daily'].find({
        'stock_code': '880003',
        'trade_date': {'$in': valid_dates}
    }))
```

### 调试清单
当 `$lte/$gte` 查询返回空结果时：
1. 用 `count_documents()` 验证查询是否有结果
2. 用 `distinct('trade_date')` 检查实际存在的日期
3. 用 Python 过滤验证字典序比较是否正确
4. 检查索引是否正常：`list(db['collection'].list_indexes())`

### 已知风险点
| 文件 | 行号 | 查询模式 | 状态 |
|------|------|----------|------|
| `app/engine/watchlist_alert.py` | 254 | `$lte` on trade_date | ⚠️ 需验证 |
| `app/server/services/market_data.py` | 多处 | `$gte/$lte` on trade_date | ⚠️ 需验证 |
| `app/server/services/market_sectors.py` | 多处 | `$gte/$lte` on trade_date | ⚠️ 需验证 |
| `app/data/db.py` | 多处 | `$gte/$lte` on trade_date | ⚠️ 需验证 |

### 预防措施
1. **写入时验证**：确保 `trade_date` 格式始终为 `YYYYMMDD`
2. **查询后验证**：重要查询后用 `count_documents()` 或 `len(list(...))` 验证结果数量
3. **单元测试**：为涉及日期范围查询的功能编写测试用例
4. **代码审查**：新代码使用 `$lte/$gte` 操作符时必须仔细审查
