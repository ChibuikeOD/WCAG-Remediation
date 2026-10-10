# Codex Cloud setup for PDFAccess

This repository can run in Codex Cloud without the development computer remaining online. Cloud tasks check out a committed branch from GitHub, so local-only and uncommitted files are not available to them.

## Create the environment

1. In Codex, connect the GitHub repository `ChibuikeOD/WCAG-Remediation`.
2. Create a cloud environment for the repository.
3. Set Python to 3.12 and Node.js to 20 or newer.
4. Use this setup command:

   ```bash
   bash scripts/codex-cloud-setup.sh
   ```

5. Leave agent internet access disabled unless a task specifically needs approved external documentation or services. The setup phase has network access for installing dependencies.
6. Start the cloud task from the pushed branch or commit that contains the desired project state.

## Credentials

No live credentials are required for the standard backend and frontend test suites. Do not copy the local `.env` file into the repository.

Codex Cloud secrets are intended for the setup phase and are removed before the agent phase. Use them only for setup-time needs such as access to a private package registry. Avoid giving ordinary coding tasks production Supabase, Stripe, Resend, Gemini, or DeepSeek credentials; tests should mock those integrations.

The following public or non-sensitive configuration may be added as cloud environment variables only when a task needs it:

- `DEPLOYMENT_MODE=testing`
- `DISABLE_AUTH=true`
- `DISABLE_LAYOUTLM=true`
- `PDF_UNICODE_LLM_ENABLED=false`
- `PLAYWRIGHT_HEADLESS=true`

## Verify a cloud checkout

```bash
uv run --project backend pytest backend/tests -q
npm --prefix frontend test -- --run
npm --prefix frontend run build
```

Some full PDF remediation paths also require Java, QPDF, Tesseract, Chromium, and the native PDF/UA helper. The setup script installs or builds those components.

## Working from a phone

After starting the task with the cloud environment, the computer may be shut down. Open the same task in the ChatGPT mobile app to review progress, send follow-up instructions, and approve actions.
