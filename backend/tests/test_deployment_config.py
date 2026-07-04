import pytest
from pydantic import SecretStr, ValidationError

from backend.config import Settings


TRIAL_SUPABASE_SETTINGS = {
    "SUPABASE_URL": "https://trial-project.supabase.co",
    "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_example",
    "SUPABASE_SECRET_KEY": "sb_secret_example",
    "SUPABASE_PROJECT_REF": "trial-project",
    "SUPABASE_ORIGINALS_BUCKET": "trial-originals",
    "SUPABASE_RESULTS_BUCKET": "trial-results",
}


def test_trial_mode_rejects_auth_bypass():
    with pytest.raises(ValidationError, match="DISABLE_AUTH"):
        Settings(
            DEPLOYMENT_MODE="trial",
            DISABLE_AUTH=True,
            _env_file=None,
            **TRIAL_SUPABASE_SETTINGS,
        )


def test_testing_mode_allows_current_bypass():
    value = Settings(
        DEPLOYMENT_MODE="testing",
        DISABLE_AUTH=True,
        _env_file=None,
    )

    assert value.DEPLOYMENT_MODE == "testing"


def test_trial_mode_accepts_complete_secure_configuration():
    value = Settings(
        DEPLOYMENT_MODE="trial",
        DISABLE_AUTH=False,
        _env_file=None,
        **TRIAL_SUPABASE_SETTINGS,
    )

    assert isinstance(value.SUPABASE_SECRET_KEY, SecretStr)
    assert value.SUPABASE_SECRET_KEY.get_secret_value() == "sb_secret_example"
    assert "sb_secret_example" not in repr(value)


def test_trial_validation_error_hides_supabase_secret():
    secret = "never-leak-this-secret"

    with pytest.raises(ValidationError) as exc_info:
        Settings(
            DEPLOYMENT_MODE="trial",
            DISABLE_AUTH=True,
            _env_file=None,
            SUPABASE_SECRET_KEY=secret,
        )

    assert secret not in str(exc_info.value)


@pytest.mark.parametrize("missing_setting", TRIAL_SUPABASE_SETTINGS)
def test_trial_mode_rejects_missing_supabase_setting(missing_setting):
    supplied_settings = TRIAL_SUPABASE_SETTINGS | {missing_setting: None}

    with pytest.raises(
        ValidationError,
        match=rf"Trial mode requires Supabase settings:.*{missing_setting}",
    ):
        Settings(
            DEPLOYMENT_MODE="trial",
            DISABLE_AUTH=False,
            _env_file=None,
            **supplied_settings,
        )
