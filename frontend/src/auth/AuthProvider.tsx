import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import type { Session, User } from '@supabase/supabase-js'

import { registerTrialAccessTokenGetter } from '../api'
import { remediationAppUrl } from '../config'
import { getSupabaseClient } from './supabase'

type AuthStatus = 'loading' | 'signed-out' | 'check-email' | 'signed-in' | 'error'

interface AuthContextValue {
  status: AuthStatus
  user: User | null
  accessToken: string | null
  error: string | null
  sendMagicLink: (email: string) => Promise<void>
  signInWithPassword: (email: string, password: string) => Promise<void>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

function magicLinkCallbackError(): string | null {
  const query = new URLSearchParams(window.location.search)
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ''))

  return query.get('error_description') ?? hash.get('error_description')
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Authentication is unavailable'
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('loading')
  const [user, setUser] = useState<User | null>(null)
  const [accessToken, setAccessToken] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const applySession = useCallback((session: Session | null) => {
    setError(null)

    if (!session?.access_token) {
      setUser(null)
      setAccessToken(null)
      setStatus('signed-out')
      return
    }

    setUser(session.user)
    setAccessToken(session.access_token)
    setStatus('signed-in')
  }, [])

  const applyError = useCallback((message: string) => {
    setUser(null)
    setAccessToken(null)
    setError(message)
    setStatus('error')
  }, [])

  useEffect(() => registerTrialAccessTokenGetter(() => accessToken), [accessToken])

  useEffect(() => {
    let isActive = true
    let client

    try {
      client = getSupabaseClient()
    } catch (clientError) {
      applyError(errorMessage(clientError))
      return undefined
    }

    const callbackError = magicLinkCallbackError()

    if (!client) {
      applySession(null)
      return undefined
    }

    const {
      data: { subscription },
    } = client.auth.onAuthStateChange((_event, session) => {
      if (isActive) {
        applySession(session)
      }
    })

    client.auth
      .getSession()
      .then(({ data, error: sessionError }) => {
        if (!isActive) {
          return
        }

        if (callbackError) {
          applyError(callbackError)
          return
        }

        if (sessionError) {
          applyError(sessionError.message)
          return
        }

        applySession(data.session)
      })
      .catch((sessionError: Error) => {
        if (isActive) {
          applyError(sessionError.message)
        }
      })

    return () => {
      isActive = false
      subscription.unsubscribe()
    }
  }, [applyError, applySession])

  const sendMagicLink = useCallback(async (email: string) => {
    let client

    try {
      client = getSupabaseClient()
    } catch (clientError) {
      applyError(errorMessage(clientError))
      return
    }

    if (!client) {
      applyError('Authentication is unavailable')
      return
    }

    const { error: signInError } = await client.auth.signInWithOtp({
      email,
      options: {
        emailRedirectTo: `${remediationAppUrl()}/auth/callback`,
      },
    })

    if (signInError) {
      applyError(signInError.message)
      return
    }

    setError(null)
    setStatus('check-email')
  }, [applyError])

  const signInWithPassword = useCallback(async (email: string, password: string) => {
    let client

    try {
      client = getSupabaseClient()
    } catch (clientError) {
      applyError(errorMessage(clientError))
      return
    }

    if (!client) {
      applyError('Authentication is unavailable')
      return
    }

    const { data, error: signInError } = await client.auth.signInWithPassword({ email, password })

    if (signInError) {
      applyError(signInError.message)
      return
    }

    applySession(data.session)
  }, [applyError, applySession])

  const signOut = useCallback(async () => {
    let client

    try {
      client = getSupabaseClient()
    } catch (clientError) {
      applyError(errorMessage(clientError))
      return
    }

    if (!client) {
      applySession(null)
      return
    }

    const { error: signOutError } = await client.auth.signOut()

    if (signOutError) {
      applyError(signOutError.message)
      return
    }

    applySession(null)
  }, [applyError, applySession])

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      accessToken,
      error,
      sendMagicLink,
      signInWithPassword,
      signOut,
    }),
    [accessToken, error, sendMagicLink, signInWithPassword, signOut, status, user]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)

  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }

  return context
}
