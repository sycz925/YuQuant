# Electron 桌面端 —— 方案设计与落地计划

> 状态：**待确认**（本文档只做设计，不进入开发）
> 负责代理：ProjectManagerAgent（跨层变更：前端壳 + 后端进程托管 + 数据存储）
> 核心约束：**完全本地自包含，不依赖任何远程服务器**。行情与 AI 能力所需的公网访问（pytdx 服务器、DeepSeek API）属于外部数据源，不属于本项目后端。

---

## 一、目标与范围

### 1.1 目标

把现有「React 前端 + FastAPI 后端 + MongoDB」的三层 Web 应用，打包成一个**双击即用**的桌面程序：

- 用户无需安装 Python、无需安装 MongoDB、无需起任何服务
- 数据全部存在本机，离线也能查看已同步的行情与计算结果
- 与现有 Web 版功能一致（同一套前端、同一套后端逻辑）

### 1.2 明确不做

| 不做 | 理由 |
| :--- | :--- |
| 远程服务器 / 云端多用户 | 用户明确要求「不需要远程服务器，直接在 Electron 内部交互数据」 |
| 重新实现业务逻辑（Node 重写） | 量化计算（RPS/ATR/ENE/二阶段）已在 Python，重写成本极高且易产生口径偏差 |
| 改用 SaaS 数据库 | 现有数据模型与 973 万条日线都在 MongoDB，迁移收益远小于成本 |

---

## 二、现状盘点（决定方案的关键事实）

| 项目 | 现状 | 对桌面端的影响 |
| :--- | :--- | :--- |
| 前端 | React 18 + Vite，`app/client`，产物 `dist/` | 可直接 `file://` 或 `app://` 加载 |
| 后端 | FastAPI + uvicorn，`app/server/main.py`，固定 `:8000` | 需改为端口由主进程分配 |
| 数据库 | MongoDB，`MONGODB_URI` 默认 `mongodb://localhost:27017/`，库 `yuquant` | **必须随包携带 mongod** |
| 数据规模 | 数据 6.63 GB / 存储 2.58 GB / 索引 0.47 GB；`stock_daily` 973 万条 6.3 GB | 安装包与首次初始化体验的核心矛盾 |
| Python | **3.14.3**，`.venv` 296 MB | 打包工具链对 3.14 支持尚不成熟（见 §7.1 风险） |
| 依赖体积 | pandas 48 MB、numpy 28 MB、akshare 9.5 MB、pymongo 5.6 MB | onedir 产物预估 250~350 MB |
| 外部数据源 | pytdx（TDX 行情服务器，需公网）、DeepSeek API（需公网） | 离线时需降级而非崩溃 |
| 启动方式 | `start.sh`：uvicorn `:8000` + `vite` `:3000` | 桌面端替代该脚本 |

---

## 三、方案选型

| 方案 | 描述 | 结论 |
| :--- | :--- | :--- |
| **A. Electron + 内嵌 Python 后端 + 内嵌 MongoDB** | 主进程拉起 mongod 与 uvicorn 两个子进程，渲染进程加载前端 dist，通过本地回环 HTTP 通信 | ✅ **推荐**。零业务代码重写，风险集中在打包而非逻辑 |
| B. Electron + 纯前端访问数据库 | 渲染进程直连 MongoDB（`mongodb` Node 驱动），去掉 Python | ❌ 需把 RPS/ATR/ENE/二阶段等全部计算用 JS 重写，口径与现有实现必然漂移 |
| C. Tauri + 内嵌 Python | Rust 壳更小，但仍需 Python sidecar | ⚠️ 体积更优，但 Rust 工具链与 sidecar 调试成本高，收益不足以抵消团队熟悉度 |
| D. Electron + 远程 API | 壳只做展示 | ❌ 与「不依赖远程服务器」冲突 |

**采用方案 A。** 下文均按 A 展开。

---

## 四、目标架构

### 4.1 进程拓扑

```
┌──────────────────────────────────────────────────────────────┐
│ Electron 主进程 (Node)                                        │
│  ├─ 申请空闲端口 P_mongo、P_api                                │
│  ├─ spawn mongod  --dbpath <userData>/data/mongo --port P_mongo│
│  ├─ spawn youquant-backend（Python 可执行）                     │
│  │     env: MONGODB_URI=mongodb://127.0.0.1:P_mongo/yuquant    │
│  │          APP_PORT=P_api  APP_TOKEN=<一次性随机 token>        │
│  ├─ 健康检查 GET http://127.0.0.1:P_api/api/health 就绪后再开窗   │
│  └─ 退出时：先 SIGTERM backend → 再 mongod 正常 shutdown        │
└──────────────────────────────────────────────────────────────┘
        │ preload 注入 window.__APP_BOOT__ = { apiBase, token }
        ▼
┌──────────────────────────────────────────────────────────────┐
│ 渲染进程（现有 React dist）                                     │
│  axios baseURL = window.__APP_BOOT__.apiBase ?? '/api'         │
└──────────────────────────────────────────────────────────────┘
                     │ HTTP 127.0.0.1（仅回环）
                     ▼
┌──────────────────────────────────────────────────────────────┐
│ uvicorn (Python) ──► MongoDB (本地 mongod)                    │
└──────────────────────────────────────────────────────────────┘
```

**关键点**：这里的 HTTP 只是**同一台机器内的进程间通信**（127.0.0.1），不对外暴露，也不存在远程服务器。这样做的原因是现有前端 100% 走 axios，保留 HTTP 契约可以让前端零改动（仅注入 baseURL）。

### 4.2 数据目录（`app.getPath('userData')`）

| 平台 | 路径 |
| :--- | :--- |
| macOS | `~/Library/Application Support/YuQuant/` |
| Windows | `%APPDATA%\YuQuant\` |
| Linux | `~/.config/YuQuant/` |

```
YuQuant/
├─ data/mongo/            # mongod dbpath（journal、数据文件）
├─ data/mongo.log
├─ logs/backend.log
├─ logs/mongod-stdout.log
├─ config/pytdx_servers.json   # 首次启动从 resources 复制，之后用户可改
└─ app.json               # 窗口尺寸、最近访问日期等 UI 状态
```

---

## 五、关键技术设计

### 5.1 后端进程托管

| 事项 | 设计 |
| :--- | :--- |
| 启动 | `child_process.spawn(exePath, [], { env })`，`detached: false`，`stdio: 'pipe'` 落盘 |
| 端口 | 主进程用 `net.createServer().listen(0)` 拿到空闲端口后关闭，再传给子进程（避免固定端口冲突） |
| 就绪判定 | 轮询 `GET /api/health`（最多 60s，指数退避），超时才提示错误并展示日志路径 |
| 崩溃处理 | 监听 `exit`：非正常退出且用户未主动退出 → 自动重启（最多 3 次，间隔递增）；仍失败则弹窗给出日志路径 |
| 退出 | `before-quit` 中：先请求 `POST /api/shutdown`（或 SIGTERM）→ 等后端退出 → 再 `mongod --shutdown`；超时 10s 强杀 |
| 单实例 | `app.requestSingleInstanceLock()`，防止两个实例同时占用同一 dbpath（mongod 会锁冲突） |

### 5.2 Python 运行时打包

| 方案 | 说明 | 评估 |
| :--- | :--- | :--- |
| **PyInstaller onedir** | 打好一个目录，含解释器与依赖 | ✅ 推荐。onedir（非 onefile）启动快、便于排查 |
| python-build-standalone + 依赖目录 | 官方可重定位解释器 + `pip install --target` | 备选。对 3.14 兼容性更可控，但需自己处理 `sys.path` |
| onefile | 单文件自解压 | ❌ 每次启动解压 300MB，首启 5~10s，不可接受 |

**版本建议**：把打包用的解释器**降到 3.12 LTS**（业务代码无 3.13/3.14 特性依赖），以规避 PyInstaller 对 3.14 的支持缺口。开发环境可继续用 3.14。

打包入口：新增 `electron/backend_entry.py`（`uvicorn.run(app, host='127.0.0.1', port=APP_PORT)`），避免直接打包 `app/server/main.py` 带来的相对导入问题。

**体积裁剪**：
- `akshare`/`baostock`/`yfinance` 仅用于「基础信息 + 名称纠错」，桌面端可改为**可选依赖**：缺失时该功能降级（`repair_stock_names` 不可用），可省约 15~20 MB 及其传递依赖
- 排除测试数据、`*.pyc` 去重、`--exclude-module tkinter/matplotlib`

### 5.3 MongoDB 打包

| 方案 | 说明 | 评估 |
| :--- | :--- | :--- |
| **随包携带 mongod 二进制** | 每个平台携带官方社区版 `mongod`（约 80~120 MB/平台），主进程托管 | ✅ 推荐。与现有数据访问层零改动 |
| 依赖用户自装 MongoDB | 安装包小，但用户门槛高 | ❌ 违背「双击即用」 |
| 改用 SQLite/DuckDB 重写数据层 | 无独立进程、体积小 | ❌ 973 万条 + 现有 `pymongo` 查询/聚合全部重写，成本远超收益（可作为长期演进方向） |

**注意**：
- mongod 需要能正常退出（journal 保证崩溃恢复），退出流程必须走 `--shutdown` 而非直接 kill
- 首次启动需在空 dbpath 上初始化（mongod 自动创建），并建好索引（现有 `app/data/db.py` 已负责建索引，依赖后端启动流程）
- 磁盘占用预算：数据 2.6~6.6 GB + journal，建议在「关于」页显示占用并提供清理入口

### 5.4 数据初始化与迁移（体验核心）

现状是 6.63 GB 数据。三个可选策略：

| 策略 | 安装包 | 首启体验 | 适用 |
| :--- | :--- | :--- | :--- |
| **① 空库 + 引导同步** | 小（约 300~400 MB） | 需联网，首次全量拉 10 年历史耗时长 | ✅ 新用户首选 |
| ② 随包种子数据（压缩 dump） | 大（+0.8~1.5 GB） | 即开即用，无网络也能看历史 | 追求开箱即用 |
| ③ 导入现有 dump | 小 | 老用户手动导入一次 | 现有 Web 用户迁移 |

**推荐：① 为默认 + ③ 为高级入口**，② 作为可选「完整数据版」安装包。

首次启动引导流程（复用现有任务系统与全局任务中心）：
1. 选择同步范围：`最近 1 年` / `全部历史（约 10 年）`
2. 后台任务执行「基础信息 → 个股/板块/ETF 日线 → RPS/均线/二阶段」
3. 顶栏任务指示器显示进度，可中断、可断点续传（按 `trade_date` 边界）
4. 同步期间允许浏览已就绪部分

**现有数据迁移**：提供「导入数据包」入口，调用 `mongorestore`（随包携带同版本工具）从 `.archive.gz` 恢复；导入前提示会覆盖同名库。

### 5.5 前端集成

| 事项 | 设计 |
| :--- | :--- |
| 加载方式 | 生产：`loadFile(dist/index.html)` 或自定义 `app://` 协议（推荐后者，避免 `file://` 的 fetch/路由限制） |
| 路由 | 现用 `BrowserRouter`，`app://` 下需确认 history 回退；必要时切 `HashRouter`（改动极小） |
| API baseURL | `app/client/src/api.js` 增加一行：`const BASE = window.__APP_BOOT__?.apiBase ?? '/api'`，其余不动 |
| 请求头 | preload 注入 token，axios 拦截器加 `X-App-Token`（后端校验，防本机其他程序调用） |
| 构建 | `vite build` 产物作为 `electron-builder` 的 `extraResources` |

### 5.6 安全基线

- `nodeIntegration: false`、`contextIsolation: true`、`sandbox: true`
- preload 仅暴露 `window.__APP_BOOT__ = { apiBase, token, version }`，不暴露 `ipcRenderer` 原对象
- 后端只 `bind 127.0.0.1`，校验 `X-App-Token`
- 生产关闭 DevTools、禁止新窗口导航（`will-navigate` / `setWindowOpenHandler` 白名单）
- CSP：`default-src 'self'; connect-src 'self' http://127.0.0.1:*`

### 5.7 自动更新

- `electron-updater` + 静态更新源（GitHub Releases 或对象存储）
- 差分更新（blockmap）减小下载量
- 更新前置条件：先停后端与 mongod，更新后重启（避免覆盖正在写的文件）

### 5.8 日志与诊断

- 统一 `userData/logs/`：`backend.log`、`mongod-stdout.log`、`main.log`
- 「关于」页提供：版本、数据目录、磁盘占用、**一键导出诊断包**（压缩最近 3 天日志 + `db.stats()` 摘要，不含行情原始数据）

### 5.9 跨平台矩阵

| 平台 | 架构 | 优先级 | 备注 |
| :--- | :--- | :--- | :--- |
| macOS | arm64 | P0 | 开发机同架构；需签名 + 公证（无账号则用户需右键打开） |
| macOS | x64 | P1 | 同一份 Python/mongod 需 x64 版本 |
| Windows | x64 | P1 | 需注意 PyInstaller onedir 被杀软误报（签名可缓解） |

---

## 六、目录结构建议（新增，不改动 `app/`）

```
electron/
├─ package.json              # electron-builder 配置、依赖
├─ main.js                   # 主进程：单实例、端口、进程托管、窗口
├─ preload.js                # 注入 __APP_BOOT__
├─ lib/
│  ├─ ports.js               # 空闲端口探测
│  ├─ mongo.js               # mongod 启停、健康检查、优雅关闭
│  ├─ backend.js             # 后端启停、健康检查、崩溃重启
│  └─ paths.js               # userData 目录推导
├─ backend_entry.py          # 后端打包入口
├─ build/                    # 图标、entitlements、notarize 配置
└─ resources/
   ├─ bin/<platform>/mongod  # 随包二进制
   └─ config/pytdx_servers.json
```

---

## 七、里程碑（每阶段可独立验收）

### M1 · 壳与闭环（不打包 Python/Mongo）
- Electron 壳加载前端 dist；dev 下复用现有 `start.sh` 启动的后端
- 注入 `apiBase`，验证「搜索 → K 线 → 关注 → 持仓」全流程可用
- **验收**：`npm run electron:dev` 打开窗口，页面数据与浏览器一致

### M2 · 自包含运行时
- 打包 Python（PyInstaller onedir）+ 携带 mongod
- 主进程托管两进程、动态端口、健康检查、优雅退出、崩溃重启
- 数据目录切到 `userData`
- **验收**：在未安装 Python/MongoDB 的干净机器上，双击即可打开并使用（空库）

### M3 · 数据初始化体验
- 首启引导：同步范围选择、进度可视化（复用全局任务中心）
- 断点续传、可中断；离线降级提示
- 「导入数据包」入口（`mongorestore`）
- **验收**：新机器从 0 到「能看最近一年行情」≤ 15 分钟（视网络）

### M4 · 发布就绪
- 签名/公证（macOS）、Windows 签名（可选）
- 自动更新、诊断包导出、关于页
- **验收**：一次完整升级流程验证通过

---

## 八、风险与对策

| 风险 | 影响 | 对策 |
| :--- | :--- | :--- |
| **Python 3.14 打包支持不足** | M2 阻塞 | 打包用 3.12 LTS；业务代码无高版本语法依赖 |
| 安装包体积过大（>600 MB） | 分发与下载体验差 | 裁剪 akshare/baostock 等可选依赖；不预置种子数据；差分更新 |
| mongod 进程被强杀导致数据文件损坏 | 数据丢失 | 退出走 `--shutdown`；启用 journal；启动失败的自动修复提示 |
| 首次全量同步耗时长（数小时） | 用户流失 | 默认只同步近 1 年；进度可见可中断；补偿「导入数据包」路径 |
| PyInstaller 产物被杀软误报 | Windows 无法启动 | 代码签名；优先 onedir；提供免安装 zip |
| 端口被占用 | 启动失败 | 动态端口；失败时给出明确提示与重试 |
| `app://` 下路由/静态资源异常 | 页面白屏 | 优先 `app://` + 验证 `BrowserRouter`；必要时切 `HashRouter` |
| 后端仅 127.0.0.1 仍可能被本机程序调用 | 数据被第三方读取 | 一次性 token + 校验头 |

---

## 九、待确认问题（需业务决策）

1. **数据初始化策略**：空库引导同步（推荐）/ 随包种子数据 / 两者都提供？
2. **可接受的安装包体积上限**：300~400 MB（无种子）能否接受？
3. **平台优先级**：先只做 macOS arm64，还是一次做 mac(arm64/x64)+Windows？
4. **离线预期**：是否需要「完全无网络也能安装并查看历史行情」（若是，则必须选种子数据方案）？
5. **签名账号**：是否已有 Apple Developer 账号（影响 macOS 分发方式）？
6. **老用户迁移**：是否需要我提供一个「从现有 6.63 GB 库导出 → 桌面端导入」的脚本？

---

## 十、附：与现有工程的衔接点

| 衔接点 | 改动 |
| :--- | :--- |
| `app/server/main.py` | 端口从 `APP_PORT` 读取；新增 `/api/shutdown`（仅本机 token 可调） |
| `app/data/db.py` | `MONGODB_URI` 由主进程注入，代码无需改 |
| `app/client/src/api.js` | 增加 `BASE` 取自 `window.__APP_BOOT__`（1 行） |
| `start.sh` / `restart.sh` | 保留（Web 开发模式仍用）；桌面端另走 electron 脚本 |
| `requirements.txt` | 拆分 `requirements-desktop.txt`，剔除 akshare/baostock/yfinance 等可选依赖 |
