"""Offline map packs: typed world coordinates, explicit image bounds, no requests."""
import base64
import io
import math
from pathlib import Path
import uuid
from profiles import image_bytes, load_image, reference_id
from routes import clean_nodes
from security import ValidationError, atomic_json, plain_text, read_json, safe_image

FORMAT='aetherroute-map-v1'
CATEGORY_KINDS={'metal':'Ore','jewelry':'Crystal','od':'Plant','herb':'Herbs',
                'tree':'Trees','berry':'Berries','vegetable':'Vegetables',
                'shellfish':'Shellfish','hidden-cube':'HiddenCube'}
WORLD_NAMES={'1000':'Poeta','1010':'Verteron','1011':'Eltnen',
             '1100':'Ishalgen','1110':'Altgard','1111':'Morheim',
             '20':'Chaotic Lower Reshanta','22':'Chaotic Middle Reshanta',
             '23':'Chaotic Upper Reshanta'}
# Coordinate metadata from the supplied world configuration, not map artwork.
# Only the verified full image receives automatic bounds. A filename, world ID
# or resource extrema cannot identify the edges of a custom/cropped picture.
KNOWN_IMAGES={'1110':('map-px-ca920d88ffabdb7d26bd815a',
                      (-408000,-408000,408000,408000)),
              '1010':('map-px-f0e6057569bd6e15171a83fb',
                      (-408000,-408000,408000,408000))}


def pair(value):
    if not isinstance(value,(list,tuple)) or len(value)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>1e9 for v in value):
        raise ValidationError('Invalid map coordinates.')
    return [float(v) for v in value]


def bounds(value):
    if value is None:return None
    if not isinstance(value,(list,tuple)) or len(value)!=4:raise ValidationError('Map bounds need minimum X, minimum Y, maximum X and maximum Y.')
    x0,y0=pair(value[:2]);x1,y1=pair(value[2:])
    if x1-x0<1e-6 or y1-y0<1e-6:raise ValidationError('Maximum map bounds must be greater than minimum bounds.')
    return [x0,y0,x1,y1]


def rows(data):
    if isinstance(data,dict) and 'result' in data:data=data['result']
    if isinstance(data,dict) and 'data' in data:data=data['data']
    if not isinstance(data,list) or len(data)>200_000:raise ValidationError('Map database must contain a bounded list of records.')
    return data


def world_choices(path):
    found={}
    for row in rows(read_json(path,50_000_000)):
        if isinstance(row,dict) and row.get('mapCategory') in CATEGORY_KINDS and (row.get('mapCategory')=='hidden-cube' or row.get('mapType')=='gatherable'):
            world=plain_text(str(row.get('mapWorldId','')),50)
            found[world]=found.get(world,0)+1
    return sorted(found.items(),key=lambda item:(-item[1],item[0]))


def from_exports(image_path,markers_path,regions_path,world,name):
    world=plain_text(world,50);name=plain_text(name,100).strip() or WORLD_NAMES.get(world,world)
    markers=[]
    for row in rows(read_json(markers_path,50_000_000)):
        if not isinstance(row,dict) or str(row.get('mapWorldId'))!=world:continue
        category=row.get('mapCategory')
        if category not in CATEGORY_KINDS:continue
        if category!='hidden-cube' and row.get('mapType')!='gatherable':continue
        locations=row.get('coordinates')
        if not isinstance(locations,list) or len(locations)>1000:raise ValidationError('Invalid resource position list.')
        for i,location in enumerate(locations):
            markers.append(dict(world=pair(location),Kind=CATEGORY_KINDS[category],
                                Name=plain_text(row.get('name',''),240),
                                Id=plain_text(str(row.get('id',''))+'#'+str(i),240)))
    regions=[]
    if regions_path:
        for row in rows(read_json(regions_path,50_000_000)):
            if not isinstance(row,dict) or str(row.get('mapWorldId'))!=world:continue
            regions.append(dict(name=plain_text(row.get('name',''),100),label=pair(row.get('label')),
                                polygons=row.get('polygons',[])))
    if not markers:raise ValidationError('This world contains no supported resource locations.')
    image=load_image(image_path)
    pack=dict(format=FORMAT,name=name,world_id=world,image=base64.b64encode(image_bytes(image)).decode('ascii'),
              markers=markers,regions=regions,world_bounds=None,flip_y=True,
              source='User-provided map database; artwork and data retain their original ownership.')
    return validate_pack(pack)[0]


def validate_pack(pack):
    if not isinstance(pack,dict) or pack.get('format') not in (FORMAT,'wayveil-map-v1'):raise ValidationError('Unsupported map pack format.')
    name=plain_text(pack.get('name',''),100).strip()
    if not name:raise ValidationError('Give the map a name.')
    world=plain_text(pack.get('world_id',''),50)
    encoded=pack.get('image')
    if not isinstance(encoded,str) or len(encoded)>45_000_000:raise ValidationError('Map image is too large.')
    try:image=safe_image(io.BytesIO(base64.b64decode(encoded,validate=True)))
    except (ValueError,TypeError,OSError) as exc:raise ValidationError('The map pack image cannot be opened.') from exc
    markers=pack.get('markers')
    if not isinstance(markers,list) or not 1<=len(markers)<=100_000:raise ValidationError('A map pack needs 1 to 100,000 resource positions.')
    clean=[];seen=set()
    for marker in markers:
        if not isinstance(marker,dict) or marker.get('Kind') not in CATEGORY_KINDS.values():raise ValidationError('Unsupported map resource type.')
        identifier=plain_text(marker.get('Id',''),240)
        if not identifier or identifier in seen:raise ValidationError('Resource identifiers must be unique.')
        seen.add(identifier)
        clean.append(dict(world=pair(marker.get('world')),Kind=marker['Kind'],Name=plain_text(marker.get('Name',''),240),Id=identifier))
    regions=pack.get('regions',[])
    if not isinstance(regions,list) or len(regions)>500:raise ValidationError('Maximum 500 map regions.')
    cleaned_regions=[];vertices=0
    for region in regions:
        if not isinstance(region,dict):raise ValidationError('Invalid map region.')
        polygons=region.get('polygons',[])
        if not isinstance(polygons,list) or len(polygons)>100:raise ValidationError('Invalid region boundaries.')
        cleaned_polygons=[]
        for polygon in polygons:
            if not isinstance(polygon,list) or not 3<=len(polygon)<=5000:raise ValidationError('Invalid region polygon.')
            vertices+=len(polygon)
            if vertices>100_000:raise ValidationError('Too many map region vertices.')
            cleaned_polygons.append([pair(point) for point in polygon])
        cleaned_regions.append(dict(name=plain_text(region.get('name',''),100),label=pair(region.get('label')),polygons=cleaned_polygons))
    flip=pack.get('flip_y',True)
    if type(flip)!=bool:raise ValidationError('Map Y direction must use true or false.')
    normalized=dict(format=FORMAT,name=name,world_id=world,image=base64.b64encode(image_bytes(image)).decode('ascii'),
                    markers=clean,regions=cleaned_regions,world_bounds=bounds(pack.get('world_bounds')),flip_y=flip,
                    source=plain_text(pack.get('source','Imported map data'),240))
    known=KNOWN_IMAGES.get(world)
    if normalized['world_bounds'] is None and known and reference_id(image)==known[0]:
        normalized['world_bounds']=list(known[1]);normalized['flip_y']=True
    return normalized,image


def world_to_pixel(point,world_bounds,size,flip_y=True):
    boundary=bounds(world_bounds)
    if boundary is None:raise ValidationError('Map coordinate bounds are missing. Configure them before using resources.')
    x,y=pair(point);x0,y0,x1,y1=boundary
    px=(x-x0)*size[0]/(x1-x0)
    py=((y1-y) if flip_y else (y-y0))*size[1]/(y1-y0)
    return px,py


def catalog(pack,size):
    result=[];outside=0
    for marker in pack['markers']:
        x,y=world_to_pixel(marker['world'],pack['world_bounds'],size,pack['flip_y'])
        if not 0<=x<=size[0] or not 0<=y<=size[1]:outside+=1;continue
        result.append(dict(X=x,Y=y,Kind=marker['Kind'],Name=marker['Name'],Id=marker['Id'],Source='Imported map database'))
    return result,outside


def contains(point,polygon):
    x,y=point;inside=False
    previous=polygon[-1]
    for current in polygon:
        ax,ay=previous;bx,by=current
        if (ay>y)!=(by>y) and x<(bx-ax)*(y-ay)/(by-ay)+ax:inside=not inside
        previous=current
    return inside


def select_nodes(nodes,kinds,search='',region=None):
    query=search.casefold().strip();result=[]
    for node in nodes:
        if node['Kind'] not in kinds or query and query not in node.get('Name','').casefold():continue
        if region and not any(contains((node['X'],node['Y']),p) for p in region):continue
        result.append(node)
    return result


def create_profile(store,pack,image,crop,nodes,route,name):
    # Validate everything before creating a save; terrain never contains drawn icons.
    x0,y0,x1,y1=crop
    selected=clean_nodes([dict(n,X=n['X']-x0,Y=n['Y']-y0) for n in nodes if x0<=n['X']<=x1 and y0<=n['Y']<=y1],(x1-x0,y1-y0))
    stops=clean_nodes([dict(n,X=n['X']-x0,Y=n['Y']-y0) for n in route if x0<=n['X']<=x1 and y0<=n['Y']<=y1],(x1-x0,y1-y0))
    if len(stops)!=len(route):raise ValidationError('The selected area must include all route stops. Clear the route or select a larger area.')
    if len(stops)>1000:raise ValidationError('A route supports at most 1000 stops.')
    return store.create(name,image,crop,catalog=selected,nodes=stops,zone_source='interactive',map_world=pack['world_id'],map_name=pack['name'])


class MapLibrary:
    def __init__(self,folder):
        self.folder=Path(folder);self.path=self.folder/'index.json'
        self.entries=read_json(self.path,100_000) if self.path.exists() else []
        if not isinstance(self.entries,list) or len(self.entries)>100:raise ValidationError('Invalid map library index.')
        seen=set()
        for entry in self.entries:
            if not isinstance(entry,dict):raise ValidationError('Invalid saved map entry.')
            identifier=str(uuid.UUID(entry['id']))
            if identifier!=entry['id'] or identifier in seen:raise ValidationError('Invalid saved map identifier.')
            seen.add(identifier);plain_text(entry['name'],100);plain_text(entry['world_id'],50)
    def file(self,entry):return self.folder/(str(uuid.UUID(entry['id']))+'.map.json')
    def load(self,entry):return validate_pack(read_json(self.file(entry),50_000_000))
    def add(self,pack):
        if len(self.entries)>=100:raise ValidationError('Maximum 100 saved maps.')
        pack,_=validate_pack(pack);entry=dict(id=str(uuid.uuid4()),name=pack['name'],world_id=pack['world_id'])
        path=self.file(entry);atomic_json(path,pack,limit=50_000_000)
        self.entries.append(entry)
        try:atomic_json(self.path,self.entries)
        except (ValueError,OSError):self.entries.remove(entry);path.unlink(missing_ok=True);raise
        return entry
    def update(self,entry,pack):
        normalized,_=validate_pack(pack)
        if normalized['name']!=entry['name'] or normalized['world_id']!=entry['world_id']:raise ValidationError('Saved map identity cannot change during coordinate setup.')
        atomic_json(self.file(entry),normalized,limit=50_000_000)
    def delete(self,entry):
        remaining=[e for e in self.entries if e['id']!=entry['id']]
        atomic_json(self.path,remaining);self.entries=remaining
        # Leave the unindexed pack as a recovery copy; it is never listed again.
