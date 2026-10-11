from io import BytesIO

import fitz
from PIL import Image
import pikepdf
import pytest

from backend import config, pdf_remediator_fixes as fixes
from backend.pdf_ocr_overlay import _image_payloads
from backend.tests.test_pdf_reviewed_glyph_rewrite import indirect_fixture


def test_sparse_type3_digital_page_is_not_rasterized(tmp_path, monkeypatch):
    original, _ = indirect_fixture(tmp_path)
    before = original.read_bytes()
    monkeypatch.setattr(config.settings, 'DISABLE_OCR', False)
    monkeypatch.setattr(fixes, '_resolve_tessdata', lambda: pytest.fail('font-only page must not request OCR'))
    result = fixes.fix_scanned_pages(original)
    assert result['success'] and result['details']['pages_overlaid'] == 0
    assert result['details']['digital_pages_preserved'] == [1]
    assert not result['details']['output_rasterized']
    assert original.read_bytes() == before
    with pikepdf.open(original) as pdf:
        assert str(pdf.pages[0].Resources.Font.F16.Subtype) == '/Type3'


@pytest.mark.parametrize('rotation', [0,90])
def test_raster_scan_receives_only_invisible_text_original_payload_unchanged(tmp_path,monkeypatch,rotation):
    source = tmp_path / 'scan.pdf'
    image = BytesIO();Image.new('RGB',(20,30),(40,90,160)).save(image,format='PNG')
    with fitz.open() as pdf:
        page=pdf.new_page(width=200,height=300)
        page.insert_image(page.rect,stream=image.getvalue());page.set_rotation(rotation)
        pdf.save(source)
        size=(page.rect.width,page.rect.height)
        pixels=page.get_pixmap(dpi=96).samples
    with pikepdf.open(source) as pdf: payloads=_image_payloads(pdf)
    with fitz.open() as ocr:
        page=ocr.new_page(width=size[0],height=size[1])
        page.insert_image(page.rect,stream=image.getvalue())
        # Recognition output contains visible text and its recognition raster.
        # The helper must discard that raster and make the text invisible.
        page.insert_text((30,40),'Scan text',fontsize=12)
        expected_box=fitz.Rect(page.get_text('words')[0][:4])
        layer=ocr.tobytes()
    monkeypatch.setattr(config.settings,'DISABLE_OCR',False)
    monkeypatch.setattr(fixes,'_resolve_tessdata',lambda:'fixture-only-no-live-tesseract')
    monkeypatch.setattr(fitz.Pixmap,'pdfocr_tobytes',lambda self,**kwargs:layer)
    result=fixes.fix_scanned_pages(source)
    assert result['success'],result
    assert result['details']['pages_overlaid']==1
    assert result['details']['source_raster_payloads_preserved']
    assert not result['details']['output_rasterized']
    with pikepdf.open(source) as pdf:
        assert _image_payloads(pdf)==payloads
    with fitz.open(source) as pdf:
        assert pdf[0].get_pixmap(dpi=96).samples==pixels
        assert pdf[0].get_text().strip()=='Scan text'
        word=pdf[0].get_text('words')[0]
        visible_box=fitz.Rect(word[:4])*pdf[0].rotation_matrix
        assert tuple(visible_box)==pytest.approx(tuple(expected_box),abs=.01)


def test_partial_raster_region_is_preserved_and_flagged(tmp_path,monkeypatch):
    source=tmp_path/'partial.pdf';image=BytesIO();Image.new('RGB',(20,20),'white').save(image,format='PNG')
    with fitz.open() as pdf:
        page=pdf.new_page(width=200,height=200);page.insert_image(fitz.Rect(20,20,140,140),stream=image.getvalue());pdf.save(source)
    before=source.read_bytes()
    monkeypatch.setattr(config.settings,'DISABLE_OCR',False)
    monkeypatch.setattr(fixes,'_resolve_tessdata',lambda:pytest.fail('unconfirmed raster region must not request OCR'))
    result=fixes.fix_scanned_pages(source)
    assert not result['success'] and result['details']['unresolved_raster_pages'][0]['page']==1
    assert source.read_bytes()==before
