"""Remove only source-reviewed, empty duplicate Table projections over graphics."""
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path

import pikepdf
import fitz

from .pdf_reviewed_figures import _placements, _same, _nested_payloads, _owners, _single_do_owner
from .pdf_reviewed_tables import _number_tree


def _records(data):
    if data.get('schema_version')=='pdfaccess.table-projection-classification.v1':
        for item in data['classifications']:
            if item.get('review_status')!='REVIEWED_SOURCE_SPECIFIC_MODEL_VISUAL_AND_OWNERSHIP' or item.get('classification')!='FIGURE_PLOT_WRONGLY_DETECTED_AS_TABLE':continue
            proof=item['existing_actual_payload_owner'];placement=proof['actual_Do_source_payload_proof']['candidate_Do']
            yield dict(id=item['review_id'],sha=item['original_input_sha256'],page=item['physical_page'],
                       bbox=item['full_detected_table_bbox_pdf'],rows=item['current_TR_count'],
                       roles=item['current_cell_role_counts'],
                       graphic=dict(subtype=placement['resource_subtype'],payload=placement['decoded_resource_sha256'],
                                    bbox=proof['current_Figure_layout_bboxes_pdf'][0]))
    elif data.get('document_id')=='D02' and 'false_table_annotation_crosswalk' in data:
        for index,item in enumerate(data['false_table_annotation_crosswalk']):
            if item.get('classification')!='false_algorithmic_Table_annotation_over_graphic':continue
            selector=item['stable_whole_source_selector'];cells=item['actual_cells'];roles={}
            for cell in cells:roles[cell['role']]=roles.get(cell['role'],0)+1
            yield dict(id=f'D02-reviewed-projection-{index}',sha=selector['original_pdf_sha256'],
                       page=selector['physical_page_1_based'],bbox=item['union_of_actual_cell_BBoxes_pdf_float'],
                       rows=item['native_failed_context']['table_rows'],roles=roles,
                       graphic=dict(subtype='/Form',payload=selector['decoded_Form_stream_sha256'],
                                    bbox=selector['bbox_pdf_bottom_left_exact_nominal_decimal_strings']))
    else:raise ValueError('unsupported reviewed projection input')


def _kids(node):
    value=node.get('/K',[])
    return list(value) if isinstance(value,pikepdf.Array) else [value]


def _structure(root):
    seen=set();result=[]
    def walk(node,parent=None,pg=None):
        if not isinstance(node,pikepdf.Dictionary):return
        if parent is not None and ('/P' not in node or node.P.objgen!=parent.objgen):raise ValueError('structure parent membership mismatch')
        identity=tuple(node.objgen)
        if identity!=(0,0):
            if identity in seen:raise ValueError('repeated/cyclic structure ownership')
            seen.add(identity)
        pg=node.get('/Pg',pg);result.append((node,parent,pg))
        for child in _kids(node):
            if isinstance(child,pikepdf.Dictionary) and '/S' in child:walk(child,node,pg)
    walk(root)
    return result


def _empty_grid(table):
    rows=_kids(table);boxes=[];roles={};nodes=[table]
    if not rows:return None
    for row in rows:
        if not isinstance(row,pikepdf.Dictionary) or str(row.get('/S'))!='/TR':return None
        nodes.append(row);cells=_kids(row)
        if not cells:return None
        for cell in cells:
            if not isinstance(cell,pikepdf.Dictionary) or str(cell.get('/S')) not in ('/TH','/TD'):return None
            if _kids(cell):return None
            nodes.append(cell);role=str(cell.S);roles[role]=roles.get(role,0)+1
            attrs=cell.get('/A',[]);attrs=list(attrs) if isinstance(attrs,pikepdf.Array) else [attrs]
            b=[list(map(float,a.BBox)) for a in attrs if isinstance(a,pikepdf.Dictionary) and '/BBox' in a]
            if len(b)!=1 or len(b[0])!=4 or not all(math.isfinite(v) for v in b[0]):return None
            boxes.append(b[0])
    # IDs and references require a separate semantic dependency repair.
    for node in nodes:
        if any(key in node for key in ('/ID','/Ref','/ActualText','/Alt')):return None
        attrs=node.get('/A',[]);attrs=list(attrs) if isinstance(attrs,pikepdf.Array) else [attrs]
        if any(isinstance(a,pikepdf.Dictionary) and '/Headers' in a for a in attrs):return None
    return dict(rows=len(rows),roles=roles,nodes=nodes,
                bbox=[min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)])


def _near(a,b):
    return len(a)==len(b)==4 and all(abs(float(x)-float(y))<=0.0001 for x,y in zip(a,b))


def _references(value,targets,active=None):
    active=set() if active is None else active
    if not isinstance(value,(pikepdf.Array,pikepdf.Dictionary,pikepdf.Stream)):return False
    identity=tuple(value.objgen)
    if identity!=(0,0):
        if identity in targets:return True
        if identity in active:return False
        active=active|{identity}
    if isinstance(value,pikepdf.Dictionary) and '/S' in value:return False
    values=value if isinstance(value,pikepdf.Array) else [child for _,child in value.items()]
    return any(_references(child,targets,active) for child in values)


def apply_reviewed_table_projections(working: Path,original: Path,sidecars):
    working=Path(working);original=Path(original)
    sha=hashlib.sha256(original.read_bytes()).hexdigest();applied=[];unmatched=[];affected=set();candidate=None;records=[];evidence=[]
    for path in sidecars:
        path=Path(path);sidecar_sha=hashlib.sha256(path.read_bytes()).hexdigest()
        for record in _records(json.loads(path.read_text(encoding='utf-8-sig'))):
            record['sidecar_sha256']=sidecar_sha;records.append(record)
    other_source_records=sum(record['sha']!=sha for record in records)
    records=[record for record in records if record['sha']==sha]
    if not records:
        return dict(applied=0,applied_review_ids=[],applied_evidence=[],considered=0,other_source_records=other_source_records,
                    unmatched=1,unmatched_records=[dict(id='source-binding',reason='original SHA mismatch: no matching reviewed source')],
                    original_sha256=sha,external_provider_invoked=False)
    duplicate_ids={r['id'] for r in records if sum(v['id']==r['id'] for v in records)>1}
    with pikepdf.open(original) as source,pikepdf.open(working) as pdf:
        root=pdf.Root.get('/StructTreeRoot')
        if root is None:raise ValueError('missing structure tree')
        for record in records:
            try:
                if record['id'] in duplicate_ids:raise ValueError('duplicate review identity')
                if record['sha']!=sha:raise ValueError('original SHA mismatch')
                index=int(record['page'])-1
                if not 0<=index<len(source.pages) or len(source.pages)!=len(pdf.pages):raise ValueError('invalid page binding')
                page=pdf.pages[index]
                old=[v for v in _placements(source.pages[index]) if _same(record['graphic'],v)]
                current=[v for v in _placements(page) if _same(record['graphic'],v)]
                if len(old)!=1 or len(current)!=1:raise ValueError('nonunique source/current graphic')
                graphic=current[0]
                t=list(map(float,record['bbox']));g=graphic['bbox']
                if not (g[0]-0.0001<=t[0]<t[2]<=g[2]+0.0001 and g[1]-0.0001<=t[1]<t[3]<=g[3]+0.0001):raise ValueError('projection is outside reviewed graphic')
                if graphic['artifact'] or len(graphic['mcids'])!=1 or _nested_payloads(old[0]['object'])!=_nested_payloads(graphic['object']):raise ValueError('changed graphic ownership/payload')
                mcid=graphic['mcids'][0];owners=_owners(root,page).get(mcid,[])
                if len(owners)!=1 or owners[0] is None or not _single_do_owner(owners[0],page,mcid):raise ValueError('graphic does not have complete single-Do Figure owner')
                tree=_number_tree(root.get('/ParentTree',{}));slots=tree.get(int(page.get('/StructParents',-1)),[])
                if mcid>=len(slots) or slots[mcid].objgen!=owners[0].objgen:raise ValueError('Figure ParentTree ownership mismatch')
                matches=[]
                for node,parent,pg in _structure(root):
                    if str(node.get('/S'))!='/Table' or pg is None or pg.objgen!=page.obj.objgen:continue
                    grid=_empty_grid(node)
                    if grid and grid['rows']==record['rows'] and grid['roles']==record['roles'] and _near(grid['bbox'],record['bbox']):matches.append((node,parent,grid))
                if len(matches)!=1:raise ValueError('nonunique or nonempty reviewed table projection')
                node,parent,grid=matches[0]
                if parent is None or str(parent.get('/S')) not in ('/Document','/Part','/Sect'):raise ValueError('protected table ancestor')
                ancestor=parent;seen=set()
                while isinstance(ancestor,pikepdf.Dictionary):
                    identity=tuple(ancestor.objgen)
                    if identity in seen:raise ValueError('cyclic table ancestor')
                    seen.add(identity)
                    if str(ancestor.get('/S')) in ('/Link','/Formula','/Note','/Reference'):raise ValueError('protected table ancestor')
                    ancestor=ancestor.get('/P')
                targets={tuple(n.objgen) for n in grid['nodes']}
                if any(_references(root.get(key),targets) for key in ('/IDTree','/ParentTree')):raise ValueError('referenced projection structure')
                if any(_references(other.get('/Ref'),targets) for other,_,_ in _structure(root)):raise ValueError('external structure Ref dependency')
                parent.K=pikepdf.Array([child for child in _kids(parent) if not isinstance(child,pikepdf.Dictionary) or child.objgen!=node.objgen])
                applied.append(record['id']);affected.add(index)
                evidence.append(dict(review_id=record['id'],sidecar_sha256=record['sidecar_sha256'],physical_page=index+1,
                                     source_graphic_payload_sha256=record['graphic']['payload'],reviewed_table_bbox=record['bbox'],
                                     resolution_source='source-specific-model-reviewed-classification'))
            except (ValueError,KeyError,IndexError,TypeError,AttributeError) as exc:unmatched.append(dict(id=record['id'],reason=str(exc)))
        if applied:
            fd,name=tempfile.mkstemp(prefix='.reviewed-projections-',suffix='.pdf',dir=working.parent);os.close(fd)
            candidate=Path(name)
            pdf.save(candidate,compress_streams=False,stream_decode_level=pikepdf.StreamDecodeLevel.none)
    if candidate is not None:
        with fitz.open(working) as before,fitz.open(candidate) as after:
            for index in affected:
                a,b=before[index],after[index]
                if a.get_text()!=b.get_text() or a.get_pixmap(dpi=96,alpha=False).samples!=b.get_pixmap(dpi=96,alpha=False).samples:
                    raise ValueError(f'projection edit changed painting/text; retained {candidate}')
        os.replace(candidate,working)
    return dict(applied=len(applied),applied_review_ids=applied,applied_evidence=evidence,considered=len(records),other_source_records=other_source_records,unmatched=len(unmatched),unmatched_records=unmatched,
                original_sha256=sha,external_provider_invoked=False)
