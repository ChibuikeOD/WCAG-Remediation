import json

import httpx

from backend.deepseek_unicode_verifier import DeepSeekDecision
from backend.jev_unicode_consensus import (
    build_jev_glyph_request,
    verify_glyph_consensus,
)


ENDPOINT = "https://ai-gateway.vercel.sh/typesafe/v1/systemone"


def ambiguity_context() -> dict:
    return {
        "document_title": "Algebra study",
        "font": "/CIDFont+F6",
        "cid": 2870,
        "gid": 2870,
        "glyph_name": "two.superior",
        "candidates": ["U+0032", "U+00B2"],
        "candidate_source": "font-metadata",
        "deterministic_contradictions": ["2", "²"],
        "occurrences": [
            {
                "page": 30,
                "masked_line": "factor x[UNKNOWN] - 2x - 3",
                "paragraph": "Factor the following polynomial.",
                "position": "superscript",
                "font_size": 6.5,
            }
        ],
        "images": ["data:image/png;base64,AAAA"],
    }


def visual_decision() -> DeepSeekDecision:
    return DeepSeekDecision(
        accepted=True,
        text="2",
        confidence=0.995,
        rejection_reason=None,
        response={
            "status": "verified",
            "unicode_sequence": ["U+0032"],
            "rendered_text": "2",
            "confidence": 0.995,
            "occurrences_consistent": True,
            "alternatives": ["U+00B2"],
            "evidence": ["glyph shape", "equation context"],
            "reason": "The visual glyph is a formatted digit two.",
            "vision_probe": "SECRET",
        },
        model_used="gemini-3.1-flash-lite",
        evidence_mode="vision",
    )


def jev_response(choice: str, confidence: float = 0.99) -> dict:
    probabilities = {
        "candidate_0": 0.005,
        "candidate_1": 0.005,
        "reject": 0.99,
    }
    probabilities["reject"] = 0.005
    probabilities[choice] = 0.99
    remaining = [key for key in probabilities if key != choice]
    probabilities[remaining[0]] = 0.005
    probabilities[remaining[1]] = 0.005
    return {
        "model": "jev-1.13.0",
        "answers": {
            "unicode_consensus": {
                "type": "choice",
                "choice": choice,
                "confidence": confidence,
                "probabilities": probabilities,
            }
        },
        "usage": {"input_tokens": 211, "output_tokens": 8},
    }


def test_request_contains_text_evidence_but_never_glyph_images() -> None:
    payload, expected = build_jev_glyph_request(
        ambiguity_context(), visual_decision(), model="typesafe-ai/jev"
    )

    assert payload["model"] == "typesafe-ai/jev"
    assert expected == "candidate_0"
    assert "images" not in payload["state"]
    serialized = json.dumps(payload)
    assert "data:image" not in serialized
    assert "vision_probe" not in serialized
    assert "factor x[UNKNOWN]" in serialized
    assert set(payload["questions"]["unicode_consensus"]["criteria"]) == {
        "candidate_0",
        "candidate_1",
        "reject",
    }


def test_gateway_accepts_only_exact_high_confidence_agreement() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == ENDPOINT
        assert request.headers["Authorization"] == "Bearer gateway-secret"
        payload = json.loads(request.content)
        assert payload["model"] == "typesafe-ai/jev"
        return httpx.Response(200, json=jev_response("candidate_0"))

    result = verify_glyph_consensus(
        ambiguity_context(),
        visual_decision(),
        gateway_token="gateway-secret",
        min_confidence=0.98,
        endpoint=ENDPOINT,
        transport=httpx.MockTransport(handler),
    )

    assert result.accepted is True
    assert result.rejection_reason is None
    assert result.model_used == "jev-1.13.0"
    assert result.selected_candidate is not None
    assert "U+0032" in result.selected_candidate
    assert result.selected_candidate == result.expected_candidate
    assert result.input_tokens == 211
    assert result.output_tokens == 8


def test_gateway_disagreement_rejects_visual_mapping() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json=jev_response("candidate_1"))
    )

    result = verify_glyph_consensus(
        ambiguity_context(),
        visual_decision(),
        gateway_token="gateway-secret",
        min_confidence=0.98,
        transport=transport,
    )

    assert result.accepted is False
    assert result.rejection_reason == "jev-disagreed"


def test_gateway_low_confidence_and_missing_credentials_fail_closed() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200, json=jev_response("candidate_0", confidence=0.80)
        )
    )
    low_confidence = verify_glyph_consensus(
        ambiguity_context(),
        visual_decision(),
        gateway_token="gateway-secret",
        min_confidence=0.98,
        transport=transport,
    )
    unavailable = verify_glyph_consensus(
        ambiguity_context(),
        visual_decision(),
        gateway_token="",
        min_confidence=0.98,
    )

    assert low_confidence.accepted is False
    assert low_confidence.rejection_reason == "jev-confidence-below-threshold"
    assert unavailable.accepted is False
    assert unavailable.rejection_reason == "gateway-credential-unavailable"


def test_gateway_retries_transient_error_then_accepts() -> None:
    attempts = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200, json=jev_response("candidate_0"))

    result = verify_glyph_consensus(
        ambiguity_context(),
        visual_decision(),
        gateway_token="gateway-secret",
        min_confidence=0.98,
        max_attempts=2,
        transport=httpx.MockTransport(handler),
        sleep=lambda _delay: None,
    )

    assert attempts["count"] == 2
    assert result.accepted is True
