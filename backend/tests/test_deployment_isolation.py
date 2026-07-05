from pathlib import Path

import pytest

from scripts.validate_deployment import (
    DeploymentValidationError,
    load_env_file,
    validate_deployment_pair,
)


ROOT = Path(__file__).resolve().parents[2]
TRIAL_ENV = ROOT / "deployment" / "trial.env.example"
TESTING_ENV = ROOT / "deployment" / "testing.env.example"


def test_example_environments_are_isolated_and_valid():
    trial = load_env_file(TRIAL_ENV)
    testing = load_env_file(TESTING_ENV)

    validate_deployment_pair(trial, testing)

    assert trial["DEPLOYMENT_MODE"] == "trial"
    assert testing["DEPLOYMENT_MODE"] == "testing"
    assert trial["DISABLE_AUTH"].lower() == "false"
    assert testing["DISABLE_AUTH"].lower() == "true"
    assert trial["SUPABASE_PROJECT_REF"] != testing["SUPABASE_PROJECT_REF"]
    assert trial["SUPABASE_ORIGINALS_BUCKET"] != testing["SUPABASE_ORIGINALS_BUCKET"]
    assert trial["SUPABASE_RESULTS_BUCKET"] != testing["SUPABASE_RESULTS_BUCKET"]
    assert trial["DATABASE_URL"] != testing["DATABASE_URL"]
    assert trial["ARTIFACT_STORAGE_ROOT"] != testing["ARTIFACT_STORAGE_ROOT"]


def test_trial_environment_rejects_auth_bypass():
    trial = load_env_file(TRIAL_ENV)
    testing = load_env_file(TESTING_ENV)
    trial["DISABLE_AUTH"] = "true"

    with pytest.raises(DeploymentValidationError, match="DISABLE_AUTH"):
        validate_deployment_pair(trial, testing)


@pytest.mark.parametrize(
    "shared_identifier",
    [
        "DATABASE_URL",
        "SUPABASE_PROJECT_REF",
        "SUPABASE_ORIGINALS_BUCKET",
        "SUPABASE_RESULTS_BUCKET",
        "ARTIFACT_STORAGE_ROOT",
    ],
)
def test_validator_rejects_shared_database_or_storage_identifiers(shared_identifier):
    trial = load_env_file(TRIAL_ENV)
    testing = load_env_file(TESTING_ENV)
    testing[shared_identifier] = trial[shared_identifier]

    with pytest.raises(DeploymentValidationError, match=shared_identifier):
        validate_deployment_pair(trial, testing)


def test_validator_rejects_same_database_with_different_credentials():
    trial = load_env_file(TRIAL_ENV)
    testing = load_env_file(TESTING_ENV)
    testing["DATABASE_URL"] = (
        "postgresql://different_user:different_password@"
        "trial-db.example.invalid:5432/pdfaccess_trial"
    )

    with pytest.raises(DeploymentValidationError, match="DATABASE_URL"):
        validate_deployment_pair(trial, testing)


@pytest.mark.parametrize(
    "testing_database_url",
    [
        "postgresql://different_user:different_password@trial-db.example.invalid/pdfaccess_trial",
        "postgresql+psycopg://different_user:different_password@trial-db.example.invalid:5432/pdfaccess_trial",
    ],
)
def test_validator_rejects_same_database_with_driver_or_default_port_variants(
    testing_database_url,
):
    trial = load_env_file(TRIAL_ENV)
    testing = load_env_file(TESTING_ENV)
    testing["DATABASE_URL"] = testing_database_url

    with pytest.raises(DeploymentValidationError, match="DATABASE_URL"):
        validate_deployment_pair(trial, testing)


@pytest.mark.parametrize(
    "key,bad_value",
    [
        ("PUBLIC_APP_ORIGIN", "https://wcag-remediation.vercel.app"),
        ("CORS_ORIGINS_LIST", "https://pdfaccess.org,https://wcag-remediation.vercel.app"),
    ],
)
def test_validator_rejects_trial_origins_pointing_at_testing_domain(key, bad_value):
    trial = load_env_file(TRIAL_ENV)
    testing = load_env_file(TESTING_ENV)
    trial[key] = bad_value

    with pytest.raises(DeploymentValidationError, match=key):
        validate_deployment_pair(trial, testing)


@pytest.mark.parametrize(
    "bad_cors",
    [
        "https://pdfaccess.org,https://evil.example",
        "https://pdfaccess.org,http://localhost:3000",
        "http://pdfaccess.org",
    ],
)
def test_validator_rejects_trial_cors_origins_outside_exact_public_origin(bad_cors):
    trial = load_env_file(TRIAL_ENV)
    testing = load_env_file(TESTING_ENV)
    trial["CORS_ORIGINS_LIST"] = bad_cors

    with pytest.raises(DeploymentValidationError, match="CORS_ORIGINS_LIST"):
        validate_deployment_pair(trial, testing)


@pytest.mark.parametrize("key", ["PUBLIC_SITE_URL", "PUBLIC_APP_ORIGIN"])
def test_validator_rejects_trial_public_origin_with_insecure_scheme_or_path(key):
    trial = load_env_file(TRIAL_ENV)
    testing = load_env_file(TESTING_ENV)
    trial[key] = "http://pdfaccess.org/some/path?x=1"

    with pytest.raises(DeploymentValidationError, match=key):
        validate_deployment_pair(trial, testing)


def test_validator_rejects_trial_cors_allow_all_bypass():
    trial = load_env_file(TRIAL_ENV)
    testing = load_env_file(TESTING_ENV)
    trial["CORS_ALLOW_ALL"] = "true"

    with pytest.raises(DeploymentValidationError, match="CORS_ALLOW_ALL"):
        validate_deployment_pair(trial, testing)


def test_runtime_cors_does_not_allow_vercel_wildcard_regex():
    from backend.main import app
    from fastapi.middleware.cors import CORSMiddleware

    cors = next(
        middleware
        for middleware in app.user_middleware
        if middleware.cls is CORSMiddleware
    )

    assert cors.kwargs.get("allow_origin_regex") is None
