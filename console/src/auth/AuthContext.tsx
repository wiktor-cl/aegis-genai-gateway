// The console never sees a role/tenant in advance — there is no "who am I"
// endpoint (see ADR-0005: RBAC is enforced at the query/API layer, not the
// presentation layer, so the console doesn't need to know the role to be
// secure — it only needs it to decide what to *show*). The token is exactly
// what routes_admin.py's `create_api_key` returns as `"{key_id}.{raw_secret}"`.

import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'

const STORAGE_KEY = 'aegis-console-token'

interface AuthContextValue {
  token: string | null
  signIn: (token: string) => void
  signOut: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() =>
    window.localStorage.getItem(STORAGE_KEY),
  )

  const value = useMemo<AuthContextValue>(
    () => ({
      token,
      signIn: (next: string) => {
        window.localStorage.setItem(STORAGE_KEY, next)
        setToken(next)
      },
      signOut: () => {
        window.localStorage.removeItem(STORAGE_KEY)
        setToken(null)
      },
    }),
    [token],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return ctx
}
