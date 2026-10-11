from io import BytesIO
import json, subprocess
from PIL import Image
import fitz, pikepdf
from backend.tests.test_native_inline_scripts import native_cli


def attrs(element):
    attribute=element.get('/A')
    return list(attribute) if isinstance(attribute,pikepdf.Array) else [attribute]


def test_native_table_spans_scope_image_parent_and_exact_fidelity(native_cli,tmp_path):
    source,output,layout=(tmp_path/name for name in ('table.pdf','table-tagged.pdf','table.json'))
    image=BytesIO();Image.new('RGB',(5,5),(80,120,160)).save(image,format='PNG')
    with fitz.open() as document:
        page=document.new_page(width=200,height=200)
        page.insert_text((30,15),'Introduction',fontsize=10)
        page.insert_text((30,40),'Name',fontsize=12)
        page.insert_text((30,130),'Sample',fontsize=12)
        page.insert_image(fitz.Rect(110,60,170,110),stream=image.getvalue())
        text=page.get_text();pixels=page.get_pixmap().samples
        document.save(source)
    description='Two test specimens have opposing ply orientations.'
    layout.write_text(json.dumps([
        {'page':0,'tag':'P','bbox':[20,182,100,200]},
        {'page':0,'tag':'TH','bbox':[20,120,90,180],'table_id':'t1','table_row':0,'table_col':0,
         'table_header':True,'table_scope':'Column'},
        {'page':0,'tag':'TD','bbox':[100,20,190,180],'table_id':'t1','table_row':0,'table_col':1,
         'table_header':False,'table_scope':'','table_row_span':2,'figure_alt_hex':description.encode().hex()},
        {'page':0,'tag':'TD','bbox':[20,20,90,100],'table_id':'t1','table_row':1,'table_col':0,
         'table_header':False,'table_scope':''}]),encoding='utf-8')
    subprocess.run([str(native_cli),str(source),str(layout),str(output)],check=True,capture_output=True,timeout=30)
    with fitz.open(output) as document:
        assert document[0].get_text()==text
        assert document[0].get_pixmap().samples==pixels
    with pikepdf.open(output) as pdf:
        root_kids=pdf.Root.StructTreeRoot.K[0].K
        assert [str(element.S) for element in root_kids]==['/P','/Table']
        table=root_kids[1]
        assert str(table.S)=='/Table'
        assert [str(row.S) for row in table.K]==['/TR','/TR']
        assert [[str(cell.S) for cell in row.K] for row in table.K]==[['/TH','/TD'],['/TD']]
        header,spanned=table.K[0].K
        assert any(str(a.get('/Scope'))=='/Column' for a in attrs(header))
        assert any(a.get('/RowSpan')==2 for a in attrs(spanned))
        figure=spanned.K[0]
        assert str(figure.S)=='/Figure' and figure.P==spanned
        assert str(figure.Alt)==description
        assert all(row.P==table for row in table.K)
        assert all(cell.P==row for row in table.K for cell in row.K)
        parent_tree=pdf.Root.StructTreeRoot.ParentTree.Nums[1]
        assert parent_tree[int(figure.K.MCID)]==figure


def test_native_retains_empty_cells_and_supplied_unknown_scope(native_cli,tmp_path):
    source,output,layout=(tmp_path/name for name in ('empty-cell.pdf','empty-cell-tagged.pdf','empty-cell.json'))
    with fitz.open() as document:
        page=document.new_page(width=200,height=200);page.insert_text((30,40),'Label')
        document.save(source)
    layout.write_text(json.dumps([
        {'page':0,'tag':'TH','bbox':[20,120,90,180],'table_id':'t1','table_row':0,'table_col':0,
         'table_header':True,'table_scope':''},
        {'page':0,'tag':'TD','bbox':[100,120,190,180],'table_id':'t1','table_row':0,'table_col':1,
         'table_header':False,'table_scope':''}]),encoding='utf-8')
    subprocess.run([str(native_cli),str(source),str(layout),str(output)],check=True,capture_output=True,timeout=30)
    with pikepdf.open(output) as pdf:
        cells=pdf.Root.StructTreeRoot.K[0].K[0].K[0].K
        assert len(cells)==2 and len(cells[1].K)==0
        assert not any('/Scope' in a for a in attrs(cells[0]))
