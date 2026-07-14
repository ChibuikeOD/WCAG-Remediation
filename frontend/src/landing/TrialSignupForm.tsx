import { useState, type FormEvent } from 'react'
import { AlertCircle, CheckCircle, Loader2, Mail } from 'lucide-react'

type TrialAuthStatus = 'loading' | 'signed-out' | 'check-email' | 'signed-in' | 'error'

interface TrialSignupFormProps {
  status: TrialAuthStatus
  error: string | null
  onSendMagicLink: (email: string) => Promise<void>
}

export function TrialSignupForm({ status, error, onSendMagicLink }: TrialSignupFormProps) {
  const [email, setEmail] = useState('')
  const [fieldError, setFieldError] = useState<string | null>(null)
  const [submissionError, setSubmissionError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const normalizedEmail = email.trim().toLowerCase()

    if (!normalizedEmail) {
      setFieldError('Enter your email address to start your PDFAccess trial.')
      return
    }

    setFieldError(null)
    setSubmissionError(null)
    setIsSubmitting(true)

    try {
      await onSendMagicLink(normalizedEmail)
    } catch (sendError) {
      setSubmissionError(sendError instanceof Error ? sendError.message : 'Unable to send your sign-in link.')
    } finally {
      setIsSubmitting(false)
    }
  }

  const displayError = fieldError ?? submissionError ?? (status === 'error' ? error : null)

  return (
    <section
      id="trial-signup"
      aria-labelledby="trial-signup-heading"
      className="rounded-lg border bg-white p-6 md:p-8"
      style={{ borderColor: 'var(--pdfaccess-outline-variant)' }}
    >
      <div className="mb-6">
        <p className="pdfaccess-eyebrow">Verified email trial</p>
        <h2 id="trial-signup-heading" className="mt-2 text-2xl font-bold text-[#0d1b2a]">
          Sign up or log in
        </h2>
        <p className="mt-3 leading-7 text-[#44474c]">
          Use a personal email for 200 pages. Register with a .edu, .org, company,
          or institution email to receive 400 pages for one-time free remediation.
        </p>
      </div>

      {status === 'check-email' && (
        <div
          role="status"
          className="mb-5 flex gap-3 rounded-md border p-4 text-sm"
          style={{
            borderColor: '#76d6d5',
            background: '#ecffff',
            color: '#004f4f',
          }}
        >
          <CheckCircle className="mt-0.5 h-5 w-5 flex-shrink-0" aria-hidden="true" />
          <div>
            <strong>Check your email.</strong> We sent a secure PDFAccess link.
            Open it in this browser to confirm your email and continue.
          </div>
        </div>
      )}

      {displayError && (
        <div
          id={fieldError ? 'landing-trial-email-error' : 'trial-signup-error'}
          role="alert"
          className="mb-5 flex gap-3 rounded-md border p-4 text-sm"
          style={{
            borderColor: '#ffb4ab',
            background: '#ffdad6',
            color: '#93000a',
          }}
        >
          <AlertCircle className="mt-0.5 h-5 w-5 flex-shrink-0" aria-hidden="true" />
          <span>{displayError}</span>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="landing-trial-email" className="pdfaccess-label">
            Email address
          </label>
          <input
            id="landing-trial-email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            aria-invalid={Boolean(fieldError)}
            aria-describedby={fieldError ? 'landing-trial-email-error' : undefined}
            autoComplete="email"
            className="mt-2 min-h-[44px] w-full rounded border bg-white px-4 py-3 text-base text-[#1a1c1a]"
            style={{ borderColor: 'var(--pdfaccess-outline-variant)' }}
            placeholder="you@organization.org"
          />
        </div>

        <button type="submit" disabled={isSubmitting} className="pdfaccess-primary-button w-full">
          {isSubmitting ? (
            <Loader2 className="h-5 w-5 animate-spin" aria-hidden="true" />
          ) : (
            <Mail className="h-5 w-5" aria-hidden="true" />
          )}
          Continue with email
        </button>
      </form>

      <p className="mt-4 text-sm leading-6 text-[#44474c]">
        Questions before registering?{' '}
        <a className="pdfaccess-link" href="mailto:support@pdfaccess.org">
          Ask a question
        </a>
        .
      </p>
    </section>
  )
}
