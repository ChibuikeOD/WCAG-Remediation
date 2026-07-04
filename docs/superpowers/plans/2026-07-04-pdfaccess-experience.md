# PDFAccess Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the approved `code.html` prototype into the `pdfaccess.org` registration entry point, connect Supabase magic links, display trial usage, and rebrand every product surface to PDFAccess.

**Architecture:** A deployment-mode router renders the public landing/auth flow only in trial mode and preserves the direct workspace in testing mode. A small auth provider owns Supabase session state; the existing remediation components remain shared.

**Tech Stack:** React 18, Vite, TypeScript, Supabase JS, Tailwind CSS, Vitest, Testing Library

---

### Task 1: Frontend test harness and mode contract

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/vite.config.ts`
- Create: `frontend/src/config.ts`
- Create: `frontend/src/config.test.ts`

- [ ] **Step 1: Add failing tests asserting `trial` and `testing` are accepted and unknown modes throw.**
- [ ] **Step 2: Run `npm --prefix frontend test -- --run`; expect a missing-script failure.**
- [ ] **Step 3: Add Vitest, jsdom, Testing Library dependencies and a `test: "vitest"` script. Implement `deploymentMode()` from `VITE_DEPLOYMENT_MODE`, defaulting to `testing` locally and throwing for other values.**
- [ ] **Step 4: Run `npm --prefix frontend test -- --run`; expect passing tests.**
- [ ] **Step 5: Commit with `git add frontend && git commit -m "test: add frontend mode contract"`.**

### Task 2: Supabase magic-link session provider

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/src/auth/supabase.ts`
- Create: `frontend/src/auth/AuthProvider.tsx`
- Create: `frontend/src/auth/AuthProvider.test.tsx`
- Modify: `frontend/src/api.ts`

- [ ] **Step 1: Write failing tests for loading, signed-out, check-email, signed-in, sign-out, and expired-link error states using a mocked Supabase client.**
- [ ] **Step 2: Run the focused test and confirm missing-module failure.**
- [ ] **Step 3: Add `@supabase/supabase-js`; create the client only in trial mode from `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY`. Implement `signInWithOtp({email, options:{emailRedirectTo: `${location.origin}/auth/callback`}})`. Subscribe to `onAuthStateChange` and expose the access token.**
- [ ] **Step 4: Change `fetchJSON` to attach `Authorization: Bearer ${token}` through a registered token getter in trial mode while preserving same-origin testing calls.**
- [ ] **Step 5: Run auth and API tests; expect all passing. Commit with `git add frontend && git commit -m "feat: add PDFAccess magic-link sessions"`.**

### Task 3: Prototype-derived public landing page

**Files:**
- Create: `frontend/src/landing/LandingPage.tsx`
- Create: `frontend/src/landing/TrialSignupForm.tsx`
- Create: `frontend/src/landing/LandingPage.test.tsx`
- Modify: `frontend/src/index.css`
- Reference only: `code.html`, `DESIGN.md`, `screen.png`

- [ ] **Step 1: Write failing tests for the PDFAccess name, 200/400-page explanation, email label, submit action, check-email state, support link, and keyboard-accessible mobile menu.**
- [ ] **Step 2: Run the focused test and confirm missing-component failure.**
- [ ] **Step 3: Port the prototype header, hero, proof strip, main content sections, signup CTA, and footer into semantic React components. Replace `AccessPDF`, “Apply,” and “early access” copy with PDFAccess free-trial copy; preserve Public Sans/Inter, teal/navy palette, 44px targets, focus rings, and responsive grid from `DESIGN.md`.**
- [ ] **Step 4: Connect the form to `AuthProvider.sendMagicLink`; use a visible label, normalized email input, disabled submitting state, generic success message, and `support@pdfaccess.org` question link.**
- [ ] **Step 5: Run tests and `npm --prefix frontend run build`; expect success. Commit with `git add frontend && git commit -m "feat: build PDFAccess trial landing page"`.**

### Task 4: Mode-aware application shell and balance UI

**Files:**
- Create: `frontend/src/trial/TrialUsage.tsx`
- Create: `frontend/src/trial/TrialUsage.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/components/Header.tsx`

- [ ] **Step 1: Write failing tests that signed-out trial mode renders `LandingPage`, signed-in trial mode renders the workspace and balance, testing mode opens the workspace directly, and a 409 renders “This PDF has X pages; Y trial pages remain.”**
- [ ] **Step 2: Add `getTrialBalance()` and the typed granted/consumed/reserved/remaining response. Implement a progress meter with text values so color is never the only signal.**
- [ ] **Step 3: Refactor `App` into mode/auth routing while retaining the existing upload/dashboard state machine. Remove OIDC login URLs and session-cookie assumptions.**
- [ ] **Step 4: Run all frontend tests and build; expect success. Commit with `git add frontend && git commit -m "feat: connect trial workspace and balance"`.**

### Task 5: Complete PDFAccess naming pass

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/src/**/*.tsx`
- Modify: `backend/config.py`
- Modify: `backend/main.py`
- Modify: `backend/remediation_report.py`
- Modify: `README.md`
- Create: `backend/tests/test_pdfaccess_brand.py`

- [ ] **Step 1: Write a failing repository scan that rejects product-name strings `AccessPDF`, `WCAG Accessibility Platform`, and `WCAG Accessibility Remediation Platform` in user-facing files while allowing WCAG standards terminology.**
- [ ] **Step 2: Replace browser title, headers, footers, API title, report product heading, demo addresses, and documentation product name with PDFAccess. Do not rename WCAG rules, conformance labels, or standards links.**
- [ ] **Step 3: Run `pytest backend/tests/test_pdfaccess_brand.py -q`, the complete frontend test suite, and the frontend build; expect success.**
- [ ] **Step 4: Commit with `git commit -am "chore: rebrand product surfaces to PDFAccess"`.**
