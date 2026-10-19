import React, { useEffect, useMemo, useState, useCallback } from 'react'
import {
  Modal, Form, Input, InputNumber, DatePicker, Select, Alert, Row, Col,
  Tag, Descriptions, Spin, Button, message, Space,
} from 'antd'
import { WalletOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { positionApi } from '../../api'
import { RISK_META, fmtPrice, fmtMoney, assetLabel } from './utils'

const { TextArea } = Input

/** 建仓弹窗：输入代码/日期/价格/股数 → 实时风控预览 → 确认建仓 */
export default function PositionEntryDialog({ open, defaultAccountId, accounts = [], onCancel, onOk }) {
  const [form] = Form.useForm()
  const [preview, setPreview] = useState(null)
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [barInfo, setBarInfo] = useState(null)
  const [barError, setBarError] = useState(null)
  const [error, setError] = useState(null)
  const [forceNeeded, setForceNeeded] = useState(false)

  const values = Form.useWatch([], form) || {}

  // 当前页面选中的账户；没有显式传入时退回第一个账户
  const initialAccount = defaultAccountId || (accounts[0] && accounts[0].account_id)
  const singleAccount = accounts.length === 1

  const accountOptions = useMemo(
    () => accounts.map((a) => ({
      value: a.account_id,
      label: `${a.account_name}（权益 ${fmtMoney(a.current_equity)}）`,
    })),
    [accounts],
  )

  // ⚠ 初始值必须走 Form 的 initialValues —— 在 useEffect 里调 setFieldsValue
  // 会因为 Modal 内容还没挂载、Form 尚未连接而静默失效（表现为账户和买入日期全空）。
  // 配合 Modal 的 destroyOnHidden：每次打开都重新挂载，initialValues 重新生效。
  // 注意：不要 useMemo 住 dayjs()，否则跨天后再打开会带出上次的日期。
  // Form 只在挂载瞬间读一次 initialValues，每次渲染重建对象没有副作用。
  const initialValues = {
    account_id: initialAccount,
    buy_date: dayjs(),      // 默认当天，仍可自由选择历史交易日
    buy_shares: 100,
  }

  // 打开/关闭时的副作用清理（不在这里写表单值）
  useEffect(() => {
    if (!open) {
      form.resetFields()
      setPreview(null)
      setBarInfo(null)
      setBarError(null)
      setError(null)
      setForceNeeded(false)
      return
    }
    // 兜底：如果打开时账户列表还没加载完，等它到了再补填（不覆盖用户已选）
    if (!form.getFieldValue('account_id') && initialAccount) {
      form.setFieldValue('account_id', initialAccount)
    }
  }, [open, initialAccount, form])

  // 代码 + 日期 → 取当日行情，自动填买入价
  useEffect(() => {
    if (!open) return
    const code = (values.stock_code || '').trim()
    const date = values.buy_date
    if (!code || !date) {
      setBarInfo(null)
      setBarError(null)
      return
    }
    let cancelled = false
    const timer = setTimeout(async () => {
      try {
        const res = await positionApi.getBar(code, dayjs(date).format('YYYYMMDD'))
        if (cancelled) return
        setBarInfo(res)
        setBarError(null)
        const cur = form.getFieldValue('buy_price')
        if (cur === undefined || cur === null || cur === '') {
          form.setFieldValue('buy_price', res.close)
        }
      } catch (e) {
        if (cancelled) return
        setBarInfo(null)
        setBarError(e?.response?.data?.detail?.message || e?.response?.data?.detail || '该日期无行情')
      }
    }, 350)
    return () => { cancelled = true; clearTimeout(timer) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, values.stock_code, values.buy_date])

  // 风控预览（防抖）
  useEffect(() => {
    if (!open) return
    const { account_id, stock_code, buy_date, buy_price, buy_shares } = values
    if (!account_id || !stock_code || !buy_date || !buy_price || !buy_shares) {
      setPreview(null)
      setError(null)
      setForceNeeded(false)
      return
    }
    let cancelled = false
    const timer = setTimeout(async () => {
      setLoading(true)
      try {
        const res = await positionApi.preview({
          account_id,
          stock_code: stock_code.trim(),
          buy_date: dayjs(buy_date).format('YYYYMMDD'),
          buy_price: Number(buy_price),
          buy_shares: Number(buy_shares),
        })
        if (cancelled) return
        setPreview(res)
        setError(null)
        setForceNeeded(res.risk_check_status !== 'PASS')
      } catch (e) {
        if (cancelled) return
        setPreview(null)
        setForceNeeded(false)
        setError(e?.response?.data?.detail?.message || e?.response?.data?.detail || '预览失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }, 420)
    return () => { cancelled = true; clearTimeout(timer) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, values.account_id, values.stock_code, values.buy_date, values.buy_price, values.buy_shares])

  const handleCreate = useCallback(async (force) => {
    let v
    try {
      v = await form.validateFields()
    } catch (e) {
      return
    }
    setCreating(true)
    try {
      const res = await positionApi.create({
        account_id: v.account_id,
        stock_code: v.stock_code.trim(),
        buy_date: dayjs(v.buy_date).format('YYYYMMDD'),
        buy_price: Number(v.buy_price),
        buy_shares: Number(v.buy_shares),
        force: !!force,
        note: v.note || null,
      })
      message.success(`已建仓 ${res.stock_code} ${res.stock_name}`)
      onOk?.(res)
    } catch (e) {
      const detail = e?.response?.data?.detail
      if (e?.response?.status === 409 && detail && detail.preview) {
        setPreview(detail.preview)
        setForceNeeded(true)
        message.warning(detail.message || '风险超标，请确认后建仓')
      } else {
        message.error(detail?.message || detail || '建仓失败')
      }
    } finally {
      setCreating(false)
    }
  }, [form, onOk])

  const dec = preview?.price_dec ?? 2
  const riskMeta = preview ? RISK_META[preview.risk_check_status] : null

  return (
    <Modal
      title="建仓（新增持仓）"
      open={open}
      onCancel={onCancel}
      destroyOnHidden
      width={880}
      maskClosable={false}
      footer={[
        <Button key="cancel" onClick={onCancel}>取消</Button>,
        forceNeeded && preview ? (
          <Button key="force" danger loading={creating} onClick={() => handleCreate(true)}>
            仍按 {preview.buy_shares} 股建仓
          </Button>
        ) : null,
        <Button
          key="ok"
          type="primary"
          loading={creating}
          disabled={!preview || !!error}
          onClick={() => handleCreate(false)}
        >
          确认建仓
        </Button>,
      ]}
    >
      <Row gutter={20} className="mt-2">
        {/* 左：表单 */}
        <Col xs={24} md={11}>
          <Form form={form} layout="vertical" preserve={false} initialValues={initialValues}>
            {/* 账户：只有一个账户时直接显示，不再让用户重复选择 */}
            <Form.Item name="account_id" hidden rules={[{ required: true, message: '请选择账户' }]}>
              <Input />
            </Form.Item>
            {singleAccount ? (
              <Form.Item label="账户" extra="使用当前页面选中的账户">
                <div className="flex items-center gap-2 h-8">
                  <WalletOutlined className="text-blue-600" />
                  <span className="font-medium">{accounts[0].account_name}</span>
                  <span className="text-xs text-gray-400">
                    权益 {fmtMoney(accounts[0].current_equity)}
                  </span>
                </div>
              </Form.Item>
            ) : (
              <Form.Item
                label="账户"
                extra="默认使用当前页面选中的账户，可切换"
              >
                <Select
                  value={values.account_id}
                  placeholder="选择账户"
                  options={accountOptions}
                  onChange={(v) => form.setFieldValue('account_id', v)}
                />
              </Form.Item>
            )}

            <Form.Item
              name="stock_code"
              label="代码（个股 / ETF）"
              rules={[{ required: true, message: '请输入代码' }]}
              extra={barInfo
                ? `${barInfo.stock_name}（${assetLabel(barInfo.asset_type)}）`
                : (barError || '输入代码与日期后自动带出当日收盘价')}
            >
              <Input placeholder="如 000001 / 510300" maxLength={6} />
            </Form.Item>

            <Form.Item
              name="buy_date"
              label="买入日期"
              rules={[{ required: true, message: '请选择买入日期' }]}
              extra="默认今天，可改成任意历史交易日（不能选未来）"
            >
              <DatePicker
                style={{ width: '100%' }}
                allowClear={false}
                inputReadOnly={false}
                format="YYYY-MM-DD"
                disabledDate={(d) => d && d.isAfter(dayjs(), 'day')}
              />
            </Form.Item>

            <Row gutter={12}>
              <Col span={12}>
                <Form.Item name="buy_price" label={`买入价${barInfo ? '（元）' : ''}`} rules={[{ required: true, message: '请输入买入价' }]}>
                  <InputNumber min={0.001} step={0.01} style={{ width: '100%' }} placeholder="成交价" />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item
                  name="buy_shares"
                  label="买入股数"
                  rules={[{ required: true, message: '请输入股数' }]}
                  extra="A 股/ETF 均为 100 股整数倍"
                >
                  <InputNumber min={100} step={100} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
            </Row>

            {barInfo && (
              <div className="text-xs text-gray-500 -mt-2 mb-3">
                {barInfo.trade_date} 行情：开 {fmtPrice(barInfo.open, barInfo.price_dec)}
                {' · '}高 {fmtPrice(barInfo.high, barInfo.price_dec)}
                {' · '}低 {fmtPrice(barInfo.low, barInfo.price_dec)}
                {' · '}收 <span className="font-mono">{fmtPrice(barInfo.close, barInfo.price_dec)}</span>
                <Button type="link" size="small" onClick={() => form.setFieldValue('buy_price', barInfo.close)}>
                  用收盘价
                </Button>
              </div>
            )}

            <Form.Item name="note" label="备注（可选）">
              <TextArea rows={2} maxLength={200} placeholder="如：突破平台买入 / 板块轮动" />
            </Form.Item>
          </Form>
        </Col>

        {/* 右：风控预览 */}
        <Col xs={24} md={13}>
          <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 h-full min-h-[300px]">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-bold text-gray-700">事前风控预览</span>
              {loading && <Spin size="small" />}
            </div>

            {error && <Alert type="error" showIcon message={error} />}

            {!error && !preview && !loading && (
              <div className="text-xs text-gray-400 mt-8 text-center">
                填写代码、日期、价格、股数后<br />自动计算 ATR 止损 / 止盈参考 / 建议股数
              </div>
            )}

            {preview && (
              <>
                <div className="mb-2 flex items-center flex-wrap gap-2">
                  <span className="font-bold">{preview.stock_name}</span>
                  <Tag>{preview.stock_code}</Tag>
                  <Tag color="blue">{assetLabel(preview.asset_type)}</Tag>
                  {riskMeta && <Tag color={riskMeta.color}>{riskMeta.label}</Tag>}
                </div>

                <Descriptions size="small" column={2} bordered
                  styles={{ label: { width: 96, fontSize: 12 }, content: { fontSize: 12 } }}>
                  <Descriptions.Item label={`ATR(${preview.atr_period})`}>{fmtPrice(preview.atr_entry, dec)}</Descriptions.Item>
                  <Descriptions.Item label="每股风险">{fmtPrice(preview.risk_per_share, dec)}</Descriptions.Item>
                  <Descriptions.Item label="初始止损">
                    <span className="font-mono text-green-600">{fmtPrice(preview.initial_stop_loss_price, dec)}</span>
                  </Descriptions.Item>
                  <Descriptions.Item label="止盈参考">
                    <span className="font-mono text-red-500">{fmtPrice(preview.take_profit_reference_price, dec)}</span>
                  </Descriptions.Item>
                  <Descriptions.Item label="建议最大股数">{preview.suggested_max_shares?.toLocaleString()}</Descriptions.Item>
                  <Descriptions.Item label="买入金额">{fmtMoney(preview.position_value)}</Descriptions.Item>
                  <Descriptions.Item label="账户权益">{fmtMoney(preview.current_equity)}</Descriptions.Item>
                  <Descriptions.Item label="可承受亏损">{fmtMoney(preview.max_loss_per_trade)}</Descriptions.Item>
                </Descriptions>

                <div className="mt-2 text-xs text-gray-500">
                  止损距买入价 {preview.buy_price ? ((preview.initial_stop_loss_price / preview.buy_price - 1) * 100).toFixed(2) : '-'}%
                  {' · '}止盈参考距买入价 {preview.buy_price ? ((preview.take_profit_reference_price / preview.buy_price - 1) * 100).toFixed(2) : '-'}%
                  {' · '}盈亏比 {preview.risk_per_share > 0
                    ? ((preview.take_profit_reference_price - preview.buy_price) / preview.risk_per_share).toFixed(2)
                    : '-'}
                </div>

                {preview.data_pending && (
                  <Alert
                    className="mt-2"
                    showIcon
                    type="info"
                    message="买入日行情尚未同步"
                    description="不影响建仓：ATR 用买入日之前的日线计算。建仓后点「刷新监控」会自动补齐该股日线；补齐前止损轨迹暂不可用。"
                  />
                )}

                {(preview.messages || []).map((m, i) => (
                  <Alert
                    key={i}
                    className="mt-2"
                    showIcon
                    type={preview.risk_check_status === 'PASS' ? 'success'
                      : preview.risk_check_status === 'REJECT' ? 'error' : 'warning'}
                    message={m}
                    action={preview.suggested_max_shares > 0 && preview.risk_check_status !== 'PASS' ? (
                      <Button size="small" onClick={() => form.setFieldValue('buy_shares', preview.suggested_max_shares)}>
                        采用建议股数
                      </Button>
                    ) : null}
                  />
                ))}

                <div className="mt-2 text-[11px] leading-5 text-gray-400">
                  止损 = 买入价 − {preview.params?.k_initial}×ATR；止盈参考 = 买入价 + {preview.params?.k_take_profit}×ATR；
                  移动止损 = 最高价 − {preview.params?.k_trail}×ATR（MTR 过滤后只上移）。
                  止盈参考为提醒位，非强制卖出价。
                </div>
              </>
            )}
          </div>
        </Col>
      </Row>
    </Modal>
  )
}
