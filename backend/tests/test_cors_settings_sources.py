"""Public-only settings and ASGI regression checks; never load project dotenv."""
import ast
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


@pytest.fixture
def settings_type(monkeypatch):
    for name in ("CORS_ORIGINS", "CORS_ORIGINS_LIST", "CORS_ALLOW_ALL", "DEPLOYMENT_MODE", "LOCAL_ONLY"):
        monkeypatch.delenv(name, raising=False)
    source = Path(__file__).parents[1] / "config.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    # Execute imports and the class alone: exclude settings singleton, filesystem
    # setup, and host detection so these checks cannot read project .env files.
    safe = ast.Module(body=[node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom, ast.ClassDef))], type_ignores=[])
    namespace = {"__file__": str(source)}
    exec(compile(safe, str(source), "exec"), namespace)
    return namespace["Settings"]


def test_defaults_include_testing_origin(settings_type):
    assert "https://wcag-remediation.vercel.app" in settings_type(_env_file=None).CORS_ORIGINS


def test_dotenv_csv_is_loaded(settings_type, tmp_path):
    dotenv = tmp_path / "public.env"
    dotenv.write_text("CORS_ORIGINS_LIST=https://one.example, https://two.example\n", encoding="utf-8")
    assert settings_type(_env_file=dotenv).CORS_ORIGINS == ["https://one.example", "https://two.example"]


def test_environment_overrides_dotenv(settings_type, tmp_path, monkeypatch):
    dotenv = tmp_path / "public.env"
    dotenv.write_text("CORS_ORIGINS_LIST=https://dotenv.example\n", encoding="utf-8")
    monkeypatch.setenv("CORS_ORIGINS_LIST", "https://environment.example")
    assert settings_type(_env_file=dotenv).CORS_ORIGINS == ["https://environment.example"]


def test_constructor_overrides_environment(settings_type, monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS_LIST", "https://environment.example")
    assert settings_type(_env_file=None, CORS_ORIGINS_LIST="https://constructor.example").CORS_ORIGINS == ["https://constructor.example"]


def test_json_origin_setting_remains_supported(settings_type, monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", '["https://json.example"]')
    assert settings_type(_env_file=None).CORS_ORIGINS == ["https://json.example"]


@pytest.mark.parametrize("csv", [None, ""])
def test_empty_csv_preserves_list(settings_type, csv):
    assert settings_type(_env_file=None, CORS_ORIGINS=["https://list.example"], CORS_ORIGINS_LIST=csv).CORS_ORIGINS == ["https://list.example"]


def test_csv_trims_and_discards_empty_entries(settings_type):
    assert settings_type(_env_file=None, CORS_ORIGINS_LIST=" , https://one.example ,, https://two.example, ").CORS_ORIGINS == ["https://one.example", "https://two.example"]


@pytest.mark.parametrize("origin,status", [("https://allowed.example", 200), ("https://unlisted.example", 400), ("https://allowed.example.evil.example", 400)])
def test_dotenv_origins_control_upload_preflight(settings_type, tmp_path, origin, status):
    dotenv = tmp_path / "public.env"
    dotenv.write_text("CORS_ORIGINS_LIST=https://allowed.example\n", encoding="utf-8")
    settings = settings_type(_env_file=dotenv)
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    messages = []
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    async def send(message):
        messages.append(message)
    scope = {"type": "http", "method": "OPTIONS", "path": "/upload", "headers": [(b"origin", origin.encode()), (b"access-control-request-method", b"POST"), (b"access-control-request-headers", b"content-type,authorization")]}
    # A CORS preflight responds inline and does not require a socket, thread,
    # lifespan, or event-loop policy. Exhaust the ASGI coroutine directly.
    with pytest.raises(StopIteration):
        app(scope, receive, send).send(None)
    start = messages[0]
    assert start["status"] == status
    headers = dict(start["headers"])
    assert headers.get(b"access-control-allow-origin") == (origin.encode() if status == 200 else None)
