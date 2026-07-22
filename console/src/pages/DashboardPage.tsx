import { useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { CostReport } from '../api/types'
import { useAuth } from '../auth/AuthContext'

export function DashboardPage() {
  const { token } = useAuth()
  const [report, setReport] = useState<CostReport | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!token) return
    api
      .getCostReport(token)
      .then(setReport)
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : 'Unexpected error'))
  }, [token])

  if (error) {
    return <p className="text-sm text-red-600 dark:text-red-400">Failed to load cost report: {error}</p>
  }
  if (!report) {
    return <p className="text-sm text-gray-500">Loading...</p>
  }

  // `percent_used` from the API is a fraction (0.0-1.0+), not already 0-100 — see
  // BudgetEnforcer.check in src/aegis/cost/budgets.py.
  const percent = Math.min(100, report.percent_used * 100)
  const barColor =
    report.status === 'hard_stop'
      ? 'bg-red-500'
      : report.status === 'soft_alert'
        ? 'bg-amber-500'
        : 'bg-emerald-500'

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-800 dark:bg-gray-900">
      <h2 className="mb-4 text-base font-semibold">Month-to-date cost — {report.tenant_id}</h2>
      <div className="mb-2 flex items-baseline justify-between">
        <span className="text-2xl font-semibold">${report.month_to_date_usd.toFixed(4)}</span>
        <span className="text-sm text-gray-500">of ${report.monthly_budget_usd.toFixed(2)} budget</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-gray-800">
        <div className={`h-full ${barColor}`} style={{ width: `${percent}%` }} />
      </div>
      <p className="mt-2 text-sm text-gray-500">
        {percent.toFixed(1)}% used — status: <span className="font-medium">{report.status}</span>
      </p>
    </div>
  )
}
