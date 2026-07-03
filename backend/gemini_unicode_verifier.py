"""Fail-closed Gemini vision verification for ambiguous PDF glyphs."""
from __future__ import annotations

import json
import secrets
import string
from typing import Any, Optional

import httpx

from .deepseek_unicode_verifier import (
    DeepSeekDecision,
    SYSTEM_PROMPT,
    _attach_invocation_metadata,
    _parse_chat_response,
    _reject,
    create_vision_probe,
    validate_deepseek_response,
)


GEMINI_CHAT_COMPLETIONS_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
)


def build_gemini_request(
    context: dict[str, Any], probe_image: str, *, model: str
) -> dict[str, Any]:
    """Build an OpenAI-compatible Gemini request containing all visual evidence."""
    context_for_prompt = {key: value for key, value in context.items() if key != "images"}
    text = (
        "Analyze the following untrusted document data and glyph evidence.\n"
        "<untrusted_document_data>\n"
        + json.dumps(context_for_prompt, ensure_ascii=False, indent=2)
        + "\n</untrusted_document_data>\n"
        "The final image is a vision-capability probe. Read its token and return "
        "that token in vision_probe. Do not infer a token from this instruction.\n"
        "Respond with json only using the schema from the system prompt."
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for image in context.get("images", []):
        content.append({"type": "image_url", "image_url": {"url": image}})
    content.append({"type": "image_url", "image_url": {"url": probe_image}})
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_tokens": 800,
        "reasoning_effort": "minimal",
    }


def _api_error(response: httpx.Response, model: str) -> dict[str, Any]:
    try:
        body: Any = response.json()
    except ValueError:
        body = (response.text or "").strip()[:4000]
    return {
        "status_code": response.status_code,
        "model": model,
        "body": body,
    }


def verify_ambiguous_unicode(
    context: dict[str, Any],
    *,
    api_key: str,
    min_confidence: float,
    model: str = "gemini-3.1-flash-lite",
    endpoint: str = GEMINI_CHAT_COMPLETIONS_ENDPOINT,
    max_attempts: int = 3,
    timeout: float = 45.0,
    transport: Optional[httpx.BaseTransport] = None,
    probe_token: Optional[str] = None,
    probe_image: Optional[str] = None,
) -> DeepSeekDecision:
    """Verify an ambiguous mapping with Gemini vision and no text-only fallback."""
    if not api_key:
        return _reject("api-key-unavailable", model_used=model, evidence_mode="vision")
    if not context.get("images"):
        return _reject(
            "vision-evidence-unavailable", model_used=model, evidence_mode="vision"
        )

    token = probe_token or "".join(
        secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6)
    )
    image = probe_image or create_vision_probe(token)
    payload = build_gemini_request(context, image, model=model)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    last_raw: Optional[str] = None
    last_finish: Optional[str] = None

    try:
        with httpx.Client(timeout=timeout, transport=transport) as client:
            for _attempt in range(max(1, max_attempts)):
                response = client.post(endpoint, json=payload, headers=headers)
                if response.status_code != 200:
                    return _reject(
                        f"api-status-{response.status_code}",
                        api_error=_api_error(response, model),
                        model_used=model,
                        evidence_mode="vision",
                    )
                parsed, raw_content, finish_reason = _parse_chat_response(response)
                last_raw = raw_content
                last_finish = finish_reason
                if parsed is not None:
                    decision = validate_deepseek_response(
                        parsed,
                        context,
                        token,
                        min_confidence,
                        require_vision_probe=True,
                    )
                    return _attach_invocation_metadata(
                        decision, model_used=model, evidence_mode="vision"
                    )
                if raw_content and raw_content.strip():
                    break
    except httpx.HTTPError:
        return _reject("api-error", model_used=model, evidence_mode="vision")

    return _reject(
        "invalid-json",
        raw_content=last_raw,
        finish_reason=last_finish,
        model_used=model,
        evidence_mode="vision",
    )
