export type DataMode = 'demo' | 'real'
export type RunStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'manual_review'
export type StageStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped'

export interface ApiEnvelope<T> {
  success: boolean
  data: T | null
  error: { code: string; message: string; details?: unknown[] } | null
}

export interface ProductPayload {
  name: string
  category: string
  description: string
  features: string[]
  materials: string[]
  use_scenarios: string[]
  target_market: string
  target_audience: string[]
  target_price: number | null
  target_currency: string
  known_risks: string[]
  data_mode: DataMode
}

export interface ProductProfile extends ProductPayload {
  product_id: string
  data_origin: string
}

export interface AnalysisRun {
  run_id: string
  product_id: string
  data_mode: DataMode
  status: RunStatus
  current_node: string
  retry_count: number
  report_id: string | null
}

export interface RunStatusView {
  run_id: string
  status: RunStatus
  current_node: string
  report_id: string | null
  error: { code?: string; message?: string } | null
}

export interface RunStage {
  stage_key: string
  sequence: number
  status: StageStatus
  started_at: string | null
  completed_at: string | null
  duration_ms: number | null
  payload: Record<string, unknown>
  error: Record<string, unknown> | null
}

export interface TimelineView {
  run_id: string
  status: RunStatus
  stages: RunStage[]
}

export interface AgentView {
  agent_name: string
  display_name: string
  responsibility: string
  status: StageStatus | 'insufficient_evidence'
  provider: string
  model_name: string | null
  real_model_called: boolean
  duration_ms: number | null
  model_call_count: number
  parse_retry_count: number
  token_usage: { total_tokens?: number; input_tokens?: number; output_tokens?: number } | null
  evidence_ids: string[]
  output_summary: string
  output: Record<string, unknown>
  error: Record<string, unknown> | null
}

export interface WorkflowNode {
  node_name: string
  display_name: string
  responsibility: string
  execution_order: number
  parallel_group: string | null
  provider: string | null
  model_name: string | null
}

export interface WorkflowMetadata {
  nodes: WorkflowNode[]
  edges: string[][]
  audit_retry_limit: number
}

export interface AuditResult {
  status: 'pass' | 'warning' | 'rejected'
  issues: string[]
  conflicting_evidence_ids: string[]
  unresolved_questions: string[]
  manual_review_required: boolean
}

export interface EvidenceReference {
  evidence_id: string
  evidence_type: string
  knowledge_type: string
  source_name: string
  source_uri: string | null
  excerpt: string
  published_at: string | null
  data_origin: string
  is_demo: boolean
  metadata: Record<string, unknown>
}

export interface ReportView {
  report_id: string
  run_id: string
  version: number
  audit_status: 'pass' | 'warning' | 'rejected'
  disclaimer: string
  sections: Record<string, unknown>
}

const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...init?.headers,
    },
  })

  const payload = (await response.json()) as ApiEnvelope<T>
  if (!response.ok || !payload.success || payload.data === null) {
    throw new Error(payload.error?.message || `请求失败（${response.status}）`)
  }
  return payload.data
}

export const api = {
  health: () => request<{ service: string; status: string }>('/health'),
  workflow: () => request<WorkflowMetadata>('/workflow/metadata'),
  createProduct: (payload: ProductPayload) =>
    request<ProductProfile>('/products', { method: 'POST', body: JSON.stringify(payload) }),
  uploadFile: (productId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    form.append('file_type', file.type.startsWith('image/') ? 'image' : 'document')
    return request<{ file_id: string }>(`/products/${productId}/files`, {
      method: 'POST',
      body: form,
    })
  },
  startRun: (productId: string, mode: DataMode, targetMarket: string) => {
    const isUnitedStates = /(美国|United States|\bUS\b|\bUSA\b)/i.test(targetMarket)
    return request<AnalysisRun>('/analysis-runs', {
      method: 'POST',
      body: JSON.stringify({
        product_id: productId,
        data_mode: mode,
        target_market: targetMarket,
        jurisdiction: isUnitedStates ? 'US' : '',
        platform: 'cross_border_ecommerce',
        background_context_types: isUnitedStates ? ['tariff_rate'] : [],
        ...(isUnitedStates ? { background_provider: 'us-tariff-provider' } : {}),
        user_constraints: { language: 'zh-CN', evidence_grounded: true },
      }),
    })
  },
  status: (runId: string) => request<RunStatusView>(`/analysis-runs/${runId}/status`),
  timeline: (runId: string) => request<TimelineView>(`/analysis-runs/${runId}/timeline`),
  agents: (runId: string) =>
    request<{ run_id: string; agents: AgentView[] }>(`/analysis-runs/${runId}/agents`),
  evidence: (runId: string) =>
    request<{ run_id: string; evidence: EvidenceReference[] }>(`/analysis-runs/${runId}/evidence`),
  evidenceDetail: (runId: string, evidenceId: string) =>
    request<{ run_id: string; evidence: EvidenceReference }>(
      `/analysis-runs/${runId}/evidence/${encodeURIComponent(evidenceId)}`,
    ),
  audit: (runId: string) =>
    request<{ run_id: string; audit: AuditResult | null }>(`/analysis-runs/${runId}/audit`),
  report: (reportId: string) => request<ReportView>(`/reports/${reportId}`),
  markdown: async (reportId: string) => {
    const response = await fetch(`${API_BASE}/reports/${reportId}/markdown`)
    if (!response.ok) throw new Error(`报告读取失败（${response.status}）`)
    return response.text()
  },
}
