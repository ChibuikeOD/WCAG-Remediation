import '@testing-library/jest-dom/vitest'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const sendMagicLink = vi.hoisted(() => vi.fn())
let mediaChangeHandler: ((event: MediaQueryListEvent) => void) | null = null
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
    mediaChangeHandler = null
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn().mockImplementation(() => ({
        matches: false,
        addEventListener: (_event: string, handler: (event: MediaQueryListEvent) => void) => {
          mediaChangeHandler = handler
        },
        removeEventListener: vi.fn(),
      })),
    })
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

    expect(screen.getByRole('link', { name: /Skip to main content/i })).toHaveAttribute(
      'href',
      '#main-content',
    )
    expect(screen.getByRole('main')).toHaveAttribute('id', 'main-content')
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

  it('associates validation errors with the email field', async () => {
    const { LandingPage } = await import('./LandingPage')

    render(<LandingPage />)

    const emailInput = screen.getByLabelText(/Email address/i)
    fireEvent.click(screen.getByRole('button', { name: /Start free trial/i }))

    const error = screen.getByRole('alert')
    expect(emailInput).toHaveAttribute('aria-invalid', 'true')
    expect(emailInput).toHaveAttribute('aria-describedby', error.id)
  })

  it('moves focus into the mobile menu and restores it after Escape', async () => {
    const { LandingPage } = await import('./LandingPage')

    render(<LandingPage />)

    const openButton = screen.getByRole('button', { name: /Open menu/i })
    expect(openButton).toHaveAttribute('aria-expanded', 'false')

    fireEvent.click(openButton)

    expect(openButton).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('dialog', { name: /Mobile navigation/i })).toHaveAttribute('aria-modal', 'true')
    expect(screen.getByRole('link', { name: /Trial allowances/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Close menu/i })).toHaveFocus()

    fireEvent.keyDown(document, { key: 'Escape' })

    expect(screen.queryByRole('dialog', { name: /Mobile navigation/i })).not.toBeInTheDocument()
    expect(openButton).toHaveAttribute('aria-expanded', 'false')
    expect(openButton).toHaveFocus()
  })

  it('traps forward and backward focus within the mobile menu', async () => {
    const { LandingPage } = await import('./LandingPage')

    render(<LandingPage />)

    fireEvent.click(screen.getByRole('button', { name: /Open menu/i }))

    const dialog = screen.getByRole('dialog', { name: /Mobile navigation/i })
    const closeButton = within(dialog).getByRole('button', { name: /Close menu/i })
    const lastLink = within(dialog).getByRole('link', { name: /Security/i })

    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true })
    expect(lastLink).toHaveFocus()

    fireEvent.keyDown(document, { key: 'Tab' })
    expect(closeButton).toHaveFocus()
  })

  it('closes the mobile menu when the desktop breakpoint becomes active', async () => {
    const { LandingPage } = await import('./LandingPage')

    render(<LandingPage />)

    const openButton = screen.getByRole('button', { name: /Open menu/i })
    fireEvent.click(openButton)
    expect(screen.getByRole('dialog', { name: /Mobile navigation/i })).toBeInTheDocument()

    act(() => {
      mediaChangeHandler?.({ matches: true } as MediaQueryListEvent)
    })

    expect(screen.queryByRole('dialog', { name: /Mobile navigation/i })).not.toBeInTheDocument()
    expect(openButton).toHaveAttribute('aria-expanded', 'false')
    expect(openButton).toHaveFocus()
  })
})
