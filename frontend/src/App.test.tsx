import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from './api'

const sendMagicLink = vi.hoisted(() => vi.fn())
const signOut = vi.hoisted(() => vi.fn())
const authState = vi.hoisted(() => ({
  value: {
    status: 'signed-out',
    user: null as { id: string; email?: string } | null,
    accessToken: null as string | null,
    error: null as string | null,
    sendMagicLink,
    signOut,
  },
}))

vi.mock('./auth/AuthProvider', () => ({
  useAuth: () => authState.value,
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
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn().mockReturnValue({
        matches: false,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    })
    sendMagicLink.mockResolvedValue(undefined)
    signOut.mockResolvedValue(undefined)
    authState.value = {
      status: 'signed-out',
      user: null,
      accessToken: null,
      error: null,
      sendMagicLink,
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
    authState.value = {
      ...authState.value,
      status: 'signed-in',
      user: { id: 'user-1', email: 'tester@example.org' },
      accessToken: 'trial-token',
    }
    vi.spyOn(api, 'getTrialBalance').mockResolvedValue(balance)
    const { default: App } = await import('./App')

    render(<App />)

    expect(screen.getByRole('button', { name: /Drop a PDF file/i })).toBeInTheDocument()
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

  it('renders the structured trial page-limit message from an upload 409', async () => {
    vi.stubEnv('VITE_DEPLOYMENT_MODE', 'trial')
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

    fireEvent.change(screen.getByLabelText(/PDF file upload/i), {
      target: { files: [new File(['pdf'], 'report.pdf', { type: 'application/pdf' })] },
    })

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(
        'This PDF has 64 pages; 12 trial pages remain.',
      )
    })
  })
})
