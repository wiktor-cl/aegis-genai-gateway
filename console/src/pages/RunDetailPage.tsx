import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import type { AgentRunDetail } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { StatusBadge } from '../components/StatusBadge'

export function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>()
  const { token } = useAuth()
  const [run, setRun] = useState<AgentRunDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!token || !runId) return
    api
      .getRun(token, runId)
      .then(setRun)
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : 'Unexpected error'))
  }, [token, runId])

  return (
    <div className="space-y-4">
      <Link to="/runs" className="text-sm text-violet-600 hover:underline dark:text-violet-400">
        &larr; Back to runs
      </Link>

      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      {!run && !error && <p className="text-sm text-gray-500">Loading...</p>}

      {run && (
        <>
          <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-800 dark:bg-gray-900">
            <div className="mb-2 flex items-center gap-3">
              <h2 className="text-base font-semibold">Run {run.run_id}</h2>
              <StatusBadge status={run.status} />
            </div>
            <p className="text-sm text-gray-500">
              {run.total_input_tokens} input / {run.total_output_tokens} output tokens across{' '}
              {run.steps.length} step{run.steps.length === 1 ? '' : 's'}
            </p>
            {run.final_output && (
              <pre className="mt-3 whitespace-pre-wrap rounded-md bg-gray-50 p-3 text-sm dark:bg-gray-800">
                {run.final_output}
              </pre>
            )}
          </div>

          <div className="space-y-3">
            {run.steps.map((step, i) => (
              <div
                key={i}
                className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-800 dark:bg-gray-900"
              >
                <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-medium">
                    Step {i + 1} — {step.step_type}
                  </span>
                  {step.tool_name && (
                    <span className="rounded bg-gray-100 px-2 py-0.5 text-xs dark:bg-gray-800">
                      {step.tool_name}
                    </span>
                  )}
                  {step.provider_name && (
                    <span className="rounded bg-gray-100 px-2 py-0.5 text-xs dark:bg-gray-800">
                      {step.provider_name} / {step.model}
                    </span>
                  )}
                  {step.duration_ms != null && (
                    <span className="text-xs text-gray-500">{step.duration_ms}ms</span>
                  )}
                  {step.retry_count > 0 && (
                    <span className="text-xs text-amber-600 dark:text-amber-400">
                      retried {step.retry_count}x
                    </span>
                  )}
                </div>
                {step.error ? (
                  <p className="text-sm text-red-600 dark:text-red-400">{step.error}</p>
                ) : (
                  <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-md bg-gray-50 p-2 text-xs dark:bg-gray-800">
                    {JSON.stringify(step.output ?? step.input, null, 2)}
                  </pre>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
