# API Test Lifespan Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make API integration tests initialize and shut down the real FastAPI application lifespan so database tables exist in a fresh checkout.

**Architecture:** Keep production startup and database configuration unchanged. The pytest client fixture will enter `TestClient` as a context manager, which runs the existing lifespan and `init_db()` before yielding the client.

**Tech Stack:** Python 3, FastAPI, Starlette TestClient, SQLAlchemy, pytest

---

## File Structure

- Modify `backend/tests/test_api.py`: make its shared client fixture own the application lifespan.

### Task 1: Run API Tests Through Application Lifespan

**Files:**
- Modify: `backend/tests/test_api.py:14-19`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Reproduce the existing database failures**

Run:

```powershell
& 'C:\Users\chibu\OneDrive\Documents\Data Viz\WCAG Project\VirtualEnvironment\Scripts\python.exe' -m pytest -p no:asyncio backend/tests/test_api.py -v
```

Expected: 8 failures contain `sqlite3.OperationalError: no such table`, while 6 tests pass.

- [ ] **Step 2: Make the fixture enter and exit application lifespan**

Replace the fixture with:

```python
@pytest.fixture
def client():
    """Create a test client with application lifespan running."""
    with TestClient(app) as test_client:
        yield test_client
```

- [ ] **Step 3: Verify the focused API file passes**

Run:

```powershell
& 'C:\Users\chibu\OneDrive\Documents\Data Viz\WCAG Project\VirtualEnvironment\Scripts\python.exe' -m pytest -p no:asyncio backend/tests/test_api.py -v
```

Expected: all 14 tests pass; no missing-table error remains.

- [ ] **Step 4: Check formatting and scope**

Run:

```powershell
git diff --check -- backend/tests/test_api.py
git diff -- backend/tests/test_api.py
```

Expected: no whitespace errors and only the fixture lifecycle changes.

- [ ] **Step 5: Commit the repair**

```powershell
git add backend/tests/test_api.py
git commit -m "test: run API client through application lifespan"
```

