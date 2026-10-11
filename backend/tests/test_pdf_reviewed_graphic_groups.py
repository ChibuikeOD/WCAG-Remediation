import hashlib
import json
from pathlib import Path

import pikepdf
import pytest

from backend import pdf_reviewed_graphic_groups as groups


def fixture(tmp_path,*,extra_paint=False):
    original=tmp_path/'original.pdf';working=tmp_path/'working.pdf';sidecar=tmp_path/'groups.json'
    source_paint=b'q 0 0 1 rg 20 20 30 30 re f 1 0 0 RG 20 20 m 50 50 l S Q'
    with pikepdf.new() as pdf:
        page=pdf.add_blank_page(page_size=(100,100))
        page.Contents=pdf.make_stream(b'0 80 10 10 re f '+source_paint+b' 80 0 10 10 re f')
        pdf.save(original)
    with pikepdf.open(original) as pdf:
        page=pdf.pages[0];page.StructParents=0
        root=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructTreeRoot')))
        prefix=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructElem'),S=pikepdf.Name('/P'),P=root,Pg=page.obj,K=0))
        # One P owner includes selected MCID1 and outside MCID2: retain that
        # outside reference in place rather than moving the P wholesale.
        owner=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructElem'),S=pikepdf.Name('/P'),P=root,Pg=page.obj,K=pikepdf.Array([1,2])))
        root.K=pikepdf.Array([prefix,owner]);root.ParentTree=pikepdf.Dictionary(Nums=pikepdf.Array([0,pikepdf.Array([prefix,owner,owner])]))
        pdf.Root.StructTreeRoot=root
        paint=b'/P <</MCID 0>> BDC 0 80 10 10 re f EMC q 0 0 1 rg /P <</MCID 1>> BDC 20 20 30 30 re f EMC /Artifact BMC 1 0 0 RG 20 20 m 50 50 l S EMC Q /P <</MCID 2>> BDC 80 0 10 10 re f EMC'
        if extra_paint:paint=paint.replace(b'20 20 30 30 re f EMC',b'20 20 30 30 re f 80 0 1 1 re f EMC')
        page.Contents=pdf.make_stream(paint);pdf.save(working)
    with pikepdf.open(original) as pdf:
        _,program=groups._program(pdf.pages[0])
    values=[v for _,v in program];selected=[i for i,v in enumerate(values) if v['operator']=='q'][0];end=[i for i,v in enumerate(values) if v['operator']=='Q'][0]
    members=[{'original_non_marking_operator_index':i} for i in range(selected,end+1) if values[i]['operator'] in groups._PAINT]
    sha=groups._sha(original)
    group={'group_id':'whole-chart','physical_page':1,'status':groups._APPROVED,'proposed_Alt':'A blue square crossed by a red diagonal line.','original_pdf_sha256':sha,'actual06_source_program_selector':{'original_input_sha256':sha,'physical_page':1,'original_page_canonical_program_sha256':groups._digest(values),'source_non_marking_operator_range_inclusive':[selected,end],'selected_ordered_program_sha256':groups._digest(values[selected:end+1])},'ordered_complete_source_paint_members':members,'ordered_complete_source_paint_members_sha256':groups._digest(members)}
    sidecar.write_text(json.dumps({'schema_version':'pdfaccess.source-bound-complete-graphic-group-proposals.v1','original':{'sha256':sha},'group_proposals':[group]}),encoding='utf-8')
    return original,working,sidecar


def test_complete_native_group_has_one_alt_and_preserves_outside_owner(tmp_path):
    original,working,sidecar=fixture(tmp_path)
    result=groups.apply_reviewed_graphic_groups(working,original,sidecar)
    assert result['applied']==1 and not result['held']
    with pikepdf.open(working) as pdf:
        root=pdf.Root.StructTreeRoot;nodes=root.K
        assert [str(n.S) for n in nodes]==['/P','/Figure','/P']
        assert int(nodes[0].K)==0 and list(nodes[2].K)==[2]
        figure=nodes[1];assert len(figure.K)==2
        assert str(figure.Alt)=='A blue square crossed by a red diagonal line.'
        parents=groups._number_tree(root.ParentTree)[0]
        assert parents[1] is None and parents[2].objgen==nodes[2].objgen
        assert all(parents[int(m.MCID)].objgen==figure.objgen for m in figure.K)
        _,scopes=groups._scopes(pdf.pages[0])
        assert all(s['tag']!='/Artifact' for s in scopes if s['paint'])


@pytest.mark.parametrize('fault',['original','full_program','selected_program','members','partial','resource','existing_actualtext','parenttree','duplicate','overlap','fidelity'])
def test_any_failed_binding_preserves_working_bytes(tmp_path,monkeypatch,fault):
    original,working,sidecar=fixture(tmp_path)
    data=json.loads(sidecar.read_text());group=data['group_proposals'][0];selector=group['actual06_source_program_selector']
    if fault=='original':data['original']['sha256']='0'*64
    if fault=='full_program':selector['original_page_canonical_program_sha256']='0'*64
    if fault=='selected_program':selector['selected_ordered_program_sha256']='0'*64
    if fault=='members':group['ordered_complete_source_paint_members_sha256']='0'*64
    if fault=='partial':
        group['ordered_complete_source_paint_members'].pop()
        group['ordered_complete_source_paint_members_sha256']=groups._digest(group['ordered_complete_source_paint_members'])
    if fault in ('resource','existing_actualtext','parenttree'):
        with pikepdf.open(working,allow_overwriting_input=True) as pdf:
            if fault=='resource':pdf.pages[0].Contents=pdf.make_stream(pdf.pages[0].Contents.read_bytes().replace(b'0 0 1 rg',b'0 1 0 rg'))
            if fault=='existing_actualtext':pdf.pages[0].Contents=pdf.make_stream(pdf.pages[0].Contents.read_bytes().replace(b'/MCID 1',b'/ActualText (existing) /MCID 1'))
            if fault=='parenttree':pdf.Root.StructTreeRoot.ParentTree.Nums[1][1]=None
            pdf.save(working)
    if fault in ('duplicate','overlap'):
        other=json.loads(json.dumps(group))
        if fault=='overlap':other['group_id']='other'
        data['group_proposals'].append(other)
    if fault=='fidelity':
        def reject(*args):raise ValueError('RGB changed')
        monkeypatch.setattr(groups,'verify_isolated_fidelity',reject)
    sidecar.write_text(json.dumps(data));before=working.read_bytes()
    with pytest.raises(ValueError):groups.apply_reviewed_graphic_groups(working,original,sidecar)
    assert working.read_bytes()==before


def test_typed_list_remains_held_without_borrowing_alt(tmp_path):
    original,working,sidecar=fixture(tmp_path)
    data=json.loads(sidecar.read_text());group=data['group_proposals'][0]
    group['status']='REVIEWED_TYPED_LIST_REQUIRES_SEMANTIC_CHILD_OWNER';group['proposed_Alt']=None
    sidecar.write_text(json.dumps(data));before=working.read_bytes()
    result=groups.apply_reviewed_graphic_groups(working,original,sidecar)
    assert result['applied']==0 and len(result['held'])==1 and working.read_bytes()==before


def test_meaningful_local_alt_survives_once_as_child_figure(tmp_path):
    original,working,sidecar=fixture(tmp_path)
    with pikepdf.open(working,allow_overwriting_input=True) as pdf:
        root=pdf.Root.StructTreeRoot;old=root.K[1];old.K=pikepdf.Array([2])
        local=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructElem'),S=pikepdf.Name('/Figure'),P=root,Pg=pdf.pages[0].obj,K=1,Alt=pikepdf.String('The filled blue square.')))
        kids=list(root.K);kids.insert(1,local);root.K=pikepdf.Array(kids)
        root.ParentTree.Nums[1][1]=local
        pdf.save(working)
    result=groups.apply_reviewed_graphic_groups(working,original,sidecar)
    assert result['applied']==1
    with pikepdf.open(working) as pdf:
        root=pdf.Root.StructTreeRoot
        assert [str(n.S) for n in root.K]==['/P','/Figure','/P']
        whole=root.K[1];local=whole.K[0]
        assert str(local.S)=='/Figure' and str(local.Alt)=='The filled blue square.'
        assert local.P.objgen==whole.objgen
        assert len(local.K)==1 and '/MCID' in whole.K[1]
        parents=groups._number_tree(root.ParentTree)[0]
        assert parents[int(local.K[0].MCID)].objgen==local.objgen
        assert parents[int(whole.K[1].MCID)].objgen==whole.objgen


def test_scope_with_selected_and_outside_paint_is_held(tmp_path):
    original,working,sidecar=fixture(tmp_path)
    with pikepdf.open(working,allow_overwriting_input=True) as pdf:
        page=pdf.pages[0]
        content=page.Contents.read_bytes()
        # Keep the exact non-marking program but extend MCID1 over the final
        # unrelated rectangle: no geometry-based scope splitting is allowed.
        content=content.replace(b'20 20 30 30 re f EMC',b'20 20 30 30 re f')
        content=content.replace(b'/P <</MCID 2>> BDC 80 0 10 10 re f EMC',b'80 0 10 10 re f EMC')
        page.Contents=pdf.make_stream(content);pdf.save(working)
    before=working.read_bytes()
    with pytest.raises(ValueError,match='outside painting'):
        groups.apply_reviewed_graphic_groups(working,original,sidecar)
    assert before==working.read_bytes()
