"""Strict local PDF fingerprints, one renderer process per document."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

SCHEMA='pdfaccess.render-fingerprint.v1'

def _sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def _fingerprint(path,pages):
    import fitz
    before=_sha(path);result=[]
    with fitz.open(path) as doc:
        count=len(doc)
        for index in pages:
            page=doc[index];text=page.get_text();pixels=page.get_pixmap(dpi=96,alpha=False)
            result.append({'page_index':index,'text_sha256':hashlib.sha256(text.encode('utf-8')).hexdigest(),
                           'rgb_sha256':hashlib.sha256(pixels.samples).hexdigest(),
                           'width':pixels.width,'height':pixels.height,'channels':pixels.n})
    if _sha(path)!=before:raise ValueError('input PDF changed during rendering')
    return {'schema':SCHEMA,'input_sha256':before,'page_count':count,'pages':result}

def isolated_fingerprint(path,pages):
    pages=sorted(set(pages))
    if not pages or any(type(i) is not int or i<0 for i in pages):raise ValueError('invalid fingerprint page selection')
    if getattr(sys,'frozen',False):
        raise ValueError('isolated rendering requires an available Python runtime; PDF retained')
    expected=_sha(path)
    import pikepdf
    with pikepdf.open(path) as pdf:expected_count=len(pdf.pages)
    try:
        completed=subprocess.run([sys.executable,str(Path(__file__).resolve()),str(Path(path).resolve()),json.dumps(pages)],
                                 capture_output=True,text=True,encoding='utf-8',timeout=300,
                                 creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except (OSError,subprocess.TimeoutExpired) as error:
        raise ValueError('isolated renderer could not complete; PDF retained') from error
    if completed.returncode!=0:raise ValueError(f'isolated renderer failed with exit {completed.returncode}')
    try:result=json.loads(completed.stdout)
    except (TypeError,ValueError) as error:raise ValueError('isolated renderer returned missing/truncated JSON') from error
    if not isinstance(result,dict) or set(result)!= {'schema','input_sha256','page_count','pages'}:
        raise ValueError('isolated renderer result schema invalid')
    if result['schema']!=SCHEMA or result['input_sha256']!=expected or _sha(path)!=expected:
        raise ValueError('isolated renderer input/schema identity mismatch')
    if type(result['page_count']) is not int or result['page_count']!=expected_count or result['page_count']<=max(pages):
        raise ValueError('isolated renderer page count invalid')
    records=result['pages']
    if not isinstance(records,list) or len(records)!=len(pages):raise ValueError('isolated renderer page result count invalid')
    for index,record in zip(pages,records):
        if not isinstance(record,dict) or set(record)!={'page_index','text_sha256','rgb_sha256','width','height','channels'}:
            raise ValueError('isolated renderer page schema invalid')
        if type(record['page_index']) is not int or record['page_index']!=index:
            raise ValueError('isolated renderer page order invalid')
        if type(record['channels']) is not int or record['channels']!=3 or any(type(record[k]) is not int or record[k]<=0 for k in ('width','height')):
            raise ValueError('isolated renderer pixel dimensions invalid')
        for key in ('text_sha256','rgb_sha256'):
            value=record[key]
            if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
                raise ValueError('isolated renderer digest invalid')
    return result

def verify_isolated_fidelity(before,after,pages):
    a=isolated_fingerprint(before,pages);b=isolated_fingerprint(after,pages)
    if a['page_count']!=b['page_count'] or a['pages']!=b['pages']:
        raise ValueError('isolated PDF rendering changed page count, text or RGB pixels')
    return {'verification':'separate-process-text-and-rgb','dpi':96,'verified_page_indices':sorted(set(pages)),
            'before_sha256':a['input_sha256'],'after_sha256':b['input_sha256'],'page_count':a['page_count']}

if __name__=='__main__':
    print(json.dumps(_fingerprint(sys.argv[1],json.loads(sys.argv[2])),separators=(',',':')),flush=True)
