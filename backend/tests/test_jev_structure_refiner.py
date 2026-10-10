"""Tests for Jev structure refinement through Vercel AI Gateway."""
from __future__ import annotations

import json

import httpx

from backend.jev_structure_refiner import (
    build_jev_structure_request,
    refine_structure_tags_with_jev,
)
from backend.layout_model import PageLayout, StructureBlock


ENDPOINT = "https://ai-gateway.vercel.sh/typesafe/v1/systemone"


def _choice(choice: str, confidence: float, options: list[str]) -> dict:
    remainder = (1.0 - confidence) / max(1, len(options) - 1)
    probabilities = {
        option: confidence if option == choice else remainder for option in options
    }
    return {
        "type": "choice",
        "choice": choice,
        "confidence": confidence,
        "probabilities": probabilities,
    }


def _layouts() -> list[PageLayout]:
    return [
        PageLayout(
            page_number=0,
            width=612,
            height=792,
            blocks=[
                StructureBlock(
                    tag="P",
                    bbox=(50, 40, 550, 80),
                    page_number=0,
                    content="Results",
                    metadata={"provider": "opendataloader"},
                ),
                StructureBlock(
                    tag="H2",
                    bbox=(50, 100, 550, 180),
                    page_number=0,
                    content="The study included 400 participants across four sites.",
                    metadata={"provider": "opendataloader"},
                ),
                StructureBlock(
                    tag="Figure",
                    bbox=(50, 200, 550, 500),
                    page_number=0,
                    content="Chart of participant outcomes",
                    metadata={"provider": "opendataloader"},
                ),
            ],
        )
    ]


def test_request_uses_native_system_one_choice_questions() -> None:
    block = _layouts()[0].blocks[0]

    request = build_jev_structure_request([block], model="typesafe-ai/jev")

    assert request["model"] == "typesafe-ai/jev"
    assert request["state"][0]["block_id"] == "B00000"
    assert request["state"][0]["current_pdf_tag"] == "P"
    assert request["questions"]["type_B00000"]["type"] == "choice"
    assert set(request["questions"]["type_B00000"]["criteria"]) == {
        "heading",
        "paragraph",
    }
    assert set(request["questions"]["level_B00000"]["criteria"]) == {
        "H1",
        "H2",
        "H3",
        "H4",
        "H5",
        "H6",
    }


def test_high_confidence_answers_refine_only_heading_and_paragraph_blocks() -> None:
    layouts = _layouts()

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == ENDPOINT
        assert request.headers["Authorization"] == "Bearer secret"
        payload = json.loads(request.content)
        assert len(payload["state"]) == 2
        answers = {
            "type_B00000": _choice("heading", 0.98, ["heading", "paragraph"]),
            "level_B00000": _choice(
                "H2", 0.96, ["H1", "H2", "H3", "H4", "H5", "H6"]
            ),
            "type_B00001": _choice("paragraph", 0.97, ["heading", "paragraph"]),
            "level_B00001": _choice(
                "H2", 0.55, ["H1", "H2", "H3", "H4", "H5", "H6"]
            ),
        }
        return httpx.Response(
            200,
            json={
                "model": "typesafe-ai/jev",
                "answers": answers,
                "usage": {"input_tokens": 420, "output_tokens": 80},
            },
        )

    result = refine_structure_tags_with_jev(
        layouts,
        gateway_token="secret",
        min_confidence=0.90,
        endpoint=ENDPOINT,
        transport=httpx.MockTransport(handler),
    )

    assert [block.tag for block in layouts[0].blocks] == ["H2", "P", "Figure"]
    assert result.attempted_blocks == 2
    assert result.applied_blocks == 2
    assert result.retained_blocks == 0
    assert result.models_used == ["typesafe-ai/jev"]
    assert result.gateway == "vercel-ai-gateway"
    assert result.input_tokens == 420
    assert layouts[0].blocks[0].metadata["jev_refinement"]["applied"] is True
    assert "jev_refinement" not in layouts[0].blocks[2].metadata


def test_uncertain_or_malformed_answers_retain_original_tags() -> None:
    layouts = _layouts()

    def handler(_request: httpx.Request) -> httpx.Response:
        answers = {
            "type_B00000": _choice("heading", 0.60, ["heading", "paragraph"]),
            "level_B00000": _choice(
                "H1", 0.99, ["H1", "H2", "H3", "H4", "H5", "H6"]
            ),
            "type_B00001": {"type": "choice", "choice": "paragraph"},
        }
        return httpx.Response(
            200,
            json={"model": "typesafe-ai/jev", "answers": answers, "usage": {}},
        )

    result = refine_structure_tags_with_jev(
        layouts,
        gateway_token="secret",
        min_confidence=0.90,
        transport=httpx.MockTransport(handler),
    )

    assert [block.tag for block in layouts[0].blocks] == ["P", "H2", "Figure"]
    assert result.applied_blocks == 0
    assert result.retained_blocks == 2


def test_api_failure_is_fail_open_and_retries_transient_status() -> None:
    layouts = _layouts()
    attempts = {"count": 0}
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(529, json={"error": "overloaded"})

    result = refine_structure_tags_with_jev(
        layouts,
        gateway_token="secret",
        max_attempts=2,
        transport=httpx.MockTransport(handler),
        sleep=delays.append,
    )

    assert attempts["count"] == 2
    assert delays == [0.5]
    assert [block.tag for block in layouts[0].blocks[:2]] == ["P", "H2"]
    assert result.errors == ["api-status-529"]
    assert result.retained_blocks == 2


def test_missing_gateway_credential_does_not_attempt_refinement() -> None:
    layouts = _layouts()

    result = refine_structure_tags_with_jev(layouts, gateway_token="")

    assert result.attempted_blocks == 0
    assert result.errors == ["gateway-credential-unavailable"]
