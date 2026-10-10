# PDFAccess agent guide

## Repository map

- `backend/`: FastAPI service, PDF analysis/remediation code, and Python tests.
- `frontend/`: React/Vite application and Vitest tests.
- `api/`: serverless API entry point and its reduced dependency set.
- `rules/`: WCAG rule definitions.
- `supabase/migrations/`: database migrations.
- `pdfua_remediator_cpp/`: native PDF/UA remediation helper.
- `opendataloader-pdf-main/`: vendored OpenDataLoader source. Avoid editing it unless a task explicitly targets the vendor integration.

## Environment setup

For a fresh Linux or Codex Cloud checkout, run:

```bash
bash scripts/codex-cloud-setup.sh
```

The Python environment is locked for Python 3.12. Use Node.js 20 or newer for the frontend.

Do not commit `.env` files, API keys, generated PDFs, uploads, test output, model caches, or virtual environments. Standard development and test runs must work without live Supabase, Stripe, Resend, Gemini, or DeepSeek credentials. Mock those integrations unless the task explicitly requires a live integration test.

## Verification

Run the narrowest relevant checks first, then the broader checks before finalizing a cross-cutting change.

```bash
# Backend (run from the repository root so subprocess module imports resolve)
uv run --project backend pytest backend/tests -q

# Frontend
npm --prefix frontend test -- --run
npm --prefix frontend run build
```

If `uv` is unavailable, activate the Python environment and run `python -m pytest backend/tests -q` from the repository root.

## Change boundaries

- Preserve existing behavior outside the requested feature.
- Add or update tests with behavior changes.
- Treat `backend/env.example` and `deployment/*.env.example` as documentation only; use placeholders, never working credentials.
- Keep generated directories (`uploads/`, `output/`, `.artifacts/`, caches, and build folders) out of commits.
- Do not modify vendored dependencies or generated lockfiles unless dependency work is part of the task.
