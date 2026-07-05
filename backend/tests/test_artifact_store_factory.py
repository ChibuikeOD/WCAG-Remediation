from pathlib import Path

from pydantic import SecretStr

from backend.config import Settings
from backend.storage import LocalArtifactStore, SupabaseArtifactStore, create_artifact_store


def test_factory_builds_local_store_for_testing_with_explicit_root(tmp_path: Path) -> None:
    root = tmp_path / "private-artifacts"
    config = Settings(
        DEPLOYMENT_MODE="testing",
        ARTIFACT_STORAGE_ROOT=root,
        _env_file=None,
    )

    store = create_artifact_store(config)

    assert isinstance(store, LocalArtifactStore)
    assert store.root == root.resolve()
    with store as entered:
        assert entered is store


def test_factory_builds_supabase_store_from_all_trial_settings() -> None:
    config = Settings(
        DEPLOYMENT_MODE="trial",
        DISABLE_AUTH=False,
        SUPABASE_URL="https://trial-project.supabase.co",
        SUPABASE_PUBLISHABLE_KEY="publishable",
        SUPABASE_SECRET_KEY=SecretStr("backend-secret"),
        SUPABASE_PROJECT_REF="trial-project",
        SUPABASE_ORIGINALS_BUCKET="originals",
        SUPABASE_RESULTS_BUCKET="results",
        SUPABASE_STORAGE_CONNECT_TIMEOUT_SECONDS=1.0,
        SUPABASE_STORAGE_READ_TIMEOUT_SECONDS=2.0,
        SUPABASE_STORAGE_WRITE_TIMEOUT_SECONDS=3.0,
        SUPABASE_STORAGE_POOL_TIMEOUT_SECONDS=4.0,
        SUPABASE_STORAGE_SIGNED_URL_SECONDS=123,
        _env_file=None,
    )

    store = create_artifact_store(config)

    assert isinstance(store, SupabaseArtifactStore)
    assert store._secret == "backend-secret"
    assert store._originals_bucket == "originals"
    assert store._results_bucket == "results"
    assert store._signed_url_expires_in_seconds == 123
    assert store._client.timeout.connect == 1.0
    assert store._client.timeout.read == 2.0
    assert store._client.timeout.write == 3.0
    assert store._client.timeout.pool == 4.0
    store.close()
