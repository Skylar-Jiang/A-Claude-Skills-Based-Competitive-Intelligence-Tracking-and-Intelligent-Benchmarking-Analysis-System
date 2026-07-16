import { FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowRight,
  ChartLineUp,
  CheckCircle,
  Clock,
  Compass,
  Database,
  FileText,
  Globe,
  Lightning,
  Package,
  Play,
  Pulse,
  ShieldCheck,
  Sparkle,
  UploadSimple,
  UsersThree,
  WarningCircle,
  XCircle,
} from '@phosphor-icons/react'
import ReactMarkdown from 'react-markdown'
import {
  api,
  type AgentView,
  type AuditResult,
  type DataMode,
  type ReportView,
  type RunStage,
  type RunStatus,
  type WorkflowMetadata,
} from './api'

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
    detail: '识别同类商品基线、价格结构与差异化机会',
    className: 'agent-white',
    icon: ChartLineUp,
  },
  {
    key: 'UserInsightAgent',
    node: 'user_insight_agent',
    name: '同类用户洞察',
    short: 'INSIGHT',
    detail: '提炼评论样本中的需求、痛点与购买因素',
    className: 'agent-pink',
    icon: UsersThree,
  },
  {
    key: 'OperationsDecisionAgent',
    node: 'operations_decision_agent',
    name: '运营决策',
    short: 'DECISION',
    detail: '综合证据生成定位、行动与内容方案',
    className: 'agent-brown',
    icon: Compass,
  },
  {
    key: 'EvidenceAuditAgent',
    node: 'evidence_audit_agent',
    name: '证据审校',
    short: 'AUDIT',
    detail: '检查事实、数值、引用范围和待验证假设',
    className: 'agent-blue',
    icon: ShieldCheck,
  },
] as const

const terminalStatuses: RunStatus[] = ['succeeded', 'failed', 'manual_review']

function splitValues(value: string) {
  return value
    .split(/[，,\n]/)
    .map((item) => item.trim())
    .filter(Boolean)
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

function App() {
  const [form, setForm] = useState<FormState>(initialForm)
  const [mode, setMode] = useState<DataMode>('demo')
  const [file, setFile] = useState<File | null>(null)
  const [connected, setConnected] = useState<boolean | null>(null)
  const [workflow, setWorkflow] = useState<WorkflowMetadata | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const [runStatus, setRunStatus] = useState<RunStatus | null>(null)
  const [currentNode, setCurrentNode] = useState('')
  const [timeline, setTimeline] = useState<RunStage[]>([])
  const [agents, setAgents] = useState<AgentView[]>([])
  const [audit, setAudit] = useState<AuditResult | null>(null)
  const [report, setReport] = useState<ReportView | null>(null)
  const [markdown, setMarkdown] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const reportRef = useRef<HTMLElement>(null)

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
    return () => {
      active = false
    }
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
            const [reportData, reportMarkdown] = await Promise.all([
              api.report(status.report_id),
              api.markdown(status.report_id),
            ])
            if (active) {
              setReport(reportData)
              setMarkdown(reportMarkdown)
            }
          }
          if (status.error?.message) setError(status.error.message)
          return
        }
        timer = window.setTimeout(poll, 1600)
      } catch (pollError) {
        if (!active) return
        setError(pollError instanceof Error ? pollError.message : '状态更新失败，请稍后重试。')
        timer = window.setTimeout(poll, 3200)
      }
    }

    void poll()
    return () => {
      active = false
      if (timer) window.clearTimeout(timer)
    }
  }, [runId])

  useEffect(() => {
    if (markdown && reportRef.current) {
      reportRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [markdown])

  const stageMap = useMemo(
    () => new Map(timeline.map((stage) => [stage.stage_key, stage])),
    [timeline],
  )

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    setRunId(null)
    setRunStatus(null)
    setTimeline([])
    setAgents([])
    setAudit(null)
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
        data_mode: mode,
      })
      if (file) await api.uploadFile(product.product_id, file)
      const run = await api.startRun(product.product_id, mode, form.targetMarket.trim())
      setRunId(run.run_id)
      setRunStatus(run.status)
      setCurrentNode(run.current_node)
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : '创建分析任务失败。')
    } finally {
      setBusy(false)
    }
  }

  const completedCount = timeline.filter((stage) => stage.status === 'succeeded').length
  const progress = runStatus && terminalStatuses.includes(runStatus)
    ? 100
    : timeline.length
      ? Math.round((completedCount / timeline.length) * 100)
      : 0
  const auditStatus = audit?.status || (runStatus === 'manual_review' ? 'warning' : 'pending')

  return (
    <>
      <a className="skip-link" href="#main-content">
        跳到主要内容
      </a>
      <div className="app-shell">
        <aside className="sidebar" aria-label="主导航">
          <a className="brand" href="#workspace" aria-label="TradePilot 首页">
            <span className="brand-logo-frame">
              <img src="/tradepilot-team-logo.png" alt="TradePilot 团队四位像素角色 Logo" />
            </span>
            <span className="brand-copy">
              <strong>TradePilot</strong>
              <small>AI COMMERCE CREW</small>
            </span>
          </a>

          <nav className="sidebar-nav">
            <a className="active" href="#workspace">
              <Lightning aria-hidden="true" />
              智能工作台
            </a>
            <a href="#agents">
              <UsersThree aria-hidden="true" />
              Agent 协作
            </a>
            <a href="#audit">
              <ShieldCheck aria-hidden="true" />
              证据审校
            </a>
            <a href="#report">
              <FileText aria-hidden="true" />
              分析报告
            </a>
          </nav>

          <div className="sidebar-foot">
            <div className={`connection ${connected === false ? 'offline' : ''}`}>
              <span className="connection-dot" />
              <div>
                <strong>{connected === null ? '正在连接' : connected ? '系统在线' : '等待后端'}</strong>
                <small>{connected ? 'API 与工作流已就绪' : '启动服务后即可分析'}</small>
              </div>
            </div>
            <span className="build-label">MULTI-AGENT · EVIDENCE FIRST</span>
          </div>
        </aside>

        <main id="main-content" className="main-content">
          <header className="topbar">
            <div>
              <span className="eyebrow">CROSS-BORDER INTELLIGENCE</span>
              <h1>新品上市决策舱</h1>
            </div>
            <div className="topbar-status">
              <span className={`status-pill status-${runStatus || 'pending'}`}>
                {statusIcon(runStatus || 'pending')}
                {runStatus ? statusText(runStatus) : '准备就绪'}
              </span>
              <span className="mode-badge">{mode === 'real' ? 'REAL MODEL' : 'DEMO MODE'}</span>
            </div>
          </header>

          <section className="hero" aria-labelledby="hero-title">
            <div className="hero-copy">
              <span className="hero-kicker">
                <Sparkle weight="fill" aria-hidden="true" />
                让四个 Agent 像一支运营团队一样协作
              </span>
              <h2 id="hero-title">
                从商品资料到上市方案，
                <em>每一步都有证据。</em>
              </h2>
              <p>
                TradePilot 将市场分析、用户洞察、运营决策与证据审校串成一条透明链路，
                帮你在新品上线前看清机会、风险和下一步行动。
              </p>
              <div className="hero-proof" aria-label="产品能力">
                <span><Database weight="bold" /> 同类数据可追溯</span>
                <span><Pulse weight="bold" /> Agent 过程可观察</span>
                <span><ShieldCheck weight="bold" /> 结论先审校再输出</span>
              </div>
            </div>

            <div className="hero-crew" aria-label="四个智能 Agent">
              <div className="crew-header">
                <span>YOUR AI CREW</span>
                <span className="live-chip"><i /> STANDBY</span>
              </div>
              <div className="crew-grid">
                {agentDefinitions.map((agent) => {
                  const Icon = agent.icon
                  return (
                    <div className={`crew-member ${agent.className}`} key={agent.key}>
                      <span className="crew-icon"><Icon weight="bold" /></span>
                      <strong>{agent.short}</strong>
                      <small>{agent.name}</small>
                    </div>
                  )
                })}
              </div>
              <div className="crew-flow" aria-hidden="true">
                <span />
                <b>并行分析</b>
                <span />
                <b>决策</b>
                <span />
                <b>审校</b>
              </div>
            </div>
          </section>

          <section id="workspace" className="workspace-grid section-anchor" aria-labelledby="workspace-title">
            <form className="panel product-form" onSubmit={handleSubmit}>
              <div className="panel-heading">
                <div>
                  <span className="step-index">01</span>
                  <div>
                    <h2 id="workspace-title">创建新品任务</h2>
                    <p>填写你已知的信息，未知参数会被标记为待验证。</p>
                  </div>
                </div>
                <Package weight="duotone" aria-hidden="true" />
              </div>

              <fieldset className="mode-switch">
                <legend>分析模式</legend>
                <label className={mode === 'demo' ? 'selected' : ''}>
                  <input
                    type="radio"
                    name="mode"
                    value="demo"
                    checked={mode === 'demo'}
                    onChange={() => setMode('demo')}
                  />
                  <span><strong>Demo</strong><small>快速体验完整流程</small></span>
                </label>
                <label className={mode === 'real' ? 'selected' : ''}>
                  <input
                    type="radio"
                    name="mode"
                    value="real"
                    checked={mode === 'real'}
                    onChange={() => setMode('real')}
                  />
                  <span><strong>Real</strong><small>真实模型与同类数据</small></span>
                </label>
              </fieldset>

              <div className="field-grid two-columns">
                <label>
                  <span>商品名称 <b>*</b></span>
                  <input
                    required
                    value={form.name}
                    onChange={(event) => setForm({ ...form, name: event.target.value })}
                  />
                </label>
                <label>
                  <span>商品类别 <b>*</b></span>
                  <input
                    required
                    value={form.category}
                    onChange={(event) => setForm({ ...form, category: event.target.value })}
                  />
                </label>
              </div>

              <label className="full-field">
                <span>商品描述</span>
                <textarea
                  rows={3}
                  value={form.description}
                  onChange={(event) => setForm({ ...form, description: event.target.value })}
                />
              </label>

              <label className="full-field">
                <span>核心功能</span>
                <input
                  value={form.features}
                  onChange={(event) => setForm({ ...form, features: event.target.value })}
                  aria-describedby="feature-help"
                />
                <small id="feature-help">用逗号分隔，例如：反光织带，四点调节，透气网布</small>
              </label>

              <div className="field-grid two-columns">
                <label>
                  <span>目标市场</span>
                  <div className="input-with-icon">
                    <Globe aria-hidden="true" />
                    <input
                      value={form.targetMarket}
                      onChange={(event) => setForm({ ...form, targetMarket: event.target.value })}
                    />
                  </div>
                </label>
                <label>
                  <span>目标售价</span>
                  <div className="price-field">
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={form.targetPrice}
                      onChange={(event) => setForm({ ...form, targetPrice: event.target.value })}
                    />
                    <select
                      aria-label="货币"
                      value={form.currency}
                      onChange={(event) => setForm({ ...form, currency: event.target.value })}
                    >
                      <option>USD</option>
                      <option>EUR</option>
                      <option>GBP</option>
                      <option>JPY</option>
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
                <span>
                  <strong>{file ? file.name : '添加商品图片或说明文档'}</strong>
                  <small>{file ? `${(file.size / 1024).toFixed(1)} KB` : '可选 · PNG、JPG、PDF、DOCX'}</small>
                </span>
                <input
                  type="file"
                  accept="image/png,image/jpeg,application/pdf,.doc,.docx,.txt"
                  onChange={(event) => setFile(event.target.files?.[0] || null)}
                />
              </label>

              {error && (
                <div className="error-banner" role="alert">
                  <WarningCircle weight="fill" />
                  <span><strong>任务未完成</strong>{error}</span>
                </div>
              )}

              <button className="primary-button" type="submit" disabled={busy || connected === false}>
                {busy ? <Pulse className="spin" weight="bold" /> : <Play weight="fill" />}
                {busy ? '正在创建任务…' : '启动智能分析'}
                {!busy && <ArrowRight weight="bold" />}
              </button>
              <p className="submit-note">
                {mode === 'real'
                  ? '真实模式需要后端已配置模型密钥与同类数据。'
                  : 'Demo 模式使用确定性数据，不产生模型费用。'}
              </p>
            </form>

            <div className="panel mission-control" aria-live="polite">
              <div className="panel-heading">
                <div>
                  <span className="step-index">02</span>
                  <div>
                    <h2>任务控制台</h2>
                    <p>{runId ? `RUN · ${runId.slice(0, 8).toUpperCase()}` : '启动后在这里查看实时进度'}</p>
                  </div>
                </div>
                <span className={`status-orb status-${runStatus || 'pending'}`}>{statusIcon(runStatus || undefined)}</span>
              </div>

              <div className="mission-summary">
                <div className="progress-ring" style={{ '--progress': `${progress * 3.6}deg` } as React.CSSProperties}>
                  <span><strong>{progress}%</strong><small>完成度</small></span>
                </div>
                <div>
                  <span className="micro-label">CURRENT STAGE</span>
                  <h3>{currentNode ? workflow?.nodes.find((node) => node.node_name === currentNode)?.display_name || currentNode : '等待创建任务'}</h3>
                  <p>{runStatus ? statusText(runStatus || undefined) : '四个 Agent 已就位，等待商品资料。'}</p>
                </div>
              </div>

              <ol className="timeline-list">
                {(workflow?.nodes || []).map((node) => {
                  const stage = stageMap.get(node.node_name)
                  const status = stage?.status || 'pending'
                  return (
                    <li className={`timeline-item status-${status}`} key={node.node_name}>
                      <span className="timeline-marker">{statusIcon(status)}</span>
                      <div>
                        <strong>{node.display_name}</strong>
                        <small>{node.responsibility}</small>
                      </div>
                      <time>{formatDuration(stage?.duration_ms)}</time>
                    </li>
                  )
                })}
              </ol>
              {!workflow && <div className="timeline-empty">连接后端后将加载完整工作流。</div>}
            </div>
          </section>

          <section id="agents" className="section-block section-anchor" aria-labelledby="agents-title">
            <div className="section-heading">
              <div><span className="eyebrow">AGENT ORCHESTRATION</span><h2 id="agents-title">四个角色，一条证据链</h2></div>
              <p>市场与用户洞察并行执行，运营决策汇总后交给证据审校。</p>
            </div>
            <div className="agent-board">
              {agentDefinitions.map((definition) => {
                const Icon = definition.icon
                const agent = agents.find((item) => item.agent_name === definition.key)
                const stage = stageMap.get(definition.node)
                const status = agent?.status || stage?.status || 'pending'
                return (
                  <article className={`agent-card ${definition.className} status-${status}`} key={definition.key}>
                    <div className="agent-card-top">
                      <span className="agent-avatar"><Icon weight="bold" /></span>
                      <span className={`agent-status status-${status}`}>{statusIcon(status)}{statusText(status)}</span>
                    </div>
                    <span className="micro-label">{definition.short} AGENT</span>
                    <h3>{definition.name}</h3>
                    <p>{agent?.output_summary || definition.detail}</p>
                    <dl>
                      <div><dt>模型</dt><dd>{agent?.model_name || '等待配置'}</dd></div>
                      <div><dt>耗时</dt><dd>{formatDuration(agent?.duration_ms)}</dd></div>
                      <div><dt>证据</dt><dd>{agent?.evidence_ids.length || 0} 条</dd></div>
                      <div><dt>调用</dt><dd>{agent?.model_call_count || 0} 次</dd></div>
                    </dl>
                  </article>
                )
              })}
            </div>
          </section>

          <section id="audit" className="insight-grid section-anchor" aria-labelledby="audit-title">
            <div className="panel audit-panel">
              <div className="panel-heading compact">
                <div><span className="step-index">03</span><div><h2 id="audit-title">证据审校</h2><p>让每条结论知道自己从哪里来。</p></div></div>
                <ShieldCheck weight="duotone" />
              </div>
              <div className={`audit-verdict audit-${auditStatus}`}>
                <span>{statusIcon(auditStatus)}</span>
                <div><small>AUDIT VERDICT</small><strong>{statusText(auditStatus)}</strong></div>
              </div>
              {audit?.issues.length ? (
                <ul className="issue-list">
                  {audit.issues.slice(0, 5).map((issue, index) => <li key={`${issue}-${index}`}>{issue}</li>)}
                </ul>
              ) : (
                <div className="empty-state"><ShieldCheck weight="thin" /><p>{audit ? '未发现阻断或提醒问题，当前结论已通过证据审校。' : runId ? '审校结果生成后会显示风险和修正建议。' : '尚未运行分析任务。'}</p></div>
              )}
            </div>

            <div className="panel evidence-principles">
              <div className="panel-heading compact">
                <div><span className="step-index">04</span><div><h2>决策护栏</h2><p>系统始终遵守的四条原则。</p></div></div>
                <Database weight="duotone" />
              </div>
              <div className="principle-list">
                <div><span>01</span><p><strong>新品不是同类商品</strong>不把同行评论归因到待上市新品。</p></div>
                <div><span>02</span><p><strong>数字必须有来源</strong>销量、评分、价格与比例都要可追溯。</p></div>
                <div><span>03</span><p><strong>假设必须被标记</strong>属性推导只作为上市前待验证事项。</p></div>
                <div><span>04</span><p><strong>证据范围可审计</strong>每条结论绑定有效 evidence ID。</p></div>
              </div>
            </div>
          </section>

          <section id="report" ref={reportRef} className="report-section section-anchor" aria-labelledby="report-title">
            <div className="section-heading report-heading">
              <div><span className="eyebrow">DECISION REPORT</span><h2 id="report-title">上市分析报告</h2></div>
              {report && <span className={`status-pill status-${report.audit_status}`}>{statusIcon(report.audit_status)}版本 {report.version} · {statusText(report.audit_status)}</span>}
            </div>
            {markdown ? (
              <article className="report-paper">
                <div className="report-meta"><span>REPORT · {report?.report_id.slice(0, 8).toUpperCase()}</span><span>{report?.disclaimer}</span></div>
                <ReactMarkdown skipHtml>{markdown}</ReactMarkdown>
              </article>
            ) : (
              <div className="report-placeholder">
                <FileText weight="thin" />
                <h3>报告会在审校完成后生成</h3>
                <p>包含商品概况、同类市场、用户洞察、运营方案、数据限制与证据索引。</p>
                <a href="#workspace">返回任务表单 <ArrowRight weight="bold" /></a>
              </div>
            )}
          </section>

          <footer>
            <div><strong>TradePilot</strong><span>基于多智能体的跨境商品智能运营决策助手</span></div>
            <span>证据优先 · 过程透明 · 人机共决策</span>
          </footer>
        </main>
      </div>
    </>
  )
}

export default App
