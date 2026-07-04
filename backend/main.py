"""
WCAG 2.2 Accessibility Remediation Platform - FastAPI Backend

Main application entry point providing endpoints for:
- /upload - Upload HTML/PDF files for analysis
- /analyze - Run accessibility analysis and return JSON report
- /remediate - Apply automated fixes for accessibility issues

All endpoints reference WCAG 2.2 success criteria as the source of truth.
"""
import uuid
import asyncio
import aiofiles
from glob import escape as glob_escape
from pathlib import Path
from typing import Optional
from datetime import datetime
from contextlib import asynccontextmanager
import logging
import json

from fastapi import FastAPI, File, UploadFile, HTTPException, Query, BackgroundTasks, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .config import settings
from .models import (
    AccessibilityReport, DocumentInfo, WCAGLevel,
    UploadResponse, AnalyzeRequest, RemediationRequest, RemediationResponse,
    RemediationResult, DocumentImageItem, AltTextResolutionRequest, AltTextGenerateRequest,
    AltTextGenerateResponse
)
from . import alt_text_context as alt_text_context_service
from .deepseek_alt_text import call_deepseek_contextual_alt_text
from .rules_engine import get_rules_engine
from .parsers import HTMLParser, PDFParser
from .remediator import HTMLRemediator, PDFRemediator

# Database & Authentication Imports
from .database import init_db, SessionLocal, UploadedFile, AccessibilityReport as DbReport
from .retention_runner import clean_expired_documents
from .auth import router as auth_router, require_user, User

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =============================================================================
# Database-Backed Storage Adapters
# =============================================================================

class DbFileStorage:
    """Simulates a dictionary interface on top of SQLite for UploadedFile metadata."""
    
    def __contains__(self, file_id: str) -> bool:
        db = SessionLocal()
        try:
            return db.query(UploadedFile).filter(UploadedFile.id == file_id).first() is not None
        finally:
            db.close()
            
    def __getitem__(self, file_id: str) -> dict:
        db = SessionLocal()
        try:
            file_rec = db.query(UploadedFile).filter(UploadedFile.id == file_id).first()
            if not file_rec:
                raise KeyError(file_id)
            return {
                "id": file_rec.id,
                "original_filename": file_rec.filename,
                "file_type": file_rec.file_type,
                "file_path": file_rec.file_path,
                "file_size": file_rec.file_size,
                "uploaded_at": file_rec.uploaded_at.isoformat()
            }
        finally:
            db.close()
            
    def __setitem__(self, file_id: str, value: dict):
        db = SessionLocal()
        try:
            file_rec = db.query(UploadedFile).filter(UploadedFile.id == file_id).first()
            uploaded_at_val = value["uploaded_at"]
            if isinstance(uploaded_at_val, str):
                uploaded_at_val = datetime.fromisoformat(uploaded_at_val)
                
            if not file_rec:
                file_rec = UploadedFile(
                    id=file_id,
                    filename=value["original_filename"],
                    file_type=value["file_type"],
                    file_path=value["file_path"],
                    file_size=value["file_size"],
                    uploaded_at=uploaded_at_val,
                    owner_id=value.get("owner_id")
                )
                db.add(file_rec)
            else:
                file_rec.filename = value["original_filename"]
                file_rec.file_type = value["file_type"]
                file_rec.file_path = value["file_path"]
                file_rec.file_size = value["file_size"]
                if value.get("owner_id"):
                    file_rec.owner_id = value["owner_id"]
            db.commit()
        finally:
            db.close()
            
    def items(self) -> list:
        db = SessionLocal()
        try:
            files = db.query(UploadedFile).all()
            return [
                (f.id, {
                    "id": f.id,
                    "original_filename": f.filename,
                    "file_type": f.file_type,
                    "file_path": f.file_path,
                    "file_size": f.file_size,
                    "uploaded_at": f.uploaded_at.isoformat()
                })
                for f in files
            ]
        finally:
            db.close()
            
    def get(self, file_id: str, default=None) -> Optional[dict]:
        try:
            return self[file_id]
        except KeyError:
            return default


class DbReportStorage:
    """Simulates a dictionary interface on top of SQLite for AccessibilityReport models."""
    
    def __contains__(self, report_id: str) -> bool:
        db = SessionLocal()
        try:
            return db.query(DbReport).filter(DbReport.id == report_id).first() is not None
        finally:
            db.close()
            
    def __getitem__(self, report_id: str) -> AccessibilityReport:
        db = SessionLocal()
        try:
            report_rec = db.query(DbReport).filter(DbReport.id == report_id).first()
            if not report_rec:
                raise KeyError(report_id)
            return AccessibilityReport.model_validate_json(report_rec.report_json)
        finally:
            db.close()
            
    def __setitem__(self, report_id: str, report_model: AccessibilityReport):
        db = SessionLocal()
        try:
            report_rec = db.query(DbReport).filter(DbReport.id == report_id).first()
            report_json_str = report_model.model_dump_json()
            
            # Find file_id if it matches the filename
            file_rec = db.query(UploadedFile).filter(UploadedFile.filename == report_model.document.filename).first()
            file_id = file_rec.id if file_rec else None
            
            if not report_rec:
                report_rec = DbReport(
                    id=report_id,
                    file_id=file_id,
                    report_json=report_json_str
                )
                db.add(report_rec)
            else:
                report_rec.file_id = file_id
                report_rec.report_json = report_json_str
            db.commit()
        finally:
            db.close()

    def get(self, report_id: str, default=None) -> Optional[AccessibilityReport]:
        try:
            return self[report_id]
        except KeyError:
            return default


# Storage instances
file_storage = DbFileStorage()
report_storage = DbReportStorage()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown."""
    # Startup
    logger.info("Starting WCAG Accessibility Remediation Platform")
    logger.info(f"Loaded {len(get_rules_engine().get_all_rules())} WCAG rules")
    
    # Initialize SQLite database schema
    init_db()
    logger.info("Database schema initialized.")
    
    # Start retention runner background worker
    app.state.retention_task = asyncio.create_task(clean_expired_documents())
    logger.info("Background retention runner task started.")
    
    yield
    
    # Shutdown
    logger.info("Stopping background retention runner...")
    app.state.retention_task.cancel()
    try:
        await app.state.retention_task
    except asyncio.CancelledError:
        pass
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

@app.middleware("http")
async def api_prefix_middleware(request: Request, call_next):
    """
    Middleware that dynamically strips /api from the beginning of paths
    so the router can match endpoints successfully regardless of whether
    the request goes through a proxy/CDN that includes the prefix.
    """
    path = request.scope.get("path", "")
    if path.startswith("/api"):
        request.scope["path"] = path[4:] or "/"
    response = await call_next(request)
    return response

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register Authentication endpoints
app.include_router(auth_router)


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
async def upload_file(file: UploadFile = File(...), user: User = Depends(require_user)):
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
        "uploaded_at": datetime.now().isoformat(),
        "owner_id": user.id
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
async def analyze_document(request: AnalyzeRequest, user: User = Depends(require_user)):
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
        
    if request.file_id:
        db_conn = SessionLocal()
        try:
            file_rec = db_conn.query(UploadedFile).filter(UploadedFile.id == request.file_id).first()
            if file_rec and file_rec.owner_id and file_rec.owner_id != user.id:
                raise HTTPException(status_code=403, detail="Access denied to this file.")
        finally:
            db_conn.close()
    
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
            
            # Run static analysis first. BeautifulSoup parsing + selector checks
            # are CPU-bound and synchronous, so run them in a worker thread to
            # avoid blocking the asyncio event loop (and every other request).
            report = await run_in_threadpool(
                engine.analyze_html,
                html_content,
                doc_info,
                target_level=request.target_level,
                include_aaa=request.include_aaa,
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
            # Parse and analyze PDF using the comprehensive PDFAccessibilityAnalyzer
            from .pdf_accessibility import PDFAccessibilityAnalyzer
            analyzer = PDFAccessibilityAnalyzer(file_path=file_path)
            
            try:
                # PDF analysis (PyMuPDF + pikepdf, structure-tree walks, per-page
                # text/font extraction) is fully synchronous and can take many
                # seconds. Run it off the event loop so a single in-flight
                # analysis cannot freeze the whole server ("loads forever").
                summary = await run_in_threadpool(analyzer.analyze)
                
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
                analyzer.close()
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
            
            # Analyze the fetched HTML (CPU-bound; keep it off the event loop)
            report = await run_in_threadpool(
                engine.analyze_html,
                results["html_content"],
                doc_info,
                target_level=request.target_level,
                include_aaa=request.include_aaa,
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
    include_aaa: bool = Query(False, description="Include AAA checks"),
    user: User = Depends(require_user)
):
    """
    Analyze a URL for accessibility issues (GET version).
    
    Convenience endpoint for quick URL analysis.
    """
    request = AnalyzeRequest(url=url, target_level=target_level, include_aaa=include_aaa)
    return await analyze_document(request, user)


# =============================================================================
# Remediate Endpoint
# =============================================================================

@app.post("/remediate", response_model=RemediationResponse)
async def remediate_document(request: RemediationRequest, user: User = Depends(require_user)):
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
        
    db_conn = SessionLocal()
    try:
        report_rec = db_conn.query(DbReport).filter(DbReport.id == request.report_id).first()
        if report_rec:
            file_rec = db_conn.query(UploadedFile).filter(UploadedFile.id == report_rec.file_id).first()
            if file_rec and file_rec.owner_id and file_rec.owner_id != user.id:
                raise HTTPException(status_code=403, detail="Access denied to this report.")
    finally:
        db_conn.close()
    
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
        # The PDF pipeline shells out to Java (OpenDataLoader), the C++ tagging
        # engine, and Tesseract OCR — all blocking and potentially slow. Run it
        # in a worker thread so it can't stall the event loop / other requests.
        results = await run_in_threadpool(
            remediator.fix_all,
            output_path=output_path,
            report=report,
            original_filename=file_info["original_filename"],
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
async def download_remediated_file(report_id: str, user: User = Depends(require_user)):
    """
    Download the remediated file.
    """
    if report_id not in report_storage:
        raise HTTPException(status_code=404, detail="Report not found")
        
    db_conn = SessionLocal()
    try:
        report_rec = db_conn.query(DbReport).filter(DbReport.id == report_id).first()
        if report_rec:
            file_rec = db_conn.query(UploadedFile).filter(UploadedFile.id == report_rec.file_id).first()
            if file_rec and file_rec.owner_id and file_rec.owner_id != user.id:
                raise HTTPException(status_code=403, detail="Access denied to this report.")
    finally:
        db_conn.close()
    
    report = report_storage[report_id]
    
    # Find remediated file
    output_filename = f"remediated_{report.document.filename}"
    output_path = settings.OUTPUT_DIR / output_filename
    
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Remediated file not found")
    
    media_type = "application/pdf" if output_filename.lower().endswith(".pdf") else "application/octet-stream"
    return FileResponse(
        path=output_path,
        filename=output_filename,
        media_type=media_type,
    )


def _latest_remediation_report_path(report_id: str) -> Optional[Path]:
    output_dir = settings.OUTPUT_DIR.resolve()
    pattern = f"Remediation_Report_{glob_escape(report_id)}_*.pdf"
    candidates = (
        path
        for path in output_dir.glob(pattern)
        if path.is_file() and path.resolve().parent == output_dir
    )
    return max(candidates, key=lambda path: path.stat().st_mtime, default=None)


@app.get("/remediate/report/{report_id}")
async def download_remediation_report_by_id(
    report_id: str,
    user: User = Depends(require_user),
):
    db_conn = SessionLocal()
    try:
        report_rec = db_conn.query(DbReport).filter(DbReport.id == report_id).first()
        if not report_rec:
            raise HTTPException(status_code=404, detail="Report not found")

        file_rec = db_conn.query(UploadedFile).filter(UploadedFile.id == report_rec.file_id).first()
        if not file_rec:
            raise HTTPException(status_code=404, detail="Associated file not found")
        if file_rec.owner_id != user.id:
            raise HTTPException(status_code=403, detail="Access denied to this report.")
    finally:
        db_conn.close()

    report_path = _latest_remediation_report_path(report_id)
    if report_path is None:
        raise HTTPException(status_code=404, detail="Remediation report not found")

    return FileResponse(
        path=report_path,
        filename=report_path.name,
        media_type="application/pdf",
    )


# =============================================================================
# PDF-Specific Endpoints
# =============================================================================

@app.post("/pdf/analyze")
async def analyze_pdf_document(file_id: str, user: User = Depends(require_user)):
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
        
    db_conn = SessionLocal()
    try:
        file_rec = db_conn.query(UploadedFile).filter(UploadedFile.id == file_id).first()
        if file_rec and file_rec.owner_id and file_rec.owner_id != user.id:
            raise HTTPException(status_code=403, detail="Access denied to this file.")
    finally:
        db_conn.close()
    
    file_info = file_storage[file_id]
    
    if file_info["file_type"] != "pdf":
        raise HTTPException(status_code=400, detail="File is not a PDF")
    
    file_path = Path(file_info["file_path"])
    
    try:
        from .pdf_accessibility import PDFAccessibilityAnalyzer
        
        analyzer = PDFAccessibilityAnalyzer(file_path=file_path)
        report = await run_in_threadpool(analyzer.analyze)
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
    generate_report: bool = True,
    user: User = Depends(require_user)
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
        
    db_conn = SessionLocal()
    try:
        file_rec = db_conn.query(UploadedFile).filter(UploadedFile.id == file_id).first()
        if file_rec and file_rec.owner_id and file_rec.owner_id != user.id:
            raise HTTPException(status_code=403, detail="Access denied to this file.")
    finally:
        db_conn.close()
    
    file_info = file_storage[file_id]
    
    if file_info["file_type"] != "pdf":
        raise HTTPException(status_code=400, detail="File is not a PDF")
    
    file_path = Path(file_info["file_path"])
    
    try:
        from .pdf_accessibility import PDFRemediator, PDFAccessibilityAnalyzer
        
        # First, analyze the document to get current state
        analyzer = PDFAccessibilityAnalyzer(file_path=file_path)
        analysis_before = await run_in_threadpool(analyzer.analyze)
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
            metadata_result = await run_in_threadpool(
                remediator.fix_metadata, title=title, language=language
            )
            results["metadata"] = metadata_result
            if metadata_result.get("success"):
                for change in metadata_result.get("changes", []):
                    change["value"] = change.get("title") or change.get("lang") or change.get("value")
                results["changes"].extend(metadata_result.get("changes", []))
        
        # Generate bookmarks
        if add_bookmarks:
            bookmark_result = await run_in_threadpool(
                remediator.generate_bookmarks_from_headings
            )
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
            tag_result = await run_in_threadpool(remediator.auto_tag_document)
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
async def download_remediation_report(filename: str, user: User = Depends(require_user)):
    """
    Download a remediation report.
    """
    db_conn = SessionLocal()
    try:
        user_files = db_conn.query(UploadedFile).filter(UploadedFile.owner_id == user.id).all()
        user_file_ids = [f.id for f in user_files]
        reports = db_conn.query(DbReport).filter(DbReport.file_id.in_(user_file_ids)).all()
        
        has_permission = False
        for r in reports:
            if filename in r.report_json:
                has_permission = True
                break
        
        if not has_permission:
            raise HTTPException(status_code=403, detail="Access denied to this report.")
    finally:
        db_conn.close()

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
async def download_pdf(file_id: str, user: User = Depends(require_user)):
    """
    Download the (remediated) PDF file.
    """
    if file_id not in file_storage:
        raise HTTPException(status_code=404, detail="File not found")
        
    db_conn = SessionLocal()
    try:
        file_rec = db_conn.query(UploadedFile).filter(UploadedFile.id == file_id).first()
        if file_rec and file_rec.owner_id and file_rec.owner_id != user.id:
            raise HTTPException(status_code=403, detail="Access denied to this file.")
    finally:
        db_conn.close()
    
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


class _CompareTaggingRequest(_BaseModel):
    report_id: str
    include_overlays: bool = False
    confidence_threshold: float = 0.0


def _resolve_pdf_path_from_report(report_id: str) -> Path:
    if report_id not in report_storage:
        raise HTTPException(status_code=404, detail="Report not found")

    report = report_storage[report_id]
    file_id = None
    for fid, finfo in file_storage.items():
        if finfo["original_filename"] == report.document.filename:
            file_id = fid
            break

    if not file_id:
        raise HTTPException(status_code=404, detail="Original file not found")

    file_info = file_storage[file_id]
    if file_info["file_type"] != "pdf":
        raise HTTPException(status_code=400, detail="Only PDF documents are supported")

    return Path(file_info["file_path"])


@app.post("/pdf/debug/compare-tagging")
async def compare_tagging_pipelines(request: _CompareTaggingRequest):
    """
    Run LayoutLM and OpenDataLoader on the same PDF and return a comparison report.
    """
    file_path = _resolve_pdf_path_from_report(request.report_id)

    try:
        from .tagging_compare import (
            build_comparison_bundle,
            run_tagging_comparison,
            save_comparison_report,
        )

        report = run_tagging_comparison(
            file_path,
            confidence_threshold=request.confidence_threshold,
        )
        json_path = save_comparison_report(report, settings.OUTPUT_DIR)

        if request.include_overlays:
            zip_path = build_comparison_bundle(file_path, report, settings.OUTPUT_DIR)
            return FileResponse(
                path=str(zip_path),
                filename=zip_path.name,
                media_type="application/zip",
            )

        payload = {k: v for k, v in report.items() if not k.startswith("_")}
        payload["report_path"] = str(json_path)
        payload["report_filename"] = json_path.name
        return payload

    except Exception as e:
        logger.error("Tagging comparison failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Tagging comparison failed: {str(e)}")


@app.post("/pdf/debug/overlays")
async def generate_layout_overlays(request: _OverlayRequest):
    """
    Generate block-level overlay images showing the extracted PDF structure.

    Runs LayoutLMv3 layout analysis on the original uploaded PDF and produces a ZIP of
    annotated page PNGs (tag + short text per block).
    """
    file_path = _resolve_pdf_path_from_report(request.report_id)

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


    if not rule:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")
    
    return rule


# =============================================================================
# Alt-Text Resolution System Helpers and Endpoints
# =============================================================================

from typing import List

def _resolve_document_from_report(report_id: str) -> tuple[Path, str]:
    if report_id not in report_storage:
        raise HTTPException(status_code=404, detail="Report not found")
        
    report = report_storage[report_id]
    file_id = None
    for fid, finfo in file_storage.items():
        if finfo["original_filename"] == report.document.filename:
            file_id = fid
            break
            
    if not file_id:
        raise HTTPException(status_code=404, detail="Original file not found")
        
    file_info = file_storage[file_id]
    return Path(file_info["file_path"]), file_info["file_type"]


def extract_html_images(html_path: Path) -> List[DocumentImageItem]:
    from bs4 import BeautifulSoup
    import base64
    
    with open(html_path, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f.read(), 'html5lib')
        
    figures = []
    for idx, img in enumerate(soup.find_all('img')):
        src = img.get('src', '')
        alt = img.get('alt', '')
        
        image_url = src
        if src and not src.startswith(('http://', 'https://', 'data:')):
            potential_path = html_path.parent / src
            if potential_path.exists():
                try:
                    with open(potential_path, 'rb') as img_f:
                        ext = potential_path.suffix.lower().replace('.', '')
                        if ext == 'jpg': ext = 'jpeg'
                        encoded = base64.b64encode(img_f.read()).decode('utf-8')
                        image_url = f"data:image/{ext};base64,{encoded}"
                except Exception:
                    pass
                    
        figures.append(DocumentImageItem(
            id=f"html_img_{idx}",
            page_num=None,
            current_alt=alt or "",
            image_url=image_url
        ))
    return figures


def extract_pdf_images(pdf_path: Path) -> List[DocumentImageItem]:
    import pikepdf
    import fitz
    import base64
    
    figures = []
    
    if not pdf_path.exists():
        return []
        
    doc = fitz.open(str(pdf_path))
    
    try:
        with pikepdf.open(pdf_path) as pdf:
            struct_root = pdf.Root.get("/StructTreeRoot")
            if not struct_root:
                # Fallback: if PDF is untagged, return raw images from pages
                for page_idx in range(len(doc)):
                    page = doc[page_idx]
                    img_infos = page.get_image_info(xrefs=True)
                    for img_idx, img_info in enumerate(img_infos):
                        bbox = img_info["bbox"]
                        xref = img_info["xref"]
                        
                        # Skip full-page background images
                        width_ratio = (bbox[2] - bbox[0]) / page.rect.width
                        height_ratio = (bbox[3] - bbox[1]) / page.rect.height
                        if width_ratio > 0.95 and height_ratio > 0.95:
                            continue
                        
                        try:
                            rect = fitz.Rect(bbox)
                            pix = page.get_pixmap(clip=rect, dpi=100)
                            if pix.alpha:
                                pix = fitz.Pixmap(pix, 0)
                            img_data = pix.tobytes("png")
                            base64_data = base64.b64encode(img_data).decode("utf-8")
                            image_url = f"data:image/png;base64,{base64_data}"
                        except Exception:
                            image_url = None
                            
                        figures.append(DocumentImageItem(
                            id=f"raw_page_{page_idx}_img_{img_idx}_xref_{xref}",
                            page_num=page_idx + 1,
                            current_alt="",
                            image_url=image_url
                        ))
                return figures
            
            # Walk structure tree recursively
            def walk(node, path):
                if not hasattr(node, "keys"):
                    return
                
                if "/S" in node and str(node["/S"]) == "/Figure":
                    current_alt = str(node["/Alt"]) if "/Alt" in node else ""
                    
                    page_num = 0
                    page_obj = node.get("/Pg")
                    if page_obj:
                        try:
                            page_num = pdf.pages.index(page_obj)
                        except Exception:
                            pass
                            
                    bbox = None
                    if "/A" in node:
                        attr = node["/A"]
                        if hasattr(attr, "keys") and "/BBox" in attr:
                            bbox = [float(x) for x in attr["/BBox"]]
                            
                    if not bbox and "/K" in node:
                        kids = node["/K"]
                        if not isinstance(kids, pikepdf.Array):
                            kids = [kids]
                        for kid in kids:
                            if hasattr(kid, "keys") and "/Type" in kid and str(kid["/Type"]) == "/OBJR":
                                obj = kid.get("/Obj")
                                if obj:
                                    xref = obj.objgen[0]
                                    page = doc[page_num]
                                    img_infos = page.get_image_info(xrefs=True)
                                    for img_info in img_infos:
                                        if img_info["xref"] == xref:
                                            p_bbox = img_info["bbox"]
                                            bbox = [p_bbox[0], page.rect.height - p_bbox[3], p_bbox[2], page.rect.height - p_bbox[1]]
                                            break
                    
                    # Check if the figure spans the entire page
                    is_full_page = False
                    try:
                        page = doc[page_num]
                        if bbox:
                            width_ratio = (bbox[2] - bbox[0]) / page.rect.width
                            height_ratio = (bbox[3] - bbox[1]) / page.rect.height
                            if width_ratio > 0.95 and height_ratio > 0.95:
                                is_full_page = True
                    except Exception:
                        pass
                    
                    if not is_full_page:
                        base64_data = ""
                        try:
                            page = doc[page_num]
                            if bbox:
                                x0 = max(0, min(bbox[0], page.rect.width))
                                y0 = max(0, min(page.rect.height - bbox[3], page.rect.height))
                                x1 = max(0, min(bbox[2], page.rect.width))
                                y1 = max(0, min(page.rect.height - bbox[1], page.rect.height))
                                
                                rect = fitz.Rect(x0, y0, x1, y1)
                                if rect.is_empty or rect.width < 5 or rect.height < 5:
                                    pix = page.get_pixmap(dpi=72)
                                else:
                                    pix = page.get_pixmap(clip=rect, dpi=120)
                            else:
                                img_list = page.get_images()
                                if img_list:
                                    xref = img_list[0][0]
                                    base_img = doc.extract_image(xref)
                                    base64_data = base64.b64encode(base_img["image"]).decode("utf-8")
                                else:
                                    pix = page.get_pixmap(dpi=50)
                                    
                            if not base64_data:
                                if pix.alpha:
                                    pix = fitz.Pixmap(pix, 0)
                                img_bytes = pix.tobytes("png")
                                base64_data = base64.b64encode(img_bytes).decode("utf-8")
                        except Exception as e:
                            logger.error(f"Error rendering figure crop: {e}")
                            
                        figures.append(DocumentImageItem(
                            id="-".join(map(str, path)),
                            page_num=page_num + 1,
                            current_alt=current_alt,
                            image_url=f"data:image/png;base64,{base64_data}" if base64_data else None
                        ))
                    
                if "/K" in node:
                    kids = node["/K"]
                    if not isinstance(kids, pikepdf.Array):
                        kids = [kids]
                    for idx, kid in enumerate(kids):
                        walk(kid, path + [idx])
                        
            walk(struct_root, [])
    finally:
        doc.close()
        
    return figures


async def call_deepseek_vision_or_ocr_fallback(
    image_url_or_bytes: str,
    api_key: str,
    tessdata_path: Optional[str] = None
) -> str:
    import base64
    import httpx
    
    base64_str = ""
    image_bytes = b""
    if image_url_or_bytes.startswith("data:image/"):
        header, base64_str = image_url_or_bytes.split(",", 1)
        image_bytes = base64.b64decode(base64_str)
    
    # Try vision first
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Describe this image for use as WCAG alt text. Provide a concise description (maximum 150 characters) focusing on the visual content and context. Do not include introductory text like 'This image shows' or 'An image of'."
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_url_or_bytes
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 100
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.deepseek.com/v1/chat/completions",
                json=payload,
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                alt_text = data["choices"][0]["message"]["content"].strip()
                alt_text = alt_text.strip('"' + "'")
                return alt_text
            else:
                logger.info(f"DeepSeek vision call returned status {response.status_code}: {response.text}. Trying OCR fallback.")
    except Exception as e:
        logger.info(f"DeepSeek vision call failed: {e}. Trying OCR fallback.")
        
    # Fallback: OCR + Text completion
    ocr_text = ""
    if image_bytes and tessdata_path:
        try:
            import fitz
            pix = fitz.Pixmap(image_bytes)
            if pix.alpha:
                pix = fitz.Pixmap(pix, 0)
            ocr_bytes = pix.pdfocr_tobytes(language="eng", tessdata=tessdata_path)
            with fitz.open("pdf", ocr_bytes) as ocr_doc:
                ocr_text = ocr_doc[0].get_text().strip()
            logger.info(f"OCR extracted text for alt-text: '{ocr_text}'")
        except Exception as ocr_err:
            logger.warning(f"OCR fallback extraction failed: {ocr_err}")
            
    prompt = (
        "Based on the following context, describe this image for use as WCAG alt text. "
        "Provide a concise description (maximum 150 characters) focusing on the visual content and context. "
        "Do not include introductory text like 'This image shows' or 'An image of'."
    )
    if ocr_text:
        prompt += f"\nThe image contains the following text: '{ocr_text}'."
    else:
        prompt += "\nThe image has no extractable text. Describe a generic chart/diagram/photo."
        
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_tokens": 100
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.deepseek.com/v1/chat/completions",
                json=payload,
                headers=headers
            )
            if response.status_code == 200:
                data = response.json()
                alt_text = data["choices"][0]["message"]["content"].strip()
                alt_text = alt_text.strip('"' + "'")
                return alt_text
            else:
                raise Exception(f"DeepSeek API error: {response.text}")
    except Exception as e:
        logger.error(f"DeepSeek text completion fallback failed: {e}")
        if ocr_text:
            return f"Image containing text: {ocr_text[:50]}..."
        return "Image description unavailable"


@app.get("/report/{report_id}/images", response_model=List[DocumentImageItem])
async def get_document_images(report_id: str, user: User = Depends(require_user)):
    """
    Extract all figures and images from a document associated with a report.
    """
    if report_id not in report_storage:
        raise HTTPException(status_code=404, detail="Report not found")
        
    db_conn = SessionLocal()
    try:
        report_rec = db_conn.query(DbReport).filter(DbReport.id == report_id).first()
        if report_rec:
            file_rec = db_conn.query(UploadedFile).filter(UploadedFile.id == report_rec.file_id).first()
            if file_rec and file_rec.owner_id and file_rec.owner_id != user.id:
                raise HTTPException(status_code=403, detail="Access denied to this report.")
    finally:
        db_conn.close()
        
    file_path, file_type = _resolve_document_from_report(report_id)
    
    if file_type == "html":
        return await run_in_threadpool(alt_text_context_service.extract_html_images, file_path)
    elif file_type == "pdf":
        return await run_in_threadpool(alt_text_context_service.extract_pdf_images, file_path)
    else:
        raise HTTPException(status_code=400, detail="Unsupported document type")


@app.post("/report/{report_id}/generate-alt-text", response_model=AltTextGenerateResponse)
async def generate_alt_text_endpoint(
    report_id: str,
    request: AltTextGenerateRequest,
    user: User = Depends(require_user)
):
    """
    Generate context-aware alt-text for an image using DeepSeek API with OCR fallback.
    """
    file_path, file_type = _resolve_document_from_report(report_id)
    if file_type == "html":
        images = await run_in_threadpool(alt_text_context_service.extract_html_images, file_path)
    elif file_type == "pdf":
        images = await run_in_threadpool(alt_text_context_service.extract_pdf_images, file_path)
    else:
        raise HTTPException(status_code=400, detail="Unsupported document type")
        
    target_image = None
    for img in images:
        if img.id == request.image_id:
            target_image = img
            break
            
    if not target_image or not target_image.image_url:
        raise HTTPException(status_code=404, detail="Image not found or has no content to describe")
        
    api_key = settings.DEEPSEEK_API_KEY
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="DeepSeek API key is required. Please set DEEPSEEK_API_KEY in the server environment."
        )
        
    from .pdf_remediator_fixes import _resolve_tessdata
    tessdata = _resolve_tessdata()

    context = await run_in_threadpool(
        alt_text_context_service.build_alt_text_context,
        file_path,
        file_type,
        images,
        target_image,
        request.context_mode
    )
    
    alt_text = await call_deepseek_contextual_alt_text(
        target_image.image_url,
        api_key,
        context,
        tessdata
    )
    
    return {"alt_text": alt_text, "context_used": context.context_used()}


@app.post("/report/{report_id}/resolve-alt-text", response_model=RemediationResponse)
async def resolve_alt_text_endpoint(
    report_id: str,
    request: AltTextResolutionRequest,
    user: User = Depends(require_user)
):
    """
    Apply manual or decorative alt-text resolutions to the document.
    """
    if report_id not in report_storage:
        raise HTTPException(status_code=404, detail="Report not found")
        
    db_conn = SessionLocal()
    try:
        report_rec = db_conn.query(DbReport).filter(DbReport.id == report_id).first()
        if report_rec:
            file_rec = db_conn.query(UploadedFile).filter(UploadedFile.id == report_rec.file_id).first()
            if file_rec and file_rec.owner_id and file_rec.owner_id != user.id:
                raise HTTPException(status_code=403, detail="Access denied to this report.")
    finally:
        db_conn.close()
        
    report = report_storage[report_id]
    file_path, file_type = _resolve_document_from_report(report_id)
    
    results = []
    
    if file_type == "html":
        async def fix_html():
            from bs4 import BeautifulSoup
            with open(file_path, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f.read(), 'html5lib')
                
            fixed = 0
            for res in request.resolutions:
                if not res.id.startswith("html_img_"):
                    continue
                try:
                    idx = int(res.id.split("_")[-1])
                    imgs = soup.find_all('img')
                    if idx < len(imgs):
                        img = imgs[idx]
                        if res.is_decorative:
                            img['alt'] = ""
                            img['role'] = "presentation"
                        else:
                            img['alt'] = res.alt_text
                            if 'role' in img.attrs:
                                del img['role']
                        fixed += 1
                        results.append(RemediationResult(
                            issue_id="1.1.1",
                            success=True,
                            message=f"Updated image {idx} alt text",
                            new_value=res.alt_text if not res.is_decorative else "decorative"
                        ))
                except Exception as e:
                    results.append(RemediationResult(
                        issue_id="1.1.1",
                        success=False,
                        message=f"Failed to update image {res.id}: {str(e)}"
                    ))
            if fixed > 0:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(str(soup))
            return results
            
        results = await fix_html()
        
    elif file_type == "pdf":
        from .pdf_remediator_fixes import resolve_pdf_alt_texts
        
        resolutions_dict = [r.model_dump() for r in request.resolutions]
        pdf_res = await run_in_threadpool(resolve_pdf_alt_texts, file_path, resolutions_dict)
        
        results.append(RemediationResult(
            issue_id="1.1.1",
            success=pdf_res["success"],
            message=pdf_res["message"],
            new_value=pdf_res.get("new_value", "")
        ))
        
    total_fixed = len([r for r in results if r.success])
    total_failed = len([r for r in results if not r.success])
    
    if total_fixed > 0:
        from .models import IssueStatus, Severity
        updated_issues = []
        for issue in report.all_issues:
            is_alt_issue = (issue.rule_id == "1.1.1" or "alt" in issue.rule_id.lower() or "alt" in issue.message.lower())
            if is_alt_issue:
                issue.fixed = True
                issue.status = IssueStatus.PASS
            updated_issues.append(issue)
            
        report.all_issues = updated_issues
        
        updated_by_principle = {}
        for issue in updated_issues:
            updated_by_principle.setdefault(issue.principle.value, []).append(issue)
        report.issues_by_principle = updated_by_principle
        
        remaining_errors = len([i for i in updated_issues if not i.fixed and i.severity == Severity.ERROR])
        remaining_warnings = len([i for i in updated_issues if not i.fixed and i.severity == Severity.WARNING])
        report.total_errors = remaining_errors
        report.total_warnings = remaining_warnings
        report.total_issues = remaining_errors + remaining_warnings
        report.total_passed = len([i for i in updated_issues if i.fixed or i.status == IssueStatus.PASS])
        
        report_storage[report.id] = report
        
    import shutil
    output_filename = f"remediated_{report.document.filename}"
    output_path = settings.OUTPUT_DIR / output_filename
    shutil.copy2(file_path, output_path)
    
    return RemediationResponse(
        report_id=report.id,
        total_fixed=total_fixed,
        total_failed=total_failed,
        results=results,
        remediated_file_path=str(output_path)
    )


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
