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
})
