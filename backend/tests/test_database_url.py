from backend.database_url import normalize_database_url


def test_normalize_database_url_uses_transaction_pooler_with_unescaped_password():
    from sqlalchemy.engine import make_url

    result = normalize_database_url(
        "postgresql://postgres:p@ss&word@db.exampleproject.supabase.co:5432/postgres",
        pooler_host="aws-1-us-west-2.pooler.supabase.com",
        project_ref="exampleproject",
    )
    url = make_url(result)

    assert url.host == "aws-1-us-west-2.pooler.supabase.com"
    assert url.port == 6543
    assert url.username == "postgres.exampleproject"
    assert url.password == "p@ss&word"
    assert url.query["sslmode"] == "require"


def test_normalize_database_url_rejects_wrong_project_for_pooler():
    import pytest

    with pytest.raises(ValueError, match="does not match"):
        normalize_database_url(
            "postgresql://postgres:secret@db.otherproject.supabase.co:5432/postgres",
            pooler_host="aws-1-us-west-2.pooler.supabase.com",
            project_ref="exampleproject",
        )


def test_normalize_database_url_retargets_existing_pooler_url():
    from sqlalchemy.engine import make_url

    result = normalize_database_url(
        "postgresql://postgres.exampleproject:p@ss@aws-0-us-west-2.pooler.supabase.com:5432/postgres",
        pooler_host="aws-1-us-west-2.pooler.supabase.com",
        project_ref="exampleproject",
    )

    assert make_url(result).host == "aws-1-us-west-2.pooler.supabase.com"


def test_render_postgres_url_uses_installed_psycopg_driver():
    assert normalize_database_url(
        "postgresql://user:password@example.com:5432/app"
    ) == "postgresql+psycopg://user:password@example.com:5432/app"


def test_legacy_postgres_url_uses_installed_psycopg_driver():
    assert normalize_database_url(
        "postgres://user:password@example.com:5432/app"
    ) == "postgresql+psycopg://user:password@example.com:5432/app"


def test_explicit_driver_and_sqlite_urls_are_unchanged():
    assert (
        normalize_database_url("postgresql+psycopg://user@example.com/app")
        == "postgresql+psycopg://user@example.com/app"
    )
    assert normalize_database_url("sqlite:///./app.db") == "sqlite:///./app.db"
