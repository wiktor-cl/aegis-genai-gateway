// Thin fetch wrapper. Auth token comes from the caller on every call rather
// than a hidden module-level global, so it's obvious where the credential
// comes from and AuthContext stays the single source of truth for it.

import type {
  AgentRunDetail,
  AgentRunOut,
  AgentRunRequest,
  AgentRunSummary,
  ApiKeyOut,
  CostReport,
  Role,
} from './types'

const BASE_URL = '/api'

export class ApiError extends Error {
  status: number

  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
  }
}

async function request<T>(path: string, token: string | null, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  headers.set('Content-Type', 'application/json')
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const resp = await fetch(`${BASE_URL}${path}`, { ...init, headers })

  if (!resp.ok) {
    let detail = resp.statusText
    try {
      const body = (await resp.json()) as { detail?: string }
      detail = body.detail ?? detail
    } catch {
      // response body wasn't JSON — fall back to statusText, already set above
    }
    throw new ApiError(resp.status, detail)
  }

  if (resp.status === 204) {
    return undefined as T
  }
  return (await resp.json()) as T
}

export const api = {
  getCostReport: (token: string) => request<CostReport>('/v1/cost/report', token),

  listRuns: (token: string) => request<AgentRunSummary[]>('/v1/agents/runs', token),

  getRun: (token: string, runId: string) =>
    request<AgentRunDetail>(`/v1/agents/runs/${runId}`, token),

  triggerRun: (token: string, body: AgentRunRequest) =>
    request<AgentRunOut>('/v1/agents/run', token, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  createApiKey: (token: string, tenantId: string, role: Role) =>
    request<ApiKeyOut>('/v1/admin/api-keys', token, {
      method: 'POST',
      body: JSON.stringify({ tenant_id: tenantId, role }),
    }),

  rotateApiKey: (token: string, keyId: string) =>
    request<ApiKeyOut>(`/v1/admin/api-keys/${keyId}/rotate`, token, { method: 'POST' }),

  revokeApiKey: (token: string, keyId: string) =>
    request<void>(`/v1/admin/api-keys/${keyId}/revoke`, token, { method: 'POST' }),
}
