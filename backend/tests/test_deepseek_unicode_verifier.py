import json

import httpx
import pytest

from backend.deepseek_unicode_verifier import (
    _parse_chat_response,
    _parse_json_object,
    build_deepseek_request,
    build_deepseek_text_request,
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
        model="deepseek-v4-pro",
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


def test_acceptance_gate_ignores_vision_probe_in_text_only_mode() -> None:
    response = valid_response() | {"vision_probe": ""}
    decision = validate_deepseek_response(
        response,
        ambiguity_context(),
        "K7M4Q2",
        0.98,
        require_vision_probe=False,
    )

    assert decision.accepted is True
    assert decision.text == "2"


def test_acceptance_gate_allows_verified_digit_with_inferred_candidates() -> None:
    context = ambiguity_context()
    context["candidates"] = [f"U+003{d}" for d in range(10)]
    context["deterministic_contradictions"] = []
    response = valid_response() | {"vision_probe": ""}

    decision = validate_deepseek_response(
        response,
        context,
        "K7M4Q2",
        0.98,
        require_vision_probe=False,
    )

    assert decision.accepted is True
    assert decision.rejection_reason is None


def test_acceptance_gate_rejects_only_authoritative_contradictions() -> None:
    context = ambiguity_context()
    context["deterministic_contradictions"] = ["2", "²"]

    decision = validate_deepseek_response(
        valid_response() | {"vision_probe": ""},
        context,
        "K7M4Q2",
        0.98,
        require_vision_probe=False,
    )

    assert decision.accepted is False
    assert decision.rejection_reason == "deterministic-contradiction"


def test_text_request_uses_plain_string_user_content() -> None:
    request = build_deepseek_text_request(ambiguity_context(), model="deepseek-v4-pro")

    assert request["model"] == "deepseek-v4-pro"
    assert isinstance(request["messages"][1]["content"], str)
    assert "No glyph images are available" in request["messages"][1]["content"]
    assert request["response_format"] == {"type": "json_object"}
    assert request["thinking"] == {"type": "disabled"}


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
        assert isinstance(payload["messages"][1]["content"], str)
        text_response = valid_response() | {"vision_probe": ""}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(text_response)}}
                ]
            },
        )

    decision = verify_ambiguous_unicode(
        ambiguity_context(),
        api_key="secret",
        min_confidence=0.98,
        model="deepseek-v4-pro",
        transport=httpx.MockTransport(handler),
        probe_token="K7M4Q2",
        probe_image="data:image/png;base64,PROBE",
    )

    assert decision.accepted is True
    assert decision.text == "2"
    assert decision.evidence_mode == "text-only"


def test_verifier_fails_closed_on_api_error() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(429, json={"error": "rate limited"})
    )

    decision = verify_ambiguous_unicode(
        ambiguity_context(),
        api_key="secret",
        min_confidence=0.98,
        model="deepseek-v4-pro",
        vision_fallback_model=None,
        transport=transport,
        probe_token="K7M4Q2",
        probe_image="data:image/png;base64,PROBE",
    )

    assert decision.accepted is False
    assert decision.rejection_reason == "api-status-429"
    assert decision.response is not None
    assert decision.response["api_error"]["status_code"] == 429


def test_verifier_falls_back_to_text_only_when_vision_rejected() -> None:
    modes: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        user_content = payload["messages"][1]["content"]
        if isinstance(user_content, list):
            modes.append(f"vision:{payload['model']}")
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "unknown variant `image_url`, expected `text`",
                        "type": "invalid_request_error",
                    }
                },
            )
        modes.append("text-only")
        text_response = valid_response() | {"vision_probe": ""}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(text_response)}}
                ]
            },
        )

    decision = verify_ambiguous_unicode(
        ambiguity_context(),
        api_key="secret",
        min_confidence=0.98,
        model="deepseek-v4-pro",
        vision_fallback_model="deepseek-chat",
        use_vision=True,
        transport=httpx.MockTransport(handler),
        probe_token="K7M4Q2",
        probe_image="data:image/png;base64,PROBE",
    )

    assert modes == [
        "vision:deepseek-v4-pro",
        "vision:deepseek-chat",
        "text-only",
    ]
    assert decision.accepted is True
    assert decision.model_used == "deepseek-v4-pro"
    assert decision.evidence_mode == "text-only"


def test_verifier_extracts_json_from_prose_wrapped_response() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "Here is the answer: "
                            + json.dumps(valid_response() | {"vision_probe": ""})
                        }
                    }
                ]
            },
        )
    )

    decision = verify_ambiguous_unicode(
        ambiguity_context(),
        api_key="secret",
        min_confidence=0.98,
        model="deepseek-v4-pro",
        vision_fallback_model=None,
        transport=transport,
        probe_token="K7M4Q2",
        probe_image="data:image/png;base64,PROBE",
    )

    assert decision.accepted is True
    assert decision.text == "2"
    assert decision.evidence_mode == "text-only"


def test_verifier_retries_empty_content_then_succeeds() -> None:
    attempts = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": ""}, "finish_reason": "length"}]},
            )
        text_response = valid_response() | {"vision_probe": ""}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(text_response)}}
                ]
            },
        )

    decision = verify_ambiguous_unicode(
        ambiguity_context(),
        api_key="secret",
        min_confidence=0.98,
        model="deepseek-v4-pro",
        max_attempts=3,
        transport=httpx.MockTransport(handler),
        probe_token="K7M4Q2",
        probe_image="data:image/png;base64,PROBE",
    )

    assert attempts["count"] == 2
    assert decision.accepted is True
    assert decision.text == "2"


def test_parse_json_object_extracts_from_reasoning_content() -> None:
    response = httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": json.dumps(
                            valid_response() | {"vision_probe": ""}
                        ),
                    },
                    "finish_reason": "stop",
                }
            ]
        },
    )

    parsed, raw_text, finish_reason = _parse_chat_response(response)

    assert parsed is not None
    assert parsed["rendered_text"] == "2"
    assert raw_text is not None
    assert finish_reason == "stop"


def test_parse_json_object_extracts_fenced_json() -> None:
    payload = "```json\n" + json.dumps(valid_response()) + "\n```"
    parsed = _parse_json_object(payload)

    assert parsed is not None
    assert parsed["rendered_text"] == "2"
