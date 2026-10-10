# PDFAccess deployment readiness and desktop releases

PDFAccess has a working shared PDF remediation engine and now has a Windows
application that runs it locally. Public deployment still needs dependency
updates, infrastructure configuration, distribution licensing, and a production
smoke test. The software release pipeline records those checks and blocks release
preparation when dependency audits fail.

## Product boundaries

The web product offers authenticated uploads, private outputs, trial page quotas,
and optional cloud AI. The desktop product runs PDF analysis, English OCR, native
tagging, metadata repair, deterministic Unicode repair, and structural fixes
without an account or network connection. Both use `PDFRemediator.fix_all`.

Desktop files are never sent to PDFAccess or an AI provider. Cloud credentials and
AI flags are removed or disabled before the engine loads; Python network requests
are rejected. Java executes the bundled local extraction CLI. This is an
application privacy boundary, not an operating-system sandbox for native code.
Managed installations can additionally block outbound network access with their
normal endpoint policy. Files saved into a synced folder remain subject to the
user's sync and backup settings.

The desktop app produces a repaired PDF, a human-readable PDF report, and a JSON
report with before/after findings. It preserves the original, isolates each run in
a separate output folder, and removes temporary working copies on completion or
failure. It does not generate AI figure descriptions or guess ambiguous glyphs.
Reading order, tables, descriptions, and remaining findings require human review;
automated output is not a compliance certificate.

## Cloud deployment

Use the container API on Render and the React frontend on Vercel for the complete
remediation workload. The root Vercel configuration currently bundles rules only;
its build does not install Java or compile the native tagging helper. Do not use
that configuration as evidence that full PDF remediation works in production.

The Dockerfile now uses Python 3.12 and the frozen backend lock, installs the Java,
QPDF, OCR, and browser dependencies, compiles the native helper, and runs as an
unprivileged user. Explicit source copies and `.dockerignore` prevent local env
files, PDFs, databases, model caches, and generated outputs from entering the image.
The container defaults to a writable local database for development; production
uses the dedicated remote database configured by the deployment.

The Render blueprint now requires authenticated trial mode, exact CORS for
`https://pdfaccess.org`, a dedicated database, and private storage configuration.
It deploys only after CI checks pass and probes `/health/ready`. Readiness checks
the database and required tagging, OCR, and QPDF tools. `/health` remains a basic
liveness endpoint. Render's [blueprint reference](https://render.com/docs/blueprint-spec)
documents the CI-gated deploy and health-check fields.

Configure Vercel with **Root Directory `frontend`**, the Vite preset, and `dist`
output for this deployment topology. Set `VITE_API_URL` to the container API HTTPS
origin, `VITE_DEPLOYMENT_MODE=trial`, the canonical app origin, and the public auth
settings from the existing trial env example. `frontend/vercel.json` provides the
SPA rewrite so `/login`, `/remediate`, and auth callbacks load the app. Configure Vercel
Deployment Checks for the Quality and Dependency security workflows before
promoting production. Keep the existing testing deployment separate.

Keep one API process/instance initially. Remediation still runs within the request;
page quotas have leases and heartbeats, but there is no general persisted worker
queue. Before scaling to multiple workers or processing large batches, move jobs
to a durable queue, cap concurrency, and expose persisted progress/retry state.
The current limits are 50 MB and 100 pages; benchmark the largest allowed PDF
against the chosen CPU/RAM and request timeout before inviting users. The Render
template grants up to 300 seconds for shutdown so an update can drain requests.

## Release blockers

| Item | Current evidence | Required before public launch |
| --- | --- | --- |
| Dependencies | Local audit found 104 advisory findings across 15 installed Python packages and 23 frontend dependency findings, including 15 high and 2 critical | Upgrade affected dependencies, refresh their locks, rerun both audits and the full tests; audit counts can change as advisories are published |
| Distribution license | README claims MIT but no root LICENSE was found; PyMuPDF has AGPL/commercial terms | Choose and document compatible distribution terms and corresponding source obligations, or the required commercial license; notices alone are insufficient |
| Windows signing | Evaluation ZIP is unsigned | Sign public executables with the organization's trusted Windows code-signing identity and verify signatures before packaging |
| Windows backend tests | 567 assertions pass and 10 tests skip, then the Python process exits with access violation `0xC0000005`; the existing suite alone reproduces it after 554 assertions pass | Diagnose native-library shutdown and require a clean Windows suite exit; the release workflow enforces this |
| Production storage and auth | Blueprint now requires private storage and remote database settings | Configure those settings, apply the existing migrations, verify private buckets and tenant ownership, and test auth callbacks |
| Operations | Request-bound processing can be interrupted during deployments | Benchmark maximum inputs, configure error/latency/resource monitoring, and test interruption recovery and retention |
| Live validation | No production services were changed; Docker Desktop's Linux engine was unavailable locally | Run the container CI job and trial smoke tests in staging, then promote the tested deployment |

The Python audit findings include FastAPI/Starlette, multipart parsing, Pillow,
JWT, font and XML processing, and related packages. The frontend findings include
the Vite/Vitest toolchain, routing, and CSS build dependencies. Local scanner output
is under `.artifacts`; the CI security workflow retains machine-readable reports.
Dependencies were not broadly upgraded in this change because the existing engine
and in-progress work need compatibility checks around those upgrades.

Confirm the exact licensing obligations for the intended distribution using
[PyMuPDF's license documentation](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright).
This evaluation build is suitable for local testing; public publishing remains a
separate release step.

## Software update pipeline

1. Open a pull request. `Quality` runs the backend suite, frontend tests/build,
   and a Docker build/readiness smoke test without provider credentials.
   `Dependency security` audits locked Python and npm dependencies.
2. Require the Quality backend, frontend, container, and Dependency security audit
   checks in branch protection. Restrict the `desktop-release` GitHub environment
   to protected release tags and configure the release reviewers.
3. Merge reviewed changes. Render's `checksPass` setting waits for CI. Vercel
   previews can be reviewed independently; require deployment checks and smoke
   tests before promoting the production build.
4. Push a reviewed semantic version tag such as `v1.0.1`. The Windows release
   workflow reruns Quality, builds the current native sources on Windows, fetches
   checksummed Java/QPDF/OCR assets, and freezes the app with PyInstaller.
5. The packaged executable must pass local analysis, native tagging, OCR, GUI
   initialization, network-blocking, and report tests. The full backend suite must
   also exit cleanly on Windows. The workflow uploads the
   ZIP, `SHA256SUMS.txt`, and `desktop-release.json` as build artifacts. No PDFs,
   test inputs, credentials, or user documents are included.
6. Successful security and Windows compatibility checks permit creation of a **draft** GitHub release. Its
   publication is a separate distribution review step, including signing and
   licensing. Publish only after the release blockers are resolved.
7. Set `VITE_DESKTOP_DOWNLOAD_URL` to that release's HTTPS ZIP asset URL and rebuild
   the frontend. Before a URL is configured, the landing page presents availability
   information rather than a broken download link.

Users install updates by closing the app and extracting the new ZIP into a
separate directory. Outputs are outside the app directory. The desktop app makes
no automatic update checks and does not modify its executable while processing.
Release checksums protect against download corruption; a signed executable and
the trusted publishing channel establish publisher identity. GitHub's
[workflow artifact documentation](https://docs.github.com/en/actions/concepts/workflows-and-actions/workflow-artifacts)
describes the build-artifact retention mechanism used here.

## Build and verify locally

Install Python 3.12 and Visual Studio C++ Build Tools on Windows, then run from
the repository root:

```powershell
uv run --frozen --project backend --with pyinstaller==6.22.3 --with cmake==3.31.6 python scripts/build_desktop.py --version 1.0.0
```

The build produces `dist/PDFAccess-1.0.0-windows-x64.zip`. Extract the entire ZIP
and run `PDFAccess/PDFAccess.exe`. The README inside the download explains usage,
privacy, manual updates, and the CLI. Java, QPDF, Python, and English OCR data are
bundled; users do not install them separately. PyInstaller's
[packaging documentation](https://www.pyinstaller.org/en/stable/usage.html)
describes the portable directory layout used by this download.

Run the backend tests from the repository root in testing mode with a disposable
SQLite database and empty provider credentials. Run `npm --prefix frontend test
-- --run` and `npm --prefix frontend run build`. Validate the deployment examples
with `python scripts/validate_deployment.py deployment/trial.env.example
deployment/testing.env.example`. Build the Docker image and check `/health/ready`
where a Linux Docker engine is available. Do not commit build outputs or `.artifacts`.

Local verification: 55 frontend tests and the production build passed. All 567
backend assertions passed with 10 skips, but the Windows process crashed during
native shutdown. The same crash occurs with the new desktop/readiness tests
excluded. Targeted desktop, report, and readiness tests exit cleanly, and the
packaged app's tagging/OCR/UI/network/report smoke test exits successfully.
