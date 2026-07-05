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
