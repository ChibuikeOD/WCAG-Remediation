from copy import deepcopy
import pytest
from backend.opendataloader_layout import OpenDataLoaderLayoutAnalyzer as Analyzer


def table():
    return {'type':'table','id':7,'page number':1,'bounding box':[10,20,190,180],
        'number of rows':2,'number of columns':2,'rows':[
            {'cells':[
                {'page number':1,'bounding box':[10,100,100,180], 'row number':1,
                 'column number':1,'row span':1,'column span':1,'header':True,'scope':'Column',
                 'kids':[{'content':'Sample'}]},
                {'page number':1,'bounding box':[100,20,190,180], 'row number':1,
                 'column number':2,'row span':2,'column span':1,
                 'kids':[{'type':'image','alt_text':'Two specimens show opposing ply orientations.'}]}]},
            {'cells':[
                {'page number':1,'bounding box':[10,20,100,100], 'row number':2,
                 'column number':1,'row span':1,'column span':1,'kids':[{'content':'G45C45'}]}]}]}


def parse(element):
    return Analyzer.parse_opendataloader_json({'number of pages':1,'kids':[element]},[(200,200)])[0].blocks


def test_supplied_cells_spans_headers_and_image_description_preserved():
    blocks=parse(table())
    assert [(b.tag,b.text,b.metadata['table_row'],b.metadata['table_col']) for b in blocks] == [
        ('TH','Sample',0,0),('TD','',0,1),('TD','G45C45',1,0)]
    assert blocks[0].metadata['table_scope']=='Column'
    assert not blocks[0].metadata['table_review_required']
    assert blocks[1].metadata['table_row_span']==2
    assert blocks[1].metadata['figure_alt_text']=='Two specimens show opposing ply orientations.'
    assert blocks[1].metadata['table_review_required']
    assert all(b.metadata['table_id']=='odl-p1-t7' for b in blocks)


def test_header_not_invented_from_first_row_or_bold_text():
    source=table();del source['rows'][0]['cells'][0]['header']
    source['rows'][0]['cells'][0]['kids'][0]['font']='TimesNewRomanPS-BoldMT'
    assert parse(source)[0].tag=='TD'
    assert parse(source)[0].metadata['table_review_required']


@pytest.mark.parametrize('damage', ['overlap','outside','zero','badheader','bbox'])
def test_invalid_grid_falls_back_with_explicit_review(damage):
    source=table();cell=source['rows'][1]['cells'][0]
    if damage=='overlap':cell['row number']=1
    elif damage=='outside':cell['column span']=3
    elif damage=='zero':cell['row span']=0
    elif damage=='badheader':cell['header']='true'
    else:cell['bounding box']=[10,20,10,100]
    blocks=parse(source)
    assert len(blocks)==1 and blocks[0].tag=='Table'
    assert blocks[0].metadata['table_review_required']
    assert blocks[0].metadata['table_review_reason']


def test_explicit_formula_description_kept_without_invention():
    source={'type':'formula','page number':1,'bounding box':[10,20,90,40],
            'content':'x squared','alt_text':'x squared equals four'}
    assert parse(source)[0].metadata['alt_text']=='x squared equals four'
    del source['alt_text']
    assert parse(source)[0].metadata['alt_text']==''

def test_serializer_keeps_table_evidence_and_reports_unknown_headers(tmp_path,monkeypatch):
    import json,shutil,subprocess
    from backend import pdf_auto_tagging as module
    from backend.config import settings
    source=tmp_path/'source.pdf';output=tmp_path/'output.pdf'
    import fitz
    with fitz.open() as document:
        document.new_page(width=200,height=200).insert_text((30,40),'Sample')
        document.save(source)
    layouts=Analyzer.parse_opendataloader_json({'number of pages':1,'kids':[table()]},[(200,200)])
    monkeypatch.setattr(Analyzer,'analyze_document',lambda self,path:layouts)
    if hasattr(settings,'JEV_STRUCTURE_REFINEMENT_ENABLED'):
        monkeypatch.setattr(settings,'JEV_STRUCTURE_REFINEMENT_ENABLED',False)
    backend=tmp_path/'backend';backend.mkdir()
    monkeypatch.setattr(module,'__file__',str(backend/'pdf_auto_tagging.py'))
    binary=tmp_path/'pdfua_remediator_cpp/build/Release/pdfua-remediator-cli.exe'
    binary.parent.mkdir(parents=True);binary.write_bytes(b'fixture')
    captured=[]
    def run(command,**kwargs):
        captured.extend(json.loads(open(command[2],encoding='utf-8').read()))
        shutil.copyfile(command[1],command[3])
        return subprocess.CompletedProcess(command,0,stdout='',stderr='')
    monkeypatch.setattr(module.subprocess,'run',run)
    result=module.auto_tag_pdf(source,output)
    assert result['success'] and result['table_review_count']==1
    assert captured[0]['table_scope']=='Column'
    assert captured[1]['table_row_span']==2 and captured[1]['table_col_span']==1
    assert bytes.fromhex(captured[1]['figure_alt_hex']).decode()=='Two specimens show opposing ply orientations.'
