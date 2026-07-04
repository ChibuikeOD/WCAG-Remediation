# PDFAccess Deployment and Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Isolate trial and testing files, data, credentials, and deployments while keeping one shared remediation source tree.

**Architecture:** A storage protocol hides local testing storage and private Supabase trial storage behind the same job interface. Two Vercel projects import the same repository but use mutually exclusive project-level environment variables and distinct Supabase projects.

**Tech Stack:** FastAPI, Supabase Storage REST API, httpx, Vercel, pytest

---

### Task 1: Storage abstraction and local adapter

**Files:**
- Create: `backend/storage/base.py`
- Create: `backend/storage/local.py`
- Create: `backend/storage/__init__.py`
- Create: `backend/tests/test_local_artifact_store.py`

- [ ] **Step 1: Write failing tests for put, materialize, signed-download response, delete, safe key validation, and user namespace isolation.**
- [ ] **Step 2: Define `ArtifactStore.put(user_id, job_id, kind, path)`, `materialize(key, destination)`, `download(key)`, and `delete(key)`. Implement `LocalArtifactStore` with resolved-path containment checks under configured upload/output roots.**
- [ ] **Step 3: Run focused tests; expect passing. Commit with `git add backend/storage backend/tests && git commit -m "refactor: isolate artifact storage behind an interface"`.**

### Task 2: Private Supabase artifact adapter

**Files:**
- Create: `backend/storage/supabase.py`
- Create: `backend/tests/test_supabase_artifact_store.py`
- Modify: `backend/config.py`

- [ ] **Step 1: Write mocked-http tests asserting keys follow `users/{user_id}/jobs/{job_id}/{kind}/{filename}`, service credentials stay in backend headers, downloads expire after 300 seconds, and foreign-user keys are rejected.**
- [ ] **Step 2: Implement storage REST calls with `SUPABASE_URL`, backend-only secret key, private `trial-originals` and `trial-results` buckets, explicit timeouts, and typed errors. Select this adapter only in trial mode; testing always selects local/testing resources.**
- [ ] **Step 3: Run adapter tests; expect passing. Commit with `git add backend/storage backend/config.py && git commit -m "feat: store trial artifacts privately in Supabase"`.**

### Task 3: Integrate artifact ownership and temporary cleanup

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/database.py`
- Modify: `backend/retention_runner.py`
- Create: `backend/tests/test_artifact_lifecycle.py`

- [ ] **Step 1: Write failing tests proving trial uploads enter private storage, each job uses a unique temporary directory, successful outputs upload before cleanup, failures clean temporary files and release quota, signed downloads require ownership, and 12-hour retention deletes only the active deployment's artifacts.**
- [ ] **Step 2: Persist artifact keys rather than trial filesystem paths. Materialize inputs into `TemporaryDirectory(prefix=f"pdfaccess-{job_id}-")`, run the unchanged remediation engine there, upload outputs, and let the context manager clean every exit path.**
- [ ] **Step 3: Update download routes to ownership-check database metadata before returning a five-minute signed trial URL or a local testing `FileResponse`.**
- [ ] **Step 4: Run lifecycle, retention, remediation-contract, and API tests; expect passing. Commit with `git commit -am "feat: isolate trial artifact lifecycle"`.**

### Task 4: Deployment manifests and operator runbook

**Files:**
- Create: `deployment/trial.env.example`
- Create: `deployment/testing.env.example`
- Create: `docs/operations/pdfaccess-release.md`
- Create: `scripts/validate_deployment.py`
- Create: `backend/tests/test_deployment_isolation.py`

- [ ] **Step 1: Write failing tests that load both example environments, assert different Supabase project refs/buckets, reject `DISABLE_AUTH=true` in trial, and reject equal database or storage identifiers across supplied trial/testing configs.**
- [ ] **Step 2: Implement the validator and document two separate Vercel project imports from the same repository, project-level rather than shared secrets, `pdfaccess.org` assignment only to trial, and `wcag-remediation.vercel.app` only to testing.**
- [ ] **Step 3: Document Supabase migrations/RLS, Resend SMTP for Supabase Auth, Resend DNS/webhook setup, required postal address, `support@pdfaccess.org` reply-to, smoke tests, rollback, and the later `DISABLE_AUTH=false` tester-lockdown step. Use symbolic example values, never live secrets.**
- [ ] **Step 4: Run `python scripts/validate_deployment.py deployment/trial.env.example deployment/testing.env.example` and `pytest backend/tests/test_deployment_isolation.py -q`; expect success.**
- [ ] **Step 5: Commit with `git add deployment docs/operations scripts backend/tests && git commit -m "docs: define isolated PDFAccess deployments"`.**

### Task 5: Full release verification

**Files:**
- Modify: `README.md`
- Create: `docs/operations/pdfaccess-release-checklist.md`

- [ ] **Step 1: Run `pytest backend/tests -q`; expect zero failures.**
- [ ] **Step 2: Run `npm --prefix frontend test -- --run` and `npm --prefix frontend run build`; expect success.**
- [ ] **Step 3: In a trial preview, register a new personal-domain user and organization-domain user; confirm 200/400 grants, over-limit 409, successful debit, failed-job release, private downloads, and unsubscribe suppression.**
- [ ] **Step 4: In the separate testing preview, confirm direct open access, no trial calls, local/testing-only artifacts, and the same remediation output contract.**
- [ ] **Step 5: Record project IDs, deployment URLs, migration versions, DNS verification, test timestamps, and rollback deployments in the checklist without recording secrets. Commit with `git add README.md docs/operations && git commit -m "docs: add PDFAccess release verification"`.**
