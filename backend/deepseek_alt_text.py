"""
DeepSeek prompt construction and calling for context-aware alt text.
"""
from __future__ import annotations

import base64
import logging
from typing import Any, Optional

import httpx

from .alt_text_context import AltTextContext, normalize_text, trim_context_text

logger = logging.getLogger(__name__)

ALT_TEXT_SYSTEM_PROMPT = (
    "You write concise WCAG alt text for academic and policy documents. "
    "Use the provided document, page, caption, OCR, and neighboring-figure context "
    "to describe the target image accurately and relevantly. Do not invent data, "
    "conclusions, or labels that are not visible or stated in context. Return only the alt text."
)


def build_deepseek_messages(
    image_url: str,
    context: AltTextContext,
    ocr_text: str = "",
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": build_context_prompt(context, ocr_text)
            + "\n\nTarget image follows. Use this image as the subject of the alt text.",
        },
        {
            "type": "image_url",
            "image_url": {"url": image_url},
        },
    ]

    for neighbor in context.neighboring_images:
        if neighbor.image_url and _is_model_image_url(neighbor.image_url):
            label = neighbor.caption or neighbor.current_alt or f"Neighboring image {neighbor.id}"
            content.append(
                {
                    "type": "text",
                    "text": f"Neighboring figure for context only: {trim_context_text(label, 220)}",
                }
            )
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": neighbor.image_url},
                }
            )

    return [
        {"role": "system", "content": ALT_TEXT_SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def build_context_prompt(context: AltTextContext, ocr_text: str = "") -> str:
    sections = [
        "Create WCAG alt text for the target image using the context below.",
        "",
        "Document context:",
        f"- Title: {context.document_title or 'Unknown'}",
        f"- Type: {context.file_type or 'document'}",
        f"- Page: {context.page_num or 'HTML/unknown'}",
    ]

    if context.headings:
        sections.append(f"- Nearby headings: {' | '.join(context.headings)}")
    if context.caption:
        sections.append(f"- Detected caption: {context.caption}")

    sections.extend(["", "Page context:"])
    if context.previous_page_text:
        sections.append(f"- Previous page summary: {context.previous_page_text}")
    if context.page_text:
        sections.append(f"- Same-page text: {context.page_text}")
    if context.next_page_text:
        sections.append(f"- Next page summary: {context.next_page_text}")

    if context.neighboring_images:
        sections.extend(["", "Neighboring figures:"])
        for neighbor in context.neighboring_images:
            details = neighbor.caption or neighbor.current_alt or "No caption or alt text available"
            page = f"page {neighbor.page_num}" if neighbor.page_num else "same HTML document"
            sections.append(f"- {neighbor.id} ({page}): {trim_context_text(details, 240)}")

    if ocr_text:
        sections.extend(["", f"OCR text visible in target image: {trim_context_text(ocr_text, 500)}"])

    sections.extend(
        [
            "",
            "Rules:",
            "- Return only the alt text.",
            "- Maximum 150 characters.",
            "- Describe the purpose or content of the target image in this document.",
            "- Do not start with 'This image shows', 'An image of', or similar boilerplate.",
            "- Use chart, map, diagram, table, or photo when that type is identifiable.",
            "- Do not mention neighboring figures unless needed to disambiguate the target image.",
        ]
    )
    return "\n".join(sections)


def build_text_fallback_prompt(context: AltTextContext, ocr_text: str = "") -> str:
    return build_context_prompt(context, ocr_text or "No extractable OCR text was found.")


async def call_deepseek_contextual_alt_text(
    image_url_or_bytes: str,
    api_key: str,
    context: AltTextContext,
    tessdata_path: Optional[str] = None,
) -> str:
    ocr_text = _extract_ocr_text(image_url_or_bytes, tessdata_path)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        payload = {
            "model": "deepseek-chat",
            "messages": build_deepseek_messages(image_url_or_bytes, context, ocr_text),
            "max_tokens": 100,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.deepseek.com/v1/chat/completions",
                json=payload,
                headers=headers,
            )
        if response.status_code == 200:
            return _clean_alt_text(response.json()["choices"][0]["message"]["content"])
        logger.info(
            "DeepSeek contextual vision call returned status %s: %s. Trying text fallback.",
            response.status_code,
            response.text,
        )
    except Exception as exc:
        logger.info("DeepSeek contextual vision call failed: %s. Trying text fallback.", exc)

    try:
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": ALT_TEXT_SYSTEM_PROMPT},
                {"role": "user", "content": build_text_fallback_prompt(context, ocr_text)},
            ],
            "max_tokens": 100,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.deepseek.com/v1/chat/completions",
                json=payload,
                headers=headers,
            )
        if response.status_code == 200:
            return _clean_alt_text(response.json()["choices"][0]["message"]["content"])
        raise Exception(f"DeepSeek API error: {response.text}")
    except Exception as exc:
        logger.error("DeepSeek contextual text fallback failed: %s", exc)
        if ocr_text:
            return trim_context_text(f"Image containing text: {ocr_text}", 150)
        return "Image description unavailable"


def _extract_ocr_text(image_url_or_bytes: str, tessdata_path: Optional[str]) -> str:
    if not tessdata_path or not image_url_or_bytes.startswith("data:image/"):
        return ""

    try:
        import fitz

        _, base64_str = image_url_or_bytes.split(",", 1)
        image_bytes = base64.b64decode(base64_str)
        pix = fitz.Pixmap(image_bytes)
        if pix.alpha:
            pix = fitz.Pixmap(pix, 0)
        ocr_bytes = pix.pdfocr_tobytes(language="eng", tessdata=tessdata_path)
        with fitz.open("pdf", ocr_bytes) as ocr_doc:
            text = normalize_text(ocr_doc[0].get_text())
        if text:
            logger.info("OCR extracted text for contextual alt text: %r", text)
        return text
    except Exception as exc:
        logger.warning("OCR fallback extraction failed: %s", exc)
        return ""


def _clean_alt_text(value: str) -> str:
    return normalize_text(value).strip('"' + "'")


def _is_model_image_url(value: str) -> bool:
    return value.startswith(("data:image/", "http://", "https://"))
