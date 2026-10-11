import hashlib
import json

import fitz
import pikepdf
import pytest

from backend.pdf_reviewed_table_projections import apply_reviewed_table_projections
from backend.tests.test_pdf_reviewed_figures import fixture as graphic_fixture


def fixture(tmp_path,fault=None):
    original,working,_=graphic_fixture(tmp_path,form=True)
    with pikepdf.open(working,allow_overwriting_input=True) as pdf:
        root=pdf.Root.StructTreeRoot;page=pdf.pages[0];figure=root.K[0]
        document=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructElem'),S=pikepdf.Name('/Document'),P=root))
        figure.P=document;root.K=pikepdf.Array([document]);page.StructParents=7
        slots=pikepdf.Array([None]*15);slots[14]=figure
        root.ParentTree=pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array([7,slots])))
        table=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructElem'),S=pikepdf.Name('/Table'),Pg=page.obj,P=document))
        row=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructElem'),S=pikepdf.Name('/TR'),P=table))
        cells=[]
        for role,box in [('/TH',[25,55,37.5,70]),('/TD',[37.5,55,50,70])]:
            cell=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructElem'),S=pikepdf.Name(role),P=row,K=pikepdf.Array([]),A=pikepdf.Dictionary(O=pikepdf.Name('/Layout'),BBox=pikepdf.Array(box))))
            cells.append(cell)
        row.K=pikepdf.Array(cells);table.K=pikepdf.Array([row]);document.K=pikepdf.Array([figure,table])
        if fault=='ID':cells[0].ID=pikepdf.String('keep-this-header')
        elif fault=='Headers':cells[1].A.Headers=pikepdf.Array([pikepdf.String('keep-this-header')])
        elif fault=='owned_content':cells[1].K=pikepdf.Array([14])
        elif fault=='parenttree':slots[14]=table
        elif fault=='cross_page':figure.K=pikepdf.Array([14,pikepdf.Dictionary(Type=pikepdf.Name('/MCR'),Pg=page.obj,MCID=99)])
        elif fault=='reference':root.IDTree=pikepdf.Dictionary(Names=pikepdf.Array([pikepdf.String('external'),table]))
        elif fault=='external_ref':figure.Ref=pikepdf.Array([table])
        elif fault=='wrong_parent':row.P=document
        elif fault=='extra_paint':page.Contents.write(page.Contents.read_bytes().replace(b' EMC',b' 0 0 3 3 re f EMC'))
        elif fault=='protected_ancestor':document.S=pikepdf.Name('/Reference')
        pdf.save(working,compress_streams=False)
    with pikepdf.open(original) as pdf:payload=hashlib.sha256(pdf.pages[0].Resources.XObject.Im.read_bytes()).hexdigest()
    record=dict(review_id='one-reviewed-projection',classification='FIGURE_PLOT_WRONGLY_DETECTED_AS_TABLE',
                review_status='REVIEWED_SOURCE_SPECIFIC_MODEL_VISUAL_AND_OWNERSHIP',
                original_input_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),physical_page=1,
                full_detected_table_bbox_pdf=[25,55,50,70],current_TR_count=1,current_cell_role_counts={'/TH':1,'/TD':1},
                existing_actual_payload_owner={'current_Figure_layout_bboxes_pdf':[[20,50,100,110]],
                  'actual_Do_source_payload_proof':{'candidate_Do':{'resource_subtype':'/Form','decoded_resource_sha256':payload}}})
    if fault=='source':record['original_input_sha256']='0'*64
    elif fault=='invalid_page':record['physical_page']=0
    elif fault=='payload':record['existing_actual_payload_owner']['actual_Do_source_payload_proof']['candidate_Do']['decoded_resource_sha256']='0'*64
    sidecar=tmp_path/'projection.json';sidecar.write_text(json.dumps(dict(schema_version='pdfaccess.table-projection-classification.v1',classifications=[record,record] if fault=='duplicate_review' else [record])))
    return original,working,sidecar


def test_reviewed_empty_duplicate_structure_removed_with_exact_painting(tmp_path):
    original,working,sidecar=fixture(tmp_path);source=original.read_bytes()
    with fitz.open(working) as pdf:pixels=pdf[0].get_pixmap(dpi=96,alpha=False).samples;text=pdf[0].get_text()
    result=apply_reviewed_table_projections(working,original,[sidecar])
    assert result['applied']==1 and result['unmatched']==0,result
    with pikepdf.open(working) as pdf:
        document=pdf.Root.StructTreeRoot.K[0]
        assert len(document.K)==1 and str(document.K[0].S)=='/Figure'
        assert int(document.K[0].K)==14
        assert pdf.Root.StructTreeRoot.ParentTree.Nums[1][14].objgen==document.K[0].objgen
    with fitz.open(working) as pdf:
        assert pdf[0].get_pixmap(dpi=96,alpha=False).samples==pixels and pdf[0].get_text()==text
    assert original.read_bytes()==source and result['external_provider_invoked'] is False


@pytest.mark.parametrize('fault',['ID','Headers','owned_content','parenttree','cross_page','reference','external_ref','wrong_parent','extra_paint','protected_ancestor','source','payload','invalid_page','duplicate_review'])
def test_unverified_or_dependent_projection_retained_byte_exact(tmp_path,fault):
    original,working,sidecar=fixture(tmp_path,fault);before=working.read_bytes();source=original.read_bytes()
    result=apply_reviewed_table_projections(working,original,[sidecar])
    assert result['applied']==0 and result['unmatched']==(2 if fault=='duplicate_review' else 1)
    assert working.read_bytes()==before and original.read_bytes()==source


def test_pipeline_routes_actual_reviewed_projection_and_retains_result(tmp_path,monkeypatch):
    from backend import config,pdf_remediator_fixes as fixes,pdf_link_descriptions
    from backend.remediator import PDFRemediator
    original,working,sidecar=fixture(tmp_path)
    engine=PDFRemediator(working,reviewed_table_projection_sidecars=[sidecar],reviewed_table_projection_original=original)
    monkeypatch.setattr(config.settings,'DISABLE_OPENDATALOADER',False)
    monkeypatch.setattr(engine,'fix_metadata',lambda **kwargs:[])
    monkeypatch.setattr(engine,'auto_tag_document',lambda **kwargs:dict(success=True,tags_created=1,pages_processed=1,tag_counts={'Figure':1}))
    for name in ('fix_scanned_pages','fix_pdf_unicode_mappings','inject_link_annotations','fix_content_stream_operator_states','fix_heading_hierarchy','fix_table_headers','fix_list_structure','fix_span_overuse','fix_reading_order','fix_untagged_urls','fix_bookmarks','fix_form_labels','fix_tab_order'):
        monkeypatch.setattr(fixes,name,lambda path:dict(issue_id='test',success=True,message='ok'))
    monkeypatch.setattr(pdf_link_descriptions,'repair_link_descriptions',lambda path:dict(issue_id='test',success=True,message='ok'))
    results=engine.fix_all()
    result=next(item for item in results if item.issue_id=='pdf-reviewed-table-projections')
    assert result.success and result.details['applied']==1 and result.details['unmatched']==0
    with pikepdf.open(working) as pdf:assert len(pdf.Root.StructTreeRoot.K[0].K)==1


def test_mixed_source_sidecars_select_matching_source_without_false_unmatched(tmp_path):
    original,working,sidecar=fixture(tmp_path)
    other=json.loads(sidecar.read_text());other['classifications'][0]['original_input_sha256']='f'*64
    other['classifications'][0]['review_id']='other-document-review'
    other['source_literal_note']='Greek ν and literal decimal 0,2179 stay unchanged'
    foreign=tmp_path/'other-source.json';foreign.write_text(json.dumps(other,ensure_ascii=False),encoding='utf-8-sig')
    result=apply_reviewed_table_projections(working,original,[sidecar,foreign])
    assert result['applied']==1 and result['unmatched']==0 and result['considered']==1
    assert result['other_source_records']==1


def test_no_matching_source_review_is_explicit_failure_and_no_write(tmp_path):
    original,working,sidecar=fixture(tmp_path,'source');before=working.read_bytes()
    result=apply_reviewed_table_projections(working,original,[sidecar])
    assert result['applied']==0 and result['unmatched']==1 and result['considered']==0
    assert result['other_source_records']==1 and 'original SHA mismatch' in result['unmatched_records'][0]['reason']
    assert working.read_bytes()==before
