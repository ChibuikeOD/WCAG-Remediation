"""Validate that PDFAccess trial and testing deployments are isolated.

The trial and testing sites must be two separate Vercel project imports from
the same repository. Configure these values as project-level environment
variables in each Vercel project; do not rely on shared/global secrets for
database URLs, Supabase storage identifiers, or auth-bypass flags.

Usage:
    python scripts/validate_deployment.py deployment/trial.env.example deployment/testing.env.example
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
from urllib.parse import urlsplit


class DeploymentValidationError(ValueError):
    """Raised when deployment configuration is unsafe or incomplete."""


REQUIRED_KEYS = {
    "APP_NAME",
    "DEPLOYMENT_MODE",
    "DISABLE_AUTH",
    "SECRET_KEY",
    "PUBLIC_SITE_URL",
    "PUBLIC_APP_ORIGIN",
    "PRIMARY_DOMAIN",
    "DATABASE_URL",
    "ARTIFACT_STORAGE_ROOT",
    "SUPABASE_PROJECT_REF",
    "SUPABASE_URL",
    "SUPABASE_PUBLISHABLE_KEY",
    "SUPABASE_SECRET_KEY",
    "SUPABASE_ORIGINALS_BUCKET",
    "SUPABASE_RESULTS_BUCKET",
    "RESEND_API_KEY",
    "RESEND_FROM_EMAIL",
    "RESEND_REPLY_TO",
    "SUPPORT_EMAIL",
}

SHARED_FORBIDDEN_KEYS = (
    "DATABASE_URL",
    "SUPABASE_PROJECT_REF",
    "SUPABASE_URL",
    "SUPABASE_ORIGINALS_BUCKET",
    "SUPABASE_RESULTS_BUCKET",
    "ARTIFACT_STORAGE_ROOT",
    "SECRET_KEY",
)


def load_env_file(path: str | Path) -> dict[str, str]:
    """Load a simple dotenv file without expanding variables or touching env."""
    env_path = Path(path)
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        env_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            raise DeploymentValidationError(
                f"{env_path}:{line_number} is not KEY=VALUE"
            )
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key or not re.fullmatch(r"[A-Z0-9_]+", key):
            raise DeploymentValidationError(
                f"{env_path}:{line_number} has invalid key {key!r}"
            )
        values[key] = value
    return values


def _bool(value: str, key: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise DeploymentValidationError(f"{key} must be true or false")


def _require(env: dict[str, str], label: str) -> None:
    missing = sorted(key for key in REQUIRED_KEYS if not env.get(key, "").strip())
    if missing:
        raise DeploymentValidationError(
            f"{label} is missing required keys: {', '.join(missing)}"
        )


def _validate_supabase(env: dict[str, str], label: str) -> None:
    project_ref = env["SUPABASE_PROJECT_REF"]
    if re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", project_ref) is None:
        raise DeploymentValidationError(f"{label} SUPABASE_PROJECT_REF is invalid")
    parsed = urlsplit(env["SUPABASE_URL"])
    expected_host = f"{project_ref}.supabase.co"
    if (
        parsed.scheme != "https"
        or parsed.netloc != expected_host
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise DeploymentValidationError(
            f"{label} SUPABASE_URL must be https://{expected_host}"
        )
    if env["SUPABASE_ORIGINALS_BUCKET"] == env["SUPABASE_RESULTS_BUCKET"]:
        raise DeploymentValidationError(
            f"{label} SUPABASE_ORIGINALS_BUCKET and SUPABASE_RESULTS_BUCKET must differ"
        )


def validate_deployment_pair(
    trial: dict[str, str], testing: dict[str, str]
) -> None:
    """Fail closed if trial/testing identifiers are not deployment-isolated."""
    _require(trial, "trial")
    _require(testing, "testing")

    if trial["DEPLOYMENT_MODE"] != "trial":
        raise DeploymentValidationError("trial DEPLOYMENT_MODE must be trial")
    if testing["DEPLOYMENT_MODE"] != "testing":
        raise DeploymentValidationError("testing DEPLOYMENT_MODE must be testing")
    if _bool(trial["DISABLE_AUTH"], "trial DISABLE_AUTH"):
        raise DeploymentValidationError("trial DISABLE_AUTH must be false")
    if not _bool(testing["DISABLE_AUTH"], "testing DISABLE_AUTH"):
        raise DeploymentValidationError(
            "testing DISABLE_AUTH should stay true until tester lockdown"
        )

    if trial["PRIMARY_DOMAIN"] != "pdfaccess.org":
        raise DeploymentValidationError("trial PRIMARY_DOMAIN must be pdfaccess.org")
    if testing["PRIMARY_DOMAIN"] != "wcag-remediation.vercel.app":
        raise DeploymentValidationError(
            "testing PRIMARY_DOMAIN must be wcag-remediation.vercel.app"
        )
    if "wcag-remediation.vercel.app" in trial["PUBLIC_SITE_URL"]:
        raise DeploymentValidationError("trial PUBLIC_SITE_URL must not use testing domain")
    if "pdfaccess.org" in testing["PUBLIC_SITE_URL"]:
        raise DeploymentValidationError("testing PUBLIC_SITE_URL must not use trial domain")

    for key in SHARED_FORBIDDEN_KEYS:
        if trial[key] == testing[key]:
            raise DeploymentValidationError(
                f"{key} must be different between trial and testing"
            )

    _validate_supabase(trial, "trial")
    _validate_supabase(testing, "testing")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trial_env", type=Path)
    parser.add_argument("testing_env", type=Path)
    args = parser.parse_args()

    trial = load_env_file(args.trial_env)
    testing = load_env_file(args.testing_env)
    validate_deployment_pair(trial, testing)
    print("PDFAccess deployment examples are isolated and valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
