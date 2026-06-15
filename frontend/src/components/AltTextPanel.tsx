import { useState, useEffect } from 'react';
import {
  X,
  Sparkles,
  Loader2,
  AlertTriangle,
  FileImage,
  Check,
  EyeOff,
  Save,
} from 'lucide-react';
import type { AccessibilityReport, DocumentImageItem, AltTextResolution, AltTextContextUsed } from '../types';
import { getDocumentImages, generateAltText, resolveAltText } from '../api';

interface AltTextPanelProps {
  report: AccessibilityReport;
  onClose: () => void;
  onComplete: (updatedReport: AccessibilityReport) => void;
}

function summarizeContextUsed(context?: AltTextContextUsed | null): string {
  if (!context) return '';

  const parts: string[] = [];
  if (context.caption) parts.push('caption');
  if (context.page_text) parts.push('same-page text');
  if (context.previous_page_text || context.next_page_text) parts.push('adjacent pages');
  if (context.headings && context.headings > 0) parts.push(`${context.headings} heading${context.headings === 1 ? '' : 's'}`);
  if (context.neighboring_images && context.neighboring_images > 0) {
    parts.push(`${context.neighboring_images} nearby figure${context.neighboring_images === 1 ? '' : 's'}`);
  }
  if (parts.length === 0) return 'target image only';
  return parts.join(', ');
}

export function AltTextPanel({ report, onClose, onComplete }: AltTextPanelProps) {
  const [images, setImages] = useState<DocumentImageItem[]>([]);
  const [selectedImage, setSelectedImage] = useState<DocumentImageItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form State for selected image
  const [altText, setAltText] = useState('');
  const [isDecorative, setIsDecorative] = useState(false);

  // Local modifications map to track changes before saving
  const [pendingChanges, setPendingChanges] = useState<Record<string, { altText: string; isDecorative: boolean }>>({});
  const [generationContext, setGenerationContext] = useState<Record<string, AltTextContextUsed>>({});

  useEffect(() => {
    async function loadImages() {
      try {
        setLoading(true);
        setError(null);
        const data = await getDocumentImages(report.id);
        setImages(data);
        if (data.length > 0) {
          setSelectedImage(data[0]);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load images');
      } finally {
        setLoading(false);
      }
    }
    loadImages();
  }, [report.id]);

  // Update form values when selected image changes
  useEffect(() => {
    if (selectedImage) {
      const pending = pendingChanges[selectedImage.id];
      if (pending) {
        setAltText(pending.altText);
        setIsDecorative(pending.isDecorative);
      } else {
        setAltText(selectedImage.current_alt || '');
        setIsDecorative(selectedImage.current_alt === '');
        // If it's a placeholder, don't prefill the text with the placeholder message
        if (selectedImage.current_alt === '[Image requires alt text]') {
          setAltText('');
        }
      }
    } else {
      setAltText('');
      setIsDecorative(false);
    }
  }, [selectedImage, pendingChanges]);

  // Apply change locally for selected image
  const handleApplyToImage = () => {
    if (!selectedImage) return;

    setPendingChanges((prev) => ({
      ...prev,
      [selectedImage.id]: {
        altText: isDecorative ? '' : altText.trim(),
        isDecorative,
      },
    }));

    // Auto-advance to next image if available
    const currentIndex = images.findIndex((img) => img.id === selectedImage.id);
    if (currentIndex !== -1 && currentIndex < images.length - 1) {
      setSelectedImage(images[currentIndex + 1]);
    }
  };

  // Generate description using DeepSeek API
  const handleGenerateAI = async () => {
    if (!selectedImage) return;
    setError(null);
    setGenerating(true);

    try {
      const res = await generateAltText(report.id, selectedImage.id);
      setAltText(res.alt_text);
      setIsDecorative(false);
      setGenerationContext((prev) => ({
        ...prev,
        [selectedImage.id]: res.context_used,
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'AI Generation failed. Check API Key or OCR backend.');
    } finally {
      setGenerating(false);
    }
  };

  // Save all changes back to server
  const handleSaveAll = async () => {
    setError(null);
    setSaving(true);

    try {
      const resolutions: AltTextResolution[] = Object.entries(pendingChanges).map(([id, change]) => ({
        id,
        alt_text: change.isDecorative ? '' : change.altText,
        is_decorative: change.isDecorative,
      }));

      if (resolutions.length === 0) {
        onClose();
        return;
      }

      const response = await resolveAltText(report.id, resolutions);
      
      // Update report state in parent component
      const successfulResults = response.results.filter((r) => r.success);
      const fixedIds = new Set(successfulResults.map((r) => r.issue_id));

      const updatedIssues = report.all_issues.map((issue) => {
        const isFixed = issue.rule_id === '1.1.1' || fixedIds.has(issue.id);
        return {
          ...issue,
          fixed: issue.fixed || isFixed,
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

      const remainingErrors = updatedIssues.filter((i) => !i.fixed && i.severity === 'error').length;
      const remainingWarnings = updatedIssues.filter((i) => !i.fixed && i.severity === 'warning').length;

      onComplete({
        ...report,
        all_issues: updatedIssues,
        issues_by_principle: updatedByPrinciple,
        total_errors: remainingErrors,
        total_warnings: remainingWarnings,
        total_issues: remainingErrors + remainingWarnings,
      });

      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save resolutions');
    } finally {
      setSaving(false);
    }
  };

  // Check if an image is fully resolved (either has pending changes or original non-placeholder alt text)
  const isImageResolved = (img: DocumentImageItem) => {
    const pending = pendingChanges[img.id];
    if (pending) {
      return pending.isDecorative || pending.altText.trim().length > 0;
    }
    return img.current_alt && img.current_alt !== '[Image requires alt text]' && img.current_alt !== '';
  };

  const isImageDecorative = (img: DocumentImageItem) => {
    const pending = pendingChanges[img.id];
    if (pending) {
      return pending.isDecorative;
    }
    return img.current_alt === '';
  };

  const selectedContextSummary = selectedImage
    ? summarizeContextUsed(generationContext[selectedImage.id])
    : '';

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6"
      style={{ background: 'rgba(4, 8, 14, 0.85)' }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="alt-text-panel-title"
    >
      <div
        className="w-full max-w-5xl h-[85vh] overflow-hidden flex flex-col animate-scale-in rounded-2xl"
        style={{ background: '#0d1420', border: '1px solid #1a2840' }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-6 py-4 flex-shrink-0"
          style={{ borderBottom: '1px solid #1a2840' }}
        >
          <div className="flex items-center gap-3">
            <div
              className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
              style={{ background: 'rgba(37, 99, 235, 0.10)' }}
            >
              <FileImage className="w-5 h-5" style={{ color: '#60a5fa' }} />
            </div>
            <div>
              <h2 id="alt-text-panel-title" className="text-base font-semibold text-[#e8edf4]">
                Alt-Text Manager
              </h2>
              <p className="text-xs text-[#7a90a8] mt-0.5">
                Review and describe images to satisfy WCAG 1.1.1 Non-text Content requirements.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-[#4a607a] hover:bg-[#111c2d] hover:text-[#e8edf4] transition-colors"
            aria-label="Close alt-text manager"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content Body */}
        <div className="flex-1 min-h-0 flex flex-col md:flex-row">
          
          {/* Left Pane: Images List */}
          <div
            className="w-full md:w-80 flex-shrink-0 flex flex-col"
            style={{ borderRight: '1px solid #1a2840', background: '#080c14' }}
          >
            <div className="p-4 flex-shrink-0 flex items-center justify-between" style={{ borderBottom: '1px solid #1a2840' }}>
              <span className="text-xs font-semibold uppercase tracking-wider text-[#4a607a]">
                Document Images
              </span>
              <span className="badge badge-info">
                {images.filter(isImageResolved).length} / {images.length} Done
              </span>
            </div>
            
            <div className="flex-1 overflow-y-auto p-2 space-y-1">
              {loading ? (
                <div className="flex flex-col items-center justify-center py-20 gap-3">
                  <Loader2 className="w-6 h-6 animate-spin text-[#60a5fa]" />
                  <span className="text-xs text-[#7a90a8]">Extracting figures…</span>
                </div>
              ) : images.length === 0 ? (
                <div className="text-center py-20 px-4">
                  <p className="text-sm text-[#4a607a]">No images requiring alt-text found.</p>
                </div>
              ) : (
                images.map((img, idx) => {
                  const isSelected = selectedImage?.id === img.id;
                  const isResolved = isImageResolved(img);
                  const isDec = isImageDecorative(img);
                  const isPending = !!pendingChanges[img.id];

                  return (
                    <button
                      key={img.id}
                      onClick={() => setSelectedImage(img)}
                      className="w-full p-2.5 rounded-lg flex items-center gap-3 text-left transition-colors"
                      style={{
                        background: isSelected ? 'rgba(37, 99, 235, 0.08)' : 'transparent',
                        border: isSelected ? '1px solid #2563eb' : '1px solid transparent',
                      }}
                      onMouseEnter={(e) => {
                        if (!isSelected) e.currentTarget.style.background = '#111c2d';
                      }}
                      onMouseLeave={(e) => {
                        if (!isSelected) e.currentTarget.style.background = 'transparent';
                      }}
                    >
                      {/* Image Thumbnail wrapper */}
                      <div className="w-12 h-12 rounded border border-[#1a2840] overflow-hidden flex-shrink-0 flex items-center justify-center bg-[#111c2d]">
                        {img.image_url ? (
                          <img
                            src={img.image_url}
                            alt=""
                            className="max-w-full max-h-full object-contain"
                          />
                        ) : (
                          <FileImage className="w-5 h-5 text-[#4a607a]" />
                        )}
                      </div>
                      
                      {/* Detail */}
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-semibold text-[#e8edf4] truncate">
                          Image #{idx + 1}
                        </p>
                        <p className="text-[10px] text-[#7a90a8] mt-0.5">
                          {img.page_num ? `Page ${img.page_num}` : 'HTML Element'}
                        </p>
                        
                        <div className="flex gap-1.5 mt-1">
                          {isResolved ? (
                            isDec ? (
                              <span className="text-[9px] px-1 rounded font-medium bg-[#1e293b] text-[#94a3b8] flex items-center gap-0.5">
                                <EyeOff className="w-2 h-2" /> Decorative
                              </span>
                            ) : (
                              <span className="text-[9px] px-1 rounded font-medium bg-emerald-950/40 text-emerald-400 border border-emerald-900/30 flex items-center gap-0.5">
                                <Check className="w-2 h-2" /> Resolved {isPending && '*'}
                              </span>
                            )
                          ) : (
                            <span className="text-[9px] px-1 rounded font-medium bg-amber-950/40 text-amber-400 border border-amber-900/30 flex items-center gap-0.5">
                              <AlertTriangle className="w-2.5 h-2.5" /> Alt Text Missing
                            </span>
                          )}
                        </div>
                      </div>
                    </button>
                  );
                })
              )}
            </div>
          </div>

          {/* Right Pane: Editor */}
          <div className="flex-1 flex flex-col bg-[#0b1019] min-w-0">
            {error && (
              <div className="p-4 bg-red-950/30 border-b border-red-900/30 flex items-start gap-3 text-red-400 text-xs">
                <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                <div className="flex-1">
                  <p className="font-semibold">Error</p>
                  <p className="opacity-90 mt-0.5">{error}</p>
                </div>
              </div>
            )}

            {selectedImage ? (
              <div className="flex-1 flex flex-col md:flex-row min-h-0 overflow-y-auto">
                {/* Preview side */}
                <div className="flex-1 p-6 flex flex-col min-w-0 justify-center items-center">
                  <span className="text-xs text-[#7a90a8] mb-3 self-start font-medium uppercase tracking-wider">
                    Image Preview
                  </span>
                  
                  {/* Image Display Frame with Grid Checkerboard Background for Transparency */}
                  <div
                    className="w-full flex-1 min-h-[200px] md:min-h-0 max-h-[350px] md:max-h-full rounded-xl border border-[#1a2840] overflow-hidden flex items-center justify-center p-6 relative"
                    style={{
                      backgroundImage: `
                        linear-gradient(45deg, #111c2d 25%, transparent 25%), 
                        linear-gradient(-45deg, #111c2d 25%, transparent 25%), 
                        linear-gradient(45deg, transparent 75%, #111c2d 75%), 
                        linear-gradient(-45deg, transparent 75%, #111c2d 75%)
                      `,
                      backgroundSize: '20px 20px',
                      backgroundPosition: '0 0, 0 10px, 10px -10px, -10px 0',
                      backgroundColor: '#070b12',
                    }}
                  >
                    {selectedImage.image_url ? (
                      <img
                        src={selectedImage.image_url}
                        alt="Previewing document figure"
                        className="max-w-full max-h-full object-contain rounded drop-shadow-md select-none pointer-events-none"
                      />
                    ) : (
                      <div className="text-center space-y-2">
                        <FileImage className="w-12 h-12 text-[#4a607a] mx-auto animate-pulse" />
                        <p className="text-xs text-[#7a90a8]">No visual crop available for this image</p>
                      </div>
                    )}
                  </div>
                </div>

                {/* Form side */}
                <div
                  className="w-full md:w-96 p-6 flex flex-col flex-shrink-0 space-y-6"
                  style={{ borderLeft: '1px solid #1a2840', background: '#0a0f18' }}
                >
                  {/* Alt text options */}
                  <div className="space-y-4 flex-1">
                    <span className="text-xs font-semibold text-[#7a90a8] uppercase tracking-wide block">
                      Choose Resolution Method
                    </span>

                    {/* Option 1: AI Generated Alt-Text */}
                    <div className="space-y-2">
                      <p className="text-xs text-[#a0b4c8] leading-relaxed">
                        Use DeepSeek vision intelligence to analyze the crop and output WCAG-compliant descriptive text.
                      </p>
                      <button
                        type="button"
                        onClick={handleGenerateAI}
                        disabled={generating || saving}
                        className="btn btn-secondary w-full justify-center flex items-center gap-2"
                      >
                        {generating ? (
                          <>
                            <Loader2 className="w-4 h-4 animate-spin" />
                            Analyzing image…
                          </>
                        ) : (
                          <>
                            <Sparkles className="w-4 h-4 text-[#fcd34d]" />
                            Generate with DeepSeek AI
                          </>
                        )}
                      </button>
                      {selectedContextSummary ? (
                        <p className="text-[10px] text-[#7a90a8] leading-relaxed">
                          Context used: {selectedContextSummary}.
                        </p>
                      ) : null}
                    </div>

                    <div className="flex items-center gap-3 my-4">
                      <div className="h-px flex-1" style={{ background: '#162238' }} />
                      <span className="text-[10px] font-semibold text-[#4a607a] uppercase tracking-wider">or</span>
                      <div className="h-px flex-1" style={{ background: '#162238' }} />
                    </div>

                    {/* Option 2: Manual text */}
                    <div className="space-y-3">
                      <div className="flex items-center justify-between">
                        <label className="text-xs font-medium text-[#c8d8e8]">
                          Manual Alt-Text Input
                        </label>
                        <label className="flex items-center gap-1.5 cursor-pointer select-none">
                          <input
                            type="checkbox"
                            checked={isDecorative}
                            onChange={(e) => setIsDecorative(e.target.checked)}
                            className="w-3.5 h-3.5 rounded"
                            style={{ accentColor: '#2563eb' }}
                          />
                          <span className="text-xs text-[#7a90a8] font-medium flex items-center gap-1">
                            <EyeOff className="w-3.5 h-3.5" /> Decorative
                          </span>
                        </label>
                      </div>

                      <textarea
                        rows={4}
                        placeholder={
                          isDecorative
                            ? 'Marked as decorative. Screen readers will skip this image.'
                            : 'Describe the image concisely for screen-reader users…'
                        }
                        disabled={isDecorative || generating}
                        value={altText}
                        onChange={(e) => setAltText(e.target.value)}
                        className="w-full p-3 text-xs rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 leading-relaxed resize-none"
                        style={{
                          background: isDecorative ? '#0b1019' : '#111c2d',
                          border: '1px solid #1a2840',
                          color: isDecorative ? '#4a607a' : '#e8edf4',
                        }}
                      />
                    </div>
                  </div>

                  {/* Apply actions */}
                  <div className="pt-4 flex gap-2" style={{ borderTop: '1px solid #162238' }}>
                    <button
                      type="button"
                      disabled={generating || (!isDecorative && !altText.trim())}
                      onClick={handleApplyToImage}
                      className="btn btn-primary w-full justify-center"
                    >
                      Apply & Continue
                    </button>
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex-1 flex items-center justify-center p-6 text-center">
                <div className="space-y-3 max-w-sm">
                  <FileImage className="w-12 h-12 text-[#4a607a] mx-auto opacity-40" />
                  <p className="text-sm font-semibold text-[#e8edf4]">No Image Selected</p>
                  <p className="text-xs text-[#7a90a8]">
                    Select an image from the sidebar list to describe it or run AI vision.
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Footer Actions */}
        <div
          className="px-6 py-4 flex justify-between items-center flex-shrink-0"
          style={{ borderTop: '1px solid #1a2840', background: '#0a0f18' }}
        >
          <div className="text-xs text-[#4a607a]">
            {Object.keys(pendingChanges).length} pending modifications
          </div>
          
          <div className="flex gap-3">
            <button
              onClick={onClose}
              disabled={saving}
              className="btn btn-secondary"
            >
              Cancel
            </button>
            <button
              onClick={handleSaveAll}
              disabled={saving || Object.keys(pendingChanges).length === 0}
              className="btn btn-primary"
            >
              {saving ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Remediating PDF…
                </>
              ) : (
                <>
                  <Save className="w-4 h-4" />
                  Save & Remediate Document
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
