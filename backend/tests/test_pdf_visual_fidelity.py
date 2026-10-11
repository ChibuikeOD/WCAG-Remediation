import json
from types import SimpleNamespace
import fitz
import pytest
from backend import pdf_visual_fidelity as fidelity

def pdf(path,color=(1,0,0),text='same text'):
    with fitz.open() as doc:
        page=doc.new_page(width=100,height=100);page.insert_text((10,20),text);page.draw_rect((10,30,80,80),fill=color);doc.save(path)

def test_separate_process_preserves_text_pixels_and_rejects_real_color_change(tmp_path):
    a=tmp_path/'a.pdf';b=tmp_path/'b.pdf';c=tmp_path/'c.pdf'
    pdf(a);pdf(b);pdf(c,color=(0,0,1))
    assert fidelity.verify_isolated_fidelity(a,b,{0})['verified_page_indices']==[0]
    with pytest.raises(ValueError,match='RGB pixels'):fidelity.verify_isolated_fidelity(a,c,{0})

@pytest.mark.parametrize('fault',['nonzero','missing','truncated','wrong_hash','wrong_count','missing_page','wrong_page','bad_dimensions','bad_digest','extra_field'])
def test_invalid_child_result_never_accepts_pdf(tmp_path,monkeypatch,fault):
    a=tmp_path/'a.pdf';pdf(a);r=fidelity._fingerprint(a,[0]);code=0
    if fault=='nonzero':code=3221225477
    if fault=='wrong_hash':r['input_sha256']='a'*64
    if fault=='wrong_count':r['page_count']=2
    if fault=='missing_page':r['pages']=[]
    if fault=='wrong_page':r['pages'][0]['page_index']=1
    if fault=='bad_dimensions':r['pages'][0]['width']=0
    if fault=='bad_digest':r['pages'][0]['rgb_sha256']='not-a-digest'
    if fault=='extra_field':r['unexpected']=True
    stdout='' if fault=='missing' else '{' if fault=='truncated' else json.dumps(r)
    monkeypatch.setattr(fidelity.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=code,stdout=stdout))
    with pytest.raises(ValueError):fidelity.isolated_fingerprint(a,[0])

def test_frozen_runtime_fails_closed_without_launching_application(tmp_path,monkeypatch):
    a=tmp_path/'a.pdf';pdf(a);monkeypatch.setattr(fidelity.sys,'frozen',True,raising=False)
    with pytest.raises(ValueError,match='Python runtime'):fidelity.isolated_fingerprint(a,[0])
