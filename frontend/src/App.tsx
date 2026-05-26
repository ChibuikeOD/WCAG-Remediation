import { useState, useCallback, useEffect } from 'react';
import { Header } from './components/Header';
import { UploadZone } from './components/UploadZone';
import { Dashboard } from './components/Dashboard';
import { IssueList } from './components/IssueList';
import { RemediationPanel } from './components/RemediationPanel';
import type { AccessibilityReport, WCAGLevel } from './types';
import { uploadFile, analyzeDocument, analyzeURL, getCurrentUser, getLoginURL, type UserSession } from './api';
import { Eye, LogIn } from 'lucide-react';

type View = 'upload' | 'dashboard';

function App() {
  const [view, setView] = useState<View>('upload');
  const [report, setReport] = useState<AccessibilityReport | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [targetLevel, setTargetLevel] = useState<WCAGLevel>('AA');
  const [selectedPrinciple, setSelectedPrinciple] = useState<string | null>(null);
  const [showRemediation, setShowRemediation] = useState(false);

  // Authentication State
  const [user, setUser] = useState<UserSession | null>(null);
  const [isAuthChecking, setIsAuthChecking] = useState(true);

  // Run SSO check on mount
  useEffect(() => {
    getCurrentUser()
      .then((session) => {
        if (session.authenticated) {
          setUser(session);
        } else {
          setUser(null);
        }
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
      // Upload the file
      const uploadResult = await uploadFile(file);
      
      if (!uploadResult.success || !uploadResult.file_id) {
        throw new Error(uploadResult.message || 'Upload failed');
      }

      // Analyze the uploaded file
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

  const handleURLAnalyze = useCallback(async (url: string) => {
    setIsLoading(true);
    setError(null);
    
    try {
      const analysisResult = await analyzeURL(url, targetLevel, targetLevel === 'AAA');
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

  // Premium loading screen while checking SSO session
  if (isAuthChecking) {
    return (
      <div className="min-h-screen bg-surface-950 flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-cyan-500 to-violet-600 flex items-center justify-center animate-pulse shadow-lg shadow-cyan-500/25">
            <Eye className="w-6 h-6 text-white animate-spin-slow" />
          </div>
          <p className="text-zinc-400 font-medium animate-pulse text-sm">Validating SSO credentials...</p>
        </div>
      </div>
    );
  }

  // Premium SSO Login splash screen
  if (!user || !user.authenticated) {
    return (
      <div className="min-h-screen bg-surface-950 flex items-center justify-center px-4 relative overflow-hidden">
        {/* Decorative Background Gradients */}
        <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-cyan-500/10 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-violet-600/10 rounded-full blur-3xl pointer-events-none" />
        
        <div className="w-full max-w-md p-8 rounded-2xl border border-zinc-800 bg-zinc-900/40 backdrop-blur-md relative z-10 shadow-2xl">
          <div className="flex justify-center mb-6">
            <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-cyan-500 to-violet-600 flex items-center justify-center shadow-lg shadow-cyan-500/20">
              <Eye className="w-8 h-8 text-white" />
            </div>
          </div>
          
          <h1 className="text-2xl font-bold text-center text-zinc-100 mb-2">
            WCAG 2.2 Remediation
          </h1>
          <p className="text-sm text-center text-zinc-500 mb-8 font-medium">
            Enterprise Conformance Audit Platform
          </p>
          
          <div className="p-4 bg-zinc-800/30 rounded-xl border border-zinc-800/80 mb-8">
            <p className="text-xs text-zinc-400 leading-relaxed text-center">
              Please sign in with your institution credential (UMass SSO or partner Enterprise account) to run audits and apply accessibility remediations.
            </p>
          </div>
          
          <button
            onClick={() => { window.location.href = getLoginURL(); }}
            className="w-full py-3.5 px-4 rounded-xl bg-gradient-to-r from-cyan-500 to-violet-600 hover:from-cyan-600 hover:to-violet-700 text-white font-semibold flex items-center justify-center gap-3 shadow-lg shadow-cyan-500/15 hover:shadow-cyan-500/25 transition-all transform hover:-translate-y-0.5 active:translate-y-0 duration-200"
          >
            <LogIn className="w-5 h-5" />
            Sign In with Enterprise SSO
          </button>
          
          <div className="mt-8 pt-6 border-t border-zinc-800/50 text-center">
            <span className="text-[10px] text-zinc-600 font-semibold tracking-wider uppercase">
              UMass System Partner Application
            </span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-surface-950">
      {/* Skip Link - WCAG 2.4.1 Bypass Blocks */}
      <a href="#main-content" className="skip-link">
        Skip to main content
      </a>

      <Header 
        onNewAnalysis={handleNewAnalysis}
        showNewButton={view === 'dashboard'}
        user={user}
      />

      <main id="main-content" className="max-w-7xl mx-auto px-4 py-8 sm:px-6 lg:px-8">
        {view === 'upload' && (
          <div className="animate-fade-in">
            {/* Hero Section */}
            <div className="text-center mb-12">
              <h1 className="text-4xl sm:text-5xl font-bold mb-4">
                <span className="gradient-text">WCAG 2.2</span> quick check
              </h1>
              <p className="text-xl text-zinc-400 max-w-2xl mx-auto">
                Upload a file or paste a URL to see what the checker finds.
              </p>
            </div>

            {/* Level Selector */}
            <div className="flex justify-center gap-4 mb-8">
              <span className="text-zinc-400 self-center">Target Level:</span>
              {(['A', 'AA', 'AAA'] as const).map((level) => (
                <button
                  key={level}
                  onClick={() => setTargetLevel(level)}
                  className={`px-4 py-2 rounded-lg font-medium transition-all ${
                    targetLevel === level
                      ? 'bg-cyan-600 text-white'
                      : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700'
                  }`}
                  aria-pressed={targetLevel === level}
                >
                  Level {level}
                </button>
              ))}
            </div>

            {/* Upload Zone */}
            <UploadZone
              onFileUpload={handleFileUpload}
              onURLAnalyze={handleURLAnalyze}
              isLoading={isLoading}
            />

            {/* Error Display */}
            {error && (
              <div 
                role="alert" 
                className="mt-6 max-w-xl mx-auto p-4 bg-red-500/20 border border-red-500/30 rounded-lg text-red-400"
              >
                <strong>Error:</strong> {error}
              </div>
            )}

            {/* WCAG Principles Overview */}
            <div className="mt-16 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 animate-stagger">
              <PrincipleCard
                number={1}
                name="Perceivable"
                description="Content must be presentable in ways users can perceive"
                color="cyan"
              />
              <PrincipleCard
                number={2}
                name="Operable"
                description="User interface must be operable by all users"
                color="violet"
              />
              <PrincipleCard
                number={3}
                name="Understandable"
                description="Information and UI must be understandable"
                color="emerald"
              />
              <PrincipleCard
                number={4}
                name="Robust"
                description="Content must work with assistive technologies"
                color="red"
              />
            </div>
          </div>
        )}

        {view === 'dashboard' && report && (
          <div className="animate-fade-in space-y-8">
            {/* Dashboard Header */}
            <Dashboard
              report={report}
              onPrincipleSelect={setSelectedPrinciple}
              selectedPrinciple={selectedPrinciple}
              onShowRemediation={() => setShowRemediation(true)}
            />

            {/* Issue List */}
            <IssueList
              issues={
                selectedPrinciple
                  ? report.issues_by_principle[selectedPrinciple] || []
                  : report.all_issues
              }
              principleFilter={selectedPrinciple}
              onClearFilter={() => setSelectedPrinciple(null)}
            />

            {/* Remediation Panel */}
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
      <footer className="border-t border-zinc-800 mt-16" role="contentinfo">
        <div className="max-w-7xl mx-auto px-4 py-8 sm:px-6 lg:px-8">
          <div className="flex flex-col md:flex-row justify-between items-center gap-4">
            <p className="text-zinc-500 text-sm">
              Prototype WCAG tester (for experimenting)
            </p>
            <p className="text-zinc-500 text-sm">
              Based on{' '}
              <a 
                href="https://www.w3.org/TR/WCAG22/" 
                target="_blank" 
                rel="noopener noreferrer"
                className="text-cyan-400 hover:underline"
              >
                W3C Web Content Accessibility Guidelines 2.2
              </a>
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
}

// Principle Card Component
function PrincipleCard({ 
  number, 
  name, 
  description, 
  color 
}: { 
  number: number; 
  name: string; 
  description: string; 
  color: 'cyan' | 'violet' | 'emerald' | 'red';
}) {
  const colorClasses = {
    cyan: 'bg-cyan-500/10 border-cyan-500/30 text-cyan-400',
    violet: 'bg-violet-500/10 border-violet-500/30 text-violet-400',
    emerald: 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400',
    red: 'bg-red-500/10 border-red-500/30 text-red-400',
  };

  const numberClasses = {
    cyan: 'bg-cyan-500/20 text-cyan-400',
    violet: 'bg-violet-500/20 text-violet-400',
    emerald: 'bg-emerald-500/20 text-emerald-400',
    red: 'bg-red-500/20 text-red-400',
  };

  return (
    <article className={`card border ${colorClasses[color]}`}>
      <div className={`w-10 h-10 rounded-lg ${numberClasses[color]} flex items-center justify-center font-bold text-lg mb-4`}>
        {number}
      </div>
      <h2 className="text-lg font-semibold text-zinc-100 mb-2">{name}</h2>
      <p className="text-zinc-400 text-sm">{description}</p>
    </article>
  );
}

export default App;





