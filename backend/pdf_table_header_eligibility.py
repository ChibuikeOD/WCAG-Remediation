"""PDF-only header-role repair from explicit ID/Headers relationships, never row position."""
from pathlib import Path
import pikepdf
from .pdf_reviewed_tables import _page_owners,_number_tree,_scopes

def _kids(node):
 value=node.get('/K',[])
 return list(value) if isinstance(value,pikepdf.Array) else [value]
def _nodes(root):
 seen=set();count=0
 def walk(node,depth=0):
  nonlocal count
  if depth>128:raise ValueError('structure exceeds bounded traversal depth')
  if not isinstance(node,pikepdf.Dictionary):return
  if node.objgen!=(0,0):
   if node.objgen in seen:raise ValueError('repeated/cyclic structure node')
   seen.add(node.objgen)
  count+=1
  if count>100000:raise ValueError('structure exceeds bounded node count')
  yield node
  for child in _kids(node):
   if isinstance(child,pikepdf.Dictionary) and '/S' in child:yield from walk(child,depth+1)
 return walk(root)
def _headers(cell):
 attributes=cell.get('/A',[]);attributes=list(attributes) if isinstance(attributes,pikepdf.Array) else [attributes];found=[]
 for attribute in attributes:
  if isinstance(attribute,pikepdf.Dictionary) and str(attribute.get('/O'))=='/Table' and '/Headers' in attribute:
   values=attribute.Headers
   if not isinstance(values,pikepdf.Array) or any(not isinstance(v,pikepdf.String) or not bytes(v) for v in values):raise ValueError('malformed explicit Headers attribute')
   found.extend(bytes(v) for v in values)
 return found
def repair_pdf_table_header_roles(path:Path):
 """Only repair a mislabeled TD already explicitly referenced as a painted header."""
 evidence=[];holds=[];promotions=[]
 with pikepdf.open(path,allow_overwriting_input=True) as pdf:
  root=pdf.Root.get('/StructTreeRoot')
  if root is None:return {'promoted_headers':0,'holds':[],'tables_checked':0}
  nodes=list(_nodes(root));tables=[n for n in nodes if str(n.get('/S'))=='/Table'];global_ids={}
  for node in nodes:
   if '/ID' in node:
    if not isinstance(node.ID,pikepdf.String) or not bytes(node.ID):raise ValueError('malformed structure ID')
    global_ids.setdefault(bytes(node.ID),[]).append(node)
  pages={p.obj.objgen:(i,p) for i,p in enumerate(pdf.pages)};parents=_number_tree(root.ParentTree) if '/ParentTree' in root else {};paint_cache={}
  def painted(cell):
   descendants=list(_nodes(cell));found=0
   for node in descendants:
    for ref in _kids(node):
     if isinstance(ref,int):mcid=ref;pg=node.get('/Pg')
     elif isinstance(ref,pikepdf.Dictionary) and '/MCID' in ref and '/Stm' not in ref:mcid=int(ref.MCID);pg=ref.get('/Pg',node.get('/Pg'))
     else:continue
     if pg is None or pg.objgen not in pages:return False
     i,page=pages[pg.objgen]
     if i not in paint_cache:
      _,scopes=_scopes(page);paint_cache[i]=(_page_owners(root,page),scopes)
     owners,scopes=paint_cache[i];matching=[s for s in scopes if s['mcid']==mcid]
     if '/StructParents' not in page.obj or int(page.StructParents) not in parents:return False
     par=parents[int(page.StructParents)]
     if mcid<0 or mcid>=len(par) or owners.get(mcid) is None or owners[mcid].objgen!=node.objgen or par[mcid] is None or par[mcid].objgen!=node.objgen or len(matching)!=1 or not matching[0]['paint']:return False
     found+=1
   return found>0
  for table in tables:
   rows=[row for row in _kids(table) if isinstance(row,pikepdf.Dictionary) and str(row.get('/S'))=='/TR'];cells=[]
   for row in rows:
    if row.get('/P') is None or row.P.objgen!=table.objgen:raise ValueError('table row parent disagrees with source ownership')
    for cell in _kids(row):
     if isinstance(cell,pikepdf.Dictionary) and str(cell.get('/S')) in ('/TD','/TH'):
      if cell.get('/P') is None or cell.P.objgen!=row.objgen:raise ValueError('table cell parent disagrees with source ownership')
      cells.append(cell)
   if any(str(cell.S)=='/TH' for cell in cells):continue
   same_table={cell.objgen:cell for cell in cells};referenced={};problem=None
   for cell in cells:
    for identity in _headers(cell):
     targets=global_ids.get(identity,[])
     if len(targets)!=1 or targets[0].objgen not in same_table or targets[0].objgen==cell.objgen:problem='ambiguous, self or cross-table explicit header identity';break
     if not painted(cell) or not painted(targets[0]):problem='explicit header relationship lacks uniquely owned source painting';break
     referenced[targets[0].objgen]=targets[0]
    if problem:break
   if problem or not referenced:
    holds.append({'table_objgen':list(table.objgen),'reason':problem or 'PDF does not establish header roles through explicit ID/Headers relationships','review_required':True});continue
   for header in referenced.values():promotions.append(header)
   evidence.append({'table_objgen':list(table.objgen),'header_IDs_hex':[bytes(h.ID).hex() for h in referenced.values()],'authority':'existing-PDF-ID-and-Headers-plus-real-marked-paint'})
  # All semantic/ownership checks precede mutation. Only /S changes; no guessed Scope.
  for header in promotions:header.S=pikepdf.Name.TH
  if promotions:pdf.save()
 return {'promoted_headers':len(promotions),'tables_checked':len(tables),'holds':holds,'PDF_only_evidence':evidence,'Scope_inferred':False,'painting_changed':False}
