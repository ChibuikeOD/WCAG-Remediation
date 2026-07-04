# PDFAccess Email Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Send branded transactional and state-aware trial activation emails to verified users, with one-click unsubscribe and bounce/complaint suppression.

**Architecture:** A Resend adapter owns delivery and provider idempotency. Database delivery records provide durable scheduling; signed unsubscribe links and verified Svix webhooks update a suppression table. Supabase Auth uses Resend SMTP for magic-link delivery.

**Tech Stack:** FastAPI, SQLAlchemy, httpx, itsdangerous, Svix, Resend API, Vercel Cron, pytest

---

### Task 1: Email schema and configuration

**Files:**
- Modify: `backend/config.py`
- Modify: `backend/database.py`
- Modify: `backend/env.example`
- Modify: `backend/requirements.txt`
- Create: `supabase/migrations/202607040002_email.sql`
- Create: `backend/tests/test_email_models.py`

- [ ] **Step 1: Write failing tests for one preference per user, unique `(user_id, campaign_key)`, unique provider event IDs, and suppression timestamps.**
- [ ] **Step 2: Add `EmailPreference`, `EmailDelivery`, and `EmailWebhookEvent`; mirror them in SQL with owner-select RLS and backend-only mutations. Add `RESEND_API_KEY`, `RESEND_WEBHOOK_SECRET`, `EMAIL_FROM`, `EMAIL_REPLY_TO`, `BUSINESS_POSTAL_ADDRESS`, `PUBLIC_APP_URL`, and `CRON_SECRET`. Trial mode must reject promotional sending when the postal address is empty.**
- [ ] **Step 3: Add `svix==1.68.0`, run model/config tests, and commit with `git commit -am "feat: add email delivery schema"`.**

### Task 2: Resend adapter and accessible templates

**Files:**
- Create: `backend/email/resend_client.py`
- Create: `backend/email/templates.py`
- Create: `backend/email/__init__.py`
- Create: `backend/tests/test_resend_client.py`
- Create: `backend/tests/test_email_templates.py`

- [ ] **Step 1: Write failing tests for sender/reply-to fields, plain-text and HTML bodies, escaped user content, support address, postal address, unsubscribe URL, and `List-Unsubscribe` plus `List-Unsubscribe-Post` headers.**
- [ ] **Step 2: Implement `ResendClient.send(message, idempotency_key)` using `POST https://api.resend.com/emails`, bearer authorization, a 20-second timeout, and the `Idempotency-Key` header. Raise a typed retryable error for 429/5xx and a permanent error for other 4xx responses.**
- [ ] **Step 3: Implement templates for activation, remediation completion, remediation failure, first-upload reminder, remaining-pages reminder, and support invitation. Every promotional template includes a visible unsubscribe link and `mailto:support@pdfaccess.org`.**
- [ ] **Step 4: Run focused tests; expect passing. Commit with `git add backend/email backend/tests && git commit -m "feat: add PDFAccess email delivery adapter"`.**

### Task 3: Campaign scheduler and state-aware selection

**Files:**
- Create: `backend/email/campaigns.py`
- Create: `backend/tests/test_email_campaigns.py`
- Modify: `backend/main.py`
- Modify: `vercel.json`

- [ ] **Step 1: Write failing tests proving only verified, non-suppressed users are selected; first-upload reminders skip users with jobs; campaign retries do not duplicate deliveries; and testing mode sends nothing.**
- [ ] **Step 2: Implement campaign keys `welcome`, `first-upload`, `remaining-pages`, and `support-invitation`. Insert the delivery row before sending, use `campaign/user-id` as both the database and Resend idempotency key, and update status after provider response.**
- [ ] **Step 3: Add `POST /internal/email/campaigns`, require exact `Authorization: Bearer ${CRON_SECRET}`, and return 404 outside trial mode. Add one daily Vercel cron entry.**
- [ ] **Step 4: Run campaign and API tests; expect passing. Commit with `git commit -am "feat: schedule trial activation emails"`.**

### Task 4: Unsubscribe and provider-event suppression

**Files:**
- Create: `backend/email/preferences.py`
- Create: `backend/tests/test_email_preferences.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Write failing tests for signed-token GET confirmation, RFC 8058 POST unsubscribe, tampered/expired tokens, repeated requests, verified Svix webhook processing, replayed `svix-id`, and bounce/complaint suppression.**
- [ ] **Step 2: Implement URL-safe timed tokens containing user ID and email-purpose version. `GET /email/unsubscribe/{token}` renders confirmation; `POST` immediately suppresses and returns empty 200.**
- [ ] **Step 3: Add `POST /webhooks/resend`; read the raw request body, verify `svix-id`, `svix-timestamp`, and `svix-signature` with `RESEND_WEBHOOK_SECRET`, store the event ID before applying it, and suppress on hard bounce or complaint.**
- [ ] **Step 4: Run all email tests and `python -m compileall backend`; expect success. Commit with `git commit -am "feat: enforce email unsubscribe and suppression"`.**
