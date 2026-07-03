# Gemini PDF Unicode Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route ambiguous PDF Unicode verification through Gemini 3.1 Flash-Lite vision with strict fail-closed validation and accurate reporting.

**Architecture:** Add a Gemini transport around the existing context and validation contract, select it when `GEMINI_API_KEY` is present, and make disclosures provider-neutral.

**Tech Stack:** Python, httpx, Pydantic, Pillow, pytest, ReportLab, Docker Compose.

---

### Task 1: Gemini request and transport

- [ ] Add failing tests in `backend/tests/test_gemini_unicode_verifier.py` for model, images, probe, JSON, endpoint, and rejection paths.
- [ ] Run them red.
- [ ] Create `backend/gemini_unicode_verifier.py`, reusing strict response validation.
- [ ] Run them green.

### Task 2: Configuration and provider selection

- [ ] Add a failing adapter test for Gemini selection.
- [ ] Add Gemini settings in `backend/config.py` and select Gemini in `backend/pdf_remediator_fixes.py`.
- [ ] Document variables in `backend/env.example` and forward the key in `docker-compose.yml`.
- [ ] Run adapter and Unicode tests green.

### Task 3: Provider-neutral reporting

- [ ] Add failing report tests expecting Gemini wording.
- [ ] Carry provider/model metadata through `backend/pdf_unicode_mapping.py`.
- [ ] Make `backend/remediation_report.py` provider-neutral.
- [ ] Run report tests green.

### Task 4: Documentation and verification

- [ ] Update `README.md`.
- [ ] Run focused verifier/remediation/report tests.
- [ ] Run the complete backend suite and `git diff --check`.
