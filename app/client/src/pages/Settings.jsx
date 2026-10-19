import React, { useState, useEffect, useRef } from 'react'
import { ConfigProvider, Card, Button, Space, Typography, Switch, message } from 'antd'
import {
  SettingOutlined,
  DatabaseOutlined,
  ToolOutlined,
  SwapOutlined,
  UploadOutlined,
  BarChartOutlined,
  StockOutlined,
  AppstoreOutlined
} from '@ant-design/icons'
import zhCN from 'antd/locale/zh_CN'
import { factorApi, taskApi } from '../api'
import ManagementDialog from '../components/ManagementDialog'
import CompareDataModal from '../components/settings/CompareDataModal'
import ImportSectorModal from '../components/settings/ImportSectorModal'
import EntityCard from '../components/settings/EntityCard'

const { Title, Text } = Typography

function SectionTitle({ icon, children }) {
  return (
    <div className="flex items-center space-x-2">
      <span className="text-gray-400">{icon}</span>
      <Title level={4} className="!mb-0">{children}</Title>
    </div>
  )
}

function Settings() {
  // 管理对话框状态
  const [manageDialog, setManageDialog] = useState({ open: false, category: '', title: '' })

  // 对比数据状态
  const [compareModal, setCompareModal] = useState({ open: false, type: '', data: null, loading: false })

  // 名称修复状态
  const [repairing, setRepairing] = useState(false)

  // 导入板块弹窗（mode: 'sector' 仅代码 | 'sector_with_stocks' 板块+成分股）
  const [importModal, setImportModal] = useState({ open: false, mode: 'sector' })

  // DeepSeek 时间窗口配置
  const [deepseekTimeLimit, setDeepseekTimeLimit] = useState(true)

  useEffect(() => {
    loadDeepseekConfig()
  }, [])

  const loadDeepseekConfig = async () => {
    try {
      const res = await factorApi.getDeepseekTimeLimit()
      if (res?.success) {
        setDeepseekTimeLimit(res.enabled)
      }
    } catch (e) {
      console.error('加载配置失败:', e)
    }
  }

  const handleToggleDeepseekTimeLimit = async () => {
    const newValue = !deepseekTimeLimit
    try {
      const res = await factorApi.setDeepseekTimeLimit(newValue)
      if (res?.success) {
        setDeepseekTimeLimit(newValue)
        message.success(`已${newValue ? '启用' : '禁用'}时间窗口限制`)
      }
    } catch (e) {
      console.error('设置配置失败:', e)
      message.error('设置失败')
    }
  }

  const handleRepairStockNames = async () => {
    if (repairing) return
    setRepairing(true)
    try {
      const res = await factorApi.repairStockNames()
      const taskId = res?.task_id
      if (!taskId) {
        message.error('启动名称修复失败')
        setRepairing(false)
        return
      }
      message.info('名称修复已启动，后台执行中...')
      // 轮询任务状态
      const timer = setInterval(async () => {
        try {
          const status = await taskApi.getStatus(taskId)
          if (status.status === 'completed') {
            clearInterval(timer)
            message.success(status.message || '名称修复完成')
            setRepairing(false)
          } else if (status.status === 'failed') {
            clearInterval(timer)
            message.error(status.message || '名称修复失败')
            setRepairing(false)
          }
        } catch (e) {
          console.error('轮询名称修复状态失败:', e)
        }
      }, 2000)
    } catch (e) {
      message.error(e?.response?.data?.detail || '名称修复启动失败')
      setRepairing(false)
    }
  }

  // 对比数据（任务模式）
  const comparePollRef = useRef(null)

  const handleCompare = async (type) => {
    setCompareModal({ open: true, type, data: null, loading: true, taskStep: '启动中...' })
    try {
      const res = type === 'stock'
        ? await factorApi.compareStocksStart()
        : await factorApi.compareSectorsStart()

      if (!res?.task_id) {
        message.error('启动对比任务失败')
        setCompareModal({ open: false, type: '', data: null, loading: false })
        return
      }

      // 轮询任务状态
      comparePollRef.current = setInterval(async () => {
        try {
          const status = await factorApi.compareStatus(res.task_id)
          if (status.status === 'completed') {
            clearInterval(comparePollRef.current)
            setCompareModal({
              open: true,
              type,
              data: status.result,
              loading: false,
              taskStep: null
            })
          } else if (status.status === 'failed') {
            clearInterval(comparePollRef.current)
            message.error('对比任务失败: ' + (status.error || '未知错误'))
            setCompareModal({ open: false, type: '', data: null, loading: false })
          } else {
            setCompareModal(prev => ({
              ...prev,
              taskStep: status.step || '处理中...'
            }))
          }
        } catch (e) {
          console.error('轮询对比状态失败:', e)
        }
      }, 2000)
    } catch (e) {
      console.error('启动对比任务失败:', e)
      message.error('启动对比任务失败')
      setCompareModal({ open: false, type: '', data: null, loading: false })
    }
  }

  // 关闭弹窗时清除轮询
  const handleCloseCompareModal = () => {
    if (comparePollRef.current) {
      clearInterval(comparePollRef.current)
    }
    setCompareModal({ open: false, type: '', data: null, loading: false })
  }

  const handleImportSuccess = () => {
    setCompareModal(prev => {
      const data = { ...prev.data }
      if (prev.type === 'stock') {
        data.new_stocks = []
        data.new_count = 0
      } else {
        data.update_sectors = []
        data.update_count = 0
      }
      return { ...prev, data }
    })
  }

  const openManage = (category, title) => setManageDialog({ open: true, category, title })

  return (
    <ConfigProvider locale={zhCN}>
      <div className="max-w-4xl mx-auto space-y-8 pb-12">
        <header className="flex items-center space-x-4">
          <div className="p-3 bg-gray-900 rounded-2xl text-white">
            <SettingOutlined style={{ fontSize: '24px' }} />
          </div>
          <div>
            <Title level={2} style={{ margin: 0, fontWeight: 900, letterSpacing: '-0.5px' }}>系统设置</Title>
            <Text type="secondary" className="text-xs font-bold uppercase tracking-widest">Entity Management · Data Maintenance · System Config</Text>
          </div>
        </header>

        {/* 实体管理 */}
        <section className="space-y-4">
          <SectionTitle icon={<DatabaseOutlined />}>实体管理</SectionTitle>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <EntityCard
              icon={<BarChartOutlined className="text-blue-600 text-xl" />}
              iconBg="#dbeafe"
              title="指数"
              description="管理指数的启用/禁用与 TDX 代码"
              onManage={() => openManage('index', '管理指数')}
            />
            <EntityCard
              icon={<StockOutlined className="text-green-600 text-xl" />}
              iconBg="#dcfce7"
              title="个股"
              description="管理个股的启用/禁用与退市标记"
              onManage={() => openManage('stock', '管理个股')}
            />
            <EntityCard
              icon={<AppstoreOutlined className="text-purple-600 text-xl" />}
              iconBg="#f3e8ff"
              title="板块"
              description="管理板块与成分股，支持导入板块代码"
              onManage={() => openManage('sector', '管理板块')}
            />
          </div>
        </section>

        {/* 数据维护 */}
        <section className="space-y-4">
          <SectionTitle icon={<ToolOutlined />}>数据维护</SectionTitle>
          <Card className="rounded-2xl shadow-sm border-gray-100">
            <div className="space-y-5">
              <div className="flex items-center justify-between gap-4 flex-wrap">
                <div>
                  <Text className="text-sm font-medium">数据对比</Text>
                  <Text type="secondary" className="text-xs block">对比 pytdx 与本地数据，发现缺失次新股或板块变化</Text>
                </div>
                <Space>
                  <Button icon={<SwapOutlined />} onClick={() => handleCompare('stock')}>次新股对比</Button>
                  <Button icon={<SwapOutlined />} onClick={() => handleCompare('sector')}>板块对比</Button>
                </Space>
              </div>

              <div className="flex items-center justify-between gap-4 flex-wrap">
                <div>
                  <Text className="text-sm font-medium">名称修复</Text>
                  <Text type="secondary" className="text-xs block">修复截断/改名的股票名称，自动禁用退市股</Text>
                </div>
                <Button
                  icon={<ToolOutlined />}
                  loading={repairing}
                  disabled={repairing}
                  onClick={handleRepairStockNames}
                >
                  修复名称
                </Button>
              </div>

              <div className="flex items-center justify-between gap-4 flex-wrap">
                <div>
                  <Text className="text-sm font-medium">导入板块</Text>
                  <Text type="secondary" className="text-xs block">导入板块代码（Excel）或板块带成分股（txt），预览后确认</Text>
                </div>
                <Space>
                  <Button icon={<UploadOutlined />} onClick={() => setImportModal({ open: true, mode: 'sector' })}>
                    导入板块
                  </Button>
                  <Button icon={<UploadOutlined />} onClick={() => setImportModal({ open: true, mode: 'sector_with_stocks' })}>
                    导入板块带成分股
                  </Button>
                </Space>
              </div>
            </div>
          </Card>
        </section>

        {/* 系统配置 */}
        <section className="space-y-4">
          <SectionTitle icon={<SettingOutlined />}>系统配置</SectionTitle>
          <Card className="rounded-2xl shadow-sm border-gray-100">
            <div className="flex items-center justify-between gap-4 flex-wrap">
              <div>
                <Text className="text-sm font-medium">DeepSeek API 时间窗口</Text>
                <Text type="secondary" className="text-xs block">可用时间：12:00-13:00 或 18:00-23:59；关闭后不限时</Text>
              </div>
              <Space>
                <Text className="text-sm" type={deepseekTimeLimit ? 'secondary' : 'success'}>
                  {deepseekTimeLimit ? '已启用' : '已禁用'}
                </Text>
                <Switch checked={deepseekTimeLimit} onChange={handleToggleDeepseekTimeLimit} />
              </Space>
            </div>
          </Card>
        </section>
      </div>

      {/* 管理对话框 */}
      <ManagementDialog
        open={manageDialog.open}
        onClose={() => setManageDialog({ open: false, category: '', title: '' })}
        category={manageDialog.category}
        title={manageDialog.title}
      />

      <CompareDataModal
        compareModal={compareModal}
        onClose={handleCloseCompareModal}
        onImportSuccess={handleImportSuccess}
      />

      <ImportSectorModal
        open={importModal.open}
        mode={importModal.mode}
        onClose={() => setImportModal(prev => ({ ...prev, open: false }))}
      />
    </ConfigProvider>
  )
}

export default Settings
