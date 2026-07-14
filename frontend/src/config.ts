const deploymentModes = ['trial', 'testing'] as const

export type DeploymentMode = (typeof deploymentModes)[number]

function isDeploymentMode(value: string): value is DeploymentMode {
  return deploymentModes.includes(value as DeploymentMode)
}

export function deploymentMode(): DeploymentMode {
  const mode = import.meta.env.VITE_DEPLOYMENT_MODE || 'testing'

  if (isDeploymentMode(mode)) {
    return mode
  }

  throw new Error(`Unknown deployment mode: ${mode}`)
}

export function publicAppOrigin(): string {
  const configuredOrigin = import.meta.env.VITE_PUBLIC_APP_ORIGIN as string | undefined

  if (configuredOrigin) return new URL(configuredOrigin).origin
  if (deploymentMode() === 'trial') return 'https://pdfaccess.org'
  return window.location.origin
}

export function remediationAppUrl(): string {
  return `${publicAppOrigin()}/remediate`
}
