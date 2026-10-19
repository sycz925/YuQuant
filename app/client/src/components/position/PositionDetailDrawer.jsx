import React, { useEffect, useMemo, useState } from 'react'
import {
  Drawer, Spin, Alert, Descriptions, Tag, Table, Tabs, Button, Empty, message, Tooltip, Switch, Space,
  Popconfirm,
} from 'antd'
import { ReloadOutlined, LeftOutlined, RightOutlined } from '@ant-design/icons'
import PositionKlineChart from './PositionKlineChart'
import { positionApi } from '../../api'
import {
  ACTION_META, MTR_META, fmtPrice, fmtMoney, fmtPct, fmtDate, assetLabel, pnlStyle,
  fmtHoldingSpan,
} from './utils'

/** 每日风控轨迹表 */
function TrajectoryTable({ rows, dec }) {
  const columns = [
    { title: '日期', dataIndex: 'date', key: 'date', width: 100, fixed: 'left' },
    { title: '收盘', dataIndex: 'close', key: 'close', width: 82, render: (v) => <span className="font-mono">{fmtPrice(v, dec)}</span> },
    { title: '最高', dataIndex: 'high', key: 'high', width: 82, render: (v) => <span className="font-mono text-gray-500">{fmtPrice(v, dec)}</span> },
    { title: '买入以来最高', dataIndex: 'highest_since_entry', key: 'hse', width: 110, render: (v) => <span className="font-mono">{fmtPrice(v, dec)}</span> },
    { title: 'ATR', dataIndex: 'atr', key: 'atr', width: 76, render: (v) => <span className="font-mono">{fmtPrice(v, dec)}</span> },
    { title: '止损价', dataIndex: 'current_stop_loss_price', key: 'stop', width: 88,
      render: (v, r) => (
        <span className="font-mono" style={{ color: r.stop_raised ? '#ef5350' : '#9ca3af', fontWeight: r.stop_raised ? 600 : 400 }}>
          {fmtPrice(v, dec)}
        </span>
      ) },
    { title: 'MTR', dataIndex: 'mtr', key: 'mtr', width: 76, render: (v) => <span className="font-mono">{fmtPrice(v, dec)}</span> },
    { title: 'MTR阈值', dataIndex: 'mtr_threshold', key: 'mtrt', width: 88, render: (v) => <span className="font-mono text-gray-500">{fmtPrice(v, dec)}</span> },
    { title: '过滤状态', dataIndex: 'mtr_filter_status', key: 'mtrs', width: 96,
      render: (v) => {
        const m = MTR_META[v]
        return m ? <Tag color={m.color}>{m.label}</Tag> : '-'
      } },
    { title: '动作', dataIndex: 'action', key: 'action', width: 100,
      render: (v) => {
        const m = ACTION_META[v] || { color: 'default', label: v || '-' }
        return <Tag color={m.color}>{m.label}</Tag>
      } },
    { title: '浮盈', dataIndex: 'unrealized_pnl', key: 'upnl', width: 100,
      render: (v) => <span className="font-mono" style={pnlStyle(v)}>{fmtMoney(v)}</span> },
  ]
  return (
    <Table
      dataSource={[...rows].reverse()}
      columns={columns}
      rowKey="trade_date"
      size="small"
      pagination={{ pageSize: 30, showSizeChanger: false, size: 'small' }}
      scroll={{ x: 1000 }}
    />
  )
}

/** 卖出记录表（分批卖出明细） */
function SellRecordsTable({ sells, dec, onRevoke, revokingId }) {
  const columns = [
    { title: '卖出日', dataIndex: 'sell_date', key: 'd', width: 108, render: fmtDate },
    { title: '卖出价', dataIndex: 'sell_price', key: 'p', width: 90,
      render: (v) => <span className="font-mono">{fmtPrice(v, dec)}</span> },
    { title: '股数', dataIndex: 'shares', key: 's', width: 90,
      render: (v) => <span className="font-mono">{v?.toLocaleString()}</span> },
    { title: '本笔盈亏', dataIndex: 'realized_pnl', key: 'pnl', width: 116,
      render: (v) => <span className="font-mono" style={pnlStyle(v)}>{fmtMoney(v)}</span> },
    { title: '收益率', dataIndex: 'return_ratio', key: 'r', width: 92,
      render: (v) => <span className="font-mono" style={pnlStyle(v)}>{fmtPct(v)}</span> },
    { title: '理由', dataIndex: 'reason', key: 'reason', width: 100,
      render: (v, r) => {
        const color = v === 'stop_loss' ? 'red' : v === 'take_profit' ? 'green' : 'default'
        return <Tag color={color}>{r.reason_label || v}</Tag>
      } },
    { title: '备注', dataIndex: 'note', key: 'note', render: (v) => v || <span className="text-gray-300">-</span> },
    {
      title: '操作', key: 'op', width: 90, fixed: 'right',
      render: (_, r) => (
        <Popconfirm
          title="撤回这笔卖出？"
          description="会回滚现金、恢复持仓并重算已实现盈亏"
          okText="撤回"
          okButtonProps={{ danger: true }}
          cancelText="取消"
          onConfirm={() => onRevoke?.(r)}
        >
          <Button size="small" type="link" danger loading={revokingId === r.sell_id}>
            撤回
          </Button>
        </Popconfirm>
      ),
    },
  ]
  const total = (sells || []).reduce((a, x) => a + (x.realized_pnl || 0), 0)
  const shares = (sells || []).reduce((a, x) => a + (x.shares || 0), 0)
  return (
    <div>
      <div className="mb-1 text-xs text-gray-500">
        共 <b>{sells.length}</b> 笔卖出，合计 <b>{shares.toLocaleString()}</b> 股，
        累计已实现 <b style={pnlStyle(total)}>{fmtMoney(total)}</b>
      </div>
      <Table
        dataSource={sells}
        columns={columns}
        rowKey={(r) => r.sell_id || r.sell_date}
        size="small"
        pagination={false}
        scroll={{ x: 880 }}
      />
    </div>
  )
}

/** 持仓详情抽屉：只画 K 线 + 持仓标注，下方挂每日轨迹表 */
export default function PositionDetailDrawer({ open, positionId, onClose, onChanged }) {
  const [loading, setLoading] = useState(false)
  const [traj, setTraj] = useState(null)
  const [refreshing, setRefreshing] = useState(false)
  const [showAtr, setShowAtr] = useState(false)   // ATR 通道开关
  const chartRef = React.useRef(null)             // 用于「前 / 后」平移
  const repeatRef = React.useRef({ delay: null, timer: null })

  // 平移 1 个交易日；按住不放时先等 300ms 再连续平移
  const stopShift = React.useCallback(() => {
    if (repeatRef.current.delay) { clearTimeout(repeatRef.current.delay); repeatRef.current.delay = null }
    if (repeatRef.current.timer) { clearInterval(repeatRef.current.timer); repeatRef.current.timer = null }
  }, [])

  const startShift = React.useCallback((dir) => {
    stopShift()
    chartRef.current?.shift(dir, 1)          // 点击立刻走一格
    repeatRef.current.delay = setTimeout(() => {
      repeatRef.current.timer = setInterval(() => {
        chartRef.current?.shift(dir, 1)      // 长按后每 60ms 一格
      }, 60)
    }, 300)
  }, [stopShift])

  // 组件卸载/弹窗关闭时清理定时器
  React.useEffect(() => stopShift, [stopShift])
  React.useEffect(() => { if (!open) stopShift() }, [open, stopShift])
  const [lastRecalcAt, setLastRecalcAt] = useState(null)
  const [activeTab, setActiveTab] = useState('chart')
  const [revokingId, setRevokingId] = useState(null)

  // 撤回一笔卖出
  const handleRevokeSell = async (rec) => {
    if (!positionId || !rec?.sell_id) return
    setRevokingId(rec.sell_id)
    try {
      const res = await positionApi.revokeSell(positionId, rec.sell_id)
      message.success(`已撤回 ${rec.sell_date} 的 ${rec.shares} 股卖出`)
      if (res?.warnings?.length) res.warnings.forEach((w) => message.warning(w, 6))
      onChanged?.(res)
      const t = await positionApi.getTrajectory(positionId)
      setTraj(t)
    } catch (e) {
      message.error(e?.response?.data?.detail?.message || e?.response?.data?.detail || '撤回失败')
    } finally {
      setRevokingId(null)
    }
  }

  const load = React.useCallback(async (pid) => {
    const res = await positionApi.getTrajectory(pid)
    setTraj(res)
    return res
  }, [])

  useEffect(() => {
    if (!open || !positionId) return
    let cancelled = false
    setLoading(true)
    setTraj(null)
    load(positionId)
      .catch((e) => {
        if (!cancelled) {
          message.error(e?.response?.data?.detail?.message || e?.response?.data?.detail || '加载持仓详情失败')
        }
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [open, positionId, load])

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      const res = await positionApi.refreshOne(positionId)
      const synced = res?.data_report?.synced || []
      const daily = res?.chart?.daily || []
      const ups = daily.filter((d) => d.stop_raised).length
      const filtered = daily.filter((d) => d.stop_move_filtered).length
      const stop = res?.current_stop_loss_price
      const detail = `${daily.length} 天 · 止损上移 ${ups} 次`
        + (filtered ? ` · MTR 过滤 ${filtered} 次` : '')
        + (stop != null ? ` · 当前止损 ${stop}` : '')
        + (synced.length ? ` · 已补齐 ${synced.join('、')} 日线` : '')
      message.success({ content: `重算完成：${detail}`, duration: 6 })
      setLastRecalcAt(new Date())
      onChanged?.(res)
      const t = await positionApi.getTrajectory(positionId)
      setTraj(t)
    } catch (e) {
      message.error(e?.response?.data?.detail?.message || '刷新失败')
    } finally {
      setRefreshing(false)
    }
  }


  const pos = traj?.position
  const chart = traj?.chart
  const dec = pos?.price_dec ?? 2

  const priceLines = useMemo(() => {
    const base = chart?.price_lines || []
    if (!pos) return base
    return [
      {
        price: pos.buy_price_adj,
        color: '#9ca3af', lineStyle: 2, lineWidth: 1,
        title: `成本 ${fmtPrice(pos.buy_price_adj, dec)}`, axisLabelVisible: true,
      },
      ...base,
    ]
  }, [chart, pos, dec])

  const dailyStates = chart?.daily || []
  const title = pos ? `${pos.stock_name} ${pos.stock_code}` : '持仓详情'

  return (
    <Drawer
      title={
        <div className="flex items-center space-x-2">
          <span>{title}</span>
          {pos && <Tag color="blue">{assetLabel(pos.asset_type)}</Tag>}
          {pos && <Tag color={pos.status === 'OPEN' ? 'green' : 'default'}>{pos.status === 'OPEN' ? '活跃' : '已平仓'}</Tag>}
        </div>
      }
      open={open}
      onClose={onClose}
      width={Math.min(1500, typeof window !== 'undefined' ? window.innerWidth - 40 : 1280)}
      destroyOnClose
      styles={{ body: { paddingTop: 12 } }}
      extra={
        <Space size={8}>
          {lastRecalcAt && (
            <span className="text-[11px] text-gray-400">
              重算于 {lastRecalcAt.toLocaleTimeString('zh-CN', { hour12: false })}
            </span>
          )}
          <Button size="small" icon={<ReloadOutlined />} loading={refreshing} onClick={handleRefresh}>
            重算轨迹
          </Button>
        </Space>
      }
    >
      {loading && (
        <div className="py-16 text-center"><Spin tip="正在回算止损轨迹..." /></div>
      )}

      {!loading && !pos && <Empty description="暂无数据" />}

      {!loading && pos && (
        <>
          {pos.error && <Alert className="mb-2" type="error" showIcon message={`回算异常：${pos.error}`} />}

          {pos.action && pos.action !== '持仓' && pos.action !== '已平仓' && (
            <Alert
              className="mb-2"
              showIcon
              type={pos.action === '利润保护参考' ? 'warning' : 'error'}
              message={pos.action_suggestion}
            />
          )}

          <Descriptions size="small" column={{ xs: 2, md: 4 }} bordered className="mb-2"
            styles={{ label: { fontSize: 12, width: 78 }, content: { fontSize: 12 } }}>
            <Descriptions.Item label="买入日">{fmtDate(pos.buy_date)}</Descriptions.Item>
            <Descriptions.Item label="买入价">
              <span className="font-mono">{fmtPrice(pos.buy_price, dec)}</span>
              {pos.adjust_ratio && Math.abs(pos.adjust_ratio - 1) > 1e-6 && (
                <Tooltip title="持有期内发生除权，已按复权锚点折算">
                  <span className="text-xs text-gray-400 ml-1">(复权 {fmtPrice(pos.buy_price_adj, dec)})</span>
                </Tooltip>
              )}
            </Descriptions.Item>
            <Descriptions.Item label="持仓股数">
              <span className="font-mono font-bold">{pos.remaining_shares?.toLocaleString()}</span>
              {(pos.sold_shares ?? 0) > 0 && (
                <span className="text-gray-400 ml-1 text-xs">
                  / 建仓 {pos.buy_shares?.toLocaleString()}（已卖 {pos.sold_shares?.toLocaleString()}）
                </span>
              )}
            </Descriptions.Item>
            <Descriptions.Item label="现价">
              <span className="font-mono" style={pnlStyle((pos.current_price ?? 0) - pos.buy_price_adj)}>
                {fmtPrice(pos.current_price, dec)}
              </span>
            </Descriptions.Item>

            <Descriptions.Item label="浮盈">
              <span className="font-mono" style={pnlStyle(pos.unrealized_pnl)}>
                {fmtMoney(pos.unrealized_pnl)}（{fmtPct(pos.unrealized_return_ratio)}）
              </span>
            </Descriptions.Item>
            <Descriptions.Item label="累计已实现">
              {(pos.sold_shares ?? 0) > 0 ? (
                <span className="font-mono" style={pnlStyle(pos.realized_pnl)}>
                  {fmtMoney(pos.realized_pnl)}（{fmtPct(pos.realized_pnl_ratio)}）
                </span>
              ) : <span className="text-gray-400">-</span>}
            </Descriptions.Item>
            <Descriptions.Item label="ATR">
              <span className="font-mono">{fmtPrice(pos.atr_current, dec)}</span>
            </Descriptions.Item>
            <Descriptions.Item label="买入以来最高">
              <span className="font-mono">{fmtPrice(pos.highest_since_entry, dec)}</span>
            </Descriptions.Item>
            <Descriptions.Item label="持股时间">
              {pos.holding_calendar_days != null
                ? fmtHoldingSpan(pos.holding_calendar_days)
                : (pos.holding_days != null ? `${pos.holding_days} 天` : '-')}
            </Descriptions.Item>

            <Descriptions.Item label="初始止损">
              <span className="font-mono text-green-600">{fmtPrice(pos.initial_stop_loss_price_adj, dec)}</span>
            </Descriptions.Item>
            <Descriptions.Item label="当前止损">
              <span className="font-mono text-red-500 font-bold">{fmtPrice(pos.current_stop_loss_price, dec)}</span>
            </Descriptions.Item>
            <Descriptions.Item label="止盈参考">
              <span className="font-mono text-green-600">{fmtPrice(pos.take_profit_reference_price_adj, dec)}</span>
            </Descriptions.Item>
            {pos.current_rr != null && (
              <Descriptions.Item label="当前盈亏比">{pos.current_rr}</Descriptions.Item>
            )}
            <Descriptions.Item label="浮盈 (R)">
              <span className="font-mono">{pos.gain_r != null ? `${pos.gain_r}R` : '-'}</span>
            </Descriptions.Item>
            {pos.dynamic_tp_price != null && (
              <Descriptions.Item label="动态止盈线">
                <Tooltip title="浮盈达设定档位后接管：收盘跌破该线即提示分批止盈/离场">
                  <span className="font-mono font-bold" style={{ color: '#a855f7' }}>
                    {fmtPrice(pos.dynamic_tp_price, dec)}
                  </span>
                </Tooltip>
              </Descriptions.Item>
            )}

            <Descriptions.Item label="持仓风险">
              <span className="font-mono">{fmtMoney(pos.position_risk_amount)}</span>
            </Descriptions.Item>
            <Descriptions.Item label="MTR">
              <span className="font-mono">{fmtPrice(pos.mtr_current, dec)}</span>
              {MTR_META[pos.mtr_filter_status] && (
                <Tag className="ml-1" color={MTR_META[pos.mtr_filter_status].color}>
                  {MTR_META[pos.mtr_filter_status].label}
                </Tag>
              )}
            </Descriptions.Item>
            <Descriptions.Item label="动作建议">
              {ACTION_META[pos.action] ? <Tag color={ACTION_META[pos.action].color}>{pos.action}</Tag> : (pos.action || '-')}
            </Descriptions.Item>
            <Descriptions.Item label="止损触发">
              {pos.stop_trigger_date ? (
                <span>
                  <Tag color="orange">{pos.stop_trigger_action || '止损'}</Tag>
                  {fmtDate(pos.stop_trigger_date)}
                  {pos.stop_trigger_count > 1 && (
                    <span className="text-gray-400 ml-1">共 {pos.stop_trigger_count} 天</span>
                  )}
                </span>
              ) : <span className="text-gray-400">未触发</span>}
            </Descriptions.Item>
            <Descriptions.Item label="止盈参考触发">
              {pos.take_profit_hit_date ? (
                <span>
                  {fmtDate(pos.take_profit_hit_date)}
                  {pos.take_profit_hit_count > 1 && (
                    <span className="text-gray-400 ml-1">共 {pos.take_profit_hit_count} 天</span>
                  )}
                </span>
              ) : <span className="text-gray-400">未触发</span>}
            </Descriptions.Item>

            {pos.status === 'CLOSED' && (
              <>
                <Descriptions.Item label="最后卖出日">{fmtDate(pos.last_sell_date || pos.sell_date)}</Descriptions.Item>
                <Descriptions.Item label="卖出均价">
                  <span className="font-mono">{fmtPrice(pos.avg_sell_price ?? pos.sell_price, dec)}</span>
                  {(pos.sell_count ?? 1) > 1 && <span className="text-gray-400 ml-1 text-xs">分 {pos.sell_count} 笔</span>}
                </Descriptions.Item>
                <Descriptions.Item label="已实现盈亏">
                  <span className="font-mono" style={pnlStyle(pos.realized_pnl)}>{fmtMoney(pos.realized_pnl)}</span>
                </Descriptions.Item>
                <Descriptions.Item label="收益率">
                  <span className="font-mono" style={pnlStyle(pos.realized_pnl)}>{fmtPct(pos.realized_pnl_ratio ?? pos.return_ratio)}</span>
                </Descriptions.Item>
              </>
            )}
          </Descriptions>

          {/* 标注图例 */}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-gray-500 mb-1.5">
            <span><span style={{ color: '#ef5350' }}>▲</span> 买入点</span>
            <span><span style={{ color: '#26a69a' }}>▼</span> 实际卖出点</span>
            <span><span style={{ color: '#f59e0b' }}>●</span> 止损触发点（硬性风控）</span>
            <span><span style={{ color: '#22c55e' }}>●</span> 止盈参考触发点</span>
            <span className="hidden md:inline"><span style={{ color: '#38bdf8' }}>╌╌</span> ATR 通道（收盘价 ± {traj?.params?.k_initial ?? 2.0}×ATR）</span>
            <span><span style={{ color: '#f59e0b' }}>▁▂▃</span> 止损阶梯线（逐日上移）</span>
            {(chart?.dynamic_tp_series || []).length > 0 && (
              <span><span style={{ color: '#a855f7' }}>▁▂▃</span> 动态止盈线（浮盈达标后接管离场）</span>
            )}
            <span><span style={{ color: '#9ca3af' }}>╌╌</span> 成本价</span>
            <span><span style={{ color: '#9ca3af' }}>┈┈</span> 初始止损</span>
            <span><span style={{ color: '#ef5350' }}>╌╌</span> 当前止损</span>
            <span><span style={{ color: '#22c55e' }}>╌╌</span> 止盈参考</span>
            <span className="text-gray-400 hidden md:inline">
              左右按钮逐日平移（可长按连发）· 已禁止缩放 · 最新交易日固定在最右侧
            </span>
            <span className="flex items-center gap-1.5 ml-auto pl-2 pr-1 py-0.5 rounded"
              style={{ background: showAtr ? 'rgba(56,189,248,0.12)' : 'transparent' }}>
              <Switch size="small" checked={showAtr} onChange={setShowAtr} />
              <span style={{ color: showAtr ? '#0284c7' : '#9ca3af', fontWeight: showAtr ? 600 : 400 }}>
                ATR 通道
              </span>
            </span>
          </div>

          <Tabs
            activeKey={activeTab}
            onChange={setActiveTab}
            size="small"
            items={[
              {
                key: 'chart',
                label: 'K线标注',
                children: (traj?.bars || []).length ? (
                  <div className="relative">
                    <Button
                      size="small"
                      shape="circle"
                      icon={<LeftOutlined />}
                      title="往前平移 1 个交易日（长按连续）"
                      onMouseDown={() => startShift(-1)}
                      onMouseUp={stopShift}
                      onMouseLeave={stopShift}
                      onTouchStart={(e) => { e.preventDefault(); startShift(-1) }}
                      onTouchEnd={stopShift}
                      onTouchCancel={stopShift}
                      className="!absolute !left-2 !top-1/2 !-translate-y-1/2 !z-20 opacity-60 hover:opacity-100 select-none"
                    />
                    <Button
                      size="small"
                      shape="circle"
                      icon={<RightOutlined />}
                      title="往后平移 1 个交易日（长按连续）"
                      onMouseDown={() => startShift(1)}
                      onMouseUp={stopShift}
                      onMouseLeave={stopShift}
                      onTouchStart={(e) => { e.preventDefault(); startShift(1) }}
                      onTouchEnd={stopShift}
                      onTouchCancel={stopShift}
                      className="!absolute !right-16 !top-1/2 !-translate-y-1/2 !z-20 opacity-60 hover:opacity-100 select-none"
                    />
                    <PositionKlineChart
                      ref={chartRef}
                      bars={traj.bars}
                      daily={dailyStates}
                      markers={chart?.markers || []}
                      priceLines={priceLines}
                      atrSeries={traj?.atr_series || []}
                      dynamicTpSeries={chart?.dynamic_tp_series || []}
                      atrBandK={traj?.params?.k_initial ?? 2.0}
                      buyDate={pos.buy_date}
                      priceDec={dec}
                      atrPeriod={traj?.params?.atr_period ?? 14}
                      showAtr={showAtr}
                      height={typeof window !== 'undefined' && window.innerWidth < 768 ? 440 : 620}
                    />
                  </div>
                ) : <Empty description="暂无日线数据" />,
              },
              {
                key: 'daily',
                label: `每日轨迹（${dailyStates.length} 天）`,
                children: <TrajectoryTable rows={dailyStates} dec={dec} />,
              },
              ...((pos.sells && pos.sells.length) ? [{
                key: 'sells',
                label: `卖出记录（${pos.sells.length} 笔）`,
                children: (
                  <SellRecordsTable
                    sells={pos.sells}
                    dec={dec}
                    onRevoke={handleRevokeSell}
                    revokingId={revokingId}
                  />
                ),
              }] : []),
            ]}
          />
        </>
      )}
    </Drawer>
  )
}
