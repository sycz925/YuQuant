# 2026-07-21 前后端优化计划

**日期**：2026-07-21
**负责代理**：ProjectManagerAgent
**当前模式**：多模块大项目架构（React + FastAPI 分离）
**执行状态**：待用户授权

---

## 📋 概述

基于对 `app/client/`（前端）与 `app/server/` + `app/engine/`（后端）的全面代码审查，整理出当前项目中存在的架构、性能、可维护性、安全性等问题，并按优先级分阶段给出优化路线图。

**优化目标**：
1. 修复阻碍项目稳定运行的架构性问题
2. 提升前后端可维护性与协作效率
3. 引入工程化基础设施（类型、测试、容器化、CI）
4. 在不破坏现有功能前提下渐进式重构

---

## 🚨 影响仪表盘（跨层变更上报）

| 维度 | 影响范围 |
| :--- | :--- |
| **涉及代理** | BackendAgent（主要）、FrontendAgent（次要）、ArchitectAgent（数据模块归位）、DeployAgent（容器化） |
| **受影响目录** | `app/server/`、`app/engine/`、`app/client/src/`、`requirements.txt`、`app/client/package.json`、`docs/` |
| **跨层变更** | ✅ 是 — 前端 API 拦截器 + 后端错误响应模型需统一契约 |
| **潜在副作用** | 1) `app/data/` 模块归位可能导致 import 路径全局变更；2) 任务队列迁移可能影响正在运行的同步任务；3) TypeScript 化可能引起短期构建失败 |
| **回滚策略** | 每个里程碑独立分支 + 标签，支持快速回滚；数据库迁移提供反向脚本 |
| **执行前置条件** | 需用户确认是否启动本计划，以及各里程碑的优先级排序 |

---

## 🔍 现状问题清单

### A. 后端严重问题（P0）

#### A1. `app/data/` 模块缺失 — 架构性断裂 ⚠️
- **现象**：项目中共有 **38 个文件** 引用 `from app.data.xxx import ...`（涉及 `manager`、`db`、`task_manager`、`holidays`），但 `app/data/` 目录在当前代码库中**完全不存在**。
- **影响**：项目直接 `python -m uvicorn app.server.main:app` 无法启动；只有这些模块被以某种方式（site-packages 安装或外部注入）补全时才可运行。
- **根因**：迁移到多模块架构时数据层代码未纳入版本控制或被误删。
- **涉及文件**：
  - [app/server/main.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/server/main.py)
  - [app/server/cache.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/server/cache.py)
  - [app/server/api/stocks.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/server/api/stocks.py)
  - [app/server/api/sync.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/server/api/sync.py)
  - [app/server/api/factors.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/server/api/factors.py)
  - [app/server/api/calendar.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/server/api/calendar.py)
  - [app/server/api/market_review.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/server/api/market_review.py)
  - [app/server/api/market_analysis.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/server/api/market_analysis.py)
  - [app/server/api/one_click_update.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/server/api/one_click_update.py)
  - [app/server/api/search.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/server/api/search.py)
  - [app/server/api/deepseek_analyst.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/server/api/deepseek_analyst.py)
  - [app/server/services/factor_service.py](file:///Users/yubo/Desktop/workudy/YuQuant/app/server/services/factor_service.py)
  - [app/engine/factor_engine.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/engine/factor_engine.py)
  - [app/engine/rps_calculator.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/engine/rps_calculator.py)

#### A2. 路由层混入业务逻辑
- **现象**：`factors.py` 单文件 **1700+ 行**；`_run_precompute_base`、`_run_sync_task`、`_run_update_task`、`_run_recalc_task` 等业务函数写在 `api/` 下。
- **影响**：违反分层架构，难以测试与复用。

#### A3. 任务管理基于内存全局变量
- **现象**：`one_click_update.py` 使用 `_task_status` / `_recalc_task_status` 全局字典 + `threading.Lock`；任务用 `threading.Thread` 启动。
- **影响**：
  1. 多进程部署（uvicorn --workers >1）下任务状态不一致；
  2. 进程重启后运行中任务状态丢失；
  3. 无任务超时与重试机制。

#### A4. FastAPI 主入口过时写法
- **现象**：`main.py` 使用 `@app.on_event("startup")`（FastAPI 0.93+ 已弃用）；CORS、日志、端口全部硬编码。
- **影响**：未来 FastAPI 升级后将失效；配置不可环境化。

#### A5. 错误处理契约不统一
- **现象**：部分接口 `raise HTTPException`，部分 `return {"success": False, "message": ...}`；前端 `api.js` 只能通过 `response.data.detail` 兜底。
- **影响**：前端错误提示不稳定，无法做错误分类与重试。

### B. 后端重要问题（P1）

#### B1. 数据访问层缺失仓库模式
- **现象**：所有路由直接 `get_db()` 后写 MongoDB 查询；`stocks.py` 中分页查询重复扫描 `disabled_codes`。
- **影响**：查询逻辑分散、无法单元测试、索引优化难落地。

#### B2. 配置散落、TDX 服务器列表重复
- **现象**：`TDX_SERVERS` 在 `factor_service.py` 与 `stocks.py` 中重复定义；`os.getenv('LEGULEGU_TOKEN')` 散落在多处。
- **影响**：维护成本高、易不一致。

#### B3. 缓存策略薄弱
- **现象**：`cache.py` 只缓存 `latest_trade_date` 与 `trade_dates`；`FactorService` 的 TTL 缓存仅单进程有效。
- **影响**：多进程部署时缓存失效；高频接口（如 calendar、market-review）无缓存。

#### B4. N+1 查询风险
- **现象**：`generate_calendar_snapshot` 中循环对每个 `top_sector` 单独查 `sector_daily`；`stocks.py` 的 `get_stock_list` 在分页前先扫一次 `disabled_codes`，循环里又重复使用。
- **影响**：接口耗时随数据量线性放大。

#### B5. 同步时间窗口逻辑重复
- **现象**：`_check_sync_time` 在 `sync.py` 定义，被 `one_click_update.py` 与 `factors.py` 函数内 import；前端 `Settings.jsx` 又自己实现一份。
- **影响**：前后端时间窗口规则可能漂移。

#### B6. requirements.txt 残留无用依赖
- **现象**：仍保留 `streamlit>=1.28.0`（已迁移到 React）；缺少 `python-multipart`（FastAPI 文件上传所需）。
- **影响**：构建体积偏大；部分接口可能运行时报错。

### C. 前端严重问题（P0）

#### C1. 缺少 TypeScript 类型约束
- **现象**：全部 `.jsx` 文件，无类型声明；API 响应全靠 `any` 兜底。
- **影响**：重构风险高、IDE 提示弱、契约变更难以追踪。

#### C2. 无路由懒加载
- **现象**：`App.jsx` 同步 `import` 8 个页面，首屏 bundle 包含全部代码。
- **影响**：首屏 TTI 偏大；用户只访问首页也加载所有图表库。

### D. 前端重要问题（P1）

#### D1. 图表库冗余
- **现象**：`package.json` 同时依赖 `echarts`、`echarts-for-react`、`lightweight-charts`、`recharts` **4 个图表库**。
- **影响**：bundle 体积爆炸；维护成本高；样式不统一。
- **建议**：保留 `lightweight-charts`（K线）+ `recharts`（统计图），移除 echarts。

#### D2. API 层契约混乱
- **现象**：`api.js` 中 `factorApi.importSectorCodes` 重复定义两次；`taskApi.getTaskStatus` 与 `calendarApi.getTaskStatus` 重复；`factorApi.getStockList` 与 `stockApi.getStockList` 重复。
- **影响**：调用方不知道该用哪个；维护时容易漏改。

#### D3. App.jsx 业务逻辑过重
- **现象**：一键更新的轮询、通知、状态管理全堆在 `App.jsx` 里，120+ 行函数体。
- **影响**：组件难以测试；状态散落多个 `useState`。

#### D4. 轮询策略硬编码
- **现象**：健康检查 30s、同步时间检查 60s、一键更新进度 3s，全部 `setInterval` 硬编码，无退避、无页面隐藏暂停。
- **影响**：后台标签页持续发请求；失败时无指数退避。

#### D5. 错误处理简单
- **现象**：`api.js` 拦截器仅做 2 秒防抖 toast，无错误分类、无重试、无请求取消（AbortController）。
- **影响**：切换页面时旧请求继续；网络抖动直接报错给用户。

#### D6. 缺少工程化基建
- **现象**：无 ESLint、Prettier、Husky 配置；无前端单元测试。
- **影响**：代码风格易漂移；质量无保障。

### E. 基础设施问题（P1）

#### E1. 无 Docker / Docker Compose
- **现象**：项目根目录无 `Dockerfile` 与 `docker-compose.yml`，AGENTS.md 已定义 DeployAgent 但无交付物。
- **影响**：部署环境不一致；MongoDB 依赖手工安装。

#### E2. 无 CI/CD
- **现象**：无 `.github/workflows/`，无 GitLab CI 配置。
- **影响**：代码推送无自动测试/lint；发布靠手工。

#### E3. 测试覆盖率低
- **现象**：仅 `tests/test_data_manager.py` 与 `tests/test_factor_engine.py`，前端 0 测试。
- **影响**：重构风险高；回归无保障。

#### E4. 调试脚本泛滥
- **现象**：`scripts/` 下有 `fix_xxx`、`debug_xxx`、`backfill_xxx` 共 19 个一次性脚本。
- **影响**：项目根目录混乱；新人误以为是核心代码。

---

## 🎯 优化项优先级矩阵

| 优先级 | 项目 | 预期收益 | 风险 | 建议时机 |
| :--- | :--- | :--- | :--- | :--- |
| **P0-1** | `app/data/` 模块归位 | 解锁项目可运行 | 高（全局 import 变更） | 阶段 1 |
| **P0-2** | 后端配置中心化（pydantic-settings） | 配置统一 | 低 | 阶段 1 |
| **P0-3** | FastAPI lifespan + 全局异常处理 | 兼容未来版本 | 低 | 阶段 1 |
| **P0-4** | 前端路由懒加载 + 代码分割 | 首屏体积↓40%+ | 低 | 阶段 2 |
| **P1-1** | 路由层业务逻辑下沉到 service | 可测试性↑ | 中 | 阶段 2 |
| **P1-2** | 任务队列替换（APScheduler / Celery） | 多进程可用 | 高 | 阶段 3 |
| **P1-3** | 仓库模式 + 索引优化 | 性能↑ | 中 | 阶段 2 |
| **P1-4** | 前端 TypeScript 化（渐进） | 类型安全 | 中 | 阶段 3-4 |
| **P1-5** | 图表库精简 | bundle↓30%+ | 中 | 阶段 3 |
| **P1-6** | 前端 API 层重构 + 请求取消 | 体验↑ | 低 | 阶段 2 |
| **P1-7** | Docker / Compose 容器化 | 部署一致 | 低 | 阶段 4 |
| **P1-8** | CI/CD（GitHub Actions） | 自动化 | 低 | 阶段 4 |
| **P2-1** | 调试脚本归档 | 仓库整洁 | 低 | 阶段 4 |
| **P2-2** | 前端 ESLint/Prettier/Husky | 风格统一 | 低 | 阶段 3 |
| **P2-3** | 测试补齐（pytest + Vitest） | 回归保障 | 低 | 阶段 4 |
| **P2-4** | requirements.txt 清理 | 体积↓ | 低 | 阶段 1 |

---

## 🗺️ 分阶段实施计划

### 阶段 1：架构修复（P0，预计 1 个里程碑）

**负责代理**：ArchitectAgent（设计） + BackendAgent（实施）
**前置条件**：用户确认 `app/data/` 模块的来源（是否从其他仓库迁移、还是需重写）

#### 任务清单
- [ ] **1.1** 恢复或重建 `app/data/` 模块（`db.py`、`manager.py`、`task_manager.py`、`holidays.py`），纳入版本控制
- [ ] **1.2** 引入 `pydantic-settings`，新建 `app/server/config.py` 统一管理：
  - MongoDB URI、DB 名称
  - CORS 允许来源
  - TDX 服务器列表
  - LEGULEGU_TOKEN、DEEPSEEK_API_KEY 等密钥
  - 同步时间窗口配置
- [ ] **1.3** `main.py` 改造：
  - 使用 `lifespan` context manager 替代 `@app.on_event`
  - 添加全局异常处理器（统一 ErrorResponse 模型）
  - 添加请求 ID 中间件 + 耗时日志
- [ ] **1.4** 清理 `requirements.txt`：移除 `streamlit`，补充 `python-multipart`、`pydantic-settings`、`apscheduler`（为阶段 3 预备）
- [ ] **1.5** 抽取 `_check_sync_time` 到 `app/server/utils/sync_window.py`，前后端共享同一份规则配置

**交付物**：
- `app/data/` 模块完整可运行
- `app/server/config.py`、`app/server/utils/`
- 改造后的 `main.py`
- 更新后的 `requirements.txt`

**验证标准**：
- `python -m uvicorn app.server.main:app --reload` 可正常启动
- 所有现有 API 返回 200（健康检查、股票列表、CR5）
- 全局异常处理器返回统一 `{code, message, detail}` 结构

---

### 阶段 2：分层重构与前端基础优化（P0+P1）

**负责代理**：BackendAgent + FrontendAgent（并行）

#### 后端任务
- [ ] **2.1** 路由层瘦身：将 `_run_precompute_base`、`_run_sync_task`、`_run_update_task`、`_run_recalc_task` 下沉到 `app/server/services/`
- [ ] **2.2** 拆分 `factors.py`：按业务域拆为 `factors/cr5.py`、`factors/indices.py`、`factors/sectors.py`、`factors/rps.py`、`factors/precompute.py`
- [ ] **2.3** 引入仓库模式 `app/server/repositories/`：
  - `stock_repo.py`、`sector_repo.py`、`index_repo.py`、`task_repo.py`
  - 路由层只调 repo，不再直接 `get_db()`
- [ ] **2.4** 修复 `stocks.py` 的 N+1：分页接口一次性查询 disabled_codes 并缓存于请求上下文
- [ ] **2.5** 为 MongoDB 集合补充索引建议文档 `docs/database/indexes.md`：
  - `stock_daily (stock_code, trade_date)` 复合索引
  - `stock_basics.is_disable` 单字段索引
  - `sync_tasks.status` + `created_at` 复合索引

#### 前端任务
- [ ] **2.6** `App.jsx` 路由懒加载：所有页面用 `React.lazy` + `Suspense` 包裹
- [ ] **2.7** 抽取一键更新逻辑到 `src/hooks/useOneClickUpdate.js`，App 组件只负责渲染
- [ ] **2.8** `api.js` 重构：
  - 去除重复定义（`importSectorCodes`、`getStockList`、`getTaskStatus`）
  - 统一任务查询到 `taskApi`
  - 添加 `AbortController` 支持，页面卸载时取消请求
  - 添加请求重试（仅幂等 GET，最多 2 次指数退避）
- [ ] **2.9** 轮询逻辑抽取到 `src/hooks/usePolling.js`，支持页面隐藏暂停 + 指数退避

**交付物**：
- `app/server/services/` 新增业务服务
- `app/server/repositories/` 数据访问层
- `app/client/src/hooks/` 自定义 hooks
- 重构后的 `api.js`

**验证标准**：
- 前端首屏 bundle 体积下降 ≥ 30%
- 后端路由文件单文件不超过 500 行
- 切换页面时控制台无未完成请求警告

---

### 阶段 3：任务队列与前端类型化（P1）

**负责代理**：BackendAgent + FrontendAgent（并行）

#### 后端任务
- [ ] **3.1** 引入 APScheduler 或 Celery + Redis 作为任务队列：
  - 替换 `threading.Thread` 启动的后台任务
  - 任务状态持久化到 MongoDB 或 Redis
  - 支持多 worker 部署
- [ ] **3.2** 任务超时与重试机制：
  - 每个步骤配置 `timeout` 与 `max_retries`
  - 失败步骤支持断点续传
- [ ] **3.3** 一键更新步骤配置化：步骤定义从代码硬编码迁移到 `config/update_steps.yaml`

#### 前端任务
- [ ] **3.4** 渐进式 TypeScript 化：
  - 先将 `api.js` → `api.ts` + `types/api.ts`（定义所有响应类型）
  - 再迁移 `hooks/`、`components/`，最后 `pages/`
  - 允许 `.jsx`/`.tsx` 共存，通过 `allowJs: true` 过渡
- [ ] **3.5** 图表库精简：
  - 评估 `echarts` 使用范围，能迁移到 `recharts` 的全部迁移
  - K 线图保留 `lightweight-charts`
  - 移除 `echarts` + `echarts-for-react` 依赖
- [ ] **3.6** 引入 ESLint + Prettier + Husky：
  - `.eslintrc.cjs`（airbnb 基础规则 + React Hooks 规则）
  - `.prettierrc`
  - `husky` + `lint-staged` 提交前钩子

**交付物**：
- 任务队列服务（`app/server/tasks/`）
- `config/update_steps.yaml`
- `app/client/src/types/`、首个 `api.ts`
- 前端 lint 配置

**验证标准**：
- 杀掉 uvicorn 进程后，重启可恢复运行中任务状态
- `npm run lint` 通过
- TypeScript 严格模式下 `api.ts` 无类型错误

---

### 阶段 4：基础设施与测试（P1+P2）

**负责代理**：DeployAgent + BackendAgent + FrontendAgent

#### 任务清单
- [ ] **4.1** Docker 化：
  - `Dockerfile.backend`（多阶段构建，基于 `python:3.11-slim`）
  - `Dockerfile.frontend`（多阶段构建，nginx 托管构建产物）
  - `docker-compose.yml`（mongo + backend + frontend）
  - `.dockerignore`
- [ ] **4.2** CI/CD（GitHub Actions）：
  - `.github/workflows/ci.yml`：lint + test + build
  - `.github/workflows/deploy.yml`：tag 触发部署
- [ ] **4.3** 后端测试补齐：
  - `tests/api/` 路由层测试（用 `TestClient` + mongomock）
  - `tests/services/` 服务层测试
  - 目标覆盖率 ≥ 60%
- [ ] **4.4** 前端测试基建：
  - Vitest + React Testing Library
  - 关键 hooks 单测（`useOneClickUpdate`、`usePolling`）
  - 关键组件快照测试
- [ ] **4.5** 调试脚本归档：
  - `scripts/` 下 `fix_*`、`debug_*` 移动到 `scripts/archive/`
  - 保留 `backfill_*` 与 `check_*` 作为运维工具
- [ ] **4.6** 文档同步：
  - 更新 `README.md` 项目结构与启动方式
  - 更新 `docs/architecture/overview.md` 反映新分层
  - 更新 `docs/database/SCHEMA.md` 补充索引设计

**交付物**：
- `Dockerfile.backend`、`Dockerfile.frontend`、`docker-compose.yml`
- `.github/workflows/ci.yml`、`.github/workflows/deploy.yml`
- `tests/api/`、`tests/services/`
- `app/client/src/__tests__/`
- 归档后的 `scripts/archive/`

**验证标准**：
- `docker compose up` 一键启动整套服务
- CI 在 PR 上自动运行，失败阻断合并
- 后端测试覆盖率 ≥ 60%

---

## ⚠️ 风险与回滚策略

| 风险点 | 概率 | 影响 | 缓解措施 |
| :--- | :--- | :--- | :--- |
| `app/data/` 模块恢复后行为与历史不一致 | 高 | 数据同步异常 | 保留旧模块作为 `app/data_legacy/` 一个版本，灰度切换 |
| 任务队列迁移过程中丢失运行中任务 | 中 | 用户感知中断 | 迁移窗口选择周末；旧任务通过脚本补偿 |
| TypeScript 化引起短期构建失败 | 中 | 前端无法部署 | 阶段 3 允许 js/ts 共存，分页面灰度迁移 |
| 图表库替换引起视觉差异 | 低 | UI 体验 | 阶段 3 先做视觉回归对比，再切换 |
| Docker 化后本地开发体验变差 | 低 | 开发效率 | 保留 `start.sh` 本地启动方式，Docker 仅用于生产 |

**通用回滚策略**：
- 每个阶段独立 git 分支：`feature/phase-1-arch-fix`、`feature/phase-2-refactor` 等
- 合并主分支前必须通过完整回归测试
- 每个里程碑打 tag：`v1.1-arch-fix`、`v1.2-refactor` 等
- 出现严重问题立即回滚到上一 tag，并在 `docs/plans/` 记录复盘

---

## 📐 执行前置确认事项

在启动本计划前，需用户明确以下问题：

1. **`app/data/` 模块来源**：是从其他仓库迁移、还是需要根据 38 个引用点反推重建？
2. **任务队列选型偏好**：APScheduler（轻量、单机）vs Celery+Redis（分布式、重）？
3. **TypeScript 化节奏**：一次性全量迁移 vs 渐进式允许 js/ts 共存？
4. **部署目标环境**：本地 macOS 开发为主，还是需兼容 Linux 服务器？是否需要 K8s？
5. **阶段优先级**：是否认可 P0→P1→P2 的顺序？是否有急需优先处理的痛点？

---

## 📚 双轨资产同步清单

执行各阶段时需同步更新的资产：

### Human-Centric
- [ ] `README.md` — 项目结构与启动方式
- [ ] `docs/architecture/overview.md` — 分层架构图
- [ ] `docs/database/SCHEMA.md` — 索引设计
- [ ] `docs/api/modules.md` — 模块接口
- [ ] `docs/getting-started/setup.md` — 环境配置
- [ ] `docs/deployment/` — 新增部署文档

### Agent-Centric
- [ ] `AGENTS.md` — 更新代理交付物清单
- [ ] `agents/BackendAgent.md` — 新增 services/repositories 职责
- [ ] `agents/FrontendAgent.md` — 新增 TypeScript 规范
- [ ] `agents/DeployAgent.md` — 新增 Docker/CI 职责

---

## 📌 附录：关键文件引用速查

### 后端入口与配置
- [app/server/main.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/server/main.py)
- [app/server/cache.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/server/cache.py)
- [app/server/models.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/server/models.py)
- [requirements.txt](file:///Users/yubo/Desktop/work/study/YuQuant/requirements.txt)

### 后端 API 层
- [app/server/api/stocks.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/server/api/stocks.py)
- [app/server/api/factors.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/server/api/factors.py)
- [app/server/api/sync.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/server/api/sync.py)
- [app/server/api/one_click_update.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/server/api/one_click_update.py)
- [app/server/api/calendar.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/server/api/calendar.py)
- [app/server/api/market_review.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/server/api/market_review.py)

### 后端服务层
- [app/server/services/factor_service.py](file:///Users/yubo/Desktop/work/study/YuQuant/app/server/services/factor_service.py)

### 前端入口与 API
- [app/client/src/App.jsx](file:///Users/yubo/Desktop/work/study/YuQuant/app/client/src/App.jsx)
- [app/client/src/api.js](file:///Users/yubo/Desktop/work/study/YuQuant/app/client/src/api.js)
- [app/client/src/main.jsx](file:///Users/yubo/Desktop/work/study/YuQuant/app/client/src/main.jsx)
- [app/client/package.json](file:///Users/yubo/Desktop/work/study/YuQuant/app/client/package.json)
- [app/client/vite.config.js](file:///Users/yubo/Desktop/work/study/YuQuant/app/client/vite.config.js)

### 启动脚本
- [start.sh](file:///Users/yubo/Desktop/work/study/YuQuant/start.sh)
- [stop.sh](file:///Users/yubo/Desktop/work/study/YuQuant/stop.sh)
- [restart.sh](file:///Users/yubo/Desktop/work/study/YuQuant/restart.sh)

---

<!-- Context-Archived: 2026-07-21 首次创建前后端优化计划，覆盖 app/data 模块缺失、路由层重构、任务队列、TS化、Docker化等四大阶段 -->
