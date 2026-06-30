import json

import httpx
import pytest

from backend.deepseek_unicode_verifier import (
    build_deepseek_request,
    validate_deepseek_response,
    verify_ambiguous_unicode,
)


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
            },
            {
                "page": 171,
                "masked_line": "8x[UNKNOWN] plus x[UNKNOWN]",
                "paragraph": "An interviewee explains polynomial multiplication.",
                "position": "superscript",
            },
        ],
        "images": [
            "data:image/png;base64,AAAA",
            "data:image/png;base64,BBBB",
        ],
    }


def valid_response() -> dict:
    return {
        "status": "verified",
        "unicode_sequence": ["U+0032"],
        "rendered_text": "2",
        "confidence": 0.99,
        "occurrences_consistent": True,
        "alternatives": [],
        "evidence": ["glyph shape", "equation context"],
        "reason": "The glyph is a formatted digit two.",
        "vision_probe": "K7M4Q2",
    }


def test_request_uses_v4_pro_images_and_untrusted_context() -> None:
    request = build_deepseek_request(
        ambiguity_context(),
        "data:image/png;base64,PROBE",
    )

    assert request["model"] == "deepseek-v4-pro"
    user_content = request["messages"][1]["content"]
    assert sum(part["type"] == "image_url" for part in user_content) == 3
    assert "untrusted document data" in user_content[0]["text"].lower()
    assert "K7M4Q2" not in user_content[0]["text"]


@pytest.mark.parametrize(
    "overrides,rejection",
    [
        ({"status": "ambiguous"}, "model-marked-ambiguous"),
        ({"confidence": 0.97}, "confidence-below-threshold"),
        ({"occurrences_consistent": False}, "occurrence-conflict"),
        ({"vision_probe": "WRONG"}, "vision-not-confirmed"),
        ({"alternatives": ["U+00B2"]}, "credible-alternative-remains"),
    ],
)
def test_acceptance_gate_rejects_unsafe_answers(overrides, rejection) -> None:
    response = valid_response() | overrides

    decision = validate_deepseek_response(
        response, ambiguity_context(), "K7M4Q2", 0.98
    )

    assert decision.accepted is False
    assert decision.rejection_reason == rejection


def test_acceptance_gate_accepts_verified_consistent_character() -> None:
    decision = validate_deepseek_response(
        valid_response(), ambiguity_context(), "K7M4Q2", 0.98
    )

    assert decision.accepted is True
    assert decision.text == "2"
    assert decision.rejection_reason is None


def test_acceptance_gate_rejects_invalid_unicode_sequence() -> None:
    response = valid_response() | {
        "unicode_sequence": ["U+D800"],
        "rendered_text": "bad",
    }

    decision = validate_deepseek_response(
        response, ambiguity_context(), "K7M4Q2", 0.98
    )

    assert decision.accepted is False
    assert decision.rejection_reason == "invalid-unicode"


def test_verifier_calls_deepseek_and_accepts_strict_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "deepseek-v4-pro"
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
        transport=httpx.MockTransport(handler),
        probe_token="K7M4Q2",
        probe_image="data:image/png;base64,PROBE",
    )

    assert decision.accepted is True
    assert decision.text == "2"


def test_verifier_fails_closed_on_api_error() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(429, json={"error": "rate limited"})
    )

    decision = verify_ambiguous_unicode(
        ambiguity_context(),
        api_key="secret",
        min_confidence=0.98,
        transport=transport,
        probe_token="K7M4Q2",
        probe_image="data:image/png;base64,PROBE",
    )

    assert decision.accepted is False
    assert decision.rejection_reason == "api-status-429"


def test_verifier_fails_closed_on_prose_wrapped_json() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "Here is the answer: " + json.dumps(valid_response())}}
                ]
            },
        )
    )

    decision = verify_ambiguous_unicode(
        ambiguity_context(),
        api_key="secret",
        min_confidence=0.98,
        transport=transport,
        probe_token="K7M4Q2",
        probe_image="data:image/png;base64,PROBE",
    )

    assert decision.accepted is False
    assert decision.rejection_reason == "invalid-json"
