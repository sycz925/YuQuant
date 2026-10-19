import React, { useEffect, useMemo, useState } from 'react'
import {
  Modal, Form, InputNumber, Switch, Select, Alert, Row, Col, message, Spin, Button, Tag, Space, Tooltip,
} from 'antd'
import { QuestionCircleOutlined } from '@ant-design/icons'
import { positionApi } from '../../api'

const LABELS = {
  atr_period: ['ATR 周期', 'TR 的简单移动平均天数'],
  k_initial: ['初始止损 ATR 倍数', '止损 = 买入价 − k × ATR'],
  k_trail: ['移动止损 ATR 倍数', '止损 = 买入以来最高价 − k × ATR'],
  k_take_profit: ['止盈参考 ATR 倍数', '参考位 = 买入价 + k × ATR（非强制卖出）'],
  mtr_period: ['MTR 周期', 'MTR 均值/标准差的窗口'],
  mtr_std_mult: ['MTR 有效放大倍数', 'MTR > 均值 + k×标准差 才算有效放大'],
  trend_ma_period: ['趋势均线周期', '仅启用趋势过滤时生效'],
  tp_trail_pct: ['动态止盈回撤幅度（%）', '浮盈达标后，收盘跌破「最高价 ×(1−该比例)」即提示止盈'],
  tp_arm_r: ['动态止盈启用档位（R）', '浮盈达到几倍初始风险后，由动态止盈接管 ATR 止损'],
}

const DESC = {
  atr_period:
    'ATR（平均真实波幅）= 近 N 个交易日「真实波幅 max(高−低, |高−前收|, |低−前收|)」的平均值，'
    + '衡量该股当前一天通常波动多少。周期越大越平滑、反应越慢。\n\n'
    + '止损距离完全由它决定：止损 = 买入价 − k_initial × ATR。所以 ATR 越大，止损越宽。',
  k_initial:
    '初始止损 = 买入价 − k × ATR_entry。倍数越大止损越宽、越不容易被正常回调打掉，'
    + '但单笔最大亏损也越大（A 股 0.5% 风险规则下建议 2.0~3.0）。\n\n'
    + '2.0 表示「止损放在 2 倍日均波幅之外」。',
  k_trail:
    '移动止损 = 买入以来最高价 − k × ATR_current，并且只上移不下移。\n\n'
    + '倍数越大：回吐越多，但越不容易被中途的正常回调洗掉（趋势票更吃得住）。\n'
    + '倍数越小：保护越紧，但容易过早离场、错过后续涨幅。',
  k_take_profit:
    '止盈参考 = 买入价 + k × ATR_entry，**建仓后固定不变**。\n\n'
    + '它只是一个「可以考虑减一部分了」的提醒位，不强制卖出；'
    + '真正的出场由移动止损决定。所以看到价格突破它不必急着全平。',
  mtr_period:
    'MTR（修正真实波幅）= max(|高−前收|, |低−前收|)，只看跳空幅度、不看日内振幅。\n\n'
    + '用近 N 日的均值与标准差来判断「今天的波动是不是异常放大」。',
  mtr_std_mult:
    '今日 MTR > N日均值 + k × 标准差，才算「波动有效放大」，此时才允许移动止损上移。\n\n'
    + '倍数越大越保守，止损上移次数越少；调到 0 附近基本等于关闭该过滤。',
  trend_ma_period:
    '启用「趋势过滤」后才生效：只有收盘价站上这条均线，才允许上移移动止损。\n\n'
    + '周期越长（如 50/120）过滤越严，越偏向抓大趋势。',
  tp_trail_pct:
    '「动态止盈」启用后，从最高价回撤该比例就提示分批止盈/离场。\n\n'
    + '越小越保守（回吐少，但可能错过后续）；越大越激进（让利润跑，但回吐多）。\n'
    + '实测 25%~30% 比较平衡。',
  tp_arm_r:
    '浮盈达到几倍初始风险 R（R = 买入价 − 初始止损）之后，才启用动态止盈。\n\n'
    + '设高一些可以避免「刚赚一点就把止损放宽」。',
  trailing_high_source:
    '计算「买入以来最高价」时用哪个价格。\n\n'
    + '收盘价：更平滑，止损移动更稳（推荐）。\n'
    + '日内最高价：保护更紧、能更快锁住利润，但容易被一根长上影线的噪音触发。',
  risk_ratio_percent:
    '建仓时的单笔风险上限，占账户总权益的百分比。\n\n'
    + '系统据此倒推建议最大股数：\n'
    + '  可承受亏损 = 账户权益 × 该比例\n'
    + '  建议股数 = 可承受亏损 ÷ 每股风险（买入价 − 初始止损）\n\n'
    + '0.5% 表示单笔最多亏掉账户的 0.5%。账户盈利后权益变大、可买股数自动增加；回撤后自动收缩。',
  mtr_filter_enabled:
    '关闭后：移动止损每天都按公式上移，不再等「波动有效放大」。\n\n'
    + '注意：硬性止损触发（价格跌破止损价）任何时候都不受这个开关影响，必须执行。',
  trend_filter_enabled:
    '开启后：价格没站上趋势均线时，不允许上移移动止损。\n\n'
    + '用于避免震荡市里止损被反复抬高、然后被扫掉的情况。',
  tp_dynamic_enabled:
    '开启后：浮盈达到「启用档位」时，改用「最高价 ×(1−回撤%)」作为离场线，接管 ATR 移动止损。\n\n'
    + '⚠ 接管会明显放松止损、回吐更多。它在趋势票上受益，但在 ATR 本身很紧的持仓上反而更差，'
    + '所以默认关闭。',
}

const NUM_FIELDS = ['atr_period', 'k_initial', 'k_trail', 'k_take_profit', 'mtr_period', 'mtr_std_mult', 'trend_ma_period', 'tp_trail_pct', 'tp_arm_r']

const fmtDefault = (name, v) => {
  if (v === undefined || v === null) return '-'
  if (typeof v === 'boolean') return v ? '开' : '关'
  if (name === 'risk_ratio_percent') return `${v}%`
  if (name === 'trailing_high_source') return v === 'high' ? '日内最高价' : '收盘价'
  return String(v)
}

/** 风控参数设置：每项都标注默认值，可一键恢复默认 */
export default function RiskParamsDialog({ open, onCancel, onSaved }) {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [meta, setMeta] = useState(null)
  const values = Form.useWatch([], form) || {}

  useEffect(() => {
    if (!open) return
    setLoading(true)
    setMeta(null)
    positionApi.getSettings()
      .then((res) => setMeta(res))
      .catch((e) => message.error(e?.response?.data?.detail || '读取风控参数失败'))
      .finally(() => setLoading(false))
  }, [open])

  // ⚠ 必须用 initialValues：Modal 内容挂载晚于父组件 effect，setFieldsValue 会失效。
  // 这里 Form 只在 meta 就绪后渲染，因此 initialValues 在挂载时一定能取到数据。
  const initialValues = useMemo(() => {
    if (!meta) return {}
    const d = meta.defaults || {}
    const p = meta.params || {}
    return {
      ...p,
      risk_ratio_percent: Number(
        ((p.risk_ratio_per_trade ?? d.risk_ratio_per_trade ?? 0.005) * 100).toFixed(4),
      ),
    }
  }, [meta])

  const defaults = meta?.defaults || {}
  const bounds = meta?.bounds || {}
  const choices = meta?.choices || {}

  const isChanged = (name) => {
    const cur = values[name]
    if (cur === undefined || cur === null) return false
    if (name === 'risk_ratio_percent') {
      return Math.abs(Number(cur) - Number(defaults.risk_ratio_per_trade ?? 0.005) * 100) > 1e-9
    }
    if (typeof defaults[name] === 'boolean') return Boolean(cur) !== defaults[name]
    if (typeof defaults[name] === 'string') return cur !== defaults[name]
    return Math.abs(Number(cur) - Number(defaults[name])) > 1e-9
  }

  const changedList = [
    ...NUM_FIELDS, 'trailing_high_source', 'mtr_filter_enabled',
    'trend_filter_enabled', 'risk_ratio_percent',
  ].filter(isChanged)

  const handleReset = () => {
    form.setFieldsValue({
      ...defaults,
      risk_ratio_percent: Number(((defaults.risk_ratio_per_trade ?? 0.005) * 100).toFixed(4)),
    })
    message.info('已恢复为出厂默认值，点击「保存」后生效')
  }

  const handleOk = async () => {
    let v
    try {
      v = await form.validateFields()
    } catch (e) {
      return
    }
    setSaving(true)
    try {
      const { risk_ratio_percent, ...rest } = v
      const payload = {
        ...rest,
        risk_ratio_per_trade: Number(risk_ratio_percent) / 100,
      }
      const res = await positionApi.saveSettings(payload)
      message.success('风控参数已保存（对之后的重算生效）')
      onSaved?.(res)
    } catch (e) {
      message.error(e?.response?.data?.detail || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const fieldProps = (name) => ({
    min: bounds[name]?.[0],
    max: bounds[name]?.[1],
    step: ['atr_period', 'mtr_period', 'trend_ma_period'].includes(name) ? 1 : 0.1,
  })

  /** 标签：参数名 + 说明问号 + 「已改」提示（默认值改放到输入框内） */
  const label = (name, title) => (
    <span className="inline-flex items-center gap-1.5">
      <span>{title}</span>
      {DESC[name] && (
        <Tooltip
          trigger={['hover', 'click']}
          overlayStyle={{ maxWidth: 380 }}
          title={<div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.7, fontSize: 12 }}>{DESC[name]}</div>}
        >
          <QuestionCircleOutlined className="text-gray-400 cursor-help" style={{ fontSize: 11 }} />
        </Tooltip>
      )}
      {isChanged(name) && (
        <Tag color="orange" bordered={false} className="!m-0 !px-1 !text-[10px] !leading-4">已改</Tag>
      )}
    </span>
  )

  /** 输入框内的默认值提示（suffix，随输入框一起显示） */
  const defSuffix = (name, text) => (
    <span className="text-[10px] text-gray-400 whitespace-nowrap select-none">
      默认 {text ?? fmtDefault(name, defaults[name])}
    </span>
  )

  return (
    <Modal
      title={
        <div className="flex items-center gap-2">
          <span>风控参数设置</span>
          {meta && (
            changedList.length === 0
              ? <Tag color="green" bordered={false}>当前全部为默认值</Tag>
              : <Tag color="orange" bordered={false}>已修改 {changedList.length} 项</Tag>
          )}
        </div>
      }
      open={open}
      onCancel={onCancel}
      destroyOnHidden
      width={760}
      footer={[
        <Button key="reset" onClick={handleReset} disabled={!meta}>恢复默认值</Button>,
        <Button key="cancel" onClick={onCancel}>取消</Button>,
        <Button key="ok" type="primary" loading={saving} onClick={handleOk}>保存</Button>,
      ]}
    >
      {loading ? (
        <div className="py-12 text-center"><Spin /></div>
      ) : (
        <Form form={form} layout="vertical" className="mt-2" preserve={false} initialValues={initialValues}>
          <Alert
            className="mb-3"
            type="warning"
            showIcon
            message="参数修改后，已有持仓的止损轨迹会在下次重算时按新参数重新计算"
            description="建仓时冻结的 initial_stop_loss_price / atr_entry / take_profit_reference_price 不会被改写（用于审计），但移动止损（current_stop_loss_price）会按新参数滚动更新。"
          />

          <Row gutter={16}>
            {NUM_FIELDS.map((name) => (
              <Col xs={24} md={12} key={name}>
                <Form.Item
                  name={name}
                  label={label(name, LABELS[name][0])}
                  extra={LABELS[name][1]}
                  rules={[{ required: true, message: '不能为空' }]}
                >
                  <InputNumber
                    {...fieldProps(name)}
                    style={{ width: '100%' }}
                    suffix={defSuffix(name)}
                    placeholder={String(defaults[name] ?? '')}
                  />
                </Form.Item>
              </Col>
            ))}

            <Col xs={24} md={12}>
              <Form.Item
                name="trailing_high_source"
                label={label('trailing_high_source', '买入以来最高价来源')}
                extra={`默认 ${fmtDefault('trailing_high_source', defaults.trailing_high_source)} · 用收盘价更平滑；用日内最高价保护更紧但易被噪音触发`}
                rules={[{ required: true }]}
              >
                <Select
                  placeholder={`默认 ${fmtDefault('trailing_high_source', defaults.trailing_high_source)}`}
                  options={(choices.trailing_high_source || ['close', 'high']).map((v) => ({
                    value: v,
                    label: v === 'high' ? '日内最高价' : '收盘价（推荐）',
                  }))}
                />
              </Form.Item>
            </Col>

            <Col xs={24} md={12}>
              <Form.Item
                name="risk_ratio_percent"
                label={label('risk_ratio_percent', '新建账户默认单笔风险比例')}
                extra="单位 %。仅作为新建账户的默认值；已有账户在「编辑账户」里单独设置"
                rules={[{ required: true, message: '不能为空' }]}
              >
                <InputNumber
                  min={0.01}
                  max={50}
                  step={0.1}
                  style={{ width: '100%' }}
                  suffix={defSuffix('risk_ratio_percent', `${Number((defaults.risk_ratio_per_trade ?? 0.005) * 100).toFixed(2)}%`)}
                  placeholder={String(Number((defaults.risk_ratio_per_trade ?? 0.005) * 100).toFixed(2))}
                />
              </Form.Item>
            </Col>

            <Col xs={12} md={6}>
              <Form.Item
                name="mtr_filter_enabled"
                label={label('mtr_filter_enabled', '启用 MTR 过滤')}
                valuePropName="checked"
                extra={`默认 ${fmtDefault('mtr_filter_enabled', defaults.mtr_filter_enabled)} · 关闭后移动止损每日都按公式上移`}
              >
                <Switch />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item
                name="trend_filter_enabled"
                label={label('trend_filter_enabled', '启用趋势过滤')}
                valuePropName="checked"
                extra={`默认 ${fmtDefault('trend_filter_enabled', defaults.trend_filter_enabled)} · 价格需站上趋势均线`}
              >
                <Switch />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item
                name="tp_dynamic_enabled"
                label={label('tp_dynamic_enabled', '启用动态止盈')}
                valuePropName="checked"
                extra={`默认 ${fmtDefault('tp_dynamic_enabled', defaults.tp_dynamic_enabled)} · 浮盈达标后接管 ATR 止损，让利润奔跑`}
              >
                <Switch />
              </Form.Item>
            </Col>
          </Row>

          <div className="text-xs text-gray-500 leading-6 bg-gray-50 rounded p-3">
            <b>纪律约束</b>：MTR 只过滤「移动止损上移 / 加仓 / 趋势确认」，<span className="text-red-500">不作用于硬性止损触发</span>——
            一旦价格触及止损价，无论 MTR 状态如何都必须执行卖出。止损只上移不下移。
          </div>
        </Form>
      )}
    </Modal>
  )
}
