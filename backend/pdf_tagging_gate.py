"""Required structural tagging must finish before a repaired PDF is published."""
from pathlib import Path

import pikepdf

_PAINT={'Do','Tj','TJ',"'",'"','S','s','f','F','f*','B','B*','b','b*','sh','INLINE IMAGE'}


def _check_content_ownership(pdf,root):
    """Bound structural traversal and verify real content, one namespace at a time."""
    parents={};seen=set();stack=[(root.ParentTree,0)];visited=0
    while stack:
        node,depth=stack.pop();visited+=1
        if depth>64 or visited>1000000 or len(parents)>1000000:raise ValueError('ParentTree traversal budget exceeded')
        if not isinstance(node,pikepdf.Dictionary):raise ValueError('invalid ParentTree node')
        if node.objgen!=(0,0):
            if node.objgen in seen:raise ValueError('repeated/cyclic ParentTree node')
            seen.add(node.objgen)
        nums=node.get('/Nums',[])
        if len(nums)%2:raise ValueError('incomplete ParentTree pairs')
        for index in range(0,len(nums),2):
            key=nums[index]
            if not isinstance(key,int) or key<0 or key in parents:raise ValueError('invalid/duplicate ParentTree key')
            parents[key]=nums[index+1]
        stack.extend((kid,depth+1) for kid in node.get('/Kids',[]))
    pages={page.obj.objgen:page for page in pdf.pages};owners={};namespaces={};seen=set();visited=0
    stack=[(root.K,None,None,0)]
    while stack:
        node,pg,owner,depth=stack.pop();visited+=1
        if depth>256 or visited>1000000:raise ValueError('structure traversal budget exceeded')
        if isinstance(node,pikepdf.Array):
            stack.extend((child,pg,owner,depth+1) for child in reversed(node));continue
        stm=None;mcid=None
        if isinstance(node,pikepdf.Dictionary):
            if node.objgen!=(0,0):
                if node.objgen in seen:raise ValueError('repeated/cyclic structure node')
                seen.add(node.objgen)
            pg=node.get('/Pg',pg)
            if '/S' in node:owner=node
            if '/MCID' in node:mcid=node.MCID;stm=node.get('/Stm')
            elif '/K' in node:stack.append((node.K,pg,owner,depth+1))
        elif isinstance(node,int):mcid=node
        if mcid is None:continue
        if not isinstance(mcid,int) or mcid<0 or pg is None or pg.objgen not in pages or owner is None or owner.objgen==(0,0):
            raise ValueError('structure content reference has no valid page/owner/MCID')
        namespace=pages[pg.objgen] if stm is None else stm
        namespace_id=(pg.objgen,None if stm is None else stm.objgen)
        identity=(*namespace_id,mcid)
        if identity in owners:raise ValueError('duplicate structural MCID owner')
        owners[identity]=owner;namespaces[namespace_id]=namespace
        if '/StructParents' not in namespace:raise ValueError('content namespace has no StructParents')
        array=parents.get(int(namespace.StructParents))
        if not isinstance(array,pikepdf.Array) or mcid>=len(array) or array[mcid] is None or array[mcid].objgen!=owner.objgen:
            raise ValueError('content owner differs from ParentTree')
    if not owners:raise ValueError('structure has no content references')
    owned_paint=0
    for identity,namespace in namespaces.items():
        active=[];declared=set();resources=namespace.get('/Resources',pages[identity[0]].Resources)
        for operands,operator in pikepdf.parse_content_stream(namespace):
            op=str(operator)
            if op in ('BMC','BDC'):
                mcid=None
                if op=='BDC':
                    props=operands[1]
                    if isinstance(props,pikepdf.Name):props=resources.get('/Properties',{}).get(str(props))
                    if isinstance(props,pikepdf.Dictionary) and '/MCID' in props:
                        mcid=int(props.MCID)
                        if mcid in declared:raise ValueError('repeated marked-content MCID')
                        declared.add(mcid)
                        if (*identity,mcid) not in owners:raise ValueError('marked-content MCID has no structure owner')
                active.append(mcid)
            elif op=='EMC':
                if not active:raise ValueError('unbalanced marked content')
                active.pop()
            elif op in _PAINT and any(mcid is not None for mcid in active):owned_paint+=1
        if active:raise ValueError('unclosed marked content')
        expected={key[2] for key in owners if key[:2]==identity}
        if not expected<=declared:raise ValueError('structure MCID has no marked-content occurrence')
    if not owned_paint:raise ValueError('structure has no owned painting operations')


class RequiredPDFTaggingError(RuntimeError):
    status = 'UNSUCCESSFUL'

    def __init__(self, path, reason):
        self.working_path = str(Path(path))
        self.reason = reason
        super().__init__('UNSUCCESSFUL: required PDF tagging '+reason)


def require_pdf_tagging(path, *, tagging_required, tagging_result=None):
    """Check the tagging prerequisite, without claiming native PDF/UA validity.

    Review holds in later semantic repairs do not enter this gate. An existing
    structure tree cannot conceal a failed required rebuild or timeout.
    """
    if tagging_required and not (tagging_result or {}).get('success'):
        reason=(tagging_result or {}).get('error','did not complete')
        raise RequiredPDFTaggingError(path,'failed: '+str(reason))
    try:
        with pikepdf.open(path) as pdf:
            root=pdf.Root.get('/StructTreeRoot')
            if not isinstance(root,pikepdf.Dictionary):
                raise ValueError('output has no StructTreeRoot')
            children=root.get('/K')
            if not isinstance(children,(pikepdf.Dictionary,pikepdf.Array)) or not len(children):
                raise ValueError('output has no structure children')
            parents=root.get('/ParentTree')
            if not isinstance(parents,pikepdf.Dictionary):
                raise ValueError('output has no structure ParentTree')
            if not any(key in parents for key in ('/Nums','/Kids')):
                raise ValueError('output has no ParentTree entries')
            _check_content_ownership(pdf,root)
    except RequiredPDFTaggingError:
        raise
    except Exception as error:
        raise RequiredPDFTaggingError(path,'postcondition failed: '+str(error)) from error
