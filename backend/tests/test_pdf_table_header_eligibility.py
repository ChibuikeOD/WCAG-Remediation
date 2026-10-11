"""PDF-only roles require explicit source semantics and real unique painting."""
import hashlib,sys
from pathlib import Path
import fitz,pikepdf,pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from backend.pdf_remediator_fixes import fix_table_headers

def make_pdf(path,mode='linked'):
 with pikepdf.new() as pdf:
  page=pdf.add_blank_page(page_size=(200,200));page.StructParents=0
  page.Resources=pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font,Subtype=pikepdf.Name.Type1,BaseFont=pikepdf.Name.Helvetica))))
  root=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot));doc=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.Document,P=root));tables=[];cells=[];ops=[]
  for ti in range(2 if mode=='cross-table' else 1):
   table=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.Table,P=doc));rows=[]
   for ri in range(2):
    row=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.TR,P=table));rowcells=[]
    for ci in range(2):
     mcid=len(cells);cell=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.TD,P=row,Pg=page.obj,K=pikepdf.Array([mcid])));cells.append(cell);rowcells.append(cell)
     ops.append(f'/P <</MCID {mcid}>> BDC BT /F1 9 Tf {20+ci*80} {170-ti*70-ri*25} Td (Cell{mcid}) Tj ET EMC\n')
    row.K=pikepdf.Array(rowcells);rows.append(row)
   table.K=pikepdf.Array(rows);tables.append(table)
  doc.K=pikepdf.Array(tables);root.K=pikepdf.Array([doc]);root.ParentTree=pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array([0,pikepdf.Array(cells)])));root.ParentTreeNextKey=1;pdf.Root.StructTreeRoot=root;page.Contents=pdf.make_stream(''.join(ops).encode())
  if mode!='unlinked':
   header=cells[4] if mode=='cross-table' else cells[0];header.ID=pikepdf.String('header-A');cells[2].A=pikepdf.Dictionary(O=pikepdf.Name.Table,Headers=pikepdf.Array([pikepdf.String('header-A')]))
  if mode=='duplicate-ID':cells[1].ID=pikepdf.String('header-A')
  if mode=='empty-header':cells[0].K=pikepdf.Array()
  if mode=='duplicate-MCID':cells[1].K=pikepdf.Array([0])
  if mode=='wrong-parent':cells[0].P=cells[0]
  if mode=='existing-TH':cells[0].S=pikepdf.Name.TH
  pdf.save(path)

def test_only_explicit_PDF_header_target_promoted_with_paint_unchanged(tmp_path):
 path=tmp_path/'input.pdf';make_pdf(path)
 with pikepdf.open(path) as pdf:before=pdf.pages[0].Contents.read_bytes()
 with fitz.open(path) as pdf:rgb=pdf[0].get_pixmap().samples;text=pdf[0].get_text()
 result=fix_table_headers(path)
 assert result['success'] and result['details']['promoted_headers']==1 and not result['details']['Scope_inferred']
 with pikepdf.open(path) as pdf:
  cells=[cell for row in pdf.Root.StructTreeRoot.K[0].K[0].K for cell in row.K]
  assert [str(c.S) for c in cells]==['/TH','/TD','/TD','/TD']
  assert bytes(cells[0].ID)==b'header-A' and bytes(cells[2].A.Headers[0])==b'header-A'
  assert '/A' not in cells[0] and pdf.pages[0].Contents.read_bytes()==before
 with fitz.open(path) as pdf:assert pdf[0].get_pixmap().samples==rgb and pdf[0].get_text()==text

@pytest.mark.parametrize('mode',['unlinked','cross-table','duplicate-ID','empty-header','duplicate-MCID','wrong-parent'])
def test_ambiguous_or_unpainted_header_roles_do_not_mutate_pdf(tmp_path,mode):
 path=tmp_path/'input.pdf';make_pdf(path,mode);before=hashlib.sha256(path.read_bytes()).hexdigest();result=fix_table_headers(path)
 assert not result['success']
 assert hashlib.sha256(path.read_bytes()).hexdigest()==before
 if mode not in ('duplicate-MCID','wrong-parent'):assert result['details']['holds']

def test_existing_TH_not_replaced_or_given_guessed_scope(tmp_path):
 path=tmp_path/'input.pdf';make_pdf(path,'existing-TH');before=path.read_bytes();result=fix_table_headers(path)
 assert result['success'] and result['details']['promoted_headers']==0 and path.read_bytes()==before
