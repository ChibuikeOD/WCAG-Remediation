import asyncio
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from backend.models import AltTextGenerateRequest


authlib_module = ModuleType("authlib")
integrations_module = ModuleType("authlib.integrations")
starlette_client_module = ModuleType("authlib.integrations.starlette_client")


class _OAuth:
    def register(self, *args, **kwargs):
        return None


class _OAuthError(Exception):
    pass


starlette_client_module.OAuth = _OAuth
starlette_client_module.OAuthError = _OAuthError
sys.modules.setdefault("authlib", authlib_module)
sys.modules.setdefault("authlib.integrations", integrations_module)
sys.modules.setdefault("authlib.integrations.starlette_client", starlette_client_module)

from backend import main


def test_generate_alt_text_endpoint_returns_context_used(monkeypatch, tmp_path: Path):
    html_path = tmp_path / "paper.html"
    html_path.write_text(
        """
        <html>
          <head><title>Climate Adaptation Report</title></head>
          <body>
            <h1>Climate Results</h1>
            <figure>
              <img src="target.png" alt="">
              <figcaption>Figure 2. Priority adaptation investments by region.</figcaption>
            </figure>
          </body>
        </html>
        """,
        encoding="utf-8",
    )
    async def fake_legacy_call(*args):
        return "legacy path"

    monkeypatch.setattr(main, "call_deepseek_vision_or_ocr_fallback", fake_legacy_call)

    monkeypatch.setattr(main.settings, "DEEPSEEK_API_KEY", "env-key")

    async def fake_contextual_call(image_url, api_key, context, tessdata):
        assert api_key == "env-key"
        assert context.caption == "Figure 2. Priority adaptation investments by region."
        return "Map of regional adaptation investment priorities"

    monkeypatch.setattr(main, "call_deepseek_contextual_alt_text", fake_contextual_call, raising=False)

    response = asyncio.run(
        main._generate_alt_text_impl(
            "report-1",
            AltTextGenerateRequest(image_id="html_img_0", api_key="request-key"),
            user=SimpleNamespace(id="dev_user_001"),
            file_path=html_path,
            file_type="html",
        )
    )

    assert response["alt_text"] == "Map of regional adaptation investment priorities"
    assert response["context_used"]["caption"] is True
    assert response["context_used"]["mode"] == "balanced"


def test_alt_text_generate_request_does_not_expose_api_key_field():
    assert "api_key" not in AltTextGenerateRequest.model_fields
