import hashlib,json,shutil
import fitz,pikepdf,pytest
from backend.pdf_reviewed_links import apply_reviewed_link_purposes,SCHEMA,STATUS

def fixture(tmp_path,mcr=False):
    original=tmp_path/'original.pdf';current=tmp_path/'current.pdf';sidecar=tmp_path/'review.json'
    with fitz.open() as d:
        p=d.new_page(width=200,height=200);p.insert_text((20,40),'Figure 7.10');d.new_page(width=200,height=200);d.save(original)
    with pikepdf.open(original,allow_overwriting_input=True) as pdf:
        annotation=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/Annot'),Subtype=pikepdf.Name('/Link'),Rect=pikepdf.Array([18,154,110,172]),A=pikepdf.Dictionary(S=pikepdf.Name('/GoTo'),D=pikepdf.String('figure.target'))))
        pdf.pages[0].Annots=pikepdf.Array([annotation]);pdf.Root.Names=pikepdf.Dictionary(Dests=pikepdf.Dictionary(Names=pikepdf.Array([pikepdf.String('figure.target'),pikepdf.Array([pdf.pages[1].obj,pikepdf.Name('/FitH'),180])])));pdf.save(original)
    shutil.copyfile(original,current)
    with pikepdf.open(current,allow_overwriting_input=True) as pdf:
        page=pdf.pages[0];root=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructTreeRoot')));doc=pdf.make_indirect(pikepdf.Dictionary(S=pikepdf.Name('/Document'),P=root));link=pdf.make_indirect(pikepdf.Dictionary(S=pikepdf.Name('/Link'),P=doc,Pg=page.obj));annot=page.Annots[0];annot.StructParent=0
        link.K=pikepdf.Array([pikepdf.Dictionary(Type=pikepdf.Name('/OBJR'),Pg=page.obj,Obj=annot)])
        if mcr:
            page.Contents=pdf.make_stream(b'/Link <</MCID 0>> BDC\n'+b'\n'.join(s.read_bytes() for s in page.Contents)+b'\nEMC');page.StructParents=1;link.K.append(pikepdf.Dictionary(Type=pikepdf.Name('/MCR'),Pg=page.obj,MCID=0))
        doc.K=pikepdf.Array([link]);root.K=doc;root.ParentTree=pikepdf.Dictionary(Nums=pikepdf.Array([0,link]+([1,pikepdf.Array([link])] if mcr else [])));pdf.Root.StructTreeRoot=root;pdf.save(current)
    with fitz.open(original) as d:
        chars=[dict(char=c['c'],bbox=list(c['bbox']),origin=list(c['origin']),source_span_font=s['font'],source_span_size=s['size']) for b in d[0].get_text('rawdict')['blocks'] for l in b.get('lines',[]) for s in l['spans'] for c in s['chars']]
    data={'schema':SCHEMA,'original_sha256':hashlib.sha256(original.read_bytes()).hexdigest(),'links':[dict(page=1,target_name='figure.target',Rect_pdf_points=[18,154,110,172],proposed_literal_purpose='Figure 7.10',proposal_status=STATUS,source_characters_with_centers_in_annotation=chars,original_destination={'page':2})]}
    sidecar.write_text(json.dumps(data),encoding='utf-8');return original,current,sidecar,data

@pytest.mark.parametrize('mcr',[False,True])
def test_reviewed_purpose_preserves_source_and_exact_objr_mcr_topology(tmp_path,mcr):
    original,current,sidecar,data=fixture(tmp_path,mcr);source=original.read_bytes()
    with pikepdf.open(current) as pdf:
        link=pdf.Root.StructTreeRoot.K.K[0];kinds=[str(k.Type) for k in link.K];mcids=[int(k.MCID) for k in link.K if '/MCID' in k]
    result=apply_reviewed_link_purposes(current,original,[sidecar]);assert result['applied']==1 and result['unmatched']==0
    assert original.read_bytes()==source and result['external_provider_invoked'] is False
    assert result['records'][0]['owner_alternative_applied'] is not mcr
    with pikepdf.open(current) as pdf:
        link=pdf.Root.StructTreeRoot.K.K[0];assert str(pdf.pages[0].Annots[0].Contents)=='Figure 7.10'
        assert [str(k.Type) for k in link.K]==kinds and [int(k.MCID) for k in link.K if '/MCID' in k]==mcids
        assert ('/Alt' in link) is not mcr

@pytest.mark.parametrize('fault',['rect','glyph','destination','parent_tree','conflict','source','duplicate'])
def test_wrong_source_binding_or_owner_never_changes_pdf(tmp_path,fault):
    original,current,sidecar,data=fixture(tmp_path)
    if fault=='rect':data['links'][0]['Rect_pdf_points'][0]+=1
    if fault=='glyph':data['links'][0]['source_characters_with_centers_in_annotation'][0]['char']='X'
    if fault=='source':data['original_sha256']='0'*64
    if fault=='duplicate':data['links']*=2
    if fault in ('destination','parent_tree','conflict'):
        with pikepdf.open(current,allow_overwriting_input=True) as pdf:
            if fault=='destination':pdf.Root.Names.Dests.Names[1][2]=179
            if fault=='parent_tree':pdf.Root.StructTreeRoot.ParentTree.Nums[1]=pdf.Root.StructTreeRoot.K
            if fault=='conflict':pdf.pages[0].Annots[0].Contents=pikepdf.String('Existing purpose')
            pdf.save(current)
    sidecar.write_text(json.dumps(data),encoding='utf-8');before=current.read_bytes()
    if fault in ('source','duplicate'):
        with pytest.raises(ValueError):apply_reviewed_link_purposes(current,original,[sidecar])
    else:
        result=apply_reviewed_link_purposes(current,original,[sidecar]);assert result['applied']==0 and result['unmatched']==1
    assert current.read_bytes()==before
