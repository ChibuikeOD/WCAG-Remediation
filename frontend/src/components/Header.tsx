import { Eye, Plus, LogOut } from 'lucide-react';
import type { UserSession } from '../api';

interface HeaderProps {
  onNewAnalysis: () => void;
  showNewButton: boolean;
  user: UserSession | null;
}

export function Header({ onNewAnalysis, showNewButton, user }: HeaderProps) {
  return (
    <header className="border-b border-zinc-800 bg-surface-900/80 backdrop-blur-sm sticky top-0 z-40" role="banner">
      <nav className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8" aria-label="Main navigation">
        <div className="flex items-center justify-between h-16">
          {/* Logo */}
          <a href="/" className="flex items-center gap-3 group">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-500 to-violet-600 flex items-center justify-center">
              <Eye className="w-5 h-5 text-white" aria-hidden="true" />
            </div>
            <div>
              <span className="font-bold text-lg text-zinc-100 group-hover:text-cyan-400 transition-colors">
                WCAG Sandbox
              </span>
              <span className="hidden sm:flex items-center gap-2 text-xs text-zinc-500">
                <span>Prototype</span>
                <span className="inline-flex items-center rounded-full bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/30 px-2 py-0.5">
                  Testing mode
                </span>
              </span>
            </div>
          </a>

          {/* Actions */}
          <div className="flex items-center gap-4">
            {user?.authenticated && (
              <div className="hidden md:flex flex-col text-right">
                <span className="text-sm text-zinc-300 font-medium">{user.name}</span>
                <span className="text-xs text-zinc-500">{user.email}</span>
              </div>
            )}
            
            {showNewButton && (
              <button
                onClick={onNewAnalysis}
                className="btn btn-primary"
                aria-label="Start over and run a new check"
              >
                <Plus className="w-4 h-4" aria-hidden="true" />
                <span className="hidden sm:inline">Start over</span>
              </button>
            )}

            {user?.authenticated && (
              <a
                href="/api/auth/logout"
                className="btn btn-secondary text-sm flex items-center gap-2 border border-zinc-700 hover:bg-zinc-800 text-zinc-300"
                aria-label="Sign out"
              >
                <LogOut className="w-4 h-4" />
                <span className="hidden sm:inline">Sign out</span>
              </a>
            )}

            {/* External Links */}
            <a
              href="https://www.w3.org/WAI/WCAG22/quickref/"
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-ghost text-sm"
              aria-label="WCAG Quick Reference (opens in new tab)"
            >
              <span className="hidden md:inline">WCAG Reference</span>
              <span className="md:hidden">Ref</span>
              <span className="sr-only">(opens in new tab)</span>
            </a>
          </div>
        </div>
      </nav>
    </header>
  );
}





