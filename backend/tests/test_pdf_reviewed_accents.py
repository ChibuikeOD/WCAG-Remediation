from decimal import Decimal
import pikepdf
import pytest
from backend.pdf_reviewed_accents import partition_reviewed_show
import hashlib,json,shutil
from pathlib import Path
import reportlab
from fontTools.ttLib import TTFont
from backend.pdf_reviewed_accents import apply_reviewed_accent_groups
from backend.pdf_unicode_mapping import parse_to_unicode_cmap


def test_split_preserves_encoded_neighbor_codes_and_every_numeric_advance():
    values=pikepdf.Array([pikepdf.String(bytes.fromhex('000100020003')),Decimal('27.125'),
        pikepdf.String(bytes.fromhex('0d240d24')),-435,pikepdf.String(bytes.fromhex('0004'))])
    pieces=partition_reviewed_show([values],'TJ',{(0,2):'base',(0,4):'base',(2,0):'bar',(2,2):'bar'})
    assert [group for group,inst in pieces]==[None,'base',None,'bar',None,None]
    flattened=[]
    for group,(args,op) in pieces:
        flattened.extend(list(args[0]) if str(op)=='TJ' else [args[0]])
    assert [bytes(v).hex() for v in flattened if isinstance(v,pikepdf.String)]==['0001','00020003','0d240d24','0004']
    assert [v for v in flattened if not isinstance(v,pikepdf.String)]==[Decimal('27.125'),-435]
    assert b''.join(bytes(v) for v in flattened if isinstance(v,pikepdf.String))==bytes.fromhex('0001000200030d240d240004')


@pytest.mark.parametrize('members', [{(0,1):'x'},{(0,4):'x'},{(1,0):'x'},{(0,0):''}])
def test_invalid_exact_token_selector_rejects(members):
    with pytest.raises(ValueError):partition_reviewed_show([pikepdf.String(bytes.fromhex('00010002'))],'Tj',members)


def test_adjacent_complete_groups_and_unselected_neighbor_retain_membership():
    pieces=partition_reviewed_show([pikepdf.String(bytes.fromhex('0001000200030004'))],'Tj',
        {(0,0):'first',(0,2):'first',(0,4):'second'})
    assert [(g,bytes(inst[0][0]).hex()) for g,inst in pieces]==[('first','00010002'),('second','0003'),(None,'0004')]


def accent_fixture(tmp_path):
    program=(Path(reportlab.__file__).parent/'fonts/Vera.ttf').read_bytes()
    tt=TTFont(Path(reportlab.__file__).parent/'fonts/Vera.ttf');order=tt.getGlyphOrder();cmap=tt.getBestCmap()
    a=order.index(cmap[ord('A')]);b=order.index(cmap[ord('B')]);bar=order.index(cmap[0xAF])
    original=tmp_path/'original.pdf';working=tmp_path/'working.pdf';sidecar=tmp_path/'review.json'
    with pikepdf.new() as pdf:
        page=pdf.add_blank_page(page_size=(200,200));descriptor=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/FontDescriptor'),FontName=pikepdf.Name('/BitstreamVeraSans'),Flags=32,FontBBox=pikepdf.Array([-1000,-1000,2000,2000]),ItalicAngle=0,Ascent=1000,Descent=-250,CapHeight=750,StemV=80,FontFile2=pdf.make_stream(program)))
        descendant=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/Font'),Subtype=pikepdf.Name('/CIDFontType2'),BaseFont=pikepdf.Name('/BitstreamVeraSans'),CIDSystemInfo=pikepdf.Dictionary(Registry=pikepdf.String('Adobe'),Ordering=pikepdf.String('Identity'),Supplement=0),FontDescriptor=descriptor,CIDToGIDMap=pikepdf.Name('/Identity')))
        text=(f'/CIDInit /ProcSet findresource begin 12 dict begin begincmap /CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def /CMapName /Test def /CMapType 2 def 1 begincodespacerange <0000> <FFFF> endcodespacerange 2 beginbfchar <{a:04x}> <0041> <{b:04x}> <0042> endbfchar endcmap CMapName currentdict /CMap defineresource pop end end').encode()
        font=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/Font'),Subtype=pikepdf.Name('/Type0'),BaseFont=pikepdf.Name('/BitstreamVeraSans'),Encoding=pikepdf.Name('/Identity-H'),DescendantFonts=pikepdf.Array([descendant]),ToUnicode=pdf.make_stream(text)))
        page.Resources=pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
        page.Contents=pdf.make_stream(f'BT /F1 12 Tf 1 0 0 1 50 100 Tm [<{a:04x}{b:04x}> 12] TJ 1 0 0 1 50 110 Tm [<{bar:04x}{bar:04x}> -7] TJ ET'.encode());pdf.save(original)
    source_sha=hashlib.sha256(original.read_bytes()).hexdigest();program_sha=hashlib.sha256(program).hexdigest()
    with pikepdf.open(original) as pdf:
        indices=[i for i,inst in enumerate(pikepdf.parse_content_stream(pdf.pages[0])) if str(inst[1]) in ('Tj','TJ')]
    def token(index,offset,code):return dict(page=1,source_instruction=index,TJ_string_part_index=0,code_byte_offset=offset,font_resource='/F1',code_hex=f'{code:04x}',font_program_sha256=program_sha)
    data=dict(schema_version='pdfaccess.reviewed-type0-MATH-glyph-and-accent-proposals.v1',review_status='REVIEWED',font_code_proposals=[dict(review_status='REVIEWED',literal_unicode='\u0305',stable_original_font_code_selector=dict(input_sha256=source_sha,CID=bar,code_length_bytes=2,code_hex=f'{bar:04x}',font_program_decoded_sha256=program_sha))],accent_group_proposals=[dict(proposal_id='one-group',review_status='REVIEWED',original_sha256=source_sha,physical_page=1,requires_engine_grouping=True,proposed_ActualText='overline(A)',bar_glyph_member_count=2,base_tokens_in_intended_literal_reading_order=[token(indices[0],0,a)],bar_source_token_selectors=[token(indices[1],0,bar),token(indices[1],2,bar)])])
    sidecar.write_text(json.dumps(data),encoding='utf-8');shutil.copyfile(original,working)
    with pikepdf.open(working,allow_overwriting_input=True) as pdf:
        page=pdf.pages[0];root=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructTreeRoot')));doc=pdf.make_indirect(pikepdf.Dictionary(S=pikepdf.Name('/Document'),P=root));paragraph=pdf.make_indirect(pikepdf.Dictionary(S=pikepdf.Name('/P'),P=doc,Pg=page.obj,K=0));doc.K=paragraph;root.K=doc;root.ParentTree=pikepdf.Dictionary(Nums=pikepdf.Array([0,pikepdf.Array([paragraph])]));pdf.Root.StructTreeRoot=root;page.StructParents=0
        page.Contents=pdf.make_stream(b'/P <</MCID 0>> BDC\n'+page.Contents.read_bytes()+b'\nEMC');pdf.save(working)
    return original,working,sidecar,data,bar,a,b


@pytest.mark.parametrize('inherited_page',[False,True])
def test_complete_group_maps_bar_once_logically_preserves_neighbor_and_inline_parent(tmp_path,inherited_page):
    original,working,sidecar,data,bar,a,b=accent_fixture(tmp_path);before=hashlib.sha256(original.read_bytes()).hexdigest()
    if inherited_page:
        with pikepdf.open(working,allow_overwriting_input=True) as pdf:
            doc=pdf.Root.StructTreeRoot.K;doc.Pg=pdf.pages[0].obj;del doc.K['/Pg'];pdf.save(working)
    result=apply_reviewed_accent_groups(working,original,sidecar)
    assert result['applied_groups']==1 and result['mapped_occurrences']==2 and not result['external_provider_invoked']
    assert hashlib.sha256(original.read_bytes()).hexdigest()==before
    with pikepdf.open(working) as pdf:
        paragraph=pdf.Root.StructTreeRoot.K.K;formula,neighbor,*displacements=list(paragraph.K)
        assert str(formula.S)=='/Formula' and formula.P.objgen==paragraph.objgen
        assert str(formula.ActualText)=='overline(A)' and '/ActualText' not in neighbor
        assert parse_to_unicode_cmap(pdf.pages[0].Resources.Font.F1.ToUnicode.read_bytes()).mappings[bar]=='\u0305'
        shows={};active=None
        for args,op in pikepdf.parse_content_stream(pdf.pages[0]):
            if str(op)=='BDC':active=int(args[1].MCID)
            elif str(op)=='EMC':active=None
            elif str(op)=='Tj':shows[active]=bytes(args[0])
            elif str(op)=='TJ':
                assert active is not None
                assert all(not isinstance(value,pikepdf.String) for value in args[0])
        assert [shows[int(ref.MCID)].hex() for ref in formula.K]==[f'{a:04x}',f'{bar:04x}{bar:04x}']
        assert shows[int(neighbor.MCID)].hex()==f'{b:04x}'
        parents=pdf.Root.StructTreeRoot.ParentTree.Nums[1]
        assert all(parents[int(ref.MCID)].objgen==formula.objgen for ref in formula.K)
        assert parents[int(neighbor.MCID)].objgen==paragraph.objgen
        assert len(displacements)==2 and all(parents[int(ref.MCID)].objgen==paragraph.objgen for ref in displacements)
        # Tagged logical replacement occurs once, followed by the original B.
        assert str(formula.ActualText)+'B'=='overline(A)B'


@pytest.mark.parametrize('fault',['wrong-source','missing-bar','wrong-code','explicit-link','existing-actualtext','duplicate-owner','wrong-parenttree','Form-bar','quote-bar','wrong-effective-font','missing-base','no-codes'])
def test_unverified_or_incomplete_group_rejects_without_mutating_working(tmp_path,fault):
    original,working,sidecar,data,bar,a,b=accent_fixture(tmp_path)
    if fault=='wrong-source':data['accent_group_proposals'][0]['original_sha256']='0'*64
    elif fault=='missing-base':data['accent_group_proposals'][0]['base_tokens_in_intended_literal_reading_order']=[]
    elif fault=='no-codes':data['font_code_proposals']=[]
    elif fault=='missing-bar':data['accent_group_proposals'][0]['bar_source_token_selectors'].pop();data['accent_group_proposals'][0]['bar_glyph_member_count']=1
    elif fault=='wrong-code':data['accent_group_proposals'][0]['base_tokens_in_intended_literal_reading_order'][0]['code_hex']=f'{b:04x}'
    elif fault=='explicit-link':
        with pikepdf.open(working,allow_overwriting_input=True) as pdf:pdf.Root.StructTreeRoot.K.K.S=pikepdf.Name('/Link');pdf.save(working)
    elif fault in ('existing-actualtext','duplicate-owner','wrong-parenttree'):
        with pikepdf.open(working,allow_overwriting_input=True) as pdf:
            paragraph=pdf.Root.StructTreeRoot.K.K
            if fault=='existing-actualtext':paragraph.ActualText=pikepdf.String('Existing exact replacement')
            elif fault=='duplicate-owner':paragraph.K=pikepdf.Array([0,0])
            else:pdf.Root.StructTreeRoot.ParentTree.Nums[1][0]=pdf.make_indirect(pikepdf.Dictionary(S=pikepdf.Name('/P')))
            pdf.save(working)
    elif fault in ('Form-bar','quote-bar','wrong-effective-font'):
        for path in (original,working):
            with pikepdf.open(path,allow_overwriting_input=True) as pdf:
                page=pdf.pages[0]
                if fault=='Form-bar':
                    form=pdf.make_stream(f'BT <{bar:04x}> Tj ET'.encode());form.Type=pikepdf.Name('/XObject');form.Subtype=pikepdf.Name('/Form');form.BBox=pikepdf.Array([0,0,100,100]);form.Resources=pikepdf.Dictionary()
                    page.Resources.XObject=pikepdf.Dictionary(X=form);extra=b' q /X Do Q'
                elif fault=='quote-bar':extra=f' BT /F1 12 Tf <{bar:04x}> \' ET'.encode()
                else:
                    page.Resources.Font.F2=pdf.make_indirect(pikepdf.Dictionary(page.Resources.Font.F1));extra=b''
                page.Contents=pdf.make_stream(page.Contents.read_bytes()+extra);pdf.save(path)
        source_sha=hashlib.sha256(original.read_bytes()).hexdigest();data['accent_group_proposals'][0]['original_sha256']=source_sha;data['font_code_proposals'][0]['stable_original_font_code_selector']['input_sha256']=source_sha
        if fault=='wrong-effective-font':data['accent_group_proposals'][0]['base_tokens_in_intended_literal_reading_order'][0]['font_resource']='/F2'
    sidecar.write_text(json.dumps(data),encoding='utf-8');before=hashlib.sha256(working.read_bytes()).hexdigest()
    with pytest.raises(ValueError):apply_reviewed_accent_groups(working,original,sidecar)
    assert hashlib.sha256(working.read_bytes()).hexdigest()==before
