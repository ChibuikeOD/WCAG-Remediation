# Backend Baseline Test Repairs

## Goal

Restore a clean backend test baseline by fixing the two confirmed, independent root causes exposed in a fresh worktree: API tests that bypass FastAPI lifespan initialization and selector checks that incorrectly suppress supported `:has(...)` queries.

## Root Causes

### API database initialization

The `backend/tests/test_api.py` client fixture returns a bare `TestClient(app)`. With the installed Starlette behavior, application lifespan starts only when the client is used as a context manager. Because `init_db()` runs exclusively during lifespan startup, a fresh checkout reaches authenticated and report-storage database queries before the `users` and `accessibility_reports` tables exist.

### Table-header selector evaluation

The WCAG 1.3.1 rule uses a valid `table:not(:has(th))` selector. `RulesEngine._check_selector` returns early for every selector containing `:has(` based on an obsolete assumption that BeautifulSoup cannot evaluate it. The installed BeautifulSoup/SoupSieve stack evaluates the rule selector correctly, so the guard suppresses a real accessibility issue.

## Design

### API fixture repair

Change the API test fixture to yield a context-managed `TestClient(app)`. Entering the context runs the real application lifespan, including database schema creation, and exiting it performs the matching shutdown. Each test patches the database engine and sessions to a file-backed temporary SQLite database, redirects upload/output directories to temporary paths, and replaces the destructive retention loop with a cancellable idle test double. Production database configuration and application startup code remain unchanged.

This repair intentionally does not introduce an app factory or database dependency-injection refactor. Those could improve test isolation later, but they are not required to address the confirmed failure.

### Selector repair

Retain general deferral for `:has(...)` selectors. Add a narrow static evaluator for the exact WCAG 1.3.1 table-header selector: select table elements normally, then use direct DOM traversal to keep only tables without a `<th>`, `role="columnheader"`, or `role="rowheader"`. This avoids activating unrelated selectors whose sibling relationships are semantically incorrect and can exhibit quadratic SoupSieve performance.

Add focused regression tests for a headerless table, native and ARIA header cells, and continued deferral of unrelated `:has(...)` selectors. The existing `test_table_without_headers` remains the higher-level integration regression.

## Data and Control Flow

1. Each API test enters `TestClient(app)`.
2. FastAPI lifespan calls `init_db()`, creating required tables in a fresh database before requests or database-backed test setup execute.
3. The fixture yields the live client and closes it after the test.

For HTML analysis:

1. `RulesEngine.analyze_html` dispatches a selector check.
2. `_check_selector` recognizes the exact table-header selector and evaluates header presence through direct DOM traversal.
3. Other `:has(...)` selectors remain deferred and return no static issues.
4. Matching headerless tables become normal `AccessibilityIssue` objects through the existing mapping path.
5. Selector evaluation exceptions continue to be caught by the existing handler.

## Error Handling

- API startup failures must surface during fixture setup rather than being hidden.
- Selector syntax or evaluation errors continue to return no issues and emit the existing debug log entry.
- The table-header evaluator performs linear descendant checks and never runs the rule through SoupSieve's relational selector engine.
- Neither repair changes production request behavior, authentication policy, database URLs, WCAG rule content, or browser-required check routing.

## Testing

- Reproduce the API failures before changing the fixture.
- Change only the fixture and verify all tests in `backend/tests/test_api.py` pass in a fresh worktree database.
- Add a focused failing table-header regression test before adding the narrow evaluator.
- Add regression coverage proving native/ARIA headers do not produce issues and unrelated `:has(...)` selectors remain deferred.
- Verify the focused selector tests and `TestHTMLAnalysis::test_table_without_headers` pass after the change.
- Run the complete `backend/tests` suite with the incompatible external pytest-asyncio plugin disabled.
- Re-run the mandatory PDF structure contract tests and frontend production build to ensure the original feature remains intact.

## Non-goals

- Refactoring the application into an app factory.
- Replacing the project database layer or changing production persistence.
- Implementing a general CSS selector parser or enabling all `:has(...)` rules.
- Changing WCAG rule definitions or table-header policy.
- Fixing unrelated warnings or dependency versions.
