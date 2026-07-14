import '@testing-library/jest-dom/vitest'
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { fireEvent } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

import { AuthProvider, useAuth } from './AuthProvider'

const supabaseMock = vi.hoisted(() => {
  type TestSession = { access_token: string; user?: { email?: string } }
  type AuthStateCallback = (event: string, session: TestSession | null) => void

  let authStateCallback:
    | AuthStateCallback
    | null = null

  const client = {
    auth: {
      getSession: vi.fn(),
      onAuthStateChange: vi.fn((callback: AuthStateCallback) => {
        authStateCallback = callback

        return {
          data: {
            subscription: {
              unsubscribe: vi.fn(),
            },
          },
        }
      }),
      signInWithOtp: vi.fn(),
      signOut: vi.fn(),
    },
  }

  return {
    client,
    emitAuthState(
      event: string,
      session: TestSession | null
    ) {
      authStateCallback?.(event, session)
    },
    reset() {
      authStateCallback = null
      client.auth.getSession.mockReset()
      client.auth.onAuthStateChange.mockClear()
      client.auth.signInWithOtp.mockReset()
      client.auth.signOut.mockReset()
    },
  }
})

vi.mock('./supabase', () => ({
  getSupabaseClient: () => supabaseMock.client,
}))

function AuthProbe({ children }: { children?: ReactNode }) {
  const auth = useAuth()

  return (
    <div>
      <p>Status: {auth.status}</p>
      <p>Token: {auth.accessToken ?? 'none'}</p>
      <p>Email: {auth.user?.email ?? 'none'}</p>
      <p>Error: {auth.error ?? 'none'}</p>
      <button type="button" onClick={() => auth.sendMagicLink('reader@example.com')}>
        Send magic link
      </button>
      <button type="button" onClick={() => auth.signOut()}>
        Sign out
      </button>
      {children}
    </div>
  )
}

function renderAuthProvider() {
  return render(
    <AuthProvider>
      <AuthProbe />
    </AuthProvider>
  )
}

describe('AuthProvider', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_DEPLOYMENT_MODE', 'trial')
    window.history.replaceState({}, '', '/')
    supabaseMock.reset()
    supabaseMock.client.auth.signInWithOtp.mockResolvedValue({ data: {}, error: null })
    supabaseMock.client.auth.signOut.mockResolvedValue({ error: null })
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllEnvs()
  })

  it('starts in a loading state while Supabase restores the session', () => {
    supabaseMock.client.auth.getSession.mockReturnValue(new Promise(() => {}))

    renderAuthProvider()

    expect(screen.getByText('Status: loading')).toBeInTheDocument()
  })

  it('renders signed-out state when there is no active session', async () => {
    supabaseMock.client.auth.getSession.mockResolvedValue({
      data: { session: null },
      error: null,
    })

    renderAuthProvider()

    expect(await screen.findByText('Status: signed-out')).toBeInTheDocument()
    expect(screen.getByText('Token: none')).toBeInTheDocument()
  })

  it('sends a magic link and moves to check-email state', async () => {
    supabaseMock.client.auth.getSession.mockResolvedValue({
      data: { session: null },
      error: null,
    })

    renderAuthProvider()
    await screen.findByText('Status: signed-out')
    fireEvent.click(screen.getByRole('button', { name: 'Send magic link' }))

    expect(supabaseMock.client.auth.signInWithOtp).toHaveBeenCalledWith({
      email: 'reader@example.com',
      options: {
        emailRedirectTo: 'https://pdfaccess.org/remediate/auth/callback',
      },
    })
    expect(await screen.findByText('Status: check-email')).toBeInTheDocument()
  })

  it('exposes the signed-in user and access token from the restored session', async () => {
    supabaseMock.client.auth.getSession.mockResolvedValue({
      data: {
        session: {
          access_token: 'restored-token',
          user: { email: 'reader@example.com' },
        },
      },
      error: null,
    })

    renderAuthProvider()

    expect(await screen.findByText('Status: signed-in')).toBeInTheDocument()
    expect(screen.getByText('Token: restored-token')).toBeInTheDocument()
    expect(screen.getByText('Email: reader@example.com')).toBeInTheDocument()
  })

  it('updates auth state from the Supabase subscription', async () => {
    supabaseMock.client.auth.getSession.mockResolvedValue({
      data: { session: null },
      error: null,
    })

    renderAuthProvider()
    await screen.findByText('Status: signed-out')

    act(() => {
      supabaseMock.emitAuthState('SIGNED_IN', {
        access_token: 'event-token',
        user: { email: 'event@example.com' },
      })
    })

    expect(await screen.findByText('Status: signed-in')).toBeInTheDocument()
    expect(screen.getByText('Token: event-token')).toBeInTheDocument()
    expect(screen.getByText('Email: event@example.com')).toBeInTheDocument()
  })

  it('signs out and clears the current token', async () => {
    supabaseMock.client.auth.getSession.mockResolvedValue({
      data: {
        session: {
          access_token: 'restored-token',
          user: { email: 'reader@example.com' },
        },
      },
      error: null,
    })

    renderAuthProvider()
    await screen.findByText('Status: signed-in')
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))

    expect(supabaseMock.client.auth.signOut).toHaveBeenCalled()
    await waitFor(() => expect(screen.getByText('Status: signed-out')).toBeInTheDocument())
    expect(screen.getByText('Token: none')).toBeInTheDocument()
  })

  it('surfaces an expired magic-link callback error', async () => {
    window.history.replaceState(
      {},
      '',
      '/auth/callback?error=access_denied&error_description=Email%20link%20is%20invalid%20or%20has%20expired'
    )
    supabaseMock.client.auth.getSession.mockResolvedValue({
      data: { session: null },
      error: null,
    })

    renderAuthProvider()

    expect(await screen.findByText('Status: error')).toBeInTheDocument()
    expect(screen.getByText('Error: Email link is invalid or has expired')).toBeInTheDocument()
  })
})
