"""Measure top-level text-show glyph ownership using an in-memory diagnostic.

Only the diagnostic assigns distinct text colors. No diagnostic painting is
written into a remediated document. Its complete non-space glyph geometry must
equal the input before operator ownership is used.
"""
from collections import Counter
from io import BytesIO
import hashlib
from decimal import Decimal

import fitz
import pikepdf


def _paint_value(value, active=None):
    """Canonical painting data, excluding Unicode/tagging-only font metadata."""
    active=set() if active is None else active
    if isinstance(value,(pikepdf.Dictionary,pikepdf.Stream,pikepdf.Array)):
        identity=value.objgen
        if identity!=(0,0):
            if identity in active:raise ValueError('cyclic painting resource graph')
            active=active|{identity}
        if isinstance(value,pikepdf.Array):return tuple(_paint_value(v,active) for v in value)
        ignored=set()
        if isinstance(value,pikepdf.Stream):ignored.update(('/Length','/Filter','/DecodeParms'))
        if str(value.get('/Type'))=='/Font':ignored.add('/ToUnicode')
        if str(value.get('/Type'))=='/FontDescriptor':ignored.add('/CIDSet')
        if str(value.get('/Subtype')) in ('/Form','/Image'):
            ignored.update(('/StructParent','/StructParents'))
        fields=tuple((str(k),_paint_value(value[k],active)) for k in sorted(value.keys()) if str(k) not in ignored)
        if isinstance(value,pikepdf.Stream):return ('stream',hashlib.sha256(value.read_bytes()).hexdigest(),fields)
        return ('dictionary',fields)
    if isinstance(value,pikepdf.String):return ('string',bytes(value))
    if isinstance(value,pikepdf.Name):return ('name',str(value))
    if isinstance(value,bool) or value is None:return value
    if isinstance(value,(int,float,Decimal)):return ('number',Decimal(str(value)).normalize())
    raise ValueError('unsupported painting resource value')


def verified_source_text_shows(source,working,page_index):
    """Transfer source ownership only when encoded painting is identical.

    ToUnicode can expand one painted ligature into several extracted characters.
    Exact original operators, advances, used resources and page geometry prove
    the source painted-glyph membership independently of that expansion.
    """
    a,b=source.pages[page_index],working.pages[page_index]
    for key in ('/MediaBox','/CropBox','/Rotate','/UserUnit'):
        if _paint_value(a.get(key))!=_paint_value(b.get(key)):return None
    streams=[]
    for page in (a,b):
        streams.append([(i,operands,op) for i,(operands,op) in enumerate(pikepdf.parse_content_stream(page))
                        if str(op) not in ('BDC','BMC','EMC')])
    if pikepdf.unparse_content_stream([(args,op) for _,args,op in streams[0]])!=pikepdf.unparse_content_stream([(args,op) for _,args,op in streams[1]]):return None
    categories={'Tf':'/Font','Do':'/XObject','gs':'/ExtGState','sh':'/Shading','cs':'/ColorSpace','CS':'/ColorSpace'}
    for _,args,op in streams[0]:
        category=categories.get(str(op))
        if category is None:
            if str(op) in ('scn','SCN') and args and isinstance(args[-1],pikepdf.Name):
                category='/Pattern';name=str(args[-1])
            else:continue
        else:name=str(args[0])
        if category=='/ColorSpace' and name in ('/DeviceGray','/DeviceRGB','/DeviceCMYK','/Pattern'):continue
        try:
            left=a.Resources[category][name];right=b.Resources[category][name]
            if _paint_value(left)!=_paint_value(right):return None
        except (KeyError,ValueError):return None
    measurement=text_show_ownership(source,page_index)
    indices={left[0]:right[0] for left,right in zip(streams[0],streams[1])}
    for show in measurement['shows']:show['instruction_index']=indices[show['instruction_index']]
    measurement['ownership_basis']='verified-identical-source-encoded-painting'
    return measurement


def _glyphs(page):
    glyphs=[]
    for block in page.get_text('rawdict')['blocks']:
        for line in block.get('lines',[]):
            for span in line['spans']:
                for char in span['chars']:
                    if not char['c'].isspace():
                        glyphs.append(dict(text=char['c'],bbox=list(char['bbox']),
                                           origin=list(char['origin']),font=span['font'],
                                           size=span['size'],color=span['color']))
    return glyphs


def _identity(glyph):
    return (glyph['text'],glyph['font'],round(glyph['size'],4),
            *[round(v,4) for v in glyph['bbox']+glyph['origin']])


def text_show_ownership(pdf, page_index):
    """Return exact operator glyphs, rejecting diagnostic geometry changes.

    Nested Form text is deliberately unassigned: it belongs to a separate
    stream/placement namespace and must never be conflated with page operators.
    """
    with pikepdf.new() as diagnostic:
        diagnostic.pages.append(pdf.pages[page_index])
        page=diagnostic.pages[0]
        before_bytes=BytesIO();diagnostic.save(before_bytes)
        with fitz.open(stream=before_bytes.getvalue(),filetype='pdf') as document:
            before=_glyphs(document[0]);original_colors={g['color'] for g in before}
        instructions=list(pikepdf.parse_content_stream(page));rewritten=[];shows=[];color_to_show={}
        next_color=0x410000;marked=[]
        resources=page.get('/Resources',pikepdf.Dictionary())
        for index,(operands,operator) in enumerate(instructions):
            op=str(operator)
            if op in ('BMC','BDC'):
                props=operands[1] if op=='BDC' else None
                if isinstance(props,pikepdf.Name):props=resources.get('/Properties',{}).get(str(props))
                marked.append({'tag':str(operands[0]),'mcid':int(props['/MCID'])
                               if isinstance(props,pikepdf.Dictionary) and '/MCID' in props else None})
            elif op=='EMC':
                if not marked:raise ValueError('unbalanced marked content during glyph ownership')
                marked.pop()
            if op not in ('Tj','TJ',"'",'"'):
                rewritten.append((operands,operator));continue
            while next_color in original_colors:next_color+=1
            if next_color>0xFFFFFF:raise ValueError('diagnostic color capacity exceeded')
            color=next_color;next_color+=1
            show={'instruction_index':index,'glyphs':[],'marked_content':[dict(v) for v in marked]}
            color_to_show[color]=show;shows.append(show)
            # Double quote changes persistent Tw/Tc. Apply those values before
            # q so restoration preserves their original effect on later text.
            if op=='"':
                rewritten.extend([(pikepdf.Array([operands[0]]),pikepdf.Operator('Tw')),
                                  (pikepdf.Array([operands[1]]),pikepdf.Operator('Tc'))])
            # QPDF's decimal serialization may round n/255 just below n;
            # choose the center of each 8-bit bucket, not its lower boundary.
            values=pikepdf.Array([min(1,((color>>shift&255)+0.5)/255) for shift in (16,8,0)])
            rewritten.extend([(pikepdf.Array([]),pikepdf.Operator('q')),
                              (values,pikepdf.Operator('rg')),(values,pikepdf.Operator('RG')),
                              (operands,operator),(pikepdf.Array([]),pikepdf.Operator('Q'))])
        page.Contents=diagnostic.make_stream(pikepdf.unparse_content_stream(rewritten))
        after_bytes=BytesIO();diagnostic.save(after_bytes)
        with fitz.open(stream=after_bytes.getvalue(),filetype='pdf') as document:after=_glyphs(document[0])
        if Counter(map(_identity,before))!=Counter(map(_identity,after)):
            raise ValueError('diagnostic text-show labeling changed glyph geometry/identity')
        unassigned=[]
        for glyph in after:
            show=color_to_show.get(glyph['color'])
            if show is None:unassigned.append(glyph)
            else:show['glyphs'].append(glyph)
        return {'shows':shows,'unassigned_glyphs':unassigned,'nonspace_glyph_geometry_verified':True}
