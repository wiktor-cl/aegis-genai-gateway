import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

export function LoginPage() {
  const { signIn } = useAuth()
  const navigate = useNavigate()
  const [token, setToken] = useState('')

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!token.trim()) return
    signIn(token.trim())
    navigate('/')
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 dark:bg-gray-950">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-800 dark:bg-gray-900"
      >
        <h1 className="mb-1 text-xl font-semibold text-gray-900 dark:text-gray-100">
          Aegis Console
        </h1>
        <p className="mb-4 text-sm text-gray-500 dark:text-gray-400">
          Paste an API key issued by an admin (<code>key_id.secret</code>). Nothing is sent
          anywhere except this Aegis API — see <code>src/aegis/tenancy/rbac.py</code>.
        </p>
        <label htmlFor="token" className="mb-1 block text-sm font-medium">
          API key
        </label>
        <input
          id="token"
          type="password"
          autoComplete="off"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder="a1b2c3.raw-secret-here"
          className="mb-4 w-full rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-800"
        />
        <button
          type="submit"
          className="w-full rounded-md bg-violet-600 px-3 py-2 text-sm font-medium text-white hover:bg-violet-700"
        >
          Sign in
        </button>
      </form>
    </div>
  )
}
