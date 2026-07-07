import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const getBillingCatalog = vi.hoisted(() => vi.fn())
const createCheckoutSession = vi.hoisted(() => vi.fn())
const createSubscriptionCheckoutSession = vi.hoisted(() => vi.fn())
const requestInstitutionalInvoice = vi.hoisted(() => vi.fn())

vi.mock('../api', () => ({
  getBillingCatalog,
  createCheckoutSession,
  createSubscriptionCheckoutSession,
  requestInstitutionalInvoice,
}))

describe('BillingPanel', () => {
  beforeEach(() => {
    getBillingCatalog.mockRejectedValue(new Error('offline'))
    createCheckoutSession.mockReturnValue(new Promise(() => {}))
    createSubscriptionCheckoutSession.mockReturnValue(new Promise(() => {}))
    requestInstitutionalInvoice.mockReturnValue(new Promise(() => {}))
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('starts a subscription checkout for the selected annual plan', async () => {
    const { BillingPanel } = await import('./BillingPanel')

    render(
      <BillingPanel
        user={{ authenticated: true, name: 'Avery Buyer', email: 'avery@example.org' }}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Subscribe by card/i }))

    await waitFor(() => {
      expect(createSubscriptionCheckoutSession).toHaveBeenCalledWith({
        plan_key: 'library',
        service_mode: 'remediation',
      })
    })
  })
})
