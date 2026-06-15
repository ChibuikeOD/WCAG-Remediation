"""
Pydantic models for the WCAG Accessibility Remediation Platform.
"""
from enum import Enum
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field
from datetime import datetime


class WCAGLevel(str, Enum):
    """WCAG conformance levels."""
    A = "A"
    AA = "AA"
    AAA = "AAA"


class WCAGPrinciple(str, Enum):
    """WCAG principles."""
    PERCEIVABLE = "Perceivable"
    OPERABLE = "Operable"
    UNDERSTANDABLE = "Understandable"
    ROBUST = "Robust"


class Severity(str, Enum):
    """Issue severity levels."""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class IssueStatus(str, Enum):
    """Status of an accessibility issue."""
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    MANUAL_REVIEW = "manual_review"
    NOT_APPLICABLE = "not_applicable"


class SelectorCheck(BaseModel):
    """A CSS selector-based accessibility check."""
    selector: str
    error: str
    fix: str
    severity: Severity = Severity.ERROR
    check_type: Optional[str] = None
    min_ratio: Optional[float] = None
    large_text_ratio: Optional[float] = None
    min_size: Optional[int] = None
    patterns_to_flag: Optional[List[str]] = None


class WCAGRule(BaseModel):
    """A single WCAG success criterion rule."""
    id: str
    name: str
    wcag_level: WCAGLevel
    description: str
    automatable: bool
    automation_notes: str
    selector_checks: List[SelectorCheck] = []
    manual_review_required: bool
    manual_review_notes: Optional[str] = None
    tags: List[str] = []
    deprecated: Optional[bool] = False
    deprecation_note: Optional[str] = None


class RuleFile(BaseModel):
    """A WCAG rule file containing multiple rules."""
    principle: WCAGPrinciple
    principle_number: int
    rules: List[WCAGRule]


class ElementLocation(BaseModel):
    """Location of an element in the document."""
    selector: str
    xpath: Optional[str] = None
    line_number: Optional[int] = None
    column_number: Optional[int] = None
    page_number: Optional[int] = None  # For PDFs
    html_snippet: Optional[str] = None


class AccessibilityIssue(BaseModel):
    """A detected accessibility issue."""
    id: str = Field(default_factory=lambda: str(datetime.now().timestamp()))
    rule_id: str
    rule_name: str
    principle: WCAGPrinciple
    wcag_level: WCAGLevel
    status: IssueStatus
    severity: Severity
    message: str
    fix_suggestion: str
    element_location: Optional[ElementLocation] = None
    evidence: Optional[Dict[str, Any]] = None
    automatable_fix: bool = False
    fixed: bool = False
    user_override: Optional[str] = None


class DocumentInfo(BaseModel):
    """Information about the analyzed document."""
    filename: str
    file_type: str  # "html", "pdf", "url"
    file_size: Optional[int] = None
    page_count: Optional[int] = None  # For PDFs
    url: Optional[str] = None
    title: Optional[str] = None
    language: Optional[str] = None
    analyzed_at: datetime = Field(default_factory=datetime.now)


class PrincipleSummary(BaseModel):
    """Summary of issues for a WCAG principle."""
    principle: WCAGPrinciple
    principle_number: int
    total_issues: int
    errors: int
    warnings: int
    passed: int
    manual_review: int


class AccessibilityReport(BaseModel):
    """Complete accessibility analysis report."""
    id: str = Field(default_factory=lambda: str(datetime.now().timestamp()))
    document: DocumentInfo
    wcag_version: str = "2.2"
    target_level: WCAGLevel = WCAGLevel.AA
    
    # Summary statistics
    total_issues: int = 0
    total_errors: int = 0
    total_warnings: int = 0
    total_passed: int = 0
    total_manual_review: int = 0
    
    # Issues grouped by principle
    principle_summaries: List[PrincipleSummary] = []
    issues_by_principle: Dict[str, List[AccessibilityIssue]] = {}
    
    # All issues flat list
    all_issues: List[AccessibilityIssue] = []
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    processing_time_ms: Optional[float] = None


class RemediationRequest(BaseModel):
    """Request to apply automated remediations."""
    report_id: str
    issue_ids: Optional[List[str]] = None  # None means apply all automatable
    apply_all_automatable: bool = False
    overwrite_tags: bool = True  # Always rebuild structure tree by default; pass False to opt out


class RemediationResult(BaseModel):
    """Result of a remediation operation."""
    issue_id: str
    success: bool
    message: str
    original_value: Optional[str] = None
    new_value: Optional[str] = None


class RemediationResponse(BaseModel):
    """Response from remediation endpoint."""
    report_id: str
    total_fixed: int
    total_failed: int
    results: List[RemediationResult]
    remediated_file_path: Optional[str] = None
    remediation_report_path: Optional[str] = None
    remediation_report_filename: Optional[str] = None


class UploadResponse(BaseModel):
    """Response from upload endpoint."""
    success: bool
    message: str
    file_id: Optional[str] = None
    file_type: Optional[str] = None
    original_filename: Optional[str] = None


class AnalyzeRequest(BaseModel):
    """Request to analyze a document or URL."""
    file_id: Optional[str] = None
    url: Optional[str] = None
    target_level: WCAGLevel = WCAGLevel.AA
    include_aaa: bool = False


class ContrastResult(BaseModel):
    """Result of a contrast check."""
    foreground_color: str
    background_color: str
    contrast_ratio: float
    passes_aa_normal: bool
    passes_aa_large: bool
    passes_aaa_normal: bool
    passes_aaa_large: bool
    font_size: Optional[float] = None
    is_bold: Optional[bool] = None
    is_large_text: bool = False


class DocumentImageItem(BaseModel):
    """Represents an extracted image/figure from the document."""
    id: str
    page_num: Optional[int] = None  # None for HTML
    current_alt: str
    image_url: Optional[str] = None  # base64 data URL
    figure_order: Optional[int] = None
    bbox: Optional[List[float]] = None
    caption: Optional[str] = None
    nearby_text: Optional[str] = None
    neighbor_image_ids: List[str] = Field(default_factory=list)


class AltTextResolution(BaseModel):
    """Represents the resolution for a single image/figure."""
    id: str
    alt_text: str
    is_decorative: bool = False


class AltTextResolutionRequest(BaseModel):
    """Payload to resolve alt-text for one or more images/figures."""
    resolutions: List[AltTextResolution]


class AltTextGenerateRequest(BaseModel):
    """Payload to request AI alt-text generation."""
    image_id: str
    api_key: Optional[str] = None
    context_mode: Literal["minimal", "balanced", "maximum"] = "balanced"


class AltTextGenerateResponse(BaseModel):
    """Response from AI alt-text generation."""
    alt_text: str
    context_used: Dict[str, Any] = Field(default_factory=dict)






