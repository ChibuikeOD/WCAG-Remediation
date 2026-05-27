import { useState, useCallback, useEffect } from 'react';
import { Header } from './components/Header';
import { UploadZone } from './components/UploadZone';
import { Dashboard } from './components/Dashboard';
import { IssueList } from './components/IssueList';
import { RemediationPanel } from './components/RemediationPanel';
import type { AccessibilityReport, WCAGLevel } from './types';
import { uploadFile, analyzeDocument, getCurrentUser, getLoginURL, type UserSession } from './api';

const DEMO_MODE = import.meta.env.VITE_DISABLE_AUTH === 'true';
const DEMO_USER: UserSession = { authenticated: true, name: 'Demo User', email: 'demo@accesspdf.com' };
import { FileCheck, LogIn, Cpu, Zap, BarChart3, Loader2 } from 'lucide-react';

type View = 'upload' | 'dashboard';

function App() {
  const [view, setView] = useState<View>('upload');
  const [report, setReport] = useState<AccessibilityReport | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [targetLevel, setTargetLevel] = useState<WCAGLevel>('AA');
  const [selectedPrinciple, setSelectedPrinciple] = useState<string | null>(null);
  const [showRemediation, setShowRemediation] = useState(false);

  // Authentication state
  // DEMO_MODE: skip the /auth/me call entirely and render straight into the app.
  const [user, setUser] = useState<UserSession | null>(DEMO_MODE ? DEMO_USER : null);
  const [isAuthChecking, setIsAuthChecking] = useState(!DEMO_MODE);

  // SSO check on mount (skipped when VITE_DISABLE_AUTH=true)
  useEffect(() => {
    if (DEMO_MODE) return;
    getCurrentUser()
      .then((session) => {
        setUser(session.authenticated ? session : null);
      })
      .catch(() => {
        setUser(null);
      })
      .finally(() => {
        setIsAuthChecking(false);
      });
  }, []);

  const handleFileUpload = useCallback(async (file: File) => {
    setIsLoading(true);
    setError(null);

    try {
      const uploadResult = await uploadFile(file);

      if (!uploadResult.success || !uploadResult.file_id) {
        throw new Error(uploadResult.message || 'Upload failed');
      }

      const analysisResult = await analyzeDocument({
        file_id: uploadResult.file_id,
        target_level: targetLevel,
        include_aaa: targetLevel === 'AAA',
      });

      setReport(analysisResult);
      setView('dashboard');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setIsLoading(false);
    }
  }, [targetLevel]);

  const handleNewAnalysis = useCallback(() => {
    setView('upload');
    setReport(null);
    setSelectedPrinciple(null);
    setShowRemediation(false);
  }, []);

  const handleRemediationComplete = useCallback((updatedReport: AccessibilityReport) => {
    setReport(updatedReport);
  }, []);

  /* ── Loading screen ─────────────────────────────────────────── */
  if (isAuthChecking) {
    return (
      <div
        className="min-h-screen flex items-center justify-center"
        style={{ background: '#080c14' }}
      >
        <div className="flex flex-col items-center gap-5">
          <div
            className="w-12 h-12 rounded-xl flex items-center justify-center"
            style={{ background: '#2563eb' }}
          >
            <Loader2 className="w-6 h-6 text-white animate-spin" aria-label="Loading" />
          </div>
          <p className="text-sm font-medium" style={{ color: '#4a607a' }}>
            Validating credentials…
          </p>
        </div>
      </div>
    );
  }

  /* ── Login screen ───────────────────────────────────────────── */
  if (!user || !user.authenticated) {
    return (
      <div
        className="min-h-screen flex items-center justify-center px-4"
        style={{ background: '#080c14' }}
      >
        <div
          className="w-full max-w-sm rounded-2xl p-8"
          style={{ background: '#0d1420', border: '1px solid #1a2840' }}
        >
          {/* Logo mark */}
          <div className="flex justify-center mb-8">
            <div
              className="w-14 h-14 rounded-2xl flex items-center justify-center"
              style={{ background: '#2563eb' }}
            >
              <FileCheck className="w-7 h-7 text-white" aria-hidden="true" />
            </div>
          </div>

          {/* Copy */}
          <div className="text-center mb-8">
            <h1
              className="text-xl font-semibold mb-2"
              style={{ color: '#e8edf4', letterSpacing: '-0.01em' }}
            >
              AccessPDF Enterprise
            </h1>
            <p className="text-sm leading-relaxed" style={{ color: '#7a90a8' }}>
              Secure, automated PDF accessibility remediation for teams that ship compliant documents at scale.
            </p>
          </div>

          {/* Login button */}
          <button
            onClick={() => { window.location.href = getLoginURL(); }}
            className="w-full py-3 px-4 rounded-xl font-semibold text-sm text-white flex items-center justify-center gap-3 transition-colors duration-150"
            style={{ background: '#2563eb' }}
            onMouseEnter={(e) => (e.currentTarget.style.background = '#1d4ed8')}
            onMouseLeave={(e) => (e.currentTarget.style.background = '#2563eb')}
          >
            <LogIn className="w-4 h-4" aria-hidden="true" />
            Sign in with Enterprise SSO
          </button>

          {/* Footer */}
          <div
            className="mt-8 pt-6 text-center"
            style={{ borderTop: '1px solid #1a2840' }}
          >
            <span
              className="text-[11px] font-medium uppercase tracking-widest"
              style={{ color: '#2d4060' }}
            >
              AccessPDF Inc.
            </span>
          </div>
        </div>
      </div>
    );
  }

  /* ── Authenticated app ──────────────────────────────────────── */
  return (
    <div className="min-h-screen" style={{ background: '#080c14' }}>
      {/* Skip Link — WCAG 2.4.1 */}
      <a href="#main-content" className="skip-link">
        Skip to main content
      </a>

      <Header
        onNewAnalysis={handleNewAnalysis}
        showNewButton={view === 'dashboard'}
        user={user}
      />

      <main id="main-content" className="max-w-7xl mx-auto px-6 lg:px-8 py-12 sm:py-16">

        {/* ── Upload view ─────────────────────────────────────── */}
        {view === 'upload' && (
          <div className="animate-fade-in">

            {/* Hero */}
            <div className="text-center mb-14">
              <h1
                className="text-3xl sm:text-4xl font-semibold tracking-tight mb-4"
                style={{ color: '#e8edf4', letterSpacing: '-0.02em' }}
              >
                Enterprise PDF Remediation
              </h1>
              <p
                className="text-base sm:text-lg max-w-xl mx-auto leading-relaxed"
                style={{ color: '#7a90a8' }}
              >
                Upload your PDF and AccessPDF will audit structure, tags, and reading order against WCAG&nbsp;2.2 and PDF/UA standards — automatically.
              </p>
            </div>

            {/* Conformance level selector */}
            <div className="flex justify-center mb-10">
              <div
                className="inline-flex items-center gap-1 p-1 rounded-lg"
                style={{ background: '#0d1420', border: '1px solid #1a2840' }}
                role="group"
                aria-label="WCAG conformance target level"
              >
                <span className="text-xs font-medium px-3" style={{ color: '#4a607a' }}>
                  Target
                </span>
                {(['A', 'AA', 'AAA'] as const).map((level) => (
                  <button
                    key={level}
                    onClick={() => setTargetLevel(level)}
                    className="px-4 py-1.5 rounded-md text-sm font-medium transition-all duration-150"
                    style={
                      targetLevel === level
                        ? { background: '#2563eb', color: '#fff' }
                        : { background: 'transparent', color: '#7a90a8' }
                    }
                    aria-pressed={targetLevel === level}
                  >
                    {level}
                  </button>
                ))}
              </div>
            </div>

            {/* Upload zone */}
            <UploadZone
              onFileUpload={handleFileUpload}
              isLoading={isLoading}
            />

            {/* Error */}
            {error && (
              <div
                role="alert"
                className="mt-6 max-w-xl mx-auto p-4 rounded-lg text-sm"
                style={{
                  background: 'rgba(239,68,68,0.08)',
                  border: '1px solid rgba(239,68,68,0.20)',
                  color: '#fca5a5',
                }}
              >
                <strong className="font-semibold">Error:</strong> {error}
              </div>
            )}

            {/* Feature cards */}
            <div className="mt-20 grid grid-cols-1 md:grid-cols-3 gap-5 animate-stagger">
              <FeatureCard
                icon={Cpu}
                title="AI Structure Tagging"
                description="LayoutLM automatically detects and restores document structure, reading order, and heading hierarchy — even on untagged PDFs."
              />
              <FeatureCard
                icon={Zap}
                title="Automated Remediation"
                description="Apply accessibility fixes in seconds. Title metadata, document language, alt text stubs, bookmarks, and table headers handled automatically."
              />
              <FeatureCard
                icon={BarChart3}
                title="Compliance Reports"
                description="Export detailed audit reports documenting every issue found, each fix applied, and all remaining action items for manual review."
              />
            </div>
          </div>
        )}

        {/* ── Dashboard view ───────────────────────────────────── */}
        {view === 'dashboard' && report && (
          <div className="animate-fade-in space-y-8">
            <Dashboard
              report={report}
              onPrincipleSelect={setSelectedPrinciple}
              selectedPrinciple={selectedPrinciple}
              onShowRemediation={() => setShowRemediation(true)}
            />

            <IssueList
              issues={
                selectedPrinciple
                  ? report.issues_by_principle[selectedPrinciple] || []
                  : report.all_issues
              }
              principleFilter={selectedPrinciple}
              onClearFilter={() => setSelectedPrinciple(null)}
            />

            {showRemediation && (
              <RemediationPanel
                report={report}
                onClose={() => setShowRemediation(false)}
                onComplete={handleRemediationComplete}
              />
            )}
          </div>
        )}
      </main>

      {/* Footer */}
      <footer
        className="mt-24"
        style={{ borderTop: '1px solid #1a2840' }}
        role="contentinfo"
      >
        <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8">
          <div className="flex flex-col sm:flex-row items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <div
                className="w-6 h-6 rounded-md flex items-center justify-center"
                style={{ background: '#2563eb' }}
              >
                <FileCheck className="w-3.5 h-3.5 text-white" aria-hidden="true" />
              </div>
              <span className="text-sm font-medium" style={{ color: '#2d4060' }}>
                AccessPDF Inc.
              </span>
            </div>
            <p className="text-xs" style={{ color: '#2d4060' }}>
              Built on{' '}
              <a
                href="https://www.w3.org/TR/WCAG22/"
                target="_blank"
                rel="noopener noreferrer"
                className="underline underline-offset-2 hover:text-blue-400 transition-colors"
                style={{ color: '#3b5a7a' }}
              >
                WCAG 2.2
              </a>{' '}
              and PDF/UA standards
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
}

/* ── Feature Card ───────────────────────────────────────────── */
function FeatureCard({
  icon: Icon,
  title,
  description,
}: {
  icon: React.ElementType;
  title: string;
  description: string;
}) {
  return (
    <article className="card flex flex-col gap-5">
      <div
        className="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0"
        style={{ background: 'rgba(37, 99, 235, 0.10)' }}
      >
        <Icon className="w-5 h-5" style={{ color: '#60a5fa' }} aria-hidden="true" />
      </div>
      <div>
        <h2
          className="text-sm font-semibold mb-2"
          style={{ color: '#e8edf4' }}
        >
          {title}
        </h2>
        <p className="text-sm leading-relaxed" style={{ color: '#7a90a8' }}>
          {description}
        </p>
      </div>
    </article>
  );
}

export default App;
