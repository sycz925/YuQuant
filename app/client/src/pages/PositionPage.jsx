import React, { useEffect, useMemo, useState, useCallback } from 'react'
import {
  Select, Button, Tag, Table, Space, Tabs, Empty, Tooltip, Popconfirm, message, Badge, Alert, Switch,
} from 'antd'
import {
  PlusOutlined, WalletOutlined, SettingOutlined, SyncOutlined, ReloadOutlined, DeleteOutlined,
  ProfileOutlined, UserAddOutlined, QuestionCircleOutlined, StopOutlined, EditOutlined,
} from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { positionApi } from '../api'
import {
  ACTION_META, MTR_META, fmtPrice, fmtMoney, fmtPct, fmtDate, pnlStyle, assetLabel, ALERT_ACTIONS,
  fmtHoldingSpan,
} from '../components/position/utils'
import AccountDialog from '../components/position/AccountDialog'
import PositionEntryDialog from '../components/position/PositionEntryDialog'
import SellPositionDialog from '../components/position/SellPositionDialog'
import PositionDetailDrawer from '../components/position/PositionDetailDrawer'
import RiskParamsDialog from '../components/position/RiskParamsDialog'

const STORAGE_KEY = 'positionAccountId'

/** 列头 + 问号说明 */
function ColTitle({ text, desc }) {
  return (
    <span className="inline-flex items-center gap-1">
      {text}
      <Tooltip title={desc} overlayStyle={{ maxWidth: 380 }}>
        <QuestionCircleOutlined className="text-gray-400" style={{ fontSize: 11 }} />
      </Tooltip>
    </span>
  )
}

/** 账户看板统计卡 */
function Stat({ label, value, sub, color, tone }) {
  return (
    <div className={`rounded-lg border p-2.5 ${tone || 'border-gray-200 bg-white'}`}>
      <div className="text-[11px] text-gray-500 truncate">{label}</div>
      <div className="text-base font-bold font-mono truncate" style={{ color: color || '#111827' }}>{value}</div>
      {sub && <div className="text-[11px] text-gray-400 truncate">{sub}</div>}
    </div>
  )
}

function PositionPage() {
  const queryClient = useQueryClient()
  const [accountId, setAccountId] = useState(null)
  const [entryOpen, setEntryOpen] = useState(false)
  const [accountDlg, setAccountDlg] = useState({ open: false, mode: 'create' })
  const [paramsOpen, setParamsOpen] = useState(false)
  const [sellTarget, setSellTarget] = useState(null)
  const [detailId, setDetailId] = useState(null)
  const [refreshing, setRefreshing] = useState(false)

  // ---- 账户 ----
  const { data: accounts = [], isFetching: accountsLoading } = useQuery({
    queryKey: ['position-accounts'],
    queryFn: () => positionApi.getAccounts(),
  })

  useEffect(() => {
    if (accountId && accounts.some((a) => a.account_id === accountId)) return
    if (!accounts.length) { setAccountId(null); return }
    // 进入页面优先展示「主账户」；没设主账户时退回上次选中的，再退回第一个
    const primary = accounts.find((a) => a.is_primary)
    if (primary) { setAccountId(primary.account_id); return }
    const saved = typeof window !== 'undefined' ? window.localStorage.getItem(STORAGE_KEY) : null
    const hit = accounts.find((a) => a.account_id === saved)
    setAccountId(hit ? saved : accounts[0].account_id)
  }, [accounts, accountId])

  useEffect(() => {
    if (accountId) window.localStorage.setItem(STORAGE_KEY, accountId)
  }, [accountId])

  // ---- 持仓 ----
  const { data: positions = [], isFetching } = useQuery({
    queryKey: ['positions', accountId],
    queryFn: () => positionApi.getList({ account_id: accountId }),
    enabled: !!accountId,
  })

  // 进入页面/切换账户时把最新快照写回库里（供顶部红点使用）
  useEffect(() => {
    if (!accountId) return
    let cancelled = false
    positionApi.refreshAll(accountId)
      .then(() => {
        if (cancelled) return
        queryClient.invalidateQueries({ queryKey: ['position-accounts'] })
        queryClient.invalidateQueries({ queryKey: ['position-alerts'] })
      })
      .catch(() => { /* 静默 */ })
    return () => { cancelled = true }
  }, [accountId, queryClient])

  const account = useMemo(
    () => accounts.find((a) => a.account_id === accountId) || null,
    [accounts, accountId],
  )

  const active = useMemo(() => positions.filter((p) => p.status === 'OPEN'), [positions])
  const closed = useMemo(() => positions.filter((p) => p.status === 'CLOSED'), [positions])
  const alerts = useMemo(
    () => active.filter((p) => ALERT_ACTIONS.has(p.action)),
    [active],
  )
  // 只要有任意一笔活跃持仓发生过部分卖出，才显示「已实现」列
  const hasRealized = useMemo(
    () => active.some((p) => (p.sold_shares ?? 0) > 0),
    [active],
  )

  // 删除账户后：关闭弹窗、清空当前选择、刷新所有相关查询
  const handleAccountDeleted = useCallback(() => {
    setAccountDlg({ open: false, mode: 'create' })
    setAccountId(null)
    try { window.localStorage.removeItem(STORAGE_KEY) } catch (e) { /* ignore */ }
    queryClient.invalidateQueries({ queryKey: ['position-accounts'] })
    queryClient.invalidateQueries({ queryKey: ['positions'] })
    queryClient.invalidateQueries({ queryKey: ['position-alerts'] })
  }, [queryClient])

  const reload = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['positions', accountId] })
    queryClient.invalidateQueries({ queryKey: ['position-accounts'] })
    queryClient.invalidateQueries({ queryKey: ['position-alerts'] })
  }, [queryClient, accountId])

  const handleRefresh = async () => {
    if (!accountId || refreshing) return
    setRefreshing(true)
    try {
      const res = await positionApi.refreshAll(accountId)
      const synced = res?.data?.synced || []
      const failed = res?.data?.failed || []
      let msg = `已重算 ${res.updated}/${res.total} 笔持仓`
      if (synced.length) msg += `，补齐日线 ${synced.length} 只（${synced.join('、')}）`
      if (failed.length) msg += `，${failed.length} 只补齐失败（${failed.join('、')}）`
      if (synced.length || failed.length) {
        message.info(msg, 5)
      } else {
        message.success(msg)
      }
      reload()
    } catch (e) {
      message.error(e?.response?.data?.detail?.message || '刷新失败')
    } finally {
      setRefreshing(false)
    }
  }

  const handleDelete = async (id) => {
    try {
      await positionApi.remove(id)
      message.success('已删除记录')
      reload()
    } catch (e) {
      message.error(e?.response?.data?.detail?.message || '删除失败')
    }
  }

  // ---- 列定义 ----
  // 「已实现」列只在存在部分卖出时才显示（否则整列都是 "-"，没有意义）
  const realizedColumn = {
    title: '已实现', dataIndex: 'realized_pnl', key: 'realized', width: 112,
    sorter: (a, b) => (a.realized_pnl || 0) - (b.realized_pnl || 0),
    render: (v) => <div className="leading-4 font-mono" style={pnlStyle(v)}>{fmtMoney(v)}</div>,
  }

  const activeColumns = [
    {
      title: '代码', dataIndex: 'stock_code', key: 'stock_code', width: 84, fixed: 'left',
      render: (v) => <span className="font-mono text-gray-500">{v}</span>,
    },
    {
      title: '名称', dataIndex: 'stock_name', key: 'stock_name', width: 130, fixed: 'left',
      render: (v, r) => (
        <span className="font-medium text-blue-600 hover:text-blue-800 cursor-pointer"
          onClick={() => setDetailId(r.position_id)}>
          {v}
          {r.asset_type === 'etf' && <Tag className="ml-1" color="blue" style={{ fontSize: 10 }}>ETF</Tag>}
        </span>
      ),
    },
    { title: '买入日', dataIndex: 'buy_date', key: 'buy_date', width: 96, render: (v) => fmtDate(v) },
    {
      title: (
        <ColTitle
          text="持股时间"
          desc="从买入日到最新交易日的持仓时长，按自然日折算为天 / 周 / 月 / 年"
        />
      ),
      dataIndex: 'holding_calendar_days', key: 'holding', width: 88,
      sorter: (a, b) => (a.holding_calendar_days || 0) - (b.holding_calendar_days || 0),
      render: (v) => (v == null ? <span className="text-gray-300">-</span> : fmtHoldingSpan(v)),
    },
    {
      title: '买入价', dataIndex: 'buy_price', key: 'buy_price', width: 88,
      render: (v, r) => (
        <Tooltip title={Math.abs((r.adjust_ratio ?? 1) - 1) > 1e-6 ? `复权成本 ${fmtPrice(r.buy_price_adj, r.price_dec)}` : null}>
          <span className="font-mono">{fmtPrice(v, r.price_dec)}</span>
        </Tooltip>
      ),
    },
    {
      title: '持仓', dataIndex: 'remaining_shares', key: 'shares', width: 96,
      sorter: (a, b) => (a.remaining_shares || 0) - (b.remaining_shares || 0),
      render: (v, r) => (
        <div className="leading-4">
          <div className="font-mono">{v?.toLocaleString()}</div>
          {(r.sold_shares ?? 0) > 0 && (
            <div className="text-[10px] text-gray-400">已卖 {r.sold_shares?.toLocaleString()}</div>
          )}
        </div>
      ),
    },
    {
      title: '现价', dataIndex: 'current_price', key: 'current_price', width: 88,
      render: (v, r) => <span className="font-mono" style={pnlStyle((v ?? 0) - r.buy_price_adj)}>{fmtPrice(v, r.price_dec)}</span>,
    },
    {
      title: '浮盈', dataIndex: 'unrealized_pnl', key: 'unrealized_pnl', width: 128,
      render: (v, r) => (
        <div className="leading-4">
          <div className="font-mono text-[13px]" style={pnlStyle(v)}>{fmtMoney(v)}</div>
          <div className="font-mono text-[11px]" style={pnlStyle(r.unrealized_return_ratio)}>{fmtPct(r.unrealized_return_ratio)}</div>
        </div>
      ),
    },
    ...(hasRealized ? [realizedColumn] : []),
    {
      title: (
        <ColTitle
          text="ATR"
          desc="ATR（平均真实波幅，14 日）：每日真实波幅 max(高−低, |高−前收|, |低−前收|) 的 14 日均值，用来衡量该股当前的波动幅度。"
        />
      ),
      dataIndex: 'atr_current', key: 'atr_current', width: 96,
      render: (v, r) => <span className="font-mono">{fmtPrice(v, r.price_dec)}</span>,
    },
    {
      title: '初始止损', dataIndex: 'initial_stop_loss_price_adj', key: 'init_stop', width: 92,
      render: (v, r) => <span className="font-mono text-green-600">{fmtPrice(v, r.price_dec)}</span>,
    },
    {
      title: '当前止损', dataIndex: 'current_stop_loss_price', key: 'cur_stop', width: 96,
      sorter: (a, b) => (a.current_stop_loss_price || 0) - (b.current_stop_loss_price || 0),
      render: (v, r) => (
        <div className="leading-4">
          <div className="font-mono text-red-500 font-bold">{fmtPrice(v, r.price_dec)}</div>
          {r.current_price != null && v != null && (
            <div className="text-[10px] text-gray-400">
              距现价 {(((v / r.current_price) - 1) * 100).toFixed(1)}%
            </div>
          )}
        </div>
      ),
    },
    {
      title: '止盈参考', dataIndex: 'take_profit_reference_price_adj', key: 'tp', width: 92,
      render: (v, r) => <span className="font-mono text-green-600">{fmtPrice(v, r.price_dec)}</span>,
    },
    {
      title: '风险额', dataIndex: 'position_risk_amount', key: 'risk', width: 100,
      sorter: (a, b) => (a.position_risk_amount || 0) - (b.position_risk_amount || 0),
      render: (v) => <span className="font-mono" style={{ color: v > 0 ? '#ef5350' : '#9ca3af' }}>{fmtMoney(v)}</span>,
    },
    {
      title: '盈亏比', dataIndex: 'current_rr', key: 'rr', width: 80,
      render: (v) => <span className="font-mono" style={pnlStyle(v)}>{v ?? '-'}</span>,
    },
    {
      title: (
        <ColTitle
          text="MTR"
          desc="MTR（修正真实波幅，20 日）：只看跳空幅度 max(|高−前收|, |低−前收|)。今日 MTR > 20日均值 + 2×标准差 才算「有效放大」，此时才允许移动止损上移；否则当天止损不动（硬性止损触发不受影响）。"
        />
      ),
      dataIndex: 'mtr_filter_status', key: 'mtr', width: 106,
      render: (v, r) => {
        const m = MTR_META[v]
        return (
          <Tooltip title={r.mtr_current != null ? `MTR ${fmtPrice(r.mtr_current, r.price_dec)} / 均值 ${fmtPrice(r.mtr_mean, r.price_dec)} / 标准差 ${fmtPrice(r.mtr_std, r.price_dec)}` : null}>
            {m ? <Tag color={m.color}>{m.label}</Tag> : <span className="text-gray-400">-</span>}
          </Tooltip>
        )
      },
    },
    {
      title: '动作建议', dataIndex: 'action', key: 'action', width: 132,
      filters: Object.keys(ACTION_META).filter((k) => k !== '已平仓').map((k) => ({ text: k, value: k })),
      onFilter: (val, r) => r.action === val,
      render: (v, r) => {
        const m = ACTION_META[v] || { color: 'default', label: v || '-' }
        return (
          <Tooltip title={r.action_suggestion}>
            <Tag color={m.color}>{m.label}</Tag>
          </Tooltip>
        )
      },
    },
    {
      title: '操作', key: 'op', width: 120, fixed: 'right',
      render: (_, r) => (
        <Space size={0}>
          <Button type="link" size="small" onClick={() => setDetailId(r.position_id)}>详情</Button>
          <Button type="link" size="small" danger onClick={() => setSellTarget(r)}>卖出</Button>
        </Space>
      ),
    },
  ]

  const closedColumns = [
    { title: '代码', dataIndex: 'stock_code', key: 'code', width: 84, render: (v) => <span className="font-mono text-gray-500">{v}</span> },
    {
      title: '名称', dataIndex: 'stock_name', key: 'name', width: 130,
      render: (v, r) => (
        <span className="font-medium text-blue-600 hover:text-blue-800 cursor-pointer" onClick={() => setDetailId(r.position_id)}>{v}</span>
      ),
    },
    { title: '买入日', dataIndex: 'buy_date', key: 'bd', width: 96, render: fmtDate },
    { title: '卖出日', dataIndex: 'sell_date', key: 'sd', width: 96, render: fmtDate },
    { title: '买入价', dataIndex: 'buy_price', key: 'bp', width: 88, render: (v, r) => <span className="font-mono">{fmtPrice(v, r.price_dec)}</span> },
    {
      title: '卖出价', dataIndex: 'sell_price', key: 'sp', width: 100,
      render: (v, r) => {
        const avg = r.avg_sell_price ?? v
        return (
          <div className="leading-4">
            <div className="font-mono">{fmtPrice(avg, r.price_dec)}</div>
            {(r.sell_count ?? 1) > 1 && (
              <div className="text-[10px] text-gray-400">均价 · 分 {r.sell_count} 笔</div>
            )}
          </div>
        )
      },
    },
    { title: '建仓股数', dataIndex: 'buy_shares', key: 'sh', width: 86, render: (v) => v?.toLocaleString() },
    {
      title: '已实现盈亏', dataIndex: 'realized_pnl', key: 'pnl', width: 120,
      sorter: (a, b) => (a.realized_pnl || 0) - (b.realized_pnl || 0),
      render: (v) => <span className="font-mono font-bold" style={pnlStyle(v)}>{fmtMoney(v)}</span>,
    },
    {
      title: '收益率', dataIndex: 'return_ratio', key: 'rr', width: 92,
      render: (v) => <span className="font-mono" style={pnlStyle(v)}>{fmtPct(v)}</span>,
    },
    {
      title: (
        <ColTitle
          text="清仓后收益"
          desc="清仓之后该股至今的涨跌幅 —— 正数=卖出后还在涨（卖飞了），负数=卖出后下跌（卖对了）。下方金额 =（最新价 − 卖出均价）× 卖出股数"
        />
      ),
      dataIndex: 'post_exit_change_pct', key: 'post_exit', width: 118,
      sorter: (a, b) => (a.post_exit_change_pct || 0) - (b.post_exit_change_pct || 0),
      render: (v, r) => (v == null
        ? <span className="text-gray-300">-</span>
        : (
          <div className="leading-4">
            <div className="font-mono text-[13px]" style={pnlStyle(v)}>
              {v >= 0 ? '+' : ''}{v.toFixed(2)}%
            </div>
            {r.post_exit_pnl != null && (
              <div className="font-mono text-[10px]" style={pnlStyle(r.post_exit_pnl)}>
                {r.post_exit_pnl >= 0 ? '+' : ''}{fmtMoney(r.post_exit_pnl)}
              </div>
            )}
          </div>
        )),
    },
    {
      title: <ColTitle text="清仓时长" desc="从买入到最终清仓的持仓时长，按自然日折算为天 / 周 / 月 / 年" />,
      dataIndex: 'holding_calendar_days', key: 'hd', width: 88,
      sorter: (a, b) => (a.holding_calendar_days || 0) - (b.holding_calendar_days || 0),
      render: (v) => (v == null ? <span className="text-gray-300">-</span> : fmtHoldingSpan(v)),
    },
    {
      title: '操作', key: 'op', width: 120, fixed: 'right',
      render: (_, r) => (
        <Space size={0}>
          <Button type="link" size="small" onClick={() => setDetailId(r.position_id)}>详情</Button>
          <Popconfirm title="删除该历史记录？" okText="删除" cancelText="取消" onConfirm={() => handleDelete(r.position_id)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  // ---- 无账户 ----
  if (!accountsLoading && accounts.length === 0) {
    return (
      <div className="py-20 text-center">
        <Empty
          image={<WalletOutlined style={{ fontSize: 56, color: '#cbd5e1' }} />}
          description={
            <div className="text-gray-500">
              <div className="text-base mb-1">还没有账户</div>
              <div className="text-xs">持仓风控以账户为管理单元，先创建一个账户（资金池）</div>
            </div>
          }
        >
          <Button type="primary" icon={<UserAddOutlined />} onClick={() => setAccountDlg({ open: true, mode: 'create' })}>
            新建账户
          </Button>
        </Empty>
        <AccountDialog
          open={accountDlg.open}
          mode={accountDlg.mode}
          account={account}
          onCancel={() => setAccountDlg({ open: false, mode: 'create' })}
          onOk={() => { setAccountDlg({ open: false, mode: 'create' }); queryClient.invalidateQueries({ queryKey: ['position-accounts'] }) }}
        />
      </div>
    )
  }

  return (
    <div>
      {/* 头部 */}
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div className="flex items-center space-x-2">
          <h2 className="text-lg font-bold flex items-center">
            <WalletOutlined className="text-blue-600 mr-1.5" />持仓
          </h2>
          <Select
            style={{ width: 240 }}
            value={accountId}
            onChange={setAccountId}
            options={accounts.map((a) => ({
              value: a.account_id,
              label: `${a.is_primary ? '★ ' : ''}${a.is_disable ? '⏸ ' : ''}${a.account_name} · 权益 ${fmtMoney(a.current_equity)}`,
            }))}
            loading={accountsLoading}
          />
          <Tag color="blue">{active.length} 活跃</Tag>
          <Tag>{closed.length} 已平仓</Tag>
          {alerts.length > 0 && (
            <Badge count={alerts.length} size="small" offset={[4, 0]}>
              <Tag color="red" icon={<ProfileOutlined />}>风险提醒</Tag>
            </Badge>
          )}
        </div>
        <Space wrap>
          <Button icon={<ReloadOutlined />} loading={refreshing} onClick={handleRefresh}>刷新监控</Button>
          <Button icon={<SettingOutlined />} onClick={() => setParamsOpen(true)}>风控参数</Button>
          <Tooltip title="改名 / 调整单笔风险比例 / 出入金 / 启用或禁用该账户">
            <Button
              icon={<EditOutlined />}
              disabled={!account}
              onClick={() => setAccountDlg({ open: true, mode: 'edit' })}
            >
              编辑账户
            </Button>
          </Tooltip>
          <Button icon={<UserAddOutlined />} onClick={() => setAccountDlg({ open: true, mode: 'create' })}>新建账户</Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            disabled={!accountId}
            onClick={() => setEntryOpen(true)}
          >
            建仓
          </Button>
        </Space>
      </div>

      {/* 账户看板 */}
      {account && (
        <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-2 mb-3">
          <Stat label="当前总权益" value={fmtMoney(account.current_equity)}
            sub={`初始 ${fmtMoney(account.initial_capital)}`}
            color={account.equity_return_ratio >= 0 ? '#ef5350' : '#26a69a'} />
          <Stat label="可用现金" value={fmtMoney(account.current_cash)} />
          <Stat label="持仓市值" value={fmtMoney(account.market_value)} sub={`成本 ${fmtMoney(account.cost_basis)}`} />
          <Stat label="浮动盈亏" value={fmtMoney(account.total_unrealized_pnl)}
            sub={fmtPct(account.unrealized_return_ratio)} color={account.total_unrealized_pnl >= 0 ? '#ef5350' : '#26a69a'} />
          <Stat label="已实现盈亏" value={fmtMoney(account.total_realized_pnl)}
            color={account.total_realized_pnl >= 0 ? '#ef5350' : '#26a69a'} />
          <Stat label="总风险金额" value={fmtMoney(account.total_position_risk_amount)}
            sub={`占权益 ${((account.total_position_risk_ratio || 0) * 100).toFixed(2)}%`}
            tone={account.total_position_risk_ratio > 0.06 ? 'border-red-200 bg-red-50' : 'border-gray-200 bg-white'} />
          <Stat label="活跃持仓" value={`${account.active_positions_count} 笔`}
            sub={account.locked_profit_amount > 0 ? `已锁定利润 ${fmtMoney(account.locked_profit_amount)}` : '止损均低于成本'} />
          <Stat label="账户收益率" value={fmtPct(account.equity_return_ratio)}
            sub={`单笔风险 ${((account.risk_ratio_per_trade || 0) * 100).toFixed(2)}%`}
            color={account.equity_return_ratio >= 0 ? '#ef5350' : '#26a69a'} />
        </div>
      )}

      {/* 风险提醒 */}
      {alerts.length > 0 && (
        <Alert
          className="mb-3"
          type="error"
          showIcon
          message={`${alerts.length} 笔持仓触发风控提醒`}
          description={
            <div className="space-y-0.5">
              {alerts.slice(0, 5).map((a) => (
                <div key={a.position_id} className="text-xs">
                  <Tag color={ACTION_META[a.action]?.color}>{a.action}</Tag>
                  <span className="font-medium">{a.stock_name}</span>
                  <span className="text-gray-500 ml-1">{a.action_suggestion}</span>
                </div>
              ))}
              {alerts.length > 5 && <div className="text-xs text-gray-400">…还有 {alerts.length - 5} 笔</div>}
            </div>
          }
        />
      )}

      <Tabs
        size="small"
        items={[
          {
            key: 'active',
            label: `活跃持仓（${active.length}）`,
            children: (
              <Table
                dataSource={active}
                columns={activeColumns}
                rowKey="position_id"
                loading={isFetching}
                size="small"
                scroll={{ x: 1730 }}
                pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (t) => `共 ${t} 笔` }}
                className="bg-white rounded-lg shadow-sm"
                rowClassName={(r) => (ALERT_ACTIONS.has(r.action) ? 'bg-red-50/40' : '')}
              />
            ),
          },
          {
            key: 'closed',
            label: `历史持仓（${closed.length}）`,
            children: (
              <Table
                dataSource={closed}
                columns={closedColumns}
                rowKey="position_id"
                loading={isFetching}
                size="small"
                scroll={{ x: 1220 }}
                pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (t) => `共 ${t} 笔` }}
                className="bg-white rounded-lg shadow-sm"
              />
            ),
          },
        ]}
      />

      {/* 弹窗 */}
      <PositionEntryDialog
        open={entryOpen}
        defaultAccountId={accountId}
        accounts={accounts}
        onCancel={() => setEntryOpen(false)}
        onOk={() => { setEntryOpen(false); reload() }}
      />

      <SellPositionDialog
        open={!!sellTarget}
        position={sellTarget}
        onCancel={() => setSellTarget(null)}
        onOk={() => { setSellTarget(null); reload() }}
      />

      <PositionDetailDrawer
        open={!!detailId}
        positionId={detailId}
        onClose={() => setDetailId(null)}
        onChanged={() => reload()}
      />

      <RiskParamsDialog
        open={paramsOpen}
        onCancel={() => setParamsOpen(false)}
        onSaved={() => { setParamsOpen(false); reload() }}
      />

      <AccountDialog
        open={accountDlg.open}
        mode={accountDlg.mode}
        account={account}
        positionCount={positions.length}
        onCancel={() => setAccountDlg({ open: false, mode: 'create' })}
        onOk={() => { setAccountDlg({ open: false, mode: 'create' }); queryClient.invalidateQueries({ queryKey: ['position-accounts'] }) }}
        onDeleted={handleAccountDeleted}
      />
    </div>
  )
}

export default PositionPage
