// WCAG Types matching backend models

export type WCAGLevel = 'A' | 'AA' | 'AAA';

export type WCAGPrinciple = 'Perceivable' | 'Operable' | 'Understandable' | 'Robust';

export type Severity = 'error' | 'warning' | 'info';

export type IssueStatus = 'pass' | 'fail' | 'warning' | 'manual_review' | 'not_applicable';

export interface ElementLocation {
  selector: string;
  xpath?: string;
  line_number?: number;
  column_number?: number;
  page_number?: number;
  html_snippet?: string;
}

export interface AccessibilityIssue {
  id: string;
  rule_id: string;
  rule_name: string;
  principle: WCAGPrinciple;
  wcag_level: WCAGLevel;
  status: IssueStatus;
  severity: Severity;
  message: string;
  fix_suggestion: string;
  element_location?: ElementLocation;
  evidence?: Record<string, unknown>;
  automatable_fix: boolean;
  fixed: boolean;
  user_override?: string;
}

export interface DocumentInfo {
  filename: string;
  file_type: string;
  file_size?: number;
  page_count?: number;
  url?: string;
  title?: string;
  language?: string;
  analyzed_at: string;
}

export interface PrincipleSummary {
  principle: WCAGPrinciple;
  principle_number: number;
  total_issues: number;
  errors: number;
  warnings: number;
  passed: number;
  manual_review: number;
}

export interface AccessibilityReport {
  id: string;
  document: DocumentInfo;
  wcag_version: string;
  target_level: WCAGLevel;
  total_issues: number;
  total_errors: number;
  total_warnings: number;
  total_passed: number;
  total_manual_review: number;
  principle_summaries: PrincipleSummary[];
  issues_by_principle: Record<string, AccessibilityIssue[]>;
  all_issues: AccessibilityIssue[];
  created_at: string;
  processing_time_ms?: number;
}

export interface UploadResponse {
  success: boolean;
  message: string;
  file_id?: string;
  file_type?: string;
  original_filename?: string;
}

export interface RemediationResult {
  issue_id: string;
  success: boolean;
  message: string;
  original_value?: string;
  new_value?: string;
}

export interface RemediationResponse {
  report_id: string;
  total_fixed: number;
  total_failed: number;
  results: RemediationResult[];
  remediated_file_path?: string;
  remediation_report_path?: string;
  remediation_report_filename?: string;
}

export interface RemediationRequest {
  report_id: string;
  issue_ids?: string[];
  apply_all_automatable?: boolean;
  overwrite_tags?: boolean;
}

export interface WCAGRule {
  id: string;
  name: string;
  wcag_level: WCAGLevel;
  description: string;
  automatable: boolean;
  tags: string[];
}

export interface TaggingComparisonSummary {
  pages: number;
  layoutlm: { blocks: number; tag_counts: Record<string, number> };
  opendataloader: { blocks: number; tag_counts: Record<string, number> };
  matched_block_pairs: number;
  tag_agreements: number;
  tag_disagreements: number;
  overall_agreement_rate: number | null;
}

export interface TaggingComparisonReport {
  document: string;
  generated_at: string;
  pipelines: {
    layoutlm: { success: boolean; error?: string | null; runtime?: string };
    opendataloader: { success: boolean; error?: string | null; runtime?: string };
  };
  comparison?: {
    summary: TaggingComparisonSummary;
    tag_count_diff: Record<string, { layoutlm: number; opendataloader: number; delta: number }>;
    pages: Array<Record<string, unknown>>;
  } | null;
  comparison_error?: string;
  report_path?: string;
  report_filename?: string;
}

export interface DocumentImageItem {
  id: string;
  page_num?: number | null;
  current_alt: string;
  image_url?: string | null;
}

export interface AltTextResolution {
  id: string;
  alt_text: string;
  is_decorative: boolean;
}






