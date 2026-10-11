"""Strict local PDF fingerprints, one renderer process per document."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

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
    expected=_sha(path)
    import pikepdf
    with pikepdf.open(path) as pdf:expected_count=len(pdf.pages)
    result_path=None
    command=[sys.executable,str(Path(__file__).resolve()),str(Path(path).resolve()),json.dumps(pages)]
    if getattr(sys,'frozen',False):
        handle,result_name=tempfile.mkstemp(prefix='pdfaccess-render-',suffix='.json')
        import os
        os.close(handle)
        result_path=Path(result_name)
        command=[sys.executable,'--render-fingerprint-input',str(Path(path).resolve()),
                 '--render-fingerprint-pages',json.dumps(pages),'--render-fingerprint-result',str(result_path)]
    try:
        completed=subprocess.run(command,
                                 capture_output=True,text=True,encoding='utf-8',timeout=300,
                                 creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if completed.returncode!=0:raise ValueError(f'isolated renderer failed with exit {completed.returncode}')
        try:
            if result_path is not None:
                if result_path.stat().st_size>16*1024*1024:raise ValueError('renderer JSON exceeds bounded size')
                payload=result_path.read_text(encoding='utf-8')
            else:payload=completed.stdout
            result=json.loads(payload)
        except (OSError,TypeError,ValueError) as error:
            raise ValueError('isolated renderer returned missing/truncated JSON') from error
    except (OSError,subprocess.TimeoutExpired) as error:
        raise ValueError('isolated renderer could not complete; PDF retained') from error
    finally:
        if result_path is not None:result_path.unlink(missing_ok=True)
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
