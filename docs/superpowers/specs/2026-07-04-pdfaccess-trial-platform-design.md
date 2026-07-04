# PDFAccess Trial Platform Design

**Date:** July 4, 2026
**Status:** Approved for implementation planning

## Objective

Launch `pdfaccess.org` as the public PDFAccess trial experience while preserving
`wcag-remediation.vercel.app` as a separate, temporarily open testing
environment. Both deployments use the same remediation source code so pipeline
improvements reach both products, but they share no runtime data, storage,
credentials, sessions, or deployment state.

The trial grants one lifetime page allowance after email verification:

- 200 pages for common personal email providers.
- 400 pages for `.edu`, `.org`, and other company or institution domains.

## Scope

This design includes:

- Rebranding the product to **PDFAccess** across user-facing surfaces.
- Converting the existing `code.html` prototype into the public landing and
  registration experience.
- Passwordless, verified-email registration through Supabase.
- Durable lifetime trial accounting and server-side enforcement.
- Private PDF and report storage isolated from the testing deployment.
- Transactional and promotional email through Resend.
- Two independent Vercel projects built from the same repository branch.
- Release, security, isolation, and regression testing.

This release does not include paid subscriptions, checkout, partial-PDF
remediation, or tester-environment lockdown. The testing deployment remains open
until the owner notifies external testers and enables a later access policy.

## Deployment Architecture

The repository feeds two independent Vercel projects from the same release
branch.

### PDFAccess trial deployment

- Primary domain: `pdfaccess.org`.
- Runtime mode: `trial`.
- Public entry point: the landing and registration experience derived from
  `code.html`.
- Authentication: Supabase passwordless magic links.
- Access policy: verified users only.
- Trial policy: server-enforced lifetime page balance.
- Data services: a dedicated Supabase project, database, and private storage.
- Email: a dedicated Resend configuration for `pdfaccess.org`.

### Testing deployment

- Domain: `wcag-remediation.vercel.app`.
- Runtime mode: `testing`.
- Public entry point: the current remediation workspace.
- Access policy: open temporarily.
- Trial policy: disabled.
- Data services: separate database and storage resources with separate secrets.
- Future policy: replace open access with an approved-tester allowlist without
  changing the remediation pipeline.

### Shared and isolated concerns

The deployments share only version-controlled application and remediation source
code. They do not share:

- Vercel projects or environment variables.
- Supabase projects, databases, or storage buckets.
- Uploaded PDFs, remediated PDFs, or generated reports.
- Authentication sessions or signing secrets.
- Logs, retention jobs, email state, or runtime temporary directories.

Each Vercel project builds and deploys independently. A failed release in one
project cannot replace or reconfigure the other. Both projects following the same
release branch ensures that a merged remediation-pipeline change is available to
both without copying the pipeline into a second codebase.

Trial enforcement must be implemented in the trial backend. Hiding controls in
the browser is not an enforcement boundary. The testing bypass is valid only in
the testing deployment and must be rejected by trial-mode configuration checks.

## Registration and Identity

PDFAccess uses Supabase passwordless magic-link authentication. The application
does not collect or store user passwords.

1. A visitor submits an email address on `pdfaccess.org`.
2. Supabase sends a time-limited magic link using the configured authenticated
   email channel.
3. An unverified identity may request another link but cannot upload, remediate,
   receive trial credits, or access the workspace.
4. Following a valid link verifies the address and creates or loads the durable
   PDFAccess profile.
5. The application assigns the lifetime grant exactly once.

Expired, malformed, or reused links show a safe recovery state that allows the
user to request a fresh link. Authentication errors must not reveal whether an
address belongs to another account.

The durable Supabase user identifier is the principal for jobs, files, ledger
entries, and email preferences. Logout, repeated verification, profile edits, or
email delivery retries cannot issue another grant.

## Trial Eligibility

Eligibility is evaluated from the normalized domain of the verified email
address.

- Addresses ending in `.edu` receive 400 pages.
- Addresses ending in `.org` receive 400 pages.
- Addresses on domains not classified as common personal email providers receive
  400 pages.
- Addresses on a maintained list of common personal providers, including Gmail,
  Outlook/Hotmail, Yahoo, and iCloud, receive 200 pages.

The eligibility decision, normalized domain, rule version, grant amount, and
decision timestamp are stored for auditability. Classification runs only while
creating the first grant; later rule-list changes do not silently alter existing
balances.

The product promises a verified-email trial, not a perfect real-world-person
deduplication system. The design prevents a single PDFAccess account or verified
email from receiving repeated grants. Broader anti-abuse controls may add rate
limits and risk review without changing the ledger model.

## Trial Ledger and Job Lifecycle

The database is the authority for page balances. A profile exposes four values:

- `granted_pages`: the immutable initial allowance.
- `consumed_pages`: pages charged for successful remediations.
- `reserved_pages`: pages held by accepted in-progress jobs.
- `remaining_pages`: granted minus consumed minus reserved.

Balances are derived from an append-only ledger or equivalently auditable ledger
records rather than browser state.

### Accepted job

1. The backend validates the file signature, MIME type, file size, and PDF
   readability.
2. The backend determines the authoritative PDF page count.
3. Inside one database transaction, it locks the relevant balance, compares the
   page count with the remaining balance, creates the job, and records a
   reservation.
4. The existing remediation pipeline processes the PDF.
5. On success, a transaction converts the reservation to consumed pages and
   records the output artifacts.

### Rejected job

If the PDF contains more pages than the remaining balance, the complete job is
rejected before remediation. The response states the PDF page count and the
remaining allowance. PDFAccess does not produce partially remediated PDFs.

### Failed or abandoned job

Pipeline failure, timeout, cancellation, or a recovery process identifying an
abandoned job releases its reservation exactly once. Retried recovery operations
must be idempotent. The user receives a safe error and retains the affected page
allowance.

Atomic reservation prevents simultaneous jobs from spending the same remaining
pages. Idempotency keys prevent duplicate submissions or network retries from
creating multiple charges.

## User Experience and Rebrand

The uncommitted `code.html` prototype is the visual and content starting point
for the public landing page. It will be converted into maintainable React
components without overwriting or deleting the prototype source. The owner can
iterate on the landing page after the initial release.

The trial journey contains:

- Public PDFAccess landing page.
- Explanation of the 200-page personal and 400-page organization allowances.
- Email submission and magic-link confirmation.
- Check-email, expired-link, invalid-link, and resend-link states.
- Verified-user remediation workspace using the current dashboard and pipeline.
- Persistent granted, used, reserved, and remaining page information.
- Clear whole-job rejection when a PDF exceeds the remaining balance.
- Processing, failure, completion, and retry states.
- Private downloads for the remediated PDF and remediation report.
- Account area with verified email, trial usage, email preferences, support, and
  sign-out.

`support@pdfaccess.org` is the consistent support and reply-to address. Users are
invited to ask questions by replying to product emails or using the support link.

All user-facing product-name references to AccessPDF or the generic WCAG
platform become **PDFAccess** in the frontend, backend descriptions, page titles,
metadata, reports, and email templates. References to WCAG remain when describing
the accessibility standard, rules, or conformance results.

The testing deployment also adopts the PDFAccess product name but continues to
open directly into its testing workspace.

## Email Design

Resend provides delivery for `pdfaccess.org`. Domain authentication records must
be verified before production sending. `support@pdfaccess.org` is the visible
reply-to address. The exact sender address may use a dedicated authenticated
subdomain to protect the reputation of the primary mailbox.

### Transactional messages

- Magic-link verification.
- Trial activation and allowance confirmation.
- Remediation completion or failure.
- Security or account notices.

Transactional delivery remains available to users who unsubscribe from
promotions when it is necessary to provide the requested service or protect the
account.

### Promotional sequence

Every verified user who is not suppressed receives a short activation sequence:

1. Welcome and start-trial message.
2. First-upload reminder for users who have not started.
3. Remaining-pages reminder encouraging continued trial use.
4. Support invitation encouraging replies and questions.

Messages should reflect current account state. For example, a first-upload
reminder is skipped after the first accepted job. The sequence does not advertise
an undefined paid plan.

Each promotional message includes accurate PDFAccess identification, the
configured valid postal address, and a one-click unsubscribe mechanism. The
postal address is a required deployment setting; promotional sending fails
closed until it is configured. Unsubscribes, hard bounces, and complaints create
suppression records that stop future promotions. Email-event processing is
idempotent, and campaign records prevent scheduler retries from sending the same
message twice.

The initial campaign targets verified users of the U.S.-focused release. Any
future geographic expansion requires a separate review of consent and messaging
requirements before campaigns are enabled for the new audience.

## Data and File Handling

The PDFAccess Supabase project stores:

- Verified user profiles and eligibility decisions.
- Trial grants and ledger entries.
- Job state and idempotency records.
- Artifact metadata and ownership.
- Email schedule, delivery events, preferences, and suppressions.

Original PDFs, remediated PDFs, and reports use private PDFAccess-only storage
buckets. The browser never receives storage service credentials.

For each job, the backend:

1. Retrieves the input into an isolated temporary job directory.
2. Runs the existing remediation pipeline against local temporary paths.
3. Uploads successful outputs to the user's private trial storage namespace.
4. Removes temporary files whether the job succeeds or fails.

Downloads use short-lived signed URLs or authenticated streaming endpoints.
Row-level security and backend ownership checks restrict each user to their own
records and artifacts.

The existing 12-hour runtime artifact-retention behavior remains the default for
the initial release. Retention jobs operate independently in each environment.
Testing artifacts never enter trial storage or trial retention jobs.

## Security and Failure Handling

- Supabase service-role and Resend API keys remain backend-only.
- Trial startup rejects unsafe authentication bypass, testing-mode storage, or
  missing trial identifiers.
- Environment validation compares explicit deployment mode and project/resource
  identifiers rather than relying on the request hostname.
- Upload validation includes PDF signature, safe filename handling, configured
  size limits, readability, and page counting.
- Rate limits protect magic-link requests, uploads, job creation, and downloads.
- Trial balance changes and job transitions are auditable.
- Public errors are actionable but do not expose filesystem paths, credentials,
  provider responses, or stack traces.
- Provider outages leave jobs recoverable and reservations releasable.
- Background reconciliation identifies stale reservations and incomplete email
  events without duplicating charges or messages.

## Verification Strategy

### Automated tests

- Personal, `.edu`, `.org`, and company-domain classification.
- Exactly-once 200/400-page grant creation.
- Verified and unverified access boundaries.
- Concurrent reservation and overspending prevention.
- Whole-job rejection above the remaining balance.
- Successful charge conversion and failed-job reservation release.
- Duplicate request and recovery idempotency.
- User-to-user record and artifact isolation.
- Trial-to-testing deployment resource isolation.
- Valid, expired, reused, and malformed magic-link states.
- Unsubscribe, bounce, complaint, and suppression behavior.
- Duplicate promotional-send prevention.
- Existing remediation API, PDF, report, and download regression suites.
- Product-name checks for frontend, API descriptions, reports, metadata, and
  emails.

### Release checks

The trial release must exercise the complete browser journey: registration,
magic-link verification, correct grant assignment, upload, page reservation,
remediation, balance update, and private downloads.

A separate testing-site check confirms that
`wcag-remediation.vercel.app` still opens the direct testing workspace and uses
only testing resources. Cross-environment probes must fail.

Both deployments require build and existing pipeline test success. A failed
deployment remains isolated to its own Vercel project.

## Required Account Configuration

Implementation will include an operator guide for:

- Creating separate Supabase projects and private storage resources.
- Applying database migrations and row-level security policies.
- Creating and authenticating the Resend sending domain or subdomain.
- Publishing the required DNS records for `pdfaccess.org`.
- Connecting `pdfaccess.org` to the trial Vercel project.
- Maintaining `wcag-remediation.vercel.app` as the separate testing project.
- Assigning distinct environment variables and secrets to each project.
- Configuring the sender identity, required postal address, and
  `support@pdfaccess.org` reply-to address.
- Running delivery, authentication, storage-isolation, and end-to-end release
  checks.

Account-console operations and secret values require owner access and are not
stored in the repository.

## Acceptance Criteria

The design is successfully implemented when:

1. `pdfaccess.org` presents the prototype-derived PDFAccess landing page and
   passwordless registration.
2. Only verified users can enter the trial workspace.
3. Eligible users receive exactly one auditable 200- or 400-page lifetime grant.
4. The server rejects whole PDFs that exceed the remaining balance and charges
   only successful remediations.
5. Concurrent or retried jobs cannot overspend or double-charge the balance.
6. Trial users can privately download successful remediated PDFs and reports.
7. Verified, non-suppressed users receive idempotent activation and support
   emails with working unsubscribe controls.
8. User-facing product references consistently say PDFAccess while WCAG standard
   terminology remains accurate.
9. The two Vercel deployments share pipeline source updates but no runtime files,
   databases, storage, credentials, sessions, logs, or deployment failures.
10. The testing deployment remains openly accessible until its later lockdown is
    explicitly enabled.
