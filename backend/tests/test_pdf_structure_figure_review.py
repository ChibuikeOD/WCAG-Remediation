"""Generic PDF-only tagging must not disguise missing figure semantics with placeholder Alt."""
import sys
from pathlib import Path
import fitz
import pikepdf
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from backend.layout_model import PageLayout,StructureBlock
from backend.pdf_structure_builder import PDFStructureBuilder

def test_figure_without_pdf_description_remains_review_required_and_paint_unchanged(tmp_path):
 source=tmp_path/'original.pdf';output=tmp_path/'tagged.pdf'
 with pikepdf.new() as pdf:
  page=pdf.add_blank_page(page_size=(100,100));page.Contents=pdf.make_stream(b'0 0 1 rg 10 10 30 30 re f\n');pdf.save(source)
 layout=PageLayout(page_number=0,width=100,height=100,blocks=[StructureBlock(tag='Figure',page_number=0,metadata={'raw_bbox':[10,10,40,40]})])
 result=PDFStructureBuilder().build_tagged_pdf(source,output,[layout])
 assert result.success and result.tag_counts=={'Figure':1}
 assert result.warnings==['Figure on page 1 requires a source-supported alternative description.']
 with pikepdf.open(source) as original,pikepdf.open(output) as tagged:
  figure=tagged.Root.StructTreeRoot.K[0].K[0]
  assert str(figure.S)=='/Figure' and '/Alt' not in figure
  assert list(figure.K)==[0] and figure.Pg.objgen==tagged.pages[0].obj.objgen
  assert original.pages[0].Contents.read_bytes()==tagged.pages[0].Contents.read_bytes()
 with fitz.open(source) as original,fitz.open(output) as tagged:
  assert original[0].get_pixmap().samples==tagged[0].get_pixmap().samples
