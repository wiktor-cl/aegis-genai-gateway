import { useState, type FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import type { ApiKeyOut, Role } from '../api/types'
import { useAuth } from '../auth/AuthContext'

const ROLES: Role[] = ['admin', 'developer', 'viewer']

export function AdminPage() {
  const { token } = useAuth()
  const [tenantId, setTenantId] = useState('')
  const [role, setRole] = useState<Role>('developer')
  const [created, setCreated] = useState<ApiKeyOut | null>(null)
  const [createError, setCreateError] = useState<string | null>(null)

  const [rotateKeyId, setRotateKeyId] = useState('')
  const [rotated, setRotated] = useState<ApiKeyOut | null>(null)
  const [rotateError, setRotateError] = useState<string | null>(null)

  const [revokeKeyId, setRevokeKeyId] = useState('')
  const [revokeStatus, setRevokeStatus] = useState<string | null>(null)
  const [revokeError, setRevokeError] = useState<string | null>(null)

  async function handleCreate(event: FormEvent) {
    event.preventDefault()
    if (!token || !tenantId.trim()) return
    setCreateError(null)
    setCreated(null)
    try {
      setCreated(await api.createApiKey(token, tenantId.trim(), role))
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : 'Unexpected error')
    }
  }

  async function handleRotate(event: FormEvent) {
    event.preventDefault()
    if (!token || !rotateKeyId.trim()) return
    setRotateError(null)
    setRotated(null)
    try {
      setRotated(await api.rotateApiKey(token, rotateKeyId.trim()))
    } catch (err) {
      setRotateError(err instanceof ApiError ? err.message : 'Unexpected error')
    }
  }

  async function handleRevoke(event: FormEvent) {
    event.preventDefault()
    if (!token || !revokeKeyId.trim()) return
    setRevokeError(null)
    setRevokeStatus(null)
    try {
      await api.revokeApiKey(token, revokeKeyId.trim())
      setRevokeStatus(`Key ${revokeKeyId.trim()} revoked.`)
    } catch (err) {
      setRevokeError(err instanceof ApiError ? err.message : 'Unexpected error')
    }
  }

  return (
    <div className="space-y-6">
      <p className="rounded-md bg-amber-50 p-3 text-sm text-amber-800 dark:bg-amber-900/30 dark:text-amber-300">
        These actions require the <code>admin</code> role (see ADR-0005) — the API rejects them
        with 403 for any other role, regardless of what this page shows.
      </p>

      <form
        onSubmit={handleCreate}
        className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-800 dark:bg-gray-900"
      >
        <h2 className="mb-3 text-base font-semibold">Create API key</h2>
        <div className="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="text-sm">
            Tenant ID
            <input
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              placeholder="acme-support"
              className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-800"
            />
          </label>
          <label className="text-sm">
            Role
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as Role)}
              className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-800"
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </label>
        </div>
        {createError && <p className="mb-3 text-sm text-red-600 dark:text-red-400">{createError}</p>}
        {created && (
          <p className="mb-3 rounded-md bg-emerald-50 p-3 text-sm text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300">
            Created <code>{created.key_id}</code> for {created.tenant_id} ({created.role}). Secret
            (shown once): <code className="break-all">{created.raw_secret}</code>
          </p>
        )}
        <button
          type="submit"
          className="rounded-md bg-violet-600 px-3 py-2 text-sm font-medium text-white hover:bg-violet-700"
        >
          Create
        </button>
      </form>

      <form
        onSubmit={handleRotate}
        className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-800 dark:bg-gray-900"
      >
        <h2 className="mb-3 text-base font-semibold">Rotate API key</h2>
        <label className="mb-3 block text-sm">
          Key ID
          <input
            value={rotateKeyId}
            onChange={(e) => setRotateKeyId(e.target.value)}
            className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-800"
          />
        </label>
        {rotateError && <p className="mb-3 text-sm text-red-600 dark:text-red-400">{rotateError}</p>}
        {rotated && (
          <p className="mb-3 rounded-md bg-emerald-50 p-3 text-sm text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300">
            New key <code>{rotated.key_id}</code>. Secret (shown once):{' '}
            <code className="break-all">{rotated.raw_secret}</code>
          </p>
        )}
        <button
          type="submit"
          className="rounded-md bg-violet-600 px-3 py-2 text-sm font-medium text-white hover:bg-violet-700"
        >
          Rotate
        </button>
      </form>

      <form
        onSubmit={handleRevoke}
        className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-800 dark:bg-gray-900"
      >
        <h2 className="mb-3 text-base font-semibold">Revoke API key</h2>
        <label className="mb-3 block text-sm">
          Key ID
          <input
            value={revokeKeyId}
            onChange={(e) => setRevokeKeyId(e.target.value)}
            className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-800"
          />
        </label>
        {revokeError && <p className="mb-3 text-sm text-red-600 dark:text-red-400">{revokeError}</p>}
        {revokeStatus && <p className="mb-3 text-sm text-emerald-700 dark:text-emerald-400">{revokeStatus}</p>}
        <button
          type="submit"
          className="rounded-md bg-red-600 px-3 py-2 text-sm font-medium text-white hover:bg-red-700"
        >
          Revoke
        </button>
      </form>
    </div>
  )
}
