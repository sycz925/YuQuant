import React, { useEffect, useRef, useCallback, useState, useMemo } from 'react';
import { createChart } from 'lightweight-charts';

// A股颜色配置
const AQ_STYLES = {
  bg: '#131722',
  grid: '#2a2e39',
  upColor: '#ef5350',
  downColor: '#26a69a',
  borderUp: '#ef5350',
  borderDown: '#26a69a',
  wickUp: '#ef5350',
  wickDown: '#26a69a',
};

// 格式化日期为图表内部格式 (yyyy-mm-dd)
const formatDateForChart = (dateStr) => {
  if (!dateStr) return dateStr;
  const s = String(dateStr);
  if (s.length === 8 && /^\d+$/.test(s)) {
    return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`;
  }
  return s;
};

// 格式化日期为悬浮框显示格式 (yyyy/mm/dd)
const formatDateForDisplay = (dateStr) => {
  if (!dateStr) return dateStr;
  const s = String(dateStr);
  if (s.length === 8 && /^\d+$/.test(s)) {
    return `${s.slice(0, 4)}/${s.slice(4, 6)}/${s.slice(6, 8)}`;
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) {
    return s.replace(/-/g, '/');
  }
  return s;
};

// MACD 计算
const calculateMACD = (data, fastPeriod = 12, slowPeriod = 26, signalPeriod = 9) => {
  const closes = data.map(d => d.close);
  const ema = (arr, period) => {
    const k = 2 / (period + 1);
    let val = arr[0];
    const res = [val];
    for (let i = 1; i < arr.length; i++) {
      val = arr[i] * k + val * (1 - k);
      res.push(val);
    }
    return res;
  };
  const emaFast = ema(closes, fastPeriod);
  const emaSlow = ema(closes, slowPeriod);
  const dif = emaFast.map((f, i) => f - emaSlow[i]);
  const dea = ema(dif, signalPeriod);
  const macd = dif.map((d, i) => (d - dea[i]) * 2);
  return data.map((d, i) => ({ time: d.time, dif: dif[i], dea: dea[i], macd: macd[i] }));
};

// 均线计算
const calculateMA = (data, period) => {
  const result = [];
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) continue;
    let sum = 0;
    for (let j = 0; j < period; j++) sum += data[i - j].close;
    result.push({ time: data[i].time, value: sum / period });
  }
  return result;
};

// 成交量均线计算
const calculateVolMA = (data, period) => {
  const result = [];
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) continue;
    let sum = 0;
    for (let j = 0; j < period; j++) sum += data[i - j].value;
    result.push({ time: data[i].time, value: sum / period });
  }
  return result;
};

const fmt = (num, dec = 2) => {
  if (num === null || num === undefined || isNaN(num)) return '-';
  return num.toFixed(dec);
};

const fmtVol = (vol) => {
  if (vol === null || vol === undefined || isNaN(vol)) return '-';
  if (vol >= 1e8) return (vol / 1e8).toFixed(2) + '亿';
  if (vol >= 1e4) return (vol / 1e4).toFixed(2) + '万';
  return vol.toString();
};

export default function TradingViewChart({ data, height = 800, stockCode, period = 'day' }) {
  const containerRef = useRef(null);
  const tooltipRef = useRef(null);
  const verticalLineRef = useRef(null);

  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });
  const [hoverData, setHoverData] = useState(null);

  // 从data中提取RPS数据（与K线使用相同周期的日期）
  const rpsData = useMemo(() => {
    if (!data || data.length === 0) return [];
    return data.filter(d => d.rps_20 !== undefined || d.rps_50 !== undefined);
  }, [data]);

  // 格式化数据
  const formatData = useCallback((rawData) => {
    if (!rawData || !rawData.length) return { candles: [], volumes: [] };
    const sortedData = [...rawData].sort((a, b) => {
      return String(a.trade_date || a.date).localeCompare(String(b.trade_date || b.date));
    });
    // 按时间去重，保留最后一条
    const seen = new Set();
    const uniqueData = sortedData.filter(d => {
      const t = formatDateForChart(d.trade_date || d.date);
      if (seen.has(t)) return false;
      seen.add(t);
      return true;
    });
    const candles = uniqueData.map(d => ({
      time: formatDateForChart(d.trade_date || d.date),
      open: parseFloat(d.open), high: parseFloat(d.high),
      low: parseFloat(d.low), close: parseFloat(d.close),
    }));
    const volumes = uniqueData.map((d, i) => {
      // 收盘价 >= 开盘价 显示红色（涨），收盘价 < 开盘价 显示绿色（跌）
      const isUp = parseFloat(d.close) >= parseFloat(d.open);
      return {
        time: formatDateForChart(d.trade_date || d.date),
        value: parseFloat(d.volume || 0),
        color: isUp ? AQ_STYLES.upColor : AQ_STYLES.downColor
      };
    });
    return { candles, volumes };
  }, []);

  useEffect(() => {
    if (!containerRef.current) return;
    const container = containerRef.current;
    const { candles, volumes } = formatData(data);

    // 计算各项指标
    const macdData = calculateMACD(candles);
    const ma10Data = calculateMA(candles, 10);
    const ma20Data = calculateMA(candles, 20);
    const ma120Data = calculateMA(candles, 120);

    // 成交量均线
    const volMa5Data = calculateVolMA(volumes, 5);
    const volMa50Data = calculateVolMA(volumes, 50);

    // 清空容器
    container.querySelectorAll('.chart-wrapper').forEach(el => el.remove());
    if (verticalLineRef.current) verticalLineRef.current.remove();

    // ==================== 全局垂直十字线 ====================
    const verticalLine = document.createElement('div');
    verticalLine.className = 'global-crosshair-line';
    verticalLine.style.cssText = `
      position: absolute; top: 0; bottom: 0; width: 1px;
      pointer-events: none; z-index: 10; display: none;
      border-left: 1px dashed rgba(117, 134, 150, 0.6);
    `;
    container.appendChild(verticalLine);
    verticalLineRef.current = verticalLine;

    // ==================== 公共配置（禁用缩放，隐藏Y轴） ====================
    const commonOpts = {
      layout: { background: { type: 'solid', color: AQ_STYLES.bg }, textColor: '#d1d4dc' },
      grid: { vertLines: { color: AQ_STYLES.grid }, horzLines: { color: AQ_STYLES.grid } },
      crosshair: {
        mode: 1,
        vertLine: { visible: false },
        horzLine: { color: '#758696', width: 1, style: 1, labelVisible: false },
      },
      rightPriceScale: {
        visible: false,
        borderVisible: false,
        scaleMargins: { top: 0.05, bottom: 0.05 },
      },
      timeScale: {
        borderColor: AQ_STYLES.grid,
        timeVisible: true,
        secondsVisible: false,
        fixLeftEdge: true,
        fixRightEdge: true,
      },
      handleScroll: {
        mouseWheel: false,
        pressedMouseMove: false,
      },
      handleScale: {
        axisPressedMouseMove: false,
        mouseWheel: false,
        pinch: false,
      },
    };

    // ==================== K线图 ====================
    const mainWrapper = document.createElement('div');
    mainWrapper.className = 'chart-wrapper';
    mainWrapper.style.cssText = `height: ${height * 0.4}px; position: relative;`;
    container.appendChild(mainWrapper);

    // K线图标签容器
    const mainLabel = document.createElement('div');
    mainLabel.className = 'chart-label';
    mainLabel.style.cssText = `
      position: absolute; top: 8px; left: 12px; z-index: 10;
      font-size: 11px; font-family: 'Consolas', 'Monaco', monospace;
      display: flex; gap: 12px;
    `;
    mainWrapper.appendChild(mainLabel);

    const mainChart = createChart(mainWrapper, {
      ...commonOpts, width: mainWrapper.clientWidth, height: mainWrapper.clientHeight,
    });
    const candleSeries = mainChart.addCandlestickSeries({
      upColor: AQ_STYLES.upColor, downColor: AQ_STYLES.downColor,
      borderDownColor: AQ_STYLES.borderDown, borderUpColor: AQ_STYLES.borderUp,
      wickDownColor: AQ_STYLES.wickDown, wickUpColor: AQ_STYLES.wickUp,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    candleSeries.setData(candles);

    // 均线
    const ma10Series = mainChart.addLineSeries({ color: '#5b9bd5', lineWidth: 1, crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: false });
    const ma20Series = mainChart.addLineSeries({ color: '#70ad47', lineWidth: 1, crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: false });
    const ma120Series = mainChart.addLineSeries({ color: '#ffc107', lineWidth: 1, crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: false });
    ma10Series.setData(ma10Data);
    ma20Series.setData(ma20Data);
    ma120Series.setData(ma120Data);

    // ==================== 成交量图 ====================
    const volumeWrapper = document.createElement('div');
    volumeWrapper.className = 'chart-wrapper';
    volumeWrapper.style.cssText = `height: ${height * 0.15}px; position: relative;`;
    container.appendChild(volumeWrapper);

    // 成交量图标签容器
    const volumeLabel = document.createElement('div');
    volumeLabel.className = 'chart-label';
    volumeLabel.style.cssText = `
      position: absolute; top: 8px; left: 12px; z-index: 10;
      font-size: 11px; font-family: 'Consolas', 'Monaco', monospace;
      display: flex; gap: 12px;
    `;
    volumeWrapper.appendChild(volumeLabel);

    const volumeChart = createChart(volumeWrapper, {
      ...commonOpts, width: volumeWrapper.clientWidth, height: volumeWrapper.clientHeight,
      timeScale: { ...commonOpts.timeScale, visible: false },
    });
    volumeChart.addHistogramSeries({
      priceFormat: {
        type: 'custom',
        formatter: (value) => {
          if (value >= 1e8) return (value / 1e8).toFixed(1) + '亿';
          if (value >= 1e4) return (value / 1e4).toFixed(0) + '万';
          return value.toFixed(0);
        },
      },
      priceScaleId: 'volume',
      priceLineVisible: false,
      lastValueVisible: false,
    }).setData(volumes);

    // 设置成交量价格轴
    volumeChart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.1, bottom: 0.1 },
    });

    // 成交量均线
    const volMa5Series = volumeChart.addLineSeries({ color: '#c586c0', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    const volMa50Series = volumeChart.addLineSeries({ color: '#5b9bd5', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    volMa5Series.setData(volMa5Data);
    volMa50Series.setData(volMa50Data);

    // ==================== MACD图 ====================
    const macdWrapper = document.createElement('div');
    macdWrapper.className = 'chart-wrapper';
    macdWrapper.style.cssText = `height: ${height * 0.2}px; position: relative;`;
    container.appendChild(macdWrapper);

    // MACD图标签容器
    const macdLabel = document.createElement('div');
    macdLabel.className = 'chart-label';
    macdLabel.style.cssText = `
      position: absolute; top: 8px; left: 12px; z-index: 10;
      font-size: 11px; font-family: 'Consolas', 'Monaco', monospace;
      display: flex; gap: 12px;
    `;
    macdWrapper.appendChild(macdLabel);

    const macdChart = createChart(macdWrapper, {
      ...commonOpts, width: macdWrapper.clientWidth, height: macdWrapper.clientHeight,
      timeScale: { ...commonOpts.timeScale, visible: false },
    });
    const difSeries = macdChart.addLineSeries({ color: '#c586c0', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    const deaSeries = macdChart.addLineSeries({ color: '#ffc107', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    const macdHistSeries = macdChart.addHistogramSeries({ priceFormat: { type: 'price', precision: 4, minMove: 0.0001 }, priceScaleId: '', priceLineVisible: false, lastValueVisible: false });
    difSeries.setData(macdData.map(d => ({ time: d.time, value: d.dif })));
    deaSeries.setData(macdData.map(d => ({ time: d.time, value: d.dea })));
    macdHistSeries.setData(macdData.map(d => ({ time: d.time, value: d.macd, color: d.macd >= 0 ? AQ_STYLES.upColor : AQ_STYLES.downColor })));

    // ==================== RPS图 ====================
    const rpsWrapper = document.createElement('div');
    rpsWrapper.className = 'chart-wrapper';
    rpsWrapper.style.cssText = `height: ${height * 0.2}px; position: relative;`;
    container.appendChild(rpsWrapper);

    // RPS图标签容器
    const rpsLabel = document.createElement('div');
    rpsLabel.className = 'chart-label';
    rpsLabel.style.cssText = `
      position: absolute; top: 8px; left: 12px; z-index: 10;
      font-size: 11px; font-family: 'Consolas', 'Monaco', monospace;
      display: flex; gap: 12px;
    `;
    rpsWrapper.appendChild(rpsLabel);

    const rpsChart = createChart(rpsWrapper, {
      ...commonOpts, width: rpsWrapper.clientWidth, height: rpsWrapper.clientHeight,
      rightPriceScale: {
        visible: false,
        borderVisible: false,
      },
    });

    // 格式化 RPS 数据（从data中提取，与K线使用相同日期）
    let rpsFormatted = {};
    if (rpsData && rpsData.length > 0) {
      const rpsTime = (d) => {
        const dateStr = d.trade_date || d.date;
        return formatDateForChart(dateStr);
      };
      // 按时间去重，保留最后一条
      const dedup = (arr) => {
        const map = new Map();
        arr.forEach(d => { map.set(d.time, d); });
        return Array.from(map.values()).sort((a, b) => a.time.localeCompare(b.time));
      };
      rpsFormatted = {
        rps20: dedup(rpsData.map(d => ({ time: rpsTime(d), value: d.rps_20 })).filter(d => d.value !== null && d.value !== undefined)),
        rps50: dedup(rpsData.map(d => ({ time: rpsTime(d), value: d.rps_50 })).filter(d => d.value !== null && d.value !== undefined)),
        rps120: dedup(rpsData.map(d => ({ time: rpsTime(d), value: d.rps_120 })).filter(d => d.value !== null && d.value !== undefined)),
        rps250: dedup(rpsData.map(d => ({ time: rpsTime(d), value: d.rps_250 })).filter(d => d.value !== null && d.value !== undefined)),
      };
    }

    const rpsSeries20 = rpsChart.addLineSeries({ color: '#ff6b6b', lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
    const rpsSeries50 = rpsChart.addLineSeries({ color: '#ffcc00', lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
    const rpsSeries120 = rpsChart.addLineSeries({ color: '#4ecdc4', lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
    const rpsSeries250 = rpsChart.addLineSeries({ color: '#95a5a6', lineWidth: 2, priceLineVisible: false, lastValueVisible: false });

    if (rpsFormatted.rps20?.length > 0) rpsSeries20.setData(rpsFormatted.rps20);
    if (rpsFormatted.rps50?.length > 0) rpsSeries50.setData(rpsFormatted.rps50);
    if (rpsFormatted.rps120?.length > 0) rpsSeries120.setData(rpsFormatted.rps120);
    if (rpsFormatted.rps250?.length > 0) rpsSeries250.setData(rpsFormatted.rps250);

    // ==================== 更新标签值的函数 ====================
    const updateLabels = (time) => {
      // K线标签
      const ma10 = ma10Data.find(d => d.time === time);
      const ma20 = ma20Data.find(d => d.time === time);
      const ma120 = ma120Data.find(d => d.time === time);
      mainLabel.innerHTML = `
        <span style="color:#5b9bd5">MA10:${fmt(ma10?.value)}</span>
        <span style="color:#70ad47">MA20:${fmt(ma20?.value)}</span>
        <span style="color:#ffc107">MA120:${fmt(ma120?.value)}</span>
      `;

      // 成交量标签
      const volMa5 = volMa5Data.find(d => d.time === time);
      const volMa50 = volMa50Data.find(d => d.time === time);
      volumeLabel.innerHTML = `
        <span style="color:#c586c0">MA5:${fmtVol(volMa5?.value)}</span>
        <span style="color:#5b9bd5">MA50:${fmtVol(volMa50?.value)}</span>
      `;

      // MACD标签
      const macd = macdData.find(d => d.time === time);
      macdLabel.innerHTML = `
        <span style="color:#c586c0">DIF:${fmt(macd?.dif, 4)}</span>
        <span style="color:#ffc107">DEA:${fmt(macd?.dea, 4)}</span>
        <span style="color:${macd?.macd >= 0 ? '#ef5350' : '#26a69a'}">MACD:${fmt(macd?.macd, 4)}</span>
      `;

      // RPS标签
      const rps20 = rpsFormatted.rps20?.find(d => d.time === time);
      const rps50 = rpsFormatted.rps50?.find(d => d.time === time);
      const rps120 = rpsFormatted.rps120?.find(d => d.time === time);
      const rps250 = rpsFormatted.rps250?.find(d => d.time === time);
      rpsLabel.innerHTML = `
        <span style="color:#ff6b6b">RPS20:${rps20?.value ?? '-'}</span>
        <span style="color:#ffcc00">RPS50:${rps50?.value ?? '-'}</span>
        <span style="color:#4ecdc4">RPS120:${rps120?.value ?? '-'}</span>
        <span style="color:#95a5a6">RPS250:${rps250?.value ?? '-'}</span>
      `;
    };

    // 初始化显示最新数据的标签
    if (candles.length > 0) {
      updateLabels(candles[candles.length - 1].time);
    }

    // ==================== 隐藏 Logo ====================
    const removeLogos = () => {
      container.querySelectorAll('a').forEach(a => { if (a.href?.includes('tradingview')) a.style.display = 'none'; });
      container.querySelectorAll('svg').forEach(svg => { if (svg.parentElement?.tagName === 'A') svg.parentElement.style.display = 'none'; });
    };
    removeLogos();
    setTimeout(removeLogos, 100);
    setTimeout(removeLogos, 500);

    // ==================== 十字准星联动 ====================
    const handleCrosshairMove = (param) => {
      if (!param.point) {
        verticalLine.style.display = 'none';
        setHoverData(null);
        // 恢复显示最新数据的标签
        if (candles.length > 0) {
          updateLabels(candles[candles.length - 1].time);
        }
        return;
      }
      verticalLine.style.left = `${param.point.x}px`;
      verticalLine.style.display = 'block';

      if (!param.time) {
        setHoverData(null);
        return;
      }

      // 更新标签值
      updateLabels(param.time);

      const c = candles.find(d => d.time === param.time);
      const v = volumes.find(d => d.time === param.time);
      const m = macdData.find(d => d.time === param.time);
      const ma10 = ma10Data.find(d => d.time === param.time);
      const ma20 = ma20Data.find(d => d.time === param.time);
      const ma120 = ma120Data.find(d => d.time === param.time);
      const rps20 = rpsFormatted.rps20?.find(d => d.time === param.time);
      const rps50 = rpsFormatted.rps50?.find(d => d.time === param.time);
      const rps120 = rpsFormatted.rps120?.find(d => d.time === param.time);
      const rps250 = rpsFormatted.rps250?.find(d => d.time === param.time);

      if (c) {
        const isUp = c.close >= c.open;
        const prevIdx = candles.findIndex(d => d.time === param.time);
        const prevC = prevIdx > 0 ? candles[prevIdx - 1] : null;
        const chg = prevC ? c.close - prevC.close : 0;
        const chgPct = prevC && prevC.close !== 0 ? (chg / prevC.close * 100) : 0;

        setHoverData({
          date: formatDateForDisplay(c.time),
          open: c.open, high: c.high, low: c.low, close: c.close,
          isUp, chg, chgPct,
          volume: v?.value,
          dif: m?.dif, dea: m?.dea, macd: m?.macd,
          ma10: ma10?.value, ma20: ma20?.value, ma120: ma120?.value,
          rps20: rps20?.value, rps50: rps50?.value, rps120: rps120?.value, rps250: rps250?.value,
        });
      }
    };

    mainChart.subscribeCrosshairMove(handleCrosshairMove);
    volumeChart.subscribeCrosshairMove(handleCrosshairMove);
    macdChart.subscribeCrosshairMove(handleCrosshairMove);
    rpsChart.subscribeCrosshairMove(handleCrosshairMove);

    // ==================== 时间轴联动 ====================
    const allCharts = [mainChart, volumeChart, macdChart, rpsChart];
    const syncTimeScale = (src) => {
      const range = src.timeScale().getVisibleRange();
      allCharts.forEach(ch => { if (ch !== src && range) ch.timeScale().setVisibleRange(range); });
    };
    mainChart.timeScale().subscribeVisibleLogicalRangeChange(() => syncTimeScale(mainChart));
    volumeChart.timeScale().subscribeVisibleLogicalRangeChange(() => syncTimeScale(volumeChart));
    macdChart.timeScale().subscribeVisibleLogicalRangeChange(() => syncTimeScale(macdChart));
    rpsChart.timeScale().subscribeVisibleLogicalRangeChange(() => syncTimeScale(rpsChart));

    // ==================== 响应式 ====================
    const ro = new ResizeObserver(() => {
      if (mainWrapper.clientWidth > 0) mainChart.applyOptions({ width: mainWrapper.clientWidth });
      if (volumeWrapper.clientWidth > 0) volumeChart.applyOptions({ width: volumeWrapper.clientWidth });
      if (macdWrapper.clientWidth > 0) macdChart.applyOptions({ width: macdWrapper.clientWidth });
      if (rpsWrapper.clientWidth > 0) rpsChart.applyOptions({ width: rpsWrapper.clientWidth });
    });
    ro.observe(container);

    return () => {
      ro.disconnect();
      mainChart.remove();
      volumeChart.remove();
      macdChart.remove();
      rpsChart.remove();
    };
  }, [data, height, formatData, rpsData]);

  // 鼠标移动
  const handleMouseMove = useCallback((e) => {
    setMousePos({ x: e.clientX, y: e.clientY });
  }, []);

  // 鼠标离开
  const handleMouseLeave = useCallback(() => {
    if (verticalLineRef.current) verticalLineRef.current.style.display = 'none';
    setHoverData(null);
  }, []);

  // 计算悬浮框位置
  const getTooltipPos = () => {
    const tooltip = tooltipRef.current;
    if (!tooltip) return { x: mousePos.x + 16, y: mousePos.y + 16 };

    const margin = 8;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const w = tooltip.offsetWidth || 200;
    const h = tooltip.offsetHeight || 300;

    let x = mousePos.x + 16;
    let y = mousePos.y + 16;

    if (x + w + margin > vw) { x = mousePos.x - w - 16; }
    if (y + h + margin > vh) { y = mousePos.y - h - 16; }
    x = Math.max(margin, x); y = Math.max(margin, y);

    return { x, y };
  };

  const tooltipPos = getTooltipPos();
  const isUp = hoverData?.isUp ?? true;

  return (
    <div
      ref={containerRef}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      style={{ width: '100%', height: `${height}px`, background: AQ_STYLES.bg, borderRadius: '8px', overflow: 'hidden', position: 'relative' }}
    >
      {/* 悬浮框 */}
      {hoverData && (
        <div
          ref={tooltipRef}
          style={{
            position: 'fixed', zIndex: 1000, pointerEvents: 'none', left: tooltipPos.x, top: tooltipPos.y,
            fontFamily: 'Microsoft YaHei, sans-serif', fontSize: '12px', border: '1px solid #444',
            boxShadow: '0 2px 8px rgba(0,0,0,0.5)', backgroundColor: '#1a1a1a',
          }}
        >
          <div style={{
            background: '#dc143c', color: '#fff', padding: '4px 12px', fontWeight: 'bold', fontSize: '14px',
          }}>
            <span>{stockCode}</span>
          </div>
          <div style={{
            display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '3px 16px', padding: '6px 12px 8px 12px',
            color: '#d1d4dc', fontSize: '13px',
          }}>
            <span style={{ color: '#999' }}>日期</span>
            <span>{hoverData.date}</span>

            <span style={{ color: '#999' }}>收盘</span>
            <span style={{ color: isUp ? '#ef5350' : '#26a69a', fontWeight: 'bold' }}>{fmt(hoverData.close)}</span>

            <span style={{ color: '#999' }}>涨跌</span>
            <span style={{ color: isUp ? '#ef5350' : '#26a69a' }}>
              {hoverData.chg >= 0 ? '+' : ''}{fmt(hoverData.chgPct)}%
            </span>

            <span style={{ color: '#999' }}>成交量</span>
            <span>{fmtVol(hoverData.volume)}</span>

            {/* K线指标 */}
            <div style={{ gridColumn: '1 / -1', marginTop: '6px', borderTop: '1px solid #444', paddingTop: '6px', fontSize: '11px', display: 'flex', gap: '8px' }}>
              <span style={{ color: '#5b9bd5' }}>MA10: {fmt(hoverData.ma10)}</span>
              <span style={{ color: '#70ad47' }}>MA20: {fmt(hoverData.ma20)}</span>
              <span style={{ color: '#ffc107' }}>MA120: {fmt(hoverData.ma120)}</span>
            </div>

            {/* MACD指标 */}
            <div style={{ gridColumn: '1 / -1', fontSize: '11px', display: 'flex', gap: '8px' }}>
              <span style={{ color: '#c586c0' }}>DIF: {fmt(hoverData.dif, 4)}</span>
              <span style={{ color: '#ffc107' }}>DEA: {fmt(hoverData.dea, 4)}</span>
              <span style={{ color: hoverData.macd >= 0 ? '#ef5350' : '#26a69a' }}>MACD: {fmt(hoverData.macd, 4)}</span>
            </div>

            {/* RPS指标 */}
            <div style={{ gridColumn: '1 / -1', marginTop: '6px', borderTop: '1px solid #444', paddingTop: '6px', display: 'flex', gap: '8px', justifyContent: 'space-between' }}>
              {(() => {
                const rpsItems = [
                  { label: 'RPS20', value: hoverData.rps20, color: '#ff6b6b' },
                  { label: 'RPS50', value: hoverData.rps50, color: '#ffcc00' },
                  { label: 'RPS120', value: hoverData.rps120, color: '#4ecdc4' },
                  { label: 'RPS250', value: hoverData.rps250, color: '#95a5a6' }
                ];
                return rpsItems.map((item, idx) => {
                  let bg = '#333';
                  let color = '#d1d4dc';
                  if (item.value !== null && item.value !== undefined) {
                    if (item.value >= 90) { bg = '#dc143c'; color = '#fff'; }
                    else if (item.value >= 80) { bg = '#ff7f50'; color = '#000'; }
                  }
                  return (
                    <div key={idx} style={{ flex: 1, textAlign: 'center', padding: '4px', borderRadius: '4px', backgroundColor: bg }}>
                      <div style={{ fontSize: '10px', color: '#888' }}>{item.label}</div>
                      <div style={{ fontSize: '12px', color, fontWeight: 'bold' }}>
                        {item.value !== null && item.value !== undefined ? item.value : '-'}
                      </div>
                    </div>
                  );
                });
              })()}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
