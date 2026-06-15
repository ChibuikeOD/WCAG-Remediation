from pathlib import Path

import fitz

from backend.models import DocumentImageItem
from backend.alt_text_context import (
    build_alt_text_context,
    extract_html_images,
    trim_context_text,
)


def test_html_context_uses_caption_heading_and_neighboring_images(tmp_path: Path):
    html_path = tmp_path / "paper.html"
    html_path.write_text(
        """
        <!doctype html>
        <html>
          <head><title>Climate Adaptation Report</title></head>
          <body>
            <h1>Climate Adaptation in Coastal Cities</h1>
            <p>This paper compares flood exposure and infrastructure resilience.</p>
            <figure>
              <img src="before.png" alt="">
              <figcaption>Figure 1. Baseline flood exposure by district.</figcaption>
            </figure>
            <p>The following figure summarizes adaptation investment priorities.</p>
            <figure>
              <img src="target.png" alt="">
              <figcaption>Figure 2. Priority adaptation investments by region.</figcaption>
            </figure>
            <figure>
              <img src="after.png" alt="">
              <figcaption>Figure 3. Projected residual risk after adaptation.</figcaption>
            </figure>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    images = extract_html_images(html_path)
    context = build_alt_text_context(
        html_path,
        "html",
        images,
        images[1],
        context_mode="balanced",
    )

    assert context.document_title == "Climate Adaptation Report"
    assert "Climate Adaptation in Coastal Cities" in context.headings
    assert context.caption == "Figure 2. Priority adaptation investments by region."
    assert "adaptation investment priorities" in context.page_text
    assert [img.id for img in context.neighboring_images] == ["html_img_0", "html_img_2"]
    assert context.context_used()["caption"] is True
    assert context.context_used()["neighboring_images"] == 2


def test_trim_context_text_is_deterministic():
    text = "word " * 200

    trimmed = trim_context_text(text, 40)

    assert len(trimmed) <= 40
    assert trimmed.endswith("...")


def test_pdf_context_uses_page_text_caption_and_adjacent_page_summaries(tmp_path: Path):
    pdf_path = tmp_path / "paper.pdf"
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_text((72, 72), "Methods define regional climate risk indicators.")
    page2 = doc.new_page()
    page2.insert_text((72, 72), "Climate Adaptation Results")
    page2.insert_text((72, 140), "Figure 2. Priority adaptation investments by region.")
    page2.insert_text((72, 190), "The map compares flood defenses, drainage, and relocation priorities.")
    page3 = doc.new_page()
    page3.insert_text((72, 72), "Residual risk remains highest in low-lying districts.")
    doc.save(pdf_path)
    doc.close()

    target = DocumentImageItem(
        id="fig_2",
        page_num=2,
        current_alt="",
        image_url="data:image/png;base64,TARGET",
        figure_order=1,
        bbox=[50, 100, 300, 240],
    )

    context = build_alt_text_context(
        pdf_path,
        "pdf",
        [target],
        target,
        context_mode="balanced",
    )

    assert context.caption == "Figure 2. Priority adaptation investments by region."
    assert "flood defenses" in context.page_text
    assert "regional climate risk indicators" in context.previous_page_text
    assert "Residual risk remains highest" in context.next_page_text
