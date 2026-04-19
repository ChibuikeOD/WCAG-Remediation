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
  Wrench
} from 'lucide-react';
import type { AccessibilityReport, WCAGPrinciple } from '../types';

interface DashboardProps {
  report: AccessibilityReport;
  onPrincipleSelect: (principle: string | null) => void;
  selectedPrinciple: string | null;
  onShowRemediation: () => void;
}

const principleConfig: Record<WCAGPrinciple, { 
  icon: typeof Eye; 
  color: string; 
  bgColor: string;
  description: string;
}> = {
  Perceivable: {
    icon: Eye,
    color: 'text-cyan-400',
    bgColor: 'bg-cyan-500/20',
    description: 'Content presentation & alternatives',
  },
  Operable: {
    icon: MousePointer,
    color: 'text-violet-400',
    bgColor: 'bg-violet-500/20',
    description: 'Navigation & interaction',
  },
  Understandable: {
    icon: Brain,
    color: 'text-emerald-400',
    bgColor: 'bg-emerald-500/20',
    description: 'Readability & predictability',
  },
  Robust: {
    icon: Puzzle,
    color: 'text-red-400',
    bgColor: 'bg-red-500/20',
    description: 'Compatibility & parsing',
  },
};

export function Dashboard({ 
  report, 
  onPrincipleSelect, 
  selectedPrinciple,
  onShowRemediation 
}: DashboardProps) {
  const automatableIssues = report.all_issues.filter(i => i.automatable_fix && !i.fixed);
  const unfixedIssues = report.all_issues.filter(i => !i.fixed);
  const fixedCount = report.all_issues.filter(i => i.fixed).length;
  const remainingErrors = unfixedIssues.filter(i => i.severity === 'error').length;
  const remainingWarnings = unfixedIssues.filter(i => i.severity === 'warning').length;

  return (
    <div className="space-y-6">
      {/* Document Info */}
      <div className="card">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-zinc-800 flex items-center justify-center">
              <FileText className="w-6 h-6 text-cyan-400" aria-hidden="true" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-zinc-100">
                {report.document.title || report.document.filename}
              </h2>
              <div className="flex flex-wrap items-center gap-3 text-sm text-zinc-400">
                <span className="flex items-center gap-1">
                  <span className="uppercase">{report.document.file_type}</span>
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
              Target: WCAG {report.target_level}
            </span>
            {automatableIssues.length > 0 && (
              <button
                onClick={onShowRemediation}
                className="btn btn-primary"
                aria-label={`Try auto-fix for ${automatableIssues.length} issues`}
              >
                <Wrench className="w-4 h-4" aria-hidden="true" />
                Try auto-fix ({automatableIssues.length})
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Fixed banner */}
      {fixedCount > 0 && (
        <div className="p-4 bg-emerald-500/10 border border-emerald-500/30 rounded-xl flex items-center gap-3">
          <CheckCircle className="w-5 h-5 text-emerald-400" aria-hidden="true" />
          <p className="text-sm text-emerald-300">
            <strong>{fixedCount} issue{fixedCount !== 1 ? 's' : ''} remediated.</strong>
            {' '}
            {unfixedIssues.length > 0
              ? `${unfixedIssues.length} remaining issue${unfixedIssues.length !== 1 ? 's' : ''} need attention.`
              : 'All detected issues have been addressed!'}
          </p>
        </div>
      )}

      {/* Summary Stats */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <StatCard
          icon={AlertCircle}
          label="Remaining"
          value={unfixedIssues.length}
          color="zinc"
        />
        <StatCard
          icon={AlertTriangle}
          label="Errors"
          value={remainingErrors}
          color="red"
        />
        <StatCard
          icon={AlertCircle}
          label="Warnings"
          value={remainingWarnings}
          color="amber"
        />
        <StatCard
          icon={ClipboardList}
          label="Manual Review"
          value={report.total_manual_review}
          color="blue"
        />
        <StatCard
          icon={CheckCircle}
          label="Fixed"
          value={fixedCount}
          color="emerald"
        />
      </div>

      {/* Principle Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {(Object.keys(principleConfig) as WCAGPrinciple[]).map((principle) => {
          const config = principleConfig[principle];
          const issues = report.issues_by_principle[principle] || [];
          const remaining = issues.filter(i => !i.fixed);
          const errors = remaining.filter(i => i.severity === 'error').length;
          const warnings = remaining.filter(i => i.severity === 'warning').length;
          const fixed = issues.filter(i => i.fixed).length;
          const isSelected = selectedPrinciple === principle;

          return (
            <button
              key={principle}
              onClick={() => onPrincipleSelect(isSelected ? null : principle)}
              className={`card text-left transition-all ${
                isSelected 
                  ? 'ring-2 ring-cyan-500 bg-zinc-800' 
                  : 'hover:bg-zinc-800/50'
              }`}
              aria-pressed={isSelected}
              aria-label={`${principle}: ${issues.length} issues. ${isSelected ? 'Click to clear filter' : 'Click to filter'}`}
            >
              <div className="flex items-start justify-between mb-4">
                <div className={`w-10 h-10 rounded-lg ${config.bgColor} flex items-center justify-center`}>
                  <config.icon className={`w-5 h-5 ${config.color}`} aria-hidden="true" />
                </div>
                <span className="text-2xl font-bold text-zinc-100">{remaining.length}</span>
              </div>

              <h3 className={`font-semibold ${config.color}`}>{principle}</h3>
              <p className="text-sm text-zinc-500 mt-1">{config.description}</p>

              {(remaining.length > 0 || fixed > 0) && (
                <div className="flex flex-wrap gap-2 mt-4">
                  {errors > 0 && (
                    <span className="badge badge-error">{errors} errors</span>
                  )}
                  {warnings > 0 && (
                    <span className="badge badge-warning">{warnings} warnings</span>
                  )}
                  {fixed > 0 && (
                    <span className="badge bg-emerald-500/20 text-emerald-400">{fixed} fixed</span>
                  )}
                </div>
              )}

              {remaining.length === 0 && fixed === 0 && (
                <div className="flex items-center gap-2 mt-4 text-emerald-400">
                  <CheckCircle className="w-4 h-4" aria-hidden="true" />
                  <span className="text-sm">No issues found</span>
                </div>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function StatCard({ 
  icon: Icon, 
  label, 
  value, 
  color 
}: { 
  icon: typeof AlertCircle; 
  label: string; 
  value: number; 
  color: 'zinc' | 'red' | 'amber' | 'blue' | 'emerald';
}) {
  const colorClasses = {
    zinc: 'bg-zinc-500/20 text-zinc-400',
    red: 'bg-red-500/20 text-red-400',
    amber: 'bg-amber-500/20 text-amber-400',
    blue: 'bg-blue-500/20 text-blue-400',
    emerald: 'bg-emerald-500/20 text-emerald-400',
  };

  return (
    <div className="card flex items-center gap-4">
      <div className={`w-12 h-12 rounded-lg ${colorClasses[color]} flex items-center justify-center`}>
        <Icon className="w-6 h-6" aria-hidden="true" />
      </div>
      <div>
        <p className="text-2xl font-bold text-zinc-100">{value}</p>
        <p className="text-sm text-zinc-500">{label}</p>
      </div>
    </div>
  );
}





