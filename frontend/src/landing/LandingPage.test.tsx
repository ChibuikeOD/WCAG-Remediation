import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
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

vi.mock('../auth/AuthProvider', () => ({
  useAuth: () => authState.value,
}))

describe('LandingPage', () => {
  beforeEach(() => {
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
    cleanup()
    vi.clearAllMocks()
  })

  it('presents the PDFAccess free-trial offer and support link', async () => {
    const { LandingPage } = await import('./LandingPage')

    render(<LandingPage />)

    expect(screen.getAllByText('PDFAccess').length).toBeGreaterThan(0)
    expect(screen.getAllByText(/200 pages/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/400 pages/i).length).toBeGreaterThan(0)
    expect(screen.getByLabelText(/Email address/i)).toBeInTheDocument()

    const supportLink = screen.getByRole('link', { name: /Ask a question/i })
    expect(supportLink).toHaveAttribute('href', 'mailto:support@pdfaccess.org')
  })

  it('submits a normalized email address through the magic-link provider', async () => {
    const { LandingPage } = await import('./LandingPage')

    render(<LandingPage />)

    fireEvent.change(screen.getByLabelText(/Email address/i), {
      target: { value: ' Applicant@University.EDU ' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Start free trial/i }))

    await waitFor(() => {
      expect(sendMagicLink).toHaveBeenCalledWith('applicant@university.edu')
    })
  })

  it('shows the check-email state from the auth provider', async () => {
    authState.value = {
      ...authState.value,
      status: 'check-email',
    }
    const { LandingPage } = await import('./LandingPage')

    render(<LandingPage />)

    expect(screen.getByText(/Check your email/i)).toBeInTheDocument()
  })

  it('opens and closes a keyboard-accessible mobile menu', async () => {
    const { LandingPage } = await import('./LandingPage')

    render(<LandingPage />)

    const openButton = screen.getByRole('button', { name: /Open menu/i })
    expect(openButton).toHaveAttribute('aria-expanded', 'false')

    fireEvent.click(openButton)

    expect(openButton).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('dialog', { name: /Mobile navigation/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Trial allowances/i })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Close menu/i }))

    expect(screen.queryByRole('dialog', { name: /Mobile navigation/i })).not.toBeInTheDocument()
    expect(openButton).toHaveAttribute('aria-expanded', 'false')
  })
})
