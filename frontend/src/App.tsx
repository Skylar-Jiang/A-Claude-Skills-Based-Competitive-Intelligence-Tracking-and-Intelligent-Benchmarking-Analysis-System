import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import {
  ArrowRight,
  Archive,
  ArrowsClockwise,
  BookOpenText,
  CaretRight,
  ChartLineUp,
  ChatCircleText,
  CheckCircle,
  Clock,
  ClockCounterClockwise,
  Compass,
  CurrencyDollar,
  Database,
  FileText,
  Fingerprint,
  Globe,
  Headset,
  Lightning,
  ListChecks,
  MagnifyingGlass,
  Megaphone,
  Package,
  PaperPlaneTilt,
  Play,
  Pulse,
  Receipt,
  RocketLaunch,
  Robot,
  Scales,
  ShieldCheck,
  SidebarSimple,
  Sparkle,
  Target,
  UploadSimple,
  UsersThree,
  WarningCircle,
  X,
  XCircle,
} from '@phosphor-icons/react'
import ReactMarkdown from 'react-markdown'
import { SearchableCombobox } from './SearchableCombobox'
import {
  api,
  type AgentView,
  type AuditResult,
  type CustomerServiceConversationMessage,
  type CustomerServiceMessageResponse,
  type CustomerServicePersonality,
  type EvidenceReference,
  type ReportHistoryItem,
  type ReportVersionSummary,
  type ReportView,
  type RunStage,
  type RunStatus,
  type WorkflowMetadata,
} from './api'
import { productCategoryOptions, targetMarketOptions } from './catalogOptions'

type PageKey = 'workspace' | 'agents' | 'decision' | 'audit'
type DecisionSection = 'strategy' | 'report'
type AuditSection = 'audit' | 'tariff' | 'evidence'

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

const navigation: Array<{ key: PageKey; label: string; caption: string; icon: typeof Lightning; agent: string }> = [
  { key: 'workspace', label: '商品市场', caption: '任务创建 · 白', icon: ChartLineUp, agent: 'A01' },
  { key: 'agents', label: '用户洞察', caption: '协作流程 · 粉', icon: UsersThree, agent: 'A02' },
  { key: 'decision', label: '运营决策', caption: '策略报告 · 棕', icon: Compass, agent: 'A03' },
  { key: 'audit', label: '历史文档', caption: '版本协作 · 蓝', icon: Archive, agent: 'A04' },
]

const legacyPageAliases: Record<string, PageKey> = {
  strategy: 'decision',
  report: 'decision',
  evidence: 'audit',
  tariff: 'audit',
}

const personalityOptions: Array<{
  value: CustomerServicePersonality
  label: string
  caption: string
}> = [
  { value: 'simple', label: '简洁', caption: '直接给结论' },
  { value: 'professional', label: '专业', caption: '严谨解释' },
  { value: 'companion', label: '陪伴', caption: '温和协作' },
  { value: 'innovative', label: '创新', caption: '启发式表达' },
]

const terminalStatuses: RunStatus[] = ['succeeded', 'failed', 'manual_review']

function pageFromHash(): PageKey {
  const value = window.location.hash.replace('#', '')
  if (legacyPageAliases[value]) return legacyPageAliases[value]
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

function formatHistoryDate(value: string) {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '时间未知'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(parsed)
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

function customerActionText(action?: string) {
  const labels: Record<string, string> = {
    explain: '解释当前方案',
    targeted_regeneration: '已生成增量版本',
    positioning_edit: '已调整产品定位',
    marketing_copy_edit: '已调整营销表达',
    promotion_strategy_edit: '已调整推广策略',
    clarification_required: '需要补充信息',
    reject: '已守住证据边界',
  }
  return labels[action || ''] || action || '等待对话'
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
  const particles = useMemo(() => Array.from({ length: 30 }, (_, index) => ({
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
      <span className="motion-orbit motion-orbit-one" />
      <span className="motion-orbit motion-orbit-two" />
      <span className="motion-beam" />
      <span className="motion-scanline" />
      <span className="pixel-sky pixel-sky-far" />
      <span className="pixel-sky pixel-sky-near" />
      <span className="pixel-ground" />
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

function PageHeader({ title, description, action }: {
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action && <div className="page-header-action">{action}</div>}
    </header>
  )
}

function App() {
  const [page, setPage] = useState<PageKey>(pageFromHash)
  const [themeFrom, setThemeFrom] = useState<PageKey>(pageFromHash)
  const [themeTo, setThemeTo] = useState<PageKey>(pageFromHash)
  const [themeTransitioning, setThemeTransitioning] = useState(false)
  const pageRef = useRef(page)
  const themeFrameRef = useRef<number | null>(null)
  const themeTimerRef = useRef<number | null>(null)
  const [decisionSection, setDecisionSection] = useState<DecisionSection>(() => (
    window.location.hash === '#strategy' ? 'strategy' : 'report'
  ))
  const [auditSection, setAuditSection] = useState<AuditSection>(() => {
    if (window.location.hash === '#tariff') return 'tariff'
    if (window.location.hash === '#evidence') return 'evidence'
    return 'audit'
  })
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
  const [reportHistory, setReportHistory] = useState<ReportHistoryItem[]>([])
  const [historyVersions, setHistoryVersions] = useState<ReportVersionSummary[]>([])
  const [activeHistoryRunId, setActiveHistoryRunId] = useState<string | null>(null)
  const [selectedVersionReportId, setSelectedVersionReportId] = useState<string | null>(null)
  const [historySearch, setHistorySearch] = useState('')
  const [historyBusy, setHistoryBusy] = useState(false)
  const [historyError, setHistoryError] = useState('')
  const [archiveOpen, setArchiveOpen] = useState(false)
  const [assistantOpen, setAssistantOpen] = useState(false)
  const [personality, setPersonality] = useState<CustomerServicePersonality>('professional')
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [customerMessages, setCustomerMessages] = useState<CustomerServiceConversationMessage[]>([])
  const [customerInput, setCustomerInput] = useState('')
  const [customerBusy, setCustomerBusy] = useState(false)
  const [customerError, setCustomerError] = useState('')
  const [customerResult, setCustomerResult] = useState<CustomerServiceMessageResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const startPageTransition = useCallback((nextPage: PageKey) => {
    const currentPage = pageRef.current
    if (currentPage === nextPage) {
      setPage(nextPage)
      setThemeTo(nextPage)
      return
    }
    if (themeFrameRef.current !== null) window.cancelAnimationFrame(themeFrameRef.current)
    if (themeTimerRef.current !== null) window.clearTimeout(themeTimerRef.current)
    setThemeFrom(currentPage)
    setThemeTo(nextPage)
    setThemeTransitioning(false)
    pageRef.current = nextPage
    setPage(nextPage)
    themeFrameRef.current = window.requestAnimationFrame(() => {
      themeFrameRef.current = window.requestAnimationFrame(() => {
        themeFrameRef.current = null
        setThemeTransitioning(true)
        themeTimerRef.current = window.setTimeout(() => {
          setThemeFrom(nextPage)
          setThemeTransitioning(false)
          themeTimerRef.current = null
        }, 760)
      })
    })
  }, [])

  useEffect(() => {
    const onHashChange = () => {
      const hash = window.location.hash.replace('#', '')
      startPageTransition(pageFromHash())
      if (hash === 'strategy' || hash === 'report') setDecisionSection(hash)
      if (hash === 'evidence' || hash === 'tariff' || hash === 'audit') setAuditSection(hash)
    }
    window.addEventListener('hashchange', onHashChange)
    if (!window.location.hash) window.history.replaceState(null, '', '#workspace')
    return () => {
      window.removeEventListener('hashchange', onHashChange)
      if (themeFrameRef.current !== null) window.cancelAnimationFrame(themeFrameRef.current)
      if (themeTimerRef.current !== null) window.clearTimeout(themeTimerRef.current)
    }
  }, [startPageTransition])

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

  const loadHistoryVersion = useCallback(async (reportId: string, resetConversation = false) => {
    const [reportData, reportMarkdown] = await Promise.all([
      api.report(reportId),
      api.markdown(reportId),
    ])
    setReport(reportData)
    setMarkdown(reportMarkdown)
    setSelectedVersionReportId(reportId)
    if (resetConversation) {
      setConversationId(null)
      setCustomerMessages([])
      setCustomerResult(null)
      setCustomerError('')
    }
  }, [])

  const refreshReportHistory = useCallback(async (
    preferredReportId?: string,
    resetConversation = false,
  ) => {
    setHistoryBusy(true)
    setHistoryError('')
    try {
      const historyData = await api.reportHistory()
      setReportHistory(historyData.reports)
      if (!historyData.reports.length) {
        setHistoryVersions([])
        setActiveHistoryRunId(null)
        setSelectedVersionReportId(null)
        return
      }
      const storedReportId = preferredReportId || localStorage.getItem('tradepilot-last-report-id') || ''
      const selectedFamily = historyData.reports.find((item) => item.report_id === storedReportId)
        || historyData.reports[0]
      localStorage.setItem('tradepilot-last-report-id', selectedFamily.report_id)
      setActiveHistoryRunId(selectedFamily.run_id)
      const versionData = await api.reportVersions(selectedFamily.report_id)
      setHistoryVersions(versionData.versions)
      const preferredVersion = versionData.versions.find((item) => item.report_id === preferredReportId)
      const latestVersion = versionData.versions[versionData.versions.length - 1]
      await loadHistoryVersion((preferredVersion || latestVersion).report_id, resetConversation)
    } catch (historyLoadError) {
      setHistoryError(historyLoadError instanceof Error ? historyLoadError.message : '历史文档读取失败。')
    } finally {
      setHistoryBusy(false)
    }
  }, [loadHistoryVersion])

  useEffect(() => {
    if (page !== 'audit') return undefined
    const timer = window.setTimeout(() => void refreshReportHistory(), 0)
    return () => window.clearTimeout(timer)
  }, [page, refreshReportHistory])

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
              localStorage.setItem('tradepilot-last-report-id', reportData.report_id)
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
  const filteredReportHistory = useMemo(() => {
    const query = historySearch.trim().toLocaleLowerCase('zh-CN')
    if (!query) return reportHistory
    return reportHistory.filter((item) => [
      item.product_name,
      item.product_category,
      item.report_id,
      item.run_id,
    ].some((value) => value.toLocaleLowerCase('zh-CN').includes(query)))
  }, [historySearch, reportHistory])
  const activeHistoryItem = reportHistory.find((item) => item.run_id === activeHistoryRunId) || null
  const selectedHistoryVersion = historyVersions.find((item) => item.report_id === selectedVersionReportId) || null
  const selectedVersionIsLatest = !!activeHistoryItem
    && activeHistoryItem.report_id === selectedVersionReportId

  const navigate = (target: PageKey) => {
    if (window.location.hash !== `#${target}`) {
      window.history.pushState(null, '', `#${target}`)
    }
    startPageTransition(target)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const openDecision = (section: DecisionSection) => {
    setDecisionSection(section)
    navigate('decision')
  }

  const openAudit = (section: AuditSection) => {
    setAuditSection(section)
    setArchiveOpen(true)
    navigate('audit')
  }

  const showEvidence = async (evidenceId: string) => {
    if (!runId || evidenceBusy) return
    setSelectedEvidenceId(evidenceId)
    setEvidenceBusy(true)
    setEvidenceError('')
    if (page !== 'audit' || auditSection !== 'evidence') openAudit('evidence')
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

  const selectHistoryFamily = async (item: ReportHistoryItem) => {
    if (historyBusy || item.run_id === activeHistoryRunId) return
    localStorage.setItem('tradepilot-last-report-id', item.report_id)
    await refreshReportHistory(item.report_id, true)
  }

  const selectHistoryVersion = async (reportId: string) => {
    if (historyBusy || reportId === selectedVersionReportId) return
    setHistoryBusy(true)
    setHistoryError('')
    try {
      await loadHistoryVersion(reportId, true)
    } catch (versionError) {
      setHistoryError(versionError instanceof Error ? versionError.message : '报告版本读取失败。')
    } finally {
      setHistoryBusy(false)
    }
  }

  const refreshCustomerConversation = async (reportId: string, nextConversationId: string) => {
    const conversation = await api.customerServiceConversation(reportId, nextConversationId)
    setConversationId(conversation.conversation_id)
    setPersonality(conversation.personality)
    setCustomerMessages(conversation.messages)
  }

  const handleCustomerMessage = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const message = customerInput.trim()
    if (!report || !message || customerBusy) return
    if (page === 'audit' && !selectedVersionIsLatest) {
      setCustomerError('历史版本为只读快照，请先切回最新版本再继续修改。')
      return
    }
    setCustomerBusy(true)
    setCustomerError('')
    setCustomerInput('')
    setCustomerMessages((current) => [
      ...current,
      { message_id: `optimistic-${Date.now()}`, role: 'user', content: message, metadata: {} },
    ])
    try {
      const result = await api.customerServiceMessage(report.report_id, {
        conversation_id: conversationId,
        message,
        personality,
      })
      setCustomerResult(result)
      localStorage.setItem('tradepilot-last-report-id', result.report_id)
      await Promise.all([
        refreshCustomerConversation(result.report_id, result.conversation_id),
        refreshReportHistory(result.report_id),
      ])
    } catch (customerServiceError) {
      setCustomerError(customerServiceError instanceof Error ? customerServiceError.message : '客服 Agent 暂时无法响应。')
      setCustomerMessages((current) => current.filter((item) => !item.message_id.startsWith('optimistic-')))
      setCustomerInput(message)
    } finally {
      setCustomerBusy(false)
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
    setAssistantOpen(false)
    setConversationId(null)
    setCustomerMessages([])
    setCustomerInput('')
    setCustomerError('')
    setCustomerResult(null)

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
        title="商品市场与任务创建"
        description="填写待上市商品和目标市场信息，系统将匹配同类商品并生成跨境运营分析。"
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
            <div><strong>基于真实资料分析</strong><small>分析将参考同类商品、用户评论和目标市场税则资料。</small></div>
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
          <h2>填写商品信息，创建跨境运营分析</h2>
          <p>本页面用于提交待上市商品与目标市场信息。填写得越完整，系统匹配的同类商品和生成的运营建议就越准确。</p>
          <ol className="mini-process">
            <li><span>01</span><div><strong>描述待上市商品</strong><small>填写名称、类别、功能特点与使用场景</small></div></li>
            <li><span>02</span><div><strong>确定目标市场</strong><small>选择销售国家、目标售价并按需上传资料</small></div></li>
            <li><span>03</span><div><strong>启动智能分析</strong><small>系统将生成市场洞察、运营策略与可审校报告</small></div></li>
          </ol>
          <div className={`connection-card ${connected === false ? 'offline' : ''}`}>
            <i />
            <div><strong>{connected === null ? '正在连接系统' : connected ? '系统已经就绪' : '系统暂未连接'}</strong><small>{connected ? '现在可以创建商品分析任务。' : '请稍后重试或联系管理员。'}</small></div>
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
        title="用户洞察与分析进度"
        description="查看市场分析、用户需求、运营建议和证据审校的实时进度与结果。"
        action={<span className={`status-pill status-${runStatus || 'pending'}`}>{statusIcon(runStatus || 'pending')}{runStatus ? statusText(runStatus) : '等待任务'}</span>}
      />

      <section className="run-command glass-panel" aria-live="polite">
        <div className="run-identity">
          <span className="signal-icon"><Pulse weight="bold" /></span>
          <div><strong>{runId ? `分析任务 ${runId.toUpperCase()}` : '尚未创建分析任务'}</strong></div>
        </div>
        <div className="run-stage"><span>当前节点</span><strong>{currentStageName || '等待任务输入'}</strong></div>
        <div className="run-progress">
          <div><span>整体进度</span><strong>{progress}%</strong></div>
          <div className="progress-track" role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}><i style={{ transform: `scaleX(${progress / 100})` }} /></div>
        </div>
        {!runId && <button className="compact-button" onClick={() => navigate('workspace')}><Play weight="fill" /> 创建任务</button>}
      </section>

      <section className="workflow-canvas glass-panel" aria-labelledby="workflow-heading">
        <div className="workflow-title"><div><h2 id="workflow-heading">分析处理流程</h2></div><span className="flow-legend"><i /> 实时更新</span></div>
        <div className={`agent-flow ${runActive ? 'is-running' : ''}`}>
          <div className={`prep-node status-${stageMap.get('statistics_provider')?.status || 'pending'}`}>
            <span><Database weight="duotone" /></span>
            <div><strong>正在准备同类商品、用户评论和税则资料</strong></div>
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
                  <div><h3>{definition.name}</h3><p>{agent?.output_summary || definition.detail}</p></div>
                  <div className="serial-meta"><span className={`agent-state status-${status}`}>{statusIcon(status)} {statusText(status)}</span><small>{formatDuration(agent?.duration_ms)} · {agent?.evidence_ids.length || 0} 条证据</small></div>
                </article>
                {index === 0 && <div className="flow-line line-down"><i /></div>}
              </div>
            )
          })}
          <div className="flow-line line-down"><i /></div>
          <div className="output-nodes">
            <button className={`report-node status-${report ? 'succeeded' : 'pending'}`} onClick={() => openDecision('strategy')}>
              <Megaphone weight="duotone" /><span><strong>查看上市营销策略</strong></span><ArrowRight weight="bold" />
            </button>
            <button className={`report-node status-${report ? 'succeeded' : 'pending'}`} onClick={() => openDecision('report')}>
              <FileText weight="duotone" /><span><strong>查看完整分析报告</strong></span><ArrowRight weight="bold" />
            </button>
          </div>
        </div>
      </section>

      <section className="timeline-panel glass-panel">
        <div className="section-title"><div><h2>分析任务时间线</h2></div><span>{completedCount} / {stageCount} 项完成</span></div>
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
          title="新品上市营销策略"
          description="把同类商品与评论证据转化为可执行的客群、价值、定价、渠道、传播和上市动作。"
          action={<span className={`status-pill ${strategyReady ? 'status-pass' : 'status-pending'}`}>{statusIcon(strategyReady ? 'pass' : 'pending')}{strategyReady ? '策略已生成' : '等待决策 Agent'}</span>}
        />
        {strategyReady ? (
          <>
            <section className="strategy-hero glass-panel">
              <div className="strategy-orbit" aria-hidden="true"><Megaphone weight="duotone" /><i /><i /></div>
              <div className="strategy-hero-copy">
                <h2>{marketingStrategy?.marketing_objective || '围绕已验证的目标客群与价值主张建立首发认知。'}</h2>
                <div className="positioning-statement"><Compass weight="duotone" /><div><small>市场定位</small><p>{marketingStrategy?.positioning || '当前证据不足，暂未形成明确市场定位。'}</p></div></div>
              </div>
              <div className="strategy-signal"><span>策略建议</span><strong>{strategyCards.reduce((total, card) => total + card.items.length, 0)}</strong><small>条</small></div>
            </section>
            <section className="strategy-grid">
              {strategyCards.map((card, index) => {
                const Icon = card.icon
                return (
                  <article className={`glass-panel strategy-card tone-${card.tone}`} key={card.key}>
                    <div className="strategy-card-head"><span><Icon weight="duotone" /></span><small>{String(index + 1).padStart(2, '0')}</small></div>
                    <h2>{card.label}</h2>
                    {card.items.length ? <ul>{card.items.map((item, itemIndex) => <li key={`${item}-${itemIndex}`}><i />{item}</li>)}</ul> : <p className="strategy-empty">证据或输入不足，暂不生成确定性策略。</p>}
                  </article>
                )
              })}
            </section>
            <section className="strategy-evidence-cta glass-panel"><div><BookOpenText weight="duotone" /><span><strong>策略结论可追溯</strong><small>通过友好编号查看支持每条结论的真实商品、评论和税则资料。</small></span></div><button className="compact-button" onClick={() => openAudit('evidence')}>打开证据中心 <ArrowRight weight="bold" /></button></section>
          </>
        ) : (
          <section className="report-placeholder glass-panel">
            <div className="placeholder-orbit"><Megaphone weight="thin" /><span /><span /></div>
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
        title="证据中心"
        description="使用面向用户的证据编号浏览真实商品、评论、统计和关税资料；机器 ID 仅保留在详情中用于审计。"
        action={<span className={`status-pill ${displayEvidence.length ? 'status-pass' : 'status-pending'}`}><Fingerprint weight="fill" />{displayEvidence.length} 条证据</span>}
      />
      {displayEvidence.length ? (
        <section className="evidence-workbench">
          <div className="glass-panel evidence-list-panel">
            <div className="section-title"><div><h2>报告证据索引</h2></div><span>{displayEvidence.length} 条</span></div>
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
                <div className="evidence-detail-head"><span><Fingerprint weight="duotone" /></span><div><h2>{selectedEvidenceIndex?.display_title || selectedEvidence.source_name}</h2><p>{selectedEvidenceIndex?.evidence_type_label || selectedEvidence.knowledge_type}</p></div></div>
                <dl className="evidence-detail-meta">
                  <div><dt>数据来源</dt><dd>{selectedEvidence.source_name}</dd></div>
                  <div><dt>知识类型</dt><dd>{selectedEvidence.knowledge_type}</dd></div>
                  <div><dt>数据模式</dt><dd>{selectedEvidence.data_origin.toUpperCase()}</dd></div>
                </dl>
                <div className="evidence-excerpt"><strong>原始资料摘录</strong><p>{selectedEvidence.excerpt || '原始摘录为空。'}</p></div>
                {selectedEvidence.source_uri && (/^https?:\/\//i.test(selectedEvidence.source_uri) ? <a className="evidence-source-link" href={selectedEvidence.source_uri} target="_blank" rel="noreferrer">打开原始来源 <ArrowRight weight="bold" /></a> : <div className="evidence-machine-field"><span>来源位置</span><code>{selectedEvidence.source_uri}</code></div>)}
              </>
            ) : <div className="evidence-detail-empty"><Fingerprint weight="thin" /><h2>选择一条证据</h2><p>左侧使用友好编号展示来源，点击后可查看原始摘录和机器审计字段。</p></div>}
          </article>
        </section>
      ) : (
        <section className="report-placeholder glass-panel"><div className="placeholder-orbit"><Fingerprint weight="thin" /><span /><span /></div><h2>报告生成后会建立证据索引</h2><p>这里将展示支持分析结论的商品、评论和税则资料。</p><button className="primary-button compact" onClick={() => navigate(runId ? 'agents' : 'workspace')}>{runId ? '查看分析进度' : '创建分析任务'}<ArrowRight weight="bold" /></button></section>
      )}
    </div>
  )

  const renderAudit = () => (
    <div className="page-view page-audit">
      <PageHeader
        title="证据审校中心"
        description="区分证据审校与报关归类两类复核：前者决定结论可信度，后者是正式进口前的业务合规门禁。"
        action={<span className={`status-pill status-${auditStatus}`}>{statusIcon(auditStatus)}{statusText(auditStatus)}</span>}
      />
      <section className="audit-layout">
        <div className="audit-verdict-card glass-panel">
          <div className={`verdict-symbol audit-${auditStatus}`}>{statusIcon(auditStatus)}</div>
          <h2>{statusText(auditStatus)}</h2>
          <p>{audit ? (evidenceAuditReviewRequired ? '证据审校发现需要人工确认的问题，请结合问题清单修正结论。' : '证据审校已经完成；报关复核状态会在下方单独展示。') : '完成四个 Agent 的真实分析后，这里会展示审校结论。'}</p>
          <dl>
            <div><dt>问题</dt><dd>{audit?.issues.length || 0}</dd></div>
            <div><dt>冲突证据</dt><dd>{audit?.conflicting_evidence_ids.length || 0}</dd></div>
            <div><dt>未决事项</dt><dd>{audit?.unresolved_questions.length || 0}</dd></div>
          </dl>
        </div>
        <div className="audit-list-card glass-panel">
          <div className="section-title"><div><h2>审校问题与建议</h2></div><ListChecks weight="duotone" /></div>
          {audit?.issues.length ? <ul className="audit-issues">{audit.issues.map((issue, index) => <li key={`${issue}-${index}`}><span>{String(index + 1).padStart(2, '0')}</span><p>{issue}</p></li>)}</ul> : <div className="empty-state"><ShieldCheck weight="thin" /><h3>{audit ? '没有发现审校问题' : '等待审校结果'}</h3><p>{audit ? '当前证据链未触发问题项。' : '先创建真实分析任务，审校 Agent 会在决策完成后运行。'}</p></div>}
        </div>
      </section>
      <section className="review-boundary-grid" aria-label="人工复核边界">
        <article className={`glass-panel review-boundary-card ${evidenceAuditReviewRequired ? 'requires-review' : 'cleared'}`}><span><ShieldCheck weight="duotone" /></span><div><h2>证据审校复核</h2><p>检查事实、数字、引用和假设，判断报告结论是否可靠。</p></div><strong>{evidenceAuditReviewRequired ? '需要复核' : audit ? '已完成' : '待审校'}</strong></article>
        <article className={`glass-panel review-boundary-card ${customsBrokerReviewRequired ? 'requires-review' : 'cleared'}`}><span><Scales weight="duotone" /></span><div><h2>报关归类复核</h2><p>候选税号和税率用于前期测算，正式进口前仍需报关行确认。</p></div><strong>{customsBrokerReviewRequired ? '需要复核' : report ? '无需额外复核' : '等待税则'}</strong></article>
      </section>
      <section className="guardrail-panel glass-panel">
        <div className="section-title"><div><h2>报告可靠性检查</h2></div><Database weight="duotone" /></div>
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
        title="美国关税与选品影响"
        description="展示候选税号、税率依据，以及关税对到岸成本和毛利的影响。"
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
              <div><small>候选税号</small><strong>{tariffProfile?.hs_code || '待确定'}</strong><p>{tariffProfile?.product_scope || '尚未形成可用的税号匹配。'}</p></div>
            </article>
            <article className="glass-panel tariff-metric">
              <span><Scales weight="duotone" /></span>
              <div><small>一般税率</small><strong>{tariffProfile?.general_rate || '未知'}</strong><p>{tariffProfile?.additional_duty_text ? '存在附加税，请纳入到岸成本。' : '未识别到附加税。'}</p></div>
            </article>
            <article className="glass-panel tariff-metric">
              <span><ShieldCheck weight="duotone" /></span>
              <div><small>归类可信度</small><strong>{typeof tariffProfile?.confidence === 'number' ? `${Math.round(tariffProfile.confidence * 100)}%` : '未知'}</strong><p>候选归类仅用于选品前测算，不替代报关行正式意见。</p></div>
            </article>
          </section>

          <section className="tariff-grid">
            <div className="glass-panel tariff-impact-card">
              <div className="section-title"><div><h2>对选品与定价的影响</h2></div><ChartLineUp weight="duotone" /></div>
              {tariffImpact?.summary && <p className="tariff-summary">{tariffImpact.summary}</p>}
              {tariffImpact?.selection_impact?.length ? (
                <ol className="impact-list">{tariffImpact.selection_impact.map((item, index) => <li key={`${item}-${index}`}><span>{String(index + 1).padStart(2, '0')}</span><p>{item}</p></li>)}</ol>
              ) : <div className="empty-inline">当前没有可用的税费选品影响。</div>}
              {!!tariffImpact?.risk_flags?.length && <div className="risk-tags" aria-label="风险标记">{tariffImpact.risk_flags.map((flag) => <span key={flag}><WarningCircle weight="fill" />{flag.replaceAll('_', ' ')}</span>)}</div>}
            </div>

            <div className="glass-panel tariff-evidence-card">
              <div className="section-title"><div><h2>税则依据</h2></div><Database weight="duotone" /></div>
              <dl className="tariff-source-meta">
                <div><dt>提供器</dt><dd>{tariffSnapshot?.provider || '未提供'}</dd></div>
                <div><dt>法域</dt><dd>{tariffSnapshot?.jurisdiction || '未提供'}</dd></div>
                <div><dt>生效日期</dt><dd>{tariffSnapshot?.effective_date || tariffEvidence[0]?.effective_date || '未提供'}</dd></div>
              </dl>
              {tariffEvidence.length ? <ul className="tariff-evidence-list">{tariffEvidence.map((item, index) => (
                <li key={item.evidence_id || index}>
                  <div><code>{item.evidence_id || `证据-${index + 1}`}</code>{typeof item.confidence === 'number' && <span>可信度 {Math.round(item.confidence * 100)}%</span>}</div>
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
          <h2>运行一次美国市场真实分析</h2>
          <p>系统会查询商品税号、税率、附加税和相关风险，并将结果纳入定价与运营建议。</p>
          <button className="primary-button compact" onClick={() => navigate(runId ? 'agents' : 'workspace')}>{runId ? '查看 Agent 进度' : '创建美国市场任务'}<ArrowRight weight="bold" /></button>
        </section>
      )}
    </div>
  )

  const renderCustomerService = () => !assistantOpen ? null : (
    <>
      <button className="assistant-scrim" aria-label="关闭客服 AI" onClick={() => setAssistantOpen(false)} />
      <aside className="customer-service-drawer" role="dialog" aria-modal="false" aria-labelledby="customer-service-title">
        <header className="customer-service-head">
          <span className="customer-service-avatar"><Robot weight="duotone" /></span>
          <div><h2 id="customer-service-title">报告客服 AI</h2><p>解释报告结论，并按照你的要求修改指定内容。</p></div>
          <button className="icon-button" aria-label="关闭客服 AI" onClick={() => setAssistantOpen(false)}><X weight="bold" /></button>
        </header>

        {!report ? (
          <div className="customer-service-locked"><FileText weight="thin" /><h3>等待分析报告</h3><p>四个 Agent 完成分析并生成报告后，客服 AI 才能基于真实结论继续对话。</p><button className="compact-button" onClick={() => { setAssistantOpen(false); navigate(runId ? 'agents' : 'workspace') }}>{runId ? '查看 Agent 进度' : '创建分析任务'}</button></div>
        ) : (
          <>
            <fieldset className="personality-picker" disabled={customerBusy}>
              <legend>选择客服回复风格</legend>
              <div>{personalityOptions.map((option) => <button type="button" className={personality === option.value ? 'active' : ''} aria-pressed={personality === option.value} key={option.value} onClick={() => setPersonality(option.value)}><strong>{option.label}</strong><small>{option.caption}</small></button>)}</div>
            </fieldset>

            <div className="customer-conversation" aria-live="polite">
              {!customerMessages.length && (
                <div className="assistant-welcome"><span><Sparkle weight="duotone" /></span><div><strong>你好，我是报告客服 Agent</strong><p>我不会脱离证据整份重写，但可以解释建议、追问需求，或局部调整目标人群、定位、文案和推广策略。</p></div></div>
              )}
              {customerMessages.map((message) => <article className={`customer-message role-${message.role}`} key={message.message_id}><span>{message.role === 'assistant' ? <Robot weight="duotone" /> : <ChatCircleText weight="duotone" />}</span><div><small>{message.role === 'assistant' ? '客服 AI' : '你'}</small><p>{message.content}</p></div></article>)}
              {customerBusy && <article className="customer-message role-assistant is-thinking"><span><Robot weight="duotone" /></span><div><small>客服 AI</small><p><Pulse className="spin" weight="bold" /> 正在识别意图并核对报告边界…</p></div></article>}
              {customerError && <div className="customer-error" role="alert"><WarningCircle weight="fill" />{customerError}</div>}
              {customerResult && (
                <div className="customer-action-card">
                  <div><span>{customerActionText(customerResult.action_taken)}</span><strong>报告 v{customerResult.report_version}</strong></div>
                  {!!customerResult.change_summary.length && <ul>{customerResult.change_summary.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul>}
                  {!!customerResult.pending_questions.length && <div className="pending-questions"><small>请继续补充</small>{customerResult.pending_questions.map((question) => <button type="button" key={question} onClick={() => setCustomerInput(question)}>{question}</button>)}</div>}
                </div>
              )}
            </div>

            {!customerMessages.length && <div className="customer-prompts" aria-label="客服 AI 示例问题">
              {['为什么建议优先做内容种草？', '目标用户调整为大学生群体', '把定位调整得更高端一些', '推广策略调整得更保守一些'].map((prompt) => <button type="button" key={prompt} onClick={() => setCustomerInput(prompt)}>{prompt}</button>)}
            </div>}

            <form className="customer-composer" onSubmit={handleCustomerMessage}>
              <label htmlFor="customer-message">继续修改或追问报告</label>
              <div><textarea id="customer-message" rows={3} value={customerInput} onChange={(event) => setCustomerInput(event.target.value)} placeholder="例如：为什么建议优先做内容种草？" disabled={customerBusy} /><button type="submit" aria-label="发送给客服 AI" disabled={customerBusy || !customerInput.trim()}>{customerBusy ? <Pulse className="spin" weight="bold" /> : <PaperPlaneTilt weight="fill" />}</button></div>
              <small>客服 AI 只修改被明确指出的模块，不会编造销量、转化率或证据。</small>
            </form>
          </>
        )}
      </aside>
    </>
  )

  const renderReport = () => (
    <div className="page-view page-report">
      <PageHeader
        title="上市分析报告"
        description="四个 Agent 完成协作与审校后，系统在这里呈现可继续编辑和交付的 Markdown 报告。"
        action={<div className="report-header-actions">{report && <span className={`status-pill status-${report.audit_status}`}>{statusIcon(report.audit_status)}版本 {report.version} · {statusText(report.audit_status)}</span>}<button className="assistant-launch-button" onClick={() => setAssistantOpen(true)}><Headset weight="duotone" /><span><strong>客服 AI</strong><small>{report ? '解释或增量修改报告' : '报告生成后可用'}</small></span></button></div>}
      />
      {markdown ? (
        <section className="report-shell glass-panel">
          <div className="report-toolbar"><div><span>报告编号</span><strong>{report?.report_id.toUpperCase()}</strong></div><div><span>审校状态</span><strong>{statusText(report?.audit_status)}</strong></div></div>
          <article className="report-paper"><ReactMarkdown
            skipHtml
            components={{
              a: ({ href, children }) => {
                const match = href?.match(/\/analysis-runs\/[^/]+\/evidence\/(.+)$/)
                if (match) {
                  return <a href="#audit" onClick={(event) => { event.preventDefault(); void showEvidence(decodeURIComponent(match[1])) }}>{children}</a>
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
          <h2>报告会在审校完成后生成</h2>
          <p>报告包含商品概况、同类市场、用户洞察、上市营销策略、美国关税影响和友好编号证据索引。</p>
          <button className="primary-button compact" onClick={() => navigate(runId ? 'agents' : 'workspace')}>{runId ? '查看 Agent 进度' : '创建分析任务'}<ArrowRight weight="bold" /></button>
        </section>
      )}
    </div>
  )

  const renderDecisionHub = () => (
    <div className="page-hub decision-hub">
      <nav className="section-switcher" aria-label="运营决策子页面">
        <button className={decisionSection === 'strategy' ? 'active' : ''} aria-pressed={decisionSection === 'strategy'} onClick={() => setDecisionSection('strategy')}><Megaphone weight="duotone" /><span><strong>营销策略</strong><small>定位与上市动作</small></span></button>
        <button className={decisionSection === 'report' ? 'active' : ''} aria-pressed={decisionSection === 'report'} onClick={() => setDecisionSection('report')}><FileText weight="duotone" /><span><strong>决策报告</strong><small>Markdown 与版本</small></span></button>
        <button className="assistant-tab" onClick={() => setAssistantOpen(true)}><Headset weight="duotone" /><span><strong>客服 AI</strong><small>解释 · 澄清 · 增量修改</small></span><i>{conversationId ? '会话中' : 'NEW'}</i></button>
      </nav>
      {decisionSection === 'strategy' ? renderStrategy() : renderReport()}
      {renderCustomerService()}
    </div>
  )

  const renderHistoryAgentPanel = () => (
    <aside className="history-agent-panel glass-panel" aria-labelledby="history-agent-title">
      <header className="history-panel-heading agent-heading">
        <span><Robot weight="duotone" /></span>
        <div><h2 id="history-agent-title">报告修改助手</h2><p>提出修改要求后，系统会保留原文并生成新版本。</p></div>
      </header>

      {!report ? (
        <div className="history-agent-empty"><Headset weight="thin" /><strong>等待可编辑报告</strong><p>完成一次真实分析后，即可在这里继续修改文档。</p></div>
      ) : (
        <>
          <div className={`history-edit-context ${selectedVersionIsLatest ? 'is-latest' : 'is-readonly'}`}>
            {selectedVersionIsLatest ? <CheckCircle weight="fill" /> : <ClockCounterClockwise weight="duotone" />}
            <div><strong>{selectedVersionIsLatest ? `正在编辑最新版本 v${report.version}` : `正在查看历史版本 v${report.version}`}</strong><small>{selectedVersionIsLatest ? 'Agent 的有效修改会自动生成下一版文档。' : '历史快照不可直接覆盖，请切回最新版本。'}</small></div>
          </div>

          <fieldset className="history-personality-picker" disabled={customerBusy || !selectedVersionIsLatest}>
            <legend>客服回复风格</legend>
            <div>{personalityOptions.map((option) => <button type="button" className={personality === option.value ? 'active' : ''} aria-pressed={personality === option.value} key={option.value} onClick={() => setPersonality(option.value)}><strong>{option.label}</strong><small>{option.caption}</small></button>)}</div>
          </fieldset>

          <div className="history-agent-conversation" aria-live="polite">
            {!customerMessages.length && <div className="assistant-welcome"><span><Sparkle weight="duotone" /></span><div><strong>告诉我想改什么</strong><p>可以调整目标人群、产品定位、营销文案或推广策略；修改结果会作为新版本存入左侧历史记录。</p></div></div>}
            {customerMessages.map((message) => <article className={`customer-message role-${message.role}`} key={message.message_id}><span>{message.role === 'assistant' ? <Robot weight="duotone" /> : <ChatCircleText weight="duotone" />}</span><div><small>{message.role === 'assistant' ? '客服 AI' : '你'}</small><p>{message.content}</p></div></article>)}
            {customerBusy && <article className="customer-message role-assistant is-thinking"><span><Robot weight="duotone" /></span><div><small>客服 AI</small><p><Pulse className="spin" weight="bold" /> 正在核对证据并生成增量版本…</p></div></article>}
            {customerError && <div className="customer-error" role="alert"><WarningCircle weight="fill" />{customerError}</div>}
            {customerResult && <div className="customer-action-card"><div><span>{customerActionText(customerResult.action_taken)}</span><strong>报告 v{customerResult.report_version}</strong></div>{!!customerResult.change_summary.length && <ul>{customerResult.change_summary.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul>}{!!customerResult.pending_questions.length && <div className="pending-questions"><small>请继续补充</small>{customerResult.pending_questions.map((question) => <button type="button" key={question} onClick={() => setCustomerInput(question)}>{question}</button>)}</div>}</div>}
          </div>

          {!customerMessages.length && selectedVersionIsLatest && <div className="history-agent-prompts" aria-label="文档修改示例">
            {['目标用户调整为大学生群体', '把产品定位调整得更高端', '营销文案写得更专业一些'].map((prompt) => <button type="button" key={prompt} onClick={() => setCustomerInput(prompt)}>{prompt}</button>)}
          </div>}

          <form className="history-agent-composer" onSubmit={handleCustomerMessage}>
            <label htmlFor="history-customer-message">输入修改要求</label>
            <textarea id="history-customer-message" rows={4} value={customerInput} onChange={(event) => setCustomerInput(event.target.value)} placeholder="例如：把推广策略调整得更保守一些" disabled={customerBusy || !selectedVersionIsLatest} />
            <div><small>不会覆盖历史版本，也不会编造销量、转化率或新证据。</small><button type="submit" disabled={customerBusy || !selectedVersionIsLatest || !customerInput.trim()}>{customerBusy ? <Pulse className="spin" weight="bold" /> : <PaperPlaneTilt weight="fill" />}<span>{customerBusy ? '处理中' : '生成新版本'}</span></button></div>
          </form>
        </>
      )}
    </aside>
  )

  const renderHistoryWorkspace = () => (
    <div className="page-view page-history">
      <PageHeader
        title="历史文档与智能修改"
        description="集中保存每次分析生成的报告及其不可变版本，并通过客服 Agent 在证据边界内继续修改。"
        action={<button className="compact-button history-refresh" onClick={() => void refreshReportHistory(activeHistoryItem?.report_id)} disabled={historyBusy}><ArrowsClockwise className={historyBusy ? 'spin' : ''} weight="bold" />刷新记录</button>}
      />

      <section className="history-statbar" aria-label="历史文档统计">
        <div><Archive weight="duotone" /><span><small>文档族</small><strong>{reportHistory.length}</strong></span></div>
        <div><ClockCounterClockwise weight="duotone" /><span><small>累计版本</small><strong>{reportHistory.reduce((total, item) => total + item.version_count, 0)}</strong></span></div>
        <div><FileText weight="duotone" /><span><small>当前预览</small><strong>{selectedHistoryVersion ? `V${selectedHistoryVersion.version}` : '—'}</strong></span></div>
      </section>

      {historyError && <div className="history-global-error" role="alert"><WarningCircle weight="fill" /><span>{historyError}</span><button type="button" onClick={() => void refreshReportHistory()}>重试</button></div>}

      <section className="history-workbench">
        <aside className="history-library glass-panel" aria-label="历史文档列表">
          <header className="history-panel-heading">
            <span><Archive weight="duotone" /></span>
            <div><h2>历史记录</h2><p>按分析任务归档，最新版本置于每组顶部。</p></div>
          </header>
          <label className="history-search"><span>搜索历史文档</span><div><MagnifyingGlass weight="bold" /><input value={historySearch} onChange={(event) => setHistorySearch(event.target.value)} placeholder="商品名、分类或报告 ID" /></div></label>
          <div className="history-family-list">
            {historyBusy && !reportHistory.length ? Array.from({ length: 3 }, (_, index) => <div className="history-skeleton" key={index}><i /><span /><span /></div>) : filteredReportHistory.map((item) => (
              <button type="button" className={item.run_id === activeHistoryRunId ? 'active' : ''} aria-pressed={item.run_id === activeHistoryRunId} key={item.run_id} onClick={() => void selectHistoryFamily(item)}>
                <span className="history-family-icon"><FileText weight="duotone" /></span>
                <span className="history-family-copy"><strong>{item.product_name}</strong><small>{item.product_category || '未分类'} · {formatHistoryDate(item.updated_at)}</small><em><i className={`audit-dot status-${item.audit_status}`} />最新 V{item.version} · 共 {item.version_count} 版</em></span>
                <CaretRight weight="bold" />
              </button>
            ))}
            {!historyBusy && !filteredReportHistory.length && <div className="history-empty"><Archive weight="thin" /><strong>{reportHistory.length ? '没有匹配记录' : '还没有历史文档'}</strong><p>{reportHistory.length ? '换一个关键词继续搜索。' : '完成一次真实分析后，报告会自动保存在这里。'}</p>{!reportHistory.length && <button className="compact-button" onClick={() => navigate('workspace')}>创建分析任务</button>}</div>}
          </div>
        </aside>

        <section className="history-document-panel glass-panel" aria-labelledby="history-document-title">
          <header className="history-panel-heading document-heading">
            <span><FileText weight="duotone" /></span>
            <div><h2 id="history-document-title">{activeHistoryItem?.product_name || '文档预览'}</h2><p>{activeHistoryItem ? `${activeHistoryItem.product_category || '未分类'} · ${activeHistoryItem.version_count} 个历史版本` : '选择左侧记录查看生成文档。'}</p></div>
            {report && <span className={`status-pill status-${report.audit_status}`}>{statusIcon(report.audit_status)}{statusText(report.audit_status)}</span>}
          </header>

          {!!historyVersions.length && <nav className="history-version-strip" aria-label="报告版本">
            {historyVersions.map((version) => <button type="button" className={version.report_id === selectedVersionReportId ? 'active' : ''} aria-pressed={version.report_id === selectedVersionReportId} key={version.report_id} onClick={() => void selectHistoryVersion(version.report_id)}><span>V{version.version}</span><small>{version.version === activeHistoryItem?.version ? '最新' : formatHistoryDate(version.created_at)}</small></button>)}
          </nav>}

          {markdown ? <>
            <div className="history-document-meta"><span><strong>报告编号</strong><code>{report?.report_id.slice(0, 8).toUpperCase()}</code></span><span><strong>版本时间</strong><em>{selectedHistoryVersion ? formatHistoryDate(selectedHistoryVersion.created_at) : '—'}</em></span><span><strong>修改范围</strong><em>{selectedHistoryVersion?.changed_section_ids.length ? `${selectedHistoryVersion.changed_section_ids.length} 个章节` : '原始报告'}</em></span></div>
            <article className="history-report-paper"><ReactMarkdown skipHtml>{markdown}</ReactMarkdown></article>
          </> : <div className="history-document-empty"><FileText weight="thin" /><strong>选择一份历史文档</strong><p>这里会显示对应版本的完整 Markdown 内容。</p></div>}
        </section>

        {renderHistoryAgentPanel()}
      </section>

      <section className="history-archive glass-panel">
        <button type="button" className="history-archive-toggle" aria-expanded={archiveOpen} onClick={() => setArchiveOpen((value) => !value)}><span><ShieldCheck weight="duotone" /><span><strong>审校与证据存档</strong><small>需要时查看当前分析关联的审校结论、关税和原始证据。</small></span></span><CaretRight className={archiveOpen ? 'is-open' : ''} weight="bold" /></button>
        {archiveOpen && <div className="history-archive-content">
          <nav className="section-switcher" aria-label="历史审校存档">
            <button className={auditSection === 'audit' ? 'active' : ''} aria-pressed={auditSection === 'audit'} onClick={() => setAuditSection('audit')}><ShieldCheck weight="duotone" /><span><strong>审校结果</strong><small>结论与复核边界</small></span></button>
            <button className={auditSection === 'tariff' ? 'active' : ''} aria-pressed={auditSection === 'tariff'} onClick={() => setAuditSection('tariff')}><Receipt weight="duotone" /><span><strong>关税合规</strong><small>美国 HTS 证据</small></span></button>
            <button className={auditSection === 'evidence' ? 'active' : ''} aria-pressed={auditSection === 'evidence'} onClick={() => setAuditSection('evidence')}><Fingerprint weight="duotone" /><span><strong>证据中心</strong><small>来源与原文详情</small></span></button>
          </nav>
          {auditSection === 'audit' && renderAudit()}
          {auditSection === 'tariff' && renderTariff()}
          {auditSection === 'evidence' && renderEvidence()}
        </div>}
      </section>
    </div>
  )

  const renderAuditHub = () => (
    <div className="page-hub history-hub">{renderHistoryWorkspace()}</div>
  )

  return (
    <>
      <a className="skip-link" href="#main-content">跳到主要内容</a>
      <div className={`app-shell theme-${page} ${sidebarCollapsed ? 'sidebar-is-collapsed' : ''}`}>
        <div className={`theme-backdrop ${themeTransitioning ? 'is-transitioning' : ''}`} aria-hidden="true">
          <span className={`theme-bg-layer palette-${themeFrom}`} />
          <span className={`theme-bg-layer theme-bg-next palette-${themeTo}`} />
        </div>
        <span className={`theme-transition-mask ${themeTransitioning ? 'is-transitioning' : ''}`} aria-hidden="true" />
        <ParticleField />
        <aside className="sidebar" aria-label="主导航">
          <div className="sidebar-top">
            <a className="brand" href="#workspace" aria-label="TradePilot 任务创建页" onClick={(event) => { event.preventDefault(); navigate('workspace') }}>
              <span className="brand-logo-frame"><img src="/tradepilot-team-logo.png" alt="" /></span>
              <span className="brand-copy"><strong>TradePilot</strong></span>
            </a>
            <button className="sidebar-toggle" onClick={() => setSidebarCollapsed((value) => !value)} aria-label={sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'} aria-expanded={!sidebarCollapsed}><SidebarSimple weight="bold" /></button>
          </div>

          <nav className="sidebar-nav">
            {navigation.map((item) => {
              const Icon = item.icon
              return <a key={item.key} className={`nav-link nav-${item.key} ${page === item.key ? 'active' : ''}`} href={`#${item.key}`} title={sidebarCollapsed ? item.label : undefined} onClick={(event) => { event.preventDefault(); navigate(item.key) }}><Icon weight={page === item.key ? 'fill' : 'regular'} /><span><strong>{item.label}</strong><small>{item.caption}</small></span><em>{item.agent}</em>{page === item.key && <i />}</a>
            })}
          </nav>

          <div className="sidebar-foot">
            <div className={`connection ${connected === false ? 'offline' : ''}`}><span className="connection-dot" /><div><strong>{connected === null ? '正在连接' : connected ? '系统在线' : '等待后端'}</strong><small>{connected ? 'Real 工作流已就绪' : '启动服务后即可分析'}</small></div></div>
          </div>
        </aside>

        <main id="main-content" className="main-content">
          <header className="topbar">
            <button className="mobile-sidebar-toggle" onClick={() => setSidebarCollapsed((value) => !value)} aria-label={sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'}><SidebarSimple weight="bold" /></button>
            <div className="breadcrumb"><strong>{navigation.find((item) => item.key === page)?.label}</strong></div>
            <div className="topbar-actions"><span className={`system-state ${connected === false ? 'offline' : ''}`}><i />{connected ? '系统可用' : connected === false ? '系统未连接' : '正在连接'}</span></div>
          </header>
          <div className={`content-stage content-stage-${page}`} key={page}>
            {page === 'workspace' && renderWorkspace()}
            {page === 'agents' && renderAgents()}
            {page === 'decision' && renderDecisionHub()}
            {page === 'audit' && renderAuditHub()}
          </div>
          <footer><div><strong>TradePilot</strong><span>基于多智能体的跨境商品智能运营决策助手</span></div><span>证据优先 · 过程透明 · 人机共决策</span></footer>
        </main>
      </div>
    </>
  )
}

export default App
