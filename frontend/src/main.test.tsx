import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

const renderRoot = vi.hoisted(() => vi.fn())

vi.mock('react-dom/client', () => ({
  default: {
    createRoot: () => ({
      render: renderRoot,
    }),
  },
}))

vi.mock('./App', () => ({
  default: () => <div>Workspace</div>,
}))

vi.mock('./auth/AuthProvider', () => ({
  AuthProvider: ({ children }: { children: ReactNode }) => (
    <div data-testid="auth-provider">{children}</div>
  ),
}))

describe('main', () => {
  afterEach(() => {
    vi.resetModules()
    renderRoot.mockClear()
    document.body.innerHTML = ''
  })

  it('mounts the app inside AuthProvider', async () => {
    document.body.innerHTML = '<div id="root"></div>'

    await import('./main')
    render(renderRoot.mock.calls[0][0])

    expect(screen.getByTestId('auth-provider')).toHaveTextContent('Workspace')
  })
})
