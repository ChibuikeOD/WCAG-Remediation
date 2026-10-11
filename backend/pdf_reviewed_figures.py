"""Opt-in reviewed alternatives bound to original painting, never candidate IDs."""
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from functools import lru_cache

import fitz
import pikepdf


def _sha(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _records(data):
    """Explicit adapters for the three reviewed evidence formats."""
    for item in data.get('bindings', data.get('records', [])):
        if 'stable_binding' in item:
            s = item['stable_binding']
            yield dict(id=item['proposal_id'], sha=s['requires_original_sha256'],
                       page=item['physical_page'], alt=item['description_text'],
                       subtype=s['original_subtype'],
                       payload=s.get('original_raw_stream_sha256') if s['original_subtype']=='/Image'
                       else s.get('original_decoded_content_sha256'),
                       bbox=s['verified_page_bbox_pdf_exact_decimal'])
        elif 'stable_original_selector' in item:
            s = item['stable_original_selector']; form='form_decoded_stream_sha256' in s
            yield dict(id=item['binding_id'], sha=s['original_pdf_sha256'],
                       page=item['physical_page_1_based'], alt=item['verified_description'],
                       subtype='/Form' if form else '/Image',
                       payload=s.get('form_decoded_stream_sha256') if form else s.get('image_payload_sha256'),
                       bbox=s.get('group_bbox_pdf_bottom_left_points') if form else s.get('bbox_pdf_bottom_left_points'))
        elif 'original' in item:
            original=item['original']; s=original['selected_content']
            yield dict(id=item['proposal_id'], sha=original['sha256'],
                       page=item['physical_page'], alt=item['proposed_alt'], subtype=s['subtype'],
                       payload=s['raw_stream_sha256'] if s['subtype']=='/Image' else s['generalized_decoded_stream_sha256'],
                       bbox=s['verified_placed_bbox_pdf_bottom_left_points'])
        else:
            raise ValueError('unsupported reviewed Figure record')


def _placements(page):
    """Top-level Do ownership only; inner Form MCIDs are a separate namespace."""
    ctm=fitz.Matrix(1,0,0,1,0,0); states=[]; marked=[]
    node=page.obj; seen=set()
    while '/Resources' not in node and '/Parent' in node:
        if node.objgen in seen: raise ValueError('cyclic page resource inheritance')
        seen.add(node.objgen);node=node.Parent
    resources=node.get('/Resources', pikepdf.Dictionary())
    for operands, operator in pikepdf.parse_content_stream(page):
        op=str(operator)
        if op=='q': states.append(fitz.Matrix(ctm))
        elif op=='Q':
            if not states: raise ValueError('unbalanced graphics state')
            ctm=states.pop()
        elif op=='cm': ctm=fitz.Matrix(*map(float,operands))*ctm
        elif op in ('BMC','BDC'):
            props=operands[1] if op=='BDC' else None
            if isinstance(props,pikepdf.Name): props=resources.get('/Properties',{}).get(str(props))
            marked.append((str(operands[0]),int(props['/MCID']) if isinstance(props,pikepdf.Dictionary) and '/MCID' in props else None))
        elif op=='EMC':
            if not marked: raise ValueError('unbalanced marked content')
            marked.pop()
        elif op=='Do':
            obj=resources.get('/XObject',{}).get(str(operands[0]))
            if not isinstance(obj,pikepdf.Stream): continue
            subtype=str(obj.get('/Subtype'))
            if subtype not in ('/Image','/Form'): continue
            if subtype=='/Form' and '/BBox' not in obj: continue
            local=[0,0,1,1] if subtype=='/Image' else list(map(float,obj.BBox))
            matrix=fitz.Matrix(*map(float,obj.get('/Matrix',[1,0,0,1,0,0])))*ctm if subtype=='/Form' else ctm
            points=[fitz.Point(x,y)*matrix for x,y in ((local[0],local[1]),(local[0],local[3]),(local[2],local[1]),(local[2],local[3]))]
            bbox=[min(p.x for p in points),min(p.y for p in points),max(p.x for p in points),max(p.y for p in points)]
            payload=hashlib.sha256(obj.read_raw_bytes() if subtype=='/Image' else obj.read_bytes()).hexdigest()
            yield dict(subtype=subtype,payload=payload,bbox=bbox,object=obj,
                       mcids=[v for tag,v in marked if v is not None],
                       artifact=any(tag=='/Artifact' for tag,v in marked))


def _same(record, placement):
    return (record['subtype']==placement['subtype'] and record['payload']==placement['payload']
            and len(record['bbox'])==4
            and all(math.isfinite(float(a)) and abs(float(a)-b)<=0.0001
                    for a,b in zip(record['bbox'],placement['bbox'])))


def _nested_payloads(obj, active=None):
    """Exact nested painting streams, without treating object IDs as identity."""
    active=set() if active is None else active
    if obj.objgen in active: raise ValueError('cyclic Form painting resources')
    active=active|{obj.objgen}
    subtype=str(obj.get('/Subtype'))
    identity=[subtype,hashlib.sha256(obj.read_raw_bytes() if subtype=='/Image' else obj.read_bytes()).hexdigest()]
    if subtype=='/Form':
        identity.extend([list(map(float,obj.get('/BBox',[]))),list(map(float,obj.get('/Matrix',[1,0,0,1,0,0])))])
        children=obj.get('/Resources',{}).get('/XObject',{})
        identity.append([(str(name),_nested_payloads(child,active)) for name,child in sorted(children.items())])
    elif subtype=='/Image':
        identity.extend([int(obj.get('/Width',0)),int(obj.get('/Height',0)),int(obj.get('/BitsPerComponent',0))])
        mask=obj.get('/SMask')
        if isinstance(mask,pikepdf.Stream): identity.append(_nested_payloads(mask,active))
    return identity


def _owner_index(root):
    """Walk the immutable ownership topology once, indexed by page and MCID.

    Alternative strings can change during the pass; /K, /Pg and /S cannot.
    The index retains only the same Figure references the old per-page walk
    returned, plus page/MCID keys, never decoded painting or raster buffers.
    """
    owners={}; seen=set()
    def walk(node, inherited_page=None, owner=None):
        if isinstance(node,pikepdf.Array):
            for child in node: walk(child,inherited_page,owner)
        elif isinstance(node,pikepdf.Dictionary):
            key=node.objgen
            if key!=(0,0):
                if key in seen: raise ValueError('repeated/cyclic structure node')
                seen.add(key)
            pg=node.get('/Pg',inherited_page)
            if str(node.get('/S'))=='/Figure': owner=node
            if '/MCID' in node:
                if '/Stm' not in node and pg is not None:
                    owners.setdefault(pg.objgen,{}).setdefault(int(node.MCID),[]).append(owner)
            elif '/K' in node: walk(node.K,pg,owner)
        elif isinstance(node,int) and inherited_page is not None:
            owners.setdefault(inherited_page.objgen,{}).setdefault(int(node),[]).append(owner)
    walk(root)
    return owners


def _owners(root, page):
    return _owner_index(root).get(page.obj.objgen,{})


def _paint_index(page):
    """Record painting operators per MCID once for the current page."""
    marked=[];paints={}
    for operands,operator in pikepdf.parse_content_stream(page):
        op=str(operator)
        if op in ('BMC','BDC'):
            props=operands[1] if op=='BDC' else None
            if isinstance(props,pikepdf.Name):props=page.get('/Resources',{}).get('/Properties',{}).get(str(props))
            marked.append(int(props.MCID) if isinstance(props,pikepdf.Dictionary) and '/MCID' in props else None)
        elif op=='EMC':
            if not marked:return None
            marked.pop()
        elif op in {'Do','Tj','TJ',"'",'"','S','s','f','F','f*','B','B*','b','b*','sh','INLINE IMAGE'}:
            # Membership, rather than stack multiplicity, preserves the old
            # single-MCID query when nested marked content repeats an MCID.
            for mcid in set(marked)-{None}:
                values=paints.setdefault(mcid,[])
                if len(values)<2:values.append(op)
    return paints


def _single_do_owner(owner, page, mcid, paints=None):
    kids=owner.get('/K',[])
    kids=list(kids) if isinstance(kids,pikepdf.Array) else [kids]
    if len(kids)!=1: return False
    child=kids[0]
    if isinstance(child,int):
        pg=owner.get('/Pg')
        valid=int(child)==mcid and pg is not None and pg.objgen==page.obj.objgen
    elif isinstance(child,pikepdf.Dictionary):
        pg=child.get('/Pg',owner.get('/Pg'))
        valid=('/MCID' in child and '/Stm' not in child and '/K' not in child
               and int(child.MCID)==mcid and pg is not None and pg.objgen==page.obj.objgen)
    else:valid=False
    if not valid:return False
    paints=_paint_index(page) if paints is None else paints
    return paints is not None and paints.get(mcid,[])==['Do']


def apply_reviewed_figure_alternatives(working: Path, original: Path, sidecars) -> dict:
    original_sha=_sha(original); records=[]
    for path in sidecars:
        records.extend(_records(json.loads(Path(path).read_text(encoding='utf-8'))))
    selected=[r for r in records if r['sha']==original_sha]
    outcome={'applied':0,'unmatched':0,'rejected':0,'other_source_records':len(records)-len(selected),
             'evidence_source':'model-reviewed-source-bound','external_provider_invoked':False,'records':[]}
    outcome['original_sha256']=original_sha
    outcome['sidecars']=[{'sha256':_sha(path),'name':Path(path).name} for path in sidecars]
    duplicates=set()
    for i,record in enumerate(selected):
        for j,other in enumerate(selected[:i]):
            if record['page']==other['page'] and _same(record,other):
                duplicates.update((i,j))
    if not selected: return outcome
    handle=tempfile.NamedTemporaryFile(prefix='.reviewed-figures-',suffix='.pdf',dir=working.parent,delete=False)
    candidate=Path(handle.name);handle.close();affected=set();assigned={}
    with pikepdf.open(original) as source,pikepdf.open(working) as pdf:
        ownership=None;ownership_error=None
        @lru_cache(maxsize=1)
        def page_evidence(index):
            # One page at a time: do not retain image/Form objects or decoded
            # content from every reviewed page in a large document.
            page=pdf.pages[index]
            return (list(_placements(source.pages[index])),list(_placements(page)),_paint_index(page))
        for record_index,record in enumerate(selected):
            status={'id':record['id']};outcome['records'].append(status)
            try:
                if record_index in duplicates: raise ValueError('duplicate/conflicting reviewed placement proposals')
                alt=str(record['alt']).strip(); index=int(record['page'])-1
                if not alt or alt.casefold() in {'image','figure','[image requires alt text]'}:
                    raise ValueError('missing meaningful reviewed alternative')
                source_placements,working_placements,paints=page_evidence(index)
                source_matches=[p for p in source_placements if _same(record,p)]
                if len(source_matches)!=1: raise ValueError('original placement not unique/verified')
                page=pdf.pages[index]
                matches=[p for p in working_placements if _same(record,p)]
                if len(matches)!=1 or matches[0]['artifact'] or len(matches[0]['mcids'])!=1:
                    raise ValueError('working semantic placement not unique')
                if _nested_payloads(source_matches[0]['object'])!=_nested_payloads(matches[0]['object']):
                    raise ValueError('working nested painting differs from original')
                if ownership is None and ownership_error is None:
                    try:ownership=_owner_index(pdf.Root.StructTreeRoot)
                    except (ValueError,IndexError,KeyError,AttributeError) as error:ownership_error=error
                if ownership_error is not None:raise ownership_error
                page_owners=ownership.get(page.obj.objgen,{})
                mcid=matches[0]['mcids'][0];owners=page_owners.get(mcid,[])
                if len(owners)!=1 or owners[0] is None: raise ValueError('unique Figure owner absent')
                owner=owners[0];key=owner.objgen
                if not _single_do_owner(owner,page,mcid,paints):
                    raise ValueError('Figure is not an exclusive single-Do page owner')
                attributes=owner.get('/A',[])
                attributes=list(attributes) if isinstance(attributes,pikepdf.Array) else [attributes]
                bounds=[a['/BBox'] for a in attributes if isinstance(a,pikepdf.Dictionary) and '/BBox' in a]
                if len(bounds)!=1 or len(bounds[0])!=4 or any(abs(float(a)-b)>0.0001 for a,b in zip(bounds[0],matches[0]['bbox'])):
                    raise ValueError('Figure geometry does not cover verified placement')
                if key in assigned or str(owner.get('/Alt','')).strip() not in ('',alt):
                    raise ValueError('duplicate/conflicting Figure alternative')
                # One reviewed whole-placement description must not silently
                # cover other MCIDs or repeated painting owned by this Figure.
                owner_mcids=[m for m,values in page_owners.items()
                             if any(v is not None and v.objgen==key for v in values)]
                if owner_mcids!=[mcid]: raise ValueError('Figure owns additional content')
                if sum(mcid in p['mcids'] for p in working_placements)!=1:
                    raise ValueError('MCID paints additional XObjects')
                assigned[key]=alt;owner.Alt=pikepdf.String(alt);affected.add(index)
                status.update(status='applied',page=index+1,mcid=mcid)
                outcome['applied']+=1
            except (ValueError,IndexError,KeyError,AttributeError) as error:
                status.update(status='unmatched',reason=str(error));outcome['unmatched']+=1
        page_evidence.cache_clear()
        if not affected: return outcome
        pdf.save(candidate,compress_streams=False,stream_decode_level=pikepdf.StreamDecodeLevel.none)
    from .pdf_visual_fidelity import verify_isolated_fidelity
    try:
        outcome['fidelity_verification']=verify_isolated_fidelity(working,candidate,affected)
    except (ValueError,TimeoutError,RuntimeError) as error:
        raise ValueError(f'reviewed Figure fidelity verification failed: {error}; retained {candidate}') from error
    os.replace(candidate,working)
    return outcome
