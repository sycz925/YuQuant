import React, { useState, useEffect, useRef } from 'react'
import { Input, Button, Card, Spin, Empty, Tag, Typography, message, Popconfirm, Tabs, Modal, FloatButton, Drawer, Tooltip, Alert } from 'antd'
import { SearchOutlined, ReloadOutlined, ApartmentOutlined, ArrowUpOutlined, DeleteOutlined, SwapOutlined, PlusOutlined, StarOutlined, BulbOutlined, CopyOutlined, ImportOutlined } from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { industryMapApi, watchlistApi } from '../api'
import useTaskPolling from '../hooks/useTaskPolling'

const { Text, Paragraph, Title } = Typography

// 生成给 DeepSeek 的产业分析提示文案
function buildDeepseekPrompt(keyword) {
  const kw = (keyword || '').trim()
  return `请帮我深度分析「${kw}」产业的 A 股产业链，输出结构化结果，要求：

一、产业链分层（必须分为 上游 / 中游 / 下游 三个阶段）
- 上游：原材料、核心零部件、设备、EDA/IP 等
- 中游：制造、封装、集成、平台等
- 下游：应用、终端、渠道、服务等

二、每个阶段下按大类组织，大类下再拆 2-5 个垂直分类

三、每个垂直分类列出 2-6 家 A 股上市公司，包含：
- 股票名称与 6 位代码
- 市场地位（如：龙头 / 第二梯队 / 细分龙头 / 新进入者）
- 市占率（若可查）
- 核心产品（1-2 个）
- 重要客户或大牌伙伴（若可查）

四、额外要求
1. 只收录 A 股上市公司（沪深主板、创业板、科创板、北交所均可）
2. 股票代码必须准确，不确定的宁可不写
3. 产业链逻辑要符合产业实际，不要为了凑数硬塞公司
4. 用 JSON 格式输出，schema 如下：

{
  "industry": "产业名称",
  "overview": "150字以内的产业概况",
  "chain": [
    {
      "stage": "上游",
      "summary": "本阶段概述",
      "categories": [
        {
          "name": "大类名称",
          "subcategories": [
            {
              "name": "垂直分类名称",
              "companies": [
                {
                  "name": "公司名称",
                  "stock_code": "600000",
                  "market_position": "龙头",
                  "market_share": "30%",
                  "key_products": "核心产品",
                  "key_partners": "重要伙伴"
                }
              ]
            }
          ]
        }
      ]
    }
  ]
}

请直接输出 JSON，不要输出其他内容。`
}

// 上游 / 中游 / 下游 的阶段配色（色条 + Tag 一致）
const STAGE_THEME = {
  上游: { bar: 'bg-green-500', tag: 'green' },
  中游: { bar: 'bg-blue-500', tag: 'blue' },
  下游: { bar: 'bg-orange-500', tag: 'orange' },
}

function RpsBadge({ label, value }) {
  if (value == null) return null
  const tone = value >= 90
    ? 'bg-red-50 text-red-600 border-red-200'
    : value >= 80
      ? 'bg-orange-50 text-orange-600 border-orange-200'
      : value <= 20
        ? 'bg-green-50 text-green-600 border-green-200'
        : 'bg-slate-50 text-slate-600 border-slate-200'
  return (
    <span className={`inline-flex items-baseline gap-1 px-2 py-0.5 rounded-md border ${tone}`}>
      <span className="text-[10px] text-gray-400 font-medium">{label}</span>
      <span className="text-xs font-semibold tabular-nums">{value}</span>
    </span>
  )
}

function CompanyCard({ company, navigate, onWatch }) {
  const hasCode = Boolean(company.stock_code)
  const goStock = () => {
    if (hasCode) {
      navigate(`/search?code=${company.stock_code}&name=${encodeURIComponent(company.name)}`)
    } else {
      navigate(`/search?keyword=${encodeURIComponent(company.name)}`)
    }
  }
  return (
    <Card
      size="small"
      className="h-full transition-shadow hover:shadow-md"
      styles={{ body: { padding: '12px 14px' } }}
    >
      <div className="flex items-start justify-between gap-1 mb-1.5">
        <span
          onClick={goStock}
          title={hasCode ? `查看 ${company.name}（${company.stock_code}）` : `搜索 ${company.name}`}
          className={`font-semibold leading-tight ${hasCode ? 'text-blue-700 cursor-pointer hover:underline' : 'text-gray-800'}`}
        >
          {company.name}
          {hasCode && <span className="text-xs text-gray-400 font-normal ml-1">{company.stock_code}</span>}
        </span>
        {company.market_position && (
          <Tag color="geekblue" style={{ marginInlineEnd: 0 }}>{company.market_position}</Tag>
        )}
      </div>
      {(company.rps_10 != null || company.rps_50 != null || company.rps_120 != null) && (
        <div className="flex items-center gap-1.5 flex-wrap mb-2">
          <RpsBadge label="RPS10" value={company.rps_10} />
          <RpsBadge label="RPS50" value={company.rps_50} />
          <RpsBadge label="RPS120" value={company.rps_120} />
        </div>
      )}
      <div className="text-xs space-y-1 leading-relaxed">
        {company.market_share && (
          <div><span className="text-gray-400 mr-1">市占率</span>{company.market_share}</div>
        )}
        {company.key_products && (
          <div><span className="text-gray-400 mr-1">重要产品</span>{company.key_products}</div>
        )}
        {company.key_partners && (
          <div><span className="text-gray-400 mr-1">大牌伙伴</span>{company.key_partners}</div>
        )}
      </div>
      {onWatch && company.stock_code && (
        <div className="mt-2 pt-2 border-t border-gray-100 text-right">
          <Button size="small" type="link" icon={<StarOutlined />} onClick={() => onWatch(company)}>
            加入关注
          </Button>
        </div>
      )}
    </Card>
  )
}

function StageSection({ stage, navigate, onWatch }) {
  const theme = STAGE_THEME[stage.stage] || { bar: 'bg-gray-400', tag: 'default' }
  const categories = stage.categories || []

  return (
    <section className="mb-8">
      {/* 阶段标题 */}
      <div className="flex items-center gap-2 mb-2">
        <span className={`w-1.5 h-6 rounded ${theme.bar}`} />
        <Title level={4} style={{ margin: 0 }}>{stage.stage}</Title>
        <Tag color={theme.tag} className="ml-1">{categories.length} 大类</Tag>
      </div>
      {stage.summary && <Paragraph type="secondary" className="mb-4">{stage.summary}</Paragraph>}

      {/* 大类 → 垂直分类 → 公司，全平铺 */}
      {categories.length === 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无数据" />}
      {categories.map(category => {
        const subs = category.subcategories || []
        return (
          <div key={category.name} className="mb-5">
            <div className="flex items-baseline gap-2 mb-2 pl-2 border-l-2 border-gray-200">
              <span className="font-semibold text-gray-800">{category.name}</span>
              <span className="text-xs text-gray-400">{subs.length} 个垂直分类</span>
            </div>
            {subs.map(sub => {
              const companies = sub.companies || []
              return (
                <div key={sub.name} className="mb-3 pl-4">
                  <div className="flex items-center gap-1.5 mb-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-gray-300" />
                    <span className="text-sm font-medium text-gray-600">{sub.name}</span>
                    <span className="text-xs text-gray-400">{companies.length} 家</span>
                  </div>
                  {companies.length > 0 ? (
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                      {companies.map(c => (
                        <CompanyCard key={c.name} company={c} navigate={navigate} onWatch={onWatch} />
                      ))}
                    </div>
                  ) : (
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无公司数据" />
                  )}
                </div>
              )
            })}
          </div>
        )
      })}
    </section>
  )
}

function IndustryMap() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [history, setHistory] = useState([])
  const [taskId, setTaskId] = useState(null)
  const [searchOpen, setSearchOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [importText, setImportText] = useState('')
  const [importKeyword, setImportKeyword] = useState('')
  const [importing, setImporting] = useState(false)
  const [compareList, setCompareList] = useState(() => {
    try {
      const saved = localStorage.getItem('industry_map_compare')
      return saved ? JSON.parse(saved) : []
    } catch {
      return []
    }
  })
  const [compareOpen, setCompareOpen] = useState(false)
  const [intersectResult, setIntersectResult] = useState(null)
  const [intersectLoading, setIntersectLoading] = useState(false)
  const [deepseekAvailable, setDeepseekAvailable] = useState(true)
  const [deepseekMsg, setDeepseekMsg] = useState('')
  const [promptModalOpen, setPromptModalOpen] = useState(false)
  const keywordRef = useRef('')

  // 加载历史记录
  useEffect(() => {
    industryMapApi.getHistory()
      .then(res => setHistory(res?.data || []))
      .catch(() => {})
  }, [])

  // 轮询 DeepSeek 时间窗口状态（用于禁用查询/更新按钮）
  useEffect(() => {
    const check = () => {
      industryMapApi.deepseekAvailable()
        .then(res => {
          setDeepseekAvailable(res?.available ?? true)
          setDeepseekMsg(res?.message || '')
        })
        .catch(() => setDeepseekAvailable(true))
    }
    check()
    const timer = setInterval(check, 30000)
    return () => clearInterval(timer)
  }, [])

  // 对比列表持久化到 localStorage（刷新不清理）
  useEffect(() => {
    try {
      localStorage.setItem('industry_map_compare', JSON.stringify(compareList))
    } catch { /* 忽略 */ }
  }, [compareList])

  const fetchMap = async (refresh, kwOverride) => {
    const kw = (kwOverride ?? keyword).trim()
    if (!kw) {
      message.warning('请输入产业关键字')
      return
    }
    if (kwOverride) setKeyword(kwOverride)
    keywordRef.current = kw
    setSearchParams({ keyword: kw }, { replace: true })
    setLoading(true)
    setError('')
    setData(null)
    try {
      const res = await industryMapApi.generate(kw, refresh)
      if (res.cached) {
        setData(res.data)
        setLoading(false)
      } else {
        setTaskId(res.task_id)
      }
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || '生成失败，请稍后重试')
      setLoading(false)
    }
  }

  const handleDelete = async () => {
    try {
      await industryMapApi.remove(keywordRef.current)
      message.success('已删除')
      setData(null)
      setTaskId(null)
      setSearchParams({}, { replace: true })
      const res = await industryMapApi.getHistory()
      setHistory(res?.data || [])
    } catch (e) {
      message.error(e?.response?.data?.detail || '删除失败')
    }
  }

  const handleImportJson = async () => {
    const text = importText.trim()
    if (!text) {
      message.warning('请粘贴产业链 JSON 文本')
      return
    }
    setImporting(true)
    try {
      const res = await industryMapApi.importJson(text, importKeyword.trim() || undefined)
      const imported = res?.data
      const kw = imported?.keyword || imported?.industry || ''
      message.success(`已导入「${kw || '产业链'}」`)
      setImportOpen(false)
      setImportText('')
      setImportKeyword('')
      if (imported) {
        setData(imported)
        setKeyword(kw)
        keywordRef.current = kw
        setTaskId(null)
        setError('')
        if (kw) setSearchParams({ keyword: kw }, { replace: true })
      }
      const his = await industryMapApi.getHistory()
      setHistory(his?.data || [])
    } catch (e) {
      message.error(e?.response?.data?.detail || '导入失败，请检查 JSON 格式')
    } finally {
      setImporting(false)
    }
  }

  const currentKeyword = () => (data?.keyword || keyword).trim()

  const handleAddToCompare = () => {
    const kw = currentKeyword()
    if (!kw) return
    setCompareList(prev => prev.includes(kw) ? prev : [...prev, kw])
    message.success(`已加入对比：${kw}`)
  }

  const handleRemoveFromCompare = (kw) => {
    setCompareList(prev => prev.filter(k => k !== kw))
  }

  const handleIntersect = async () => {
    if (compareList.length < 2) {
      message.warning('至少选择 2 个产业')
      return
    }
    setIntersectLoading(true)
    setIntersectResult(null)
    try {
      const res = await industryMapApi.intersect(compareList)
      setIntersectResult(res?.data || [])
    } catch (e) {
      message.error(e?.response?.data?.detail || '生成交集失败')
    } finally {
      setIntersectLoading(false)
    }
  }

  const handleAddWatch = async (company) => {
    if (!company?.stock_code) return
    try {
      await watchlistApi.add(company.stock_code)
      message.success(`已加入关注：${company.name}`)
    } catch (e) {
      if (e?.response?.status === 409) {
        message.info('已在关注列表中')
      } else {
        message.error(e?.response?.data?.detail || '加入关注失败')
      }
    }
  }

  const handleShowPrompt = () => {
    const kw = keyword.trim()
    if (!kw) {
      message.warning('请输入产业关键字后再生成提示语')
      return
    }
    setPromptModalOpen(true)
  }

  const handleCopyPrompt = async () => {
    const text = buildDeepseekPrompt(keyword.trim())
    try {
      await navigator.clipboard.writeText(text)
      message.success('提示文案已复制，去 DeepSeek 粘贴即可')
    } catch {
      // 兼容非 https 环境
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      message.success('提示文案已复制，去 DeepSeek 粘贴即可')
    }
  }

  // 挂载时从 URL 参数恢复（返回本页时还原之前查询结果）
  useEffect(() => {
    const kwFromUrl = searchParams.get('keyword')
    if (kwFromUrl && kwFromUrl.trim()) {
      fetchMap(false, kwFromUrl.trim())
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 任务轮询：完成后取缓存结果
  useTaskPolling(taskId, {
    interval: 3000,
    onComplete: async () => {
      try {
        const res = await industryMapApi.getCached(keywordRef.current)
        setData(res?.data)
      } catch (e) { /* 忽略 */ }
      setLoading(false)
      setTaskId(null)
    },
    onFailed: (taskStatus) => {
      setError(taskStatus?.error || '生成失败，请稍后重试')
      setLoading(false)
      setTaskId(null)
    },
  })

  const chain = data?.chain || []

  return (
    <div className="space-y-4">
      {/* 悬浮图标组：导入 + 搜索 + 产业对比 */}
      <FloatButton.Group>
        <FloatButton
          icon={<ImportOutlined />}
          onClick={() => setImportOpen(true)}
          tooltip="导入 JSON"
        />
        <FloatButton
          type="primary"
          icon={<SearchOutlined />}
          onClick={() => setSearchOpen(true)}
          tooltip="搜索产业"
        />
        <FloatButton
          icon={<SwapOutlined />}
          badge={compareList.length > 0 ? { count: compareList.length } : undefined}
          onClick={() => setCompareOpen(true)}
          tooltip="产业对比"
        />
      </FloatButton.Group>

      {/* 搜索弹窗 */}
      <Modal
        title="搜索产业"
        open={searchOpen}
        onCancel={() => setSearchOpen(false)}
        footer={null}
        width={480}
      >
        <div className="flex items-center gap-2">
          <Input
            size="large"
            autoFocus
            prefix={<ApartmentOutlined className="text-gray-400" />}
            value={keyword}
            onChange={e => setKeyword(e.target.value)}
            onPressEnter={() => { fetchMap(false); setSearchOpen(false) }}
            placeholder="输入产业关键字，如：国产CPU、创新药、光伏、半导体…"
            allowClear
          />
          <Tooltip title={!deepseekAvailable ? deepseekMsg : undefined}>
            <Button type="primary" size="large" icon={<SearchOutlined />} loading={loading} disabled={!deepseekAvailable} onClick={() => { fetchMap(false); setSearchOpen(false) }}>
              查询
            </Button>
          </Tooltip>
          <Tooltip title="生成给 DeepSeek 的提示文案，复制后自行前往 DeepSeek 搜索">
            <Button size="large" icon={<BulbOutlined />} onClick={handleShowPrompt}>
              提示语
            </Button>
          </Tooltip>
        </div>
      </Modal>

      {/* 导入 JSON 弹窗 */}
      <Modal
        title="导入产业链 JSON"
        open={importOpen}
        onCancel={() => setImportOpen(false)}
        footer={null}
        width={680}
      >
        <div className="space-y-3">
          <Input
            prefix={<ApartmentOutlined className="text-gray-400" />}
            value={importKeyword}
            onChange={e => setImportKeyword(e.target.value)}
            placeholder="产业关键字（可留空，默认取 JSON 里的 industry 字段）"
            allowClear
          />
          <Input.TextArea
            value={importText}
            onChange={e => setImportText(e.target.value)}
            placeholder='在此粘贴产业链 JSON，结构：{"industry":"产业名","overview":"概览","chain":[{"stage":"上游","summary":"...","categories":[{"name":"大类","subcategories":[{"name":"细分","companies":[{"name":"公司名","market_share":"...","market_position":"...","key_products":"...","key_partners":"..."}]}]}]}]}'
            rows={14}
            style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 12 }}
          />
          <Alert
            type="info"
            showIcon
            message="导入后自动匹配个股代码与最新 RPS"
            description="层级需为 stage → categories → subcategories → companies；公司名会自动匹配 stock_basics 回填股票代码，缺失字段自动补空。"
          />
          <div className="flex justify-end gap-2">
            <Button onClick={() => setImportOpen(false)}>取消</Button>
            <Button type="primary" icon={<ImportOutlined />} loading={importing} onClick={handleImportJson}>
              导入
            </Button>
          </div>
        </div>
      </Modal>

      {/* 主内容：历史 tab 与产业链内容衔接 */}
      <Card>
        {history.length > 0 && (
          <Tabs
            type="card"
            size="small"
            activeKey={data?.keyword || keyword || undefined}
            onChange={(key) => fetchMap(false, key)}
            items={history.slice(0, 20).map(h => ({
              key: h.keyword,
              label: h.industry || h.keyword,
            }))}
            className="mb-4 industry-history-tabs"
          />
        )}

        {/* 加载中（生成中） */}
        {loading && (
          <div className="flex flex-col items-center justify-center py-20 gap-3">
            <Spin size="large" />
            <Text type="secondary">正在生成产业链图谱（约 30-60 秒，可离开本页稍后回查）…</Text>
          </div>
        )}

        {/* 错误 */}
        {!loading && error && <Empty description={error} />}

        {/* 结果：单页纵向平铺，无需点击展开 */}
        {!loading && !error && data && (
          <div>
            <div className="flex items-start justify-between gap-4 mb-4">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <Title level={3} style={{ margin: 0 }}>{data.industry || keyword}</Title>
                  {data.generated_at && <Text type="secondary" className="text-xs">{data.generated_at}</Text>}
                </div>
                {data.overview && <Paragraph className="mt-2 mb-0">{data.overview}</Paragraph>}
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <Button size="small" icon={<PlusOutlined />} onClick={handleAddToCompare}>
                  加入对比
                </Button>
                <Popconfirm
                  title="重新生成？"
                  description="将重新调用 DeepSeek，耗时约 30-60 秒"
                  onConfirm={() => fetchMap(true)}
                  okText="确认更新"
                  cancelText="取消"
                  disabled={!deepseekAvailable}
                >
                  <Button icon={<ReloadOutlined />} size="small" disabled={!deepseekAvailable} title={!deepseekAvailable ? deepseekMsg : undefined}>更新</Button>
                </Popconfirm>
                <Popconfirm
                  title="删除该产业地图？"
                  description="删除后需重新生成"
                  onConfirm={handleDelete}
                  okText="确认删除"
                  cancelText="取消"
                  okButtonProps={{ danger: true }}
                >
                  <Button icon={<DeleteOutlined />} danger size="small">删除</Button>
                </Popconfirm>
              </div>
            </div>

            {chain.length > 0 ? (
              chain.map(stage => (
                <StageSection key={stage.stage} stage={stage} navigate={navigate} onWatch={handleAddWatch} />
              ))
            ) : (
              <Empty description="未解析出产业链结构" />
            )}

            {/* 回到顶部 */}
            <div className="text-center mt-2">
              <Button
                type="text"
                size="small"
                icon={<ArrowUpOutlined />}
                onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
              >
                回到顶部
              </Button>
            </div>
          </div>
        )}

        {/* 初始空态 */}
        {!loading && !error && !data && (
          <Empty description="点击右下角搜索图标，查询产业链上游/中游/下游生态图谱" />
        )}
      </Card>

      {/* 产业对比面板 */}
      <Drawer
        title="产业对比"
        open={compareOpen}
        onClose={() => setCompareOpen(false)}
        width={1000}
      >
        <div className="mb-4">
          <div className="text-sm font-medium text-gray-700 mb-2">已选产业（{compareList.length}）</div>
          {compareList.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {compareList.map(kw => (
                <Tag key={kw} closable onClose={() => handleRemoveFromCompare(kw)}>{kw}</Tag>
              ))}
            </div>
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未添加产业，在产业地图标题栏点「加入对比」" />
          )}
        </div>

        <Button
          type="primary"
          block
          icon={<SwapOutlined />}
          loading={intersectLoading}
          disabled={compareList.length < 2}
          onClick={handleIntersect}
        >
          生成交集
        </Button>

        {intersectResult && intersectResult.length > 0 && (
          <div className="mt-4">
            <div className="text-sm font-medium text-gray-700 mb-2">交集个股（{intersectResult.length}）</div>
            <div className="grid grid-cols-3 gap-2">
              {intersectResult.map(item => (
                <div key={item.stock_code || item.name}>
                  <CompanyCard company={item} navigate={navigate} onWatch={handleAddWatch} />
                  <div className="text-[10px] text-gray-400 px-1 mt-1 leading-relaxed">
                    {(item.matched_in || []).map(m => `${m.keyword}·${m.subcategory}`).join(' ｜ ')}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
        {intersectResult && intersectResult.length === 0 && (
          <div className="mt-4">
            <Empty description="没有同时存在于这些产业的个股" />
          </div>
        )}
      </Drawer>

      {/* DeepSeek 提示文案弹窗 */}
      <Modal
        title={
          <span>
            <BulbOutlined className="mr-2 text-yellow-500" />
            DeepSeek 提示文案：{keyword.trim()}
          </span>
        }
        open={promptModalOpen}
        onCancel={() => setPromptModalOpen(false)}
        width={720}
        footer={[
          <Button key="copy" type="primary" icon={<CopyOutlined />} onClick={handleCopyPrompt}>
            复制文案
          </Button>,
          <Button key="close" onClick={() => setPromptModalOpen(false)}>
            关闭
          </Button>,
        ]}
      >
        <Alert
          type="info"
          showIcon
          className="mb-3"
          message="使用方法：点击「复制文案」→ 打开 DeepSeek → 粘贴发送 → 将返回的 JSON 用于后续导入"
        />
        <div className="relative">
          <pre
            className="max-h-[420px] overflow-auto bg-gray-50 border border-gray-200 rounded-lg p-4 text-xs leading-relaxed whitespace-pre-wrap break-words select-text"
          >
            {buildDeepseekPrompt(keyword.trim())}
          </pre>
        </div>
      </Modal>
    </div>
  )
}

export default IndustryMap
