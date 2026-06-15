from backend.alt_text_context import AltTextContext, NeighboringImageContext
from backend.deepseek_alt_text import (
    ALT_TEXT_SYSTEM_PROMPT,
    build_deepseek_messages,
    build_text_fallback_prompt,
)


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


def test_build_deepseek_messages_includes_system_prompt_and_balanced_context():
    messages = build_deepseek_messages("data:image/png;base64,TARGET", _context(), ocr_text="Region A 42%")

    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == ALT_TEXT_SYSTEM_PROMPT
    assert messages[1]["role"] == "user"

    content = messages[1]["content"]
    text_parts = [part["text"] for part in content if part["type"] == "text"]
    image_parts = [part for part in content if part["type"] == "image_url"]

    joined_text = "\n".join(text_parts)
    assert "Climate Adaptation Report" in joined_text
    assert "Figure 2. Priority adaptation investments by region." in joined_text
    assert "Figure 1. Baseline flood exposure by district." in joined_text
    assert "Region A 42%" in joined_text
    assert "Return only the alt text" in joined_text
    assert image_parts[0]["image_url"]["url"] == "data:image/png;base64,TARGET"


def test_text_fallback_prompt_includes_ocr_and_context_without_image_payload():
    prompt = build_text_fallback_prompt(_context(), ocr_text="Region A 42%")

    assert "Region A 42%" in prompt
    assert "Climate Adaptation Report" in prompt
    assert "Priority adaptation investments" in prompt
    assert "Return only the alt text" in prompt
