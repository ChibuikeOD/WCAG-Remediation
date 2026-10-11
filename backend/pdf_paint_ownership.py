"""Measure top-level text-show glyph ownership using an in-memory diagnostic.

Only the diagnostic assigns distinct text colors. No diagnostic painting is
written into a remediated document. Its complete non-space glyph geometry must
equal the input before operator ownership is used.
"""
from collections import Counter
from io import BytesIO

import fitz
import pikepdf


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
