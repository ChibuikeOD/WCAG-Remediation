// API client for PDFAccess

import type {
  AccessibilityReport,
  UploadResponse,
  RemediationResponse,
  TaggingComparisonReport,
  WCAGLevel,
  WCAGRule,
  DocumentImageItem,
  AltTextResolution,
  AltTextGenerateResponse,
} from './types';

const API_BASE = (import.meta.env.VITE_API_URL as string) || '/api';

type TrialAccessTokenGetter = () => string | null | undefined;

let trialAccessTokenGetter: TrialAccessTokenGetter = () => null;

export function registerTrialAccessTokenGetter(getter: TrialAccessTokenGetter): () => void {
  trialAccessTokenGetter = getter;

  return () => {
    if (trialAccessTokenGetter === getter) {
      trialAccessTokenGetter = () => null;
    }
  };
}

function withTrialAuthorization(
  headers: Record<string, string> = {}
): Record<string, string> {
  const token = import.meta.env.VITE_DEPLOYMENT_MODE === 'trial' ? trialAccessTokenGetter() : null;

  if (!token) {
    return headers;
  }

  return {
    ...headers,
    Authorization: `Bearer ${token}`,
  };
}

export class APIError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: unknown,
  ) {
    super(message);
    this.name = 'APIError';
  }
}

export interface TrialBalance {
  granted_pages: number;
  consumed_pages: number;
  reserved_pages: number;
  remaining_pages: number;
  normalized_domain: string;
  eligibility_rule_version: string;
}

export interface TrialPageLimitDetail {
  code: 'trial_page_limit_exceeded';
  requested_pages: number;
  remaining_pages: number;
}

function errorMessage(detail: unknown, fallback: string): string {
  return typeof detail === 'string' ? detail : fallback;
}

// User representation used by the shared testing and trial workspace.
export interface UserSession {
  authenticated: boolean;
  id?: string;
  name?: string;
  email?: string;
  created_at?: string;
}

async function fetchJSON<T>(url: string, options?: RequestInit): Promise<T> {
  const headers = withTrialAuthorization({
    'Content-Type': 'application/json',
    ...(options?.headers as Record<string, string> | undefined),
  });

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new APIError(
      response.status,
      errorMessage(error.detail, 'Request failed'),
      error.detail,
    );
  }

  return response.json();
}

export async function getTrialBalance(): Promise<TrialBalance> {
  return fetchJSON<TrialBalance>(`${API_BASE}/trial/me`);
}

// Upload a file for analysis
export async function uploadFile(file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch(`${API_BASE}/upload`, {
    method: 'POST',
    body: formData,
    headers: withTrialAuthorization(),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Upload failed' }));
    throw new APIError(
      response.status,
      errorMessage(error.detail, 'Upload failed'),
      error.detail,
    );
  }

  return response.json();
}

// Analyze a file or URL
export async function analyzeDocument(params: {
  file_id?: string;
  url?: string;
  target_level?: WCAGLevel;
  include_aaa?: boolean;
}): Promise<AccessibilityReport> {
  return fetchJSON<AccessibilityReport>(`${API_BASE}/analyze`, {
    method: 'POST',
    body: JSON.stringify(params),
  });
}

// Analyze a URL directly
export async function analyzeURL(
  url: string,
  targetLevel: WCAGLevel = 'AA',
  includeAAA = false
): Promise<AccessibilityReport> {
  const params = new URLSearchParams({
    url,
    target_level: targetLevel,
    include_aaa: String(includeAAA),
  });
  
  return fetchJSON<AccessibilityReport>(`${API_BASE}/analyze/url?${params}`);
}

// Apply remediations
export async function remediateDocument(params: {
  report_id: string;
  issue_ids?: string[];
  apply_all_automatable?: boolean;
}): Promise<RemediationResponse> {
  return fetchJSON<RemediationResponse>(`${API_BASE}/remediate`, {
    method: 'POST',
    body: JSON.stringify(params),
  });
}

// Get a report
export async function getReport(reportId: string): Promise<AccessibilityReport> {
  return fetchJSON<AccessibilityReport>(`${API_BASE}/report/${reportId}`);
}

// Get report summary
export async function getReportSummary(reportId: string): Promise<{
  report_id: string;
  document: string;
  target_level: WCAGLevel;
  total_issues: number;
  total_errors: number;
  total_warnings: number;
  total_manual_review: number;
  by_principle: Record<string, { total: number; errors: number; warnings: number }>;
  created_at: string;
  processing_time_ms?: number;
}> {
  return fetchJSON(`${API_BASE}/report/${reportId}/summary`);
}

// List rules
export async function listRules(params?: {
  level?: WCAGLevel;
  tag?: string;
  automatable?: boolean;
}): Promise<{ total: number; rules: WCAGRule[] }> {
  const searchParams = new URLSearchParams();
  if (params?.level) searchParams.set('level', params.level);
  if (params?.tag) searchParams.set('tag', params.tag);
  if (params?.automatable !== undefined) searchParams.set('automatable', String(params.automatable));

  const query = searchParams.toString();
  return fetchJSON(`${API_BASE}/rules${query ? `?${query}` : ''}`);
}

// Get specific rule
export async function getRule(ruleId: string): Promise<WCAGRule> {
  return fetchJSON<WCAGRule>(`${API_BASE}/rules/${ruleId}`);
}

// Health check
export async function healthCheck(): Promise<{
  status: string;
  rules_loaded: number;
  timestamp: string;
}> {
  return fetchJSON(`${API_BASE}/health`);
}

// Download remediated file
export function getRemediatedFileURL(reportId: string): string {
  return `${API_BASE}/remediate/download/${reportId}`;
}

export function getRemediationReportURL(reportId: string): string {
  return `${API_BASE}/remediate/report/${reportId}`;
}

async function fetchBlob(url: string): Promise<Blob> {
  const response = await fetch(url, {
    headers: withTrialAuthorization(),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Download failed' }));
    throw new APIError(response.status, error.detail || 'Download failed');
  }

  return response.blob();
}

export function downloadRemediatedFile(reportId: string): Promise<Blob> {
  return fetchBlob(getRemediatedFileURL(reportId));
}

export function downloadRemediationReport(reportId: string): Promise<Blob> {
  return fetchBlob(getRemediationReportURL(reportId));
}

// Compare LayoutLM vs OpenDataLoader tagging (JSON report, or ZIP with overlays)
export async function compareTaggingPipelines(
  reportId: string,
  options?: { includeOverlays?: boolean; confidenceThreshold?: number }
): Promise<TaggingComparisonReport | Blob> {
  const response = await fetch(`${API_BASE}/pdf/debug/compare-tagging`, {
    method: 'POST',
    headers: withTrialAuthorization({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({
      report_id: reportId,
      include_overlays: options?.includeOverlays ?? false,
      confidence_threshold: options?.confidenceThreshold ?? 0,
    }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Tagging comparison failed' }));
    throw new APIError(response.status, error.detail || 'Tagging comparison failed');
  }

  if (options?.includeOverlays) {
    return response.blob();
  }

  return response.json();
}

// Generate model overlay debug images (returns a downloadable ZIP blob)
export async function generateModelOverlays(reportId: string): Promise<Blob> {
  const response = await fetch(`${API_BASE}/pdf/debug/overlays`, {
    method: 'POST',
    headers: withTrialAuthorization({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ report_id: reportId }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Overlay generation failed' }));
    throw new APIError(response.status, error.detail || 'Overlay generation failed');
  }

  return response.blob();
}

// Export report
export async function exportReport(
  reportId: string,
  format: 'json' | 'csv' | 'html'
): Promise<{ csv?: string; html?: string } | AccessibilityReport> {
  return fetchJSON(`${API_BASE}/report/${reportId}/export?format=${format}`);
}

// Fetch document images for alt-text resolution
export async function getDocumentImages(reportId: string): Promise<DocumentImageItem[]> {
  return fetchJSON<DocumentImageItem[]>(`${API_BASE}/report/${reportId}/images`);
}

// Generate alt-text using DeepSeek AI
export async function generateAltText(
  reportId: string,
  imageId: string
): Promise<AltTextGenerateResponse> {
  return fetchJSON<AltTextGenerateResponse>(`${API_BASE}/report/${reportId}/generate-alt-text`, {
    method: 'POST',
    body: JSON.stringify({ image_id: imageId, context_mode: 'balanced' }),
  });
}

// Save resolved alt-texts back to the document
export async function resolveAltText(
  reportId: string,
  resolutions: AltTextResolution[]
): Promise<RemediationResponse> {
  return fetchJSON<RemediationResponse>(`${API_BASE}/report/${reportId}/resolve-alt-text`, {
    method: 'POST',
    body: JSON.stringify({ resolutions }),
  });
}





