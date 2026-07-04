import pytest
from pydantic import ValidationError

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
