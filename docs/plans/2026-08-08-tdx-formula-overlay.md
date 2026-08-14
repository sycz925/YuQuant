# 通达信公式叠加 K 线主图 实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 `/search?sector=880652` 等全部 K 线页面（个股/ETF/板块统一）主图上，用通达信公式（MA7 蓝色粗线 + KD 红色信号段 + KK 绿色信号段）叠加显示，替换原 MA10/MA20/MA120 数据库均线。

**Architecture:** 纯前端实现。公式所需的 EMAD(EMA7)/EMAC(EMA21)/MA7/MA10/MACD 全部由收盘价序列在 `TradingViewChart.jsx` 内部计算，不依赖后端返回 ma 字段。移除周线/月线切换（TIME_PERIODS 只留日线），消除月线仅 ~10 条数据时 EMA21 无法计算的隐患。改动仅两个文件：`StockAnalysis.jsx`（周期选项）、`TradingViewChart.jsx`（主图叠加）。

**Tech Stack:** React 18, lightweight-charts 4.2.3, Vite, Ant Design（Segmented/Select）

**已确认决策：**
- 作用范围：个股/ETF/板块全部统一（TradingViewChart 为共享组件，一处改全局生效）
- 原 MA10/MA20/MA120 数据库均线：**全部移除**，主图只画新公式线
- 时间周期：**页面只显示日线**，移除周线/月线选项及其转换逻辑
- 公式内含 MA10 只作 KD 条件，不画线

**公式定义（用户提供，通达信语法）：**
```
EMAD:=EMA(C,7);
EMAC:=EMA(C,21);
MA10:=MA(C,10);
MAXX:MA(C,7);                 // 蓝色粗线
KD = EMAD上升 且 EMAC上升 且 MACD>REF(MACD,1) 且 MA10上升 → 7日线红色粗线
KK = (EMAD或EMAC任一下降) 且 MACD<REF(MACD,1) → 绿色粗线
```

**参考现有代码：**
- `app/client/src/pages/StockAnalysis.jsx:16-20` TIME_PERIODS 定义；L150-280 convertToWeekly/convertToMonthly；L382-386 周期转换调用；L620-629 周期 Select；L133-137、L532-537 useEffect 依赖 timePeriod
- `app/client/src/components/TradingViewChart.jsx:40-58` calculateMACD；L61-70 calculateMA；L142-153 ma10/ma20/ma120Data 提取；L266-272 均线 series；L406-446 updateLabels；L489-520 hoverData
- 前端无测试框架（package.json 仅 dev/build/preview），验证方式为 `npm run build` + 浏览器手动核验

---

### Task 1: StockAnalysis 移除周线/月线，只留日线

**Files:**
- Modify: `app/client/src/pages/StockAnalysis.jsx`

**Step 1: 修改 TIME_PERIODS 只保留日线**

将 L16-20 的 TIME_PERIODS 数组改为仅日线，并移除 getISOWeek/convertToWeekly/convertToMonthly 三组函数（L134-280）。

```jsx
// 时间周期选项（仅日线）
const TIME_PERIODS = [
  { value: 'day', label: '日线' }
]
```

**Step 2: 移除周期转换逻辑**

L382-386 删除：
```jsx
      // 根据时间周期转换数据
      if (timePeriod === 'week') {
        data = convertToWeekly(data)
      } else if (timePeriod === 'month') {
        data = convertToMonthly(data)
      }
```

L512-518 删除：
```jsx
        // 根据时间周期转换
        let processedData = mergedData
        if (timePeriod === 'week') {
          processedData = convertToWeekly(mergedData)
        } else if (timePeriod === 'month') {
          processedData = convertToMonthly(mergedData)
        }

        setAllData(processedData)
```
改为直接 `setAllData(mergedData)`（注意保留 L520 的 setCurrentIndex 更新逻辑）。

**Step 3: 移除周期切换 Select（L620-629）**

删除整段 `Select value={timePeriod}` 块（含 TIME_PERIODS.map）。保留加载更多数据的左/右箭头按钮（loadingMore/handleMoveLeft 仍被 L555 加载更多逻辑使用）。

**Step 4: 清理 timePeriod state 相关**

- L39 `const [timePeriod, setTimePeriod] = useState('day')` 可删除（确认无其它引用）
- L533-537 useEffect 依赖 `[timePeriod]` 改为 `[]` 或直接删除（loadInitialData 在 selectedCode 变化时已触发）
- L540-547 displayData useMemo 依赖 `[allData, currentIndex, timePeriod]` 移除 timePeriod
- L550-560 handleMoveLeft/Right 依赖数组中的 timePeriod 一并移除
- L672 TradingViewChart 的 `period={timePeriod}` prop 删除（组件层确认后可移除 prop）

**Step 5: 验证构建**

Run: `npm run build`（在 app/client 目录）
Expected: 构建成功，无未使用变量告警报错

**Step 6: Commit**

```bash
git add app/client/src/pages/StockAnalysis.jsx
git commit -m "feat: K线页面仅保留日线，移除周/月线切换"
```

---

### Task 2: TradingViewChart 新增通达信公式计算

**Files:**
- Modify: `app/client/src/components/TradingViewChart.jsx`

**Step 1: 新增 calculateEMA 辅助函数（紧邻 L40 calculateMACD 之上或之后）**

```js
// EMA 计算
const calculateEMA = (data, period) => {
  const k = 2 / (period + 1);
  let prev = data[0];
  const res = [prev];
  for (let i = 1; i < data.length; i++) {
    prev = data[i] * k + prev * (1 - k);
    res.push(prev);
  }
  return res;
};
```

注意：现有 calculateMACD 内部已有内联 ema 闭包，可复用不改。calculateEMA 用于主图公式 EMAD/EMAC。

**Step 2: 新增通达信信号计算函数（calculateMA 下方）**

```js
// 通达信主图公式：MA7蓝线 + KD红段 + KK绿段
const calculateTDXOverlay = (data) => {
  const closes = data.map(d => d.close);
  const ema7 = calculateEMA(closes, 7);
  const ema21 = calculateEMA(closes, 21);
  const ma7 = calculateMA(data, 7);
  const ma10 = calculateMA(data, 10);
  const macd = calculateMACD(data);

  // 构建索引映射 time -> 指标
  const idx = {};
  data.forEach((d, i) => {
    idx[d.time] = {
      ema7: ema7[i], ema21: ema21[i],
      ma10: ma10.find(m => m.time === d.time)?.value ?? null,
      macd: macd[i].macd,
    };
  });

  const kdData = [];
  const kkData = [];
  const ma7Full = [];
  for (let i = 0; i < data.length; i++) {
    const d = data[i];
    const t = d.time;
    const cur = idx[t];
    const prev = idx[data[i - 1]?.time];
    const m7 = ma7.find(m => m.time === t)?.value ?? null;
    ma7Full.push({ time: t, value: m7 });

    if (!cur || !prev || m7 === null) {
      kdData.push({ time: t, value: null });
      kkData.push({ time: t, value: null });
      continue;
    }
    const ema7Up = cur.ema7 > prev.ema7;
    const ema21Up = cur.ema21 > prev.ema21;
    const ma10Up = cur.ma10 !== null && prev.ma10 !== null && cur.ma10 > prev.ma10;
    const macdUp = cur.macd > prev.macd;

    const kd = ema7Up && ema21Up && macdUp && ma10Up;
    const kk = (!ema7Up || !ema21Up) && !macdUp;
    kdData.push({ time: t, value: kd ? m7 : null });
    kkData.push({ time: t, value: kk ? m7 : null });
  }
  return { ma7Full, kdData, kkData };
};
```

**Step 3: 移除数据库均线提取，新增公式线数据**

L142-153 删除 ma10Data/ma20Data/ma120Data 提取；在 formatData 返回中移除它们。在 useEffect L169 处改用计算：

```js
const { candles, volumes, volMa5Data, volMa50Data } = formatData(data);
const macdData = calculateMACD(candles);
const { ma7Full, kdData, kkData } = calculateTDXOverlay(candles);
```

**Step 4: 替换主图均线 series（L266-272）**

删除 ma10/ma20/ma120 series 创建与 setData，替换为：

```js
// 通达信公式叠加（MA7 蓝粗线 + KD 红段 + KK 绿段）
const ma7Series = mainChart.addLineSeries({ color: '#5b9bd5', lineWidth: 2, crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: false });
const kdSeries = mainChart.addLineSeries({ color: '#ef5350', lineWidth: 3, crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: false, lineType: 2 });
const kkSeries = mainChart.addLineSeries({ color: '#26a69a', lineWidth: 3, crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: false, lineType: 2 });
ma7Series.setData(ma7Full);
kdSeries.setData(kdData);
kkSeries.setData(kkData);
```

`lineType: 2` = LineType.WithSteps，null 值处保持不连线，形成红/绿信号段独立显示。

**Step 5: 更新 updateLabels 主图标签（L406-415）**

```js
const updateLabels = (time) => {
  // K线标签（通达信公式）
  const ma7 = ma7Full.find(d => d.time === time);
  const kd = kdData.find(d => d.time === time);
  const kk = kkData.find(d => d.time === time);
  mainLabel.innerHTML = `
    <span style="color:#5b9bd5">MA7:${fmt(ma7?.value, priceDec)}</span>
    ${kd?.value !== null && kd?.value !== undefined ? '<span style="color:#ef5350">KD↑</span>' : ''}
    ${kk?.value !== null && kk?.value !== undefined ? '<span style="color:#26a69a">KK↓</span>' : ''}
  `;
```

**Step 6: 更新悬浮框 hoverData（L486-521）**

- L489-491 移除 ma10/ma20/ma120 查找
- 新增 ma7/kd/kk 查找并放入 setHoverData
- L518 `ma10: ma10?.value, ma20: ma20?.value, ma120: ma120?.value` 替换为 `ma7: ma7?.value, kd: kd?.value, kk: kk?.value`

**Step 7: 更新悬浮框 UI（L637-641）**

替换 K线指标块：
```jsx
<div style={{ gridColumn: '1 / -1', marginTop: '6px', borderTop: '1px solid #444', paddingTop: '6px', fontSize: '11px', display: 'flex', gap: '8px' }}>
  <span style={{ color: '#5b9bd5' }}>MA7: {fmt(hoverData.ma7, priceDec)}</span>
  {hoverData.kd !== null && hoverData.kd !== undefined && <span style={{ color: '#ef5350', fontWeight: 'bold' }}>KD信号</span>}
  {hoverData.kk !== null && hoverData.kk !== undefined && <span style={{ color: '#26a69a', fontWeight: 'bold' }}>KK信号</span>}
</div>
```

**Step 8: 验证构建**

Run: `npm run build`（在 app/client 目录）
Expected: 构建成功

**Step 9: 浏览器手动核验**

启动前后端，访问 `/search?sector=880652&name=创新药`：
- 主图显示一条蓝色 MA7 粗线，出现红色粗线段（KD）与绿色粗线段（KK）
- 个股页面（如 `/search?code=688279`）同样显示新公式，不再有 MA10/20/120
- ETF 页面同样生效
- 时间周期切换（周/月）已消失，仅日线
- 悬浮框与主图标签显示 MA7 与 KD/KK 状态

**Step 10: Commit**

```bash
git add app/client/src/components/TradingViewChart.jsx
git commit -m "feat: K线主图用通达信公式叠加 MA7蓝线+KD/KK红绿信号段，替换MA10/20/120"
```

---

## 验证清单（最终）

| # | 验证项 | 预期 |
|---|--------|------|
| 1 | `npm run build` | 成功无报错 |
| 2 | 板块页 `/search?sector=880652` | MA7 蓝粗线 + 红/绿信号段 |
| 3 | 个股页 `/search?code=688279` | 同一套公式线 |
| 4 | ETF 页 `/search?etf=...` | 同一套公式线 |
| 5 | 时间周期选项 | 仅日线，无周/月 |
| 6 | 悬浮框 | MA7 + KD/KK 状态，无 MA10/20/120 |
| 7 | 主图标签 | MA7 + KD↑/KK↓ 指示 |

## 影响面（Impact Dashboard）

- **仅前端，无后端/数据库改动**：公式纯前端计算，板块 API 已返回 close 序列足够使用
- **共享组件全局生效**：TradingViewChart 被 `/analysis`、`/search` 两个路由复用，改动覆盖个股/板块/ETF 全部 K 线
- **无回归风险点**：MACD 副图、成交量图、RPS 图、十字线联动逻辑均不触碰
- **潜在边界**：日线数据不足 7 条时 MA7/信号不显示（正常降级）；板块/ETF 历史数据充足（200 条）
