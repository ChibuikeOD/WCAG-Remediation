import { useState, type FormEvent } from 'react'
import { AlertCircle, ArrowLeft, FileCheck, Loader2 } from 'lucide-react'
import type { User } from '@supabase/supabase-js'
import { getSupabaseClient } from '../auth/supabase'

export function RegistrationPage({ user, onComplete, onBack }: { user: User; onComplete: () => Promise<void>; onBack: () => Promise<void> }) {
  const [fullName, setFullName] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [forInstitution, setForInstitution] = useState(false)
  const [institutionName, setInstitutionName] = useState('')
  const [roleTitle, setRoleTitle] = useState('')
  const [intendedUse, setIntendedUse] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (password.length < 8) return setError('Password must be at least 8 characters.')
    if (password !== confirmPassword) return setError('Passwords do not match.')
    if (forInstitution && !institutionName.trim()) return setError('Enter your institution name.')
    const client = getSupabaseClient()
    if (!client) return setError('Registration is unavailable.')
    setSaving(true); setError(null)
    const { error: passwordError } = await client.auth.updateUser({ password })
    if (passwordError) { setSaving(false); return setError(passwordError.message) }
    const { error: profileError } = await client.from('user_registration_profiles').upsert({
      user_id: user.id,
      full_name: fullName.trim(),
      registering_for_institution: forInstitution,
      institution_name: forInstitution ? institutionName.trim() : null,
      role_title: roleTitle.trim() || null,
      intended_use: intendedUse.trim() || null,
    }, { onConflict: 'user_id' })
    if (profileError) { setSaving(false); return setError(profileError.message) }
    await onComplete()
    setSaving(false)
  }

  return <OnboardingShell title="Complete your registration" subtitle="Set up your account before starting your free trial.">
    <button type="button" className="pdfaccess-link mb-6 inline-flex items-center gap-2" onClick={() => void onBack()}>
      <ArrowLeft className="h-4 w-4" aria-hidden="true" />
      Back to home
    </button>
    {error && <div role="alert" className="mb-5 flex gap-2 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800"><AlertCircle className="h-5 w-5" />{error}</div>}
    <form onSubmit={submit} className="space-y-5">
      <Field label="Email"><input className="onboarding-input" value={user.email ?? ''} disabled /></Field>
      <Field label="Full name"><input className="onboarding-input" value={fullName} onChange={e => setFullName(e.target.value)} autoComplete="name" required /></Field>
      <div className="grid gap-5 sm:grid-cols-2">
        <Field label="Password"><input className="onboarding-input" type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="new-password" minLength={8} required /></Field>
        <Field label="Confirm password"><input className="onboarding-input" type="password" value={confirmPassword} onChange={e => setConfirmPassword(e.target.value)} autoComplete="new-password" required /></Field>
      </div>
      <fieldset><legend className="pdfaccess-label mb-2">Are you registering on behalf of an institution?</legend><div className="flex gap-6 text-sm text-[#44474c]">{[true, false].map(value => <label key={String(value)} className="flex items-center gap-2"><input type="radio" checked={forInstitution === value} onChange={() => setForInstitution(value)} />{value ? 'Yes' : 'No'}</label>)}</div></fieldset>
      {forInstitution && <Field label="Institution name"><input className="onboarding-input" value={institutionName} onChange={e => setInstitutionName(e.target.value)} required /></Field>}
      <Field label="Role or job title (optional)"><input className="onboarding-input" value={roleTitle} onChange={e => setRoleTitle(e.target.value)} /></Field>
      <Field label="How do you plan to use PDFAccess? (optional)"><textarea className="onboarding-input min-h-24" value={intendedUse} onChange={e => setIntendedUse(e.target.value)} /></Field>
      <button className="pdfaccess-primary-button w-full" disabled={saving}>{saving && <Loader2 className="h-5 w-5 animate-spin" />}Complete registration</button>
    </form>
  </OnboardingShell>
}

export function OnboardingShell({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return <main className="pdfaccess-landing min-h-screen bg-[#f9faf5] px-5 py-10 text-[#1a1c1a]"><div className="mx-auto max-w-2xl"><div className="mb-8 flex items-center gap-3 text-xl font-bold text-[#0d1b2a]"><span className="flex h-10 w-10 items-center justify-center rounded bg-[#006a6a]"><FileCheck className="h-6 w-6 text-white" /></span>PDFAccess</div><section className="rounded-lg border border-[#c4c6cc] bg-white p-6 shadow-sm sm:p-10"><p className="pdfaccess-eyebrow">Account setup</p><h1 className="mt-2 text-3xl font-bold text-[#0d1b2a]">{title}</h1><p className="mb-8 mt-3 text-[#44474c]">{subtitle}</p>{children}</section></div></main>
}

function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="pdfaccess-label">{label}<span className="mt-2 block">{children}</span></label> }
