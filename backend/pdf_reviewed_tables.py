"""Source-bound reviewed table grids and exact text-show ownership."""
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import os
import tempfile

import fitz
import pikepdf

from .pdf_paint_ownership import _glyphs, text_show_ownership, verified_source_text_shows
from .pdf_reviewed_figures import _sha, _placements, _same, _single_do_owner, _nested_payloads


def _review_tables(path):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    for table in data.get('tables',data.get('records',[])):
        if 'stable_original_selector' in table:
            selector=table['stable_original_selector']
            inverse=fitz.Matrix(*table['coordinate_transforms']['upright_to_source_fitz_top_left'])
            cells=[]
            for c in table['cells']:
                glyphs=[{'text':g['literal'],'origin':list(fitz.Point(*g['origin_upright_points'])*inverse)}
                        for g in c['source_glyph_boxes'] if not g['literal'].isspace()]
                cells.append(dict(id=c['cell_id'],row=c['logical_row_index_0_based'],col=c['logical_column_index_0_based'],
                    rowspan=c['row_span'],colspan=c['column_span'],role=c['intended_role'],scope=c['header_scope'],
                    headers=c['header_cell_ids'],glyphs=glyphs,literal=c['source_emission_compact_text'],bbox=c['cell_region_pdf_bottom_left_points']))
            yield dict(id=table['table_binding_id'],sha=selector['original_pdf_sha256'],page=selector['physical_page_1_based'],
                       cells=cells,caption_ids=selector.get('caption_glyph_ids',[]),caption=selector['caption_literal'],
                       caption_words=None,source_format='A')
        elif 'original' in table:
            original=table['original'];cells=[]
            for c in table['cells']:
                cells.append(dict(id=c['cell_id'],row=c['physical_grid_row_1_based']-1,col=c['column_1_based']-1,
                    rowspan=c['row_span'],colspan=c['column_span'],role=c['proposed_role'],scope=c['proposed_scope'],
                    headers=c['header_refs'],glyphs=[{'text':g['literal_char'],'origin':g['origin_mupdf']}
                    for g in c['glyphs'] if not g['literal_char'].isspace()],literal=c['literal_text_from_native_words'],
                    bbox=c['allocation_bbox_pdf_bottom_left_points']))
            yield dict(id=table['proposal_id'],sha=original['sha256'],page=original['physical_page_1_based'],cells=cells,
                       caption=table['caption_binding']['visible_anchor'],caption_words=table['caption_binding']['native_literal_words'],
                       source_format='B')
        elif 'original_sha256' in table:
            evidence=table['source_layout_evidence'];geometry_path=Path(evidence['path'])
            if _sha(geometry_path)!=evidence['sha256']:raise ValueError('table glyph evidence hash mismatch')
            geometry=json.loads(geometry_path.read_text(encoding='utf-8'))
            if geometry['original_sha256']!=table['original_sha256']:raise ValueError('table glyph evidence source mismatch')
            catalog={g['glyph_id']:g for g in geometry['glyphs']};cells=[]
            for c in table['cells']:
                glyphs=[]
                for identifier in c['source_glyph_ids']:
                    g=catalog[identifier]
                    if not g['text_extracted'].isspace():glyphs.append({'text':g['text_extracted'],'origin':g['origin_pymupdf']})
                cells.append(dict(id=c['cell_id'],row=c['logical_row'],col=c['logical_column'],rowspan=c['rowspan'],
                    colspan=c['colspan'],role=c['role_proposal'],scope=c['scope_proposal'],headers=c['headers_proposal'],
                    glyphs=glyphs,literal=c['literal_source_extracted_text'],bbox=c['region_pdf_points']))
                if not glyphs and (str(c.get('literal_visually_verified_text','') or '').strip()
                                   or c.get('embedded_image_binding')):
                    cells[-1]['raster_literal_without_native_glyphs']=True
                if c.get('embedded_image_binding'):
                    cells[-1]['embedded_image_binding']=c['embedded_image_binding']
            captions=[{'text':catalog[i]['text_extracted'],'origin':catalog[i]['origin_pymupdf']}
                      for i in table['caption_source_glyph_ids'] if not catalog[i]['text_extracted'].isspace()]
            yield dict(id=table['table_id'],sha=table['original_sha256'],page=table['physical_page'],cells=cells,
                       caption=table['caption_literal_extracted_text'],caption_glyphs=captions,caption_words=None,source_format='C')
        else:raise ValueError('unsupported reviewed table format')


def _near_origin(a,b):
    return all(abs(float(x)-float(y))<=0.0001 for x,y in zip(a,b))


def _source_catalog(page):
    catalog={}
    for bi,block in enumerate(page.get_text('rawdict')['blocks']):
        for li,line in enumerate(block.get('lines',[])):
            for si,span in enumerate(line['spans']):
                for gi,char in enumerate(span['chars']):
                    catalog[f'b{bi}-l{li}-s{si}-g{gi}']={'text':char['c'],'origin':list(char['origin'])}
    return catalog


def bind_table_text_shows(table, source_page, working_pdf, source_pdf=None):
    """Prove whole-show membership from reviewed source glyph origins.

    A show spanning cells, unassigned Form glyph, overlapping ownership or
    source-literal mismatch rejects the grid; no centroid allocation is used.
    """
    cells=table['cells'];by_id={c['id']:c for c in cells}
    if len(by_id)!=len(cells):raise ValueError('duplicate cell IDs')
    occupied=set()
    for c in cells:
        if c.get('raster_literal_without_native_glyphs') and not c.get('embedded_image_binding'):
            raise ValueError('raster cell requires verified image-region painting ownership')
        if c['role'] not in ('TH','TD') or c['row']<0 or c['col']<0 or c['rowspan']<1 or c['colspan']<1:
            raise ValueError('invalid reviewed grid/role')
        if c['scope'] not in (None,'row','column','both','Row','Column','Both'):raise ValueError('unsupported reviewed header scope')
        for header in c['headers']:
            if header not in by_id or by_id[header]['role']!='TH':raise ValueError('header references unknown/non-header cell')
        for row in range(c['row'],c['row']+c['rowspan']):
            for col in range(c['col'],c['col']+c['colspan']):
                if (row,col) in occupied:raise ValueError('overlapping reviewed cell spans')
                occupied.add((row,col))
    visiting=set();complete=set()
    def check_header_chain(cell_id):
        if cell_id in visiting:raise ValueError('cyclic reviewed header references')
        if cell_id in complete:return
        visiting.add(cell_id)
        for header in by_id[cell_id]['headers']:check_header_chain(header)
        visiting.remove(cell_id);complete.add(cell_id)
    for cell_id in by_id:check_header_chain(cell_id)
    source=_glyphs(source_page)
    if table['source_format']=='A':
        catalog=_source_catalog(source_page)
        caption_glyphs=[catalog[i] for i in table['caption_ids'] if not catalog[i]['text'].isspace()]
    elif table.get('caption_glyphs') is not None:caption_glyphs=table['caption_glyphs']
    else:
        caption_glyphs=[]
        for word in table['caption_words']:
            box=word['bbox_mupdf']
            glyphs=[g for g in source if box[0]-0.0001<=g['origin'][0]<=box[2]+0.0001
                    and box[1]-0.0001<=g['origin'][1]<=box[3]+0.0001]
            if ''.join(g['text'] for g in glyphs)!=word['literal_text'].replace(' ',''):
                raise ValueError('caption word/glyph ownership mismatch')
            caption_glyphs.extend(glyphs)
    expected=[]
    for c in cells:
        for glyph in c['glyphs']:expected.append((c['id'],glyph))
    for glyph in caption_glyphs:expected.append(('caption',glyph))
    verified=[]
    for cell,glyph in expected:
        matches=[g for g in source if g['text']==glyph['text'] and _near_origin(g['origin'],glyph['origin'])]
        if len(matches)!=1:raise ValueError('reviewed source glyph not unique/exact')
        if any(_near_origin(glyph['origin'],v['origin']) and matches[0]['font']==v['font']
               and abs(matches[0]['size']-v['size'])<=0.0001 and glyph['text']==v['text']
               for _,v in verified):raise ValueError('duplicate/overlapping reviewed glyph ownership')
        verified.append((cell,matches[0]))
    if not verified:raise ValueError('reviewed grid has no native text glyph ownership')
    measurement=verified_source_text_shows(source_pdf,working_pdf,table['page']-1) if source_pdf is not None else None
    if measurement is None:measurement=text_show_ownership(working_pdf,table['page']-1)
    for g in measurement['unassigned_glyphs']:
        if any(_near_origin(g['origin'],v['origin']) for _,v in verified):
            raise ValueError('table glyph belongs to unassigned Form/colored-font painting')
    assignments={};covered=set();cell_shows=defaultdict(list)
    for show in measurement['shows']:
        memberships=[]
        for glyph in show['glyphs']:
            matches=[(i,cell,v) for i,(cell,v) in enumerate(verified)
                     if _near_origin(glyph['origin'],v['origin']) and glyph['font']==v['font']
                     and abs(glyph['size']-v['size'])<=0.0001]
            exact=[m for m in matches if m[2]['text']==glyph['text']]
            if exact:matches=exact
            if len(matches)>1:raise ValueError('working glyph ownership ambiguous')
            memberships.append(matches[0] if matches else None)
        bound=[m for m in memberships if m is not None]
        if not bound:continue
        owners={m[1] for m in bound}
        if len(owners)!=1 or len(bound)!=len(memberships):raise ValueError('text-show crosses reviewed cell/caption ownership')
        owner=next(iter(owners));index=show['instruction_index'];assignments[index]=owner
        covered.update(m[0] for m in bound);cell_shows[owner].append((min(m[0] for m in bound),index))
    if covered!=set(range(len(verified))):raise ValueError('reviewed table native glyph coverage incomplete')
    return {'assignments':assignments,'cell_show_order':{cell:[i for _,i in sorted(values)] for cell,values in cell_shows.items()},
            'source_glyph_count':len(verified),'caption_glyph_count':len(caption_glyphs),
            'text_show_count':len(assignments),'ownership_basis':measurement.get('ownership_basis','current-painted-glyph-origins')}


_PAINT={'Do','Tj','TJ',"'",'"','S','s','f','F','f*','B','B*','b','b*','sh','INLINE IMAGE'}


def _scopes(page):
    instructions=list(pikepdf.parse_content_stream(page));scopes=[];active=[]
    for index,(operands,operator) in enumerate(instructions):
        op=str(operator)
        if op in ('BMC','BDC'):
            props=operands[1] if op=='BDC' else None
            if isinstance(props,pikepdf.Name):props=page.get('/Resources',{}).get('/Properties',{}).get(str(props))
            scope={'start':index,'end':None,'operands':operands,'operator':operator,'tag':str(operands[0]),
                   'mcid':int(props.MCID) if isinstance(props,pikepdf.Dictionary) and '/MCID' in props else None,
                   'actual_text':isinstance(props,pikepdf.Dictionary) and '/ActualText' in props,'paint':set()}
            scopes.append(scope);active.append(scope)
        elif op=='EMC':
            if not active:raise ValueError('unbalanced table marked content')
            active.pop()['end']=index
        elif op in _PAINT:
            for scope in active:scope['paint'].add(index)
    if active:raise ValueError('unclosed table marked content')
    return instructions,scopes


def _page_owners(root,page):
    owners={};visited=set()
    def register(mcid,owner):
        if mcid in owners:raise ValueError('duplicate page MCID structure ownership')
        owners[mcid]=owner
    def walk(node,pg=None,owner=None):
        if isinstance(node,pikepdf.Array):
            for child in node:walk(child,pg,owner)
        elif isinstance(node,pikepdf.Dictionary):
            if node.objgen!=(0,0):
                if node.objgen in visited:raise ValueError('cyclic/repeated table structure')
                visited.add(node.objgen)
            pg=node.get('/Pg',pg)
            if '/S' in node:owner=node
            if '/MCID' in node and '/Stm' not in node and pg is not None and pg.objgen==page.obj.objgen:
                register(int(node.MCID),owner)
            elif '/K' in node:walk(node.K,pg,owner)
        elif isinstance(node,int) and pg is not None and pg.objgen==page.obj.objgen:register(int(node),owner)
    walk(root)
    return owners


def _number_tree(node):
    values={}
    if '/Nums' in node:
        nums=node.Nums
        if len(nums)%2:raise ValueError('invalid ParentTree number leaf')
        for i in range(0,len(nums),2):values[int(nums[i])]=nums[i+1]
    for child in node.get('/Kids',[]):
        part=_number_tree(child)
        if values.keys()&part.keys():raise ValueError('duplicate ParentTree keys')
        values.update(part)
    return values


def _name_tree(node):
    values={}
    if '/Names' in node:
        names=node.Names
        if len(names)%2:raise ValueError('invalid structure IDTree leaf')
        for i in range(0,len(names),2):values[str(names[i])]=names[i+1]
    for child in node.get('/Kids',[]):
        part=_name_tree(child)
        if values.keys()&part.keys():raise ValueError('duplicate structure IDs')
        values.update(part)
    return values


def _prune_removed(node,page_objgen,removed,pg=None):
    """Remove only obsolete references; keep other pages/Form namespaces."""
    if isinstance(node,int):return None if pg is not None and pg.objgen==page_objgen and int(node) in removed else node
    if isinstance(node,pikepdf.Array):
        return pikepdf.Array([value for child in node if (value:=_prune_removed(child,page_objgen,removed,pg)) is not None])
    if not isinstance(node,pikepdf.Dictionary):return node
    pg=node.get('/Pg',pg)
    if '/MCID' in node:
        return None if '/Stm' not in node and pg is not None and pg.objgen==page_objgen and int(node.MCID) in removed else node
    if '/K' not in node:return node
    old=node.K;updated=_prune_removed(old,page_objgen,removed,pg)
    if updated is None or isinstance(updated,pikepdf.Array) and not len(updated):
        if isinstance(old,pikepdf.Array) and not len(old):return node
        if str(node.get('/S')) in ('/Document','/Part','/Sect'):
            node.K=pikepdf.Array([]);return node
        return None if '/S' in node else node
    node.K=updated
    return node


def _insert_parent(root,owner):
    """Find the root-child slot that currently owns the table's first glyph."""
    target=owner;seen=set()
    while target is not None and '/P' in target and target.P.objgen!=root.objgen:
        if target.objgen in seen:raise ValueError('cyclic table parent')
        seen.add(target.objgen)
        parent=target.P
        if str(parent.get('/S')) in ('/Document','/Part','/Sect'):
            children=parent.get('/K',[]);children=list(children) if isinstance(children,pikepdf.Array) else [children]
            return parent,next(i for i,v in enumerate(children) if isinstance(v,pikepdf.Dictionary) and v.objgen==target.objgen)
        target=parent
    return root,0


def _reuse_existing_image_grid(pdf, page, table, binding, source_pdf):
    """Keep an already-correct image-cell graph; verify every cell before attributes."""
    root=pdf.Root.StructTreeRoot;owners=_page_owners(root,page)
    instructions,scopes=_scopes(page);nodes={};figures={}
    for cell in table['cells']:
        image=cell.get('embedded_image_binding')
        if image:
            if cell['glyphs']:raise ValueError('mixed image/text cell requires separate ownership proof')
            record=dict(subtype='/Image',payload=image['original_raw_stream_sha256'],
                        bbox=image['verified_page_bbox_pdf_exact_decimal'])
            source=[p for p in _placements(source_pdf.pages[table['page']-1]) if _same(record,p)]
            current=[p for p in _placements(page) if _same(record,p)]
            if len(source)!=1 or len(current)!=1 or current[0]['artifact']:
                raise ValueError('reviewed image cell source/current placement not unique')
            from .pdf_paint_ownership import _paint_value
            if _paint_value(source[0]['object'])!=_paint_value(current[0]['object']):
                raise ValueError('reviewed image cell painting resources changed')
            if len(current[0]['mcids'])!=1:raise ValueError('reviewed image cell MCID namespace ambiguous')
            mcid=current[0]['mcids'][0];figure=owners.get(mcid)
            if figure is None or str(figure.get('/S'))!='/Figure' or not _single_do_owner(figure,page,mcid):
                raise ValueError('reviewed image cell Figure owns additional painting')
            node=figure.get('/P');figures[cell['id']]=figure
            if not isinstance(node,pikepdf.Dictionary) or str(node.get('/S'))!='/TD':
                raise ValueError('reviewed image does not already belong to a table cell')
        else:
            indices=set(binding['cell_show_order'].get(cell['id'],[]))
            if not indices:raise ValueError('existing reviewed cell has no bound native glyphs')
            matched=[scope for scope in scopes if scope['paint']&indices]
            if any(scope['mcid'] is None or scope['paint']-indices for scope in matched):
                raise ValueError('existing reviewed cell scope owns additional painting')
            candidates={owners[scope['mcid']].objgen:owners[scope['mcid']] for scope in matched
                        if scope['mcid'] in owners}
            if len(candidates)!=1:raise ValueError('reviewed glyphs do not belong to one existing cell')
            node=next(iter(candidates.values()))
            if str(node.get('/S')) not in ('/TH','/TD'):raise ValueError('reviewed text owner is not an existing cell')
        if '/ID' in node or '/Ref' in node:raise ValueError('existing image grid has structural dependencies')
        nodes[cell['id']]=node
    if len({n.objgen for n in nodes.values()})!=len(nodes):raise ValueError('reviewed cells share existing ownership')
    for cell_id,node in nodes.items():
        kids=node.get('/K',[]);kids=list(kids) if isinstance(kids,pikepdf.Array) else [kids]
        for child in kids:
            if isinstance(child,pikepdf.Dictionary) and str(child.get('/S'))=='/Figure':
                if cell_id not in figures or child.objgen!=figures[cell_id].objgen:
                    raise ValueError('existing cell owns an unreviewed Figure')
            elif isinstance(child,pikepdf.Dictionary) and '/MCID' in child and '/Stm' not in child:
                pg=child.get('/Pg',node.get('/Pg'))
                owner=owners.get(int(child.MCID))
                if pg is None or pg.objgen!=page.obj.objgen or owner is None or owner.objgen!=node.objgen:
                    raise ValueError('existing cell has foreign or conflicting MCID ownership')
            elif isinstance(child,int) and node.get('/Pg') is not None and node.Pg.objgen==page.obj.objgen:
                owner=owners.get(child)
                if owner is None or owner.objgen!=node.objgen:raise ValueError('existing integer MCID ownership conflicts')
            else:raise ValueError('existing cell has unverified nested/foreign content')

    tables={}
    for node in nodes.values():
        row=node.get('/P');grid=row.get('/P') if isinstance(row,pikepdf.Dictionary) else None
        if not isinstance(grid,pikepdf.Dictionary) or str(row.get('/S'))!='/TR' or str(grid.get('/S'))!='/Table':
            raise ValueError('existing image grid cell ancestry invalid')
        tables[grid.objgen]=grid
    if len(tables)!=1:raise ValueError('reviewed cells cross existing tables')
    grid=next(iter(tables.values()));rows=list(grid.get('/K',[]))
    expected_rows=sorted({c['row'] for c in table['cells']})
    if expected_rows!=list(range(len(rows))):raise ValueError('existing image grid row count differs')
    for index,row in enumerate(rows):
        expected=[nodes[c['id']].objgen for c in sorted(table['cells'],key=lambda c:c['col']) if c['row']==index]
        if str(row.get('/S'))!='/TR' or [n.objgen for n in row.get('/K',[])]!=expected:
            raise ValueError('existing image grid logical cell order differs')
    ancestor=grid;seen=set()
    while isinstance(ancestor,pikepdf.Dictionary):
        if ancestor.objgen in seen:raise ValueError('cyclic existing image grid ancestry')
        seen.add(ancestor.objgen)
        if '/ID' in ancestor or '/Ref' in ancestor or str(ancestor.get('/S')) in ('/Link','/Formula','/Note','/Reference'):
            raise ValueError('existing image grid has protected structural dependencies')
        ancestor=ancestor.get('/P')
    parents=_number_tree(root.ParentTree).get(int(page.StructParents))
    if not isinstance(parents,pikepdf.Array):raise ValueError('image grid ParentTree unavailable')
    measurement=verified_source_text_shows(source_pdf,pdf,table['page']-1)
    shown={show['instruction_index']:show['glyphs'] for show in measurement['shows']}
    target=set(binding['assignments']);cell_ids={n.objgen for n in nodes.values()}
    for scope in scopes:
        owner=owners.get(scope['mcid'])
        if owner is None or owner.objgen not in cell_ids|{f.objgen for f in figures.values()}:continue
        if scope['mcid']<0 or scope['mcid']>=len(parents) or parents[scope['mcid']] is None or parents[scope['mcid']].objgen!=owner.objgen:
            raise ValueError('existing image grid ParentTree owner conflicts')
        if owner.objgen in cell_ids:
            for i in scope['paint']-target:
                if i not in shown or shown[i]:raise ValueError('existing cell owns unreviewed visible painting')
    ids=_name_tree(root.IDTree) if '/IDTree' in root else {};names={}
    for cell in table['cells']:
        name='review-'+table['sha'][:12]+'-'+cell['id']
        if name in ids:raise ValueError('reviewed image grid ID conflicts')
        names[cell['id']]=name
    # All ownership checks precede the first mutation. Keep K, streams and ParentTree exact.
    for cell in table['cells']:
        node=nodes[cell['id']];node.S=pikepdf.Name('/'+cell['role']);node.ID=pikepdf.String(names[cell['id']]);ids[names[cell['id']]]=node
        attributes=pikepdf.Dictionary(O=pikepdf.Name('/Table'),RowSpan=cell['rowspan'],ColSpan=cell['colspan'])
        if cell['scope']:attributes.Scope=pikepdf.Name('/'+cell['scope'].title())
        if cell['headers']:attributes.Headers=pikepdf.Array([pikepdf.String(names[h]) for h in cell['headers']])
        old=node.get('/A',[]);old=list(old) if isinstance(old,pikepdf.Array) else [old]
        node.A=pikepdf.Array([a for a in old if isinstance(a,pikepdf.Dictionary) and str(a.get('/O'))!='/Table']+[attributes])
    root.IDTree=pikepdf.Dictionary(Names=pikepdf.Array([v for name in sorted(ids) for v in (pikepdf.String(name),ids[name])]))
    return {'preserved_image_cells':len(figures),'preserved_existing_grid':True}


def _rewrite_table_page(pdf,page,bindings):
    if any(c.get('embedded_image_binding') for t,b in bindings for c in t['cells']):
        raise ValueError('image cell requires preserved existing-grid ownership')
    root=pdf.Root.StructTreeRoot;instructions,scopes=_scopes(page)
    selected={};labels={};all_cells={};caption_keys={}
    for table,binding in bindings:
        for c in table['cells']:
            if c['id'] in all_cells:raise ValueError('duplicate source-bound table cell ID')
            all_cells[c['id']]=c
        caption_key=table['id']+'-caption';caption_keys[table['id']]=caption_key
        for index,cell in binding['assignments'].items():
            if index in selected:raise ValueError('overlapping source-bound table paint operators')
            selected[index]=caption_key if cell=='caption' else cell
    target=set(selected);owners=_page_owners(root,page);removed=set();drop=set();insertions=[]
    for scope in scopes:
        covered=scope['paint']&target
        if not covered:continue
        if scope['actual_text']:raise ValueError('reviewed table intersects existing ActualText scope')
        if scope['mcid'] is not None:
            if scope['paint']-target:raise ValueError('existing MCID also owns non-table painting; safe scope split required')
            owner=owners.get(scope['mcid'])
            if owner is None:raise ValueError('existing table MCID owner missing')
            ancestor=owner;seen_ancestors=set()
            while isinstance(ancestor,pikepdf.Dictionary):
                if ancestor.objgen in seen_ancestors:raise ValueError('cyclic table owner ancestry')
                seen_ancestors.add(ancestor.objgen)
                if str(ancestor.get('/S')) in ('/Link','/Formula','/Note','/Reference'):
                    raise ValueError('table ownership intersects explicit inline semantics')
                if '/ID' in ancestor:
                    raise ValueError('table ownership intersects existing structural ID dependencies')
                ancestor=ancestor.get('/P')
            removed.add(scope['mcid'])
            drop.update((scope['start'],scope['end']))
        elif not scope['paint']-target:drop.update((scope['start'],scope['end']))
    # Place each rebuilt table at its earliest source-owned structural slot.
    for table,binding in bindings:
        involved=[s for s in scopes if s['mcid'] in removed and s['paint']&set(binding['assignments'])]
        candidates=[_insert_parent(root,owners[s['mcid']]) for s in involved]
        if not candidates:
            # Meaningful content previously Artifact needs a source-page slot.
            first=next((o for o in owners.values() if o is not None),None)
            if first is None:raise ValueError('source-page structure insertion slot unavailable')
            parent,index=_insert_parent(root,first)
        else:
            parent,index=min(candidates,key=lambda value:value[1])
            if any(p.objgen!=parent.objgen for p,_ in candidates):raise ValueError('table content crosses structural containers')
        children=parent.get('/K',[]);children=list(children) if isinstance(children,pikepdf.Array) else [children]
        prefixes={v.objgen for v in children[:index] if isinstance(v,pikepdf.Dictionary)}
        insertions.append((table,binding,parent,index,prefixes))
    parent_values=_number_tree(root.ParentTree);key=int(page.StructParents)
    parents=parent_values.get(key)
    if not isinstance(parents,pikepdf.Array):raise ValueError('page ParentTree array missing')
    parents=pikepdf.Array(list(parents));maximum=max([s['mcid'] for s in scopes if s['mcid'] is not None]+[-1])
    next_mcid=max(maximum+1,len(parents));new_mcids={index:next_mcid+i for i,index in enumerate(sorted(target))}
    while len(parents)<next_mcid+len(target):parents.append(None)
    for mcid in removed:
        if mcid>=len(parents):raise ValueError('old MCID outside ParentTree')
        parents[mcid]=None
    ids=_name_tree(root.IDTree) if '/IDTree' in root else {}
    for table,binding,parent,index,prefixes in insertions:
        table_node=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructElem'),S=pikepdf.Name('/Table'),P=parent,Pg=page.obj))
        children=[]
        caption_key=caption_keys[table['id']]
        if 'caption' in binding['cell_show_order']:
            caption=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructElem'),S=pikepdf.Name('/Caption'),P=table_node,Pg=page.obj))
            captions=[new_mcids[i] for i in binding['cell_show_order']['caption']]
            caption.K=pikepdf.Array([pikepdf.Dictionary(Type=pikepdf.Name('/MCR'),Pg=page.obj,MCID=m) for m in captions])
            for m in captions:parents[m]=caption
            children.append(caption)
        rows={};cell_nodes={};id_names={}
        for cell in sorted(table['cells'],key=lambda c:(c['row'],c['col'])):
            row=rows.get(cell['row'])
            if row is None:
                row=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructElem'),S=pikepdf.Name('/TR'),P=table_node,Pg=page.obj,K=pikepdf.Array([])))
                rows[cell['row']]=row
            attributes=pikepdf.Dictionary(O=pikepdf.Name('/Table'),RowSpan=cell['rowspan'],ColSpan=cell['colspan'])
            if cell['scope'] is not None:attributes.Scope=pikepdf.Name('/'+cell['scope'].title())
            node=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructElem'),S=pikepdf.Name('/'+cell['role']),P=row,Pg=page.obj,A=attributes))
            name='review-'+table['sha'][:12]+'-'+cell['id']
            if name in ids:raise ValueError('reviewed table ID conflicts with existing structure')
            node.ID=pikepdf.String(name);ids[name]=node;id_names[cell['id']]=name;cell_nodes[cell['id']]=node
            mcids=[new_mcids[i] for i in binding['cell_show_order'].get(cell['id'],[])]
            node.K=pikepdf.Array([pikepdf.Dictionary(Type=pikepdf.Name('/MCR'),Pg=page.obj,MCID=m) for m in mcids])
            for m in mcids:parents[m]=node
            row.K.append(node)
        for cell in table['cells']:
            if cell['headers']:cell_nodes[cell['id']].A.Headers=pikepdf.Array([pikepdf.String(id_names[h]) for h in cell['headers']])
        children.extend(rows[r] for r in sorted(rows));table_node.K=pikepdf.Array(children)
        labels[table['id']]=table_node
    # Prune only old page MCR references, never Form MCRs or other pages.
    _prune_removed(root,page.obj.objgen,removed)
    # Several reviewed grids can consume the same original structural slot.
    # Insert later source-owned captions/shows first so earlier grids retain
    # their order at that slot. This orders only these verified replacements;
    # unrelated siblings and distinct parent containers retain their slots.
    def insertion_order(value):
        table,binding,parent,index,prefixes=value
        caption=binding['cell_show_order'].get('caption',[])
        return index,min(caption or binding['assignments'])
    for table,binding,parent,index,prefixes in sorted(insertions,key=insertion_order,reverse=True):
        kids=parent.get('/K',[]);kids=list(kids) if isinstance(kids,pikepdf.Array) else [kids]
        position=sum(isinstance(v,pikepdf.Dictionary) and v.objgen in prefixes for v in kids)
        kids.insert(position,labels[table['id']]);parent.K=pikepdf.Array(kids)
    parent_values[key]=parents;root.ParentTree=pikepdf.Dictionary(Nums=pikepdf.Array([v for k in sorted(parent_values) for v in (k,parent_values[k])]))
    root.IDTree=pikepdf.Dictionary(Names=pikepdf.Array([v for name in sorted(ids) for v in (pikepdf.String(name),ids[name])]))
    active=[];rewritten=[];starts={s['start']:s for s in scopes}
    for index,instruction in enumerate(instructions):
        op=str(instruction[1])
        if op in ('BMC','BDC'):
            scope=starts[index];active.append(scope)
            if index not in drop:rewritten.append(instruction)
        elif op=='EMC':
            active.pop()
            if index not in drop:rewritten.append(instruction)
        elif index in target:
            keep=[s for s in active if s['start'] not in drop]
            for scope in reversed(keep):rewritten.append((pikepdf.Array([]),pikepdf.Operator('EMC')))
            rewritten.extend([(pikepdf.Array([pikepdf.Name('/Span'),pikepdf.Dictionary(MCID=new_mcids[index])]),pikepdf.Operator('BDC')),
                              instruction,(pikepdf.Array([]),pikepdf.Operator('EMC'))])
            for scope in keep:rewritten.append((scope['operands'],scope['operator']))
        else:rewritten.append(instruction)
    page.Contents=pdf.make_stream(pikepdf.unparse_content_stream(rewritten))
    return {'new_mcids':len(target),'removed_mcids':len(removed),'table_cells':len(all_cells)}


def apply_reviewed_table_grids(working,original,sidecars):
    original_sha=_sha(original);tables=[]
    for path in sidecars:tables.extend(_review_tables(path))
    selected=[t for t in tables if t['sha']==original_sha]
    result={'applied_tables':0,'applied_cells':0,'unmatched_tables':0,'records':[],
            'original_sha256':original_sha,'evidence_source':'model-reviewed-source-bound',
            'external_provider_invoked':False,
            'sidecars':[{'path':str(path),'sha256':_sha(path)} for path in sidecars]}
    if not selected:return result
    handle=tempfile.NamedTemporaryFile(prefix='.reviewed-tables-',suffix='.pdf',dir=Path(working).parent,delete=False)
    candidate=Path(handle.name);handle.close();affected=set()
    with fitz.open(original) as source,pikepdf.open(original) as source_pdf,pikepdf.open(working) as pdf:
        groups=defaultdict(list)
        for table in selected:
            item={'id':table['id'],'page':table['page']};result['records'].append(item)
            try:
                binding=bind_table_text_shows(table,source[table['page']-1],pdf,source_pdf)
                if any(c.get('embedded_image_binding') for c in table['cells']):
                    details=_reuse_existing_image_grid(pdf,pdf.pages[table['page']-1],table,binding,source_pdf)
                    item.update(status='applied',ownership_basis=binding['ownership_basis'],**details)
                    result['applied_tables']+=1;result['applied_cells']+=len(table['cells']);affected.add(table['page']-1)
                else:groups[table['page']-1].append((table,binding,item))
            except (ValueError,KeyError,IndexError) as error:
                item.update(status='unmatched',reason=str(error));result['unmatched_tables']+=1
        for index,entries in groups.items():
            try:
                details=_rewrite_table_page(pdf,pdf.pages[index],[(t,b) for t,b,i in entries])
            except ValueError as error:
                # Rewriting is deliberately atomic at the document level.
                raise ValueError(f'reviewed table page {index+1} rejected: {error}') from error
            for table,binding,item in entries:
                item.update(status='applied',source_glyph_count=binding['source_glyph_count'],text_show_count=binding['text_show_count'],ownership_basis=binding['ownership_basis'])
                result['applied_tables']+=1;result['applied_cells']+=len(table['cells'])
            affected.add(index)
        if not affected:return result
        pdf.save(candidate,compress_streams=False,stream_decode_level=pikepdf.StreamDecodeLevel.none)
    with fitz.open(working) as before,fitz.open(candidate) as after:
        for index in affected:
            a,b=before[index],after[index]
            if a.get_text()!=b.get_text() or a.get_pixmap(dpi=96,alpha=False).samples!=b.get_pixmap(dpi=96,alpha=False).samples:
                raise ValueError(f'reviewed table changed page text/pixels; candidate retained {candidate}')
    os.replace(candidate,working)
    return result
