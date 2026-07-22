import { useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import type { AgentRunSummary } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { StatusBadge } from '../components/StatusBadge'

const DATA_CLASSIFICATIONS = ['public', 'internal', 'confidential', 'restricted']
const COST_TIERS = ['economy', 'standard', 'premium']

export function RunsPage() {
  const { token } = useAuth()
  const [runs, setRuns] = useState<AgentRunSummary[] | null>(null)
  const [listError, setListError] = useState<string | null>(null)

  const [agentName, setAgentName] = useState('demo')
  const [systemPrompt, setSystemPrompt] = useState('You are a helpful assistant with access to tools.')
  const [userMessage, setUserMessage] = useState('')
  const [dataClassification, setDataClassification] = useState('internal')
  const [costTier, setCostTier] = useState('standard')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  function reload() {
    if (!token) return
    api
      .listRuns(token)
      .then(setRuns)
      .catch((err: unknown) => setListError(err instanceof ApiError ? err.message : 'Unexpected error'))
  }

  useEffect(reload, [token])

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!token || !userMessage.trim()) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      await api.triggerRun(token, {
        agent_name: agentName,
        system_prompt: systemPrompt,
        user_message: userMessage,
        data_classification: dataClassification,
        cost_tier: costTier,
      })
      setUserMessage('')
      reload()
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : 'Unexpected error')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-6">
      <form
        onSubmit={handleSubmit}
        className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-800 dark:bg-gray-900"
      >
        <h2 className="mb-3 text-base font-semibold">Trigger a new agent run</h2>
        <div className="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="text-sm">
            Agent name
            <input
              value={agentName}
              onChange={(e) => setAgentName(e.target.value)}
              className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-800"
            />
          </label>
          <label className="text-sm">
            Data classification
            <select
              value={dataClassification}
              onChange={(e) => setDataClassification(e.target.value)}
              className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-800"
            >
              {DATA_CLASSIFICATIONS.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            Cost tier
            <select
              value={costTier}
              onChange={(e) => setCostTier(e.target.value)}
              className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-800"
            >
              {COST_TIERS.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="mb-3 block text-sm">
          System prompt
          <input
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-800"
          />
        </label>
        <label className="mb-3 block text-sm">
          User message
          <textarea
            value={userMessage}
            onChange={(e) => setUserMessage(e.target.value)}
            rows={3}
            required
            className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-800"
          />
        </label>
        {submitError && <p className="mb-3 text-sm text-red-600 dark:text-red-400">{submitError}</p>}
        <button
          type="submit"
          disabled={submitting}
          className="rounded-md bg-violet-600 px-3 py-2 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-50"
        >
          {submitting ? 'Running...' : 'Run agent'}
        </button>
      </form>

      <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-800 dark:bg-gray-900">
        <h2 className="mb-3 text-base font-semibold">Recent runs</h2>
        {listError && <p className="text-sm text-red-600 dark:text-red-400">{listError}</p>}
        {!runs && !listError && <p className="text-sm text-gray-500">Loading...</p>}
        {runs && runs.length === 0 && <p className="text-sm text-gray-500">No runs yet.</p>}
        {runs && runs.length > 0 && (
          <table className="w-full text-left text-sm">
            <thead className="text-gray-500">
              <tr>
                <th className="pb-2 pr-4 font-medium">Agent</th>
                <th className="pb-2 pr-4 font-medium">Status</th>
                <th className="pb-2 pr-4 font-medium">Steps</th>
                <th className="pb-2 pr-4 font-medium">Tokens (in/out)</th>
                <th className="pb-2 font-medium">Created</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.run_id} className="border-t border-gray-100 dark:border-gray-800">
                  <td className="py-2 pr-4">
                    <Link to={`/runs/${run.run_id}`} className="text-violet-600 hover:underline dark:text-violet-400">
                      {run.agent_name}
                    </Link>
                  </td>
                  <td className="py-2 pr-4">
                    <StatusBadge status={run.status} />
                  </td>
                  <td className="py-2 pr-4">{run.step_count}</td>
                  <td className="py-2 pr-4">
                    {run.total_input_tokens} / {run.total_output_tokens}
                  </td>
                  <td className="py-2 text-gray-500">{new Date(run.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
