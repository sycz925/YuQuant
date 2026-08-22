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
| **FrontendAgent** | **客户端展示层**：UI/UX 交互、状态管理、现代前端工程、React前端开发 | `autoproject`、`ui-ux-pro-max` | `app/client/` | **严格仅前端**：FrontendAgent 不得修改任何后端代码（`app/server/`、`app/data/`、`app/engine/`）、数据库架构或 NGINX/Docker 基础设施配置。必须向 PM 代理上报任何跨层变更 |
| **BackendAgent** | **服务器端领域层**：FastAPI后端、高并发业务逻辑、持久化、数据同步、因子引擎 | `autoproject`、`VibeSec-Skill` | `app/server/`、`app/data/`、`app/engine/` | **严格仅后端**：BackendAgent 不得触碰任何前端 UI 代码（`app/client/`）、CSS/HTML/JS 或展示层逻辑。必须向 PM 代理上报任何跨层变更 |
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

在执行 `docs/plans/YYYY-MM-DD-<slug>.md`（如 `docs/plans/2026-08-08-watchlist-alert-design.md`）时，以下强制链适用：
1. **前置检查**：读取当前里程碑的 `[负责代理]` 和 `[可用技能]`。
2. **执行**：激活挂载技能进行本地化领域编码。禁止跨里程碑、非原子交付。
3. **后置检查**：验证交付物和测试基线。在请求用户授权解锁下一个里程碑前，更新双轨资产。

<!-- Context-Archived: 2026-08 代码审计与代理配置对齐：修正代理文件过时技术栈(SQLite/HDF5→MongoDB、移除 sentiment_engine、data_manager.py→data/manager.py)，重写第6节日期查询结论(定宽零填充下字典序=日期序)，新增第7节架构分层契约；审计产出 docs/refactor-audit.md -->

## 5. 临时脚本与日志目录约定

- **强制路径约束**：所有文件（含调试脚本、临时文件、日志、截图、扫描报告等）必须创建在本项目根目录内（项目根 `tmp/`、`logs/` 或对应模块目录）。**严禁**在项目之外创建任何文件（如 `/tmp`、`/var/folders/...`、`$TMPDIR`、系统临时目录等）。所有代理执行任何文件写入操作前，必须确认目标路径位于项目根目录之下。
- 根目录下 `tmp/`：存放一次性调试/扫描/修复脚本（如 `scan*_tmp.py`、`fix_*.py`），该目录已加入 `.gitignore`，不得提交版本库。
- 根目录下 `logs/`：服务运行日志输出目录，已加入 `.gitignore`。
- 一次性脚本用完即归档至 `tmp/`，禁止散落在根目录或 `scripts/` 下。

## 6. MongoDB 日期范围查询规范（重要）

> 此前版本将 `trade_date` 的 `$lte/$gte` 查询标记为"字典序陷阱"，经 2026-08 代码审计复核后**更正结论**，请以本节为准。

### 正确结论
`trade_date` 以**定宽 8 位零填充字符串** `YYYYMMDD` 存储（写入侧统一 `strftime('%Y%m%d')`）。对于定宽零填充字符串，**字典序与日期序完全一致**，因此 `$lte/$gte/$lt/$gt` 比较是**安全且推荐**的，无需"先 distinct 再 Python 过滤"的降级写法（那反而是 O(N) 反模式）。

### 真正需要防范的风险
1. **非零填充**：如 `"202679"` vs `"2026109"`，一旦混入非定宽日期，字典序就会错乱。
2. **格式混用**：`"2026-07-24"`、`"2026/07/24"`、`"20260724"` 混存。
3. **写入侧未规范化**：任何新写入路径都必须保证日期为 `YYYYMMDD` 零填充。

### 正确做法（收口到单一 helper，已落地 `app/data/db.py`）
```python
# app/data/db.py —— 统一日期范围查询构建，一处保证零填充
def _norm_date(d: str) -> str:
    """接受 YYYYMMDD / YYYY-MM-DD / YYYY/MM/DD，输出零填充 YYYYMMDD。"""
    s = str(d).strip()
    for fmt in ('%Y%m%d', '%Y-%m-%d', '%Y/%m/%d'):
        try:
            return datetime.strptime(s, fmt).strftime('%Y%m%d')
        except ValueError:
            continue
    raise ValueError(f"无法识别的日期格式: {d!r}")

def build_date_range_query(start=None, end=None) -> dict:
    q = {}
    if start or end:
        q['trade_date'] = {}
        if start: q['trade_date']['$gte'] = _norm_date(start)
        if end:   q['trade_date']['$lte'] = _norm_date(end)
    return q
```

### 审计结论（2026-08 复核）
- 现有代码中 `trade_date` 均零填充，`$lte/$gte` 使用安全，无空结果隐患。
- 优化方向：把散落在 `app/server/services/`、`app/data/db.py`、`app/engine/` 等处的日期范围查询统一收口到 `build_date_range_query()`（见 `docs/refactor-audit.md` P2），并为核心查询补单测。

## 7. 架构分层契约（重构铁律，2026-08 起强制）

> 背景：审计发现 API 层 146 处直连 `db['xxx']`，架空了已建的 repositories/factories/orchestrators 分层。详见 `docs/refactor-audit.md`。

| 分层 | 职责 | 是否允许访问 `get_db()` |
| :--- | :--- | :--- |
| **api/** | 薄路由：参数解析、调用 Service、组装响应 | ❌ 禁止直连集合 |
| **services/** | 业务编排：领域逻辑、缓存读写、跨 Repository 编排 | ❌ 通过 Repository |
| **repositories/** | 数据访问：**唯一允许访问 `get_db()`/`collection` 的层** | ✅ 唯一白名单 |
| **factories/** | 计算工厂：CR5/板块/指数等派生指标计算，纯函数优先 | ❌ 通过 Repository |
| **orchestrators/** | 任务编排：一键更新/月度重算等多步任务流程 | ❌ 通过 Service/Repository |
| **data/** | 数据源与持久化：`manager.py`(DataManager)、`sources/`、`db.py`(底层 CRUD + 日期 helper) | ✅ 底层封装 |
| **engine/** | 因子引擎：`factor_engine.py`、`rps_calculator.py`、`watchlist_alert.py`、`ene_alert.py` | 通过 `data/db.py` 封装 |

**强制规则**：
1. 新增/修改路由时，禁止 `from app.data.db import get_db` 后直连集合，必须经 Repository。
2. 新增/修改 API 契约、数据 Schema 属于**跨层变更**，必须先报 PM 输出影响仪表盘并等待确认。
