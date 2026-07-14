from backend.database_url import normalize_database_url


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
