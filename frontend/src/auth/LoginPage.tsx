import { useEffect, useState, type FormEvent } from 'react'
import { AlertCircle, FileText, Loader2, LogIn } from 'lucide-react'

import { useAuth } from './AuthProvider'

export function LoginPage() {
  const auth = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [fieldError, setFieldError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  useEffect(() => {
    if (auth.status === 'signed-in') {
      window.location.assign('/remediate')
    }
  }, [auth.status])

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const normalizedUsername = username.trim().toLowerCase()

    if (!normalizedUsername || !password) {
      setFieldError('Enter your username and password.')
      return
    }

    setFieldError(null)
    setIsSubmitting(true)
    try {
      await auth.signInWithPassword(normalizedUsername, password)
    } finally {
      setIsSubmitting(false)
    }
  }

  const displayError = fieldError ?? (auth.status === 'error' ? auth.error : null)

  return (
    <div className="pdfaccess-landing min-h-screen bg-[#f9faf5] text-[#1a1c1a]">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <header className="border-b bg-[#f9faf5]" style={{ borderColor: 'var(--pdfaccess-outline-variant)' }}>
        <div className="mx-auto flex h-16 max-w-[1440px] items-center px-4 md:px-8 lg:px-12">
          <a href="/" className="flex min-h-[44px] items-center gap-2 rounded-sm text-[#0d1b2a]">
            <FileText className="h-6 w-6 text-[#006a6a]" aria-hidden="true" />
            <span className="text-xl font-bold">PDFAccess</span>
          </a>
        </div>
      </header>

      <main id="main-content" className="mx-auto flex max-w-[1440px] justify-center px-4 py-16 md:px-8 md:py-24">
        <section aria-labelledby="login-heading" className="w-full max-w-md rounded-lg border bg-white p-6 md:p-8" style={{ borderColor: 'var(--pdfaccess-outline-variant)' }}>
          <p className="pdfaccess-eyebrow">Welcome back</p>
          <h1 id="login-heading" className="mt-2 text-3xl font-bold text-[#0d1b2a]">Log in to PDFAccess</h1>
          <p className="mt-3 leading-7 text-[#44474c]">Access your account and continue remediating PDFs.</p>

          {displayError && (
            <div id="login-error" role="alert" className="mt-6 flex gap-3 rounded-md border p-4 text-sm" style={{ borderColor: '#ffb4ab', background: '#ffdad6', color: '#93000a' }}>
              <AlertCircle className="mt-0.5 h-5 w-5 flex-shrink-0" aria-hidden="true" />
              <span>{displayError}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="mt-6 space-y-4">
            <div>
              <label htmlFor="login-username" className="pdfaccess-label">Username or email address</label>
              <input id="login-username" type="text" value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" aria-invalid={Boolean(fieldError)} aria-describedby={fieldError ? 'login-error' : undefined} className="mt-2 min-h-[44px] w-full rounded border bg-white px-4 py-3 text-base" style={{ borderColor: 'var(--pdfaccess-outline-variant)' }} required />
            </div>
            <div>
              <label htmlFor="login-password" className="pdfaccess-label">Password</label>
              <input id="login-password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" aria-invalid={Boolean(fieldError)} aria-describedby={fieldError ? 'login-error' : undefined} className="mt-2 min-h-[44px] w-full rounded border bg-white px-4 py-3 text-base" style={{ borderColor: 'var(--pdfaccess-outline-variant)' }} required />
            </div>
            <button type="submit" disabled={isSubmitting} className="pdfaccess-primary-button w-full">
              {isSubmitting ? <Loader2 className="h-5 w-5 animate-spin" aria-hidden="true" /> : <LogIn className="h-5 w-5" aria-hidden="true" />}
              Log in and start remediating
            </button>
          </form>

          <p className="mt-6 text-sm leading-6 text-[#44474c]">New to PDFAccess? <a className="pdfaccess-link" href="/#trial-signup">Sign up for a trial</a>.</p>
        </section>
      </main>
    </div>
  )
}
