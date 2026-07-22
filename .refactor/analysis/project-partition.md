# Phase 0: 项目分区与资源盘点

**分析日期**: 2026-07-22
**项目**: A股量化仿真与前端看板系统
**技术栈**: React 18 + FastAPI + MongoDB + Pydantic

---

## 1. 目录结构概览

```
app/
├── client/                    # 前端 React 应用
│   └── src/
│       ├── App.jsx            # 主入口（258行）
│       ├── api.js             # API 封装（187行）
│       ├── components/        # 通用组件（12个）
│       └── pages/             # 页面组件（8个）
│
├── server/                    # 后端 FastAPI 应用
│   ├── main.py               # 入口（125行）
│   ├── config.py             # 配置中心（新建）
│   ├── models.py             # Pydantic 模型
│   ├── cache.py              # 内存缓存
│   ├── api/                  # 路由层（10个文件，共 12,441 行）
│   │   ├── factors.py        # 因子 API（1915行）⚠️ 过大
│   │   ├── market_review.py  # 市场复盘（3115行）⚠️ 过大
│   │   ├── calendar.py       # 日历复盘（1546行）⚠️ 过大
│   │   ├── one_click_update.py # 一键更新（466行）
│   │   ├── sync.py           # 数据同步（335行）
│   │   └── ...
│   └── services/             # 服务层
│       └── factor_service.py # 因子服务（1295行）⚠️ 过大
│
├── data/                     # 数据层
│   ├── db.py                 # MongoDB 连接（496行）
│   ├── manager.py            # 数据管理器（703行）
│   ├── task_manager.py       # 任务管理器（347行）
│   ├── holidays.py           # 节假日判断
│   └── sources/              # 数据源（7个）
│       ├── pytdx_source.py   # 通达信（1388行）
│       ├── tqcenter_source.py # 天勤（598行）
│       ├── akshare_source.py
│       └── ...
│
└── engine/                   # 计算引擎
    ├── factor_engine.py      # 因子引擎（602行）
    └── rps_calculator.py     # RPS 计算器（523行）
```

**代码量统计**:
- 后端 Python: 16,436 行
- 前端 JS/JSX: 8,152 行
- 总计: 24,588 行

---

## 2. 领域划分

```
项目领域划分
├── 前端域 (Frontend Domain)
│   ├── 页面层 (pages/)        - 8个页面组件
│   ├── 组件层 (components/)   - 12个业务组件
│   ├── 基础设施 (api.js)      - API 封装
│   └── 样式 (index.css)       - Tailwind CSS
│
├── 后端域 (Backend Domain)
│   ├── 路由层 (api/)          - 10个路由文件
│   ├── 服务层 (services/)     - factor_service
│   ├── 引擎层 (engine/)       - factor_engine, rps_calculator
│   └── 数据层 (data/)         - db, manager, sources
│
└── 公共域 (Common Domain)
    ├── 配置 (config.py, .env)
    └── 模型 (models.py)
```

---

## 3. 资源盘点

### 3.1 前端资源

#### UI 组件库 (Ant Design)
| 组件 | 使用文件数 | 使用位置 |
|------|-----------|----------|
| Button | 12 | 全局 |
| Spin | 6 | 全局加载状态 |
| Modal | 5 | 弹窗 |
| message | 5 | 全局提示 |
| notification | 3 | 通知 |
| Tag | 5 | 标签 |
| Select | 5 | 下拉选择 |
| Table | 3 | 表格 |
| Tooltip | 4 | 提示 |
| ConfigProvider | 3 | 国际化 |
| Segmented | 3 | 分段控制器 |
| DatePicker | 3 | 日期选择 |
| Input | 1 | 输入框 |
| Form | 1 | 表单 |
| Switch | 1 | 开关 |
| Empty | 1 | 空状态 |
| Result | 1 | 结果展示 |
| List | 1 | 列表 |
| Typography | 2 | 排版 |
| Space | 2 | 间距 |

#### 图表库
| 库 | 使用文件 | 用途 |
|----|---------|------|
| lightweight-charts | TradingViewChart.jsx | K线图 |
| recharts | MarketOverview, MaBreadthChart, NhNlOverlayChart | 统计图表 |
| echarts | 未找到直接使用 | ⚠️ 未使用但安装 |
| echarts-for-react | 未找到直接使用 | ⚠️ 未使用但安装 |

#### 自定义组件
| 组件 | 行数 | 用途 |
|------|------|------|
| AiAnalysis | 480 | AI 分析展示 |
| TradingViewChart | 679 | K线图 |
| MarketSignals | 598 | 市场信号 |
| ManagementDialog | 280 | 管理弹窗 |
| MarketReview | 368 | 市场复盘 |
| NhNlOverlayChart | 212 | NH-NL 图表 |
| MarketOverview | 163 | 市场概览 |
| MaBreadthChart | 155 | MA 广度图 |
| TacticalAllocationCard | 125 | 战术配置 |
| ErrorBoundary | - | 错误边界 |

#### 自定义 Hooks
| Hook | 用途 |
|------|------|
| 无 | ⚠️ 没有自定义 hooks |

#### 工具函数
| 函数 | 位置 | 用途 |
|------|------|------|
| 无独立 utils | - | ⚠️ 没有独立的工具函数目录 |

---

### 3.2 后端资源

#### 数据源 (data/sources/)
| 数据源 | 行数 | 用途 |
|--------|------|------|
| pytdx_source | 1388 | 通达信数据 |
| tqcenter_source | 598 | 天勤数据 |
| akshare_source | ~200 | AkShare 数据 |
| baostock_source | ~100 | BaoStock 数据 |
| yfinance_source | ~50 | Yahoo Finance |
| tushare_source | ~100 | Tushare 数据 |
| tencent_mv | ~50 | 腾讯市值 |

#### 服务层 (services/)
| 服务 | 行数 | 职责 |
|------|------|------|
| factor_service | 1295 | 因子计算、指数管理、数据同步 |

#### 引擎层 (engine/)
| 引擎 | 行数 | 职责 |
|------|------|------|
| factor_engine | 602 | RPS 计算、冗余字段计算 |
| rps_calculator | 523 | RPS 计算（独立模块） |

#### 基础设施
| 基础设施 | 位置 | 用途 |
|----------|------|------|
| 日志系统 | main.py | Python logging，输出到 logs/ |
| 缓存系统 | cache.py | 内存缓存（threading.Lock） |
| 配置系统 | config.py | pydantic-settings |
| 任务管理 | task_manager.py | MongoDB 持久化任务状态 |
| 节假日 | holidays.py | 交易日判断 |

---

### 3.3 基础设施清单

| 基础设施类型 | 当前状态 | 评价 |
|-------------|---------|------|
| 日志系统 | ✅ 有 | Python logging，统一配置 |
| 错误处理 | ⚠️ 部分统一 | 后端混合 HTTPException/return dict |
| 配置管理 | ✅ 新建 | pydantic-settings |
| 缓存系统 | ⚠️ 简单 | 仅内存缓存，无 Redis |
| 任务管理 | ✅ 有 | MongoDB 持久化 |
| 路由系统 | ✅ 有 | React Router |
| 请求拦截 | ✅ 有 | Axios 拦截器 |
| 类型系统 | ❌ 无 | 全部 JSX，无 TypeScript |
| 测试 | ❌ 极少 | 仅 2 个测试文件 |
| CI/CD | ❌ 无 | 无自动化流水线 |
| 容器化 | ❌ 无 | 无 Docker |

---

## 4. Phase 0 输出

**资源盘点完成**。关键发现：
1. 后端路由层文件过大（factors.py 1915行, market_review.py 3115行, calendar.py 1546行）
2. 无自定义 hooks，前端逻辑全部内联在组件中
3. 图表库冗余（echarts 已安装但未使用）
4. 无 TypeScript 类型系统
5. 无测试覆盖
6. get_db() 调用 142 次，分散在所有路由文件中
