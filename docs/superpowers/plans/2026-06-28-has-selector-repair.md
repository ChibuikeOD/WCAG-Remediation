# Supported Has Selector Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Report data tables without headers through a narrow static evaluator while keeping unrelated `:has(...)` selectors deferred.

**Architecture:** Recognize only the exact WCAG 1.3.1 table-header selector and evaluate it through direct DOM traversal. Preserve the general `:has(...)` deferral guard to avoid activating unrelated, semantically incorrect, and potentially quadratic selectors.

**Tech Stack:** Python 3, BeautifulSoup 4.12.3, SoupSieve, Pydantic, pytest

---

## File Structure

- Modify `backend/tests/test_rules_engine.py`: cover missing headers, native/ARIA headers, and unrelated-selector deferral.
- Modify `backend/rules_engine.py`: add the narrow table-header evaluator and retain general `:has(...)` deferral.

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

### Task 2: Bound Static Evaluation to Table Headers

**Files:**
- Modify: `backend/tests/test_rules_engine.py:80-145`
- Modify: `backend/rules_engine.py:35-50,274-300`
- Test: `backend/tests/test_rules_engine.py`

- [ ] **Step 1: Add safety regressions before revising the broad fix**

Add these methods to `TestRulesEngine`:

```python
    @pytest.mark.parametrize(
        "header_html",
        [
            "<th>Name</th>",
            "<td role='columnheader'>Name</td>",
            "<td role='rowheader'>Name</td>",
        ],
    )
    def test_table_header_selector_ignores_tables_with_headers(
        self,
        engine,
        header_html,
    ):
        rule = engine.get_rule_by_id("1.3.1")
        check = next(
            item for item in rule.selector_checks
            if item.selector.startswith("table:not(:has(th))")
        )
        soup = BeautifulSoup(
            f"<table><tr>{header_html}</tr></table>",
            "html5lib",
        )

        issues = engine._check_selector(
            soup,
            check,
            rule,
            WCAGPrinciple.PERCEIVABLE,
        )

        assert issues == []

    def test_selector_check_keeps_unrelated_has_selector_deferred(self, engine):
        rule = engine.get_rule_by_id("3.3.2")
        check = next(
            item for item in rule.selector_checks
            if item.selector.startswith("input[id]:not(:has(~label[for]))")
        )
        soup = BeautifulSoup(
            "<label for='email'>Email</label><input id='email'>",
            "html5lib",
        )

        issues = engine._check_selector(
            soup,
            check,
            rule,
            WCAGPrinciple.UNDERSTANDABLE,
        )

        assert issues == []
```

- [ ] **Step 2: Verify the unrelated-selector test fails under broad evaluation**

Run:

```powershell
& 'C:\Users\chibu\OneDrive\Documents\Data Viz\WCAG Project\VirtualEnvironment\Scripts\python.exe' -m pytest -p no:asyncio backend/tests/test_rules_engine.py::TestRulesEngine::test_selector_check_keeps_unrelated_has_selector_deferred -v
```

Expected: FAIL because broad SoupSieve evaluation flags the valid preceding-label input.

- [ ] **Step 3: Add a constant for the one supported relational rule**

Add after `STATIC_CAPABLE_CHECKS`:

```python
TABLE_HEADER_SELECTOR = (
    "table:not(:has(th)):not(:has([role='columnheader'])):"
    "not(:has([role='rowheader']))"
)
```

- [ ] **Step 4: Evaluate only that selector through direct DOM traversal**

At the start of the selector `try` block, use:

```python
            selector = check.selector

            if selector == TABLE_HEADER_SELECTOR:
                elements = [
                    table
                    for table in soup.select("table")
                    if table.find("th") is None
                    and table.find(
                        attrs={"role": ["columnheader", "rowheader"]}
                    ) is None
                ]
            elif ':has(' in selector:
                # Other relational selectors remain deferred until they have
                # dedicated static evaluators or browser-backed checks.
                return issues

            # Handle :empty pseudo-selector
            elif ':empty' in selector:
                base_selector = selector.replace(':empty', '')
                elements = soup.select(base_selector)
                elements = [el for el in elements if not el.get_text(strip=True) and not el.find_all()]
            else:
                elements = soup.select(selector)
```

Replace the existing `:empty`/default selection block rather than duplicating it. Do not change the surrounding `try`/`except` or issue mapping.

- [ ] **Step 5: Verify focused selector behavior is green**

Run:

```powershell
& 'C:\Users\chibu\OneDrive\Documents\Data Viz\WCAG Project\VirtualEnvironment\Scripts\python.exe' -m pytest -p no:asyncio backend/tests/test_rules_engine.py::TestRulesEngine::test_selector_check_evaluates_supported_has_selector backend/tests/test_rules_engine.py::TestRulesEngine::test_table_header_selector_ignores_tables_with_headers backend/tests/test_rules_engine.py::TestRulesEngine::test_selector_check_keeps_unrelated_has_selector_deferred backend/tests/test_rules_engine.py::TestHTMLAnalysis::test_table_without_headers -v
```

Expected: all focused cases pass, including all three parameterized header variants.

- [ ] **Step 6: Run the complete rules-engine test file**

Run:

```powershell
& 'C:\Users\chibu\OneDrive\Documents\Data Viz\WCAG Project\VirtualEnvironment\Scripts\python.exe' -m pytest -p no:asyncio backend/tests/test_rules_engine.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Check formatting and scope**

Run:

```powershell
git diff --check -- backend/rules_engine.py
git diff HEAD~1 -- backend/rules_engine.py backend/tests/test_rules_engine.py
```

Expected: no whitespace errors; the production diff restores general deferral and adds only the table-header evaluator.

- [ ] **Step 8: Commit the bounded repair and safety tests**

```powershell
git add backend/rules_engine.py backend/tests/test_rules_engine.py
git commit -m "fix: bound relational selector evaluation"
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
