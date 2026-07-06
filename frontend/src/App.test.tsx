import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const sendMagicLink = vi.hoisted(() => vi.fn())
const authState = vi.hoisted(() => ({
  value: {
    status: 'signed-out',
    user: null,
    accessToken: null,
    error: null,
    sendMagicLink,
    signOut: vi.fn(),
  },
}))

vi.mock('./auth/AuthProvider', () => ({
  useAuth: () => authState.value,
}))

describe('App trial authentication', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_DEPLOYMENT_MODE', 'trial')
    sendMagicLink.mockResolvedValue(undefined)
    authState.value = {
      status: 'signed-out',
      user: null,
      accessToken: null,
      error: null,
      sendMagicLink,
      signOut: vi.fn(),
    }
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.clearAllMocks()
  })

  it('uses Supabase magic links instead of the legacy enterprise SSO login', async () => {
    const { default: App } = await import('./App')

    render(<App />)

    expect(screen.queryByText(/Enterprise SSO/i)).not.toBeInTheDocument()
    expect(document.querySelector('a[href*="/auth/login"]')).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText(/Email address/i), {
      target: { value: ' Tester@Example.ORG ' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Email me a secure sign-in link/i }))

    await waitFor(() => {
      expect(sendMagicLink).toHaveBeenCalledWith('tester@example.org')
    })
  })

  it('shows the check-email state after requesting a magic link', async () => {
    authState.value = {
      ...authState.value,
      status: 'check-email',
    }
    const { default: App } = await import('./App')

    render(<App />)

    expect(screen.getByText(/Check your email/i)).toBeInTheDocument()
  })
})
