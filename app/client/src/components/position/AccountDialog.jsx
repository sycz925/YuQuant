import React, { useMemo, useState } from 'react'
import { Modal, Form, Input, InputNumber, Alert, message, Switch, Popconfirm, Button, Space } from 'antd'
import { DeleteOutlined } from '@ant-design/icons'
import { positionApi } from '../../api'

/** 新建 / 编辑账户 */
export default function AccountDialog({ open, mode = 'create', account, positionCount = 0, onCancel, onOk, onDeleted }) {
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const isEdit = mode === 'edit'

  // ⚠ 必须用 initialValues：Modal 内容挂载晚于父组件 effect，setFieldsValue 会失效
  const initialValues = useMemo(() => (
    isEdit && account
      ? {
        account_name: account.account_name,
        risk_ratio_percent: Number(((account.risk_ratio_per_trade ?? 0.005) * 100).toFixed(4)),
        capital_delta: null,
        enabled: !account.is_disable,
        primary: !!account.is_primary,
      }
      : { risk_ratio_percent: 0.5, enabled: true }
  ), [isEdit, account])

  const handleOk = async () => {
    let values
    try {
      values = await form.validateFields()
    } catch (e) {
      return
    }
    setSaving(true)
    try {
      const risk = Number(values.risk_ratio_percent) / 100
      if (isEdit) {
        await positionApi.updateAccount(account.account_id, {
          account_name: values.account_name,
          risk_ratio_per_trade: risk,
          capital_delta: values.capital_delta || null,
          is_disable: values.enabled === false,
          is_primary: !!values.primary,
        })
        message.success('账户已更新')
      } else {
        await positionApi.createAccount({
          account_name: values.account_name,
          initial_capital: values.initial_capital,
          risk_ratio_per_trade: risk,
        })
        message.success('账户已创建')
      }
      onOk?.()
    } catch (e) {
      message.error(e?.response?.data?.detail?.message || e?.response?.data?.detail || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!account) return
    setDeleting(true)
    try {
      await positionApi.deleteAccount(account.account_id, true)
      message.success(`已删除账户「${account.account_name}」及其全部持仓记录`)
      onDeleted?.(account)
    } catch (e) {
      message.error(e?.response?.data?.detail?.message || e?.response?.data?.detail || '删除失败')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <Modal
      title={isEdit ? '编辑账户' : '新建账户'}
      open={open}
      onCancel={onCancel}
      footer={
        <div className="flex items-center justify-between mt-2">
          {isEdit ? (
            <Popconfirm
              title="删除整个账户？"
              description={
                <div style={{ maxWidth: 268, lineHeight: 1.7 }}>
                  将同时删除该账户下的 <b>{positionCount}</b> 笔持仓记录（含已平仓），
                  以及其现金与权益数据。<br />
                  <span className="text-red-500">此操作不可撤销。</span>
                </div>
              }
              okText="确认删除"
              okButtonProps={{ danger: true }}
              cancelText="取消"
              onConfirm={handleDelete}
            >
              <Button danger type="text" icon={<DeleteOutlined />} loading={deleting}>
                删除账户
              </Button>
            </Popconfirm>
          ) : <span />}
          <Space>
            <Button onClick={onCancel}>取消</Button>
            <Button type="primary" loading={saving} onClick={handleOk}>保存</Button>
          </Space>
        </div>
      }
      destroyOnHidden
      width={460}
    >
      <Form form={form} layout="vertical" className="mt-3" preserve={false} initialValues={initialValues}>
        <Form.Item name="account_name" label="账户名称" rules={[{ required: true, message: '请输入账户名称' }]}>
          <Input placeholder="如：主账户 / 试验账户" maxLength={30} />
        </Form.Item>

        {!isEdit && (
          <Form.Item name="initial_capital" label="初始资金（元）" rules={[{ required: true, message: '请输入初始资金' }]}>
            <InputNumber min={1} step={10000} style={{ width: '100%' }} placeholder="如：200000" />
          </Form.Item>
        )}

        <Form.Item
          name="risk_ratio_percent"
          label="单笔最大风险占权益比例（%）"
          rules={[{ required: true, message: '请输入风险比例' }]}
          extra="默认 0.5%。账户权益越大，单笔可承受的风险金额越高。"
        >
          <InputNumber min={0.01} max={50} step={0.1} style={{ width: '100%' }} addonAfter="%" />
        </Form.Item>

        {isEdit && (
          <Form.Item name="capital_delta" label="出入金（正=入金 / 负=出金，元）" extra="写入后按新现金重算账户权益。">
            <InputNumber step={10000} style={{ width: '100%' }} placeholder="留空表示不变" />
          </Form.Item>
        )}

        {isEdit && (
          <>
            <Form.Item
              name="primary"
              label="设为主账户"
              valuePropName="checked"
              extra="进入「持仓」页面时默认展示该账户。全局只能有一个主账户，设置后原主账户会自动取消。"
            >
              <Switch />
            </Form.Item>
            <Form.Item
              name="enabled"
              label="启用该账户"
              valuePropName="checked"
              extra="禁用后：该账户持仓不再产生顶部预警，也不参与「刷新监控」的批量重算；仍可正常查看与管理。"
            >
              <Switch />
            </Form.Item>
          </>
        )}

        <Alert
          type="info"
          showIcon
          message="权益动态风控"
          description="current_equity 每日随持仓市值更新，作为新的风险校验基准：盈利后风险敞口自动放大，回撤后自动收缩。"
        />
      </Form>
    </Modal>
  )
}
