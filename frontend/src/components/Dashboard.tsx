import {
  Eye,
  MousePointer,
  Brain,
  Puzzle,
  AlertTriangle,
  AlertCircle,
  CheckCircle,
  ClipboardList,
  Clock,
  FileText,
  Wrench,
  Image,
} from 'lucide-react';
import type { AccessibilityReport, WCAGPrinciple } from '../types';

interface DashboardProps {
  report: AccessibilityReport;
  onPrincipleSelect: (principle: string | null) => void;
  selectedPrinciple: string | null;
  onShowRemediation: () => void;
  onShowAltTextResolution: () => void;
}

const principleConfig: Record<WCAGPrinciple, {
  icon: typeof Eye;
  label: string;
  description: string;
}> = {
  Perceivable: {
    icon: Eye,
    label: 'Perceivable',
    description: 'Content presentation & alternatives',
  },
  Operable: {
    icon: MousePointer,
    label: 'Operable',
    description: 'Navigation & interaction',
  },
  Understandable: {
    icon: Brain,
    label: 'Understandable',
    description: 'Readability & predictability',
  },
  Robust: {
    icon: Puzzle,
    label: 'Robust',
    description: 'Compatibility & parsing',
  },
};

export function Dashboard({
  report,
  onPrincipleSelect,
  selectedPrinciple,
  onShowRemediation,
  onShowAltTextResolution,
}: DashboardProps) {
  const automatableIssues = report.all_issues.filter((i) => i.automatable_fix && !i.fixed);
  const unfixedIssues     = report.all_issues.filter((i) => !i.fixed);
  const fixedCount        = report.all_issues.filter((i) => i.fixed).length;
  const remainingErrors   = unfixedIssues.filter((i) => i.severity === 'error').length;
  const remainingWarnings = unfixedIssues.filter((i) => i.severity === 'warning').length;

  return (
    <div className="space-y-6">

      {/* Document info bar */}
      <div className="card">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div
              className="w-11 h-11 rounded-lg flex items-center justify-center flex-shrink-0"
              style={{ background: '#111c2d' }}
            >
              <FileText className="w-5 h-5" style={{ color: '#60a5fa' }} aria-hidden="true" />
            </div>
            <div>
              <h2 className="text-base font-semibold" style={{ color: '#e8edf4' }}>
                {report.document.title || report.document.filename}
              </h2>
              <div className="flex flex-wrap items-center gap-3 mt-0.5 text-sm" style={{ color: '#7a90a8' }}>
                <span className="uppercase text-xs font-medium tracking-wide">
                  {report.document.file_type}
                </span>
                {report.document.language && (
                  <span>Language: {report.document.language}</span>
                )}
                <span className="flex items-center gap-1">
                  <Clock className="w-3.5 h-3.5" aria-hidden="true" />
                  {report.processing_time_ms?.toFixed(0)}ms
                </span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <span className="badge badge-info">
              WCAG {report.target_level}
            </span>
            <button
              onClick={onShowAltTextResolution}
              className="btn btn-secondary flex items-center gap-2"
              aria-label="Open Alt-Text Manager"
            >
              <Image className="w-4 h-4" aria-hidden="true" />
              Alt-Text Manager
            </button>
            {automatableIssues.length > 0 && (
              <button
                onClick={onShowRemediation}
                className="btn btn-primary"
                aria-label={`Run auto-remediation for ${automatableIssues.length} issues`}
              >
                <Wrench className="w-4 h-4" aria-hidden="true" />
                Auto-fix ({automatableIssues.length})
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Remediation success banner */}
      {fixedCount > 0 && (
        <div
          className="p-4 rounded-xl flex items-start gap-3"
          style={{
            background: 'rgba(34, 197, 94, 0.07)',
            border: '1px solid rgba(34, 197, 94, 0.18)',
          }}
          role="status"
        >
          <CheckCircle className="w-5 h-5 flex-shrink-0 mt-0.5" style={{ color: '#86efac' }} aria-hidden="true" />
          <p className="text-sm" style={{ color: '#bbf7d0' }}>
            <strong className="font-semibold">{fixedCount} issue{fixedCount !== 1 ? 's' : ''} remediated.</strong>
            {' '}
            {unfixedIssues.length > 0
              ? `${unfixedIssues.length} remaining issue${unfixedIssues.length !== 1 ? 's' : ''} need attention.`
              : 'All detected issues have been addressed.'}
          </p>
        </div>
      )}

      {/* Summary stats */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
        <StatCard icon={AlertCircle}    label="Remaining"      value={unfixedIssues.length}           variant="neutral" />
        <StatCard icon={AlertTriangle}  label="Errors"         value={remainingErrors}                variant="error"   />
        <StatCard icon={AlertCircle}    label="Warnings"       value={remainingWarnings}              variant="warning" />
        <StatCard icon={ClipboardList}  label="Manual Review"  value={report.total_manual_review}     variant="info"    />
        <StatCard icon={CheckCircle}    label="Fixed"          value={fixedCount}                     variant="success" />
      </div>

      {/* Principle cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {(Object.keys(principleConfig) as WCAGPrinciple[]).map((principle) => {
          const config     = principleConfig[principle];
          const issues     = report.issues_by_principle[principle] || [];
          const remaining  = issues.filter((i) => !i.fixed);
          const errors     = remaining.filter((i) => i.severity === 'error').length;
          const warnings   = remaining.filter((i) => i.severity === 'warning').length;
          const fixed      = issues.filter((i) => i.fixed).length;
          const isSelected = selectedPrinciple === principle;

          return (
            <button
              key={principle}
              onClick={() => onPrincipleSelect(isSelected ? null : principle)}
              className="card text-left transition-all duration-150"
              style={
                isSelected
                  ? {
                      background: 'rgba(37, 99, 235, 0.08)',
                      borderColor: '#2563eb',
                    }
                  : undefined
              }
              onMouseEnter={(e) => {
                if (!isSelected) {
                  (e.currentTarget as HTMLElement).style.background = '#111c2d';
                }
              }}
              onMouseLeave={(e) => {
                if (!isSelected) {
                  (e.currentTarget as HTMLElement).style.background = '#0d1420';
                }
              }}
              aria-pressed={isSelected}
              aria-label={`${principle}: ${issues.length} issues. ${isSelected ? 'Click to clear filter' : 'Click to filter by this principle'}`}
            >
              {/* Card header */}
              <div className="flex items-start justify-between mb-5">
                <div
                  className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
                  style={{
                    background: isSelected ? 'rgba(37, 99, 235, 0.15)' : '#111c2d',
                  }}
                >
                  <config.icon
                    className="w-4 h-4"
                    style={{ color: isSelected ? '#60a5fa' : '#7a90a8' }}
                    aria-hidden="true"
                  />
                </div>
                <span
                  className="text-2xl font-semibold tabular-nums"
                  style={{ color: '#e8edf4' }}
                >
                  {remaining.length}
                </span>
              </div>

              {/* Card label */}
              <p
                className="text-sm font-semibold mb-0.5"
                style={{ color: isSelected ? '#93c5fd' : '#e8edf4' }}
              >
                {config.label}
              </p>
              <p className="text-xs mb-4" style={{ color: '#4a607a' }}>
                {config.description}
              </p>

              {/* Badges */}
              {(remaining.length > 0 || fixed > 0) && (
                <div className="flex flex-wrap gap-1.5">
                  {errors   > 0 && <span className="badge badge-error">{errors} error{errors !== 1 ? 's' : ''}</span>}
                  {warnings > 0 && <span className="badge badge-warning">{warnings} warning{warnings !== 1 ? 's' : ''}</span>}
                  {fixed    > 0 && <span className="badge badge-success">{fixed} fixed</span>}
                </div>
              )}

              {remaining.length === 0 && fixed === 0 && (
                <div className="flex items-center gap-2">
                  <CheckCircle className="w-3.5 h-3.5" style={{ color: '#86efac' }} aria-hidden="true" />
                  <span className="text-xs" style={{ color: '#86efac' }}>No issues found</span>
                </div>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/* ── Stat Card ──────────────────────────────────────────────── */
type StatVariant = 'neutral' | 'error' | 'warning' | 'info' | 'success';

const variantStyles: Record<StatVariant, { icon: string; bg: string }> = {
  neutral: { icon: '#7a90a8', bg: '#111c2d' },
  error:   { icon: '#fca5a5', bg: 'rgba(239,68,68,0.08)' },
  warning: { icon: '#fcd34d', bg: 'rgba(245,158,11,0.08)' },
  info:    { icon: '#93c5fd', bg: 'rgba(59,130,246,0.08)' },
  success: { icon: '#86efac', bg: 'rgba(34,197,94,0.08)'  },
};

function StatCard({
  icon: Icon,
  label,
  value,
  variant,
}: {
  icon: typeof AlertCircle;
  label: string;
  value: number;
  variant: StatVariant;
}) {
  const styles = variantStyles[variant];

  return (
    <div className="card flex items-center gap-4">
      <div
        className="w-11 h-11 rounded-lg flex items-center justify-center flex-shrink-0"
        style={{ background: styles.bg }}
      >
        <Icon className="w-5 h-5" style={{ color: styles.icon }} aria-hidden="true" />
      </div>
      <div>
        <p className="text-2xl font-semibold tabular-nums" style={{ color: '#e8edf4' }}>
          {value}
        </p>
        <p className="text-xs mt-0.5" style={{ color: '#4a607a' }}>
          {label}
        </p>
      </div>
    </div>
  );
}
