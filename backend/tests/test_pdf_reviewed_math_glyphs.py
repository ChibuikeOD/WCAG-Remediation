import hashlib
import json
import shutil
from pathlib import Path

import pikepdf
import pytest
import reportlab
import fitz
from fontTools import t1Lib

from backend.pdf_reviewed_math_glyphs import _fingerprint, _parse_program, load_reviewed_math_glyphs


def fixture(tmp_path):
    # Existing ReportLab test font, not a downloaded/replaced corpus font.
    payload=t1Lib.readPFB(str(Path(reportlab.__file__).parent/'fonts'/'cob_____.pfb'))
    encoding,chars=_parse_program(payload,'Type1');assert encoding[65]=='A'
    original=tmp_path/'source.pdf';working=tmp_path/'working.pdf';sidecar=tmp_path/'review.json'
    with pikepdf.new() as pdf:
        page=pdf.add_blank_page(page_size=(200,200))
        descriptor=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/FontDescriptor'),FontName=pikepdf.Name('/Courier-Bold'),FontFile=pdf.make_stream(payload)))
        font=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/Font'),Subtype=pikepdf.Name('/Type1'),BaseFont=pikepdf.Name('/Courier-Bold'),
            FontDescriptor=descriptor,FirstChar=65,LastChar=65,Widths=pikepdf.Array([600])))
        page.Resources=pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font));page.Contents=pdf.make_stream(b'BT /F1 12 Tf 20 150 Td (A) Tj ET')
        pdf.save(original)
    sha=hashlib.sha256(original.read_bytes()).hexdigest();program_sha=hashlib.sha256(payload).hexdigest()
    with pikepdf.open(original) as pdf:
        font=pdf.pages[0].Resources.Font.F1;identity=_fingerprint(font);objgen=list(font.objgen)
    encoding_sha=hashlib.sha256(json.dumps({str(i):str(n) for i,n in enumerate(encoding)},ensure_ascii=True,separators=(',',':')).encode('ascii')).hexdigest()
    source=dict(source_id='actual-font',input_sha256=sha,font_objgen=objgen,canonical_full_font_content_fingerprint_sha256=identity,font_program_decoded_sha256=program_sha)
    binding=dict(source_id='actual-font',input_sha256=sha,font_objgen=objgen,font_resource='/F1',character_code=65,
        canonical_full_font_content_fingerprint_sha256=identity,font_program_decoded_sha256=program_sha,
        glyph_charstring_sha256=hashlib.sha256(chars['A'].bytecode).hexdigest(),effective_glyph_name='A',embedded_encoding_vector_sha256=encoding_sha,
        resource_invocation_path=[],original_first_recorded_placement=dict(physical_page=1,operator_index=3,operator='Tj',raw_show_strings_hex=['41'],string_index=0,byte_offset_in_string=0))
    data=dict(schema_version='pdfaccess.math-glyph-proposals.v1',review_status='REVIEWED_SOURCE_SPECIFIC_COMPLETE_SYMBOL_PROPOSALS_ONLY',sources=[source],
        proposals=[dict(proposal_id='observed-A',review_status='REVIEWED',mapping_kind='complete-symbol',isolated_glyph_mapping_allowed=True,literal_unicode='A',effective_glyph_name='A',bindings=[binding])],
        held_combining_bindings=[{'must_not_be_consumed':True}],deferred_extension_bindings=[{'must_not_be_consumed':True}])
    sidecar.write_text(json.dumps(data));shutil.copyfile(original,working)
    return original,working,sidecar,data


def test_actual_embedded_code_and_charstring_bind_without_mutation(tmp_path):
    original,working,sidecar,_=fixture(tmp_path);before=working.read_bytes();source_bytes=original.read_bytes()
    result=load_reviewed_math_glyphs(sidecar,original,working)
    assert len(result)==1 and result.binding_counts=={'considered':1,'matched':1,'unmatched':0}
    value=next(iter(result.values()));assert value['text']=='A' and value['mapping_kind']=='complete-symbol'
    assert value['font_metadata_authority'] is False
    assert working.read_bytes()==before and original.read_bytes()==source_bytes


@pytest.mark.parametrize('fault',['held','glyph_hash','encoding_hash','placement','source'])
def test_unverified_complete_symbol_input_rejected(tmp_path,fault):
    original,working,sidecar,data=fixture(tmp_path);p=data['proposals'][0];b=p['bindings'][0]
    if fault=='held':p['mapping_kind']='extension-piece'
    elif fault=='glyph_hash':b['glyph_charstring_sha256']='0'*64
    elif fault=='encoding_hash':b['embedded_encoding_vector_sha256']='0'*64
    elif fault=='placement':b['original_first_recorded_placement']['raw_show_strings_hex']=['42']
    elif fault=='source':data['sources'][0]['input_sha256']='0'*64
    sidecar.write_text(json.dumps(data));before=working.read_bytes()
    with pytest.raises(ValueError):load_reviewed_math_glyphs(sidecar,original,working)
    assert working.read_bytes()==before


@pytest.mark.parametrize('fault',['metrics','encoding','program'])
def test_same_basefont_name_does_not_bind_changed_painting(tmp_path,fault):
    original,working,sidecar,_=fixture(tmp_path)
    with pikepdf.open(working,allow_overwriting_input=True) as pdf:
        font=pdf.pages[0].Resources.Font.F1
        if fault=='metrics':font.Widths=pikepdf.Array([601])
        elif fault=='encoding':font.Encoding=pikepdf.Dictionary(Differences=pikepdf.Array([65,pikepdf.Name('/B')]))
        elif fault=='program':font.FontDescriptor.FontFile.write(font.FontDescriptor.FontFile.read_bytes()+b' changed')
        pdf.save(working)
    result=load_reviewed_math_glyphs(sidecar,original,working)
    assert not result and result.binding_counts=={'considered':1,'matched':0,'unmatched':1}


def test_reviewed_math_installs_real_cmap_with_no_external_request(tmp_path):
    from backend.pdf_unicode_mapping import repair_missing_unicode,parse_to_unicode_cmap
    original,working,sidecar,_=fixture(tmp_path);source_bytes=original.read_bytes()
    with fitz.open(working) as doc:before=doc[0].get_pixmap(dpi=96,alpha=False).samples
    def forbidden_external(*args,**kwargs):raise AssertionError('external verifier must not run')
    result=repair_missing_unicode(working,verifier=forbidden_external,reviewed_math_sidecar=sidecar,reviewed_math_original=original)
    assert result['details']['reviewed_math_applied']==1 and result['details']['reviewed_math_bound']==1
    assert result['details']['llm_invoked'] is False
    with pikepdf.open(working) as pdf:
        assert parse_to_unicode_cmap(pdf.pages[0].Resources.Font.F1.ToUnicode.read_bytes()).mappings[65]=='A'
    with fitz.open(working) as doc:assert doc[0].get_pixmap(dpi=96,alpha=False).samples==before
    assert original.read_bytes()==source_bytes


@pytest.mark.parametrize('fault',[None,'wrong_unicode','changed_metrics','missing_mapping'])
def test_saved_font_namespace_verification_checks_exact_mapping(tmp_path,fault):
    from backend.pdf_unicode_mapping import _write_unicode_mappings,verify_repair
    original,working,_,_=fixture(tmp_path)
    with pikepdf.open(working) as pdf:
        identity=tuple(pdf.pages[0].Resources.Font.F1.objgen)
    output=tmp_path/'saved.pdf'
    _write_unicode_mappings(working,output,[(identity,65,'A')],reviewed_math_fonts={identity})
    with pikepdf.open(output,allow_overwriting_input=True) as pdf:
        font=pdf.pages[0].Resources.Font.F1
        if fault=='wrong_unicode':font.ToUnicode.write(font.ToUnicode.read_bytes().replace(b'<0041>',b'<0042>'))
        elif fault=='changed_metrics':font.Widths=pikepdf.Array([601])
        elif fault=='missing_mapping':del font['/ToUnicode']
        with pikepdf.new() as reordered:
            reordered.Root['/AResourceVerificationFixture']=reordered.make_indirect(pikepdf.Dictionary(Value=1))
            reordered.pages.append(pdf.pages[0])
            reordered.save(output,object_stream_mode=pikepdf.ObjectStreamMode.generate)
    with pikepdf.open(output) as saved:
        assert tuple(saved.pages[0].Resources.Font.F1.objgen)!=identity
    ok,reason=verify_repair(working,output,[(identity,65,'A')],{1})
    assert ok is (fault is None),reason
    if fault is not None:assert reason.startswith('mapping-verification-error:')
