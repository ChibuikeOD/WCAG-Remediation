import hashlib
import json

import fitz
import pikepdf
import pytest

from backend.pdf_reviewed_figures import apply_reviewed_figure_alternatives


def fixture(tmp_path, *, form=False, duplicate=False, role='/Figure'):
    original=tmp_path/'original.pdf';working=tmp_path/'working.pdf';sidecar=tmp_path/'review.json'
    with pikepdf.new() as pdf:
        page=pdf.add_blank_page(page_size=(200,200))
        image=pdf.make_stream(bytes([0,90,180,255]));image.Type=pikepdf.Name('/XObject')
        image.Subtype=pikepdf.Name('/Image');image.Width=2;image.Height=2
        image.ColorSpace=pikepdf.Name('/DeviceGray');image.BitsPerComponent=8
        obj=image
        if form:
            obj=pdf.make_stream(b'/P <</MCID 0>> BDC q 2 0 0 2 0 0 cm /I Do Q EMC')
            obj.Type=pikepdf.Name('/XObject');obj.Subtype=pikepdf.Name('/Form')
            obj.BBox=pikepdf.Array([0,0,2,2]);obj.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(I=image))
        page.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im=obj))
        paint=b'q 40 0 0 30 20 50 cm /Im Do Q'
        page.Contents=pdf.make_stream(paint+(b' '+paint if duplicate else b''))
        pdf.save(original,compress_streams=False)
    with pikepdf.open(original) as pdf:
        page=pdf.pages[0];obj=page.Resources.XObject.Im
        payload=hashlib.sha256(obj.read_bytes() if form else obj.read_raw_bytes()).hexdigest()
        paint=page.Contents.read_bytes();page.Contents=pdf.make_stream(b'/Figure <</MCID 14>> BDC '+paint+b' EMC')
        root=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructTreeRoot')))
        owner=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructElem'),S=pikepdf.Name(role),Pg=page.obj,K=14,P=root))
        owner.A=pikepdf.Dictionary(O=pikepdf.Name('/Layout'),BBox=pikepdf.Array([20,50,100,110] if form else [20,50,60,80]))
        root.K=pikepdf.Array([owner]);pdf.Root.StructTreeRoot=root
        pdf.save(working,compress_streams=False)
    record={'proposal_id':'review-1','physical_page':1,'description_text':'Two-by-two grayscale pattern, dark upper left and light lower right.',
            'stable_binding':{'requires_original_sha256':hashlib.sha256(original.read_bytes()).hexdigest(),
                              'original_subtype':'/Form' if form else '/Image',
                              'original_raw_stream_sha256':None if form else payload,
                              'original_decoded_content_sha256':payload if form else None,
                              'verified_page_bbox_pdf_exact_decimal':[20,50,100,110] if form else [20,50,60,80]}}
    sidecar.write_text(json.dumps({'bindings':[record]}))
    return original,working,sidecar


@pytest.mark.parametrize('form',[False,True])
def test_exact_painting_binding_updates_only_unique_figure_alt(tmp_path,form):
    original,working,sidecar=fixture(tmp_path,form=form)
    before=working.read_bytes()
    with fitz.open(working) as pdf: pixels=pdf[0].get_pixmap(dpi=96,alpha=False).samples;text=pdf[0].get_text()
    result=apply_reviewed_figure_alternatives(working,original,[sidecar])
    assert result['applied']==1 and result['unmatched']==0
    with pikepdf.open(working) as pdf:
        owner=pdf.Root.StructTreeRoot.K[0]
        assert int(owner.K)==14 and str(owner.S)=='/Figure'
        assert str(owner.Alt).startswith('Two-by-two')
    with fitz.open(working) as pdf:
        assert pixels==pdf[0].get_pixmap(dpi=96,alpha=False).samples and text==pdf[0].get_text()
    assert before!=working.read_bytes()


@pytest.mark.parametrize('fault',['payload','bbox','duplicate','role','source','tinyFigure','changedInner'])
def test_unmatched_or_ambiguous_evidence_never_changes_output(tmp_path,fault):
    original,working,sidecar=fixture(tmp_path,duplicate=fault=='duplicate',role='/Link' if fault=='role' else '/Figure')
    data=json.loads(sidecar.read_text());record=data['bindings'][0]
    if fault=='payload':record['stable_binding']['original_raw_stream_sha256']='0'*64
    if fault=='bbox':record['stable_binding']['verified_page_bbox_pdf_exact_decimal']=[20,50,61,80]
    if fault=='source':record['stable_binding']['requires_original_sha256']='0'*64
    if fault=='tinyFigure':
        with pikepdf.open(working,allow_overwriting_input=True) as pdf:
            pdf.Root.StructTreeRoot.K[0].A.BBox=pikepdf.Array([20,50,20.1,50.1]);pdf.save(working)
    if fault=='changedInner':
        with pikepdf.open(working,allow_overwriting_input=True) as pdf:
            pdf.pages[0].Resources.XObject.Im.write(bytes([255,90,180,0]));pdf.save(working,compress_streams=False)
    sidecar.write_text(json.dumps(data));before=working.read_bytes()
    result=apply_reviewed_figure_alternatives(working,original,[sidecar])
    assert result['applied']==0 and before==working.read_bytes()
    assert result['unmatched']==1 if fault!='source' else result['other_source_records']==1


def test_conflicting_reviews_reject_both_without_first_wins(tmp_path):
    original,working,sidecar=fixture(tmp_path)
    data=json.loads(sidecar.read_text());other=json.loads(json.dumps(data['bindings'][0]))
    other['proposal_id']='conflict';other['description_text']='A different claimed figure.'
    data['bindings'].append(other);sidecar.write_text(json.dumps(data));before=working.read_bytes()
    result=apply_reviewed_figure_alternatives(working,original,[sidecar])
    assert result['applied']==0 and result['unmatched']==2
    assert before==working.read_bytes()
