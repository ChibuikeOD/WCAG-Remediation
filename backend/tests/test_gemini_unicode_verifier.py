import json

import httpx

from backend.gemini_unicode_verifier import (
    build_gemini_request,
    verify_ambiguous_unicode,
)


ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"


def ambiguity_context() -> dict:
    return {
        "document_title": "Algebra study",
        "font": "/CIDFont+F6",
        "cid": 2870,
        "gid": 2870,
        "candidates": ["U+0032", "U+00B2"],
        "deterministic_contradictions": [],
        "occurrences": [
            {
                "page": 30,
                "masked_line": "factor x[UNKNOWN] - 2x - 3",
                "paragraph": "Factor the following polynomial.",
                "position": "superscript",
            }
        ],
        "images": [
            "data:image/png;base64,AAAA",
            "data:image/png;base64,BBBB",
        ],
    }


def valid_response(*, probe: str = "K7M4Q2") -> dict:
    return {
        "status": "verified",
        "unicode_sequence": ["U+0032"],
        "rendered_text": "2",
        "confidence": 0.99,
        "occurrences_consistent": True,
        "alternatives": [],
        "evidence": ["glyph shape", "equation context"],
        "reason": "The glyph is a visually confirmed formatted digit two.",
        "vision_probe": probe,
    }


def test_request_uses_gemini_vision_images_and_json_mode() -> None:
    request = build_gemini_request(
        ambiguity_context(),
        "data:image/png;base64,PROBE",
        model="gemini-3.1-flash-lite",
    )

    assert request["model"] == "gemini-3.1-flash-lite"
    assert request["response_format"] == {"type": "json_object"}
    assert request["temperature"] == 0
    assert request["reasoning_effort"] == "minimal"
    user_content = request["messages"][1]["content"]
    assert sum(part["type"] == "image_url" for part in user_content) == 3
    assert "untrusted document data" in user_content[0]["text"].lower()
    assert "K7M4Q2" not in user_content[0]["text"]


def test_verifier_posts_to_configured_endpoint_and_accepts_visual_answer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == ENDPOINT
        assert request.headers["Authorization"] == "Bearer secret"
        payload = json.loads(request.content)
        assert isinstance(payload["messages"][1]["content"], list)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(valid_response())}}
                ]
            },
        )

    decision = verify_ambiguous_unicode(
        ambiguity_context(),
        api_key="secret",
        min_confidence=0.98,
        model="gemini-3.1-flash-lite",
        endpoint=ENDPOINT,
        transport=httpx.MockTransport(handler),
        probe_token="K7M4Q2",
        probe_image="data:image/png;base64,PROBE",
    )

    assert decision.accepted is True
    assert decision.text == "2"
    assert decision.model_used == "gemini-3.1-flash-lite"
    assert decision.evidence_mode == "vision"


def test_verifier_fails_closed_when_vision_probe_is_wrong() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(valid_response(probe="WRONG"))}}
                ]
            },
        )
    )

    decision = verify_ambiguous_unicode(
        ambiguity_context(),
        api_key="secret",
        min_confidence=0.98,
        endpoint=ENDPOINT,
        transport=transport,
        probe_token="K7M4Q2",
        probe_image="data:image/png;base64,PROBE",
    )

    assert decision.accepted is False
    assert decision.rejection_reason == "vision-not-confirmed"


def test_verifier_fails_closed_on_api_error() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(429, json={"error": "rate limited"})
    )

    decision = verify_ambiguous_unicode(
        ambiguity_context(),
        api_key="secret",
        min_confidence=0.98,
        endpoint=ENDPOINT,
        transport=transport,
        probe_token="K7M4Q2",
        probe_image="data:image/png;base64,PROBE",
    )

    assert decision.accepted is False
    assert decision.rejection_reason == "api-status-429"
    assert decision.response["api_error"]["status_code"] == 429


def test_verifier_retries_empty_content_then_succeeds() -> None:
    attempts = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": ""}, "finish_reason": "length"}]},
            )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(valid_response())}}]},
        )

    decision = verify_ambiguous_unicode(
        ambiguity_context(),
        api_key="secret",
        min_confidence=0.98,
        endpoint=ENDPOINT,
        max_attempts=3,
        transport=httpx.MockTransport(handler),
        probe_token="K7M4Q2",
        probe_image="data:image/png;base64,PROBE",
    )

    assert attempts["count"] == 2
    assert decision.accepted is True
