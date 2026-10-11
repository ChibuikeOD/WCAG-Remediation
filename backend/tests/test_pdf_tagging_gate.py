import ast
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any,List,Optional

import pikepdf
import pytest

from backend.pdf_tagging_gate import RequiredPDFTaggingError, require_pdf_tagging


def candidate(tmp_path, structure=True):
    path=tmp_path/'candidate.pdf'
    with pikepdf.Pdf.new() as pdf:
        page=pdf.add_blank_page(page_size=(72,72))
        if structure:
            root=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructTreeRoot')))
            owner=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructElem'),S=pikepdf.Name('/P'),P=root,Pg=page.obj,K=0))
            root.K=pikepdf.Array([owner]);root.ParentTree=pikepdf.Dictionary(Nums=pikepdf.Array([0,pikepdf.Array([owner])]))
            pdf.Root.StructTreeRoot=root;page.StructParents=0
            page.Contents=pdf.make_stream(b'/P <</MCID 0>> BDC 0 0 2 2 re f EMC')
        pdf.save(path)
    return path


def test_timeout_is_unsuccessful_even_if_an_old_structure_tree_survives(tmp_path):
    path=candidate(tmp_path);before=path.read_bytes()
    with pytest.raises(RequiredPDFTaggingError,match='UNSUCCESSFUL.*timed out') as caught:
        require_pdf_tagging(path,tagging_required=True,tagging_result=dict(success=False,error='OpenDataLoader timed out after 180s'))
    assert caught.value.status=='UNSUCCESSFUL' and caught.value.working_path==str(path)
    assert path.read_bytes()==before


def test_claimed_success_without_output_structure_cannot_be_published(tmp_path):
    path=candidate(tmp_path,False);before=path.read_bytes()
    with pytest.raises(RequiredPDFTaggingError,match='no StructTreeRoot'):
        require_pdf_tagging(path,tagging_required=True,tagging_result=dict(success=True))
    assert path.read_bytes()==before


@pytest.mark.parametrize('fault',['children','parenttree','entries'])
def test_incomplete_structural_output_fails_postcondition(tmp_path,fault):
    path=candidate(tmp_path)
    with pikepdf.open(path,allow_overwriting_input=True) as pdf:
        root=pdf.Root.StructTreeRoot
        if fault=='children':root.K=pikepdf.Array([])
        elif fault=='parenttree':del root.ParentTree
        else:root.ParentTree=pikepdf.Dictionary()
        pdf.save(path)
    with pytest.raises(RequiredPDFTaggingError,match='postcondition failed'):
        require_pdf_tagging(path,tagging_required=True,tagging_result=dict(success=True))


def test_existing_structure_can_be_repaired_when_rebuild_is_explicitly_disabled(tmp_path):
    path=candidate(tmp_path)
    require_pdf_tagging(path,tagging_required=False)


def test_disabling_tagging_does_not_authorize_missing_structure(tmp_path):
    with pytest.raises(RequiredPDFTaggingError,match='no StructTreeRoot'):
        require_pdf_tagging(candidate(tmp_path,False),tagging_required=False)


def test_successful_tagging_gate_does_not_claim_native_validity(tmp_path):
    path=candidate(tmp_path)
    assert require_pdf_tagging(path,tagging_required=True,tagging_result=dict(success=True)) is None


@pytest.mark.parametrize('fault',['no-paint','missing-marking','wrong-parent','duplicate-mcid','cycle'])
def test_metadata_only_or_mismatched_content_ownership_never_passes(tmp_path,fault):
    path=candidate(tmp_path)
    with pikepdf.open(path,allow_overwriting_input=True) as pdf:
        page=pdf.pages[0];root=pdf.Root.StructTreeRoot
        if fault=='no-paint':page.Contents=pdf.make_stream(b'/P <</MCID 0>> BDC EMC')
        elif fault=='missing-marking':page.Contents=pdf.make_stream(b'0 0 2 2 re f')
        elif fault=='wrong-parent':root.ParentTree.Nums[1][0]=root
        elif fault=='duplicate-mcid':page.Contents=pdf.make_stream(b'/P <</MCID 0>> BDC 0 0 2 2 re f EMC /P <</MCID 0>> BDC 0 0 2 2 re f EMC')
        else:root.K[0].K=root.K[0]
        pdf.save(path)
    with pytest.raises(RequiredPDFTaggingError,match='postcondition failed'):
        require_pdf_tagging(path,tagging_required=True,tagging_result=dict(success=True))


def test_structure_depth_budget_stops_pathological_input(tmp_path):
    path=candidate(tmp_path)
    with pikepdf.open(path,allow_overwriting_input=True) as pdf:
        root=pdf.Root.StructTreeRoot;node=root.K[0]
        for _ in range(260):
            child=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructElem'),S=pikepdf.Name('/Span'),P=node))
            node.K=child;node=child
        node.K=0;pdf.save(path)
    with pytest.raises(RequiredPDFTaggingError,match='traversal budget exceeded'):
        require_pdf_tagging(path,tagging_required=True,tagging_result=dict(success=True))


@pytest.mark.parametrize('failure',['timeout','missing-output','manual-hold'])
def test_full_pipeline_gate_stops_before_structural_repairs_but_allows_review_holds(tmp_path,monkeypatch,failure):
    source=Path(__file__).parents[1]/'remediator.py';tree=ast.parse(source.read_text(encoding='utf-8-sig'))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='PDFRemediator')
    method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='fix_all')
    cutoff=next(i for i,n in enumerate(method.body) if isinstance(n,ast.ImportFrom) and n.module=='pdf_link_descriptions')
    method.body=method.body[:cutoff]+ast.parse("downstream(results)\nreturn results").body
    calls=[]
    def downstream(results):
        calls.append('downstream')
        results.append(SimpleNamespace(issue_id='pdf-reviewed-graphic-groups',success=False,details={'held':['typed list']}))
    namespace=dict(__package__='backend',Path=Path,Optional=Optional,List=List,Any=Any,RemediationResult=SimpleNamespace,
        logger=SimpleNamespace(info=lambda *a,**kw:None,error=lambda *a,**kw:None),downstream=downstream)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),str(source),'exec'),namespace)
    path=candidate(tmp_path,failure!='missing-output')
    fix=lambda *a,**kw:dict(issue_id='test-fix',success=True,message='measured fixture')
    monkeypatch.setitem(sys.modules,'backend.pdf_remediator_fixes',SimpleNamespace(fix_scanned_pages=fix,fix_pdf_unicode_mappings=fix,inject_link_annotations=fix))
    monkeypatch.setitem(sys.modules,'backend.config',SimpleNamespace(settings=SimpleNamespace(DISABLE_OPENDATALOADER=False)))
    result=dict(success=failure!='timeout',tags_created=1,pages_processed=1,tag_counts={'P':1},error='timed out after 180s')
    subject=SimpleNamespace(file_path=path,reviewed_glyph_sidecar=None,reviewed_math_sidecar=None,
        fix_metadata=lambda **kw:[],auto_tag_document=lambda **kw:result)
    if failure=='manual-hold':
        results=namespace['fix_all'](subject)
        assert calls==['downstream'] and results[-1].details['held']==['typed list']
    else:
        with pytest.raises(RequiredPDFTaggingError):namespace['fix_all'](subject)
        assert not calls
