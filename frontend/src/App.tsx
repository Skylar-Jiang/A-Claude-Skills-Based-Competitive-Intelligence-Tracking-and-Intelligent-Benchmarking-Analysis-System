import { FormEvent, useEffect, useMemo, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import {
  ArrowRight,
  BookOpenText,
  ChartLineUp,
  ChatCircleText,
  CheckCircle,
  Clock,
  Compass,
  CurrencyDollar,
  Database,
  FileText,
  Fingerprint,
  FlowArrow,
  Globe,
  Lightning,
  ListChecks,
  Megaphone,
  Package,
  Play,
  Pulse,
  Receipt,
  RocketLaunch,
  Scales,
  ShieldCheck,
  SidebarSimple,
  Sparkle,
  Target,
  UploadSimple,
  UsersThree,
  WarningCircle,
  XCircle,
} from '@phosphor-icons/react'
import ReactMarkdown from 'react-markdown'
import { SearchableCombobox } from './SearchableCombobox'
import {
  api,
  type AgentView,
  type AuditResult,
  type EvidenceReference,
  type ReportView,
  type RunStage,
  type RunStatus,
  type WorkflowMetadata,
} from './api'
import { productCategoryOptions, targetMarketOptions } from './catalogOptions'

type PageKey = 'workspace' | 'agents' | 'strategy' | 'evidence' | 'tariff' | 'audit' | 'report'

type MarketingStrategy = {
  positioning?: string
  marketing_objective?: string
  target_segments?: string[]
  value_propositions?: string[]
  pricing_strategy?: string[]
  channel_strategy?: string[]
  messaging_strategy?: string[]
  launch_actions?: string[]
}

type ExecutiveSummary = {
  manual_review_required?: boolean
  evidence_audit_manual_review_required?: boolean
  customs_broker_review_required?: boolean
  evidence_count?: number
  limitation_count?: number
}

type EvidenceIndexItem = {
  display_number?: number
  display_label?: string
  display_title?: string
  evidence_type_label?: string
  support_summary?: string
  detail_path?: string
  evidence_id: string
  knowledge_type?: string
  source_name?: string
  source_uri?: string | null
  excerpt?: string
  data_origin?: string
  metadata?: Record<string, unknown>
}

type TariffEvidence = {
  evidence_id?: string
  summary?: string
  source_name?: string
  source_uri?: string
  effective_date?: string | null
  confidence?: number | null
}

type TariffProfile = {
  hs_code?: string
  product_scope?: string
  general_rate?: string
  special_rate_text?: string
  additional_duty_text?: string
  confidence?: number | null
}

type TariffSnapshot = {
  provider?: string
  market?: string
  jurisdiction?: string
  effective_date?: string | null
  tariff_evidence?: TariffEvidence[]
  data_gaps?: Array<{ field?: string; reason?: string }>
}

type TariffImpact = {
  summary?: string
  risk_flags?: string[]
  manual_review_required?: boolean
  selection_impact?: string[]
  primary_tariff_profile?: TariffProfile
}

type FormState = {
  name: string
  category: string
  description: string
  features: string
  materials: string
  scenarios: string
  audience: string
  targetMarket: string
  targetPrice: string
  currency: string
}

const initialForm: FormState = {
  name: '轻量反光防挣脱犬用胸背带',
  category: '犬用胸背带',
  description: '面向城市遛犬和夜间出行的待上市新品，强调舒适性、安全感与快速调节。',
  features: '反光织带，四点调节，前后双牵引环，透气网布',
  materials: '尼龙织带，聚酯网布，锌合金',
  scenarios: '日常遛犬，夜间出行，基础训练',
  audience: '中小型犬主人，城市养宠家庭',
  targetMarket: '美国跨境电商市场',
  targetPrice: '29.99',
  currency: 'USD',
}

const agentDefinitions = [
  {
    key: 'ProductMarketAgent',
    node: 'product_market_agent',
    name: '商品市场分析',
    short: 'MARKET',
    sequence: 'A01',
    detail: '读取同类商品与 SQL 统计，识别价格基线、结构特征和差异化机会。',
    className: 'agent-white',
    icon: ChartLineUp,
  },
  {
    key: 'UserInsightAgent',
    node: 'user_insight_agent',
    name: '同类用户洞察',
    short: 'INSIGHT',
    sequence: 'A02',
    detail: '从同类商品评论中提炼购买动机、使用痛点与未满足需求。',
    className: 'agent-pink',
    icon: UsersThree,
  },
  {
    key: 'OperationsDecisionAgent',
    node: 'operations_decision_agent',
    name: '运营决策',
    short: 'DECISION',
    sequence: 'A03',
    detail: '汇总市场与用户洞察，生成定位、内容、渠道和执行优先级。',
    className: 'agent-brown',
    icon: Compass,
  },
  {
    key: 'EvidenceAuditAgent',
    node: 'evidence_audit_agent',
    name: '证据审校',
    short: 'AUDIT',
    sequence: 'A04',
    detail: '检查事实、数字、证据引用与假设标签，决定通过或退回修正。',
    className: 'agent-blue',
    icon: ShieldCheck,
  },
] as const

const navigation: Array<{ key: PageKey; label: string; caption: string; icon: typeof Lightning }> = [
  { key: 'workspace', label: '任务创建', caption: '真实商品分析', icon: Lightning },
  { key: 'agents', label: 'Agent 协作', caption: '四角色流程', icon: FlowArrow },
  { key: 'strategy', label: '营销策略', caption: '定位与上市动作', icon: Megaphone },
  { key: 'evidence', label: '证据中心', caption: '来源与原文详情', icon: Fingerprint },
  { key: 'tariff', label: '关税合规', caption: '美国 HTS 证据', icon: Receipt },
  { key: 'audit', label: '证据审校', caption: '风险与护栏', icon: ShieldCheck },
  { key: 'report', label: '决策报告', caption: 'Markdown 输出', icon: FileText },
]

const terminalStatuses: RunStatus[] = ['succeeded', 'failed', 'manual_review']

function pageFromHash(): PageKey {
  const value = window.location.hash.replace('#', '')
  return navigation.some((item) => item.key === value) ? value as PageKey : 'workspace'
}

function splitValues(value: string) {
  return value.split(/[，,\n]/).map((item) => item.trim()).filter(Boolean)
}

function formatDuration(duration: number | null | undefined) {
  if (duration === null || duration === undefined) return '—'
  if (duration < 1000) return `${duration} ms`
  return `${(duration / 1000).toFixed(1)} s`
}

function statusText(status?: string) {
  const labels: Record<string, string> = {
    pending: '待命',
    running: '执行中',
    succeeded: '已完成',
    failed: '失败',
    skipped: '已跳过',
    insufficient_evidence: '证据不足',
    manual_review: '人工复核',
    warning: '有提醒',
    pass: '已通过',
    rejected: '未通过',
  }
  return labels[status || 'pending'] || status || '待命'
}

function statusIcon(status?: string) {
  if (status === 'succeeded' || status === 'pass') return <CheckCircle weight="fill" />
  if (status === 'failed' || status === 'rejected') return <XCircle weight="fill" />
  if (status === 'warning' || status === 'manual_review' || status === 'insufficient_evidence') {
    return <WarningCircle weight="fill" />
  }
  if (status === 'running') return <Pulse weight="bold" />
  return <Clock weight="regular" />
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function asStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

function asEvidenceIndex(value: unknown): EvidenceIndexItem[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is EvidenceIndexItem => {
    const record = asRecord(item)
    return typeof record?.evidence_id === 'string'
  })
}

function tariffSections(report: ReportView | null) {
  const snapshot = asRecord(report?.sections.tax_and_tariff_snapshot) as TariffSnapshot | null
  const impact = asRecord(report?.sections.tariff_selection_impact) as TariffImpact | null
  return { snapshot, impact }
}

function ParticleField() {
  const particles = useMemo(() => Array.from({ length: 22 }, (_, index) => ({
    left: `${(index * 41 + 13) % 97}%`,
    top: `${(index * 67 + 11) % 91}%`,
    delay: `${(index % 7) * -0.73}s`,
    duration: `${5 + (index % 5) * 1.1}s`,
    size: `${2 + (index % 3)}px`,
  })), [])

  return (
    <div className="particle-field" aria-hidden="true">
      <span className="ambient-orb orb-one" />
      <span className="ambient-orb orb-two" />
      {particles.map((particle, index) => (
        <i
          key={index}
          style={{
            '--particle-left': particle.left,
            '--particle-top': particle.top,
            '--particle-delay': particle.delay,
            '--particle-duration': particle.duration,
            '--particle-size': particle.size,
          } as CSSProperties}
        />
      ))}
    </div>
  )
}

function PageHeader({ eyebrow, title, description, action }: {
  eyebrow: string
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <header className="page-header">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action && <div className="page-header-action">{action}</div>}
    </header>
  )
}

function App() {
  const [page, setPage] = useState<PageKey>(pageFromHash)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    const saved = localStorage.getItem('tradepilot-sidebar-collapsed')
    return saved === 'true' || window.innerWidth < 1120
  })
  const [form, setForm] = useState<FormState>(initialForm)
  const [file, setFile] = useState<File | null>(null)
  const [connected, setConnected] = useState<boolean | null>(null)
  const [workflow, setWorkflow] = useState<WorkflowMetadata | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const [runStatus, setRunStatus] = useState<RunStatus | null>(null)
  const [currentNode, setCurrentNode] = useState('')
  const [timeline, setTimeline] = useState<RunStage[]>([])
  const [agents, setAgents] = useState<AgentView[]>([])
  const [audit, setAudit] = useState<AuditResult | null>(null)
  const [evidence, setEvidence] = useState<EvidenceReference[]>([])
  const [selectedEvidence, setSelectedEvidence] = useState<EvidenceReference | null>(null)
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(null)
  const [evidenceBusy, setEvidenceBusy] = useState(false)
  const [evidenceError, setEvidenceError] = useState('')
  const [report, setReport] = useState<ReportView | null>(null)
  const [markdown, setMarkdown] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const onHashChange = () => setPage(pageFromHash())
    window.addEventListener('hashchange', onHashChange)
    if (!window.location.hash) window.history.replaceState(null, '', '#workspace')
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  useEffect(() => {
    localStorage.setItem('tradepilot-sidebar-collapsed', String(sidebarCollapsed))
  }, [sidebarCollapsed])

  useEffect(() => {
    let active = true
    Promise.all([api.health(), api.workflow()])
      .then(([, metadata]) => {
        if (!active) return
        setConnected(true)
        setWorkflow(metadata)
      })
      .catch(() => {
        if (active) setConnected(false)
      })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!runId) return
    let active = true
    let timer: number | undefined

    const poll = async () => {
      try {
        const [status, stages, agentData, auditData] = await Promise.all([
          api.status(runId),
          api.timeline(runId),
          api.agents(runId),
          api.audit(runId),
        ])
        if (!active) return
        setRunStatus(status.status)
        setCurrentNode(status.current_node)
        setTimeline(stages.stages)
        setAgents(agentData.agents)
        setAudit(auditData.audit)

        if (terminalStatuses.includes(status.status)) {
          if (status.report_id) {
            const [reportData, reportMarkdown, evidenceData] = await Promise.all([
              api.report(status.report_id),
              api.markdown(status.report_id),
              api.evidence(runId),
            ])
            if (active) {
              setReport(reportData)
              setMarkdown(reportMarkdown)
              setEvidence(evidenceData.evidence)
            }
          }
          if (status.error?.message) setError(status.error.message)
          return
        }
        timer = window.setTimeout(poll, 1500)
      } catch (pollError) {
        if (!active) return
        setError(pollError instanceof Error ? pollError.message : '状态更新失败，请稍后重试。')
        timer = window.setTimeout(poll, 3000)
      }
    }

    void poll()
    return () => {
      active = false
      if (timer) window.clearTimeout(timer)
    }
  }, [runId])

  const stageMap = useMemo(() => new Map(timeline.map((stage) => [stage.stage_key, stage])), [timeline])
  const runActive = runId !== null && (runStatus === null || !terminalStatuses.includes(runStatus))
  const completedCount = timeline.filter((stage) => stage.status === 'succeeded').length
  const stageCount = workflow?.nodes.length || 8
  const progress = runStatus && terminalStatuses.includes(runStatus)
    ? 100
    : Math.min(96, Math.round((completedCount / stageCount) * 100))
  const auditStatus = audit?.status || (runStatus === 'manual_review' ? 'warning' : 'pending')
  const currentStageName = workflow?.nodes.find((node) => node.node_name === currentNode)?.display_name || currentNode
  const { snapshot: tariffSnapshot, impact: tariffImpact } = tariffSections(report)
  const marketingStrategy = asRecord(report?.sections.launch_marketing_strategy) as MarketingStrategy | null
  const executiveSummary = asRecord(report?.sections.executive_summary) as ExecutiveSummary | null
  const evidenceIndex = asEvidenceIndex(
    report?.sections.evidence_index
      || asRecord(report?.sections.data_limitations_and_evidence_index)?.evidence_index,
  )
  const displayEvidence = evidenceIndex.length ? evidenceIndex : evidence.map((item, index) => ({
    display_number: index + 1,
    display_label: `证据${index + 1}`,
    display_title: item.source_name,
    evidence_type_label: item.knowledge_type === 'review_insight' ? '同类商品真实评论' : '真实资料',
    support_summary: item.excerpt,
    evidence_id: item.evidence_id,
    knowledge_type: item.knowledge_type,
    source_name: item.source_name,
    source_uri: item.source_uri,
    excerpt: item.excerpt,
    data_origin: item.data_origin,
    metadata: item.metadata,
  }))
  const selectedEvidenceIndex = displayEvidence.find((item) => item.evidence_id === selectedEvidenceId)
  const evidenceAuditReviewRequired = executiveSummary?.evidence_audit_manual_review_required
    ?? audit?.manual_review_required
    ?? false
  const customsBrokerReviewRequired = executiveSummary?.customs_broker_review_required ?? false
  const tariffProfile = tariffImpact?.primary_tariff_profile || null
  const tariffEvidence = tariffSnapshot?.tariff_evidence || []
  const tariffGaps = tariffSnapshot?.data_gaps || []

  const navigate = (target: PageKey) => {
    window.location.assign(`#${target}`)
    setPage(target)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const showEvidence = async (evidenceId: string) => {
    if (!runId || evidenceBusy) return
    setSelectedEvidenceId(evidenceId)
    setEvidenceBusy(true)
    setEvidenceError('')
    if (page !== 'evidence') navigate('evidence')
    try {
      const result = await api.evidenceDetail(runId, evidenceId)
      setSelectedEvidence(result.evidence)
    } catch (detailError) {
      setSelectedEvidence(null)
      setEvidenceError(detailError instanceof Error ? detailError.message : '证据详情读取失败。')
    } finally {
      setEvidenceBusy(false)
    }
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (busy || runActive) return
    setBusy(true)
    setError('')
    setRunId(null)
    setRunStatus(null)
    setTimeline([])
    setAgents([])
    setAudit(null)
    setEvidence([])
    setSelectedEvidence(null)
    setSelectedEvidenceId(null)
    setEvidenceError('')
    setReport(null)
    setMarkdown('')

    try {
      const product = await api.createProduct({
        name: form.name.trim(),
        category: form.category.trim(),
        description: form.description.trim(),
        features: splitValues(form.features),
        materials: splitValues(form.materials),
        use_scenarios: splitValues(form.scenarios),
        target_market: form.targetMarket.trim(),
        target_audience: splitValues(form.audience),
        target_price: form.targetPrice ? Number(form.targetPrice) : null,
        target_currency: form.currency,
        known_risks: ['待上市新品，尚无自身销量、评分和评论数据'],
        data_mode: 'real',
      })
      if (file) await api.uploadFile(product.product_id, file)
      const run = await api.startRun(product.product_id, 'real', form.targetMarket.trim())
      setRunId(run.run_id)
      setRunStatus(run.status)
      setCurrentNode(run.current_node)
      navigate('agents')
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : '创建分析任务失败。')
    } finally {
      setBusy(false)
    }
  }

  const renderWorkspace = () => (
    <div className="page-view page-workspace">
      <PageHeader
        eyebrow="REAL COMMERCE INTELLIGENCE"
        title="创建真实分析任务"
        description="输入新品资料，系统将调用真实模型、同类商品数据与四个 Agent 完成决策分析。"
        action={<span className="real-badge"><i /> REAL MODE ONLY</span>}
      />

      <section className="workspace-layout">
        <form className="glass-panel product-form" onSubmit={handleSubmit}>
          <div className="panel-heading">
            <div className="heading-index">01</div>
            <div><h2>商品输入</h2><p>必填项用于匹配同类商品，其他信息可按已知程度补充。</p></div>
            <Package weight="duotone" aria-hidden="true" />
          </div>

          <div className="real-notice">
            <span><Lightning weight="fill" /></span>
            <div><strong>真实模型链路</strong><small>MiniMax-M3 · Qwen Embedding · Qwen3-VL · 同类数据 · 美国 HTS</small></div>
          </div>

          <div className="field-grid two-columns">
            <label>
              <span>商品名称 <b>*</b></span>
              <input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
            </label>
            <SearchableCombobox
              id="product-category"
              label="商品类别"
              required
              value={form.category}
              options={productCategoryOptions}
              placeholder="搜索或输入商品类别"
              helperText="选择常用品类，或输入自定义类别"
              icon={<Package weight="duotone" />}
              onChange={(category) => setForm((current) => ({ ...current, category }))}
            />
          </div>

          <label className="full-field">
            <span>商品描述</span>
            <textarea rows={3} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} />
          </label>

          <label className="full-field">
            <span>核心功能</span>
            <input value={form.features} onChange={(event) => setForm({ ...form, features: event.target.value })} aria-describedby="feature-help" />
            <small id="feature-help">用逗号分隔，例如：反光织带，四点调节，透气网布</small>
          </label>

          <div className="field-grid two-columns">
            <SearchableCombobox
              id="target-market"
              label="目标市场"
              required
              value={form.targetMarket}
              options={targetMarketOptions}
              placeholder="搜索国家、地区或市场"
              helperText="支持中文、英文、国家缩写和自定义市场"
              icon={<Globe weight="duotone" />}
              onChange={(targetMarket) => setForm((current) => ({ ...current, targetMarket }))}
            />
            <label>
              <span>目标售价</span>
              <div className="price-field">
                <input type="number" min="0" step="0.01" value={form.targetPrice} onChange={(event) => setForm({ ...form, targetPrice: event.target.value })} />
                <select aria-label="货币" value={form.currency} onChange={(event) => setForm({ ...form, currency: event.target.value })}>
                  <option>USD</option><option>EUR</option><option>GBP</option><option>JPY</option>
                </select>
              </div>
            </label>
          </div>

          <details className="advanced-fields">
            <summary>补充商品信息</summary>
            <div className="field-grid two-columns">
              <label><span>材料</span><input value={form.materials} onChange={(event) => setForm({ ...form, materials: event.target.value })} /></label>
              <label><span>使用场景</span><input value={form.scenarios} onChange={(event) => setForm({ ...form, scenarios: event.target.value })} /></label>
            </div>
            <label className="full-field"><span>目标人群</span><input value={form.audience} onChange={(event) => setForm({ ...form, audience: event.target.value })} /></label>
          </details>

          <label className="file-drop">
            <UploadSimple weight="bold" aria-hidden="true" />
            <span><strong>{file ? file.name : '添加商品图片或说明文档'}</strong><small>{file ? `${(file.size / 1024).toFixed(1)} KB` : '可选 · PNG、JPG、PDF、DOCX'}</small></span>
            <input type="file" accept="image/png,image/jpeg,application/pdf,.doc,.docx,.txt" onChange={(event) => setFile(event.target.files?.[0] || null)} />
          </label>

          {error && <div className="error-banner" role="alert"><WarningCircle weight="fill" /><span><strong>任务未完成</strong>{error}</span></div>}

          <button className="primary-button" type="submit" disabled={busy || runActive || connected === false}>
            {busy || runActive ? <Pulse className="spin" weight="bold" /> : <Play weight="fill" />}
            {busy ? '正在创建真实任务…' : runActive ? '四个 Agent 执行中…' : '启动真实智能分析'}
            {!busy && !runActive && <ArrowRight weight="bold" />}
          </button>
        </form>

        <aside className="launch-brief glass-panel" aria-label="分析任务说明">
          <div className="brief-visual">
            <div className="radar-rings"><span /><span /><span /></div>
            <img src="/tradepilot-team-logo.png" alt="TradePilot 四位 Agent 团队 Logo" />
          </div>
          <span className="eyebrow">MISSION PROFILE</span>
          <h2>四个 Agent，完成一次可审计决策</h2>
          <p>市场分析与用户洞察并行运行，运营决策汇总信号，证据审校最后把关。</p>
          <ol className="mini-process">
            <li><span>01</span><div><strong>真实数据准备</strong><small>同行匹配 · RAG · SQL · HTS 税则</small></div></li>
            <li><span>02</span><div><strong>双 Agent 并行分析</strong><small>市场 + 用户洞察</small></div></li>
            <li><span>03</span><div><strong>决策与证据审校</strong><small>允许一次审校退回</small></div></li>
          </ol>
          <div className={`connection-card ${connected === false ? 'offline' : ''}`}>
            <i />
            <div><strong>{connected === null ? '正在检查真实链路' : connected ? '真实链路已就绪' : '后端暂未连接'}</strong><small>{connected ? '接口与工作流元数据连接正常' : '请先启动 FastAPI 服务'}</small></div>
          </div>
        </aside>
      </section>
    </div>
  )

  const agentStatus = (definition: typeof agentDefinitions[number]) => {
    const agent = agents.find((item) => item.agent_name === definition.key)
    const stage = stageMap.get(definition.node)
    return { agent, stage, status: agent?.status || stage?.status || 'pending' }
  }

  const renderAgents = () => (
    <div className="page-view page-agents">
      <PageHeader
        eyebrow="LIVE AGENT ORCHESTRATION"
        title="四 Agent 协作流程"
        description="这里展示后端真实执行状态：两路并行洞察汇聚为运营决策，再进入证据审校。"
        action={<span className={`status-pill status-${runStatus || 'pending'}`}>{statusIcon(runStatus || 'pending')}{runStatus ? statusText(runStatus) : '等待任务'}</span>}
      />

      <section className="run-command glass-panel" aria-live="polite">
        <div className="run-identity">
          <span className="signal-icon"><Pulse weight="bold" /></span>
          <div><span className="micro-label">CURRENT RUN</span><strong>{runId ? runId.toUpperCase() : '尚未创建任务'}</strong></div>
        </div>
        <div className="run-stage"><span>当前节点</span><strong>{currentStageName || '等待任务输入'}</strong></div>
        <div className="run-progress">
          <div><span>整体进度</span><strong>{progress}%</strong></div>
          <div className="progress-track" role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}><i style={{ transform: `scaleX(${progress / 100})` }} /></div>
        </div>
        {!runId && <button className="compact-button" onClick={() => navigate('workspace')}><Play weight="fill" /> 创建任务</button>}
      </section>

      <section className="workflow-canvas glass-panel" aria-labelledby="workflow-heading">
        <div className="workflow-title"><div><span className="eyebrow">EXECUTION GRAPH</span><h2 id="workflow-heading">证据驱动的协作链路</h2></div><span className="flow-legend"><i /> 实时数据流</span></div>
        <div className={`agent-flow ${runActive ? 'is-running' : ''}`}>
          <div className={`prep-node status-${stageMap.get('statistics_provider')?.status || 'pending'}`}>
            <span><Database weight="duotone" /></span>
            <div><small>DATA PREP</small><strong>同类数据、RAG 与 HTS 税则准备</strong></div>
            <b>{statusIcon(stageMap.get('statistics_provider')?.status)}</b>
          </div>
          <div className="flow-line line-down"><i /></div>
          <div className="parallel-label"><span />并行执行<span /></div>
          <div className="parallel-agents">
            {agentDefinitions.slice(0, 2).map((definition) => {
              const { agent, status } = agentStatus(definition)
              const Icon = definition.icon
              return (
                <article className={`flow-agent-card ${definition.className} status-${status}`} key={definition.key}>
                  <div className="agent-card-head"><span className="agent-avatar"><Icon weight="bold" /></span><span className={`agent-state status-${status}`}>{statusIcon(status)} {statusText(status)}</span></div>
                  <small>{definition.sequence} · {definition.short}</small>
                  <h3>{definition.name}</h3>
                  <p>{agent?.output_summary || definition.detail}</p>
                  <div className="agent-metrics"><span>耗时 <b>{formatDuration(agent?.duration_ms)}</b></span><span>证据 <b>{agent?.evidence_ids.length || 0}</b></span><span>调用 <b>{agent?.model_call_count || 0}</b></span></div>
                </article>
              )
            })}
          </div>
          <div className="merge-connector"><span /><b>信号汇聚</b><span /></div>
          {agentDefinitions.slice(2).map((definition, index) => {
            const { agent, status } = agentStatus(definition)
            const Icon = definition.icon
            return (
              <div className="serial-step" key={definition.key}>
                <article className={`serial-agent ${definition.className} status-${status}`}>
                  <span className="agent-avatar"><Icon weight="bold" /></span>
                  <div><small>{definition.sequence} · {definition.short}</small><h3>{definition.name}</h3><p>{agent?.output_summary || definition.detail}</p></div>
                  <div className="serial-meta"><span className={`agent-state status-${status}`}>{statusIcon(status)} {statusText(status)}</span><small>{formatDuration(agent?.duration_ms)} · {agent?.evidence_ids.length || 0} 条证据</small></div>
                </article>
                {index === 0 && <div className="flow-line line-down"><i /></div>}
              </div>
            )
          })}
          <div className="flow-line line-down"><i /></div>
          <div className="output-nodes">
            <button className={`report-node status-${report ? 'succeeded' : 'pending'}`} onClick={() => navigate('strategy')}>
              <Megaphone weight="duotone" /><span><small>STRATEGY</small><strong>查看上市营销策略</strong></span><ArrowRight weight="bold" />
            </button>
            <button className={`report-node status-${report ? 'succeeded' : 'pending'}`} onClick={() => navigate('report')}>
              <FileText weight="duotone" /><span><small>REPORT</small><strong>查看 Markdown 决策报告</strong></span><ArrowRight weight="bold" />
            </button>
          </div>
        </div>
      </section>

      <section className="timeline-panel glass-panel">
        <div className="section-title"><div><span className="eyebrow">SYSTEM TIMELINE</span><h2>完整节点时间线</h2></div><span>{completedCount} / {stageCount} 节点完成</span></div>
        <ol className="timeline-grid">
          {(workflow?.nodes || []).map((node) => {
            const stage = stageMap.get(node.node_name)
            const status = stage?.status || 'pending'
            return <li className={`status-${status}`} key={node.node_name}><span>{statusIcon(status)}</span><div><strong>{node.display_name}</strong><small>{node.responsibility}</small></div><time>{formatDuration(stage?.duration_ms)}</time></li>
          })}
        </ol>
        {!workflow && <div className="empty-inline">连接后端后将加载完整工作流。</div>}
      </section>
    </div>
  )

  const renderStrategy = () => {
    const strategyCards = [
      { key: 'segments', label: '目标客群', caption: 'WHO', items: asStringList(marketingStrategy?.target_segments), icon: UsersThree, tone: 'pink' },
      { key: 'value', label: '核心价值主张', caption: 'VALUE', items: asStringList(marketingStrategy?.value_propositions), icon: Sparkle, tone: 'white' },
      { key: 'pricing', label: '定价策略', caption: 'PRICE', items: asStringList(marketingStrategy?.pricing_strategy), icon: CurrencyDollar, tone: 'brown' },
      { key: 'channel', label: '渠道策略', caption: 'CHANNEL', items: asStringList(marketingStrategy?.channel_strategy), icon: Target, tone: 'blue' },
      { key: 'message', label: '传播信息策略', caption: 'MESSAGE', items: asStringList(marketingStrategy?.messaging_strategy), icon: ChatCircleText, tone: 'pink' },
      { key: 'actions', label: '上市执行动作', caption: 'ACTION', items: asStringList(marketingStrategy?.launch_actions), icon: RocketLaunch, tone: 'brown' },
    ]
    const strategyReady = Boolean(
      marketingStrategy?.marketing_objective
      || marketingStrategy?.positioning
      || strategyCards.some((card) => card.items.length),
    )

    return (
      <div className="page-view page-strategy">
        <PageHeader
          eyebrow="LAUNCH MARKETING SYSTEM"
          title="新品上市营销策略"
          description="把同类商品与评论证据转化为可执行的客群、价值、定价、渠道、传播和上市动作。"
          action={<span className={`status-pill ${strategyReady ? 'status-pass' : 'status-pending'}`}>{statusIcon(strategyReady ? 'pass' : 'pending')}{strategyReady ? '策略已生成' : '等待决策 Agent'}</span>}
        />
        {strategyReady ? (
          <>
            <section className="strategy-hero glass-panel">
              <div className="strategy-orbit" aria-hidden="true"><Megaphone weight="duotone" /><i /><i /></div>
              <div className="strategy-hero-copy">
                <span className="eyebrow">MARKETING OBJECTIVE</span>
                <h2>{marketingStrategy?.marketing_objective || '围绕已验证的目标客群与价值主张建立首发认知。'}</h2>
                <div className="positioning-statement"><Compass weight="duotone" /><div><small>市场定位</small><p>{marketingStrategy?.positioning || '当前证据不足，暂未形成明确市场定位。'}</p></div></div>
              </div>
              <div className="strategy-signal"><span>STRATEGY SIGNAL</span><strong>{strategyCards.reduce((total, card) => total + card.items.length, 0)}</strong><small>条证据约束策略</small></div>
            </section>
            <section className="strategy-grid">
              {strategyCards.map((card, index) => {
                const Icon = card.icon
                return (
                  <article className={`glass-panel strategy-card tone-${card.tone}`} key={card.key}>
                    <div className="strategy-card-head"><span><Icon weight="duotone" /></span><small>{String(index + 1).padStart(2, '0')} · {card.caption}</small></div>
                    <h2>{card.label}</h2>
                    {card.items.length ? <ul>{card.items.map((item, itemIndex) => <li key={`${item}-${itemIndex}`}><i />{item}</li>)}</ul> : <p className="strategy-empty">证据或输入不足，暂不生成确定性策略。</p>}
                  </article>
                )
              })}
            </section>
            <section className="strategy-evidence-cta glass-panel"><div><BookOpenText weight="duotone" /><span><strong>策略结论可追溯</strong><small>通过友好编号查看支持每条结论的真实商品、评论和税则资料。</small></span></div><button className="compact-button" onClick={() => navigate('evidence')}>打开证据中心 <ArrowRight weight="bold" /></button></section>
          </>
        ) : (
          <section className="report-placeholder glass-panel">
            <div className="placeholder-orbit"><Megaphone weight="thin" /><span /><span /></div>
            <span className="eyebrow">STRATEGY STANDBY</span>
            <h2>运营决策 Agent 将生成完整营销策略</h2>
            <p>新版策略包含营销目标、市场定位、目标客群、价值主张、定价、渠道、传播信息和上市动作。</p>
            <button className="primary-button compact" onClick={() => navigate(runId ? 'agents' : 'workspace')}>{runId ? '查看 Agent 进度' : '创建分析任务'}<ArrowRight weight="bold" /></button>
          </section>
        )}
      </div>
    )
  }

  const renderEvidence = () => (
    <div className="page-view page-evidence">
      <PageHeader
        eyebrow="TRACEABLE EVIDENCE"
        title="证据中心"
        description="使用面向用户的证据编号浏览真实商品、评论、统计和关税资料；机器 ID 仅保留在详情中用于审计。"
        action={<span className={`status-pill ${displayEvidence.length ? 'status-pass' : 'status-pending'}`}><Fingerprint weight="fill" />{displayEvidence.length} 条证据</span>}
      />
      {displayEvidence.length ? (
        <section className="evidence-workbench">
          <div className="glass-panel evidence-list-panel">
            <div className="section-title"><div><span className="eyebrow">EVIDENCE INDEX</span><h2>报告证据索引</h2></div><span>{displayEvidence.length} ITEMS</span></div>
            <div className="evidence-list">
              {displayEvidence.map((item) => (
                <button
                  className={selectedEvidenceId === item.evidence_id ? 'active' : ''}
                  key={item.evidence_id}
                  onClick={() => void showEvidence(item.evidence_id)}
                  aria-pressed={selectedEvidenceId === item.evidence_id}
                >
                  <span className="evidence-number">{item.display_label || `证据${item.display_number || ''}`}</span>
                  <span className="evidence-list-copy"><strong>{item.display_title || item.source_name || '未命名证据'}</strong><small>{item.evidence_type_label || item.knowledge_type || '真实资料'}</small><p>{item.support_summary || item.excerpt || '点击查看原始证据详情。'}</p></span>
                  <ArrowRight weight="bold" />
                </button>
              ))}
            </div>
          </div>
          <article className="glass-panel evidence-detail-panel" aria-live="polite">
            {evidenceBusy ? <div className="evidence-detail-empty"><Pulse className="spin" weight="bold" /><h2>正在读取原始证据</h2><p>从持久化证据仓库加载完整来源与元数据。</p></div> : evidenceError ? <div className="evidence-detail-empty error"><WarningCircle weight="thin" /><h2>证据读取失败</h2><p>{evidenceError}</p></div> : selectedEvidence ? (
              <>
                <div className="evidence-detail-head"><span><Fingerprint weight="duotone" /></span><div><small>{selectedEvidenceIndex?.display_label || 'EVIDENCE DETAIL'}</small><h2>{selectedEvidenceIndex?.display_title || selectedEvidence.source_name}</h2><p>{selectedEvidenceIndex?.evidence_type_label || selectedEvidence.knowledge_type}</p></div></div>
                <dl className="evidence-detail-meta">
                  <div><dt>数据来源</dt><dd>{selectedEvidence.source_name}</dd></div>
                  <div><dt>知识类型</dt><dd>{selectedEvidence.knowledge_type}</dd></div>
                  <div><dt>数据模式</dt><dd>{selectedEvidence.data_origin.toUpperCase()}</dd></div>
                </dl>
                <div className="evidence-excerpt"><span className="eyebrow">ORIGINAL EVIDENCE</span><p>{selectedEvidence.excerpt || '原始摘录为空。'}</p></div>
                {selectedEvidence.source_uri && (/^https?:\/\//i.test(selectedEvidence.source_uri) ? <a className="evidence-source-link" href={selectedEvidence.source_uri} target="_blank" rel="noreferrer">打开原始来源 <ArrowRight weight="bold" /></a> : <div className="evidence-machine-field"><span>来源位置</span><code>{selectedEvidence.source_uri}</code></div>)}
                <details className="evidence-metadata"><summary>查看机器审计字段</summary><div><span>evidence_id</span><code>{selectedEvidence.evidence_id}</code><span>metadata</span><pre>{JSON.stringify(selectedEvidence.metadata, null, 2)}</pre></div></details>
              </>
            ) : <div className="evidence-detail-empty"><Fingerprint weight="thin" /><h2>选择一条证据</h2><p>左侧使用友好编号展示来源，点击后可查看原始摘录和机器审计字段。</p></div>}
          </article>
        </section>
      ) : (
        <section className="report-placeholder glass-panel"><div className="placeholder-orbit"><Fingerprint weight="thin" /><span /><span /></div><span className="eyebrow">EVIDENCE STANDBY</span><h2>报告生成后会建立证据索引</h2><p>证据中心只展示后端真实持久化的证据，不生成示例数据或模拟来源。</p><button className="primary-button compact" onClick={() => navigate(runId ? 'agents' : 'workspace')}>{runId ? '查看 Agent 进度' : '创建分析任务'}<ArrowRight weight="bold" /></button></section>
      )}
    </div>
  )

  const renderAudit = () => (
    <div className="page-view page-audit">
      <PageHeader
        eyebrow="EVIDENCE GOVERNANCE"
        title="证据审校中心"
        description="区分证据审校与报关归类两类复核：前者决定结论可信度，后者是正式进口前的业务合规门禁。"
        action={<span className={`status-pill status-${auditStatus}`}>{statusIcon(auditStatus)}{statusText(auditStatus)}</span>}
      />
      <section className="audit-layout">
        <div className="audit-verdict-card glass-panel">
          <div className={`verdict-symbol audit-${auditStatus}`}>{statusIcon(auditStatus)}</div>
          <span className="eyebrow">AUDIT VERDICT</span>
          <h2>{statusText(auditStatus)}</h2>
          <p>{audit ? (evidenceAuditReviewRequired ? '证据审校发现需要人工确认的问题，请结合问题清单修正结论。' : '证据审校已经完成；报关复核状态会在下方单独展示。') : '完成四个 Agent 的真实分析后，这里会展示审校结论。'}</p>
          <dl>
            <div><dt>问题</dt><dd>{audit?.issues.length || 0}</dd></div>
            <div><dt>冲突证据</dt><dd>{audit?.conflicting_evidence_ids.length || 0}</dd></div>
            <div><dt>未决事项</dt><dd>{audit?.unresolved_questions.length || 0}</dd></div>
          </dl>
        </div>
        <div className="audit-list-card glass-panel">
          <div className="section-title"><div><span className="eyebrow">REVIEW FINDINGS</span><h2>审校问题与建议</h2></div><ListChecks weight="duotone" /></div>
          {audit?.issues.length ? <ul className="audit-issues">{audit.issues.map((issue, index) => <li key={`${issue}-${index}`}><span>{String(index + 1).padStart(2, '0')}</span><p>{issue}</p></li>)}</ul> : <div className="empty-state"><ShieldCheck weight="thin" /><h3>{audit ? '没有发现审校问题' : '等待审校结果'}</h3><p>{audit ? '当前证据链未触发问题项。' : '先创建真实分析任务，审校 Agent 会在决策完成后运行。'}</p></div>}
        </div>
      </section>
      <section className="review-boundary-grid" aria-label="人工复核边界">
        <article className={`glass-panel review-boundary-card ${evidenceAuditReviewRequired ? 'requires-review' : 'cleared'}`}><span><ShieldCheck weight="duotone" /></span><div><small>EVIDENCE AUDIT</small><h2>证据审校复核</h2><p>检查事实范围、数字、引用和假设标签，影响报告结论是否可用。</p></div><strong>{evidenceAuditReviewRequired ? '需要复核' : audit ? '已完成' : '待审校'}</strong></article>
        <article className={`glass-panel review-boundary-card ${customsBrokerReviewRequired ? 'requires-review' : 'cleared'}`}><span><Scales weight="duotone" /></span><div><small>CUSTOMS CLASSIFICATION</small><h2>报关归类复核</h2><p>候选 HTS 和税率用于前期测算，正式进口前仍需报关行确认。</p></div><strong>{customsBrokerReviewRequired ? '需要复核' : report ? '无需额外复核' : '等待税则'}</strong></article>
      </section>
      <section className="guardrail-panel glass-panel">
        <div className="section-title"><div><span className="eyebrow">DECISION GUARDRAILS</span><h2>四条决策护栏</h2></div><Database weight="duotone" /></div>
        <div className="guardrail-grid">
          <article><span>01</span><h3>新品不是同类商品</h3><p>不把同行评论与历史表现归因到待上市新品。</p></article>
          <article><span>02</span><h3>数字必须有来源</h3><p>销量、评分、价格与比例必须能够追溯。</p></article>
          <article><span>03</span><h3>假设必须被标记</h3><p>属性推导仅作为上市前待验证事项处理。</p></article>
          <article><span>04</span><h3>证据范围可审计</h3><p>关键结论绑定有效 evidence ID 与数据范围。</p></article>
        </div>
      </section>
    </div>
  )

  const renderTariff = () => (
    <div className="page-view page-tariff">
      <PageHeader
        eyebrow="TARIFF & LANDED COST"
        title="美国关税与选品影响"
        description="基于最新 main 分支的本地 HTS 税则数据，展示候选税号、税率证据以及对 landed cost 和毛利的影响。"
        action={<span className={`status-pill ${tariffImpact?.manual_review_required ? 'status-warning' : tariffSnapshot ? 'status-pass' : 'status-pending'}`}>
          {statusIcon(tariffImpact?.manual_review_required ? 'warning' : tariffSnapshot ? 'pass' : 'pending')}
          {tariffImpact?.manual_review_required ? '需人工归类复核' : tariffSnapshot ? '税则证据已载入' : '等待美国市场任务'}
        </span>}
      />

      {tariffSnapshot || tariffImpact ? (
        <>
          <section className="tariff-metrics" aria-label="关税关键指标">
            <article className="glass-panel tariff-metric primary">
              <span><Receipt weight="duotone" /></span>
              <div><small>CANDIDATE HTS</small><strong>{tariffProfile?.hs_code || '待确定'}</strong><p>{tariffProfile?.product_scope || '尚未形成可用的税号匹配。'}</p></div>
            </article>
            <article className="glass-panel tariff-metric">
              <span><Scales weight="duotone" /></span>
              <div><small>GENERAL RATE</small><strong>{tariffProfile?.general_rate || '未知'}</strong><p>{tariffProfile?.additional_duty_text ? '存在附加税文本，请纳入到岸成本。' : '未识别到附加税文本。'}</p></div>
            </article>
            <article className="glass-panel tariff-metric">
              <span><ShieldCheck weight="duotone" /></span>
              <div><small>MAPPING CONFIDENCE</small><strong>{typeof tariffProfile?.confidence === 'number' ? `${Math.round(tariffProfile.confidence * 100)}%` : '未知'}</strong><p>候选归类仅用于选品前测算，不替代报关行正式意见。</p></div>
            </article>
          </section>

          <section className="tariff-grid">
            <div className="glass-panel tariff-impact-card">
              <div className="section-title"><div><span className="eyebrow">SELECTION IMPACT</span><h2>对选品与定价的影响</h2></div><ChartLineUp weight="duotone" /></div>
              {tariffImpact?.summary && <p className="tariff-summary">{tariffImpact.summary}</p>}
              {tariffImpact?.selection_impact?.length ? (
                <ol className="impact-list">{tariffImpact.selection_impact.map((item, index) => <li key={`${item}-${index}`}><span>{String(index + 1).padStart(2, '0')}</span><p>{item}</p></li>)}</ol>
              ) : <div className="empty-inline">当前没有可用的税费选品影响。</div>}
              {!!tariffImpact?.risk_flags?.length && <div className="risk-tags" aria-label="风险标记">{tariffImpact.risk_flags.map((flag) => <span key={flag}><WarningCircle weight="fill" />{flag.replaceAll('_', ' ')}</span>)}</div>}
            </div>

            <div className="glass-panel tariff-evidence-card">
              <div className="section-title"><div><span className="eyebrow">SOURCE EVIDENCE</span><h2>税则证据链</h2></div><Database weight="duotone" /></div>
              <dl className="tariff-source-meta">
                <div><dt>提供器</dt><dd>{tariffSnapshot?.provider || '未提供'}</dd></div>
                <div><dt>法域</dt><dd>{tariffSnapshot?.jurisdiction || '未提供'}</dd></div>
                <div><dt>生效日期</dt><dd>{tariffSnapshot?.effective_date || tariffEvidence[0]?.effective_date || '未提供'}</dd></div>
              </dl>
              {tariffEvidence.length ? <ul className="tariff-evidence-list">{tariffEvidence.map((item, index) => (
                <li key={item.evidence_id || index}>
                  <div><code>{item.evidence_id || `EVIDENCE-${index + 1}`}</code>{typeof item.confidence === 'number' && <span>{Math.round(item.confidence * 100)}% confidence</span>}</div>
                  <p>{item.summary}</p>
                  <small>{item.source_name || '未知来源'}</small>
                </li>
              ))}</ul> : <div className="empty-inline">本次报告未包含可展示的税则证据。</div>}
            </div>
          </section>

          {!!tariffGaps.length && <section className="glass-panel tariff-gaps" role="status"><WarningCircle weight="fill" /><div><strong>税则数据缺口</strong>{tariffGaps.map((gap, index) => <p key={`${gap.field}-${index}`}>{gap.field || '相关数据'}：{gap.reason || '需要补充证据。'}</p>)}</div></section>}
        </>
      ) : (
        <section className="tariff-placeholder glass-panel">
          <div className="placeholder-orbit"><Receipt weight="thin" /><span /><span /></div>
          <span className="eyebrow">HTS DATA STANDBY</span>
          <h2>运行一次美国市场真实分析</h2>
          <p>系统会自动请求 <code>us-tariff-provider</code>，并把税号、税率、附加税文本和风险标记传给运营决策 Agent。</p>
          <button className="primary-button compact" onClick={() => navigate(runId ? 'agents' : 'workspace')}>{runId ? '查看 Agent 进度' : '创建美国市场任务'}<ArrowRight weight="bold" /></button>
        </section>
      )}
    </div>
  )

  const renderReport = () => (
    <div className="page-view page-report">
      <PageHeader
        eyebrow="DECISION DOCUMENT"
        title="上市分析报告"
        description="四个 Agent 完成协作与审校后，系统在这里呈现可继续编辑和交付的 Markdown 报告。"
        action={report ? <span className={`status-pill status-${report.audit_status}`}>{statusIcon(report.audit_status)}版本 {report.version} · {statusText(report.audit_status)}</span> : undefined}
      />
      {markdown ? (
        <section className="report-shell glass-panel">
          <div className="report-toolbar"><div><span>REPORT ID</span><strong>{report?.report_id.toUpperCase()}</strong></div><div><span>审校状态</span><strong>{statusText(report?.audit_status)}</strong></div><div><span>格式</span><strong>MARKDOWN</strong></div></div>
          <article className="report-paper"><ReactMarkdown
            skipHtml
            components={{
              a: ({ href, children }) => {
                const match = href?.match(/\/analysis-runs\/[^/]+\/evidence\/(.+)$/)
                if (match) {
                  return <a href="#evidence" onClick={(event) => { event.preventDefault(); void showEvidence(decodeURIComponent(match[1])) }}>{children}</a>
                }
                return <a href={href} target="_blank" rel="noreferrer">{children}</a>
              },
            }}
          >{markdown}</ReactMarkdown></article>
          {report?.disclaimer && <div className="report-disclaimer"><WarningCircle weight="fill" /><span>{report.disclaimer}</span></div>}
        </section>
      ) : (
        <section className="report-placeholder glass-panel">
          <div className="placeholder-orbit"><FileText weight="thin" /><span /><span /></div>
          <span className="eyebrow">REPORT STANDBY</span>
          <h2>报告会在审校完成后生成</h2>
          <p>报告包含商品概况、同类市场、用户洞察、上市营销策略、美国关税影响和友好编号证据索引。</p>
          <button className="primary-button compact" onClick={() => navigate(runId ? 'agents' : 'workspace')}>{runId ? '查看 Agent 进度' : '创建分析任务'}<ArrowRight weight="bold" /></button>
        </section>
      )}
    </div>
  )

  return (
    <>
      <a className="skip-link" href="#main-content">跳到主要内容</a>
      <div className={`app-shell ${sidebarCollapsed ? 'sidebar-is-collapsed' : ''}`}>
        <ParticleField />
        <aside className="sidebar" aria-label="主导航">
          <div className="sidebar-top">
            <a className="brand" href="#workspace" aria-label="TradePilot 任务创建页">
              <span className="brand-logo-frame"><img src="/tradepilot-team-logo.png" alt="" /></span>
              <span className="brand-copy"><strong>TradePilot</strong><small>AI COMMERCE CREW</small></span>
            </a>
            <button className="sidebar-toggle" onClick={() => setSidebarCollapsed((value) => !value)} aria-label={sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'} aria-expanded={!sidebarCollapsed}><SidebarSimple weight="bold" /></button>
          </div>

          <nav className="sidebar-nav">
            <span className="nav-caption">WORKSPACE</span>
            {navigation.map((item) => {
              const Icon = item.icon
              return <a key={item.key} className={page === item.key ? 'active' : ''} href={`#${item.key}`} title={sidebarCollapsed ? item.label : undefined}><Icon weight={page === item.key ? 'fill' : 'regular'} /><span><strong>{item.label}</strong><small>{item.caption}</small></span>{page === item.key && <i />}</a>
            })}
          </nav>

          <div className="sidebar-foot">
            <div className={`connection ${connected === false ? 'offline' : ''}`}><span className="connection-dot" /><div><strong>{connected === null ? '正在连接' : connected ? '系统在线' : '等待后端'}</strong><small>{connected ? 'Real 工作流已就绪' : '启动服务后即可分析'}</small></div></div>
            <span className="build-label">REAL · EVIDENCE FIRST</span>
          </div>
        </aside>

        <main id="main-content" className="main-content">
          <header className="topbar">
            <button className="mobile-sidebar-toggle" onClick={() => setSidebarCollapsed((value) => !value)} aria-label={sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'}><SidebarSimple weight="bold" /></button>
            <div className="breadcrumb"><span>TRADEPILOT</span><b>/</b><strong>{navigation.find((item) => item.key === page)?.label}</strong></div>
            <div className="topbar-actions"><span className="real-badge"><i /> REAL</span><span className={`system-state ${connected === false ? 'offline' : ''}`}><i />{connected ? 'API ONLINE' : connected === false ? 'API OFFLINE' : 'CONNECTING'}</span></div>
          </header>
          <div className="content-stage">
            {page === 'workspace' && renderWorkspace()}
            {page === 'agents' && renderAgents()}
            {page === 'strategy' && renderStrategy()}
            {page === 'evidence' && renderEvidence()}
            {page === 'tariff' && renderTariff()}
            {page === 'audit' && renderAudit()}
            {page === 'report' && renderReport()}
          </div>
          <footer><div><strong>TradePilot</strong><span>基于多智能体的跨境商品智能运营决策助手</span></div><span>证据优先 · 过程透明 · 人机共决策</span></footer>
        </main>
      </div>
    </>
  )
}

export default App
