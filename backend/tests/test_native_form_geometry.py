import json
import subprocess

import fitz
import pikepdf
import pytest

from backend.tests.test_native_inline_scripts import native_cli


def write_inherited_fixture(path, matrix):
    def stream(dictionary, content):
        return dictionary + b' /Length ' + str(len(content)).encode() + b' >>\nstream\n' + content + b'\nendstream'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 /Resources << /XObject << /Chart 4 0 R >> >> >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 250 250] /Contents 5 0 R >>',
               stream(b'<< /Type /XObject /Subtype /Form /BBox [-10 -5 40 60] /Matrix [' +
                      ' '.join(map(str,matrix)).encode() + b'] /Resources << /Font << /F1 6 0 R >> >>',
                      b'0 0 40 60 re S BT /F1 10 Tf 2 20 Td (Chart) Tj ET'),
               stream(b'<<', b'q 2 0 0 3 60 30 cm /Chart Do Q'),
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    content = b'%PDF-1.7\n'; offsets = []
    for number, obj in enumerate(objects,1):
        offsets.append(len(content)); content += f'{number} 0 obj\n'.encode() + obj + b'\nendobj\n'
    xref = len(content)
    content += b'xref\n0 7\n0000000000 65535 f \n'
    content += b''.join(f'{offset:010} 00000 n \n'.encode() for offset in offsets)
    content += f'trailer\n<< /Root 1 0 R /Size 7 >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    path.write_bytes(content)


@pytest.mark.parametrize('matrix,expected', [
    ([1,0,0,1,0,0], [40,15,140,210]),
    ([0,.5,-.5,0,20,10], [40,45,105,120]),
    ([-1,0,.25,1,40,0], [57.5,15,190,210]),
])
@pytest.mark.parametrize('inherited_resources', [False, True])
def test_form_bbox_matrix_page_ctm_and_fidelity(native_cli, tmp_path, matrix, expected, inherited_resources):
    source, layout, output = (tmp_path / n for n in ('source.pdf', 'layout.json', 'tagged.pdf'))
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(250,250))
        font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font,
                                                  Subtype=pikepdf.Name.Type1,
                                                  BaseFont=pikepdf.Name.Helvetica))
        form = pdf.make_stream(b'0 0 40 60 re S BT /F1 10 Tf 2 20 Td (Chart) Tj ET')
        form.Type = pikepdf.Name.XObject; form.Subtype = pikepdf.Name.Form
        form.BBox = pikepdf.Array([-10,-5,40,60]); form.Matrix = pikepdf.Array(matrix)
        form.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
        page.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Chart=form))
        if inherited_resources:
            pdf.Root.Pages.Resources = page.Resources
            del page.obj['/Resources']
        page.Contents = pdf.make_stream(b'q 2 0 0 3 60 30 cm /Chart Do Q')
        pdf.save(source)
    if inherited_resources:
        # QPDF's normal writer pushes inherited resources to pages. Write a
        # valid small fixture explicitly to exercise actual serialized inheritance.
        write_inherited_fixture(source, matrix)
    layout.write_text(json.dumps([{'page':0,'tag':'Figure','bbox':expected,
                                  'alt_hex':'A test chart with a rectangular frame.'.encode().hex()}]))
    with fitz.open(source) as pdf:
        pixels, text = pdf[0].get_pixmap(dpi=96).samples, pdf[0].get_text()
    subprocess.run([str(native_cli),str(source),str(layout),str(output)],check=True,capture_output=True,timeout=30)
    with fitz.open(output) as pdf:
        assert pdf[0].get_pixmap(dpi=96).samples == pixels
        assert pdf[0].get_text() == text
    with pikepdf.open(source) as before, pikepdf.open(output) as after:
        original_resources = before.pages[0].get('/Resources', before.Root.Pages.get('/Resources'))
        tagged_resources = after.pages[0].get('/Resources', after.Root.Pages.get('/Resources'))
        original_form, tagged_form = original_resources.XObject.Chart, tagged_resources.XObject.Chart
        assert original_form.read_bytes() == tagged_form.read_bytes()
        assert original_form.Matrix == tagged_form.Matrix
        assert original_form.BBox == tagged_form.BBox
        figure = after.Root.StructTreeRoot.K[0].K[0]
        assert str(figure.S) == '/Figure'
        attributes = figure.A if isinstance(figure.A,pikepdf.Array) else [figure.A]
        bounds = next(a.BBox for a in attributes if '/BBox' in a)
        assert [float(x) for x in bounds] == pytest.approx(expected)
        assert after.Root.StructTreeRoot.ParentTree.Nums[1][int(figure.K.MCID)] == figure


def test_form_without_valid_bbox_has_no_fabricated_unit_square(native_cli,tmp_path):
    source, layout, output = (tmp_path / n for n in ('source.pdf','layout.json','tagged.pdf'))
    with pikepdf.Pdf.new() as pdf:
        page=pdf.add_blank_page(page_size=(100,100))
        form=pdf.make_stream(b'0 0 10 10 re f');form.Subtype=pikepdf.Name.Form
        page.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(F=form))
        page.Contents=pdf.make_stream(b'/F Do');pdf.save(source)
    layout.write_text('[]')
    subprocess.run([str(native_cli),str(source),str(layout),str(output)],check=True,capture_output=True,timeout=30)
    with pikepdf.open(output) as pdf:
        figure=pdf.Root.StructTreeRoot.K[0].K[0]
        assert '/A' not in figure
