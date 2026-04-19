// API client for WCAG Accessibility Platform

import type {
  AccessibilityReport,
  UploadResponse,
  RemediationResponse,
  WCAGLevel,
  WCAGRule,
} from './types';

const API_BASE = '/api';

class APIError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'APIError';
  }
}

async function fetchJSON<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
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

// Upload a file for analysis
export async function uploadFile(file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch(`${API_BASE}/upload`, {
    method: 'POST',
    body: formData,
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





