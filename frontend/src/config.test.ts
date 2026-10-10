import { afterEach, describe, expect, it, vi } from 'vitest'

import { deploymentMode, desktopDownloadUrl, publicAppOrigin, remediationAppUrl } from './config'

describe('deploymentMode', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it.each(['trial', 'testing'] as const)('accepts %s mode', (mode) => {
    vi.stubEnv('VITE_DEPLOYMENT_MODE', mode)

    expect(deploymentMode()).toBe(mode)
  })

  it('defaults to testing locally', () => {
    vi.stubEnv('VITE_DEPLOYMENT_MODE', '')

    expect(deploymentMode()).toBe('testing')
  })

  it('throws for unknown modes', () => {
    vi.stubEnv('VITE_DEPLOYMENT_MODE', 'production')

    expect(() => deploymentMode()).toThrow('Unknown deployment mode: production')
  })
})

describe('publicAppOrigin', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('uses the configured origin without path components', () => {
    vi.stubEnv('VITE_DEPLOYMENT_MODE', 'trial')
    vi.stubEnv('VITE_PUBLIC_APP_ORIGIN', 'https://preview.pdfaccess.org/some/path')

    expect(publicAppOrigin()).toBe('https://preview.pdfaccess.org')
  })

  it('defaults trial magic links to the canonical production origin', () => {
    vi.stubEnv('VITE_DEPLOYMENT_MODE', 'trial')
    vi.stubEnv('VITE_PUBLIC_APP_ORIGIN', '')

    expect(publicAppOrigin()).toBe('https://pdfaccess.org')
  })

  it('defaults testing magic links to the current browser origin', () => {
    vi.stubEnv('VITE_DEPLOYMENT_MODE', 'testing')
    vi.stubEnv('VITE_PUBLIC_APP_ORIGIN', '')

    expect(publicAppOrigin()).toBe(window.location.origin)
  })
})

describe('remediationAppUrl', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('places the remediation workspace below the canonical origin', () => {
    vi.stubEnv('VITE_DEPLOYMENT_MODE', 'trial')
    vi.stubEnv('VITE_PUBLIC_APP_ORIGIN', 'https://pdfaccess.org')

    expect(remediationAppUrl()).toBe('https://pdfaccess.org/remediate')
  })
})

describe('desktopDownloadUrl', () => {
  afterEach(() => { vi.unstubAllEnvs() })
  it('uses an explicitly published HTTPS download', () => {
    vi.stubEnv('VITE_DESKTOP_DOWNLOAD_URL', 'https://downloads.pdfaccess.org/app.zip')
    expect(desktopDownloadUrl()).toBe('https://downloads.pdfaccess.org/app.zip')
  })
  it.each(['', 'javascript:alert(1)', 'http://example.org/app.zip', 'https://user:pass@example.org/app.zip'])('does not expose an unavailable or unsafe link: %s', (url) => {
    vi.stubEnv('VITE_DESKTOP_DOWNLOAD_URL', url)
    expect(desktopDownloadUrl()).toBeNull()
  })
})
