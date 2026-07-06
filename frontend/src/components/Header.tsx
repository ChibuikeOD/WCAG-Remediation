import { FileCheck, Plus, LogOut, User } from 'lucide-react';
import type { TrialBalance, UserSession } from '../api';
import { TrialUsage } from '../trial/TrialUsage';

interface HeaderProps {
  onNewAnalysis: () => void;
  onSignOut?: () => Promise<void> | void;
  showNewButton: boolean;
  user: UserSession | null;
  trialBalance?: TrialBalance | null;
}

export function Header({
  onNewAnalysis,
  onSignOut,
  showNewButton,
  user,
  trialBalance,
}: HeaderProps) {
  return (
    <header
      className="sticky top-0 z-40 backdrop-blur-sm"
      style={{ background: 'rgba(8, 12, 20, 0.92)', borderBottom: '1px solid #1a2840' }}
      role="banner"
    >
      <nav
        className="max-w-7xl mx-auto px-6 lg:px-8"
        aria-label="Main navigation"
      >
        <div className="flex items-center justify-between h-16">

          {/* Logo */}
          <a
            href="/"
            className="flex items-center gap-3 group focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded-lg"
            aria-label="PDFAccess — home"
          >
            <div
              className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
              style={{ background: '#2563eb' }}
            >
              <FileCheck className="w-4 h-4 text-white" aria-hidden="true" />
            </div>
            <div className="flex items-baseline gap-2.5">
              <span
                className="font-semibold text-[15px] tracking-tight transition-colors duration-150"
                style={{ color: '#e8edf4' }}
              >
                PDFAccess
              </span>
              <span
                className="hidden sm:block text-[11px] font-medium uppercase tracking-widest"
                style={{ color: '#4a607a' }}
              >
                Enterprise
              </span>
            </div>
          </a>

          {/* Right actions */}
          <div className="flex items-center gap-2">

            {/* User identity */}
            {user?.authenticated && (
              <div
                className="hidden md:flex items-center gap-2 px-3 py-1.5 rounded-lg"
                style={{ background: '#111c2d', border: '1px solid #1a2840' }}
              >
                <User className="w-3.5 h-3.5 flex-shrink-0" style={{ color: '#4a607a' }} aria-hidden="true" />
                <span className="text-sm font-medium" style={{ color: '#a0b4c8' }}>
                  {user.name || user.email}
                </span>
              </div>
            )}

            {/* New document button */}
            {showNewButton && (
              <button
                onClick={onNewAnalysis}
                className="btn btn-secondary"
                aria-label="Analyse a new document"
              >
                <Plus className="w-4 h-4" aria-hidden="true" />
                <span className="hidden sm:inline">New Document</span>
              </button>
            )}

            {/* Sign out */}
            {user?.authenticated && onSignOut && (
              <button
                type="button"
                onClick={() => { void onSignOut(); }}
                className="btn btn-ghost"
                aria-label="Sign out of PDFAccess"
              >
                <LogOut className="w-4 h-4" aria-hidden="true" />
                <span className="hidden sm:inline">Sign out</span>
              </button>
            )}
          </div>

        </div>
        {trialBalance && (
          <div className="pb-2">
            <TrialUsage balance={trialBalance} />
          </div>
        )}
      </nav>
    </header>
  );
}
