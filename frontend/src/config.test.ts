import { afterEach, describe, expect, it, vi } from 'vitest'

import { deploymentMode } from './config'

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
