"""
WCAG 2.2 Accessibility Remediation Platform - FastAPI Backend

Main application entry point providing endpoints for:
- /upload - Upload HTML/PDF files for analysis
- /analyze - Run accessibility analysis and return JSON report
- /remediate - Apply automated fixes for accessibility issues

All endpoints reference WCAG 2.2 success criteria as the source of truth.
"""
import uuid
import aiofiles
from pathlib import Path
from typing import Optional
from datetime import datetime
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, File, UploadFile, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .config import settings
from .models import (
    AccessibilityReport, DocumentInfo, WCAGLevel,
    UploadResponse, AnalyzeRequest, RemediationRequest, RemediationResponse,
    RemediationResult
)
from .rules_engine import get_rules_engine
from .parsers import HTMLParser, PDFParser
from .remediator import HTMLRemediator, PDFRemediator

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Storage for uploaded files and reports
file_storage: dict = {}
report_storage: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown."""
    # Startup
    logger.info("Starting WCAG Accessibility Remediation Platform")
    logger.info(f"Loaded {len(get_rules_engine().get_all_rules())} WCAG rules")
    
    yield
    
    # Shutdown
    logger.info("Shutting down WCAG Accessibility Remediation Platform")


app = FastAPI(
    title="WCAG 2.2 Accessibility Remediation Platform",
    description="""
    An automated accessibility audit engine for web pages and PDF documents.
    
    Based on WCAG 2.2 guidelines, this platform:
    - Analyzes HTML and PDF documents for accessibility issues
    - Provides detailed reports grouped by WCAG principle
    - Applies automated fixes where possible
    
    ## WCAG Principles
    1. **Perceivable** - Information must be presentable to users
    2. **Operable** - UI components must be operable  
    3. **Understandable** - Information and UI must be understandable
    4. **Robust** - Content must be robust for assistive technologies
    """,
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "wcag_version": "2.2",
        "endpoints": {
            "upload": "/upload",
            "analyze": "/analyze",
            "remediate": "/remediate",
            "rules": "/rules",
            "report": "/report/{report_id}"
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    engine = get_rules_engine()
    return {
        "status": "healthy",
        "rules_loaded": len(engine.get_all_rules()),
        "timestamp": datetime.now().isoformat()
    }


# =============================================================================
# Upload Endpoint
# =============================================================================

@app.post("/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...)):
    """
    Upload an HTML or PDF file for accessibility analysis.
    
    Accepts:
    - HTML files (.html, .htm)
    - PDF files (.pdf)
    
    Returns a file_id to use with the /analyze endpoint.
    """
    # Validate file type
    filename = file.filename or "unknown"
    file_ext = Path(filename).suffix.lower()
    
    allowed_extensions = {'.html', '.htm', '.pdf'}
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file_ext}. Allowed: {', '.join(allowed_extensions)}"
        )
    
    # Check file size
    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    
    if size_mb > settings.MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=400,
            detail=f"File too large: {size_mb:.1f}MB. Maximum: {settings.MAX_FILE_SIZE_MB}MB"
        )
    
    # Generate file ID and save
    file_id = str(uuid.uuid4())
    file_type = "pdf" if file_ext == ".pdf" else "html"
    
    # Save to upload directory
    save_path = settings.UPLOAD_DIR / f"{file_id}{file_ext}"
    async with aiofiles.open(save_path, 'wb') as f:
        await f.write(content)
    
    # Store metadata
    file_storage[file_id] = {
        "id": file_id,
        "original_filename": filename,
        "file_type": file_type,
        "file_path": str(save_path),
        "file_size": len(content),
        "uploaded_at": datetime.now().isoformat()
    }
    
    logger.info(f"Uploaded file: {filename} ({size_mb:.2f}MB) -> {file_id}")
    
    return UploadResponse(
        success=True,
        message="File uploaded successfully",
        file_id=file_id,
        file_type=file_type,
        original_filename=filename
    )


# =============================================================================
# Analyze Endpoint
# =============================================================================

@app.post("/analyze", response_model=AccessibilityReport)
async def analyze_document(request: AnalyzeRequest):
    """
    Analyze a document or URL for accessibility issues.
    
    Runs the document against the WCAG 2.2 rules engine and returns
    a detailed report grouped by WCAG Principle.
    
    Parameters:
    - file_id: ID from /upload endpoint
    - url: URL to analyze (alternative to file_id)
    - target_level: WCAG conformance level (A, AA, AAA)
    - include_aaa: Include AAA-level checks even if targeting lower level
    """
    if not request.file_id and not request.url:
        raise HTTPException(
            status_code=400,
            detail="Either file_id or url must be provided"
        )
    
    engine = get_rules_engine()
    
    if request.file_id:
        # Analyze uploaded file
        if request.file_id not in file_storage:
            raise HTTPException(status_code=404, detail="File not found")
        
        file_info = file_storage[request.file_id]
        file_path = Path(file_info["file_path"])
        
        if file_info["file_type"] == "html":
            # Parse and analyze HTML
            async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                html_content = await f.read()
            
            doc_info = DocumentInfo(
                filename=file_info["original_filename"],
                file_type="html",
                file_size=file_info["file_size"]
            )
            
            # Run static analysis first
            report = engine.analyze_html(
                html_content,
                doc_info,
                target_level=request.target_level,
                include_aaa=request.include_aaa
            )
            
            # Run browser-based checks (contrast, target size, focus, etc.)
            try:
                from .playwright_analyzer import get_playwright_analyzer
                from .models import Severity
                
                analyzer = await get_playwright_analyzer()
                browser_results = await analyzer.analyze_html(html_content, run_all=True)
                
                # Add browser-detected issues to report
                for issue in browser_results.get("issues", []):
                    report.all_issues.append(issue)
                    principle_key = issue.principle.value
                    if principle_key not in report.issues_by_principle:
                        report.issues_by_principle[principle_key] = []
                    report.issues_by_principle[principle_key].append(issue)
                
                # Recalculate totals
                report.total_issues = len(report.all_issues)
                report.total_errors = len([i for i in report.all_issues if i.severity == Severity.ERROR])
                report.total_warnings = len([i for i in report.all_issues if i.severity == Severity.WARNING])
                
                logger.info(f"Browser checks completed: {len(browser_results.get('issues', []))} additional issues found")
                
            except ImportError:
                logger.warning("Playwright not available - skipping browser-based checks")
            except Exception as e:
                logger.warning(f"Browser checks failed: {e}")
            
        elif file_info["file_type"] == "pdf":
            # Parse and analyze PDF
            parser = PDFParser(file_path=file_path)
            
            try:
                summary = parser.get_accessibility_summary()
                
                doc_info = DocumentInfo(
                    filename=file_info["original_filename"],
                    file_type="pdf",
                    file_size=file_info["file_size"],
                    page_count=summary["metadata"].get("page_count"),
                    title=summary["metadata"].get("title"),
                    language=summary["metadata"].get("language")
                )
                
                # For PDF, create report from summary
                from .models import AccessibilityIssue, IssueStatus, Severity, WCAGPrinciple, PrincipleSummary
                
                all_issues = []
                for issue_data in summary.get("issues", []):
                    # PDF summary uses "wcag_criterion" as the rule ID
                    rule_id = issue_data.get("wcag_criterion", issue_data.get("rule_id"))
                    rule = engine.get_rule_by_id(rule_id)
                    if rule:
                        issue = AccessibilityIssue(
                            rule_id=rule_id,
                            rule_name=rule.name,
                            principle=WCAGPrinciple.PERCEIVABLE,  # Most PDF issues are perceivable
                            wcag_level=rule.wcag_level,
                            status=IssueStatus.FAIL if issue_data["severity"] == "error" else IssueStatus.WARNING,
                            severity=Severity.ERROR if issue_data["severity"] == "error" else Severity.WARNING,
                            message=issue_data["message"],
                            fix_suggestion=rule.automation_notes,
                            automatable_fix=issue_data.get("auto_fixable", False)
                        )
                        all_issues.append(issue)
                    else:
                        # Rule not found in engine, create issue with data from PDF analyzer
                        issue = AccessibilityIssue(
                            rule_id=rule_id,
                            rule_name=issue_data.get("wcag_name", "Unknown"),
                            principle=WCAGPrinciple.PERCEIVABLE,
                            wcag_level=issue_data.get("wcag_level", "A"),
                            status=IssueStatus.FAIL if issue_data["severity"] == "error" else IssueStatus.WARNING,
                            severity=Severity.ERROR if issue_data["severity"] == "error" else Severity.WARNING,
                            message=issue_data["message"],
                            fix_suggestion=issue_data.get("fix_suggestion", ""),
                            automatable_fix=issue_data.get("auto_fixable", False)
                        )
                        all_issues.append(issue)
                
                # Debug: Log auto-fixable issues
                auto_fixable_count = len([i for i in all_issues if i.automatable_fix])
                logger.info(f"PDF Analysis: {len(all_issues)} issues, {auto_fixable_count} auto-fixable")
                for issue in all_issues:
                    logger.info(f"  Issue {issue.rule_id}: automatable_fix={issue.automatable_fix}")
                
                report = AccessibilityReport(
                    document=doc_info,
                    target_level=request.target_level,
                    total_issues=len(all_issues),
                    total_errors=len([i for i in all_issues if i.severity == Severity.ERROR]),
                    total_warnings=len([i for i in all_issues if i.severity == Severity.WARNING]),
                    all_issues=all_issues,
                    principle_summaries=[],
                    issues_by_principle={"Perceivable": all_issues}
                )
                
            finally:
                parser.close()
        else:
            raise HTTPException(status_code=400, detail="Unsupported file type")
    
    elif request.url:
        # Analyze URL using Playwright
        try:
            from .playwright_analyzer import get_playwright_analyzer
            import asyncio
            
            analyzer = await get_playwright_analyzer()
            results = await analyzer.analyze_url(request.url)
            
            doc_info = DocumentInfo(
                filename=request.url,
                file_type="url",
                url=request.url
            )
            
            # Analyze the fetched HTML
            report = engine.analyze_html(
                results["html_content"],
                doc_info,
                target_level=request.target_level,
                include_aaa=request.include_aaa
            )
            
            # Add Playwright-detected issues
            for issue in results.get("contrast_issues", []):
                report.all_issues.append(issue)
                report.issues_by_principle.setdefault("Perceivable", []).append(issue)
            
            for issue in results.get("target_size_issues", []):
                report.all_issues.append(issue)
                report.issues_by_principle.setdefault("Operable", []).append(issue)
            
            # Recalculate totals
            report.total_issues = len(report.all_issues)
            report.total_errors = len([i for i in report.all_issues if i.severity == Severity.ERROR])
            report.total_warnings = len([i for i in report.all_issues if i.severity == Severity.WARNING])
            
        except ImportError:
            raise HTTPException(
                status_code=500,
                detail="Playwright not available for URL analysis"
            )
    
    # Store report
    report_storage[report.id] = report
    
    logger.info(f"Analysis complete: {report.total_issues} issues found")
    
    return report


@app.get("/analyze/url")
async def analyze_url_get(
    url: str = Query(..., description="URL to analyze"),
    target_level: WCAGLevel = Query(WCAGLevel.AA, description="Target WCAG level"),
    include_aaa: bool = Query(False, description="Include AAA checks")
):
    """
    Analyze a URL for accessibility issues (GET version).
    
    Convenience endpoint for quick URL analysis.
    """
    request = AnalyzeRequest(url=url, target_level=target_level, include_aaa=include_aaa)
    return await analyze_document(request)


# =============================================================================
# Remediate Endpoint
# =============================================================================

@app.post("/remediate", response_model=RemediationResponse)
async def remediate_document(request: RemediationRequest):
    """
    Apply automated fixes for accessibility issues.
    
    Processes the report and applies fixes where possible:
    - Missing alt attributes (WCAG 1.1.1)
    - Missing form labels (WCAG 1.3.1, 3.3.2)  
    - Missing language attributes (WCAG 3.1.1)
    - Missing page titles (WCAG 2.4.2)
    
    Returns the remediated document and summary of changes.
    """
    if request.report_id not in report_storage:
        raise HTTPException(status_code=404, detail="Report not found")
    
    report = report_storage[request.report_id]
    
    # Find the original file
    file_id = None
    for fid, finfo in file_storage.items():
        if finfo["original_filename"] == report.document.filename:
            file_id = fid
            break
    
    if not file_id:
        raise HTTPException(status_code=404, detail="Original file not found")
    
    file_info = file_storage[file_id]
    file_path = Path(file_info["file_path"])
    
    results: list[RemediationResult] = []
    remediated_path: Optional[str] = None
    remediation_report_path: Optional[str] = None
    remediation_report_filename: Optional[str] = None
    
    if file_info["file_type"] == "html":
        # Remediate HTML
        async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
            html_content = await f.read()
        
        remediator = HTMLRemediator(html_content)
        
        # Get issues to fix
        issues_to_fix = []
        if request.apply_all_automatable:
            issues_to_fix = [i for i in report.all_issues if i.automatable_fix]
        elif request.issue_ids:
            issues_to_fix = [i for i in report.all_issues if i.id in request.issue_ids]
        
        # Apply fixes
        results = remediator.apply_fixes(issues_to_fix)
        
        # Save remediated file
        output_filename = f"remediated_{file_info['original_filename']}"
        output_path = settings.OUTPUT_DIR / output_filename
        
        async with aiofiles.open(output_path, 'w', encoding='utf-8') as f:
            await f.write(remediator.get_remediated_html())
        
        remediated_path = str(output_path)
        
    elif file_info["file_type"] == "pdf":
        import shutil

        output_filename = f"remediated_{file_info['original_filename']}"
        output_path = settings.OUTPUT_DIR / output_filename
        shutil.copy2(file_path, output_path)

        remediator = PDFRemediator(output_path)
        results = remediator.fix_all(
            output_path=output_path,
            report=report,
            original_filename=file_info["original_filename"],
            overwrite_tags=request.overwrite_tags,
        )

        remediated_path = str(output_path)
    
    # Count results
    total_fixed = len([r for r in results if r.success])
    total_failed = len([r for r in results if not r.success])
    
    logger.info(f"Remediation complete: {total_fixed} fixed, {total_failed} failed")

    # Always generate remediation report
    try:
        from .remediation_report import generate_remediation_report_for_api

        report_path = generate_remediation_report_for_api(
            original_filename=file_info["original_filename"],
            file_id=file_id,
            report_id=request.report_id,
            file_type=file_info["file_type"],
            analysis_report=report.model_dump(),
            remediation_results=[r.model_dump() for r in results],
            remediated_file_path=remediated_path,
            output_dir=settings.OUTPUT_DIR,
        )
        remediation_report_path = str(report_path)
        remediation_report_filename = report_path.name
    except Exception as e:
        logger.warning(f"Failed to generate remediation report: {e}")
    
    return RemediationResponse(
        report_id=request.report_id,
        total_fixed=total_fixed,
        total_failed=total_failed,
        results=results,
        remediated_file_path=remediated_path,
        remediation_report_path=remediation_report_path,
        remediation_report_filename=remediation_report_filename,
    )


@app.get("/remediate/download/{report_id}")
async def download_remediated_file(report_id: str):
    """
    Download the remediated file.
    """
    if report_id not in report_storage:
        raise HTTPException(status_code=404, detail="Report not found")
    
    report = report_storage[report_id]
    
    # Find remediated file
    output_filename = f"remediated_{report.document.filename}"
    output_path = settings.OUTPUT_DIR / output_filename
    
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Remediated file not found")
    
    return FileResponse(
        path=output_path,
        filename=output_filename,
        media_type="application/octet-stream"
    )


# =============================================================================
# PDF-Specific Endpoints
# =============================================================================

@app.post("/pdf/analyze")
async def analyze_pdf_document(file_id: str):
    """
    Detailed PDF accessibility analysis.
    
    Returns comprehensive PDF/UA compliance report including:
    - Document metadata
    - Structure analysis
    - WCAG compliance status
    - Specific issues with fix suggestions
    """
    if file_id not in file_storage:
        raise HTTPException(status_code=404, detail="File not found")
    
    file_info = file_storage[file_id]
    
    if file_info["file_type"] != "pdf":
        raise HTTPException(status_code=400, detail="File is not a PDF")
    
    file_path = Path(file_info["file_path"])
    
    try:
        from .pdf_accessibility import PDFAccessibilityAnalyzer
        
        analyzer = PDFAccessibilityAnalyzer(file_path=file_path)
        report = analyzer.analyze()
        analyzer.close()
        
        return report
        
    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"PDF analysis libraries not installed: {e}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/pdf/remediate")
async def remediate_pdf_document(
    file_id: str,
    title: Optional[str] = None,
    language: Optional[str] = "en",
    add_bookmarks: bool = False,
    auto_tag: bool = False,
    generate_report: bool = True
):
    """
    Apply automated fixes to a PDF document.
    
    Fixes that can be applied:
    - Set document title (WCAG 2.4.2)
    - Set document language (WCAG 3.1.1)
    - Generate bookmarks from headings (WCAG 2.4.5)
    - Auto-tag untagged PDFs using OpenDataLoader layout extraction (WCAG 1.3.1)
    
    Parameters:
    - file_id: The uploaded file ID
    - title: Document title to set
    - language: Document language (default: "en")
    - add_bookmarks: Generate bookmarks from headings
    - auto_tag: Use OpenDataLoader layout extraction to auto-tag untagged PDFs
    - generate_report: Generate a PDF report of changes (default: True)
    """
    if file_id not in file_storage:
        raise HTTPException(status_code=404, detail="File not found")
    
    file_info = file_storage[file_id]
    
    if file_info["file_type"] != "pdf":
        raise HTTPException(status_code=400, detail="File is not a PDF")
    
    file_path = Path(file_info["file_path"])
    
    try:
        from .pdf_accessibility import PDFRemediator, PDFAccessibilityAnalyzer
        
        # First, analyze the document to get current state
        analyzer = PDFAccessibilityAnalyzer(file_path=file_path)
        analysis_before = analyzer.analyze()
        analyzer.close()
        
        # Apply remediations
        remediator = PDFRemediator(file_path)
        results = {
            "file_id": file_id,
            "original_filename": file_info["original_filename"],
            "changes": []
        }
        
        # Apply metadata fixes
        if title or language:
            metadata_result = remediator.fix_metadata(title=title, language=language)
            results["metadata"] = metadata_result
            if metadata_result.get("success"):
                for change in metadata_result.get("changes", []):
                    change["value"] = change.get("title") or change.get("lang") or change.get("value")
                results["changes"].extend(metadata_result.get("changes", []))
        
        # Generate bookmarks
        if add_bookmarks:
            bookmark_result = remediator.generate_bookmarks_from_headings()
            results["bookmarks"] = bookmark_result
            if bookmark_result.get("success"):
                results["changes"].append({
                    "type": "add_bookmarks",
                    "value": f"{bookmark_result.get('bookmarks_added', 0)} bookmarks",
                    "count": bookmark_result.get("bookmarks_added", 0)
                })
        
        # Auto-tag using OpenDataLoader layout extraction
        if auto_tag:
            logger.info("Running PDF structure tagging on PDF...")
            tag_result = remediator.auto_tag_document()
            results["auto_tag"] = tag_result
            if tag_result.get("success"):
                results["changes"].append({
                    "type": "auto_tag",
                    "value": f"{tag_result['tags_created']} structure tags",
                    "tags_created": tag_result["tags_created"],
                    "tag_counts": tag_result.get("tag_counts", {}),
                })
                logger.info(f"Auto-tagging: {tag_result['tags_created']} tags created")
        
        results["total_changes"] = len(results["changes"])
        results["success"] = results["total_changes"] > 0
        
        # Generate remediation report
        if generate_report and results["success"]:
            try:
                from .remediation_report import generate_remediation_report
                
                report_path = generate_remediation_report(
                    original_filename=file_info["original_filename"],
                    file_id=file_id,
                    analysis_result=analysis_before,
                    remediation_result=results,
                    output_dir=settings.OUTPUT_DIR
                )
                
                results["report_path"] = str(report_path)
                results["report_filename"] = report_path.name
                logger.info(f"Generated remediation report: {report_path}")
                
            except Exception as e:
                logger.error(f"Failed to generate report: {e}")
                results["report_error"] = str(e)
        
        return results
        
    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"PDF remediation libraries not installed: {e}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/pdf/report/{filename}")
async def download_remediation_report(filename: str):
    """
    Download a remediation report.
    """
    report_path = settings.OUTPUT_DIR / filename
    
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    
    media_type = "application/pdf" if filename.endswith(".pdf") else "application/json"
    
    return FileResponse(
        path=report_path,
        filename=filename,
        media_type=media_type
    )


@app.get("/pdf/download/{file_id}")
async def download_pdf(file_id: str):
    """
    Download the (remediated) PDF file.
    """
    if file_id not in file_storage:
        raise HTTPException(status_code=404, detail="File not found")
    
    file_info = file_storage[file_id]
    file_path = Path(file_info["file_path"])
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    
    return FileResponse(
        path=file_path,
        filename=file_info["original_filename"],
        media_type="application/pdf"
    )


# =============================================================================
# Debug: Layout Overlay Endpoint
# =============================================================================

from pydantic import BaseModel as _BaseModel

class _OverlayRequest(_BaseModel):
    report_id: str

@app.post("/pdf/debug/overlays")
async def generate_layout_overlays(request: _OverlayRequest):
    """
    Generate block-level overlay images showing the extracted PDF structure.

    Runs OpenDataLoader on the original uploaded PDF and produces a ZIP of
    annotated page PNGs (tag + short text per block).
    """
    if request.report_id not in report_storage:
        raise HTTPException(status_code=404, detail="Report not found")

    report = report_storage[request.report_id]

    # Resolve report -> original file (same pattern as /remediate)
    file_id = None
    for fid, finfo in file_storage.items():
        if finfo["original_filename"] == report.document.filename:
            file_id = fid
            break

    if not file_id:
        raise HTTPException(status_code=404, detail="Original file not found")

    file_info = file_storage[file_id]
    if file_info["file_type"] != "pdf":
        raise HTTPException(status_code=400, detail="Overlays are only available for PDFs")

    file_path = Path(file_info["file_path"])

    try:
        from .layout_model import DocumentLayoutAnalyzer
        from .pdf_overlay_debug import generate_block_overlays_zip

        analyzer = DocumentLayoutAnalyzer()
        layouts = analyzer.analyze_document(file_path)

        zip_path = generate_block_overlays_zip(file_path, layouts, settings.OUTPUT_DIR)

        return FileResponse(
            path=str(zip_path),
            filename=zip_path.name,
            media_type="application/zip",
        )

    except Exception as e:
        logger.error(f"Overlay generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Overlay generation failed: {str(e)}")


# =============================================================================
# Rules Endpoints
# =============================================================================

@app.get("/rules")
async def list_rules(
    level: Optional[WCAGLevel] = Query(None, description="Filter by WCAG level"),
    principle: Optional[str] = Query(None, description="Filter by principle"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    automatable: Optional[bool] = Query(None, description="Filter by automatable")
):
    """
    List all WCAG rules in the engine.
    
    Provides filtering options to find specific rules.
    """
    engine = get_rules_engine()
    rules = engine.get_all_rules()
    
    # Apply filters
    if level:
        rules = [r for r in rules if r.wcag_level == level]
    
    if tag:
        rules = [r for r in rules if tag in r.tags]
    
    if automatable is not None:
        rules = [r for r in rules if r.automatable == automatable]
    
    return {
        "total": len(rules),
        "rules": [
            {
                "id": r.id,
                "name": r.name,
                "wcag_level": r.wcag_level,
                "description": r.description,
                "automatable": r.automatable,
                "tags": r.tags
            }
            for r in rules
        ]
    }


@app.get("/rules/{rule_id}")
async def get_rule(rule_id: str):
    """
    Get detailed information about a specific WCAG rule.
    """
    engine = get_rules_engine()
    rule = engine.get_rule_by_id(rule_id)
    
    if not rule:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")
    
    return rule


# =============================================================================
# Report Endpoints
# =============================================================================

@app.get("/report/{report_id}")
async def get_report(report_id: str):
    """
    Retrieve a previously generated accessibility report.
    """
    if report_id not in report_storage:
        raise HTTPException(status_code=404, detail="Report not found")
    
    return report_storage[report_id]


@app.get("/report/{report_id}/summary")
async def get_report_summary(report_id: str):
    """
    Get a summary of an accessibility report.
    """
    if report_id not in report_storage:
        raise HTTPException(status_code=404, detail="Report not found")
    
    report = report_storage[report_id]
    
    return {
        "report_id": report.id,
        "document": report.document.filename,
        "target_level": report.target_level,
        "total_issues": report.total_issues,
        "total_errors": report.total_errors,
        "total_warnings": report.total_warnings,
        "total_manual_review": report.total_manual_review,
        "by_principle": {
            p.principle.value: {
                "total": p.total_issues,
                "errors": p.errors,
                "warnings": p.warnings
            }
            for p in report.principle_summaries
        },
        "created_at": report.created_at.isoformat(),
        "processing_time_ms": report.processing_time_ms
    }


@app.get("/report/{report_id}/export")
async def export_report(
    report_id: str,
    format: str = Query("json", description="Export format: json, csv, html")
):
    """
    Export an accessibility report in various formats.
    """
    if report_id not in report_storage:
        raise HTTPException(status_code=404, detail="Report not found")
    
    report = report_storage[report_id]
    
    if format == "json":
        return report
    
    elif format == "csv":
        # Generate CSV
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Rule ID", "Rule Name", "Principle", "Level", "Status",
            "Severity", "Message", "Fix Suggestion", "Location"
        ])
        
        for issue in report.all_issues:
            writer.writerow([
                issue.rule_id,
                issue.rule_name,
                issue.principle.value,
                issue.wcag_level.value,
                issue.status.value,
                issue.severity.value,
                issue.message,
                issue.fix_suggestion,
                issue.element_location.selector if issue.element_location else ""
            ])
        
        return JSONResponse(
            content={"csv": output.getvalue()},
            headers={"Content-Disposition": f"attachment; filename=report_{report_id}.csv"}
        )
    
    elif format == "html":
        # Generate HTML report
        html = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Accessibility Report - {report.document.filename}</title>
            <style>
                body {{ font-family: system-ui, sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; }}
                h1 {{ color: #1a1a1a; }}
                .summary {{ background: #f5f5f5; padding: 20px; border-radius: 8px; margin: 20px 0; }}
                .issue {{ border: 1px solid #ddd; padding: 15px; margin: 10px 0; border-radius: 4px; }}
                .error {{ border-left: 4px solid #dc3545; }}
                .warning {{ border-left: 4px solid #ffc107; }}
                .info {{ border-left: 4px solid #17a2b8; }}
                .tag {{ display: inline-block; background: #e9ecef; padding: 2px 8px; border-radius: 4px; font-size: 12px; margin: 2px; }}
            </style>
        </head>
        <body>
            <h1>Accessibility Report</h1>
            <div class="summary">
                <p><strong>Document:</strong> {report.document.filename}</p>
                <p><strong>Target Level:</strong> WCAG 2.2 {report.target_level.value}</p>
                <p><strong>Total Issues:</strong> {report.total_issues}</p>
                <p><strong>Errors:</strong> {report.total_errors} | <strong>Warnings:</strong> {report.total_warnings}</p>
            </div>
            <h2>Issues</h2>
        """
        
        for issue in report.all_issues:
            html += f"""
            <div class="issue {issue.severity.value}">
                <h3>{issue.rule_id} - {issue.rule_name}</h3>
                <p><span class="tag">{issue.principle.value}</span> <span class="tag">Level {issue.wcag_level.value}</span></p>
                <p><strong>Issue:</strong> {issue.message}</p>
                <p><strong>Fix:</strong> {issue.fix_suggestion}</p>
            </div>
            """
        
        html += "</body></html>"
        
        return JSONResponse(
            content={"html": html},
            headers={"Content-Disposition": f"attachment; filename=report_{report_id}.html"}
        )
    
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
