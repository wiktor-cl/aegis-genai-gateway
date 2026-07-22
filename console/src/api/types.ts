// Mirrors the Pydantic response/request models in src/aegis/api/*.py.
// Kept as plain interfaces (no codegen) — the surface is small enough that
// hand-written types stay easier to read than a generated client, and any
// drift is caught immediately by the pages that consume these at compile time.

export interface CostReport {
  tenant_id: string
  month_to_date_usd: number
  monthly_budget_usd: number
  percent_used: number
  status: string
}

export interface AgentRunSummary {
  run_id: string
  agent_name: string
  status: string
  step_count: number
  total_input_tokens: number
  total_output_tokens: number
  created_at: string
  completed_at: string | null
}

export interface AgentRunOut {
  run_id: string
  status: string
  final_output: string | null
  total_input_tokens: number
  total_output_tokens: number
  step_count: number
}

export interface AgentStepOut {
  step_type: string
  tool_name: string | null
  provider_name: string | null
  model: string | null
  input: Record<string, unknown>
  output: Record<string, unknown> | null
  error: string | null
  input_tokens: number
  output_tokens: number
  retry_count: number
  duration_ms: number | null
}

export interface AgentRunDetail {
  run_id: string
  status: string
  final_output: string | null
  total_input_tokens: number
  total_output_tokens: number
  steps: AgentStepOut[]
}

export interface AgentRunRequest {
  agent_name: string
  system_prompt: string
  user_message: string
  data_classification: string
  cost_tier: string
}

export type Role = 'admin' | 'developer' | 'viewer'

export interface ApiKeyOut {
  key_id: string
  raw_secret: string
  tenant_id: string
  role: Role
}
