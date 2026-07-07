import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

describe('API auth headers', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_URL', '')
    vi.resetModules()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
  })

  it('preserves same-origin calls without Authorization in testing mode', async () => {
    vi.stubEnv('VITE_DEPLOYMENT_MODE', 'testing')
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'ok', rules_loaded: 1, timestamp: 'now' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const api = await import('./api')
    api.registerTrialAccessTokenGetter(() => 'trial-token')
    await api.healthCheck()

    expect(fetchMock).toHaveBeenCalledWith('/api/health', {
      headers: {
        'Content-Type': 'application/json',
      },
    })
  })

  it('attaches a bearer token from the registered getter in trial mode', async () => {
    vi.stubEnv('VITE_DEPLOYMENT_MODE', 'trial')
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const api = await import('./api')
    api.registerTrialAccessTokenGetter(() => 'trial-token')
    await api.analyzeDocument({ file_id: 'file-1', target_level: 'AA' })

    expect(fetchMock).toHaveBeenCalledWith('/api/analyze', {
      method: 'POST',
      body: JSON.stringify({ file_id: 'file-1', target_level: 'AA' }),
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer trial-token',
      },
    })
  })

  it('attaches a bearer token to file uploads in trial mode', async () => {
    vi.stubEnv('VITE_DEPLOYMENT_MODE', 'trial')
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, file_id: 'file-1' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const api = await import('./api')
    api.registerTrialAccessTokenGetter(() => 'trial-token')
    await api.uploadFile(new File(['pdf'], 'sample.pdf', { type: 'application/pdf' }))

    expect(fetchMock).toHaveBeenCalledWith('/api/upload', {
      method: 'POST',
      body: expect.any(FormData),
      headers: {
        Authorization: 'Bearer trial-token',
      },
    })
  })

  it('downloads remediated files with a bearer token in trial mode', async () => {
    vi.stubEnv('VITE_DEPLOYMENT_MODE', 'trial')
    const blob = new Blob(['fixed'])
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: async () => blob,
    })
    vi.stubGlobal('fetch', fetchMock)

    const api = await import('./api')
    api.registerTrialAccessTokenGetter(() => 'trial-token')
    await expect(api.downloadRemediatedFile('report-1')).resolves.toBe(blob)

    expect(fetchMock).toHaveBeenCalledWith('/api/remediate/download/report-1', {
      headers: {
        Authorization: 'Bearer trial-token',
      },
    })
  })

  it('omits Authorization in trial mode when the getter has no token', async () => {
    vi.stubEnv('VITE_DEPLOYMENT_MODE', 'trial')
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'ok', rules_loaded: 1, timestamp: 'now' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const api = await import('./api')
    api.registerTrialAccessTokenGetter(() => null)
    await api.healthCheck()

    expect(fetchMock).toHaveBeenCalledWith('/api/health', {
      headers: {
        'Content-Type': 'application/json',
      },
    })
  })

  it('fetches the authenticated trial balance', async () => {
    vi.stubEnv('VITE_DEPLOYMENT_MODE', 'trial')
    const balance = {
      granted_pages: 200,
      consumed_pages: 25,
      reserved_pages: 5,
      remaining_pages: 170,
      normalized_domain: 'example.org',
      eligibility_rule_version: '2026-07-04',
    }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => balance,
    })
    vi.stubGlobal('fetch', fetchMock)

    const api = await import('./api')
    api.registerTrialAccessTokenGetter(() => 'trial-token')

    await expect(api.getTrialBalance()).resolves.toEqual(balance)
    expect(fetchMock).toHaveBeenCalledWith('/api/trial/me', {
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer trial-token',
      },
    })
  })

  it('creates a Stripe checkout session with the authenticated bearer token', async () => {
    vi.stubEnv('VITE_DEPLOYMENT_MODE', 'trial')
    const response = {
      purchase_id: 'purchase-1',
      checkout_session_id: 'cs_test_123',
      url: 'https://checkout.stripe.test/pay',
    }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => response,
    })
    vi.stubGlobal('fetch', fetchMock)

    const api = await import('./api')
    api.registerTrialAccessTokenGetter(() => 'trial-token')

    await expect(api.createCheckoutSession({
      pack_key: 'starter',
      service_mode: 'audit',
    })).resolves.toEqual(response)
    expect(fetchMock).toHaveBeenCalledWith('/api/billing/checkout-session', {
      method: 'POST',
      body: JSON.stringify({ service_mode: 'audit', pack_key: 'starter' }),
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer trial-token',
      },
    })
  })

  it('creates a Stripe subscription checkout session with the authenticated bearer token', async () => {
    vi.stubEnv('VITE_DEPLOYMENT_MODE', 'trial')
    const response = {
      purchase_id: 'subscription-1',
      checkout_session_id: 'cs_sub_123',
      url: 'https://checkout.stripe.test/subscription',
    }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => response,
    })
    vi.stubGlobal('fetch', fetchMock)

    const api = await import('./api')
    api.registerTrialAccessTokenGetter(() => 'trial-token')

    await expect(api.createSubscriptionCheckoutSession({
      plan_key: 'library',
      service_mode: 'audit',
    })).resolves.toEqual(response)
    expect(fetchMock).toHaveBeenCalledWith('/api/billing/subscription-checkout-session', {
      method: 'POST',
      body: JSON.stringify({ service_mode: 'audit', plan_key: 'library' }),
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer trial-token',
      },
    })
  })

  it('submits institutional invoice requests through the billing API', async () => {
    vi.stubEnv('VITE_DEPLOYMENT_MODE', 'trial')
    const response = {
      request_id: 'invoice-request-1',
      purchase_id: 'purchase-1',
      plan_key: 'library',
      service_mode: 'remediation',
      domain_verified: true,
      status: 'requested',
    }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => response,
    })
    vi.stubGlobal('fetch', fetchMock)

    const api = await import('./api')
    api.registerTrialAccessTokenGetter(() => 'trial-token')

    await expect(api.requestInstitutionalInvoice({
      plan_key: 'library',
      organization_name: 'City Library',
      contact_name: 'Avery Buyer',
      contact_email: 'avery@library.org',
      po_number: 'PO-42',
    })).resolves.toEqual(response)
    expect(fetchMock).toHaveBeenCalledWith('/api/billing/invoice-request', {
      method: 'POST',
      body: JSON.stringify({
        service_mode: 'remediation',
        plan_key: 'library',
        organization_name: 'City Library',
        contact_name: 'Avery Buyer',
        contact_email: 'avery@library.org',
        po_number: 'PO-42',
      }),
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer trial-token',
      },
    })
  })
})
