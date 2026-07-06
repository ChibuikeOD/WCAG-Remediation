import { useState } from 'react'
import {
  BarChart3,
  CheckCircle,
  FileCheck,
  FileText,
  Gauge,
  Menu,
  ShieldCheck,
  X,
} from 'lucide-react'

import { useAuth } from '../auth/AuthProvider'
import { TrialSignupForm } from './TrialSignupForm'

const navigationLinks = [
  { href: '#trial-signup', label: 'Start trial' },
  { href: '#allowances', label: 'Allowances' },
  { href: '#workflow', label: 'Workflow' },
  { href: '#capabilities', label: 'Security' },
]

const proofItems = [
  { icon: Gauge, label: 'High-volume processing' },
  { icon: CheckCircle, label: 'WCAG 2.2 guidance' },
  { icon: ShieldCheck, label: 'PDF/UA-aware outputs' },
  { icon: BarChart3, label: 'Actionable reporting' },
]

const workflowSteps = [
  {
    title: 'Upload a PDF',
    body: 'PDFAccess validates the file and counts pages before starting remediation.',
  },
  {
    title: 'Review automated findings',
    body: 'The shared remediation pipeline checks structure, tags, reading order, and WCAG issues.',
  },
  {
    title: 'Download private outputs',
    body: 'Verified users receive the remediated PDF and a remediation report from private trial storage.',
  },
]

export function LandingPage() {
  const auth = useAuth()
  const [isMenuOpen, setIsMenuOpen] = useState(false)

  const closeMenu = () => setIsMenuOpen(false)

  return (
    <div className="pdfaccess-landing min-h-screen bg-[#f9faf5] text-[#1a1c1a]">
      <header className="sticky top-0 z-50 border-b bg-[#f9faf5]" style={{ borderColor: 'var(--pdfaccess-outline-variant)' }}>
        <div className="mx-auto flex h-16 max-w-[1440px] items-center justify-between px-4 md:px-12">
          <a href="#" className="flex min-h-[44px] items-center gap-2 rounded-sm text-[#0d1b2a]">
            <FileText className="h-6 w-6 text-[#006a6a]" aria-hidden="true" />
            <span className="text-xl font-bold">PDFAccess</span>
          </a>

          <nav className="hidden items-center gap-6 md:flex" aria-label="Primary navigation">
            {navigationLinks.map((link) => (
              <a key={link.href} href={link.href} className="pdfaccess-nav-link">
                {link.label}
              </a>
            ))}
          </nav>

          <div className="flex items-center gap-3">
            <a href="#trial-signup" className="pdfaccess-primary-button hidden md:inline-flex">
              Start free trial
            </a>
            <button
              type="button"
              aria-label="Open menu"
              aria-expanded={isMenuOpen}
              aria-controls="pdfaccess-mobile-menu"
              onClick={() => setIsMenuOpen((current) => !current)}
              className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-sm text-[#006a6a] md:hidden"
            >
              <Menu className="h-6 w-6" aria-hidden="true" />
            </button>
          </div>
        </div>
      </header>

      {isMenuOpen && (
        <div
          id="pdfaccess-mobile-menu"
          role="dialog"
          aria-label="Mobile navigation"
          className="fixed inset-0 z-[60] bg-[#f9faf5] p-4 md:hidden"
        >
          <div className="flex h-12 items-center justify-between border-b" style={{ borderColor: 'var(--pdfaccess-outline-variant)' }}>
            <span className="text-xl font-bold text-[#0d1b2a]">Menu</span>
            <button
              type="button"
              aria-label="Close menu"
              onClick={closeMenu}
              className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-sm text-[#006a6a]"
            >
              <X className="h-6 w-6" aria-hidden="true" />
            </button>
          </div>
          <nav className="mt-6 flex flex-col gap-3" aria-label="Mobile menu links">
            <a onClick={closeMenu} className="pdfaccess-mobile-link" href="#trial-signup">
              Start free trial
            </a>
            <a onClick={closeMenu} className="pdfaccess-mobile-link" href="#allowances">
              Trial allowances
            </a>
            <a onClick={closeMenu} className="pdfaccess-mobile-link" href="#workflow">
              Workflow
            </a>
            <a onClick={closeMenu} className="pdfaccess-mobile-link" href="#capabilities">
              Security
            </a>
          </nav>
        </div>
      )}

      <main>
        <section className="mx-auto grid max-w-[1440px] gap-10 px-4 py-12 md:grid-cols-[1fr_420px] md:items-center md:px-12 md:py-24">
          <div>
            <p className="pdfaccess-eyebrow">Enterprise PDF accessibility</p>
            <h1 className="mt-5 max-w-3xl text-4xl font-bold leading-tight tracking-[-0.02em] text-[#0d1b2a] md:text-5xl">
              Accessible PDFs, ready for real-world trial remediation.
            </h1>
            <p className="mt-6 max-w-2xl text-lg leading-8 text-[#44474c]">
              PDFAccess helps organizations test automated PDF remediation against
              WCAG 2.2 and PDF/UA expectations using the same remediation pipeline
              that powers the current testing workspace.
            </p>
            <div className="mt-8 flex flex-col gap-3 sm:flex-row">
              <a href="#trial-signup" className="pdfaccess-primary-button">
                Start free trial
              </a>
              <a href="#workflow" className="pdfaccess-secondary-button">
                See how it works
              </a>
            </div>
          </div>

          <div className="rounded-lg border bg-white p-5" style={{ borderColor: 'var(--pdfaccess-outline-variant)' }}>
            <div className="mb-5 flex items-center gap-3 border-b pb-4" style={{ borderColor: 'var(--pdfaccess-surface-variant)' }}>
              <div className="flex h-11 w-11 items-center justify-center rounded bg-[#ffdad6] text-[#93000a]">
                <FileCheck className="h-5 w-5" aria-hidden="true" />
              </div>
              <div>
                <h2 className="font-semibold text-[#0d1b2a]">Annual_Report.pdf</h2>
                <p className="text-sm text-[#44474c]">64 pages • private trial job</p>
              </div>
            </div>
            <div className="mb-4 flex items-center justify-between rounded-lg border bg-[#f3f4f0] p-4" style={{ borderColor: 'var(--pdfaccess-outline-variant)' }}>
              <span className="font-semibold">Accessibility score</span>
              <span className="text-2xl font-bold text-[#006a6a]">78%</span>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-lg border p-4" style={{ borderColor: 'var(--pdfaccess-outline-variant)' }}>
                <p className="text-sm text-[#44474c]">Issues found</p>
                <p className="mt-2 text-3xl font-bold text-[#0d1b2a]">37</p>
              </div>
              <div className="rounded-lg border p-4" style={{ borderColor: 'var(--pdfaccess-outline-variant)' }}>
                <p className="text-sm text-[#44474c]">Auto fixes</p>
                <p className="mt-2 text-3xl font-bold text-[#006a6a]">29</p>
              </div>
            </div>
            <div className="mt-5">
              <div className="mb-2 flex justify-between text-sm">
                <span>Remediation progress</span>
                <span className="font-bold text-[#006a6a]">60%</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-[#e2e3df]">
                <div className="h-full w-3/5 rounded-full bg-[#006a6a]" />
              </div>
            </div>
          </div>
        </section>

        <section className="border-y bg-[#edeeea] py-8" style={{ borderColor: 'var(--pdfaccess-outline-variant)' }}>
          <div className="mx-auto grid max-w-[1440px] grid-cols-2 gap-6 px-4 text-center md:grid-cols-4 md:px-12">
            {proofItems.map(({ icon: Icon, label }) => (
              <div key={label} className="flex flex-col items-center gap-3">
                <Icon className="h-6 w-6 text-[#006a6a]" aria-hidden="true" />
                <span className="font-semibold text-[#0d1b2a]">{label}</span>
              </div>
            ))}
          </div>
        </section>

        <section id="allowances" className="mx-auto grid max-w-[1440px] gap-8 px-4 py-16 md:grid-cols-3 md:px-12">
          <div className="md:col-span-1">
            <p className="pdfaccess-eyebrow">Trial allowances</p>
            <h2 className="mt-3 text-3xl font-bold text-[#0d1b2a]">One verified trial, clear page limits.</h2>
          </div>
          <div className="grid gap-4 md:col-span-2 md:grid-cols-2">
            <div className="pdfaccess-card">
              <p className="text-4xl font-bold text-[#006a6a]">200 pages</p>
              <h3 className="mt-4 text-xl font-bold text-[#0d1b2a]">Personal email trial</h3>
              <p className="mt-3 leading-7 text-[#44474c]">
                Gmail, Outlook, Yahoo, iCloud, and other common personal domains
                receive 200 pages for testing the remediation workflow.
              </p>
            </div>
            <div className="pdfaccess-card">
              <p className="text-4xl font-bold text-[#006a6a]">400 pages</p>
              <h3 className="mt-4 text-xl font-bold text-[#0d1b2a]">Education, nonprofit, and institution trial</h3>
              <p className="mt-3 leading-7 text-[#44474c]">
                .edu, .org, company, and institution domains receive 400 pages
                after email verification.
              </p>
            </div>
          </div>
        </section>

        <section id="workflow" className="bg-white py-16">
          <div className="mx-auto max-w-[1440px] px-4 md:px-12">
            <p className="pdfaccess-eyebrow">Workflow</p>
            <h2 className="mt-3 max-w-2xl text-3xl font-bold text-[#0d1b2a]">
              The public trial uses the same remediation engine as direct testing.
            </h2>
            <div className="mt-8 grid gap-4 md:grid-cols-3">
              {workflowSteps.map((step, index) => (
                <article key={step.title} className="pdfaccess-card">
                  <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-[#90efef] font-bold text-[#004f4f]">
                    {index + 1}
                  </span>
                  <h3 className="mt-5 text-xl font-bold text-[#0d1b2a]">{step.title}</h3>
                  <p className="mt-3 leading-7 text-[#44474c]">{step.body}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section id="capabilities" className="mx-auto grid max-w-[1440px] gap-8 px-4 py-16 md:grid-cols-[1fr_420px] md:px-12">
          <div>
            <p className="pdfaccess-eyebrow">Security and support</p>
            <h2 className="mt-3 text-3xl font-bold text-[#0d1b2a]">
              Built for verified users, private outputs, and questions.
            </h2>
            <p className="mt-4 max-w-2xl leading-7 text-[#44474c]">
              Trial access starts only after email confirmation. Promotional and
              product-question emails are limited to verified users, and support
              routes to support@pdfaccess.org.
            </p>
          </div>
          <TrialSignupForm
            status={auth.status}
            error={auth.error}
            onSendMagicLink={auth.sendMagicLink}
          />
        </section>
      </main>

      <footer className="border-t bg-[#edeeea]" style={{ borderColor: 'var(--pdfaccess-outline-variant)' }}>
        <div className="mx-auto grid max-w-[1440px] gap-8 px-4 py-10 md:grid-cols-4 md:px-12">
          <div>
            <p className="text-xl font-bold text-[#0d1b2a]">PDFAccess</p>
            <p className="mt-3 text-sm leading-6 text-[#44474c]">
              Enterprise-grade PDF accessibility remediation for public trial testers.
            </p>
          </div>
          <div>
            <h2 className="font-bold text-[#0d1b2a]">Platform</h2>
            <a className="pdfaccess-footer-link" href="#trial-signup">Start trial</a>
            <a className="pdfaccess-footer-link" href="#allowances">Allowances</a>
          </div>
          <div>
            <h2 className="font-bold text-[#0d1b2a]">Resources</h2>
            <a className="pdfaccess-footer-link" href="#workflow">Workflow</a>
            <a className="pdfaccess-footer-link" href="#capabilities">Security</a>
          </div>
          <div>
            <h2 className="font-bold text-[#0d1b2a]">Support</h2>
            <a className="pdfaccess-footer-link" href="mailto:support@pdfaccess.org">support@pdfaccess.org</a>
            <p className="mt-4 text-sm text-[#44474c]">© 2026 PDFAccess. WCAG remains the accessibility standard we test against.</p>
          </div>
        </div>
      </footer>
    </div>
  )
}
