# Supported Has Selector Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow the rules engine to evaluate supported CSS `:has(...)` selectors so data tables without headers are reported.

**Architecture:** Add a focused regression test around `_check_selector` using the repository's WCAG 1.3.1 selector, then remove the stale blanket early return. Existing `soup.select()` behavior and exception handling remain responsible for evaluation and graceful failure.

**Tech Stack:** Python 3, BeautifulSoup 4.12.3, SoupSieve, Pydantic, pytest

---

## File Structure

- Modify `backend/tests/test_rules_engine.py`: add a focused selector-level regression test and imports.
- Modify `backend/rules_engine.py`: remove only the obsolete `:has(...)` skip guard.

### Task 1: Prove Supported `:has(...)` Selectors Are Suppressed

**Files:**
- Modify: `backend/tests/test_rules_engine.py:10-18,80-130`
- Test: `backend/tests/test_rules_engine.py`

- [ ] **Step 1: Add the focused failing selector test**

Add this import:

```python
from bs4 import BeautifulSoup
```

Extend the models import to include `WCAGPrinciple`:

```python
from backend.models import WCAGLevel, WCAGPrinciple, DocumentInfo, IssueStatus, Severity
```

Add this method to `TestRulesEngine`:

```python
    def test_selector_check_evaluates_supported_has_selector(self, engine):
        """Supported :has() selectors should run during static analysis."""
        rule = engine.get_rule_by_id("1.3.1")
        check = next(
            item for item in rule.selector_checks
            if item.selector.startswith("table:not(:has(th))")
        )
        soup = BeautifulSoup(
            "<table><tr><td>Name</td></tr></table>",
            "html5lib",
        )

        issues = engine._check_selector(
            soup,
            check,
            rule,
            WCAGPrinciple.PERCEIVABLE,
        )

        assert len(issues) == 1
        assert "header" in issues[0].message.lower()
```

- [ ] **Step 2: Run the focused test and verify it fails for the guard**

Run:

```powershell
& 'C:\Users\chibu\OneDrive\Documents\Data Viz\WCAG Project\VirtualEnvironment\Scripts\python.exe' -m pytest -p no:asyncio backend/tests/test_rules_engine.py::TestRulesEngine::test_selector_check_evaluates_supported_has_selector -v
```

Expected: FAIL because `_check_selector` returns zero issues while the guard is present.

- [ ] **Step 3: Commit the failing regression test**

```powershell
git add backend/tests/test_rules_engine.py
git commit -m "test: cover supported has selectors"
```

### Task 2: Evaluate `:has(...)` Through SoupSieve

**Files:**
- Modify: `backend/rules_engine.py:274-284`
- Test: `backend/tests/test_rules_engine.py`

- [ ] **Step 1: Remove the obsolete blanket guard**

Delete only this block:

```python
            # Handle :has() pseudo-selector (not natively supported by BeautifulSoup)
            selector = check.selector

            # Check for :has() - we need to handle this manually
            if ':has(' in selector or ':not(:has(' in selector:
                # Skip complex selectors that require JavaScript evaluation
                # These will be handled by Playwright
                return issues
```

Keep a single selector assignment before the existing `:empty` handling:

```python
            selector = check.selector
```

Do not change the surrounding `try`/`except`; it remains the graceful fallback for selector evaluation errors.

- [ ] **Step 2: Verify focused selector behavior is green**

Run:

```powershell
& 'C:\Users\chibu\OneDrive\Documents\Data Viz\WCAG Project\VirtualEnvironment\Scripts\python.exe' -m pytest -p no:asyncio backend/tests/test_rules_engine.py::TestRulesEngine::test_selector_check_evaluates_supported_has_selector backend/tests/test_rules_engine.py::TestHTMLAnalysis::test_table_without_headers -v
```

Expected: 2 passed.

- [ ] **Step 3: Run the complete rules-engine test file**

Run:

```powershell
& 'C:\Users\chibu\OneDrive\Documents\Data Viz\WCAG Project\VirtualEnvironment\Scripts\python.exe' -m pytest -p no:asyncio backend/tests/test_rules_engine.py -v
```

Expected: all tests pass.

- [ ] **Step 4: Check formatting and scope**

Run:

```powershell
git diff --check -- backend/rules_engine.py
git diff HEAD~1 -- backend/rules_engine.py backend/tests/test_rules_engine.py
```

Expected: no whitespace errors; the production diff only removes the stale guard and retains selector exception handling.

- [ ] **Step 5: Commit the production repair**

```powershell
git add backend/rules_engine.py
git commit -m "fix: evaluate supported has selectors"
```

### Task 3: Verify Both Repairs and the Original Feature

**Files:**
- Verify: `backend/tests/test_api.py`
- Verify: `backend/tests/test_rules_engine.py`
- Verify: `backend/tests/test_pdf_remediation_contract.py`
- Verify: `backend/tests/test_frontend_remediation_contract.py`
- Verify: `backend/tests/test_pdf_auto_tagging.py`

- [ ] **Step 1: Run the complete backend suite**

Run:

```powershell
& 'C:\Users\chibu\OneDrive\Documents\Data Viz\WCAG Project\VirtualEnvironment\Scripts\python.exe' -m pytest -p no:asyncio backend/tests -q
```

Expected: all backend tests pass with zero failures.

- [ ] **Step 2: Run the frontend production build**

Run from `frontend`:

```powershell
npm run build
```

Expected: TypeScript compilation and Vite build finish with exit code 0.

- [ ] **Step 3: Verify repository hygiene**

Run:

```powershell
git diff --check 623a973..HEAD
git status --short
```

Expected: no whitespace errors and a clean worktree.
