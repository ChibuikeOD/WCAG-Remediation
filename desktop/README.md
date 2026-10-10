# PDFAccess Desktop for Windows

Extract the entire ZIP, then open `PDFAccess/PDFAccess.exe`. Keep `_internal` beside
the executable. Windows x64 is supported. Python, Java, an account, and an internet
connection are not required after download. The bundle includes Java, the native
PDF tagger, QPDF, and English OCR language data.

Choose a PDF, choose an output folder, and select **Remediate on this device**.
Each run creates a separate folder containing the repaired PDF, a PDF remediation
report, and `review.json` with before/after findings. The original is never edited.
Temporary working copies are removed after processing. Saved outputs remain in the
folder you chose until you delete them. The app accepts PDFs up to 50 MB / 100 pages.

Cloud AI, authentication, storage, billing, model downloads, and telemetry are
disabled. Python network calls are blocked. The bundled Java command only performs
local layout extraction; document URLs are not fetched. Treat inputs and exports
with the same care as the original documents, including access permissions and
your organization's backups or synced folders.

English OCR, metadata, tagging, deterministic Unicode repair, bookmarks, and
structural fixes run locally. AI-generated alt text and uncertain glyph decisions
are unavailable offline. Review figure descriptions, tables, reading order, and
all remaining findings with an accessibility specialist. Automated output is not
a certification of WCAG or PDF/UA compliance.

## Updates

Updates are explicit downloads. Visit the project's Releases page when you want
a newer version, verify its checksum against `SHA256SUMS.txt`, close the old app,
and extract the new release into a separate folder. Existing output folders are
independent of the app and remain available. The app does not contact an update
server or replace itself while processing a document.

## Command line

```powershell
.\PDFAccess.exe --remediate document.pdf --output-dir C:\Exports --result-json C:\Exports\result.json
.\PDFAccess.exe --self-test C:\Temp\PDFAccessTest --result-json C:\Temp\PDFAccessTest\result.json
```

The release pipeline checks the packaged executable's analysis, native tagging,
OCR, and PDF report generation. Dependency license notices are in
`_internal/notices` and the bundled Java runtime's `legal` directory. This build
is for evaluation until the project license and distribution terms are resolved.
