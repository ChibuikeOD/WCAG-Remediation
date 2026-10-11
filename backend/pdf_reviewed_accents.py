"""Exact encoded text partitioning for source-reviewed whole accent groups.

This module does not infer accents from glyph names or geometry. Numeric TJ
advances and string bytes are preserved when splitting explicitly bound codes.
"""
import pikepdf
import hashlib
import json
import os
import tempfile
from pathlib import Path
from collections import defaultdict

from .pdf_paint_ownership import _paint_value,verified_source_text_shows
from .pdf_reviewed_tables import _scopes,_page_owners,_number_tree
from .pdf_visual_fidelity import isolated_fingerprint


def partition_reviewed_show(operands,operator,members,code_width=2):
    """Return (review group or None, Tj/TJ instruction) with identical advances.

    members maps (string-array index, byte offset) to a group identifier. Tj
    uses string index zero. A selected code must fit its original encoded string;
    the caller must independently prove the effective font/encoding and tokens.
    Numeric TJ displacements remain in their original sequence, including those
    between two pieces assigned to the same semantic group.
    """
    op=str(operator)
    if op not in ('Tj','TJ'):raise ValueError('accent partition requires explicit Tj/TJ')
    if type(code_width) is not int or code_width not in (1,2):raise ValueError('unsupported exact code width')
    values=list(operands[0]) if op=='TJ' else [operands[0]]
    if op=='Tj' and len(operands)!=1:raise ValueError('invalid Tj operands')
    consumed=set();pieces=[]
    for part,value in enumerate(values):
        if not isinstance(value,pikepdf.String):
            if op!='TJ' or not isinstance(value,(int,float)):
                from decimal import Decimal
                if op!='TJ' or not isinstance(value,Decimal):raise ValueError('invalid TJ displacement')
            pieces.append((None,(pikepdf.Array([pikepdf.Array([value])]),pikepdf.Operator('TJ'))));continue
        raw=bytes(value)
        if len(raw)%code_width:raise ValueError('encoded accent string has incomplete code')
        start=0;current=None
        for offset in range(0,len(raw),code_width):
            group=members.get((part,offset))
            if (part,offset) in members:
                if not isinstance(group,str) or not group:raise ValueError('invalid reviewed accent group')
                consumed.add((part,offset))
            if offset and group!=current:
                pieces.append((current,(pikepdf.Array([pikepdf.String(raw[start:offset])]),pikepdf.Operator('Tj'))));start=offset
            current=group
        if raw:pieces.append((current,(pikepdf.Array([pikepdf.String(raw[start:])]),pikepdf.Operator('Tj'))))
    if consumed!=set(members):raise ValueError('reviewed accent token lies outside encoded show')
    return pieces


def _replace_refs(value,page,substitutions,pg=None):
    if isinstance(value,int):return substitutions.get(value,[value]) if pg is not None and pg.objgen==page.objgen else [value]
    if isinstance(value,pikepdf.Array):
        return [v for child in value for v in _replace_refs(child,page,substitutions,pg)]
    if isinstance(value,pikepdf.Dictionary):
        pg=value.get('/Pg',pg)
        if '/MCID' in value and '/Stm' not in value and pg is not None and pg.objgen==page.objgen:
            return substitutions.get(int(value.MCID),[value])
    return [value]


def _source_code_uses(source,codes):
    uses=set();fonts={};programs={};expected={s['font_program_decoded_sha256'] for s in codes.values()}
    def visit(container,resources,font,page_index,path,active):
        if container.objgen in active:raise ValueError('cyclic source accent Form graph')
        stack=[]
        for index,(args,operator) in enumerate(pikepdf.parse_content_stream(container)):
            op=str(operator)
            if op=='q':stack.append(font)
            elif op=='Q':
                if not stack:raise ValueError('unbalanced source font state')
                font=stack.pop()
            elif op=='Tf':font=resources.Font[args[0]]
            elif op=='Do':
                child=resources.XObject[args[0]]
                if str(child.get('/Subtype'))=='/Form':visit(child,child.get('/Resources',resources),font,page_index,path+[str(args[0])],active|{container.objgen})
            elif op in ('Tj','TJ',"'",'"'):
                if not path:fonts[(page_index,index)]=font.objgen if font is not None else None
                if font is None or str(font.get('/Subtype'))!='/Type0':continue
                if font.objgen not in programs:
                    stream=font.DescendantFonts[0].get('/FontDescriptor',{}).get('/FontFile2')
                    programs[font.objgen]=hashlib.sha256(stream.read_bytes()).hexdigest() if isinstance(stream,pikepdf.Stream) else None
                if programs[font.objgen] not in expected:continue
                values=list(args[0]) if op=='TJ' else [args[-1]]
                for part,value in enumerate(values):
                    if not isinstance(value,pikepdf.String):continue
                    raw=bytes(value)
                    if len(raw)%2:raise ValueError('incomplete source Identity-H code')
                    for offset in range(0,len(raw),2):
                        if int.from_bytes(raw[offset:offset+2],'big') in codes:
                            if path or op not in ('Tj','TJ'):raise ValueError('accent code has unreviewed Form/quote occurrence')
                            uses.add((page_index,index,part,offset))
        if stack:raise ValueError('unclosed source font state')
    for page_index,page in enumerate(source.pages):visit(page.obj,page.Resources,None,page_index,[],set())
    return uses,fonts


def apply_reviewed_accent_groups(working,original,sidecar):
    """Apply reviewed U+0305 codes only with their complete inline Formula groups.

    Whole group ActualText belongs to one Formula; individual extender MCRs
    never receive empty or repeated replacement text. Unselected glyphs keep
    their original owner and position. This is an opt-in source-bound operation.
    """
    sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
    data=json.loads(Path(sidecar).read_text(encoding='utf-8-sig'));source_sha=sha(original)
    if data.get('schema_version')!='pdfaccess.reviewed-type0-MATH-glyph-and-accent-proposals.v1' or data.get('review_status')!='REVIEWED':
        raise ValueError('unsupported or unreviewed complete accent input')
    groups=data['accent_group_proposals'];proposals=data['font_code_proposals']
    if not groups or len({g['proposal_id'] for g in groups})!=len(groups):raise ValueError('missing/duplicate complete accent groups')
    pages=defaultdict(list);codes={};tokens={};expected_bar_tokens=set()
    for proposal in proposals:
        selector=proposal['stable_original_font_code_selector']
        if proposal.get('review_status')!='REVIEWED' or proposal.get('literal_unicode')!='\u0305' or selector['input_sha256']!=source_sha:
            raise ValueError('unmatched accent mapping source or literal')
        code=int(selector['CID'])
        if selector['code_length_bytes']!=2 or selector['code_hex'].lower()!=code.to_bytes(2,'big').hex() or code in codes:
            raise ValueError('invalid/duplicate accent code')
        codes[code]=selector
    if not codes:raise ValueError('complete accent input has no reviewed combining codes')
    for group in groups:
        if group.get('review_status')!='REVIEWED' or group['original_sha256']!=source_sha or not group['requires_engine_grouping']:
            raise ValueError('unmatched complete accent source')
        text=group['proposed_ActualText']
        if not isinstance(text,str) or not text.strip() or any(ord(c)<32 or c=='\ufffd' for c in text):raise ValueError('invalid whole accent ActualText')
        members=group['base_tokens_in_intended_literal_reading_order']+group['bar_source_token_selectors']
        if not group['base_tokens_in_intended_literal_reading_order'] or not group['bar_source_token_selectors']:
            raise ValueError('complete accent requires both its base and bar assembly')
        if len(group['bar_source_token_selectors'])!=group['bar_glyph_member_count']:raise ValueError('incomplete bar assembly')
        for rank,token in enumerate(members):
            page=int(token.get('page',token.get('physical_page')))-1
            if page!=int(group['physical_page'])-1:raise ValueError('accent group crosses pages')
            key=(page,int(token['source_instruction']),int(token['TJ_string_part_index']),int(token['code_byte_offset']))
            if key in tokens:raise ValueError('duplicate accent token ownership')
            tokens[key]=(group['proposal_id'],token,rank)
            if rank>=len(group['base_tokens_in_intended_literal_reading_order']):expected_bar_tokens.add(key)
        pages[int(group['physical_page'])-1].append(group)
    fd,name=tempfile.mkstemp(prefix='.reviewed-accents-',suffix='.pdf',dir=Path(working).parent);os.close(fd);candidate=Path(name)
    formula_evidence=[];mapped_fonts={};actual_bar_tokens=set()
    with pikepdf.open(original) as source,pikepdf.open(working) as pdf:
        # Recount every source code use so no extender receives a global mapping
        # without a reviewed whole-group occurrence. Nested Form occurrences hold.
        actual_bar_tokens,effective_fonts=_source_code_uses(source,codes)
        if actual_bar_tokens!=expected_bar_tokens:raise ValueError('complete accent review does not cover every mapped code use')
        root=pdf.Root.StructTreeRoot;parent_values=_number_tree(root.ParentTree)
        for page_index,page_groups in pages.items():
            if verified_source_text_shows(source,pdf,page_index) is None:raise ValueError('accent source/current encoded painting differs')
            page=pdf.pages[page_index];instructions,scopes=_scopes(page);owners=_page_owners(root,page)
            a=[(i,args,op) for i,(args,op) in enumerate(pikepdf.parse_content_stream(source.pages[page_index])) if str(op) not in ('BDC','BMC','EMC')]
            b=[(i,args,op) for i,(args,op) in enumerate(instructions) if str(op) not in ('BDC','BMC','EMC')]
            index_map={left[0]:right[0] for left,right in zip(a,b)};selected=defaultdict(dict);ranks={}
            for (p,index,part,offset),(identifier,token,rank) in tokens.items():
                if p!=page_index:continue
                current=index_map[index];args,op=instructions[current];values=list(args[0]) if str(op)=='TJ' else [args[0]]
                if str(op) not in ('Tj','TJ') or bytes(values[part])[offset:offset+2].hex()!=token['code_hex'].lower():raise ValueError('exact accent source token differs')
                source_font=source.pages[p].Resources.Font[token['font_resource']];font=page.Resources.Font[token['font_resource']]
                if effective_fonts.get((p,index))!=source_font.objgen:raise ValueError('reviewed accent token does not use its declared source font')
                program=source_font.DescendantFonts[0].FontDescriptor.FontFile2
                if hashlib.sha256(program.read_bytes()).hexdigest()!=token.get('font_program_sha256',token.get('font_program_decoded_sha256')) or _paint_value(source_font)!=_paint_value(font):raise ValueError('accent font identity differs')
                if str(font.Encoding)!='/Identity-H' or str(font.DescendantFonts[0].CIDToGIDMap)!='/Identity':raise ValueError('accent encoding identity differs')
                selected[current][(part,offset)]=identifier;ranks[(current,part,offset)]=(identifier,rank)
                mapped_fonts[font.objgen]=font
            touched=[s for s in scopes if s['paint']&set(selected)]
            affected_mcids=set();drop=set();paint_scope={}
            for scope in touched:
                if scope['actual_text'] or scope['mcid'] is None:raise ValueError('accent intersects unverified ActualText/Artifact scope')
                if any(str(instructions[i][1]) not in ('Tj','TJ') for i in scope['paint']):raise ValueError('accent owner also owns non-text painting')
                mcid=scope['mcid'];owner=owners.get(mcid)
                if owner is None:raise ValueError('accent owner missing')
                ancestor=owner;seen=set()
                while isinstance(ancestor,pikepdf.Dictionary):
                    if ancestor.objgen in seen:raise ValueError('cyclic accent owner ancestry')
                    seen.add(ancestor.objgen)
                    if '/ID' in ancestor or '/ActualText' in ancestor or str(ancestor.get('/S')) in ('/Formula','/Link','/Note','/Reference'):raise ValueError('accent intersects explicit semantic/ID dependency')
                    ancestor=ancestor.get('/P')
                affected_mcids.add(mcid);drop.update((scope['start'],scope['end']))
                for index in scope['paint']:
                    if index in paint_scope:raise ValueError('nested accent marked-content ownership')
                    paint_scope[index]=mcid
            if not set(selected)<=paint_scope.keys():raise ValueError('accent member lacks explicit page ownership')
            key=int(page.StructParents);parents=parent_values[key]
            if not isinstance(parents,pikepdf.Array):raise ValueError('accent page ParentTree missing')
            parents=pikepdf.Array(list(parents));next_mcid=max(len(parents),max(owners,default=-1)+1)
            for mcid in affected_mcids:
                if mcid>=len(parents) or parents[mcid] is None or parents[mcid].objgen!=owners[mcid].objgen:raise ValueError('accent ParentTree ownership differs')
                parents[mcid]=None
            formulas={};anchor_owners={};formula_members=defaultdict(list)
            for group in page_groups:
                token=group['base_tokens_in_intended_literal_reading_order'][0];anchor=index_map[token['source_instruction']]
                owner=owners[paint_scope[anchor]]
                if str(owner.get('/S')) not in ('/P','/Span'):raise ValueError('accent inline parent is not a paragraph/span')
                node=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructElem'),S=pikepdf.Name('/Formula'),P=owner,Pg=page.obj,ActualText=pikepdf.String(group['proposed_ActualText'])))
                formulas[group['proposal_id']]=node;anchor_owners[group['proposal_id']]=owner
            substitutions=defaultdict(list);inserted=set();rewritten=[]
            for index,instruction in enumerate(instructions):
                if index in drop:continue
                if index not in paint_scope:rewritten.append(instruction);continue
                old_mcid=paint_scope[index];old_owner=owners[old_mcid];members=selected.get(index,{})
                for identifier,piece in partition_reviewed_show(*instruction,members):
                    args,op=piece
                    # Numeric-only TJ is still a text-show content item. Keep
                    # its original paragraph ownership and marked scope rather
                    # than emitting an untagged displacement after splitting.
                    mcid=next_mcid;next_mcid+=1
                    while len(parents)<=mcid:parents.append(None)
                    ref=pikepdf.Dictionary(Type=pikepdf.Name('/MCR'),Pg=page.obj,MCID=mcid)
                    if identifier is None:
                        parents[mcid]=old_owner;substitutions[old_mcid].append(ref)
                    else:
                        node=formulas[identifier];parents[mcid]=node
                        member_ranks=[rank for (i,part,offset),(g,rank) in ranks.items() if i==index and g==identifier]
                        formula_members[identifier].append((min(member_ranks),ref))
                        if old_owner.objgen==anchor_owners[identifier].objgen and identifier not in inserted:
                            substitutions[old_mcid].append(node);inserted.add(identifier)
                    rewritten.extend([(pikepdf.Array([pikepdf.Name('/Span'),pikepdf.Dictionary(MCID=mcid)]),pikepdf.Operator('BDC')),piece,(pikepdf.Array([]),pikepdf.Operator('EMC'))])
            if inserted!=set(formulas):raise ValueError('complete accent inline insertion unavailable')
            for identifier,node in formulas.items():
                node.K=pikepdf.Array([ref for rank,ref in sorted(formula_members[identifier],key=lambda v:v[0])])
                formula_evidence.append(dict(proposal_id=identifier,page=page_index+1,ActualText=str(node.ActualText),parent=list(node.P.objgen),member_mcids=[int(ref.MCID) for ref in node.K]))
            for mcid in affected_mcids:substitutions.setdefault(mcid,[])
            for owner in {o.objgen:o for m,o in owners.items() if m in affected_mcids}.values():
                owner.K=pikepdf.Array(_replace_refs(owner.K,page.obj,substitutions,owner.get('/Pg',page.obj)))
            page.Contents=pdf.make_stream(pikepdf.unparse_content_stream(rewritten));parent_values[key]=parents
        from .pdf_unicode_mapping import add_cmap_mappings,parse_to_unicode_cmap
        for font in mapped_fonts.values():
            cmap=font.get('/ToUnicode')
            if not isinstance(cmap,pikepdf.Stream):raise ValueError('accent source existing CMap unavailable')
            parsed=parse_to_unicode_cmap(cmap.read_bytes())
            if any(code in parsed.mappings and parsed.mappings[code]!='\u0305' for code in codes):raise ValueError('accent Unicode conflicts with existing mapping')
            font.ToUnicode=pdf.make_stream(add_cmap_mappings(cmap.read_bytes(),{code:'\u0305' for code in codes}))
        root.ParentTree=pikepdf.Dictionary(Nums=pikepdf.Array([v for k in sorted(parent_values) for v in (k,parent_values[k])]))
        for index in pages:_page_owners(root,pdf.pages[index])
        pdf.save(candidate,compress_streams=False,stream_decode_level=pikepdf.StreamDecodeLevel.none)
    before=isolated_fingerprint(working,pages);after=isolated_fingerprint(candidate,pages)
    if before['page_count']!=after['page_count'] or any(a['rgb_sha256']!=b['rgb_sha256'] or any(a[k]!=b[k] for k in ('width','height','channels')) for a,b in zip(before['pages'],after['pages'])):
        raise ValueError(f'accent edit changed pixels; retained {candidate}')
    if sha(original)!=source_sha:raise ValueError('accent original changed during verification')
    os.replace(candidate,working)
    return dict(applied_groups=len(formula_evidence),mapped_codes=len(codes),mapped_occurrences=len(actual_bar_tokens),groups=formula_evidence,
                original_sha256=source_sha,sidecar_sha256=sha(sidecar),external_provider_invoked=False,evidence_source='model-reviewed-source-bound-whole-accent',
                fidelity=dict(verification='separate-process-rgb',dpi=96,pages=sorted(pages),before_sha256=before['input_sha256'],after_sha256=after['input_sha256']),
                extraction_changes='reviewed U+0305 mapping; single whole-group replacement resides on each Formula, never individual extender')
