import { ArrowRight, CheckCircle } from 'lucide-react'
import { OnboardingShell } from './RegistrationPage'

export function WelcomePage({ grantedPages, onStart }: { grantedPages?: number; onStart: () => Promise<void> }) {
  return <OnboardingShell title="Welcome to PDFAccess" subtitle="Your account is ready. Your free trial starts now.">
    <div className="rounded-lg bg-[#ecffff] p-5 text-[#004f4f]"><h2 className="text-xl font-bold">{grantedPages ?? 200} pages of remediation included</h2><p className="mt-2 leading-7">Upload PDFs, audit them against WCAG 2.2 and PDF/UA, apply automated fixes, and download the remediated file and report. Trial usage is counted by PDF page.</p></div>
    <ul className="my-7 space-y-3 text-[#44474c]">{['Private, account-specific document processing', 'Automated accessibility analysis and remediation', 'Downloadable remediated PDFs and compliance reports'].map(item => <li className="flex gap-3" key={item}><CheckCircle className="h-5 w-5 shrink-0 text-[#006a6a]" />{item}</li>)}</ul>
    <button className="pdfaccess-primary-button w-full" onClick={() => void onStart()}>Start Remediating <ArrowRight className="h-5 w-5" /></button>
  </OnboardingShell>
}
