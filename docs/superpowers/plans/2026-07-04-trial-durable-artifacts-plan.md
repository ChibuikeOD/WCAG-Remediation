# Trial Durable Artifacts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make trial remediation reservations, artifacts, replay, recovery, and upload validation bounded and crash-safe.

**Architecture:** Trial jobs own relative artifact keys beneath `OUTPUT_DIR/jobs/{job_id}` and publish a same-filesystem temporary directory atomically. `TrialService` owns reservation/start, completion, and stale-release transactions; the API owns pipeline execution and safe filesystem cleanup. Uploads stream into temporary files and parse PDFs off the event loop under a short timeout.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite/PostgreSQL migration DDL, PyMuPDF, pytest.

---

### Task 1: Durable job state and atomic lifecycle

**Files:**
- Modify: `backend/database.py`
- Modify: `backend/trial/service.py`
- Modify: `supabase/migrations/202607040001_trial_core.sql`
- Test: `backend/tests/test_trial_models.py`
- Test: `backend/tests/test_trial_service.py`

- [ ] Add failing tests for five nullable job columns, migration parity, atomic `reserve_and_start_processing`, atomic response/artifact completion, and idempotent expired-lease release.
- [ ] Run the focused model/service tests and confirm failures identify missing columns/methods.
- [ ] Add `output_artifact_key`, `report_artifact_key`, `response_json`, `processing_started_at`, and `lease_expires_at`; implement service operations using one commit each and exact ledger validation.
- [ ] Re-run focused tests until green.

### Task 2: Bounded upload staging

**Files:**
- Modify: `backend/main.py`
- Test: `backend/tests/test_trial_api.py`

- [ ] Add failing tests using a counting upload stream for early oversized rejection and patched PDF parsing for worker-thread timeout behavior.
- [ ] Replace whole-body reads with 1 MiB staging writes, size checks, signature validation, `asyncio.wait_for(run_in_threadpool(...))`, atomic final promotion, and containment-safe cleanup.
- [ ] Re-run upload API tests until green while preserving testing-mode HTML/PDF behavior.

### Task 3: Job-scoped publish, replay, and downloads

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/tests/test_trial_api.py`
- Modify intentional download assertions in `backend/tests/test_api.py`

- [ ] Add failing tests for unique cross-user artifacts/download bytes, path traversal filenames, replay without rerun/recharge, corrupt replay state, and cleanup on failure/cancellation.
- [ ] Stage under `OUTPUT_DIR/.tmp`, process with a sanitized display name, atomically publish to `OUTPUT_DIR/jobs/{job_id}`, store relative keys plus serialized response in the completion transaction, and replay only validated succeeded state.
- [ ] Resolve trial downloads from the authenticated succeeded job and its contained stored key; retain legacy testing-mode behavior.
- [ ] Re-run API/remediation/auth tests until green.

### Task 4: Verification and commits

**Files:** all files above.

- [ ] Run `pytest backend/tests/test_trial_api.py backend/tests/test_trial_service.py backend/tests/test_trial_models.py backend/tests/test_api.py backend/tests/test_supabase_auth.py -q`.
- [ ] Run `pytest backend/tests -q`, `python -m compileall -q backend`, and `git diff --check`.
- [ ] Review requirements A-D against tests, commit follow-up changes without amending prior commits, and report SHAs plus optional skips.
