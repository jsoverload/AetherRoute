"""Read-only packaged worlds, independent of the user's custom map library."""
import hashlib
from pathlib import Path
import re
from map_data import validate_pack
from security import ValidationError, plain_text, read_json

def built_in_maps(root):
    path=Path(root)/'maps'/'index.json'
    if not path.exists():return []
    data=read_json(path,100000)
    if not isinstance(data,list) or len(data)>100:raise ValidationError('Invalid built-in world list.')
    entries=[];seen=set()
    for item in data:
        if not isinstance(item,dict):raise ValidationError('Invalid built-in world entry.')
        world=plain_text(item.get('world_id',''),50)
        name=plain_text(item.get('name',''),100)
        filename=item.get('file','');digest=item.get('sha256','')
        if not world.isdecimal() or world in seen or not name or not isinstance(filename,str) or not re.fullmatch(r'[a-z0-9-]+\.map\.json',filename) or not isinstance(digest,str) or not re.fullmatch(r'[0-9a-f]{64}',digest):
            raise ValidationError('Invalid built-in map metadata.')
        seen.add(world);entries.append(dict(id='builtin-'+world,name=name,world_id=world,file=filename,sha256=digest,builtin=True))
    return entries

def load_built_in(root,entry):
    path=Path(root)/'maps'/entry['file']
    if path.resolve().parent!=(Path(root)/'maps').resolve() or path.stat().st_size>50000000:raise ValidationError('Invalid built-in map file.')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:raise ValidationError('The built-in map is incomplete or modified. Extract the complete application again.')
    pack,image=validate_pack(read_json(path,50000000))
    if pack['world_id']!=entry['world_id'] or pack['name']!=entry['name'] or pack['world_bounds'] is None:raise ValidationError('The built-in world is not configured correctly.')
    return pack,image
