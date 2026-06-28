# API Test Lifespan Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make API integration tests initialize and shut down the real FastAPI application lifespan so database tables exist in a fresh checkout.

**Architecture:** Keep production startup and database configuration unchanged. The pytest client fixture enters `TestClient` as a context manager while patching database sessions and file paths to per-test temporary storage; the destructive retention loop is replaced with a cancellable idle test double.

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

- [ ] **Step 2: Add an isolation regression test**

```python
def test_client_uses_isolated_storage(client, tmp_path):
    assert Path(str(database.engine.url.database)).parent == tmp_path
    assert settings.UPLOAD_DIR == tmp_path / "uploads"
    assert settings.OUTPUT_DIR == tmp_path / "output"
```

Run this test against the context-only fixture and verify it fails because the engine still points to `./wcag_platform.db`.

- [ ] **Step 3: Make the fixture isolated and lifespan-aware**

Add imports for `asyncio`, SQLAlchemy `create_engine`/`sessionmaker`, `backend.database as database`, and `backend.main as main_module`. Replace the fixture with:

```python
@pytest.fixture
def client(tmp_path, monkeypatch):
    """Create an isolated test client with application lifespan running."""
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    test_session = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=test_engine,
    )

    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", test_session)
    monkeypatch.setattr(main_module, "SessionLocal", test_session)

    upload_dir = tmp_path / "uploads"
    output_dir = tmp_path / "output"
    upload_dir.mkdir()
    output_dir.mkdir()
    monkeypatch.setattr(settings, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(settings, "OUTPUT_DIR", output_dir)

    async def idle_retention_worker():
        await asyncio.Event().wait()

    monkeypatch.setattr(
        main_module,
        "clean_expired_documents",
        idle_retention_worker,
    )

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        test_engine.dispose()
```

- [ ] **Step 4: Verify the focused API file passes**

Run:

```powershell
& 'C:\Users\chibu\OneDrive\Documents\Data Viz\WCAG Project\VirtualEnvironment\Scripts\python.exe' -m pytest -p no:asyncio backend/tests/test_api.py -v
```

Expected: all 15 tests pass; no missing-table error remains and the isolation test passes.

- [ ] **Step 5: Check formatting and scope**

Run:

```powershell
git diff --check -- backend/tests/test_api.py
git diff -- backend/tests/test_api.py
```

Expected: no whitespace errors and only the fixture lifecycle changes.

- [ ] **Step 6: Commit the repair**

```powershell
git add backend/tests/test_api.py
git commit -m "test: isolate API client database and storage"
```
