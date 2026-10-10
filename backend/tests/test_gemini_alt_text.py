import json

import httpx
import pytest

from backend.alt_text_context import AltTextContext, NeighboringImageContext
from backend.gemini_alt_text import (
    ALT_TEXT_SYSTEM_PROMPT,
    build_gemini_alt_text_messages,
    build_gemini_alt_text_request,
    call_gemini_contextual_alt_text,
)


ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"


def _context() -> AltTextContext:
    return AltTextContext(
        document_title="Climate Adaptation Report",
        file_type="pdf",
        target_image_id="fig_2",
        page_num=4,
        context_mode="balanced",
        caption="Figure 2. Priority adaptation investments by region.",
        headings=["Climate Adaptation in Coastal Cities"],
        page_text="The paper compares flood exposure and adaptation investment priorities.",
        previous_page_text="The previous page defines exposure metrics.",
        next_page_text="The next page discusses residual risk.",
        neighboring_images=[
            NeighboringImageContext(
                id="fig_1",
                page_num=4,
                caption="Figure 1. Baseline flood exposure by district.",
                current_alt="",
                image_url="data:image/png;base64,AAA",
            )
        ],
    )


def test_build_gemini_request_uses_configured_model_and_contextual_images():
    request = build_gemini_alt_text_request(
        "data:image/png;base64,TARGET",
        _context(),
        ocr_text="Region A 42%",
        model="gemini-3.1-flash-lite",
    )

    assert request["model"] == "gemini-3.1-flash-lite"
    assert request["max_tokens"] == 100
    assert request["messages"][0]["content"] == ALT_TEXT_SYSTEM_PROMPT

    content = request["messages"][1]["content"]
    text_parts = [part["text"] for part in content if part["type"] == "text"]
    image_parts = [part for part in content if part["type"] == "image_url"]

    joined_text = "\n".join(text_parts)
    assert "Climate Adaptation Report" in joined_text
    assert "Figure 2. Priority adaptation investments by region." in joined_text
    assert "Figure 1. Baseline flood exposure by district." in joined_text
    assert "Region A 42%" in joined_text
    assert "Return only the alt text" in joined_text
    assert image_parts[0]["image_url"]["url"] == "data:image/png;base64,TARGET"


@pytest.mark.asyncio
async def test_call_gemini_contextual_alt_text_posts_to_configured_endpoint():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == ENDPOINT
        assert request.headers["Authorization"] == "Bearer gemini-secret"
        payload = json.loads(request.content)
        assert payload["model"] == "gemini-3.1-flash-lite"
        assert isinstance(payload["messages"][1]["content"], list)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '"Map of regional adaptation investment priorities"'
                        }
                    }
                ]
            },
        )

    alt_text = await call_gemini_contextual_alt_text(
        "data:image/png;base64,TARGET",
        "gemini-secret",
        _context(),
        model="gemini-3.1-flash-lite",
        endpoint=ENDPOINT,
        transport=httpx.MockTransport(handler),
    )

    assert alt_text == "Map of regional adaptation investment priorities"


def test_build_gemini_messages_keeps_existing_prompt_shape():
    messages = build_gemini_alt_text_messages(
        "data:image/png;base64,TARGET", _context(), ocr_text="Region A 42%"
    )

    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == ALT_TEXT_SYSTEM_PROMPT
    assert messages[1]["role"] == "user"
