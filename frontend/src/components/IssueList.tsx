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
  CheckCircle2
} from 'lucide-react';
import type { AccessibilityIssue, Severity, WCAGLevel } from '../types';

interface IssueListProps {
  issues: AccessibilityIssue[];
  principleFilter: string | null;
  onClearFilter: () => void;
}

const severityConfig: Record<Severity, { icon: typeof AlertCircle; label: string; class: string }> = {
  error: { icon: AlertCircle, label: 'Error', class: 'badge-error' },
  warning: { icon: AlertTriangle, label: 'Warning', class: 'badge-warning' },
  info: { icon: Info, label: 'Info', class: 'badge-info' },
};

const levelColors: Record<WCAGLevel, string> = {
  A: 'bg-emerald-500/20 text-emerald-400',
  AA: 'bg-amber-500/20 text-amber-400',
  AAA: 'bg-violet-500/20 text-violet-400',
};

export function IssueList({ issues, principleFilter, onClearFilter }: IssueListProps) {
  const [expandedIssue, setExpandedIssue] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [severityFilter, setSeverityFilter] = useState<Severity | 'all'>('all');
  const [levelFilter, setLevelFilter] = useState<WCAGLevel | 'all'>('all');

  const filteredIssues = useMemo(() => {
    return issues.filter(issue => {
      // Search filter
      if (searchQuery) {
        const query = searchQuery.toLowerCase();
        const matchesSearch = 
          issue.rule_id.toLowerCase().includes(query) ||
          issue.rule_name.toLowerCase().includes(query) ||
          issue.message.toLowerCase().includes(query);
        if (!matchesSearch) return false;
      }

      // Severity filter
      if (severityFilter !== 'all' && issue.severity !== severityFilter) {
        return false;
      }

      // Level filter
      if (levelFilter !== 'all' && issue.wcag_level !== levelFilter) {
        return false;
      }

      return true;
    });
  }, [issues, searchQuery, severityFilter, levelFilter]);

  const toggleExpand = (issueId: string) => {
    setExpandedIssue(expandedIssue === issueId ? null : issueId);
  };

  return (
    <section aria-labelledby="issues-heading">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
        <div className="flex items-center gap-3">
          <h2 id="issues-heading" className="text-xl font-semibold text-zinc-100">
            Issues
          </h2>
          <span className="badge badge-info">
            {filteredIssues.length} of {issues.length}
          </span>
          {principleFilter && (
            <button
              onClick={onClearFilter}
              className="badge badge-warning flex items-center gap-1"
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
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" aria-hidden="true" />
            <input
              type="search"
              placeholder="Search issues..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9 pr-4 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-cyan-500"
              aria-label="Search issues"
            />
          </div>

          {/* Severity Filter */}
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-zinc-500" aria-hidden="true" />
            <select
              value={severityFilter}
              onChange={(e) => setSeverityFilter(e.target.value as Severity | 'all')}
              className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:ring-2 focus:ring-cyan-500"
              aria-label="Filter by severity"
            >
              <option value="all">All Severities</option>
              <option value="error">Errors</option>
              <option value="warning">Warnings</option>
              <option value="info">Info</option>
            </select>
          </div>

          {/* Level Filter */}
          <select
            value={levelFilter}
            onChange={(e) => setLevelFilter(e.target.value as WCAGLevel | 'all')}
            className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:ring-2 focus:ring-cyan-500"
            aria-label="Filter by WCAG level"
          >
            <option value="all">All Levels</option>
            <option value="A">Level A</option>
            <option value="AA">Level AA</option>
            <option value="AAA">Level AAA</option>
          </select>
        </div>
      </div>

      {/* Issues List */}
      {filteredIssues.length === 0 ? (
        <div className="card text-center py-12">
          <p className="text-zinc-400">No issues match your filters</p>
        </div>
      ) : (
        <ul className="space-y-3" role="list" aria-label="Accessibility issues">
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

function IssueCard({ 
  issue, 
  isExpanded, 
  onToggle 
}: { 
  issue: AccessibilityIssue; 
  isExpanded: boolean; 
  onToggle: () => void;
}) {
  const severity = severityConfig[issue.severity];
  const SeverityIcon = severity.icon;

  return (
    <li className={`card !p-0 overflow-hidden ${issue.fixed ? 'opacity-60' : ''}`}>
      {/* Issue Header */}
      <button
        onClick={onToggle}
        className="w-full p-4 flex items-start gap-4 text-left hover:bg-zinc-800/50 transition-colors"
        aria-expanded={isExpanded}
        aria-controls={`issue-details-${issue.id}`}
      >
        {/* Severity / Fixed Icon */}
        <div className={`flex-shrink-0 mt-0.5 ${
          issue.fixed ? 'text-emerald-400' :
          issue.severity === 'error' ? 'text-red-400' :
          issue.severity === 'warning' ? 'text-amber-400' :
          'text-blue-400'
        }`}>
          {issue.fixed ? (
            <CheckCircle2 className="w-5 h-5" aria-hidden="true" />
          ) : (
            <SeverityIcon className="w-5 h-5" aria-hidden="true" />
          )}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2 mb-1">
            {/* WCAG ID */}
            <a
              href={`https://www.w3.org/WAI/WCAG22/Understanding/${issue.rule_id.replace('.', '')}`}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="font-mono text-sm text-cyan-400 hover:underline"
              aria-label={`WCAG ${issue.rule_id} ${issue.rule_name} (opens in new tab)`}
            >
              {issue.rule_id}
            </a>

            {/* Level Badge */}
            <span className={`badge ${levelColors[issue.wcag_level]}`}>
              {issue.wcag_level}
            </span>

            {/* Fixed Badge */}
            {issue.fixed ? (
              <span className="badge bg-emerald-500/20 text-emerald-400">Fixed</span>
            ) : (
              <>
                {/* Severity Badge */}
                <span className={`badge ${severity.class}`}>
                  {severity.label}
                </span>

                {/* Automatable Badge */}
                {issue.automatable_fix && (
                  <span className="badge badge-success">Auto-fixable</span>
                )}
              </>
            )}
          </div>

          <h3 className={`font-medium mb-1 ${issue.fixed ? 'text-zinc-400 line-through' : 'text-zinc-100'}`}>
            {issue.rule_name}
          </h3>
          <p className="text-sm text-zinc-400 line-clamp-2">
            {issue.fixed ? 'This issue has been remediated.' : issue.message}
          </p>
        </div>

        {/* Expand Icon */}
        <div className="flex-shrink-0 text-zinc-500">
          {isExpanded ? (
            <ChevronUp className="w-5 h-5" aria-hidden="true" />
          ) : (
            <ChevronDown className="w-5 h-5" aria-hidden="true" />
          )}
        </div>
      </button>

      {/* Expanded Details */}
      {isExpanded && (
        <div 
          id={`issue-details-${issue.id}`}
          className="border-t border-zinc-800 p-4 space-y-4 bg-zinc-900/50"
        >
          {/* Fix Suggestion */}
          <div className="flex gap-3">
            <Lightbulb className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" aria-hidden="true" />
            <div>
              <h4 className="text-sm font-medium text-zinc-300 mb-1">Suggested Fix</h4>
              <p className="text-sm text-zinc-400">{issue.fix_suggestion}</p>
            </div>
          </div>

          {/* Element Location */}
          {issue.element_location?.html_snippet && (
            <div className="flex gap-3">
              <Code className="w-5 h-5 text-cyan-400 flex-shrink-0 mt-0.5" aria-hidden="true" />
              <div className="flex-1 min-w-0">
                <h4 className="text-sm font-medium text-zinc-300 mb-1">Affected Element</h4>
                <pre className="text-xs bg-zinc-800 p-3 rounded-lg overflow-x-auto text-zinc-300 font-mono">
                  {issue.element_location.html_snippet}
                </pre>
                {issue.element_location.selector && (
                  <p className="text-xs text-zinc-500 mt-2 font-mono">
                    Selector: {issue.element_location.selector}
                  </p>
                )}
              </div>
            </div>
          )}

          {/* Evidence */}
          {issue.evidence && Object.keys(issue.evidence).length > 0 && (
            <div className="flex gap-3">
              <Info className="w-5 h-5 text-blue-400 flex-shrink-0 mt-0.5" aria-hidden="true" />
              <div className="flex-1 min-w-0">
                <h4 className="text-sm font-medium text-zinc-300 mb-1">Evidence</h4>
                <dl className="text-sm grid grid-cols-2 gap-x-4 gap-y-1">
                  {Object.entries(issue.evidence).map(([key, value]) => (
                    <div key={key} className="contents">
                      <dt className="text-zinc-500">{key.replace(/_/g, ' ')}:</dt>
                      <dd className="text-zinc-300 truncate">
                        {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                      </dd>
                    </div>
                  ))}
                </dl>
              </div>
            </div>
          )}

          {/* WCAG Reference Link */}
          <div className="pt-2">
            <a
              href={`https://www.w3.org/WAI/WCAG22/Understanding/${issue.rule_id.replace('.', '')}`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 text-sm text-cyan-400 hover:underline"
            >
              <ExternalLink className="w-4 h-4" aria-hidden="true" />
              Read WCAG {issue.rule_id} Understanding Document
              <span className="sr-only">(opens in new tab)</span>
            </a>
          </div>
        </div>
      )}
    </li>
  );
}





