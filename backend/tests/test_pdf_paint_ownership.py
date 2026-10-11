import pikepdf

from backend.pdf_paint_ownership import text_show_ownership


def test_per_show_glyph_ownership_preserves_tj_advance_and_quote_spacing():
    with pikepdf.new() as pdf:
        page=pdf.add_blank_page(page_size=(300,300))
        font=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/Font'),Subtype=pikepdf.Name('/Type1'),BaseFont=pikepdf.Name('/Helvetica')))
        page.Resources=pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
        page.Contents=pdf.make_stream(b'BT /F1 12 Tf 1 0 0 1 20 250 Tm /P <</MCID 4>> BDC (AB) Tj (CD) Tj EMC 15 TL 3 1 (E F) " (GH) Tj ET')
        before=page.Contents.read_bytes()
        result=text_show_ownership(pdf,0)
        assert result['nonspace_glyph_geometry_verified'] and not result['unassigned_glyphs']
        assert [''.join(g['text'] for g in show['glyphs']) for show in result['shows']]==['AB','CD','EF','GH']
        assert result['shows'][0]['marked_content']==[{'tag':'/P','mcid':4}]
        assert result['shows'][1]['glyphs'][0]['origin'][0]>result['shows'][0]['glyphs'][-1]['origin'][0]
        assert page.Contents.read_bytes()==before


def test_nested_form_text_is_unassigned_not_page_mcid():
    with pikepdf.new() as pdf:
        page=pdf.add_blank_page(page_size=(300,300))
        font=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/Font'),Subtype=pikepdf.Name('/Type1'),BaseFont=pikepdf.Name('/Helvetica')))
        form=pdf.make_stream(b'BT /F1 12 Tf 1 0 0 1 20 100 Tm /P <</MCID 4>> BDC (Form) Tj EMC ET')
        form.Type=pikepdf.Name('/XObject');form.Subtype=pikepdf.Name('/Form');form.BBox=pikepdf.Array([0,0,200,200])
        form.Resources=pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
        page.Resources=pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font),XObject=pikepdf.Dictionary(Form=form))
        page.Contents=pdf.make_stream(b'/Figure <</MCID 4>> BDC /Form Do EMC BT /F1 12 Tf 1 0 0 1 20 250 Tm (Page) Tj ET')
        result=text_show_ownership(pdf,0)
        assert ''.join(g['text'] for g in result['shows'][0]['glyphs'])=='Page'
        assert ''.join(g['text'] for g in result['unassigned_glyphs'])=='Form'
