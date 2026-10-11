import hashlib
import pikepdf
import pytest
from backend.pdf_reviewed_tables import _reuse_existing_image_grid, _page_owners
from backend.pdf_reviewed_figures import _placements

def fixture():
    pdf=pikepdf.new();page=pdf.add_blank_page(page_size=(200,200))
    font=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/Font'),Subtype=pikepdf.Name('/Type1'),BaseFont=pikepdf.Name('/Helvetica')))
    image=pdf.make_stream(b'\xff\x00\x00');image.Type=pikepdf.Name('/XObject');image.Subtype=pikepdf.Name('/Image');image.Width=1;image.Height=1;image.BitsPerComponent=8;image.ColorSpace=pikepdf.Name('/DeviceRGB')
    page.Resources=pikepdf.Dictionary(Font=pikepdf.Dictionary(F=font),XObject=pikepdf.Dictionary(I=image))
    page.Contents=pdf.make_stream(b'BT /F 12 Tf 10 180 Td /Span <</MCID 0>> BDC (Name) Tj EMC 80 0 Td /Span <</MCID 1>> BDC (Image) Tj EMC -80 -30 Td /Span <</MCID 2>> BDC (Row1) Tj EMC 0 -30 Td /Span <</MCID 3>> BDC (Row2) Tj EMC ET /Figure <</MCID 4>> BDC q 30 0 0 50 100 90 cm /I Do Q EMC')
    root=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructTreeRoot')));doc=pdf.make_indirect(pikepdf.Dictionary(S=pikepdf.Name('/Document'),P=root));grid=pdf.make_indirect(pikepdf.Dictionary(S=pikepdf.Name('/Table'),P=doc));root.K=doc;doc.K=pikepdf.Array([grid]);pdf.Root.StructTreeRoot=root
    rows=[pdf.make_indirect(pikepdf.Dictionary(S=pikepdf.Name('/TR'),P=grid,K=pikepdf.Array([]))) for _ in range(3)];grid.K=pikepdf.Array(rows)
    cells=[];nodes=[]
    for identifier,row,col,mcid,role in [('h1',0,0,0,'TH'),('h2',0,1,1,'TH'),('r1',1,0,2,'TH'),('im',1,1,None,'TD'),('r2',2,0,3,'TH')]:
        node=pdf.make_indirect(pikepdf.Dictionary(S=pikepdf.Name('/TD'),P=rows[row],Pg=page.obj,K=pikepdf.Array([])))
        rows[row].K.append(node);nodes.append(node)
        if mcid is not None:node.K.append(pikepdf.Dictionary(Type=pikepdf.Name('/MCR'),Pg=page.obj,MCID=mcid))
        cells.append(dict(id=identifier,row=row,col=col,rowspan=2 if identifier=='im' else 1,colspan=1,role=role,scope='Column' if row==0 else 'Row' if role=='TH' else None,headers=['h2','r1','r2'] if identifier=='im' else [],glyphs=[]))
    figure=pdf.make_indirect(pikepdf.Dictionary(S=pikepdf.Name('/Figure'),P=nodes[3],Pg=page.obj,K=pikepdf.Dictionary(Type=pikepdf.Name('/MCR'),Pg=page.obj,MCID=4)));nodes[3].K.append(figure)
    parents=pikepdf.Array([nodes[0],nodes[1],nodes[2],nodes[4],figure]);root.ParentTree=pikepdf.Dictionary(Nums=pikepdf.Array([0,parents]));page.StructParents=0
    placement=next(_placements(page));cells[3]['embedded_image_binding']={'original_raw_stream_sha256':placement['payload'],'verified_page_bbox_pdf_exact_decimal':placement['bbox']}
    inst=list(pikepdf.parse_content_stream(page));shows=[i for i,v in enumerate(inst) if str(v[1])=='Tj'];order=dict(zip(['h1','h2','r1','r2'],[[i] for i in shows]));binding={'cell_show_order':order,'assignments':{i:c for c,indices in order.items() for i in indices}}
    return pdf,page,root,grid,nodes,figure,dict(id='table',sha='a'*64,page=1,cells=cells),binding

def test_preserve_existing_image_grid_and_add_exact_headers():
    pdf,page,root,grid,nodes,figure,table,binding=fixture()
    with pdf:
        stream=page.Contents.read_bytes();parents=[n.objgen for n in root.ParentTree.Nums[1]];owners={m:n.objgen for m,n in _page_owners(root,page).items()};figure_k=str(figure.K)
        result=_reuse_existing_image_grid(pdf,page,table,binding,pdf)
        assert result=={'preserved_image_cells':1,'preserved_existing_grid':True}
        assert page.Contents.read_bytes()==stream and [n.objgen for n in root.ParentTree.Nums[1]]==parents
        assert {m:n.objgen for m,n in _page_owners(root,page).items()}==owners
        assert str(figure.K)==figure_k and figure.P.objgen==nodes[3].objgen
        assert str(nodes[2].S)=='/TH' and str(nodes[2].A[-1].Scope)=='/Row'
        assert nodes[3].A[-1].RowSpan==2
        assert [str(h) for h in nodes[3].A[-1].Headers]==[str(nodes[i].ID) for i in (1,2,4)]

@pytest.mark.parametrize('fault',['payload','order','parent_tree','dependency','extra_image_paint','extra_text_paint','foreign_page','foreign_form'])
def test_reject_unverified_existing_image_grid_before_mutation(fault):
    pdf,page,root,grid,nodes,figure,table,binding=fixture()
    with pdf:
        if fault=='payload':table['cells'][3]['embedded_image_binding']['original_raw_stream_sha256']='0'*64
        if fault=='order':grid.K[0].K=pikepdf.Array(list(reversed(grid.K[0].K)))
        if fault=='parent_tree':root.ParentTree.Nums[1][4]=nodes[3]
        if fault=='dependency':nodes[2].ID=pikepdf.String('existing')
        if fault=='extra_image_paint':page.Contents=pdf.make_stream(page.Contents.read_bytes().replace(b'/I Do',b'/I Do 0 0 10 10 re f'))
        if fault=='extra_text_paint':page.Contents=pdf.make_stream(page.Contents.read_bytes().replace(b'(Name) Tj',b'(Name) Tj (Other) Tj'))
        if fault=='foreign_page':nodes[0].K.append(pikepdf.Dictionary(Type=pikepdf.Name('/MCR'),Pg=pdf.add_blank_page().obj,MCID=99))
        if fault=='foreign_form':nodes[0].K.append(pikepdf.Dictionary(Type=pikepdf.Name('/MCR'),Pg=page.obj,Stm=pdf.make_stream(b''),MCID=99))
        before=[str(n) for n in nodes];stream=page.Contents.read_bytes()
        with pytest.raises(ValueError):_reuse_existing_image_grid(pdf,page,table,binding,pdf)
        assert [str(n) for n in nodes]==before and page.Contents.read_bytes()==stream
