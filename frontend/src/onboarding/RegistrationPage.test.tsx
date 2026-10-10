import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { User } from '@supabase/supabase-js'

import { RegistrationPage } from './RegistrationPage'

const profile = vi.hoisted(() => ({ updateUser: vi.fn(), upsert: vi.fn() }))
vi.mock('../auth/supabase', () => ({
  getSupabaseClient: () => ({
    auth: { updateUser: profile.updateUser },
    from: () => ({ upsert: profile.upsert }),
  }),
}))

const user = { id: 'current-user', email: 'reader@example.org' } as User
const onComplete = vi.fn()

function fillRegistration(confirmPassword = 'valid-password') {
  fireEvent.change(screen.getByLabelText('Full name'), { target: { value: '  Reader Name  ' } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'valid-password' } })
  fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: confirmPassword } })
}

describe('RegistrationPage', () => {
  beforeEach(() => {
    profile.updateUser.mockReset().mockResolvedValue({ error: null })
    profile.upsert.mockReset().mockResolvedValue({ error: null })
    onComplete.mockReset().mockResolvedValue(undefined)
  })
  afterEach(cleanup)

  it('saves the password and a profile owned by the signed-in user', async () => {
    render(<RegistrationPage user={user} onComplete={onComplete} onBack={vi.fn()} />)
    fillRegistration()
    fireEvent.click(screen.getByRole('radio', { name: 'Yes' }))
    fireEvent.change(screen.getByLabelText('Institution name'), { target: { value: '  Example College  ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Complete registration' }))

    await waitFor(() => expect(onComplete).toHaveBeenCalledOnce())
    expect(profile.updateUser).toHaveBeenCalledWith({ password: 'valid-password' })
    expect(profile.upsert).toHaveBeenCalledWith({
      user_id: user.id, full_name: 'Reader Name', registering_for_institution: true,
      institution_name: 'Example College', role_title: null, intended_use: null,
    }, { onConflict: 'user_id' })
    expect(screen.getByLabelText('Email')).toBeDisabled()
  })

  it('rejects mismatched passwords before making provider requests', async () => {
    render(<RegistrationPage user={user} onComplete={onComplete} onBack={vi.fn()} />)
    fillRegistration('different-password')
    fireEvent.click(screen.getByRole('button', { name: 'Complete registration' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Passwords do not match.')
    expect(profile.updateUser).not.toHaveBeenCalled()
    expect(profile.upsert).not.toHaveBeenCalled()
  })

  it('keeps registration open when password setup fails', async () => {
    profile.updateUser.mockResolvedValue({ error: { message: 'Password setup failed' } })
    render(<RegistrationPage user={user} onComplete={onComplete} onBack={vi.fn()} />)
    fillRegistration()
    fireEvent.click(screen.getByRole('button', { name: 'Complete registration' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Password setup failed')
    expect(profile.upsert).not.toHaveBeenCalled()
    expect(onComplete).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Complete registration' })).toBeEnabled()
  })

  it('shows profile errors and permits retry without entering the workspace', async () => {
    profile.upsert.mockResolvedValue({ error: { message: 'Profile could not be saved' } })
    render(<RegistrationPage user={user} onComplete={onComplete} onBack={vi.fn()} />)
    fillRegistration()
    fireEvent.click(screen.getByRole('button', { name: 'Complete registration' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Profile could not be saved')
    expect(onComplete).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Complete registration' })).toBeEnabled()
  })
})
