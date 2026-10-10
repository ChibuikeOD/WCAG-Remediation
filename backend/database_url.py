"""Database URL compatibility helpers."""

import re
from urllib.parse import unquote, urlsplit

from sqlalchemy.engine import URL


def normalize_database_url(
    database_url: str,
    *,
    pooler_host: str | None = None,
    project_ref: str | None = None,
) -> str:
    """Use the installed Psycopg 3 driver for platform-provided Postgres URLs."""
    if pooler_host:
        if not project_ref or not re.fullmatch(r"[a-z0-9]+", project_ref):
            raise ValueError("A valid Supabase project ref is required for the database pooler")
        if not re.fullmatch(r"aws-[0-9]+-[a-z0-9-]+\.pooler\.supabase\.com", pooler_host):
            raise ValueError("Invalid Supabase database pooler host")
        try:
            credentials, endpoint = database_url.rsplit("@", 1)
            scheme, userinfo = credentials.split("://", 1)
            source_user, password = userinfo.split(":", 1)
            source = urlsplit("postgresql://" + endpoint)
        except (ValueError, IndexError) as exc:
            raise ValueError("Invalid Supabase database URL") from exc
        if scheme not in {"postgres", "postgresql", "postgresql+psycopg"}:
            raise ValueError("Supabase database URL must use Postgres")
        is_direct = source.hostname == f"db.{project_ref}.supabase.co" and source_user == "postgres"
        is_pooler = (
            re.fullmatch(r"aws-[0-9]+-[a-z0-9-]+\.pooler\.supabase\.com", source.hostname or "")
            and source_user == f"postgres.{project_ref}"
        )
        if not (is_direct or is_pooler):
            raise ValueError("Supabase database URL does not match the configured project")
        return URL.create(
            "postgresql+psycopg",
            username=f"postgres.{project_ref}",
            password=unquote(password),
            host=pooler_host,
            port=6543,
            database=source.path.lstrip("/") or "postgres",
            query={"sslmode": "require"},
        ).render_as_string(hide_password=False)

    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url
