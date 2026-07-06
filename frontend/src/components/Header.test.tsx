import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { Header } from './Header'

describe('Header trial logout', () => {
  it('uses the provided Supabase sign-out handler instead of the legacy logout URL', async () => {
    const signOut = vi.fn().mockResolvedValue(undefined)

    render(
      <Header
        onNewAnalysis={vi.fn()}
        onSignOut={signOut}
        showNewButton={false}
        user={{ authenticated: true, email: 'tester@pdfaccess.org' }}
      />
    )

    expect(document.querySelector('a[href="/api/auth/logout"]')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Sign out of PDFAccess/i }))

    await waitFor(() => {
      expect(signOut).toHaveBeenCalled()
    })
  })
})
