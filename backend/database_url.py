"""Database URL compatibility helpers."""


def normalize_database_url(database_url: str) -> str:
    """Use the installed Psycopg 3 driver for platform-provided Postgres URLs."""
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url
