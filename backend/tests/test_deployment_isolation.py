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
