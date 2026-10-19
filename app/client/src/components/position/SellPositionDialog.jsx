import React, { useEffect, useMemo, useState } from 'react'
import {
  Modal, Form, InputNumber, DatePicker, Input, Alert, Descriptions, Row, Col,
  Button, Space, message, Tag, Divider, Select,
} from 'antd'
import dayjs from 'dayjs'
import { positionApi } from '../../api'
import { fmtMoney, fmtPrice, fmtPct, assetLabel, pnlStyle } from './utils'

const { TextArea } = Input

const REASONS = [
  { value: 'take_profit', label: '主动减仓（达止盈参考）' },
  { value: 'stop_loss', label: '被动止损（跌破止损价）' },
  { value: 'manual', label: '手动卖出' },
]

/**
 * 卖出入库（支持分批）
 *  - 只卖部分股数时持仓保持「活跃」，卖完才转历史持仓
 *  - 卖出股数不要求 100 整数倍（与买入不同）；剩余不足 100 股为零股，需一次卖完
 */
export default function SellPositionDialog({ open, position, onCancel, onOk }) {
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [warnings, setWarnings] = useState([])
  const [barInfo, setBarInfo] = useState(null)
  const [barError, setBarError] = useState(null)
  const lastAutoDateRef = React.useRef(null)   // 已自动带出过价格的日期，避免反复覆盖手填值
  const values = Form.useWatch([], form) || {}

  const dec = position?.price_dec ?? 2
  const isEtf = position?.asset_type === 'etf'
  const buyPrice = position?.buy_price ?? 0
  const remaining = position?.remaining_shares ?? position?.buy_shares ?? 0
  const currentPrice = position?.current_price ?? 0
  const cumRealized = position?.realized_pnl ?? 0
  const lastSellDate = position?.last_sell_date || null

  // ⚠ 必须用 Form.initialValues：antd Modal 的内容在父组件 effect 之后才挂载
  // （rc-dialog DialogWrap 首帧 return null），在 effect 里 setFieldsValue 会静默失效。
  const initialValues = {
    sell_date: position?.trade_date ? dayjs(position.trade_date, 'YYYYMMDD') : dayjs(),
    sell_price: position?.current_price ?? null,
    shares: position?.remaining_shares ?? position?.buy_shares ?? 0,
    reason: 'take_profit',
  }

  useEffect(() => {
    if (!open) {
      setError(null)
      setWarnings([])
      setBarInfo(null)
      setBarError(null)
      lastAutoDateRef.current = null
    }
  }, [open])

  // 卖出日期变化 → 自动带出该交易日行情，并把卖出价填成当日收盘价
  // （选「最新交易日」时拿到的就是当前最新价）
  const sellDateStr = values.sell_date ? dayjs(values.sell_date).format('YYYYMMDD') : null
  useEffect(() => {
    if (!open || !position || !sellDateStr) return undefined
    if (lastAutoDateRef.current === sellDateStr) return undefined
    let cancelled = false
    const timer = setTimeout(async () => {
      try {
        const res = await positionApi.getBar(position.stock_code, sellDateStr)
        if (cancelled) return
        setBarInfo(res)
        setBarError(null)
        lastAutoDateRef.current = sellDateStr
        form.setFieldValue('sell_price', res.close)
      } catch (e) {
        if (cancelled) return
        const msg = e?.response?.data?.detail?.message || e?.response?.data?.detail || '该日期无行情'
        setBarInfo(null)
        setBarError(msg)
        lastAutoDateRef.current = sellDateStr
        // 拿不到当日行情时退回最新价
        if (position.current_price) form.setFieldValue('sell_price', position.current_price)
      }
    }, 250)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [open, position, sellDateStr, form])

  const sellPrice = Number(values.sell_price) || 0
  const qty = Math.floor(Number(values.shares) || 0)
  const left = remaining - qty

  const preview = useMemo(() => {
    if (sellPrice <= 0 || qty <= 0) return null
    const amount = sellPrice * qty
    const realized = (sellPrice - buyPrice) * qty
    const ratio = buyPrice > 0 ? (sellPrice - buyPrice) / buyPrice : null
    const leftUnrealized = currentPrice > 0 && left > 0 ? (currentPrice - buyPrice) * left : 0
    return {
      amount,
      realized,
      ratio,
      left,
      leftUnrealized,
      cumRealized: cumRealized + realized,
    }
  }, [sellPrice, qty, buyPrice, currentPrice, left, cumRealized])

  const setQty = (v) => form.setFieldValue('shares', v)

  const handleOk = async () => {
    let v
    try {
      v = await form.validateFields()
    } catch (e) {
      return
    }
    setSaving(true)
    setError(null)
    try {
      const res = await positionApi.sell(position.position_id, {
        sell_date: dayjs(v.sell_date).format('YYYYMMDD'),
        sell_price: Number(v.sell_price),
        shares: Math.floor(Number(v.shares)),
        reason: v.reason,
        note: v.note || null,
      })
      const isClosed = res.status === 'CLOSED'
      message.success(isClosed
        ? `已全部卖出，累计实现盈亏 ${fmtMoney(res.realized_pnl)}`
        : `已卖出 ${qty} 股，剩余 ${res.remaining_shares} 股继续监控`)
      if (res.warnings?.length) res.warnings.forEach((w) => message.warning(w, 6))
      onOk?.(res)
    } catch (e) {
      const detail = e?.response?.data?.detail
      setError(detail?.message || detail || '卖出失败')
    } finally {
      setSaving(false)
    }
  }

  if (!position) return null

  const isPartial = preview && preview.left > 0
  const zeroLotHint = preview && preview.left > 0 && preview.left < 100 && !isEtf

  return (
    <Modal
      title={
        <div className="flex items-center gap-2">
          <span>卖出</span>
          <Tag color="blue">{assetLabel(position.asset_type)}</Tag>
          <Tag color={isPartial ? 'green' : 'default'}>
            {isPartial ? '部分卖出（持仓继续）' : '全部卖出（转历史持仓）'}
          </Tag>
        </div>
      }
      open={open}
      onCancel={onCancel}
      onOk={handleOk}
      confirmLoading={saving}
      okText={isPartial ? `卖出 ${qty || 0} 股` : '确认全部卖出'}
      okButtonProps={{ danger: true }}
      destroyOnHidden
      width={620}
    >
      <Alert
        className="mb-3"
        type="info"
        showIcon
        message="系统不做自动平仓，所有卖出都由你手动触发后记录"
        description="只卖部分股数时，该持仓仍保持「活跃」并继续按 ATR 移动止损监控（止损价不因减仓而改变）。"
      />

      <Descriptions size="small" column={2} bordered className="mb-3"
        styles={{ label: { width: 92, fontSize: 12 }, content: { fontSize: 12 } }}>
        <Descriptions.Item label="标的">
          {position.stock_name} <span className="text-gray-400">({position.stock_code})</span>
        </Descriptions.Item>
        <Descriptions.Item label="买入日 / 买入价">
          {position.buy_date} / <span className="font-mono">{fmtPrice(buyPrice, dec)}</span>
        </Descriptions.Item>
        <Descriptions.Item label="原始建仓">
          {position.buy_shares?.toLocaleString()} 股
          {(position.sold_shares ?? 0) > 0 && (
            <span className="text-gray-400 ml-1">（已卖 {position.sold_shares?.toLocaleString()}）</span>
          )}
        </Descriptions.Item>
        <Descriptions.Item label="当前可卖">
          <span className="font-mono font-bold">{remaining?.toLocaleString()} 股</span>
        </Descriptions.Item>
        <Descriptions.Item label="最新价">
          <span className="font-mono">{fmtPrice(currentPrice, dec)}</span>
        </Descriptions.Item>
        <Descriptions.Item label="累计已实现">
          <span className="font-mono" style={pnlStyle(cumRealized)}>{fmtMoney(cumRealized)}</span>
        </Descriptions.Item>
      </Descriptions>

      <Form form={form} layout="vertical" preserve={false} initialValues={initialValues}>
        <Row gutter={12}>
          <Col span={12}>
            <Form.Item name="sell_date" label="卖出日期" rules={[{ required: true, message: '请选择卖出日期' }]}>
              <DatePicker
                style={{ width: '100%' }}
                allowClear={false}
                disabledDate={(d) => {
                  if (!d) return false
                  const s = d.format('YYYYMMDD')
                  if (d.isAfter(dayjs(), 'day')) return true
                  if (!isEtf && s <= position.buy_date) return true     // A股 T+1
                  if (s < position.buy_date) return true
                  if (lastSellDate && s < lastSellDate) return true     // 不能早于上一笔卖出
                  return false
                }}
              />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="sell_price"
              label="卖出价"
              rules={[{ required: true, message: '请输入卖出价' }]}
              extra={barError || (barInfo ? '已自动带出该日收盘价，可手动改' : '选日期后自动带出')}
            >
              <InputNumber min={0.001} step={0.01} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
        </Row>

        {barInfo && (
          <div className="text-xs text-gray-500 -mt-1 mb-2">
            {barInfo.trade_date} 行情：开 {fmtPrice(barInfo.open, barInfo.price_dec)}
            {' · '}高 {fmtPrice(barInfo.high, barInfo.price_dec)}
            {' · '}低 {fmtPrice(barInfo.low, barInfo.price_dec)}
            {' · '}收 <span className="font-mono">{fmtPrice(barInfo.close, barInfo.price_dec)}</span>
            <Button type="link" size="small" onClick={() => form.setFieldValue('sell_price', barInfo.close)}>
              用收盘价
            </Button>
            {position?.current_price != null && (
              <Button
                type="link"
                size="small"
                onClick={() => form.setFieldValue('sell_price', position.current_price)}
              >
                用最新价 {fmtPrice(position.current_price, dec)}
              </Button>
            )}
          </div>
        )}

        <Form.Item
          name="shares"
          label="卖出股数"
          rules={[
            { required: true, message: '请输入卖出股数' },
            {
              validator: (_, v) => {
                const n = Math.floor(Number(v) || 0)
                if (n <= 0) return Promise.reject(new Error('卖出股数必须大于 0'))
                if (n > remaining) return Promise.reject(new Error(`不能超过可卖 ${remaining} 股`))
                return Promise.resolve()
              },
            },
          ]}
          extra="卖出不要求 100 股整数倍（与买入不同）"
        >
          <InputNumber
            min={1}
            max={remaining}
            step={100}
            style={{ width: '100%' }}
            addonAfter={<span className="text-xs text-gray-400">/ 可卖 {remaining}</span>}
          />
        </Form.Item>

        <Space className="mb-3" wrap>
          <span className="text-xs text-gray-500">快捷：</span>
          <Button size="small" onClick={() => setQty(Math.max(1, Math.floor(remaining / 3)))}>1/3</Button>
          <Button size="small" onClick={() => setQty(Math.max(1, Math.floor(remaining / 2)))}>1/2</Button>
          <Button size="small" onClick={() => setQty(Math.max(1, Math.floor((remaining * 2) / 3)))}>2/3</Button>
          <Button size="small" type="primary" ghost onClick={() => setQty(remaining)}>全部</Button>
        </Space>

        <Form.Item name="reason" label="卖出理由" rules={[{ required: true }]}
          extra="用于区分「主动减仓」和「被动止损」，便于事后统计两类卖出的盈亏贡献">
          <Select options={REASONS} />
        </Form.Item>

        <Form.Item name="note" label="备注（可选）">
          <TextArea rows={2} maxLength={200} placeholder="如：达止盈参考位减半 / 跌破止损离场" />
        </Form.Item>
      </Form>

      {preview && (
        <div className="rounded-lg bg-gray-50 border border-gray-200 p-3 text-sm">
          <div className="flex justify-between">
            <span className="text-gray-500">本笔卖出金额</span>
            <span className="font-mono">{fmtMoney(preview.amount)}</span>
          </div>
          <div className="flex justify-between mt-1">
            <span className="text-gray-500">本笔已实现盈亏</span>
            <span className="font-mono font-bold" style={pnlStyle(preview.realized)}>
              {preview.realized >= 0 ? '+' : ''}{fmtMoney(preview.realized)}（{fmtPct(preview.ratio)}）
            </span>
          </div>
          <Divider className="!my-2" />
          <div className="flex justify-between">
            <span className="text-gray-500">卖出后剩余股数</span>
            <span className="font-mono">{preview.left.toLocaleString()} 股</span>
          </div>
          {preview.left > 0 && (
            <div className="flex justify-between mt-1">
              <span className="text-gray-500">剩余持仓浮动盈亏</span>
              <span className="font-mono" style={pnlStyle(preview.leftUnrealized)}>
                {fmtMoney(preview.leftUnrealized)}
              </span>
            </div>
          )}
          <div className="flex justify-between mt-1">
            <span className="text-gray-500">累计已实现盈亏</span>
            <span className="font-mono" style={pnlStyle(preview.cumRealized)}>
              {fmtMoney(preview.cumRealized)}
            </span>
          </div>
        </div>
      )}

      {zeroLotHint && (
        <Alert
          className="mt-2"
          type="warning"
          showIcon
          message={`卖出后剩余 ${preview.left} 股为零股，下次必须一次性全部卖出`}
        />
      )}

      {error && <Alert className="mt-3" type="error" showIcon message={error} />}
      {warnings.map((w, i) => (
        <Alert key={i} className="mt-2" type="warning" showIcon message={w} />
      ))}
    </Modal>
  )
}
