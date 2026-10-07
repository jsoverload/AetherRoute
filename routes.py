"""Portable local routes/catalogs. Coordinates belong to the included map reference."""
from security import ValidationError
import csv
import io
import math
import uuid
from security import read_json, plain_text
from pathlib import Path

REFERENCE='uruthumheim-812x733'
KINDS=('Ore','Crystal','Plant','Custom','Herbs','Trees','Berries','Vegetables','Shellfish','HiddenCube','Waypoint')
NAMES={'Ore':'Metal Ore','Crystal':'Gems','Plant':'Od','Custom':'Custom','Herbs':'Herbs','Trees':'Trees','Berries':'Berries','Vegetables':'Vegetables','Shellfish':'Shellfish','HiddenCube':'Hidden Cube Spots','Waypoint':'Waypoint'}
ALIASES={v.lower():k for k,v in NAMES.items()} | {k.lower():k for k in KINDS}

def clean_nodes(nodes,size=(812,733)):
    if not isinstance(nodes,list) or len(nodes)>10000:raise ValidationError('Invalid marker list (maximum 10,000).')
    result=[]
    for node in nodes:
        if not isinstance(node,dict):raise ValidationError('Each marker must be an object.')
        try:
            if isinstance(node['X'],bool) or isinstance(node['Y'],bool):raise ValidationError()
            x,y=float(node['X']),float(node['Y'])
        except (KeyError,TypeError,ValueError,OverflowError) as exc:raise ValidationError('Invalid marker coordinates.') from exc
        kind=ALIASES.get(str(node.get('Kind','Custom')).lower())
        if not math.isfinite(x) or not math.isfinite(y) or not 0<=x<=size[0] or not 0<=y<=size[1] or kind is None:
            raise ValidationError('Invalid marker coordinates or category. Use the included reference map, not game/world coordinates.')
        clean=dict(X=x,Y=y,Kind=kind)
        for key in ('Name','Id','Source'):
            value=plain_text(node.get(key,'') or '',240)
            if value:clean[key]=value
        result.append(clean)
    return result

def decode_route(data,reference=REFERENCE,size=(812,733)):
    if not isinstance(data,dict) or data.get('format') not in ('aion2-visual-route-v2','aion2-visual-route-v3','aion2-visual-route-v4') or data.get('reference')!=reference:
        raise ValidationError('This route is for a different reference map or uses an unsupported format.')
    nodes=clean_nodes(data.get('nodes'),size)
    if len(nodes)>1000:raise ValidationError('Routes support at most 1000 stops. Import larger lists as a gatherable catalog.')
    try:opacity=float(data.get('opacity',.85));next_node=int(data.get('next',0))
    except (ValueError,TypeError,OverflowError) as exc:raise ValidationError('Invalid route display settings.') from exc
    if not math.isfinite(opacity):raise ValidationError('Invalid opacity.')
    filters=data.get('filters',{})
    if not isinstance(filters,dict):raise ValidationError('Invalid filters.')
    if any(type(v)!=bool for k,v in filters.items() if k in KINDS) or any(type(data[k])!=bool for k in ('loop','labels','hide_moving') if k in data):raise ValidationError('Route options must use true or false.')
    name=plain_text(data.get('name','Imported route'),100).strip() or 'Untitled route'
    if len(name)>100:raise ValidationError('Route name is too long.')
    return dict(format=data['format'],reference=reference,id=plain_text(data.get('id') or str(uuid.uuid4()),100),nodes=nodes,name=name,next=min(max(0,len(nodes)-1),max(0,next_node)),opacity=max(.25,min(1,opacity)),filters={k:v for k,v in filters.items() if k in KINDS},loop=data.get('loop',True),labels=data.get('labels',True),hide_moving=data.get('hide_moving',True))

def read_catalog(path,reference=REFERENCE,size=(812,733),crop=None,source_size=None):
    path=Path(path)
    if path.stat().st_size>24000000:raise ValidationError('Catalog file is too large.')
    if path.suffix.lower()=='.csv':
        rows=list(csv.DictReader(io.StringIO(path.read_text(encoding='utf-8-sig'))))
        refs={r.get('Reference') for r in rows}
        if len(refs)!=1:raise ValidationError('All rows must specify the same Reference.')
        ref=next(iter(refs));nodes=rows
    else:
        data=read_json(path);
        if not isinstance(data,dict):raise ValidationError('Catalog must be a JSON object.')
        ref=data.get('reference');nodes=data.get('nodes')
    if ref==reference:return clean_nodes(nodes,size)
    if ref=='source-image' and crop is not None and source_size is not None:
        points=clean_nodes(nodes,source_size);x0,y0,x1,y1=crop
        return [dict(n,X=n['X']-x0,Y=n['Y']-y0) for n in points if x0<=n['X']<=x1 and y0<=n['Y']<=y1]
    raise ValidationError('Catalog reference does not match this profile. Use profile pixels or source-image pixels with crop metadata.')

def label(node):return node.get('Name') or NAMES[node['Kind']]
