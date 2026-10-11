"""Source-bound complete graphic ownership, without changing any painting.

Only literal, reviewed whole-group alternatives are accepted. Typed lists and
partial expressions remain held. Original instruction numbers address a pinned
source program; current MCIDs and structure owners are resolved afresh.
"""
import hashlib
import json
import os
import tempfile
from decimal import Decimal, localcontext
from pathlib import Path

import pikepdf

from .pdf_paint_ownership import _paint_value
from .pdf_reviewed_figures import _sha
from .pdf_reviewed_tables import _PAINT, _scopes, _page_owners, _number_tree, _prune_removed
from .pdf_visual_fidelity import verify_isolated_fidelity

_APPROVED='REVIEWED_SOURCE_SPECIFIC_COMPLETE_GROUP_LITERAL_ALTERNATIVE'
_MARK={'BMC','BDC','EMC'}


def _argument(value):
    if isinstance(value,pikepdf.String):return {'string_hex':bytes(value).hex()}
    if isinstance(value,pikepdf.Array):return [_argument(v) for v in value]
    if isinstance(value,pikepdf.Dictionary):return {str(k):_argument(v) for k,v in sorted(value.items())}
    if isinstance(value,bool) or value is None:return value
    if isinstance(value,(int,float,Decimal)):
        number=Decimal(str(value))
        with localcontext() as context:
            context.prec=max(120,len(number.as_tuple().digits))
            return {'number':'0' if not number else format(number.normalize(),'f')}
    if isinstance(value,pikepdf.Name):return {'name':str(value)}
    raise ValueError('unsupported complete graphic source operand')


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')).hexdigest()


def _program(page):
    instructions=list(pikepdf.parse_content_stream(page))
    pairs=[(index,{'operator':str(op),'operands':[_argument(v) for v in args]})
           for index,(args,op) in enumerate(instructions) if str(op) not in _MARK]
    if any(item['operator'] in ('MP','DP','INLINE IMAGE') for _,item in pairs):
        raise ValueError('unsupported graphic marking or inline image namespace')
    return instructions,pairs


def _resources(page):
    node=page.obj;seen=set()
    while '/Resources' not in node and '/Parent' in node:
        if node.objgen in seen:raise ValueError('cyclic graphic page resources')
        seen.add(node.objgen);node=node.Parent
    return node.get('/Resources',pikepdf.Dictionary())


def _raw_images(obj,active=None):
    """Retain exact encoded image and transparency-mask payload identity."""
    active=set() if active is None else active
    if obj.objgen in active:raise ValueError('cyclic graphic XObject graph')
    active=active|{obj.objgen};subtype=str(obj.get('/Subtype'))
    if subtype=='/Image':
        masks=[(name,hashlib.sha256(obj[name].read_raw_bytes()).hexdigest())
               for name in ('/Mask','/SMask') if isinstance(obj.get(name),pikepdf.Stream)]
        return (subtype,hashlib.sha256(obj.read_raw_bytes()).hexdigest(),masks)
    if subtype=='/Form':
        return (subtype,[(str(name),_raw_images(child,active)) for name,child in sorted(obj.get('/Resources',{}).get('/XObject',{}).items())])
    raise ValueError('unsupported graphic XObject subtype')


def _verify_page(source,page):
    for key in ('/MediaBox','/CropBox','/Rotate','/UserUnit'):
        if _paint_value(source.get(key))!=_paint_value(page.get(key)):
            raise ValueError('graphic page geometry differs from source')
    _,left=_program(source);instructions,right=_program(page)
    if [v for _,v in left]!=[v for _,v in right]:
        raise ValueError('graphic page non-marking program differs from source')
    a,b=_resources(source),_resources(page)
    categories={'Tf':'/Font','Do':'/XObject','gs':'/ExtGState','sh':'/Shading','cs':'/ColorSpace','CS':'/ColorSpace'}
    for _,item in left:
        op=item['operator'];args=item['operands'];category=categories.get(op)
        if category is not None:name=args[0]['name']
        elif op in ('scn','SCN') and args and isinstance(args[-1],dict) and 'name' in args[-1]:
            category='/Pattern';name=args[-1]['name']
        else:continue
        if category=='/ColorSpace' and name in ('/DeviceGray','/DeviceRGB','/DeviceCMYK','/Pattern'):continue
        with localcontext() as context:
            context.prec=120
            if _paint_value(a[category][name])!=_paint_value(b[category][name]):
                raise ValueError('graphic source painting resource differs')
        if category=='/XObject' and _raw_images(a[category][name])!=_raw_images(b[category][name]):
            raise ValueError('graphic encoded image or mask payload differs')
    return instructions,left,right


def _bind_group(group,source,page):
    instructions,left,right=_verify_page(source,page)
    selector=group['actual06_source_program_selector']
    program=[v for _,v in left]
    if selector['physical_page']!=group['physical_page'] or _digest(program)!=selector['original_page_canonical_program_sha256']:
        raise ValueError('graphic original full program identity mismatch')
    start,end=selector['source_non_marking_operator_range_inclusive']
    if type(start) is not int or type(end) is not int or not 0<=start<=end<len(program):
        raise ValueError('invalid complete graphic source range')
    if program[start]['operator']!='q' or program[end]['operator']!='Q':
        raise ValueError('complete graphic is not an explicit graphics-state group')
    depth=0
    for item in program[start:end+1]:
        if item['operator']=='q':depth+=1
        elif item['operator']=='Q':depth-=1
        if depth<0:raise ValueError('unbalanced complete graphic graphics state')
    if depth:raise ValueError('unclosed complete graphic graphics state')
    if _digest(program[start:end+1])!=selector['selected_ordered_program_sha256']:
        raise ValueError('graphic selected program identity mismatch')
    members=group['ordered_complete_source_paint_members']
    if _digest(members)!=group['ordered_complete_source_paint_members_sha256']:
        raise ValueError('graphic reviewed member list identity mismatch')
    indices=[member['original_non_marking_operator_index'] for member in members]
    expected=[i for i in range(start,end+1) if program[i]['operator'] in _PAINT]
    if indices!=expected or not expected:
        raise ValueError('graphic reviewed members do not own complete source painting')
    return {right[i][0] for i in expected}


def _graphic_slot(root,owner):
    target=owner;seen=set()
    while '/P' in target:
        if target.objgen in seen:raise ValueError('cyclic graphic insertion ancestry')
        seen.add(target.objgen);parent=target.P
        if parent.objgen==root.objgen or str(parent.get('/S')) in ('/Document','/Part','/Sect'):
            kids=parent.get('/K',[]);kids=list(kids) if isinstance(kids,pikepdf.Array) else [kids]
            matches=[i for i,v in enumerate(kids) if isinstance(v,pikepdf.Dictionary) and v.objgen==target.objgen]
            if len(matches)!=1:raise ValueError('graphic insertion parent and child disagree')
            return parent,matches[0]
        target=parent
    raise ValueError('graphic insertion owner not attached to root')


def _rewrite_page(pdf,page,groups):
    root=pdf.Root.StructTreeRoot;instructions,scopes=_scopes(page)
    targets={};group_targets={}
    for group,indices in groups:
        if set(targets)&indices:raise ValueError('overlapping complete graphic groups')
        group_targets[group['group_id']]=indices
        targets.update({i:group['group_id'] for i in indices})
    selected=set(targets);owners=_page_owners(root,page)
    parent_values=_number_tree(root.ParentTree);page_key=int(page.StructParents)
    old_parents=parent_values.get(page_key)
    if not isinstance(old_parents,pikepdf.Array):raise ValueError('graphic page ParentTree absent')
    removed=set();drop=set();slots={}
    for scope in scopes:
        covered=scope['paint']&selected
        if not covered:continue
        if scope['actual_text']:raise ValueError('graphic intersects existing ActualText')
        mcid=scope['mcid']
        if mcid is not None:
            if scope['paint']-selected:raise ValueError('graphic MCID owns outside painting; source-bound split required')
            if len({targets[i] for i in scope['paint']})!=1:
                raise ValueError('graphic MCID spans multiple proposed groups')
            owner=owners.get(mcid)
            if owner is None or mcid>=len(old_parents) or old_parents[mcid] is None or old_parents[mcid].objgen!=owner.objgen:
                raise ValueError('graphic ParentTree and structure ownership disagree')
            ancestor=owner;seen=set()
            while isinstance(ancestor,pikepdf.Dictionary):
                if ancestor.objgen in seen:raise ValueError('cyclic graphic structure ancestry')
                seen.add(ancestor.objgen)
                if '/ID' in ancestor or '/ActualText' in ancestor or str(ancestor.get('/S')) in ('/Link','/Formula','/Note','/Reference','/Table','/L'):
                    raise ValueError('graphic intersects dependent explicit semantics')
                ancestor=ancestor.get('/P')
            group_id=targets[next(iter(covered))]
            slots.setdefault(group_id,[]).append(_graphic_slot(root,owner))
            removed.add(mcid);drop.update((scope['start'],scope['end']))
        elif not scope['paint']-selected:drop.update((scope['start'],scope['end']))
    # A Figure that partly remains outside a whole group must keep its local Alt.
    for mcid in removed:
        owner=owners[mcid]
        if str(owner.get('/S'))=='/Figure' and any(v.objgen==owner.objgen and m not in removed for m,v in owners.items() if v is not None):
            raise ValueError('graphic Figure retains outside content')
    insertion=[]
    for group,indices in groups:
        options=slots.get(group['group_id'],[])
        if not options:raise ValueError('graphic source-owned structure slot absent')
        parent,index=min(options,key=lambda item:item[1])
        if any(p.objgen!=parent.objgen for p,_ in options):raise ValueError('graphic spans structural containers')
        kids=parent.get('/K',[]);kids=list(kids) if isinstance(kids,pikepdf.Array) else [kids]
        prefixes={v.objgen for v in kids[:index] if isinstance(v,pikepdf.Dictionary)}
        insertion.append((group,parent,index,prefixes))
    parents=pikepdf.Array(list(old_parents))
    next_mcid=max(len(parents),1+max([s['mcid'] for s in scopes if s['mcid'] is not None]+[-1]))
    new_mcids={i:next_mcid+n for n,i in enumerate(sorted(selected))}
    while len(parents)<next_mcid+len(selected):parents.append(None)
    for mcid in removed:parents[mcid]=None
    nodes={};local_figures={};paint_local_owner={};local_updates=[]
    for scope in scopes:
        if scope['mcid'] not in removed:continue
        owner=owners[scope['mcid']];alt=str(owner.get('/Alt','')).strip()
        if str(owner.get('/S'))!='/Figure' or not alt or alt.casefold() in {'image','figure','[image requires alt text]'}:continue
        local_figures[owner.objgen]=owner
        for i in scope['paint']:paint_local_owner[i]=owner.objgen
    for key in local_figures:
        if len({targets[i] for i,v in paint_local_owner.items() if v==key})!=1:
            raise ValueError('existing local Figure alternative spans proposed groups')
    for group,parent,index,prefixes in insertion:
        node=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructElem'),S=pikepdf.Name('/Figure'),P=parent,Pg=page.obj,Alt=pikepdf.String(group['proposed_Alt'].strip())))
        children=[];included=set()
        for i in sorted(group_targets[group['group_id']]):
            key=paint_local_owner.get(i);mcid=new_mcids[i]
            # Existing meaningful image-local alternatives survive verbatim
            # as child Figures. The reviewed whole description occurs once.
            if key is not None and str(local_figures[key].Alt).strip()!=group['proposed_Alt'].strip():
                local=local_figures[key]
                if key not in included:
                    kids=pikepdf.Array([pikepdf.Dictionary(Type=pikepdf.Name('/MCR'),Pg=page.obj,MCID=new_mcids[j]) for j in sorted(group_targets[group['group_id']]) if paint_local_owner.get(j)==key])
                    local_updates.append((local,node,kids))
                    children.append(local);included.add(key)
                parents[mcid]=local
            else:
                children.append(pikepdf.Dictionary(Type=pikepdf.Name('/MCR'),Pg=page.obj,MCID=mcid));parents[mcid]=node
        node.K=pikepdf.Array(children)
        nodes[group['group_id']]=node
    _prune_removed(root,page.obj.objgen,removed)
    for local,parent,kids in local_updates:
        local.P=parent;local.Pg=page.obj;local.K=kids
    for group,parent,index,prefixes in sorted(insertion,key=lambda entry:(entry[2],min(group_targets[entry[0]['group_id']])),reverse=True):
        kids=parent.get('/K',[]);kids=list(kids) if isinstance(kids,pikepdf.Array) else [kids]
        position=sum(isinstance(v,pikepdf.Dictionary) and v.objgen in prefixes for v in kids)
        kids.insert(position,nodes[group['group_id']]);parent.K=pikepdf.Array(kids)
    parent_values[page_key]=parents
    root.ParentTree=pikepdf.Dictionary(Nums=pikepdf.Array([v for key in sorted(parent_values) for v in (key,parent_values[key])]))
    active=[];rewritten=[];starts={scope['start']:scope for scope in scopes}
    for index,instruction in enumerate(instructions):
        op=str(instruction[1])
        if op in ('BMC','BDC'):
            active.append(starts[index])
            if index not in drop:rewritten.append(instruction)
        elif op=='EMC':
            active.pop()
            if index not in drop:rewritten.append(instruction)
        elif index in selected:
            keep=[scope for scope in active if scope['start'] not in drop]
            for scope in reversed(keep):rewritten.append((pikepdf.Array([]),pikepdf.Operator('EMC')))
            rewritten.extend([(pikepdf.Array([pikepdf.Name('/Figure'),pikepdf.Dictionary(MCID=new_mcids[index])]),pikepdf.Operator('BDC')),instruction,(pikepdf.Array([]),pikepdf.Operator('EMC'))])
            for scope in keep:rewritten.append((scope['operands'],scope['operator']))
        else:rewritten.append(instruction)
    page.Contents=pdf.make_stream(pikepdf.unparse_content_stream(rewritten))
    return {'groups':len(groups),'new_mcids':len(selected),'removed_mcids':len(removed)}


def apply_reviewed_graphic_groups(working,original,sidecar):
    working=Path(working);original=Path(original)
    data=json.loads(Path(sidecar).read_text(encoding='utf-8'));original_sha=_sha(original)
    if data.get('schema_version')!='pdfaccess.source-bound-complete-graphic-group-proposals.v1' or data['original']['sha256']!=original_sha:
        raise ValueError('complete graphic original/schema identity mismatch')
    outcome={'applied':0,'held':[],'records':[],'original_sha256':original_sha,'sidecar_sha256':_sha(sidecar),'external_provider_invoked':False}
    accepted=[];ids=set()
    for group in data['group_proposals']:
        if group['group_id'] in ids:raise ValueError('duplicate complete graphic group ID')
        ids.add(group['group_id'])
        if group['status']!=_APPROVED or not isinstance(group.get('proposed_Alt'),str) or not group['proposed_Alt'].strip():
            outcome['held'].append({'id':group['group_id'],'reason':'typed or incomplete semantics require a separate owner'});continue
        if group['original_pdf_sha256']!=original_sha or group['actual06_source_program_selector']['original_input_sha256']!=original_sha:
            raise ValueError('complete graphic per-group original identity mismatch')
        accepted.append(group)
    if not accepted:return outcome
    handle=tempfile.NamedTemporaryFile(prefix='.reviewed-graphic-groups-',suffix='.pdf',dir=working.parent,delete=False)
    candidate=Path(handle.name);handle.close();affected=set()
    with pikepdf.open(original) as source,pikepdf.open(working) as pdf:
        pages={}
        for group in accepted:
            index=group['physical_page']-1
            if type(index) is not int or index<0 or index>=len(source.pages):raise ValueError('invalid complete graphic physical page')
            binding=_bind_group(group,source.pages[index],pdf.pages[index])
            pages.setdefault(index,[]).append((group,binding))
        for index,groups in pages.items():
            proof=_rewrite_page(pdf,pdf.pages[index],groups);affected.add(index)
            for group,_ in groups:outcome['records'].append({'id':group['group_id'],'page':index+1,'status':'applied','page_ownership_proof':proof})
        pdf.save(candidate,compress_streams=False,stream_decode_level=pikepdf.StreamDecodeLevel.none)
    try:outcome['fidelity_verification']=verify_isolated_fidelity(working,candidate,affected)
    except (ValueError,TimeoutError,RuntimeError) as error:
        raise ValueError(f'complete graphic fidelity failed; retained {candidate}: {error}') from error
    os.replace(candidate,working);outcome['applied']=len(accepted)
    return outcome
