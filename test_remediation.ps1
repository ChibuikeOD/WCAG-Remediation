# ============================================
# PDF Remediation Test Script
# ============================================
# This script uploads a PDF, applies fixes, and generates a report

param(
    [string]$PdfFile = "Test PDF 2.pdf",
    [string]$Title = "Test Document - Remediated",
    [string]$Language = "en"
)

$baseUrl = "http://localhost:8000"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host " PDF Remediation with Report Generation" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

# Step 1: Upload
Write-Host "`n[1/4] Uploading $PdfFile..." -ForegroundColor Yellow

$filePath = Join-Path (Get-Location) $PdfFile
if (-not (Test-Path $filePath)) {
    Write-Host "ERROR: File not found: $filePath" -ForegroundColor Red
    exit 1
}

$fileBytes = [System.IO.File]::ReadAllBytes($filePath)
$fileEnc = [System.Text.Encoding]::GetEncoding('ISO-8859-1').GetString($fileBytes)
$boundary = [System.Guid]::NewGuid().ToString()
$LF = "`r`n"

$bodyLines = (
    "--$boundary",
    "Content-Disposition: form-data; name=`"file`"; filename=`"$PdfFile`"",
    "Content-Type: application/pdf$LF",
    $fileEnc,
    "--$boundary--$LF"
) -join $LF

try {
    $uploadResponse = Invoke-RestMethod -Uri "$baseUrl/upload" -Method Post -ContentType "multipart/form-data; boundary=$boundary" -Body $bodyLines
    $fileId = $uploadResponse.file_id
    Write-Host "   SUCCESS: File ID = $fileId" -ForegroundColor Green
} catch {
    Write-Host "   ERROR: Upload failed - $_" -ForegroundColor Red
    exit 1
}

# Step 2: Analyze (before)
Write-Host "`n[2/4] Analyzing current accessibility state..." -ForegroundColor Yellow

try {
    $analysisResponse = Invoke-RestMethod -Uri "$baseUrl/pdf/analyze?file_id=$fileId" -Method Post
    Write-Host "   Found $($analysisResponse.summary.total_issues) issues ($($analysisResponse.summary.auto_fixable) auto-fixable)" -ForegroundColor Yellow
} catch {
    Write-Host "   WARNING: Analysis failed - $_" -ForegroundColor Yellow
}

# Step 3: Remediate
Write-Host "`n[3/4] Applying fixes..." -ForegroundColor Yellow
Write-Host "   - Setting title: $Title"
Write-Host "   - Setting language: $Language"
Write-Host "   - Generating bookmarks: Yes"

$encodedTitle = [System.Web.HttpUtility]::UrlEncode($Title)
$remediateUrl = "$baseUrl/pdf/remediate?file_id=$fileId&title=$encodedTitle&language=$Language&add_bookmarks=true&auto_tag=true&generate_report=true"

try {
    $remediateResponse = Invoke-RestMethod -Uri $remediateUrl -Method Post
    Write-Host "   SUCCESS: $($remediateResponse.total_changes) changes applied" -ForegroundColor Green
} catch {
    Write-Host "   ERROR: Remediation failed - $_" -ForegroundColor Red
    exit 1
}

# Step 4: Results
Write-Host "`n[4/4] Results:" -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Cyan

Write-Host "`nCHANGES APPLIED:" -ForegroundColor White
foreach ($change in $remediateResponse.changes) {
    $type = $change.type -replace "_", " "
    $value = if ($change.value) { $change.value } elseif ($change.title) { $change.title } elseif ($change.lang) { $change.lang } else { "Done" }
    Write-Host "   [OK] $type : $value" -ForegroundColor Green
}

if ($remediateResponse.report_filename) {
    Write-Host "`nREMEDIATION REPORT GENERATED:" -ForegroundColor White
    Write-Host "   File: $($remediateResponse.report_filename)" -ForegroundColor Cyan
    
    # Download the report
    $reportUrl = "$baseUrl/pdf/report/$($remediateResponse.report_filename)"
    $localReportPath = Join-Path (Get-Location) $remediateResponse.report_filename
    
    Write-Host "   Downloading report..." -ForegroundColor Gray
    try {
        Invoke-WebRequest -Uri $reportUrl -OutFile $localReportPath
        Write-Host "   Saved to: $localReportPath" -ForegroundColor Green
        
        # Open the report
        Write-Host "`nOpening report..." -ForegroundColor Yellow
        # Start-Process $localReportPath
    } catch {
        Write-Host "   Download URL: $reportUrl" -ForegroundColor Gray
    }
}

# Download fixed PDF
Write-Host "`nDOWNLOAD FIXED PDF:" -ForegroundColor White
$fixedPdfPath = Join-Path (Join-Path (Get-Location) "output") "$($PdfFile -replace '\.pdf$', '_FIXED.pdf')"
New-Item -ItemType Directory -Path (Split-Path $fixedPdfPath) -Force | Out-Null

try {
    Invoke-WebRequest -Uri "$baseUrl/pdf/download/$fileId" -OutFile $fixedPdfPath
    Write-Host "   Saved to: $fixedPdfPath" -ForegroundColor Green
} catch {
    Write-Host "   Download URL: $baseUrl/pdf/download/$fileId" -ForegroundColor Gray
}

Write-Host "`n============================================" -ForegroundColor Cyan
Write-Host " Remediation Complete!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Cyan





