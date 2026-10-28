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
  AppstoreOutlined,
  FundOutlined
} from '@ant-design/icons'
import zhCN from 'antd/locale/zh_CN'
import { factorApi, taskApi } from '../api'
import ManagementDialog from '../components/ManagementDialog'
import { useTaskCenter } from '../contexts/TaskCenter'
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
  const { activeTasks, startTask } = useTaskCenter()
  // 任务状态由全局任务中心派生（切页面/刷新不丢）
  const repairing = activeTasks.some(t => t.kind === 'repair-names' || /名称修复/.test(t.name || ''))
  const [repairingLocal, setRepairingLocal] = useState(false)

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
    if (repairing || repairingLocal) return
    setRepairingLocal(true)
    try {
      const res = await factorApi.repairStockNames()
      const taskId = res?.task_id
      if (!taskId) {
        message.error('启动名称修复失败')
        return
      }
      startTask(taskId, { title: '名称修复', kind: 'repair-names', message: '正在修复股票名称...' })
    } catch (e) {
      message.error(e?.response?.data?.detail || '名称修复启动失败')
    } finally {
      setRepairingLocal(false)
    }
  }

  // 对比数据（任务模式，进度由全局任务中心驱动）
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

      const taskId = res.task_id
      startTask(taskId, {
        title: type === 'stock' ? '数据对比：个股' : '数据对比：板块',
        kind: 'compare',
        message: '启动中...',
        onProgress: (st) => setCompareModal(prev => ({
          ...prev,
          taskStep: st.message || st.current_stock_name || '处理中...',
        })),
        onDone: async () => {
          try {
            const st = await factorApi.compareStatus(taskId)
            setCompareModal({ open: true, type, data: st?.result, loading: false, taskStep: null })
          } catch (e) {
            message.error('获取对比结果失败')
            setCompareModal({ open: false, type: '', data: null, loading: false })
          }
        },
        onFailed: (st) => {
          message.error('对比任务失败: ' + (st.error || '未知错误'))
          setCompareModal({ open: false, type: '', data: null, loading: false })
        },
      })
    } catch (e) {
      console.error('启动对比任务失败:', e)
      message.error('启动对比任务失败')
      setCompareModal({ open: false, type: '', data: null, loading: false })
    }
  }

  // 关闭弹窗（任务仍在全局任务中心继续，进度可从顶栏查看）
  const handleCloseCompareModal = () => {
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
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
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
            <EntityCard
              icon={<FundOutlined className="text-orange-600 text-xl" />}
              iconBg="#ffedd5"
              title="ETF"
              description="查看 ETF 列表与二阶段状态"
              onManage={() => openManage('etf', '管理ETF')}
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
                  loading={repairing || repairingLocal}
                  disabled={repairing || repairingLocal}
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
                <Text className="text-sm font-medium">DeepSeek API 空闲时段限制</Text>
                <Text type="secondary" className="text-xs block">高峰时段（工作日 9:00-12:00、14:00-18:00）不可用；其余时间含周末与法定节假日全天可用。关闭后不限时</Text>
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
