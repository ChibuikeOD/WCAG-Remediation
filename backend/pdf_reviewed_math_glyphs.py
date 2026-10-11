"""Opt-in complete-symbol review bound to actual embedded font painting."""
import hashlib
import json
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pikepdf
from fontTools import t1Lib
from fontTools.cffLib import CFFFontSet
from fontTools.ttLib import TTFont

from .pdf_paint_ownership import _paint_value
from .pdf_reviewed_glyphs import ReviewedGlyphMappings, _fonts, _sha_file


def _canonical(value, active=None):
    active=set() if active is None else active
    if isinstance(value,(pikepdf.Dictionary,pikepdf.Stream,pikepdf.Array)):
        if value.objgen!=(0,0):
            if value.objgen in active:raise ValueError('cyclic reviewed font dictionary')
            active=active|{value.objgen}
        if isinstance(value,pikepdf.Array):return [_canonical(v,active) for v in value]
        ignored={'/Length','/Filter','/DecodeParms'} if isinstance(value,pikepdf.Stream) else set()
        fields={str(k):_canonical(value[k],active) for k in sorted(value.keys()) if str(k) not in ignored}
        if isinstance(value,pikepdf.Stream):
            payload=value.read_bytes()
            return dict(decoded_stream_sha256=hashlib.sha256(payload).hexdigest(),decoded_stream_bytes=len(payload),stream_dictionary=fields)
        return fields
    if isinstance(value,pikepdf.String):return {'pdf_string_bytes_hex':bytes(value).hex()}
    if isinstance(value,pikepdf.Name):return str(value)
    if isinstance(value,bool) or value is None:return value
    if isinstance(value,(int,float,Decimal)):
        number=float(value);return int(number) if number.is_integer() else number
    raise ValueError('unsupported reviewed font value')


def _fingerprint(font):
    return hashlib.sha256(json.dumps(_canonical(font),sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('ascii')).hexdigest()


def _program(font):
    descriptor=font.get('/FontDescriptor',{})
    if '/FontFile' in descriptor:return descriptor.FontFile.read_bytes(),'Type1'
    stream=descriptor.get('/FontFile3')
    if isinstance(stream,pikepdf.Stream) and str(stream.get('/Subtype'))=='/Type1C':return stream.read_bytes(),'Type1C'
    raise ValueError('reviewed complete symbols require embedded Type1/Type1C program')


def _parse_program(payload,kind):
    if kind=='Type1':
        font=object.__new__(t1Lib.T1Font);font.data=payload;font.encoding='ascii';font.parse()
        return font.font['Encoding'],font.font['CharStrings']
    cff=CFFFontSet();cff.decompile(BytesIO(payload),TTFont())
    if len(cff.fontNames)!=1:raise ValueError('ambiguous CFF font program')
    top=cff[cff.fontNames[0]]
    return top.Encoding,top.CharStrings


def _glyph_name(font,code,builtin):
    encoding=font.get('/Encoding')
    if encoding is None:
        return builtin[code] if isinstance(builtin,list) else None
    if isinstance(encoding,pikepdf.Name):base=str(encoding)
    elif isinstance(encoding,pikepdf.Dictionary):base=str(encoding.get('/BaseEncoding',''))
    else:raise ValueError('unsupported math font Encoding')
    if base:
        from reportlab.pdfbase import _fontdata
        vector=_fontdata.encodings.get(base.lstrip('/'))
        if vector is None:raise ValueError('unsupported named math Encoding')
    else:vector=builtin
    name=vector[code] if isinstance(vector,(list,tuple)) else None
    if isinstance(encoding,pikepdf.Dictionary):
        index=None
        for entry in encoding.get('/Differences',[]):
            if isinstance(entry,int):index=entry
            elif isinstance(entry,pikepdf.Name) and index is not None:
                if index==code:name=str(entry).lstrip('/')
                index+=1
            else:raise ValueError('invalid reviewed Encoding Differences')
    return name


def _verify_placement(pdf,binding):
    placement=binding['original_first_recorded_placement'];page=pdf.pages[placement['physical_page']-1]
    container=page;resources=page.Resources
    for step in binding['resource_invocation_path']:
        ops=list(pikepdf.parse_content_stream(container));args,op=ops[step['invoking_operator_index']]
        if str(op)!='Do' or str(args[0])!=step['xobject_resource']:raise ValueError('math source Form invocation mismatch')
        container=resources.XObject[step['xobject_resource']]
        if list(container.objgen)!=step['xobject_objgen']:raise ValueError('math source Form identity mismatch')
        resources=container.Resources
    ops=list(pikepdf.parse_content_stream(container));selected=placement['operator_index']
    font_name=None;stack=[]
    for args,op in ops[:selected]:
        if str(op)=='q':stack.append(font_name)
        elif str(op)=='Q':
            if not stack:raise ValueError('unbalanced math source graphics state')
            font_name=stack.pop()
        elif str(op)=='Tf':font_name=str(args[0])
    if font_name!=binding['font_resource'] or list(resources.Font[font_name].objgen)!=binding['font_objgen']:
        raise ValueError('reviewed math code is not used by selected source font')
    from .pdf_unicode_mapping import _string_bytes
    args,op=ops[selected];strings=list(_string_bytes(args,str(op)))
    if str(op)!=placement['operator'] or [s.hex() for s in strings]!=placement['raw_show_strings_hex']:
        raise ValueError('reviewed math source show bytes mismatch')
    if strings[placement['string_index']][placement['byte_offset_in_string']]!=binding['character_code']:
        raise ValueError('reviewed math source code mismatch')


def load_reviewed_math_glyphs(sidecar,original,working):
    data=json.loads(Path(sidecar).read_text(encoding='utf-8-sig'))
    if data.get('schema_version')!='pdfaccess.math-glyph-proposals.v1' or data.get('review_status')!='REVIEWED_SOURCE_SPECIFIC_COMPLETE_SYMBOL_PROPOSALS_ONLY':
        raise ValueError('unsupported/unreviewed complete-symbol sidecar')
    sha=_sha_file(Path(original));sources={s['source_id']:s for s in data['sources'] if s['input_sha256']==sha}
    if not sources:raise ValueError('math review does not match original SHA256')
    result=ReviewedGlyphMappings();program_cache={};font_cache={}
    with pikepdf.open(original) as source_pdf,pikepdf.open(working) as target:
        for proposal in data['proposals']:
            if proposal.get('review_status')!='REVIEWED' or proposal.get('mapping_kind')!='complete-symbol' or proposal.get('isolated_glyph_mapping_allowed') is not True:
                raise ValueError('held combining/extension mapping cannot be activated')
            text=proposal['literal_unicode']
            if not isinstance(text,str) or not text or any(ord(c)<32 or c=='\ufffd' or 0xD800<=ord(c)<=0xDFFF for c in text):raise ValueError('invalid complete-symbol Unicode')
            for binding in proposal['bindings']:
                source=sources.get(binding['source_id'])
                if source is None:continue
                code=binding['character_code']
                if isinstance(code,bool) or not isinstance(code,int) or not 0<=code<=255:raise ValueError('invalid reviewed math character code')
                if binding['input_sha256']!=sha or binding['font_objgen']!=source['font_objgen']:raise ValueError('inconsistent source math binding')
                font=source_pdf.get_object(tuple(binding['font_objgen']))
                if str(font.get('/Subtype'))!='/Type1':raise ValueError('unsupported complete-symbol simple-font subtype')
                fingerprint=_fingerprint(font)
                if fingerprint!=source['canonical_full_font_content_fingerprint_sha256'] or fingerprint!=binding['canonical_full_font_content_fingerprint_sha256']:
                    raise ValueError('reviewed source full-font fingerprint mismatch')
                payload,kind=_program(font);program_sha=hashlib.sha256(payload).hexdigest()
                if program_sha!=source['font_program_decoded_sha256'] or program_sha!=binding['font_program_decoded_sha256']:raise ValueError('math font program mismatch')
                if program_sha not in program_cache:program_cache[program_sha]=_parse_program(payload,kind)
                builtin,charstrings=program_cache[program_sha];name=_glyph_name(font,code,builtin)
                expected_encoding=binding.get('embedded_encoding_vector_sha256')
                if expected_encoding is not None:
                    if not isinstance(builtin,list) or len(builtin)!=256:raise ValueError('unsupported embedded Encoding vector')
                    material={str(i):str(glyph_name) for i,glyph_name in enumerate(builtin)}
                    encoding_sha=hashlib.sha256(json.dumps(material,separators=(',',':'),ensure_ascii=True).encode('ascii')).hexdigest()
                    if encoding_sha!=expected_encoding:raise ValueError('embedded math Encoding vector mismatch')
                if name!=binding['effective_glyph_name'] or name!=proposal['effective_glyph_name']:raise ValueError('math code/Encoding/glyph mismatch')
                glyph=charstrings[name]
                if glyph.bytecode is None:raise ValueError('reviewed glyph lacks original CharString bytes')
                if hashlib.sha256(glyph.bytecode).hexdigest()!=binding['glyph_charstring_sha256']:raise ValueError('math glyph CharString mismatch')
                _verify_placement(source_pdf,binding)
                resource=binding['font_resource']
                if resource not in font_cache:font_cache[resource]=list(_fonts(target,resource))
                result.binding_counts['considered']+=1;matched=False
                for current in font_cache[resource]:
                    if _paint_value(font)!=_paint_value(current):continue
                    key=(current.objgen,code);cmap=current.get('/ToUnicode')
                    if isinstance(cmap,pikepdf.Stream):
                        from .pdf_unicode_mapping import parse_to_unicode_cmap
                        existing=parse_to_unicode_cmap(cmap.read_bytes()).mappings.get(code)
                        if existing is not None and existing!=text:raise ValueError('math review conflicts with existing Unicode')
                    if key in result and result[key]['text']!=text:raise ValueError('conflicting reviewed complete symbols')
                    result[key]={'text':text,'resolution_source':'model-reviewed-sidecar','proposal_id':proposal['proposal_id'],
                                 'source_sha256':sha,'font_program_sha256':program_sha,'glyph_charstring_sha256':binding['glyph_charstring_sha256'],
                                 'font_metadata_authority':False,'mapping_kind':'complete-symbol'}
                    matched=True
                result.binding_counts['matched' if matched else 'unmatched']+=1
    return result
