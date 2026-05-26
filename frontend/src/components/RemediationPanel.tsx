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
  Layers,
  GitCompare
} from 'lucide-react';
import type {
  AccessibilityReport,
  AccessibilityIssue,
  RemediationResult,
  TaggingComparisonReport,
} from '../types';
import {
  remediateDocument,
  getRemediatedFileURL,
  generateModelOverlays,
  compareTaggingPipelines,
} from '../api';

interface RemediationPanelProps {
  report: AccessibilityReport;
  onClose: () => void;
  onComplete: (updatedReport: AccessibilityReport) => void;
}

const PDF_ISSUE_ID_TO_RULE: Record<string, string> = {
  'pdf-title': '2.4.2',
  'pdf-lang': '3.1.1',
  'pdf-auto-tag': '1.3.1',
  'pdf-heading-hierarchy': '1.3.1',
  'pdf-table-headers': '1.3.1',
  'pdf-list-structure': '1.3.1',
  'pdf-span-overuse': '1.3.1',
  'pdf-reading-order': '1.3.2',
  'pdf-untagged-urls': '2.4.4',
  'pdf-bookmarks': '2.4.5',
  'pdf-ocr': '1.4.5',
  'pdf-form-labels': '3.3.2',
};

export function RemediationPanel({ report, onClose, onComplete }: RemediationPanelProps) {
  const [isProcessing, setIsProcessing] = useState(false);
  const [results, setResults] = useState<RemediationResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [debugOverlays, setDebugOverlays] = useState(false);
  const [overlayLoading, setOverlayLoading] = useState(false);
  const [overlayDone, setOverlayDone] = useState(false);
  const [overwriteTags, setOverwriteTags] = useState(false);
  const [compareTagging, setCompareTagging] = useState(false);
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareResult, setCompareResult] = useState<TaggingComparisonReport | null>(null);

  const isPdf = report.document.file_type === 'pdf';
  const automatableIssues = report.all_issues.filter(i => i.automatable_fix && !i.fixed);

  const handleCompareTagging = async () => {
    setCompareLoading(true);
    setError(null);
    try {
      if (compareTagging) {
        const blob = await compareTaggingPipelines(report.id, { includeOverlays: true });
        const url = URL.createObjectURL(blob as Blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `tagging_compare_${report.document.filename.replace(/\.pdf$/i, '')}.zip`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      } else {
        const data = (await compareTaggingPipelines(report.id)) as TaggingComparisonReport;
        setCompareResult(data);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Tagging comparison failed');
    } finally {
      setCompareLoading(false);
    }
  };

  const handleDownloadOverlays = async () => {
    setOverlayLoading(true);
    try {
      const blob = await generateModelOverlays(report.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `layout_overlays.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setOverlayDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Overlay generation failed');
    } finally {
      setOverlayLoading(false);
    }
  };

  const handleApplyFixes = async () => {
    setIsProcessing(true);
    setError(null);

    try {
      const response = await remediateDocument({
        report_id: report.id,
        apply_all_automatable: true,
        ...(overwriteTags && { overwrite_tags: true }),
      });

      setResults(response.results);

      const successfulResults = response.results.filter(r => r.success);

      const fixedRuleIds = new Set<string>();
      for (const r of successfulResults) {
        const mappedRule = PDF_ISSUE_ID_TO_RULE[r.issue_id];
        if (mappedRule) {
          fixedRuleIds.add(mappedRule);
        }
        fixedRuleIds.add(r.issue_id);
      }

      const updatedIssues = report.all_issues.map(issue => {
        const isFixed = fixedRuleIds.has(issue.rule_id) || fixedRuleIds.has(issue.id);
        return {
          ...issue,
          fixed: issue.fixed || isFixed,
          status: isFixed ? ('pass' as const) : issue.status,
        };
      });

      const updatedByPrinciple: Record<string, typeof updatedIssues> = {};
      for (const issue of updatedIssues) {
        const principle = issue.principle;
        if (!updatedByPrinciple[principle]) {
          updatedByPrinciple[principle] = [];
        }
        updatedByPrinciple[principle].push(issue);
      }

      const remainingErrors = updatedIssues.filter(i => !i.fixed && i.severity === 'error').length;
      const remainingWarnings = updatedIssues.filter(i => !i.fixed && i.severity === 'warning').length;

      const updatedReport: AccessibilityReport = {
        ...report,
        all_issues: updatedIssues,
        issues_by_principle: updatedByPrinciple,
        total_errors: remainingErrors,
        total_warnings: remainingWarnings,
        total_issues: remainingErrors + remainingWarnings,
      };

      onComplete(updatedReport);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Remediation failed');
    } finally {
      setIsProcessing(false);
    }
  };

  const successCount = results?.filter(r => r.success).length ?? 0;
  const failedCount = results?.filter(r => !r.success).length ?? 0;

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="remediation-title"
    >
      <div className="bg-surface-900 border border-zinc-800 rounded-2xl w-full max-w-2xl max-h-[80vh] overflow-hidden flex flex-col animate-scale-in">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-zinc-800">
          <div className="flex items-center gap-3">
            <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
              results ? 'bg-emerald-500/20' : 'bg-cyan-500/20'
            }`}>
              {results ? (
                <FileCheck className="w-5 h-5 text-emerald-400" aria-hidden="true" />
              ) : (
                <Wrench className="w-5 h-5 text-cyan-400" aria-hidden="true" />
              )}
            </div>
            <div>
              <h2 id="remediation-title" className="text-lg font-semibold text-zinc-100">
                {results ? 'Auto-fix run complete' : 'Try auto-fixes'}
              </h2>
              <p className="text-sm text-zinc-400">
                {results
                  ? `${successCount} fix${successCount !== 1 ? 'es' : ''} applied successfully`
                  : `${automatableIssues.length} issues can be fixed automatically`}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-zinc-400 hover:text-zinc-100 rounded-lg hover:bg-zinc-800 transition-colors"
            aria-label="Close remediation panel"
          >
            <X className="w-5 h-5" aria-hidden="true" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {error && (
            <div 
              role="alert" 
              className="mb-6 p-4 bg-red-500/20 border border-red-500/30 rounded-lg flex items-start gap-3"
            >
              <AlertTriangle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" aria-hidden="true" />
              <div>
                <p className="font-medium text-red-400">Error</p>
                <p className="text-sm text-red-300">{error}</p>
              </div>
            </div>
          )}

          {/* Processing state */}
          {isProcessing && (
            <div className="p-6 bg-cyan-500/10 border border-cyan-500/30 rounded-lg" role="status" aria-live="polite">
              <div className="flex flex-col items-center text-center gap-4">
                <Loader2 className="w-10 h-10 text-cyan-400 animate-spin" aria-hidden="true" />
                <div>
                  <p className="font-medium text-cyan-300">Applying Fixes...</p>
                  <p className="text-sm text-zinc-400 mt-1">
                    Trying the automated fixes on your document.
                    Larger PDFs can take a bit.
                  </p>
                </div>
                <div className="w-full bg-zinc-800 rounded-full h-1.5 overflow-hidden">
                  <div className="bg-cyan-500 h-1.5 rounded-full animate-pulse w-2/3" />
                </div>
              </div>
            </div>
          )}

          {/* Pre-remediation: issue list + options */}
          {!results && !isProcessing && (
            <>
              <div className="space-y-3 mb-6">
                <h3 className="text-sm font-medium text-zinc-400 uppercase tracking-wider">
                  Issues to Fix
                </h3>
                <ul className="space-y-2" role="list">
                  {automatableIssues.slice(0, 10).map((issue) => (
                    <IssuePreview key={issue.id} issue={issue} />
                  ))}
                </ul>
                {automatableIssues.length > 10 && (
                  <p className="text-sm text-zinc-500">
                    And {automatableIssues.length - 10} more...
                  </p>
                )}
              </div>

              {isPdf && (
                <div className="mb-6 space-y-3">
                  <div className="p-4 bg-zinc-800/50 border border-zinc-700 rounded-lg">
                    <label className="flex items-start gap-3 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={overwriteTags}
                        onChange={(e) => setOverwriteTags(e.target.checked)}
                        className="mt-1 w-4 h-4 rounded border-zinc-600 bg-zinc-800 text-cyan-500 focus:ring-cyan-500 focus:ring-offset-0"
                      />
                      <div>
                        <span className="font-medium text-zinc-300">
                          Overwrite existing tags (rebuild structure with LayoutLM)
                        </span>
                        <p className="text-xs text-amber-400/80 mt-1">
                          Forces LayoutLM to re-tag the entire PDF even if it already has a
                          structure tree. Use for "fake-tagged" PDFs with low-quality tags.
                        </p>
                      </div>
                    </label>
                  </div>
                  <div className="p-4 bg-zinc-800/50 border border-zinc-700 rounded-lg">
                    <label className="flex items-start gap-3 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={debugOverlays}
                        onChange={(e) => setDebugOverlays(e.target.checked)}
                        className="mt-1 w-4 h-4 rounded border-zinc-600 bg-zinc-800 text-cyan-500 focus:ring-cyan-500 focus:ring-offset-0"
                      />
                      <div>
                        <div className="flex items-center gap-2">
                          <Layers className="w-4 h-4 text-zinc-400" aria-hidden="true" />
                          <span className="font-medium text-zinc-300">
                            Generate layout overlay images (debug)
                          </span>
                        </div>
                        <p className="text-xs text-zinc-500 mt-1">
                          Creates annotated page images showing the detected blocks for each page
                          (tag, text). Downloads as a ZIP after remediation.
                        </p>
                      </div>
                    </label>
                  </div>
                  <div className="p-4 bg-zinc-800/50 border border-zinc-700 rounded-lg space-y-3">
                    <label className="flex items-start gap-3 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={compareTagging}
                        onChange={(e) => setCompareTagging(e.target.checked)}
                        className="mt-1 w-4 h-4 rounded border-zinc-600 bg-zinc-800 text-cyan-500 focus:ring-cyan-500 focus:ring-offset-0"
                      />
                      <div>
                        <div className="flex items-center gap-2">
                          <GitCompare className="w-4 h-4 text-zinc-400" aria-hidden="true" />
                          <span className="font-medium text-zinc-300">
                            Include overlay images in comparison ZIP
                          </span>
                        </div>
                        <p className="text-xs text-zinc-500 mt-1">
                          Runs LayoutLM and OpenDataLoader on the same PDF and compares block tags.
                        </p>
                      </div>
                    </label>
                    <button
                      type="button"
                      onClick={handleCompareTagging}
                      disabled={compareLoading}
                      className="btn btn-secondary w-full"
                    >
                      {compareLoading ? (
                        <>
                          <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
                          Comparing pipelines...
                        </>
                      ) : (
                        <>
                          <GitCompare className="w-4 h-4" aria-hidden="true" />
                          Compare LayoutLM vs OpenDataLoader
                        </>
                      )}
                    </button>
                  </div>
                </div>
              )}

              {compareResult?.comparison?.summary && (
                <div className="mb-6 p-4 bg-violet-500/10 border border-violet-500/30 rounded-lg text-sm text-violet-100 space-y-2">
                  <p className="font-semibold text-violet-200">Tagging comparison summary</p>
                  <p>
                    LayoutLM blocks: {compareResult.comparison.summary.layoutlm.blocks}
                    {' · '}
                    OpenDataLoader blocks: {compareResult.comparison.summary.opendataloader.blocks}
                  </p>
                  <p>
                    Matched pairs: {compareResult.comparison.summary.matched_block_pairs}
                    {' · '}
                    Tag agreement:{' '}
                    {compareResult.comparison.summary.overall_agreement_rate != null
                      ? `${Math.round(compareResult.comparison.summary.overall_agreement_rate * 100)}%`
                      : 'n/a'}
                  </p>
                  {compareResult.report_filename && (
                    <p className="text-xs text-violet-300/80">
                      Full report saved as {compareResult.report_filename} on the server.
                    </p>
                  )}
                </div>
              )}

              <div className="p-4 bg-amber-500/10 border border-amber-500/30 rounded-lg">
                <p className="text-sm text-amber-400">
                  <strong>Note:</strong> Automated fixes add placeholder values that you should review. 
                  For example, alt text will need meaningful descriptions.
                </p>
              </div>
            </>
          )}

          {/* Post-remediation: results summary */}
          {results && !isProcessing && (
            <>
              {/* Summary cards */}
              <div className="grid grid-cols-2 gap-4 mb-6">
                <div className="p-4 bg-emerald-500/10 border border-emerald-500/30 rounded-lg flex items-center gap-3">
                  <CheckCircle className="w-6 h-6 text-emerald-400" aria-hidden="true" />
                  <div>
                    <p className="text-2xl font-bold text-emerald-400">{successCount}</p>
                    <p className="text-sm text-emerald-300">Fixed Successfully</p>
                  </div>
                </div>
                {failedCount > 0 && (
                  <div className="p-4 bg-red-500/10 border border-red-500/30 rounded-lg flex items-center gap-3">
                    <XCircle className="w-6 h-6 text-red-400" aria-hidden="true" />
                    <div>
                      <p className="text-2xl font-bold text-red-400">{failedCount}</p>
                      <p className="text-sm text-red-300">Failed</p>
                    </div>
                  </div>
                )}
              </div>

              {/* What was fixed - plain language summary */}
              {successCount > 0 && (
                <div className="mb-6 p-4 bg-emerald-500/10 border border-emerald-500/30 rounded-lg">
                  <h3 className="text-sm font-semibold text-emerald-300 mb-2">
                    What was remediated:
                  </h3>
                  <ul className="space-y-1.5">
                    {results.filter(r => r.success).map((result, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm text-emerald-200">
                        <CheckCircle className="w-4 h-4 text-emerald-400 flex-shrink-0 mt-0.5" aria-hidden="true" />
                        <span>{result.message}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Detailed results */}
              <div className="space-y-2">
                <h3 className="text-sm font-medium text-zinc-400 uppercase tracking-wider mb-3">
                  Detailed Results
                </h3>
                <ul className="space-y-2 max-h-48 overflow-y-auto" role="list">
                  {results.map((result, index) => (
                    <li 
                      key={`${result.issue_id}-${index}`}
                      className={`p-3 rounded-lg flex items-start gap-3 ${
                        result.success 
                          ? 'bg-emerald-500/10 border border-emerald-500/30' 
                          : 'bg-red-500/10 border border-red-500/30'
                      }`}
                    >
                      {result.success ? (
                        <CheckCircle className="w-5 h-5 text-emerald-400 flex-shrink-0" aria-hidden="true" />
                      ) : (
                        <XCircle className="w-5 h-5 text-red-400 flex-shrink-0" aria-hidden="true" />
                      )}
                      <div className="min-w-0">
                        <p className={`text-sm ${result.success ? 'text-emerald-300' : 'text-red-300'}`}>
                          {result.message}
                        </p>
                        {result.new_value && (
                          <p className="text-xs text-zinc-500 mt-1 font-mono truncate">
                            New value: {result.new_value}
                          </p>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>

              {/* Reminder */}
              <div className="mt-4 p-3 bg-zinc-800/50 rounded-lg">
                <p className="text-xs text-zinc-500">
                  The remediated file is ready to download. Issues marked as fixed have been 
                  updated in the dashboard. Re-upload the fixed file to verify all changes.
                </p>
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="p-6 border-t border-zinc-800 flex justify-end gap-3">
          {!results ? (
            <>
              <button
                onClick={onClose}
                className="btn btn-secondary"
                disabled={isProcessing}
              >
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
                    Processing...
                  </>
                ) : (
                  <>
                    <Wrench className="w-4 h-4" aria-hidden="true" />
                    Apply {automatableIssues.length} Fixes
                  </>
                )}
              </button>
            </>
          ) : (
            <>
              <button
                onClick={onClose}
                className="btn btn-secondary"
              >
                Close
              </button>
              {debugOverlays && isPdf && (
                <button
                  onClick={handleDownloadOverlays}
                  disabled={overlayLoading}
                  className="btn btn-secondary"
                >
                  {overlayLoading ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
                      Generating...
                    </>
                  ) : overlayDone ? (
                    <>
                      <CheckCircle className="w-4 h-4 text-emerald-400" aria-hidden="true" />
                      Overlays Downloaded
                    </>
                  ) : (
                    <>
                      <Layers className="w-4 h-4" aria-hidden="true" />
                      Download Overlays
                    </>
                  )}
                </button>
              )}
              <a
                href={getRemediatedFileURL(report.id)}
                download
                className="btn btn-primary"
              >
                <Download className="w-4 h-4" aria-hidden="true" />
                Download Fixed File
              </a>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function IssuePreview({ issue }: { issue: AccessibilityIssue }) {
  return (
    <li className="p-3 bg-zinc-800/50 rounded-lg flex items-center gap-3">
      <span className="font-mono text-sm text-cyan-400">{issue.rule_id}</span>
      <span className="text-sm text-zinc-300 truncate">{issue.rule_name}</span>
      <span className="badge badge-success ml-auto">Auto-fix</span>
    </li>
  );
}
