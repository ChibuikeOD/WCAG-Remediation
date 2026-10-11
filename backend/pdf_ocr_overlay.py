"""Add local OCR text without replacing any original page painting."""
from collections import Counter
import hashlib
from io import BytesIO
import math
import os
from pathlib import Path
import tempfile

import fitz
import pikepdf


def _image_payloads(pdf):
    return Counter(hashlib.sha256(obj.read_raw_bytes()).hexdigest() for obj in pdf.objects
                   if isinstance(obj, pikepdf.Stream) and str(obj.get('/Subtype')) == '/Image')


def _font_programs(pdf):
    hashes = set()
    for obj in pdf.objects:
        if isinstance(obj, pikepdf.Dictionary):
            for key in ('/FontFile', '/FontFile2', '/FontFile3'):
                stream = obj.get(key)
                if isinstance(stream, pikepdf.Stream):
                    hashes.add(hashlib.sha256(stream.read_bytes()).hexdigest())
    return hashes


def install_ocr_text_layers(source: Path, layers: dict[int, tuple[bytes, tuple]]) -> dict:
    """Import only invisible OCR text/font resources, preserving original images.

    The rasterized recognition input is temporary. Its image is never copied to
    the output. Every visible page operator and original raster payload remains.
    """
    handle = tempfile.NamedTemporaryFile(prefix='.ocr-text-', suffix='.pdf', dir=source.parent, delete=False)
    candidate = Path(handle.name); handle.close()
    with pikepdf.open(source) as pdf:
        original_images = _image_payloads(pdf)
        original_fonts = _font_programs(pdf)
        for page_index, (ocr_bytes, matrix) in layers.items():
            if len(matrix) != 6 or not all(math.isfinite(v) for v in matrix):
                raise ValueError('invalid OCR placement matrix')
            with pikepdf.open(BytesIO(ocr_bytes)) as ocr:
                if len(ocr.pages) != 1:
                    raise ValueError('OCR text layer must contain exactly one page')
                layer = ocr.pages[0]
                page = pdf.pages[page_index]
                resources = pikepdf.Dictionary(page.get('/Resources', pikepdf.Dictionary()))
                fonts = pikepdf.Dictionary(resources.get('/Font', pikepdf.Dictionary()))
                source_fonts = layer.Resources.get('/Font', pikepdf.Dictionary())
                renamed = {}
                text_instructions = []
                for operands, operator in pikepdf.parse_content_stream(layer):
                    op = str(operator)
                    if op == 'Do':
                        xobject = layer.Resources.get('/XObject', {}).get(str(operands[0]))
                        if xobject is None or str(xobject.get('/Subtype')) != '/Image':
                            raise ValueError('unsupported non-image OCR XObject')
                        continue
                    if op in {'S','s','f','F','f*','B','B*','b','b*','sh','INLINE IMAGE'}:
                        raise ValueError('unsupported visible OCR layer painting')
                    if op == 'Tf':
                        old = str(operands[0])
                        if old not in renamed:
                            if old not in source_fonts:
                                raise ValueError('OCR text references missing font')
                            index = 0
                            while f'/OCR{index}' in fonts: index += 1
                            name = f'/OCR{index}'
                            fonts[name] = pdf.copy_foreign(ocr.make_indirect(source_fonts[old]))
                            renamed[old] = name
                        operands = pikepdf.Array([pikepdf.Name(renamed[old]), operands[1]])
                    if op == 'Tr':
                        operands = pikepdf.Array([3])
                    text_instructions.append((operands, operator))
                    if op == 'BT':
                        text_instructions.append((pikepdf.Array([3]), pikepdf.Operator('Tr')))
                resources.Font = fonts
                page.Resources = resources
                prefix = ('q ' + ' '.join(str(v) for v in matrix) + ' cm\n').encode()
                overlay = pdf.make_stream(prefix + pikepdf.unparse_content_stream(text_instructions) + b'\nQ')
                contents = page.get('/Contents')
                page.Contents = pikepdf.Array(list(contents) + [overlay] if isinstance(contents,pikepdf.Array)
                                             else [contents,overlay])
        pdf.save(candidate, compress_streams=False,
                 stream_decode_level=pikepdf.StreamDecodeLevel.none)
    with pikepdf.open(candidate) as after:
        if _image_payloads(after) != original_images or not original_fonts <= _font_programs(after):
            raise ValueError(f'OCR overlay changed original image/font payloads; candidate retained at {candidate}')
        added_programs = len(_font_programs(after) - original_fonts)
    with fitz.open(source) as before, fitz.open(candidate) as after:
        for page_index in layers:
            a,b = before[page_index].get_pixmap(dpi=96,alpha=False),after[page_index].get_pixmap(dpi=96,alpha=False)
            if (a.width,a.height,a.samples) != (b.width,b.height,b.samples):
                raise ValueError(f'OCR overlay changed page pixels; candidate retained at {candidate}')
    os.replace(candidate,source)
    return {'pages_overlaid':len(layers),'source_raster_payloads_preserved':True,
            'source_font_programs_preserved':True,'ocr_font_programs_added':added_programs,
            'output_rasterized':False,'ocr_text_review_required':True}
