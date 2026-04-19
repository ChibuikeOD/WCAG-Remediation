# Replace LayoutLM PDF Tagging with OpenDataLoader Extraction

## Summary
- Replace LayoutLM-based PDF structure detection with OpenDataLoader JSON extraction, while keeping the existing Python `pikepdf` structure writer as the component that actually writes tags into the PDF.
- Keep the current frontend/backend remediation API stable; the swap is internal to the PDF auto-tagging pipeline and debug overlay generation.
- Do **not** depend on OpenDataLoader `format="pdf"` for tagging. In the checked-out source and in the public `2.2.1` release dated April 3, 2026, that path generates an annotated/debug PDF, not a real `/StructTreeRoot` tagged PDF.

## Key Changes
- Add a shared PDF auto-tagging service in `backend/` and route both `PDFRemediator.auto_tag_document(...)` and `PDFAccessibilityAnalyzer.auto_tag_document(...)` through it, instead of keeping the current duplicated LayoutLM flow.
- Introduce provider-neutral layout types so `PageLayout` / `StructureBlock` no longer depend on LayoutLM word predictions or confidence scores. `StructureBlock` should carry explicit text content for OpenDataLoader-derived blocks.
- Implement an OpenDataLoader adapter that:
  - resolves runtime in this order: built local checkout at `opendataloader-pdf-main` if artifacts exist, else installed `opendataloader-pdf==2.2.1`, else returns a clear feature/setup error;
  - runs OpenDataLoader with `format="json"`, `include_header_footer=True`, and `use_struct_tree=False`;
  - parses the `kids` array in reading order and maps element types to current PDF tags:
    - `heading` -> `H1`..`H6`
    - `paragraph` / `text block` -> `P`
    - `list` -> `L`
    - `table` -> `Table`
    - `image` -> `Figure`
    - `caption` -> `Caption`
    - `header` / `footer` -> `Artifact`
  - converts OpenDataLoader coordinates from 1-indexed PDF-point `[left, bottom, right, top]` into the app’s 0-indexed, 0-1000 normalized boxes, including Y-axis inversion per page.
- Keep `PDFStructureBuilder` as the tag writer, but make it provider-agnostic. When `overwrite_tags=true`, explicitly clear prior `/StructTreeRoot`, parent-tree references, and page `/StructParents` before writing the replacement tree.
- Replace the current LayoutLM overlay/debug path with OpenDataLoader-derived overlays. Keep the ZIP output format, but change labels to `tag + text snippet` only because OpenDataLoader JSON does not expose confidence scores.
- Remove LayoutLM-specific runtime wiring from the active path:
  - no more `checkpoint_1` lookups in remediation/debug endpoints;
  - no more LayoutLM/AI-model wording in logs, UI copy, or docs;
  - remove `torch` / `transformers` from required backend dependencies for tagging.
- Add config/documentation for local-source integration:
  - new `OPENDATALOADER_ROOT` env var, defaulting to `<repo>/opendataloader-pdf-main`;
  - document that a local checkout must be built first (`mvn package` in `java/`, then build/install the Python wrapper wheel) because the extracted directory currently has no bundled CLI JAR.

## Public APIs / Interfaces
- No external request/response changes for `/remediate`, `/pdf/remediate`, or the frontend remediation types.
- Internal `auto_tag_document(...)` methods become provider-neutral and stop treating `model_path` / `confidence_threshold` as meaningful inputs.
- New internal config surface:
  - `OPENDATALOADER_ROOT` optional path override
  - default runtime precedence: built local checkout -> installed `opendataloader-pdf==2.2.1` -> actionable setup error

## Test Plan
- Unit test JSON-to-layout mapping using `opendataloader-pdf-main/samples/json/lorem.json` plus added fixtures for lists, tables, images, captions, headers, and footers.
- Unit test coordinate conversion: page-number normalization, PDF-point to normalized bbox conversion, and Y-axis flip.
- Integration test the shared auto-tagging service with mocked OpenDataLoader execution for:
  - successful tagging
  - missing Java / missing package / unbuilt local checkout
  - `overwrite_tags=false` skip behavior
  - `overwrite_tags=true` rebuild behavior
- Integration test `/pdf/debug/overlays` to confirm ZIP generation still works and no confidence text remains.
- Regression test remediation output and frontend-visible copy so nothing references LayoutLM, checkpoints, or AI confidence.

## Assumptions
- OpenDataLoader becomes the only structure-detection engine in the active PDF auto-tag path; LayoutLM is removed from runtime use rather than kept as fallback.
- The migration keeps the current Python block-level writer, so this pass improves structure detection and reading order but does not expand the writer to full nested `Table/TR/TD` or `L/LI` PDF hierarchy.
- The local OpenDataLoader checkout and the public `2.2.1` package both still expose extraction plus annotated-PDF output, not a production-ready auto-tag API, so the safe implementation is: OpenDataLoader for structure extraction, existing Python code for tag writing.
