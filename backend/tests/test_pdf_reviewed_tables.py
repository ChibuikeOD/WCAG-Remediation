import pikepdf
import pytest
import fitz
from io import BytesIO
import hashlib
import json
import shutil

from backend.pdf_reviewed_tables import _prune_removed, _rewrite_table_page, _page_owners, bind_table_text_shows, apply_reviewed_table_grids


def fixture():
    pdf = pikepdf.new()
    page = pdf.add_blank_page(page_size=(300, 300))
    other = pdf.add_blank_page(page_size=(300, 300))
    font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/Font'), Subtype=pikepdf.Name('/Type1'), BaseFont=pikepdf.Name('/Helvetica')))
    page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
    page.Contents = pdf.make_stream(b'BT /F1 12 Tf 20 250 Td /P <</MCID 0>> BDC (Header) Tj 0 -20 Td (Body) Tj EMC ET /Artifact BMC 10 10 20 20 re S EMC')
    root = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructTreeRoot')))
    doc = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructElem'), S=pikepdf.Name('/Document'), P=root))
    old = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructElem'), S=pikepdf.Name('/P'), P=doc, Pg=page.obj, K=0))
    empty = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructElem'), S=pikepdf.Name('/TD'), P=doc, Pg=other.obj, K=pikepdf.Array([])))
    other_owner = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructElem'), S=pikepdf.Name('/P'), P=doc, Pg=other.obj, K=0))
    doc.K = pikepdf.Array([old, empty, other_owner]); root.K = doc
    root.ParentTree = pikepdf.Dictionary(Nums=pikepdf.Array([0, pikepdf.Array([old]), 1, pikepdf.Array([other_owner])]))
    page.StructParents = 0; other.StructParents = 1; pdf.Root.StructTreeRoot = root
    instructions = list(pikepdf.parse_content_stream(page))
    shows = [i for i, inst in enumerate(instructions) if str(inst[1]) == 'Tj']
    cells = [dict(id='h', row=0, col=0, rowspan=1, colspan=1, role='TH', scope='Column', headers=[]), dict(id='d', row=1, col=0, rowspan=1, colspan=1, role='TD', scope=None, headers=['h'])]
    table = dict(id='table', sha='a'*64, cells=cells)
    binding = dict(assignments=dict(zip(shows, ['h', 'd'])), cell_show_order={'h': [shows[0]], 'd': [shows[1]]})
    return pdf, page, other, doc, empty, other_owner, table, binding


def test_rebuild_preserves_unrelated_empty_structure_and_explicit_header_order():
    pdf, page, other, doc, empty, other_owner, table, binding = fixture()
    with pdf:
        old_paint = [(list(i[0]), str(i[1])) for i in pikepdf.parse_content_stream(page) if str(i[1]) not in ('BDC', 'BMC', 'EMC')]
        result = _rewrite_table_page(pdf, page, [(table, binding)])
        assert result == {'new_mcids': 2, 'removed_mcids': 1, 'table_cells': 2}
        assert [str(n.S) for n in doc.K] == ['/Table', '/TD', '/P']
        assert doc.K[1].objgen == empty.objgen and not len(empty.K)
        assert doc.K[2].objgen == other_owner.objgen and other_owner.K == 0
        header, body = doc.K[0].K[0].K[0], doc.K[0].K[1].K[0]
        assert str(header.S) == '/TH' and str(header.A.Scope) == '/Column'
        assert [str(x) for x in body.A.Headers] == [str(header.ID)]
        assert header.K[0].MCID == 1 and body.K[0].MCID == 2
        owners = _page_owners(pdf.Root.StructTreeRoot, page)
        assert owners[1].objgen == header.objgen and owners[2].objgen == body.objgen
        assert pdf.Root.StructTreeRoot.ParentTree.Nums[3][0].objgen == other_owner.objgen
        new_paint = [(list(i[0]), str(i[1])) for i in pikepdf.parse_content_stream(page) if str(i[1]) not in ('BDC', 'BMC', 'EMC')]
        assert old_paint == new_paint
        assert b'/Artifact BMC' in page.Contents.read_bytes()


def test_form_mcid_namespace_and_other_page_mcid_are_never_pruned():
    with pikepdf.new() as pdf:
        page = pdf.add_blank_page(); other = pdf.add_blank_page()
        form = pdf.make_stream(b'')
        refs = pikepdf.Array([pikepdf.Dictionary(Type=pikepdf.Name('/MCR'), Pg=page.obj, MCID=0), pikepdf.Dictionary(Type=pikepdf.Name('/MCR'), Pg=page.obj, Stm=form, MCID=0), pikepdf.Dictionary(Type=pikepdf.Name('/MCR'), Pg=other.obj, MCID=0)])
        kept = _prune_removed(refs, page.obj.objgen, {0})
        assert len(kept) == 2 and kept[0].Stm.objgen == form.objgen and kept[1].Pg.objgen == other.obj.objgen


@pytest.mark.parametrize('role', ['Link', 'Formula', 'Note', 'Reference'])
def test_explicit_inline_semantics_are_rejected_before_rewriting(role):
    pdf, page, _, doc, _, _, table, binding = fixture()
    with pdf:
        doc.K[0].S = pikepdf.Name('/'+role)
        before = page.Contents.read_bytes()
        with pytest.raises(ValueError, match='explicit inline semantics'):
            _rewrite_table_page(pdf, page, [(table, binding)])
        assert page.Contents.read_bytes() == before


def test_header_cycles_are_rejected_without_reaching_paint_assignment():
    pdf, page, _, _, _, _, table, _ = fixture()
    with pdf:
        table['cells'][0]['headers'] = ['h']
        with pytest.raises(ValueError, match='cyclic reviewed header'):
            bind_table_text_shows(table, None, pdf)


def test_raster_cell_without_native_paint_ownership_cannot_become_empty_td():
    pdf, _, _, _, _, _, table, _ = fixture()
    with pdf:
        table['cells'][1]['raster_literal_without_native_glyphs'] = True
        with pytest.raises(ValueError, match='raster cell requires verified image-region'):
            bind_table_text_shows(table, None, pdf)


@pytest.mark.parametrize('role', ['Link', 'Formula', 'Note', 'Reference'])
def test_nested_span_cannot_erase_explicit_semantic_ancestor(role):
    pdf, page, _, doc, _, _, table, binding = fixture()
    with pdf:
        parent = doc.K[0]; parent.S = pikepdf.Name('/'+role)
        span = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructElem'), S=pikepdf.Name('/Span'), P=parent, Pg=page.obj, K=0))
        parent.K = span
        before = page.Contents.read_bytes()
        with pytest.raises(ValueError, match='explicit inline semantics'):
            _rewrite_table_page(pdf, page, [(table, binding)])
        assert page.Contents.read_bytes() == before and parent.K.objgen == span.objgen


def test_duplicate_page_mcid_owners_rejected_before_mutation():
    pdf, page, _, doc, _, _, table, binding = fixture()
    with pdf:
        duplicate = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructElem'), S=pikepdf.Name('/P'), P=doc, Pg=page.obj, K=0))
        doc.K.append(duplicate);before=page.Contents.read_bytes()
        with pytest.raises(ValueError, match='duplicate page MCID'):
            _rewrite_table_page(pdf, page, [(table, binding)])
        assert page.Contents.read_bytes()==before and len(doc.K)==4


def test_existing_mcid_with_non_table_vector_paint_is_rejected():
    pdf, page, _, _, _, _, table, binding = fixture()
    with pdf:
        page.Contents = pdf.make_stream(page.Contents.read_bytes().replace(b'EMC ET', b'10 10 20 20 re S EMC ET'))
        before = page.Contents.read_bytes()
        with pytest.raises(ValueError, match='owns non-table painting'):
            _rewrite_table_page(pdf, page, [(table, binding)])
        assert page.Contents.read_bytes() == before


def test_binding_proves_literal_glyph_ownership_and_rejects_cross_cell_show():
    pdf, page, _, _, _, _, table, expected = fixture()
    with pdf:
        buffer = BytesIO(); pdf.save(buffer)
        with fitz.open(stream=buffer.getvalue(), filetype='pdf') as source:
            lines = [line for block in source[0].get_text('rawdict')['blocks'] for line in block.get('lines', [])]
            for cell, line in zip(table['cells'], lines):
                cell['glyphs'] = [dict(text=c['c'], origin=list(c['origin'])) for s in line['spans'] for c in s['chars']]
            table.update(page=1, source_format='B', caption_words=[])
            actual = bind_table_text_shows(table, source[0], pdf)
            assert actual['assignments'] == expected['assignments']
            assert actual['cell_show_order'] == expected['cell_show_order']
            assert actual['source_glyph_count'] == 10
            table['cells'][1]['glyphs'].append(table['cells'][0]['glyphs'].pop())
            with pytest.raises(ValueError, match='crosses reviewed cell'):
                bind_table_text_shows(table, source[0], pdf)


def test_source_bound_public_grid_application_preserves_original_text_pixels_and_headers(tmp_path):
    pdf, _, _, _, _, _, table, _ = fixture()
    original=tmp_path/'original.pdf';working=tmp_path/'working.pdf';sidecar=tmp_path/'review.json'
    with pdf:pdf.save(original)
    original_bytes=original.read_bytes();shutil.copyfile(original,working)
    with fitz.open(original) as source:
        lines=[line for block in source[0].get_text('rawdict')['blocks'] for line in block.get('lines', [])]
        before_pixels=source[0].get_pixmap(dpi=96,alpha=False).samples;before_text=source[0].get_text()
        cells=[]
        for cell,line in zip(table['cells'],lines):
            cells.append(dict(cell_id=cell['id'],physical_grid_row_1_based=cell['row']+1,column_1_based=1,
                row_span=1,column_span=1,proposed_role=cell['role'],proposed_scope=cell['scope'],header_refs=cell['headers'],
                glyphs=[dict(literal_char=c['c'],origin_mupdf=list(c['origin'])) for s in line['spans'] for c in s['chars']],
                literal_text_from_native_words=''.join(c['c'] for s in line['spans'] for c in s['chars']),
                allocation_bbox_pdf_bottom_left_points=[0,0,300,300]))
    sidecar.write_text(json.dumps({'records':[dict(proposal_id='real-grid',original=dict(sha256=hashlib.sha256(original_bytes).hexdigest(),physical_page_1_based=1),
        cells=cells,caption_binding=dict(visible_anchor='',native_literal_words=[]))]}))
    result=apply_reviewed_table_grids(working,original,[sidecar])
    assert result['applied_tables']==1 and result['applied_cells']==2 and not result['unmatched_tables']
    assert not result['external_provider_invoked'] and original.read_bytes()==original_bytes
    with fitz.open(working) as after:
        assert after[0].get_text()==before_text and after[0].get_pixmap(dpi=96,alpha=False).samples==before_pixels
    with pikepdf.open(working) as after:
        rebuilt=after.Root.StructTreeRoot.K.K[0]
        header=rebuilt.K[0].K[0];body=rebuilt.K[1].K[0]
        assert str(header.S)=='/TH' and str(body.S)=='/TD'
        assert str(body.A.Headers[0])==str(header.ID)
