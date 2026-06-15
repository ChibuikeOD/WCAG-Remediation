// API client for WCAG Accessibility Platform

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

class APIError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'APIError';
  }
}

// User representation returned by SSO /auth/me
export interface UserSession {
  authenticated: boolean;
  id?: string;
  name?: string;
  email?: string;
  created_at?: string;
}

async function fetchJSON<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    credentials: 'same-origin', // Ensure session cookies are sent for auth
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new APIError(response.status, error.detail || 'Request failed');
  }

  return response.json();
}

// Fetch active user session
export async function getCurrentUser(): Promise<UserSession> {
  return fetchJSON<UserSession>(`${API_BASE}/auth/me`);
}

// Get OIDC / SSO Login URL
export function getLoginURL(redirect_to: string = '/'): string {
  return `${API_BASE}/auth/login?redirect_to=${encodeURIComponent(redirect_to)}`;
}

// Get OIDC / SSO Logout URL
export function getLogoutURL(): string {
  return `${API_BASE}/auth/logout`;
}

// Upload a file for analysis
export async function uploadFile(file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch(`${API_BASE}/upload`, {
    method: 'POST',
    body: formData,
    credentials: 'same-origin', // Ensure cookies are sent
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Upload failed' }));
    throw new APIError(response.status, error.detail);
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
  overwrite_tags?: boolean;
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

// Compare LayoutLM vs OpenDataLoader tagging (JSON report, or ZIP with overlays)
export async function compareTaggingPipelines(
  reportId: string,
  options?: { includeOverlays?: boolean; confidenceThreshold?: number }
): Promise<TaggingComparisonReport | Blob> {
  const response = await fetch(`${API_BASE}/pdf/debug/compare-tagging`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
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
    headers: { 'Content-Type': 'application/json' },
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
  imageId: string,
  apiKey?: string
): Promise<AltTextGenerateResponse> {
  return fetchJSON<AltTextGenerateResponse>(`${API_BASE}/report/${reportId}/generate-alt-text`, {
    method: 'POST',
    body: JSON.stringify({ image_id: imageId, api_key: apiKey, context_mode: 'balanced' }),
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





