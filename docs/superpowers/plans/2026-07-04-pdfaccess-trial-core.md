# PDFAccess Trial Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add verified Supabase identity, one-time 200/400-page grants, and atomic remediation quota enforcement without changing the PDF remediation engine.

**Architecture:** FastAPI verifies Supabase bearer tokens in trial mode and retains the current development identity only in testing mode. Focused eligibility and ledger services own trial policy; `/remediate` reserves pages before invoking the existing pipeline, consumes them on success, and releases them on failure.

**Tech Stack:** FastAPI, SQLAlchemy 2, PostgreSQL/Supabase, PyJWT, PyMuPDF, pytest

---

### Task 1: Fail-closed deployment configuration

**Files:**
- Modify: `backend/config.py`
- Modify: `backend/env.example`
- Create: `backend/tests/test_deployment_config.py`

- [ ] **Step 1: Write failing configuration tests**

```python
from pydantic import ValidationError
from backend.config import Settings

def test_trial_mode_rejects_auth_bypass():
    with pytest.raises(ValidationError, match="DISABLE_AUTH"):
        Settings(DEPLOYMENT_MODE="trial", DISABLE_AUTH=True, _env_file=None)

def test_testing_mode_allows_current_bypass():
    value = Settings(DEPLOYMENT_MODE="testing", DISABLE_AUTH=True, _env_file=None)
    assert value.DEPLOYMENT_MODE == "testing"
```

- [ ] **Step 2: Run `pytest backend/tests/test_deployment_config.py -q` and confirm it fails because `DEPLOYMENT_MODE` is undefined.**
- [ ] **Step 3: Add `DEPLOYMENT_MODE: Literal["trial", "testing"] = "testing"`, Supabase settings, and a `model_validator(mode="after")` that rejects trial mode when auth is disabled or required Supabase identifiers are absent. Document exact variables in `env.example`.**
- [ ] **Step 4: Run `pytest backend/tests/test_deployment_config.py -q`; expect 2 passed.**
- [ ] **Step 5: Commit with `git commit -am "feat: validate trial deployment configuration"`.**

### Task 2: Supabase JWT authentication boundary

**Files:**
- Modify: `backend/requirements.txt`
- Replace: `backend/auth.py`
- Create: `backend/tests/test_supabase_auth.py`

- [ ] **Step 1: Add failing tests for missing bearer tokens, unverified email claims, valid verified claims, and testing-mode identity. Use a stub verifier returning:**

```python
{
    "sub": "user-123",
    "email": "person@university.edu",
    "role": "authenticated",
    "email_confirmed_at": "2026-07-04T12:00:00Z",
}
```

- [ ] **Step 2: Run `pytest backend/tests/test_supabase_auth.py -q`; expect import or assertion failures.**
- [ ] **Step 3: Add `PyJWT[crypto]==2.10.1`. Implement `verify_supabase_token(token)` with `PyJWKClient(f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json")`, restricting algorithms to `RS256` and `ES256`, issuer to `SUPABASE_URL/auth/v1`, and audience to `authenticated`.**
- [ ] **Step 4: Make `require_user` read `HTTPBearer(auto_error=False)`. In trial mode, reject absent/invalid/unverified claims with 401/403 and upsert `User(id=sub, email=email)`; in testing mode only, retain the development user. Remove OIDC routes and session-cookie dependence.**
- [ ] **Step 5: Run `pytest backend/tests/test_supabase_auth.py backend/tests/test_retention_and_auth.py -q`; expect all tests to pass after updating the obsolete OIDC assertions.**
- [ ] **Step 6: Commit with `git commit -am "feat: authenticate trial users with Supabase"`.**

### Task 3: Deterministic email eligibility

**Files:**
- Create: `backend/trial/eligibility.py`
- Create: `backend/trial/__init__.py`
- Create: `backend/tests/test_trial_eligibility.py`

- [ ] **Step 1: Write parameterized failing tests asserting 200 for Gmail, Outlook/Hotmail, Yahoo, and iCloud; 400 for `.edu`, `.org`, and `employee@acme.com`; lowercase normalization; and rejection of malformed addresses.**
- [ ] **Step 2: Run `pytest backend/tests/test_trial_eligibility.py -q`; expect module-not-found failure.**
- [ ] **Step 3: Implement the complete public interface:**

```python
@dataclass(frozen=True)
class EligibilityDecision:
    normalized_email: str
    normalized_domain: str
    granted_pages: int
    rule_version: str = "2026-07-04"

def classify_verified_email(email: str) -> EligibilityDecision:
    local, separator, domain = email.strip().lower().rpartition("@")
    if separator != "@" or not local or "." not in domain:
        raise ValueError("A valid verified email is required")
    organization = domain.endswith((".edu", ".org")) or domain not in PERSONAL_DOMAINS
    return EligibilityDecision(email.strip().lower(), domain, 400 if organization else 200)
```

- [ ] **Step 4: Run `pytest backend/tests/test_trial_eligibility.py -q`; expect all cases to pass.**
- [ ] **Step 5: Commit with `git add backend/trial backend/tests/test_trial_eligibility.py && git commit -m "feat: classify PDFAccess trial eligibility"`.**

### Task 4: Trial schema and migration

**Files:**
- Modify: `backend/database.py`
- Create: `supabase/migrations/202607040001_trial_core.sql`
- Create: `backend/tests/test_trial_models.py`

- [ ] **Step 1: Write failing model tests for exactly one `TrialAccount` per user, unique ledger idempotency keys, job ownership, and persisted PDF `page_count`.**
- [ ] **Step 2: Run `pytest backend/tests/test_trial_models.py -q`; expect missing-model failures.**
- [ ] **Step 3: Add `TrialAccount`, `TrialLedgerEntry`, and `RemediationJob` SQLAlchemy models. Use integer page counts, UTC timestamps, `status` strings, unique `(user_id, idempotency_key)`, and foreign keys to `users` and `uploaded_files`. Add nullable `page_count` to `UploadedFile`.**
- [ ] **Step 4: Mirror the schema in SQL migration, enable RLS, and add owner-select policies using `auth.uid()::text = user_id`; keep mutations backend-only.**
- [ ] **Step 5: Run `pytest backend/tests/test_trial_models.py backend/tests/test_retention_and_auth.py -q`; expect all passing.**
- [ ] **Step 6: Commit with `git add backend/database.py backend/tests/test_trial_models.py supabase && git commit -m "feat: add durable trial ledger schema"`.**

### Task 5: Atomic trial ledger service

**Files:**
- Create: `backend/trial/service.py`
- Create: `backend/tests/test_trial_service.py`

- [ ] **Step 1: Write failing tests for `ensure_account`, `get_balance`, `reserve`, `consume`, and `release`, including repeated idempotency keys, two reservations exceeding the balance, and repeated release calls.**
- [ ] **Step 2: Run `pytest backend/tests/test_trial_service.py -q`; expect module-not-found failure.**
- [ ] **Step 3: Implement this interface with database transactions and row locking (`with_for_update()` on PostgreSQL):**

```python
@dataclass(frozen=True)
class TrialBalance:
    granted: int
    consumed: int
    reserved: int
    remaining: int

class InsufficientPages(Exception):
    def __init__(self, requested: int, remaining: int):
        self.requested = requested
        self.remaining = remaining
        super().__init__(f"Requested {requested} pages with {remaining} remaining")
```

`TrialService` exposes `ensure_account(user)`, `get_balance(user_id)`,
`reserve(user_id, job_id, pages, key)`, `consume(job_id)`, and
`release(job_id, reason)`. Each transition writes an immutable signed page delta,
returns the resulting `TrialBalance`, and returns the existing result for a
repeated idempotency key.

- [ ] **Step 4: Run `pytest backend/tests/test_trial_service.py -q`; expect all passing on SQLite, then run the same test file with `TEST_DATABASE_URL` pointed at the trial Supabase preview database to exercise row locks.**
- [ ] **Step 5: Commit with `git add backend/trial/service.py backend/tests/test_trial_service.py && git commit -m "feat: enforce atomic trial page balances"`.**

### Task 6: Integrate quota with upload and remediation

**Files:**
- Modify: `backend/models.py`
- Modify: `backend/main.py`
- Create: `backend/tests/test_trial_api.py`

- [ ] **Step 1: Write failing API tests proving `/trial/me` returns the grant/balance, PDF upload persists an authoritative page count, an over-balance remediation returns 409 before `PDFRemediator.fix_all`, success consumes pages, and exceptions release pages.**
- [ ] **Step 2: Run `pytest backend/tests/test_trial_api.py -q`; expect 404 and missing-field failures.**
- [ ] **Step 3: Add `TrialBalanceResponse` and `TrialLimitError` response models. Count pages with `fitz.open(stream=content, filetype="pdf").page_count` during PDF upload and persist it.**
- [ ] **Step 4: Add `GET /trial/me`. In `remediate_document`, create a job and reserve before invoking the existing HTML/PDF branches; translate `InsufficientPages` to 409 with `requested_pages` and `remaining_pages`; consume after outputs are recorded; release in `except BaseException` and re-raise. Leave testing mode unmetered.**
- [ ] **Step 5: Run `pytest backend/tests/test_trial_api.py backend/tests/test_api.py backend/tests/test_pdf_remediation_contract.py -q`; expect all passing.**
- [ ] **Step 6: Run `python -m compileall backend`; expect success. Commit with `git commit -am "feat: enforce trial quota around remediation"`.**
