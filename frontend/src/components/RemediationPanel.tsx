import { useState } from 'react';
import {
  X,
  Wrench,
  CheckCircle,
  XCircle,
  Download,
  Loader2,
  AlertTriangle,
  FileCheck,
} from 'lucide-react';
import type {
  AccessibilityReport,
  AccessibilityIssue,
  RemediationResult,
} from '../types';
import {
  remediateDocument,
  getRemediatedFileURL,
} from '../api';

interface RemediationPanelProps {
  report: AccessibilityReport;
  onClose: () => void;
  onComplete: (updatedReport: AccessibilityReport) => void;
}

const PDF_ISSUE_ID_TO_RULE: Record<string, string> = {
  'pdf-title':            '2.4.2',
  'pdf-lang':             '3.1.1',
  'pdf-auto-tag':         '1.3.1',
  'pdf-heading-hierarchy':'1.3.1',
  'pdf-table-headers':    '1.3.1',
  'pdf-list-structure':   '1.3.1',
  'pdf-span-overuse':     '1.3.1',
  'pdf-reading-order':    '1.3.2',
  'pdf-untagged-urls':    '2.4.4',
  'pdf-bookmarks':        '2.4.5',
  'pdf-ocr':              '1.4.5',
  'pdf-form-labels':      '3.3.2',
};

export function RemediationPanel({ report, onClose, onComplete }: RemediationPanelProps) {
  const [isProcessing, setIsProcessing] = useState(false);
  const [results, setResults]           = useState<RemediationResult[] | null>(null);
  const [error, setError]               = useState<string | null>(null);

  const automatableIssues = report.all_issues.filter((i) => i.automatable_fix && !i.fixed);

  /* ── Handlers ─────────────────────────────────────────────── */

  const handleApplyFixes = async () => {
    setIsProcessing(true);
    setError(null);

    try {
      const response = await remediateDocument({
        report_id: report.id,
        apply_all_automatable: true,
      });

      setResults(response.results);

      const successfulResults = response.results.filter((r) => r.success);
      const fixedRuleIds      = new Set<string>();

      for (const r of successfulResults) {
        const mapped = PDF_ISSUE_ID_TO_RULE[r.issue_id];
        if (mapped) fixedRuleIds.add(mapped);
        fixedRuleIds.add(r.issue_id);
      }

      const updatedIssues = report.all_issues.map((issue) => {
        const isFixed = fixedRuleIds.has(issue.rule_id) || fixedRuleIds.has(issue.id);
        return {
          ...issue,
          fixed:  issue.fixed || isFixed,
          status: isFixed ? ('pass' as const) : issue.status,
        };
      });

      const updatedByPrinciple: Record<string, typeof updatedIssues> = {};
      for (const issue of updatedIssues) {
        if (!updatedByPrinciple[issue.principle]) {
          updatedByPrinciple[issue.principle] = [];
        }
        updatedByPrinciple[issue.principle].push(issue);
      }

      const remainingErrors   = updatedIssues.filter((i) => !i.fixed && i.severity === 'error').length;
      const remainingWarnings = updatedIssues.filter((i) => !i.fixed && i.severity === 'warning').length;

      onComplete({
        ...report,
        all_issues:           updatedIssues,
        issues_by_principle:  updatedByPrinciple,
        total_errors:         remainingErrors,
        total_warnings:       remainingWarnings,
        total_issues:         remainingErrors + remainingWarnings,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Remediation failed');
    } finally {
      setIsProcessing(false);
    }
  };

  const successCount = results?.filter((r) => r.success).length  ?? 0;
  const failedCount  = results?.filter((r) => !r.success).length ?? 0;

  /* ── Render ───────────────────────────────────────────────── */
  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4"
      style={{ background: 'rgba(4, 8, 14, 0.80)' }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="remediation-title"
    >
      <div
        className="w-full sm:max-w-2xl max-h-[90vh] sm:max-h-[80vh] overflow-hidden flex flex-col animate-scale-in sm:rounded-2xl"
        style={{ background: '#0d1420', border: '1px solid #1a2840' }}
      >
        {/* Modal header */}
        <div
          className="flex items-center justify-between px-6 py-5"
          style={{ borderBottom: '1px solid #1a2840' }}
        >
          <div className="flex items-center gap-3">
            <div
              className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
              style={{
                background: results
                  ? 'rgba(34, 197, 94, 0.10)'
                  : 'rgba(37, 99, 235, 0.10)',
              }}
            >
              {results ? (
                <FileCheck className="w-5 h-5" style={{ color: '#86efac' }} aria-hidden="true" />
              ) : (
                <Wrench className="w-5 h-5" style={{ color: '#60a5fa' }} aria-hidden="true" />
              )}
            </div>
            <div>
              <h2
                id="remediation-title"
                className="text-base font-semibold"
                style={{ color: '#e8edf4' }}
              >
                {results ? 'Remediation complete' : 'Apply automated fixes'}
              </h2>
              <p className="text-sm mt-0.5" style={{ color: '#7a90a8' }}>
                {results
                  ? `${successCount} fix${successCount !== 1 ? 'es' : ''} applied successfully`
                  : `${automatableIssues.length} issues can be fixed automatically`}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-lg flex items-center justify-center transition-colors"
            style={{ color: '#4a607a' }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLElement).style.background = '#111c2d';
              (e.currentTarget as HTMLElement).style.color = '#e8edf4';
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLElement).style.background = 'transparent';
              (e.currentTarget as HTMLElement).style.color = '#4a607a';
            }}
            aria-label="Close remediation panel"
          >
            <X className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">

          {/* Error state */}
          {error && (
            <div
              role="alert"
              className="p-4 rounded-lg flex items-start gap-3"
              style={{
                background: 'rgba(239,68,68,0.08)',
                border: '1px solid rgba(239,68,68,0.18)',
              }}
            >
              <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" style={{ color: '#fca5a5' }} aria-hidden="true" />
              <div>
                <p className="text-sm font-semibold" style={{ color: '#fca5a5' }}>Error</p>
                <p className="text-sm mt-0.5" style={{ color: '#fca5a5', opacity: 0.8 }}>{error}</p>
              </div>
            </div>
          )}

          {/* Processing */}
          {isProcessing && (
            <div
              className="p-6 rounded-lg flex flex-col items-center gap-4 text-center"
              style={{ background: 'rgba(37,99,235,0.06)', border: '1px solid rgba(37,99,235,0.15)' }}
              role="status"
              aria-live="polite"
            >
              <Loader2 className="w-8 h-8 animate-spin" style={{ color: '#60a5fa' }} aria-hidden="true" />
              <div>
                <p className="text-sm font-semibold" style={{ color: '#93c5fd' }}>Applying fixes…</p>
                <p className="text-sm mt-1" style={{ color: '#7a90a8' }}>
                  Larger PDFs may take a moment. Please wait.
                </p>
              </div>
              <div className="w-full rounded-full overflow-hidden" style={{ background: '#111c2d', height: '2px' }}>
                <div
                  className="h-full animate-pulse rounded-full"
                  style={{ background: '#2563eb', width: '60%' }}
                />
              </div>
            </div>
          )}

          {/* Pre-remediation: issue list + options */}
          {!results && !isProcessing && (
            <>
              {/* Issues to fix */}
              <div className="space-y-2">
                <p
                  className="text-xs font-semibold uppercase tracking-widest mb-3"
                  style={{ color: '#4a607a' }}
                >
                  Issues queued for auto-fix
                </p>
                <ul className="space-y-1.5" role="list">
                  {automatableIssues.slice(0, 10).map((issue) => (
                    <IssuePreview key={issue.id} issue={issue} />
                  ))}
                </ul>
                {automatableIssues.length > 10 && (
                  <p className="text-xs pt-1" style={{ color: '#4a607a' }}>
                    +{automatableIssues.length - 10} more issues
                  </p>
                )}
              </div>

              {/* Disclaimer */}
              <div
                className="p-4 rounded-lg"
                style={{ background: 'rgba(245,158,11,0.06)', border: '1px solid rgba(245,158,11,0.15)' }}
              >
                <p className="text-sm" style={{ color: '#fcd34d', opacity: 0.85 }}>
                  <strong className="font-semibold">Note:</strong> Auto-fixes apply placeholder values that require human review. Alt text, for example, will need meaningful descriptions.
                </p>
              </div>
            </>
          )}

          {/* Post-remediation results */}
          {results && !isProcessing && (
            <>
              {/* Summary */}
              <div className="grid grid-cols-2 gap-4">
                <div
                  className="p-4 rounded-lg flex items-center gap-3"
                  style={{ background: 'rgba(34,197,94,0.08)', border: '1px solid rgba(34,197,94,0.18)' }}
                >
                  <CheckCircle className="w-6 h-6 flex-shrink-0" style={{ color: '#86efac' }} aria-hidden="true" />
                  <div>
                    <p className="text-2xl font-semibold tabular-nums" style={{ color: '#86efac' }}>
                      {successCount}
                    </p>
                    <p className="text-xs mt-0.5" style={{ color: '#bbf7d0' }}>Fixed successfully</p>
                  </div>
                </div>
                {failedCount > 0 && (
                  <div
                    className="p-4 rounded-lg flex items-center gap-3"
                    style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.18)' }}
                  >
                    <XCircle className="w-6 h-6 flex-shrink-0" style={{ color: '#fca5a5' }} aria-hidden="true" />
                    <div>
                      <p className="text-2xl font-semibold tabular-nums" style={{ color: '#fca5a5' }}>
                        {failedCount}
                      </p>
                      <p className="text-xs mt-0.5" style={{ color: '#fecaca' }}>Failed</p>
                    </div>
                  </div>
                )}
              </div>

              {/* What was fixed */}
              {successCount > 0 && (
                <div
                  className="p-4 rounded-lg"
                  style={{ background: 'rgba(34,197,94,0.06)', border: '1px solid rgba(34,197,94,0.14)' }}
                >
                  <p className="text-xs font-semibold uppercase tracking-widest mb-3" style={{ color: '#86efac' }}>
                    Remediated
                  </p>
                  <ul className="space-y-2">
                    {results.filter((r) => r.success).map((result, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm" style={{ color: '#bbf7d0' }}>
                        <CheckCircle className="w-4 h-4 flex-shrink-0 mt-0.5" style={{ color: '#86efac' }} aria-hidden="true" />
                        {result.message}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Detailed results */}
              <div>
                <p className="text-xs font-semibold uppercase tracking-widest mb-3" style={{ color: '#4a607a' }}>
                  Detailed results
                </p>
                <ul className="space-y-1.5 max-h-44 overflow-y-auto" role="list">
                  {results.map((result, index) => (
                    <li
                      key={`${result.issue_id}-${index}`}
                      className="px-3 py-2.5 rounded-lg flex items-start gap-3"
                      style={
                        result.success
                          ? { background: 'rgba(34,197,94,0.06)', border: '1px solid rgba(34,197,94,0.12)' }
                          : { background: 'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.12)' }
                      }
                    >
                      {result.success ? (
                        <CheckCircle className="w-4 h-4 flex-shrink-0 mt-0.5" style={{ color: '#86efac' }} aria-hidden="true" />
                      ) : (
                        <XCircle className="w-4 h-4 flex-shrink-0 mt-0.5" style={{ color: '#fca5a5' }} aria-hidden="true" />
                      )}
                      <div className="min-w-0">
                        <p className="text-sm" style={{ color: result.success ? '#bbf7d0' : '#fecaca' }}>
                          {result.message}
                        </p>
                        {result.new_value && (
                          <p className="text-xs mt-0.5 font-mono truncate" style={{ color: '#4a607a' }}>
                            {result.new_value}
                          </p>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>

              {/* Reminder */}
              <p className="text-xs leading-relaxed" style={{ color: '#4a607a' }}>
                The remediated file is ready to download. Re-upload it to verify all changes have been applied correctly.
              </p>
            </>
          )}
        </div>

        {/* Modal footer */}
        <div
          className="px-6 py-4 flex justify-end gap-3"
          style={{ borderTop: '1px solid #1a2840' }}
        >
          {!results ? (
            <>
              <button onClick={onClose} className="btn btn-secondary" disabled={isProcessing}>
                Cancel
              </button>
              <button
                onClick={handleApplyFixes}
                className="btn btn-primary"
                disabled={isProcessing || automatableIssues.length === 0}
              >
                {isProcessing ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
                    Processing…
                  </>
                ) : (
                  <>
                    <Wrench className="w-4 h-4" aria-hidden="true" />
                    Apply {automatableIssues.length} fix{automatableIssues.length !== 1 ? 'es' : ''}
                  </>
                )}
              </button>
            </>
          ) : (
            <>
              <button onClick={onClose} className="btn btn-secondary">
                Close
              </button>
              <a
                href={getRemediatedFileURL(report.id)}
                download
                className="btn btn-primary"
              >
                <Download className="w-4 h-4" aria-hidden="true" />
                Download Fixed PDF
              </a>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Issue Preview ───────────────────────────────────────────── */
function IssuePreview({ issue }: { issue: AccessibilityIssue }) {
  return (
    <li
      className="px-3 py-2.5 rounded-lg flex items-center gap-3"
      style={{ background: '#111c2d', border: '1px solid #1a2840' }}
    >
      <span className="font-mono text-xs font-medium" style={{ color: '#60a5fa' }}>
        {issue.rule_id}
      </span>
      <span className="text-sm truncate flex-1" style={{ color: '#a0b4c8' }}>
        {issue.rule_name}
      </span>
      <span className="badge badge-success flex-shrink-0">Auto-fix</span>
    </li>
  );
}
