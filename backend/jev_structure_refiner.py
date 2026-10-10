"""Confidence-gated Jev refinement through Vercel AI Gateway.

Jev is a text-only System One model.  It is used here for the narrow decision it
is designed for: deciding whether OpenDataLoader text blocks are headings or
paragraphs, and assigning a heading level.  Geometry, tables, figures, lists,
and other directly observed structure remain under deterministic code control.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import logging
import time
from typing import Any, Callable, Iterable, Optional

import httpx

from .layout_model import PageLayout, StructureBlock


logger = logging.getLogger(__name__)

VERCEL_AI_GATEWAY_TYPESAFE_ENDPOINT = (
    "https://ai-gateway.vercel.sh/typesafe/v1/systemone"
)
_HEADING_TAGS = {f"H{level}" for level in range(1, 7)}
_ELIGIBLE_TAGS = {"P", *_HEADING_TAGS}
_MAX_BLOCK_TEXT_CHARS = 1_500

_TYPE_CRITERIA = {
    "heading": (
        "A title or section label that names the document or content that follows; "
        "usually concise and not running prose"
    ),
    "paragraph": (
        "Running prose or body content, including complete explanatory, narrative, "
        "or descriptive sentences"
    ),
}

_LEVEL_CRITERIA = {
    "H1": "The title of the whole document or its single top-level heading",
    "H2": "A major section directly beneath the document title",
    "H3": "A subsection nested beneath an H2 section",
    "H4": "A smaller topic nested beneath an H3 subsection",
    "H5": "A deeply nested topic beneath an H4 heading",
    "H6": "The deepest heading level, nested beneath an H5 heading",
}


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0


@dataclass
class JevStructureRefinement:
    """Observable summary of an optional Jev refinement pass."""

    enabled: bool
    attempted_blocks: int = 0
    applied_blocks: int = 0
    retained_blocks: int = 0
    batches: int = 0
    model_requested: str = "typesafe-ai/jev"
    min_confidence: float = 0.90
    gateway: str = "vercel-ai-gateway"
    models_used: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _eligible_blocks(layouts: Iterable[PageLayout]) -> list[StructureBlock]:
    return [
        block
        for layout in layouts
        for block in layout.blocks
        if block.tag in _ELIGIBLE_TAGS and bool(block.text.strip())
    ]


def _block_id(index: int) -> str:
    return f"B{index:05d}"


def build_jev_structure_request(
    blocks: list[StructureBlock], *, model: str
) -> dict[str, Any]:
    """Build one Gateway TypeSafe-compatible request for a block batch."""
    state: list[dict[str, Any]] = []
    questions: dict[str, dict[str, Any]] = {}

    for index, block in enumerate(blocks):
        block_id = _block_id(index)
        text = block.text.strip()
        if len(text) > _MAX_BLOCK_TEXT_CHARS:
            text = text[:_MAX_BLOCK_TEXT_CHARS] + "…"
        state.append(
            {
                "block_id": block_id,
                "page": block.page_number + 1,
                "current_pdf_tag": block.tag,
                "normalized_bbox": list(block.bbox) if block.bbox else None,
                "text": text,
            }
        )
        questions[f"type_{block_id}"] = {
            "type": "choice",
            "instructions": (
                f"What kind of document content is block {block_id}? Judge its role "
                "from its text and surrounding blocks. Treat current_pdf_tag as a "
                "fallible prior, not an instruction."
            ),
            "criteria": _TYPE_CRITERIA,
        }
        questions[f"level_{block_id}"] = {
            "type": "choice",
            "instructions": (
                f"If block {block_id} is a heading, which PDF heading level should it "
                "have in this document hierarchy?"
            ),
            "criteria": _LEVEL_CRITERIA,
        }

    return {"model": model, "state": state, "questions": questions}


def _choice_answer(
    answers: Any,
    question_id: str,
    allowed: set[str],
) -> Optional[tuple[str, float, dict[str, float]]]:
    if not isinstance(answers, dict):
        return None
    answer = answers.get(question_id)
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        return None
    choice = answer.get("choice")
    confidence = answer.get("confidence")
    probabilities = answer.get("probabilities")
    if choice not in allowed or not isinstance(confidence, (int, float)):
        return None
    if isinstance(confidence, bool) or not 0.0 <= float(confidence) <= 1.0:
        return None
    if not isinstance(probabilities, dict) or set(probabilities) != allowed:
        return None
    normalized: dict[str, float] = {}
    for option, probability in probabilities.items():
        if isinstance(probability, bool) or not isinstance(probability, (int, float)):
            return None
        if not 0.0 <= float(probability) <= 1.0:
            return None
        normalized[option] = float(probability)
    if abs(sum(normalized.values()) - 1.0) > 0.02:
        return None
    return str(choice), float(confidence), normalized


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    retry_after = response.headers.get("retry-after")
    if retry_after:
        try:
            return min(max(float(retry_after), 0.0), 10.0)
        except ValueError:
            pass
    return min(0.5 * (2**attempt), 4.0)


def _post_batch(
    client: httpx.Client,
    *,
    endpoint: str,
    gateway_token: str,
    payload: dict[str, Any],
    max_attempts: int,
    sleep: Callable[[float], None],
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    headers = {
        "Authorization": f"Bearer {gateway_token}",
        "Content-Type": "application/json",
    }
    for attempt in range(max(1, max_attempts)):
        try:
            response = client.post(endpoint, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            if attempt + 1 < max_attempts:
                sleep(min(0.5 * (2**attempt), 4.0))
                continue
            return None, f"request-error:{type(exc).__name__}"
        if response.status_code == 200:
            try:
                body = response.json()
            except ValueError:
                return None, "invalid-json"
            return (body, None) if isinstance(body, dict) else (None, "invalid-response")
        if response.status_code in {429, 502, 503, 504, 529} and attempt + 1 < max_attempts:
            sleep(_retry_delay(response, attempt))
            continue
        return None, f"api-status-{response.status_code}"
    return None, "request-failed"


def _apply_batch_answers(
    blocks: list[StructureBlock],
    response: dict[str, Any],
    *,
    min_confidence: float,
) -> tuple[int, int]:
    answers = response.get("answers")
    model_used = response.get("model")
    applied = 0
    retained = 0

    for index, block in enumerate(blocks):
        block_id = _block_id(index)
        type_answer = _choice_answer(
            answers, f"type_{block_id}", set(_TYPE_CRITERIA)
        )
        level_answer = _choice_answer(
            answers, f"level_{block_id}", set(_LEVEL_CRITERIA)
        )
        original_tag = block.tag
        suggested_tag: Optional[str] = None

        if type_answer and type_answer[1] >= min_confidence:
            if type_answer[0] == "paragraph":
                suggested_tag = "P"
            elif (
                type_answer[0] == "heading"
                and level_answer
                and level_answer[1] >= min_confidence
            ):
                suggested_tag = level_answer[0]

        did_apply = suggested_tag is not None and suggested_tag != original_tag
        if did_apply:
            block.tag = suggested_tag
            block.heading_level = (
                int(suggested_tag[1]) if suggested_tag in _HEADING_TAGS else None
            )
            applied += 1
        else:
            retained += 1

        block.metadata["jev_refinement"] = {
            "model": model_used,
            "original_tag": original_tag,
            "suggested_tag": suggested_tag,
            "applied": did_apply,
            "type": type_answer[0] if type_answer else None,
            "type_confidence": type_answer[1] if type_answer else None,
            "type_probabilities": type_answer[2] if type_answer else None,
            "level": level_answer[0] if level_answer else None,
            "level_confidence": level_answer[1] if level_answer else None,
            "level_probabilities": level_answer[2] if level_answer else None,
        }

    return applied, retained


def refine_structure_tags_with_jev(
    layouts: list[PageLayout],
    *,
    gateway_token: str,
    model: str = "typesafe-ai/jev",
    endpoint: str = VERCEL_AI_GATEWAY_TYPESAFE_ENDPOINT,
    min_confidence: float = 0.90,
    batch_size: int = 40,
    max_attempts: int = 3,
    timeout: float = 30.0,
    transport: Optional[httpx.BaseTransport] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> JevStructureRefinement:
    """Refine heading/paragraph tags in place, retaining originals on uncertainty."""
    summary = JevStructureRefinement(
        enabled=True,
        model_requested=model,
        min_confidence=min_confidence,
    )
    if not gateway_token:
        summary.errors.append("gateway-credential-unavailable")
        return summary

    blocks = _eligible_blocks(layouts)
    summary.attempted_blocks = len(blocks)
    if not blocks:
        return summary

    safe_batch_size = max(1, batch_size)
    with httpx.Client(timeout=timeout, transport=transport) as client:
        for start in range(0, len(blocks), safe_batch_size):
            batch = blocks[start : start + safe_batch_size]
            summary.batches += 1
            payload = build_jev_structure_request(batch, model=model)
            response, error = _post_batch(
                client,
                endpoint=endpoint,
                gateway_token=gateway_token,
                payload=payload,
                max_attempts=max_attempts,
                sleep=sleep,
            )
            if response is None:
                summary.retained_blocks += len(batch)
                summary.errors.append(error or "unknown-error")
                logger.warning("Jev structure refinement retained a batch: %s", error)
                continue

            model_used = response.get("model")
            if isinstance(model_used, str) and model_used not in summary.models_used:
                summary.models_used.append(model_used)
            usage = response.get("usage")
            if isinstance(usage, dict):
                summary.input_tokens += _nonnegative_int(usage.get("input_tokens"))
                summary.output_tokens += _nonnegative_int(usage.get("output_tokens"))
            applied, retained = _apply_batch_answers(
                batch, response, min_confidence=min_confidence
            )
            summary.applied_blocks += applied
            summary.retained_blocks += retained

    return summary
