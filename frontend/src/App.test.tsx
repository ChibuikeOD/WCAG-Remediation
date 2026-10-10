import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from './api'

const sendMagicLink = vi.hoisted(() => vi.fn())
const signOut = vi.hoisted(() => vi.fn())
const signInWithPassword = vi.hoisted(() => vi.fn())
const authState = vi.hoisted(() => ({
  value: {
    status: 'signed-out',
    user: null as { id: string; email?: string } | null,
    accessToken: null as string | null,
    error: null as string | null,
    sendMagicLink,
    signInWithPassword,
    signOut,
  },
}))

vi.mock('./auth/AuthProvider', () => ({
  useAuth: () => authState.value,
}))

const profiles = vi.hoisted(() => ({
  load: vi.fn(),
  update: vi.fn(),
  updateForUser: vi.fn(),
}))

vi.mock('./auth/supabase', () => ({
  getSupabaseClient: () => ({
    from: () => ({
      select: () => ({ eq: () => ({ maybeSingle: profiles.load }) }),
      update: (values: unknown) => {
        profiles.update(values)
        return { eq: profiles.updateForUser }
      },
    }),
  }),
}))

const balance: api.TrialBalance = {
  granted_pages: 200,
  consumed_pages: 25,
  reserved_pages: 5,
  remaining_pages: 170,
  normalized_domain: 'example.org',
  eligibility_rule_version: '2026-07-04',
}

describe('App deployment routing', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/')
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn().mockReturnValue({
        matches: false,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    })
    sendMagicLink.mockResolvedValue(undefined)
    signInWithPassword.mockResolvedValue(undefined)
    signOut.mockResolvedValue(undefined)
    profiles.load.mockReset().mockResolvedValue({
      data: { welcome_completed_at: '2026-07-11T00:00:00Z' }, error: null,
    })
    profiles.update.mockClear()
    profiles.updateForUser.mockReset().mockResolvedValue({ error: null })
    authState.value = {
      status: 'signed-out',
      user: null,
      accessToken: null,
      error: null,
      sendMagicLink,
      signInWithPassword,
      signOut,
    }
    vi.spyOn(api, 'getBillingCatalog').mockRejectedValue(new Error('offline'))
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
  })

  it('renders the public landing page for a signed-out trial user', async () => {
    vi.stubEnv('VITE_DEPLOYMENT_MODE', 'trial')
    const { default: App } = await import('./App')

    render(<App />)

    expect(screen.getByRole('heading', { name: /Accessible PDFs/i })).toBeInTheDocument()
    expect(screen.getByLabelText(/Email address/i)).toBeInTheDocument()
  })

  it('renders the workspace and trial balance for a signed-in trial user', async () => {
    vi.stubEnv('VITE_DEPLOYMENT_MODE', 'trial')
    window.history.replaceState({}, '', '/remediate')
    authState.value = {
      ...authState.value,
      status: 'signed-in',
      user: { id: 'user-1', email: 'tester@example.org' },
      accessToken: 'trial-token',
    }
    vi.spyOn(api, 'getTrialBalance').mockResolvedValue(balance)
    const { default: App } = await import('./App')

    render(<App />)

    expect(await screen.findByRole('button', { name: /Drop a PDF file/i })).toBeInTheDocument()
    expect(await screen.findByText(/170 of 200 trial pages remaining/i)).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: /Trial pages used/i })).toHaveAttribute(
      'aria-valuenow',
      '30',
    )
  })

  it('opens the unrestricted workspace directly in testing mode', async () => {
    vi.stubEnv('VITE_DEPLOYMENT_MODE', 'testing')
    const balanceSpy = vi.spyOn(api, 'getTrialBalance')
    const { default: App } = await import('./App')

    render(<App />)

    expect(screen.getByRole('button', { name: /Drop a PDF file/i })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /Accessible PDFs/i })).not.toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: /Page credits and institutional billing/i }),
    ).not.toBeInTheDocument()
    expect(balanceSpy).not.toHaveBeenCalled()
  })

  it('renders a dedicated login page for existing users', async () => {
    vi.stubEnv('VITE_DEPLOYMENT_MODE', 'trial')
    window.history.replaceState({}, '', '/login')
    const { default: App } = await import('./App')

    render(<App />)

    expect(screen.getByRole('heading', { name: /Log in to PDFAccess/i })).toBeInTheDocument()
    expect(screen.getByLabelText(/Username or email address/i)).toHaveAttribute('autocomplete', 'username')
    expect(screen.getByLabelText(/Password/i)).toBeInTheDocument()
    expect(screen.queryByText(/200 pages/i)).not.toBeInTheDocument()
  })

  it('requires registration before showing the signed-in trial workspace', async () => {
    vi.stubEnv('VITE_DEPLOYMENT_MODE', 'trial')
    window.history.replaceState({}, '', '/remediate')
    authState.value = { ...authState.value, status: 'signed-in', user: { id: 'user-1', email: 'tester@example.org' } }
    profiles.load.mockResolvedValue({ data: null, error: null })
    vi.spyOn(api, 'getTrialBalance').mockResolvedValue(balance)
    const { default: App } = await import('./App')

    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Complete your registration' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Drop a PDF file/i })).not.toBeInTheDocument()
  })

  it('records welcome completion for the current user before opening the workspace', async () => {
    vi.stubEnv('VITE_DEPLOYMENT_MODE', 'trial')
    window.history.replaceState({}, '', '/remediate')
    authState.value = { ...authState.value, status: 'signed-in', user: { id: 'user-1', email: 'tester@example.org' } }
    profiles.load.mockResolvedValue({ data: { welcome_completed_at: null }, error: null })
    vi.spyOn(api, 'getTrialBalance').mockResolvedValue(balance)
    const { default: App } = await import('./App')

    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: /Start Remediating/i }))

    expect(await screen.findByRole('button', { name: /Drop a PDF file/i })).toBeInTheDocument()
    expect(profiles.update).toHaveBeenCalledWith({ welcome_completed_at: expect.any(String) })
    expect(profiles.updateForUser).toHaveBeenCalledWith('user_id', 'user-1')
  })

  it('keeps the public website at the root for a signed-in trial user', async () => {
    vi.stubEnv('VITE_DEPLOYMENT_MODE', 'trial')
    authState.value = {
      ...authState.value,
      status: 'signed-in',
      user: { id: 'user-1', email: 'tester@example.org' },
      accessToken: 'trial-token',
    }
    const { default: App } = await import('./App')

    render(<App />)

    expect(screen.getByRole('heading', { name: /Accessible PDFs/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Drop a PDF file/i })).not.toBeInTheDocument()
  })

  it('renders the structured trial page-limit message from an upload 409', async () => {
    vi.stubEnv('VITE_DEPLOYMENT_MODE', 'trial')
    window.history.replaceState({}, '', '/remediate')
    authState.value = {
      ...authState.value,
      status: 'signed-in',
      user: { id: 'user-1', email: 'tester@example.org' },
      accessToken: 'trial-token',
    }
    vi.spyOn(api, 'getTrialBalance').mockResolvedValue(balance)
    vi.spyOn(api, 'uploadFile').mockRejectedValue(
      new api.APIError(409, 'Trial page limit exceeded', {
        code: 'trial_page_limit_exceeded',
        requested_pages: 64,
        remaining_pages: 12,
      }),
    )
    const { default: App } = await import('./App')

    render(<App />)

    fireEvent.change(await screen.findByLabelText(/PDF file upload/i), {
      target: { files: [new File(['pdf'], 'report.pdf', { type: 'application/pdf' })] },
    })

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(
        'This PDF has 64 pages; 12 trial pages remain.',
      )
    })
  })
})
