import { useState, useMemo } from 'react';
import {
  AlertTriangle,
  AlertCircle,
  Info,
  ChevronDown,
  ChevronUp,
  X,
  Code,
  Lightbulb,
  ExternalLink,
  Filter,
  Search,
  CheckCircle2,
} from 'lucide-react';
import type { AccessibilityIssue, Severity, WCAGLevel } from '../types';

interface IssueListProps {
  issues: AccessibilityIssue[];
  principleFilter: string | null;
  onClearFilter: () => void;
}

const severityConfig: Record<Severity, { icon: typeof AlertCircle; label: string; class: string }> = {
  error:   { icon: AlertCircle,   label: 'Error',   class: 'badge-error'   },
  warning: { icon: AlertTriangle, label: 'Warning', class: 'badge-warning' },
  info:    { icon: Info,          label: 'Info',    class: 'badge-info'    },
};

const levelStyle = 'badge badge-info';

export function IssueList({ issues, principleFilter, onClearFilter }: IssueListProps) {
  const [expandedIssue, setExpandedIssue] = useState<string | null>(null);
  const [searchQuery, setSearchQuery]     = useState('');
  const [severityFilter, setSeverityFilter] = useState<Severity | 'all'>('all');
  const [levelFilter, setLevelFilter]     = useState<WCAGLevel | 'all'>('all');

  const filteredIssues = useMemo(() => {
    return issues.filter((issue) => {
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        if (
          !issue.rule_id.toLowerCase().includes(q) &&
          !issue.rule_name.toLowerCase().includes(q) &&
          !issue.message.toLowerCase().includes(q)
        ) return false;
      }
      if (severityFilter !== 'all' && issue.severity !== severityFilter) return false;
      if (levelFilter    !== 'all' && issue.wcag_level !== levelFilter)   return false;
      return true;
    });
  }, [issues, searchQuery, severityFilter, levelFilter]);

  const toggleExpand = (id: string) =>
    setExpandedIssue(expandedIssue === id ? null : id);

  return (
    <section aria-labelledby="issues-heading">

      {/* Header row */}
      <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
        <div className="flex items-center gap-3">
          <h2
            id="issues-heading"
            className="text-base font-semibold"
            style={{ color: '#e8edf4' }}
          >
            Issues
          </h2>
          <span className="badge badge-info">
            {filteredIssues.length} of {issues.length}
          </span>
          {principleFilter && (
            <button
              onClick={onClearFilter}
              className="badge badge-warning flex items-center gap-1 cursor-pointer"
              aria-label={`Clear ${principleFilter} filter`}
            >
              {principleFilter}
              <X className="w-3 h-3" aria-hidden="true" />
            </button>
          )}
        </div>

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Search */}
          <div className="relative">
            <Search
              className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 pointer-events-none"
              style={{ color: '#4a607a' }}
              aria-hidden="true"
            />
            <input
              type="search"
              placeholder="Search issues…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9 pr-4 py-2 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              style={{
                background: '#111c2d',
                border: '1px solid #1a2840',
                color: '#e8edf4',
              }}
              aria-label="Search issues"
            />
          </div>

          {/* Severity filter */}
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4" style={{ color: '#4a607a' }} aria-hidden="true" />
            <select
              value={severityFilter}
              onChange={(e) => setSeverityFilter(e.target.value as Severity | 'all')}
              className="rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              style={{
                background: '#111c2d',
                border: '1px solid #1a2840',
                color: '#e8edf4',
              }}
              aria-label="Filter by severity"
            >
              <option value="all">All Severities</option>
              <option value="error">Errors</option>
              <option value="warning">Warnings</option>
              <option value="info">Info</option>
            </select>
          </div>

          {/* Level filter */}
          <select
            value={levelFilter}
            onChange={(e) => setLevelFilter(e.target.value as WCAGLevel | 'all')}
            className="rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            style={{
              background: '#111c2d',
              border: '1px solid #1a2840',
              color: '#e8edf4',
            }}
            aria-label="Filter by WCAG level"
          >
            <option value="all">All Levels</option>
            <option value="A">Level A</option>
            <option value="AA">Level AA</option>
            <option value="AAA">Level AAA</option>
          </select>
        </div>
      </div>

      {/* Issues */}
      {filteredIssues.length === 0 ? (
        <div className="card text-center py-14">
          <p className="text-sm" style={{ color: '#4a607a' }}>
            No issues match your current filters
          </p>
        </div>
      ) : (
        <ul className="space-y-2" role="list" aria-label="Accessibility issues">
          {filteredIssues.map((issue) => (
            <IssueCard
              key={issue.id}
              issue={issue}
              isExpanded={expandedIssue === issue.id}
              onToggle={() => toggleExpand(issue.id)}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

/* ── Issue Card ─────────────────────────────────────────────── */
function IssueCard({
  issue,
  isExpanded,
  onToggle,
}: {
  issue: AccessibilityIssue;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const severity    = severityConfig[issue.severity];
  const SeverityIcon = severity.icon;

  const severityIconColor = issue.fixed
    ? '#86efac'
    : issue.severity === 'error'
    ? '#fca5a5'
    : issue.severity === 'warning'
    ? '#fcd34d'
    : '#93c5fd';

  return (
    <li
      className="rounded-xl overflow-hidden"
      style={{
        background: '#0d1420',
        border: '1px solid #1a2840',
        opacity: issue.fixed ? 0.55 : 1,
      }}
    >
      {/* Row button */}
      <button
        onClick={onToggle}
        className="w-full p-4 sm:p-5 flex items-start gap-4 text-left transition-colors duration-100"
        style={{ background: 'transparent' }}
        onMouseEnter={(e) => ((e.currentTarget as HTMLElement).style.background = '#111c2d')}
        onMouseLeave={(e) => ((e.currentTarget as HTMLElement).style.background = 'transparent')}
        aria-expanded={isExpanded}
        aria-controls={`issue-details-${issue.id}`}
      >
        {/* Severity icon */}
        <div className="flex-shrink-0 mt-0.5" style={{ color: severityIconColor }}>
          {issue.fixed ? (
            <CheckCircle2 className="w-5 h-5" aria-hidden="true" />
          ) : (
            <SeverityIcon className="w-5 h-5" aria-hidden="true" />
          )}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2 mb-1.5">
            {/* WCAG rule link */}
            <a
              href={`https://www.w3.org/WAI/WCAG22/Understanding/${issue.rule_id.replace('.', '')}`}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="font-mono text-xs font-medium hover:underline underline-offset-2"
              style={{ color: '#60a5fa' }}
              aria-label={`WCAG ${issue.rule_id} ${issue.rule_name} (opens in new tab)`}
            >
              {issue.rule_id}
            </a>

            {/* Level badge */}
            <span className={levelStyle}>{issue.wcag_level}</span>

            {issue.fixed ? (
              <span className="badge badge-success">Fixed</span>
            ) : (
              <>
                <span className={`badge ${severity.class}`}>{severity.label}</span>
                {issue.automatable_fix && (
                  <span className="badge badge-success">Auto-fixable</span>
                )}
              </>
            )}
          </div>

          <h3
            className="text-sm font-medium mb-0.5"
            style={{ color: issue.fixed ? '#4a607a' : '#e8edf4' }}
          >
            {issue.rule_name}
          </h3>
          <p
            className="text-sm line-clamp-2"
            style={{ color: '#7a90a8' }}
          >
            {issue.fixed ? 'This issue has been remediated.' : issue.message}
          </p>
        </div>

        {/* Expand chevron */}
        <div className="flex-shrink-0" style={{ color: '#4a607a' }}>
          {isExpanded ? (
            <ChevronUp className="w-4 h-4" aria-hidden="true" />
          ) : (
            <ChevronDown className="w-4 h-4" aria-hidden="true" />
          )}
        </div>
      </button>

      {/* Expanded detail panel */}
      {isExpanded && (
        <div
          id={`issue-details-${issue.id}`}
          className="px-5 pb-5 pt-4 space-y-5"
          style={{ borderTop: '1px solid #1a2840', background: '#080c14' }}
        >
          {/* Fix suggestion */}
          <div className="flex gap-3">
            <Lightbulb
              className="w-4 h-4 flex-shrink-0 mt-0.5"
              style={{ color: '#fcd34d' }}
              aria-hidden="true"
            />
            <div>
              <h4 className="text-xs font-semibold uppercase tracking-wide mb-1.5" style={{ color: '#7a90a8' }}>
                Suggested Fix
              </h4>
              <p className="text-sm leading-relaxed" style={{ color: '#a0b4c8' }}>
                {issue.fix_suggestion}
              </p>
            </div>
          </div>

          {/* Element location */}
          {issue.element_location?.html_snippet && (
            <div className="flex gap-3">
              <Code
                className="w-4 h-4 flex-shrink-0 mt-0.5"
                style={{ color: '#60a5fa' }}
                aria-hidden="true"
              />
              <div className="flex-1 min-w-0">
                <h4 className="text-xs font-semibold uppercase tracking-wide mb-1.5" style={{ color: '#7a90a8' }}>
                  Affected Element
                </h4>
                <pre
                  className="text-xs p-3 rounded-lg overflow-x-auto font-mono"
                  style={{ background: '#111c2d', color: '#a0b4c8' }}
                >
                  {issue.element_location.html_snippet}
                </pre>
                {issue.element_location.selector && (
                  <p className="text-xs mt-2 font-mono" style={{ color: '#4a607a' }}>
                    Selector: {issue.element_location.selector}
                  </p>
                )}
              </div>
            </div>
          )}

          {/* Evidence */}
          {issue.evidence && Object.keys(issue.evidence).length > 0 && (
            <div className="flex gap-3">
              <Info
                className="w-4 h-4 flex-shrink-0 mt-0.5"
                style={{ color: '#93c5fd' }}
                aria-hidden="true"
              />
              <div className="flex-1 min-w-0">
                <h4 className="text-xs font-semibold uppercase tracking-wide mb-1.5" style={{ color: '#7a90a8' }}>
                  Evidence
                </h4>
                <dl className="text-sm grid grid-cols-2 gap-x-4 gap-y-1">
                  {Object.entries(issue.evidence).map(([key, value]) => (
                    <div key={key} className="contents">
                      <dt style={{ color: '#4a607a' }}>{key.replace(/_/g, ' ')}:</dt>
                      <dd className="truncate" style={{ color: '#a0b4c8' }}>
                        {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                      </dd>
                    </div>
                  ))}
                </dl>
              </div>
            </div>
          )}

          {/* WCAG reference */}
          <div className="pt-1">
            <a
              href={`https://www.w3.org/WAI/WCAG22/Understanding/${issue.rule_id.replace('.', '')}`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 text-xs font-medium hover:underline underline-offset-2 transition-colors"
              style={{ color: '#60a5fa' }}
            >
              <ExternalLink className="w-3.5 h-3.5" aria-hidden="true" />
              WCAG {issue.rule_id} Understanding Document
              <span className="sr-only">(opens in new tab)</span>
            </a>
          </div>
        </div>
      )}
    </li>
  );
}
