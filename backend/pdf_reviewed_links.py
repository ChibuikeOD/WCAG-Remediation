"""Source-bound literal Link purposes; preserve annotation and OBJR ownership."""
import json
import math
import os
from pathlib import Path
import tempfile
import fitz
import pikepdf
from .pdf_reviewed_figures import _sha
from .pdf_reviewed_tables import _number_tree
from .pdf_visual_fidelity import verify_isolated_fidelity
from .pdf_link_descriptions import _meaningful

SCHEMA='pdfaccess.actual-current-link-purpose-review.v1'
STATUS='REVIEWED_SOURCE_SPECIFIC_LITERAL_LINK_PURPOSE_ONLY'

def _destination(annotation):
    action=annotation.get('/A')
    if not isinstance(action,pikepdf.Dictionary) or str(action.get('/S'))!='/GoTo':return None
    value=action.get('/D')
    return str(value) if isinstance(value,(pikepdf.String,pikepdf.Name)) else None

def _named_destination(pdf,name):
    from .pdf_reviewed_tables import _name_tree
    names=pdf.Root.get('/Names',{}).get('/Dests')
    values=_name_tree(names) if names is not None else {}
    destination=values.get(name)
    if destination is None:destination=pdf.Root.get('/Dests',{}).get('/'+name)
    if isinstance(destination,pikepdf.Dictionary):destination=destination.get('/D')
    if not isinstance(destination,pikepdf.Array) or len(destination)<2:raise ValueError('named Link destination unresolved')
    page=destination[0];indices=[i for i,p in enumerate(pdf.pages) if isinstance(page,pikepdf.Dictionary) and p.obj.objgen==page.objgen]
    if len(indices)!=1:raise ValueError('named Link destination page not unique')
    return (indices[0]+1,tuple(str(v) for v in list(destination)[1:]))


def _matches(annotation,record):
    rect=annotation.get('/Rect',[]);expected=record['Rect_pdf_points']
    return (str(annotation.get('/Subtype'))=='/Link' and _destination(annotation)==record['target_name']
            and len(rect)==len(expected)==4 and all(math.isfinite(float(b)) and abs(float(a)-float(b))<=0.0001 for a,b in zip(rect,expected)))

def _owners(root):
    result={};seen=set()
    def walk(node,owner=None):
        if isinstance(node,pikepdf.Array):
            for child in node:walk(child,owner)
        elif isinstance(node,pikepdf.Dictionary):
            if node.objgen!=(0,0):
                if node.objgen in seen:raise ValueError('repeated/cyclic Link structure')
                seen.add(node.objgen)
            if '/S' in node:owner=node if str(node.S)=='/Link' else None
            if str(node.get('/Type'))=='/OBJR':
                obj=node.get('/Obj')
                if obj is not None:result.setdefault(obj.objgen,[]).append((owner,node))
            if '/K' in node:walk(node.K,owner)
    walk(root);return result

def apply_reviewed_link_purposes(working,original,sidecars):
    original_sha=_sha(original);selected=[];other=0
    for path in sidecars:
        data=json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if data.get('schema')!=SCHEMA:raise ValueError('unsupported reviewed Link schema')
        if data.get('original_sha256')!=original_sha:other+=len(data.get('links',[]));continue
        selected.extend(data.get('links',[]))
    if not selected:raise ValueError('reviewed Link input has no matching original SHA')
    identities=[(r['page'],r['target_name'],tuple(r['Rect_pdf_points'])) for r in selected]
    if len(set(identities))!=len(identities):raise ValueError('duplicate reviewed Link bindings')
    outcome={'applied':0,'unmatched':0,'other_source_records':other,'records':[],
             'original_sha256':original_sha,'evidence_source':'model-reviewed-source-bound',
             'external_provider_invoked':False,'painted_label_membership_reconstructed':False,
             'sidecars':[{'path':str(p),'sha256':_sha(p)} for p in sidecars]}
    affected=set();seen=set();paint_verified=set()
    handle=tempfile.NamedTemporaryFile(prefix='.reviewed-links-',suffix='.pdf',dir=Path(working).parent,delete=False);candidate=Path(handle.name);handle.close()
    with pikepdf.open(original) as source,pikepdf.open(working) as pdf,fitz.open(original) as source_text:
        owners=_owners(pdf.Root.StructTreeRoot);parents=_number_tree(pdf.Root.StructTreeRoot.ParentTree)
        for record in selected:
            item={'page':record.get('page'),'target_name':record.get('target_name')};outcome['records'].append(item)
            try:
                label=_meaningful(record.get('proposed_literal_purpose'));index=record['page']-1
                if record.get('proposal_status')!=STATUS or not label:raise ValueError('unreviewed/empty Link purpose')
                if index<0:raise ValueError('invalid reviewed Link page')
                identity=(index,record['target_name'],tuple(record['Rect_pdf_points']))
                if identity in seen:raise ValueError('duplicate reviewed Link binding')
                seen.add(identity)
                originals=[a for a in source.pages[index].obj.get('/Annots',[]) if _matches(a,record)]
                current=[a for a in pdf.pages[index].obj.get('/Annots',[]) if _matches(a,record)]
                if len(originals)!=1 or len(current)!=1:raise ValueError('source/current annotation not unique')
                from .pdf_paint_ownership import _paint_value
                if _paint_value(originals[0].A)!=_paint_value(current[0].A):raise ValueError('reviewed Link action changed')
                source_dest=_named_destination(source,record['target_name']);current_dest=_named_destination(pdf,record['target_name'])
                if source_dest!=current_dest or source_dest[0]!=record['original_destination']['page']:
                    raise ValueError('source/current reviewed Link destination differs')
                if index not in paint_verified:
                    from .pdf_paint_ownership import verified_source_text_shows
                    verified_source_text_shows(source,pdf,index);paint_verified.add(index)
                expected=record.get('source_characters_with_centers_in_annotation',[])
                if not expected:raise ValueError('reviewed Link lacks source glyph evidence')
                chars=[(c,span) for block in source_text[index].get_text('rawdict')['blocks'] for line in block.get('lines',[]) for span in line['spans'] for c in span['chars']]
                frame=fitz.Rect(record['Rect_pdf_points'])*source_text[index].transformation_matrix
                for char in expected:
                    box=fitz.Rect(char['bbox']);center=(box.tl+box.br)/2
                    if center not in frame:raise ValueError('reviewed source glyph lies outside annotation frame')
                    matches=[c for c,span in chars if c['c']==char['char'] and span['font']==char['source_span_font']
                             and abs(span['size']-char['source_span_size'])<=0.0001
                             and all(abs(a-b)<=0.0001 for a,b in zip(c['bbox'],char['bbox']))
                             and all(abs(a-b)<=0.0001 for a,b in zip(c['origin'],char['origin']))]
                    if len(matches)!=1:raise ValueError('reviewed source glyph identity differs')
                annotation=current[0];bindings=owners.get(annotation.objgen,[])
                if len(bindings)!=1 or bindings[0][0] is None:raise ValueError('annotation lacks unique explicit Link OBJR owner')
                owner,objr=bindings[0]
                kids=owner.get('/K',[]);kids=list(kids) if isinstance(kids,pikepdf.Array) else [kids]
                objrs=[k for k in kids if isinstance(k,pikepdf.Dictionary) and str(k.get('/Type'))=='/OBJR']
                mcrs=[k for k in kids if isinstance(k,pikepdf.Dictionary) and '/MCID' in k and '/Stm' not in k]
                if len(objrs)!=1 or len(objrs)+len(mcrs)!=len(kids):raise ValueError('reviewed Link owns unverified content')
                if mcrs:
                    from .pdf_reviewed_tables import _page_owners
                    page=pdf.pages[index];page_owners=_page_owners(pdf.Root.StructTreeRoot,page)
                    page_parents=parents.get(int(page.StructParents))
                    for ref in mcrs:
                        pg=ref.get('/Pg',owner.get('/Pg'));mcid=int(ref.MCID)
                        if pg is None or pg.objgen!=page.obj.objgen or mcid<0 or page_owners.get(mcid) is None or page_owners[mcid].objgen!=owner.objgen:
                            raise ValueError('reviewed Link MCR belongs to another owner/page')
                        if not isinstance(page_parents,pikepdf.Array) or mcid>=len(page_parents) or page_parents[mcid] is None or page_parents[mcid].objgen!=owner.objgen:
                            raise ValueError('reviewed Link MCR ParentTree conflicts')
                if sum(any(o is not None and o.objgen==owner.objgen for o,r in values) for values in owners.values())!=1:
                    raise ValueError('reviewed Link owns another annotation')
                pg=objr.get('/Pg',owner.get('/Pg'))
                if pg is None or pg.objgen!=pdf.pages[index].obj.objgen:raise ValueError('Link OBJR belongs to another page')
                parent=parents.get(int(annotation.get('/StructParent',-1)))
                if not isinstance(parent,pikepdf.Dictionary) or parent.objgen!=owner.objgen:raise ValueError('Link ParentTree owner conflicts')
                if '/ActualText' in owner or str(owner.get('/Alt','')).strip() not in ('',label) or str(annotation.get('/Contents','')).strip() not in ('',label):
                    raise ValueError('reviewed Link conflicts with existing alternative')
                annotation.Contents=pikepdf.String(label)
                if not mcrs:owner.Alt=pikepdf.String(label)
                affected.add(index)
                item.update(status='applied',purpose=label,owner_alternative_applied=not bool(mcrs));outcome['applied']+=1
            except (ValueError,KeyError,IndexError,TypeError) as error:
                item.update(status='unmatched',reason=str(error));outcome['unmatched']+=1
        if not affected:return outcome
        pdf.save(candidate,compress_streams=False,stream_decode_level=pikepdf.StreamDecodeLevel.none)
    try:outcome['fidelity_verification']=verify_isolated_fidelity(working,candidate,affected)
    except ValueError as error:raise ValueError(f'reviewed Link fidelity failed; retained {candidate}: {error}') from error
    os.replace(candidate,working);return outcome
