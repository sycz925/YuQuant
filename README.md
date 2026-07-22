# 📊 A股量化系统

基于 **React + FastAPI** 分离架构的A股量化系统，提供专业的市场监控、复盘报告和AI分析功能。

## ✨ 功能特性

### 🔍 市场监控
- **趋势对比图**：CR5%（个股）与 CR10%（板块）拥挤度对比，叠加大盘指数，支持日/周/月/季/年周期
- **均线占比趋势**：MA50/MA20 站上均线比例历史曲线，叠加大盘指数
- **新高新低指数（NH-NL）**：250日滚动窗口，剔除上市未满1年新股，与大盘叠加
- **主要大盘指数涨跌幅**：含 PE_TTM 市盈率数据（乐咕乐股源）
- **AI 综合研判**：基于 DeepSeek API，融合交易哲学生成专业分析

### 📈 复盘报告（A股运行状态与板块效应）
- **新高板块效应聚类**：Top10 强势行业，展示先锋/中军/后排三梯队个股
- **低位潜力板块**：筛选短线爆发+长线低位的潜力板块

## 📐 核心算法

### CR5% 个股成交额前5%拥挤度
```
CR5% = 成交额最高的5%个股成交额之和 / 全市场成交额 × 100%
```
- CR5% > 55%：资金高度集中，市场分化严重
- CR5% 30%-55%：正常水平
- CR5% < 30%：资金分散，普涨或普跌

### CR10% 板块成交额前10%拥挤度
```
CR10% = 成交额最高的10%板块成交额之和 / 全市场板块成交额 × 100%
```
必须用 `sector_daily`（板块级）计算。

### NH-NL 新高新低指数（Elder）
```
NH = 当日收盘价 >= 过去250个交易日最高收盘价的股票数（不含当天）
NL = 当日收盘价 <= 过去250个交易日最低收盘价的股票数（不含当天）
```
- **250日滚动窗口**：`[当天前一个交易日 - 365天, 当天前一个交易日]`，不含当天
- **剔除次新股**：上市未满365天不参与计算

### 新高板块效应聚类
从新高股票中提取行业聚类，展示强势板块的三梯队个股。排除禁用板块。

| 梯队 | 数量 | 选取规则 | 含义 |
|------|------|----------|------|
| 先锋 pioneer | 3只 | 按 chg_50d（50日涨幅）降序 | 50日涨幅最高的领涨股 |
| 中军 main_force | 3只 | 成交额 Top10 内按 chg_50d 降序 | 市值大+50日涨幅高的核心股 |
| 后排 followers | 2只 | 成交额升序 Top20（排除ST）按当日涨幅降序 | 低价+当天涨幅高的补涨股 |

板块涨幅取自 `sector_daily.chg_pct`，非新高股平均值。

### 低位潜力板块
筛选条件：
1. 板块指数 MA10 > MA20
2. RPS10 > 85（短线爆发力）
3. RPS50 < 70（长线趋势尚未走强，低位）
4. 近3天有1天以上 ≥15% 的股票创20日新高
5. 近5天有4天净新高(20日新高-20日新低) > -10

排除禁用板块，按 RPS10 降序，最多返回5个。包含先锋/中军/后排个股。

### RPS 相对强度
```
RPS = rank(区间涨幅) / 总数 × 100
```
支持 10/20/50/120/250 日多周期。

### DeepSeek AI 综合研判
- 调用 `deepseek-v4-pro` + 思考模式（reasoning_effort=high）
- 输入数据全部从 `market_daily` + `base_data_daily` 读取，不实时计算
- 盘后每日仅调一次，结果缓存到 `market_daily.ai_analysis`

## 📊 数据预计算与缓存

### "同步基础数据"一键预计算
点击 Settings 指数卡片的"同步基础数据"按钮，一键完成：
1. **base_data_daily**：CR5/CR10/MA50/MA20/NH/NL
2. **market_daily**：overview + new_high（新高板块聚类） + low_position_sectors（低位潜力板块）

市场监控页面直接从数据库读取，无需实时计算。

### base_data_daily 宽表
一行存一个交易日的所有核心指标：

| 字段 | 含义 |
|------|------|
| `cr5_pct` | 个股成交额前5%拥挤度 |
| `cr10_pct` | 板块成交额前10%拥挤度 |
| `ma50_pct` / `ma20_pct` | MA50/MA20 占比 |
| `nh` / `nl` | 250日新高/新低股票数 |
| `is_final` | 是否收盘后最终数据 |

### market_daily 快照
| 字段 | 含义 |
|------|------|
| `overview` | 大盘指数涨跌幅 + PE_TTM |
| `new_high` | 新高板块聚类 Top10 |
| `low_position_sectors` | 低位潜力板块 Top5 |
| `ai_analysis` | DeepSeek AI 研判结果 |
| `is_final` | 是否收盘后数据 |

### sector_daily 板块日线
新增 `nh`/`nl` 字段：板块内个股的250日新高/新低数量（不含当天，剔除次新股）。

## 📐 数据库集合

| 集合 | 用途 | 关键字段 |
|------|------|----------|
| `base_data_daily` | 预计算基础指标（date 主键） | cr5_pct, cr10_pct, ma50_pct, ma20_pct, nh, nl, is_final |
| `market_daily` | 盘后快照 + AI 分析 | trade_date, overview, new_high, low_position_sectors, ai_analysis |
| `stock_daily` | 个股日线 | stock_code, trade_date, close, ma50, ma20, rps_*, chg_*, pe_ttm |
| `index_daily` | 指数日线 | stock_code, trade_date, close, pe_ttm |
| `sector_daily` | 板块日线 | stock_code, trade_date, close, rps_*, nh, nl |
| `sector_basics` | 板块基础信息 | code, name, stock_codes, source |
| `stock_basics` | 个股基础信息 | stock_code, stock_name, list_date |
| `exclusions` | 排除管理 | code, category, exclude_display/sync/rps |

## 🏗️ 技术架构

```
A股量化系统/
├── app/
│   ├── data/                 # MongoDB 数据层
│   │   ├── db.py             # 数据库操作封装 + is_final 管理
│   │   ├── manager.py        # 多源数据同步管理器
│   │   └── task_manager.py   # 后台任务管理
│   │
│   ├── server/               # FastAPI 后端
│   │   ├── cache.py          # 交易日缓存
│   │   └── api/
│   │       ├── market_review.py    # 预计算 + 新高/低位板块 + AI分析
│   │       ├── deepseek_analyst.py # DeepSeek AI桥接
│   │       ├── factors.py          # RPS + 板块同步 + PE同步 + 基础数据预计算
│   │       ├── market_analysis.py  # 多维统计分析 + 气泡图
│   │       └── exclusions.py       # 排除管理
│   │
│   ├── client/               # React 前端
│   │   └── src/
│   │       ├── pages/        # MarketMonitor, MarketAnalysis, Settings, StockAnalysis
│   │       └── components/   # MarketSignals, AiAnalysis, MaBreadthChart, NhNlOverlayChart
│   │
│   └── engine/               # 因子计算引擎
│       └── factor_engine.py  # CR5/CR10/RPS/均线 计算
│
├── data_tools/               # 数据补全工具
├── scripts/                  # 数据修复/预计算脚本
└── requirements.txt
```

## 🚀 快速开始

### 前置条件
- Python 3.8+ / Node.js 16+ / **MongoDB 5.0+**

### 1. 安装依赖
```bash
python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt
cd app/client && npm install
```

### 2. 环境配置
```
MONGODB_URI=mongodb://localhost:27017/
MONGODB_DB_NAME=yuquant
DEEPSEEK_API_KEY=your-key-here
```

### 3. 启动
```bash
./start.sh
```

### 4. 初始化数据
在 Settings 页面依次点击：
1. **同步指数** → 同步指数日线
2. **同步个股** → 同步个股日线
3. **同步板块** → 同步板块数据
4. **计算RPS** → 计算个股和板块 RPS
5. **同步PE** → 同步指数市盈率（需乐咕乐股 Token）
6. **同步基础数据** → 一键生成 base_data_daily + market_daily

## 📚 核心 API

| 端点 | 说明 |
|------|------|
| `GET /base-data` | 统一基础数据（CR5/MA/NH-NL），支持周期聚合 |
| `GET /overview` | 大盘指数涨跌幅（含 PE_TTM） |
| `GET /signals` | A股运行状态指标 |
| `GET /new-high-blocks` | 新高板块聚类 Top10（从 market_daily 缓存读取） |
| `GET /low-position-sectors` | 低位潜力板块 Top5（从 market_daily 缓存读取） |
| `GET /ai-analysis` | DeepSeek AI 分析 |
| `POST /factors/precompute-base` | 一键预计算基础数据（后台任务） |
| `POST /factors/sync-index-pe` | 同步指数 PE（乐咕乐股） |

## ⏱️ 数据同步策略

- **时间窗口**：盘中 11:30-13:00、盘后 15:30-23:59
- **数据源瀑布**：TqCenter → PyTdX → AkShare → BaoStock
- **板块成分股来源**：东方财富（138个行业+概念板块）+ 同花顺（22个行业板块）+ 通达信概念（204个）
- **板块来源标记**：`sector_basics.source` 字段记录数据来源（东方财富/通达信概念/同花顺）

## 📄 许可证

MIT License
