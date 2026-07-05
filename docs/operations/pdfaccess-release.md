# PDFAccess release runbook

This runbook keeps the public free-trial deployment and the direct testing deployment separate while both continue to use the same remediation source tree.

## Deployment split

- Trial project: create a dedicated Vercel project for `pdfaccess.org`.
- Testing project: keep a separate Vercel project for `wcag-remediation.vercel.app`.
- Import the same Git repository into both projects, but configure environment variables at the project level. Do not use shared team/global secrets for database URLs, Supabase keys, storage buckets, or auth bypass flags.
- Apply `deployment/trial.env.example` only to the trial project and `deployment/testing.env.example` only to the testing project.
- Run `python scripts/validate_deployment.py deployment/trial.env.example deployment/testing.env.example` before copying values into Vercel.

## Trial project: `pdfaccess.org`

- `DEPLOYMENT_MODE=trial`.
- `DISABLE_AUTH=false`.
- Domain assignment: `pdfaccess.org` only.
- Use a dedicated Supabase project, dedicated database URL, dedicated private originals/results buckets, and backend-only service credentials.
- Configure Supabase Auth magic links and email confirmation before inviting testers. Only verified users receive trial quota or promotional/question emails.
- Configure Resend as the Supabase SMTP provider:
  - verified sending domain: `pdfaccess.org`;
  - sender/reply-to mailbox: `support@pdfaccess.org`;
  - webhook endpoint: the trial deployment only;
  - required physical postal address: enter the business mailing address in Resend/compliance settings, never in tracked files.

## Testing project: `wcag-remediation.vercel.app`

- `DEPLOYMENT_MODE=testing`.
- Keep `DISABLE_AUTH=true` while direct external testing remains open.
- Domain assignment: `wcag-remediation.vercel.app` only.
- Use a separate testing Supabase project/database/storage identifiers from trial, even if testing primarily uses local artifact storage.
- When you notify external testers that the open testing site is being locked down, change testing to `DISABLE_AUTH=false`, redeploy, and run the smoke tests again.

## Supabase setup

For each Supabase project:

1. Apply the database migrations for users, uploaded files, reports, trial accounts, ledger entries, remediation jobs, and email subscriptions.
2. Enable row-level security on trial-facing tables and storage buckets.
3. Create private storage buckets matching that project’s env file.
4. Store service-role keys only in the backend/Vercel project environment.
5. Confirm `SUPABASE_URL` host matches `SUPABASE_PROJECT_REF`.

## Smoke tests

Run these in a preview deployment before promoting:

- Trial personal-domain registration confirms email, grants 200 pages, remediates once, and returns private downloads.
- Trial `.edu`, `.org`, or company/institution email confirms email, grants 400 pages, and cannot claim a second free trial.
- Trial over-limit remediation returns a clear 409 and does not debit pages.
- Trial failed remediation releases reserved pages.
- Trial duplicate successful remediation replays from stored artifacts without rerunning or double-charging.
- Testing deployment remains directly accessible while `DISABLE_AUTH=true` and does not write to trial Supabase identifiers.
- Promotional/question email sending targets verified users only and includes unsubscribe handling where required.

## Rollback

- Keep the previous Vercel production deployment ID for both projects before promoting.
- If trial fails, roll back only the `pdfaccess.org` project; do not roll back testing unless its own smoke tests fail.
- If a Supabase migration must be rolled back, pause trial traffic first, preserve ledger/job tables for audit, and restore artifacts from the matching project bucket only.

## Secret handling

- Never commit live keys, database passwords, Resend API keys, postal addresses, or Supabase service-role secrets.
- Keep trial/testing credentials different even when they point at placeholder infrastructure.
- Treat `support@pdfaccess.org` as the public support/reply-to mailbox, not as a secret.
