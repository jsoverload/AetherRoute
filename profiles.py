"""Profile store: image + catalog + routes, with atomic writes and legacy migration."""
from security import ValidationError
import base64
import hashlib
import io
import json
from pathlib import Path
import uuid
import shutil
import time
import struct
from PIL import Image
from security import read_json, atomic_json, plain_image, safe_image, MAX_IMAGE_BYTES, plain_text, friendly_error
from routes import REFERENCE, clean_nodes, decode_route
from minimap import settings as minimap_settings

MAX_PIXELS=25_000_000
LEGACY_IMAGE_REFERENCE='map-e33a20aa90e13a87007723b3'
LEGACY_PIXEL_REFERENCE='map-px-35d1723c988f1194a08f650c'

def image_bytes(image):
    out=io.BytesIO();plain_image(image).save(out,format='PNG');return out.getvalue()

def load_image(path):
    if Path(path).stat().st_size>MAX_IMAGE_BYTES:raise ValidationError('Image file is too large.')
    return safe_image(path)

def reference_id(image):
    # Identity describes visible pixels, never the platform's PNG compressor.
    # The original namespace is retained across the AetherRoute rename.
    rgb=plain_image(image)
    digest=hashlib.sha256(b'WayveilRGB-v1\0'+struct.pack('<II',*rgb.size)+rgb.tobytes())
    return 'map-px-'+digest.hexdigest()[:24]

def legacy_metadata_reference(image):
    out=io.BytesIO();image.convert('RGB').save(out,format='PNG')
    return 'map-'+hashlib.sha256(out.getvalue()).hexdigest()[:24]

def reference_aliases(image,raw=None):
    pixel=reference_id(image)
    aliases={pixel,legacy_metadata_reference(image),
             'map-'+hashlib.sha256(image_bytes(image)).hexdigest()[:24]}
    if raw is not None:aliases.add('map-'+hashlib.sha256(raw).hexdigest()[:24])
    if pixel==LEGACY_PIXEL_REFERENCE:aliases.update((REFERENCE,LEGACY_IMAGE_REFERENCE))
    return aliases

def matching_reference(image,ref,raw=None):
    return isinstance(ref,str) and ref in reference_aliases(image,raw)

def validate_geometry(p,size):
    if type(p.get('width'))!=int or type(p.get('height'))!=int or size!=(p['width'],p['height']):raise ValidationError('Profile image dimensions do not match.')
    crop=p.get('crop');source=p.get('source_size')
    if not isinstance(source,list) or len(source)!=2 or not isinstance(crop,list) or len(crop)!=4:raise ValidationError('Invalid crop metadata.')
    if any(type(v)!=int for v in crop+source) or not 0<=crop[0]<crop[2]<=source[0] or not 0<=crop[1]<crop[3]<=source[1] or (crop[2]-crop[0],crop[3]-crop[1])!=size:raise ValidationError('Invalid crop bounds.')

def profile_source(profile):
    if profile.get('zone_source') in ('picture','interactive','welcome'):return profile['zone_source']
    return 'interactive' if any(n.get('Source')=='Imported map database' for n in profile.get('catalog',[])) else 'picture'

def source_metadata(profile):
    source=profile.get('zone_source')
    if source is not None and source not in ('picture','interactive','welcome'):raise ValidationError('Invalid zone source.')
    for key in ('map_world','map_name'):
        if key in profile:profile[key]=plain_text(profile[key],100)
    return profile

class ProfileStore:
    def __init__(self,folder,assets):
        self.folder=Path(folder);self.assets=Path(assets);self.path=self.folder/'profiles.json'
        self.recovered=False
        if self.path.exists():
            try:
                self.data=read_json(self.path,50_000_000);self.validate_data()
            except (ValueError,OSError,TypeError,KeyError) as exc:
                backup=self.path.with_name('profiles.backup.json')
                if not backup.exists():raise ValidationError('Saved profiles could not be opened. '+friendly_error(exc)+' Original files are preserved.') from exc
                try:self.data=read_json(backup,50_000_000);self.validate_data()
                except (ValueError,OSError,TypeError,KeyError) as backup_exc:
                    raise ValidationError('Saved profiles and their backup could not be opened. '+friendly_error(backup_exc)+' Original files are preserved.') from backup_exc
                self.recovered=True
                shutil.copy2(self.path,self.path.with_name('profiles.damaged-'+str(time.time_ns())+'.json'))
        else:self.data=self.migrate();self.validate_data();self.write()
    def validate_data(self):
        if not isinstance(self.data,dict) or not isinstance(self.data.get('profiles'),list) or not self.data['profiles']:raise ValidationError('Saved profiles are invalid. Original files have been preserved.')
        if len(self.data['profiles'])>100:raise ValidationError('Maximum 100 zone profiles.')
        ids=set()
        for p in self.data['profiles']:
            self.validate(p)
            if p['id'] in ids:raise ValidationError('Duplicate saved zone identifiers.')
            ids.add(p['id'])
    @property
    def profiles(self):return self.data['profiles']
    @property
    def active(self):return next((p for p in self.profiles if p['id']==self.data.get('active')),self.profiles[0])
    def validate(self,p):
        if not isinstance(p,dict):raise ValidationError('Invalid profile object.')
        p['id']=plain_text(p.get('id',''),36)
        p['name']=plain_text(p.get('name','My zone'),100)
        p['minimap']=minimap_settings(p.get('minimap'))
        if p.get('overlay_mode','big') not in ('big','minimap'):raise ValidationError('Invalid overlay mode.')
        image_path=self.folder/'profile-images'/(str(uuid.UUID(p['id']))+'.png')
        image=load_image(image_path)
        validate_geometry(p,image.size)
        with Image.open(image_path) as original:
            if not matching_reference(original,p['reference'],image_path.read_bytes()):raise ValidationError('The saved map picture does not match its profile.')
        p['catalog']=clean_nodes(p.get('catalog',[]),image.size)
        source_metadata(p)
        routes=p.get('routes',[])
        if not isinstance(routes,list) or not 1<=len(routes)<=500:raise ValidationError('A zone must have 1 to 500 routes.')
        p['routes']=[decode_route(r,p['reference'],image.size) for r in routes]
        return p
    def image_path(self,p):return self.folder/'profile-images'/(str(uuid.UUID(p['id']))+'.png')
    def write(self):
        if len(json.dumps(self.data,indent=2,allow_nan=False).encode('utf-8'))>50_000_000:raise ValidationError('Saved data exceeds the supported size limit. Export and remove unused zones or routes.')
        if self.path.exists() and not self.recovered:
            try:
                previous=read_json(self.path,50_000_000)
                if isinstance(previous,dict) and isinstance(previous.get('profiles'),list):atomic_json(self.path.with_name('profiles.backup.json'),previous)
            except ValueError:pass
        atomic_json(self.path,self.data)
        self.recovered=False
    def migrate(self):
        seed=read_json(self.assets/'seed.json',8000) if (self.assets/'seed.json').exists() else {}
        if seed.get('welcome') and any((self.folder/name).exists() for name in ('session.json','routes.json','catalog.json')):
            raise ValidationError('Older setup detected. Export a profile using your previous version, then import it here. Original files are preserved.')
        image=load_image(self.assets/'reference.png');pid=str(uuid.uuid4());path=self.folder/'profile-images'/(pid+'.png');path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(image_bytes(image))
        starter=read_json(self.assets/'starter-nodes.json')
        old_points={(round(n['X'],3),round(n['Y'],3)) for n in starter if n['Kind']=='Ore'}
        def fix(nodes):
            for n in nodes:
                if n.get('Kind')=='Ore' and not n.get('Name') and (round(float(n['X']),3),round(float(n['Y']),3)) in old_points:
                    n['Kind']='HiddenCube';n['Source']='Original screenshot (estimated position)'
            return nodes
        starter=fix(starter)
        route=dict(format='aion2-visual-route-v4',reference=reference_id(image) if seed.get('welcome') else REFERENCE,id=str(uuid.uuid4()),name='My route' if seed.get('welcome') else 'Starter route',nodes=starter,loop=True,labels=True,filters={})
        routes=[];current=route
        # Read old files before the new store is written. Do not overwrite them.
        if (self.folder/'routes.json').exists():routes=[decode_route(r) for r in read_json(self.folder/'routes.json')]
        if (self.folder/'session.json').exists():current=decode_route(read_json(self.folder/'session.json'))
        for r in routes:
            fix(r['nodes']);r.setdefault('id',str(uuid.uuid4()))
            if 'Ore' in r.get('filters',{}):r['filters']['HiddenCube']=r['filters']['Ore']
        fix(current['nodes']);current.setdefault('id',str(uuid.uuid4()))
        if 'Ore' in current.get('filters',{}):current['filters']['HiddenCube']=current['filters']['Ore']
        at=next((i for i,r in enumerate(routes) if r['id']==current['id']),None)
        if at is None:routes.append(current)
        else:routes[at]=current
        # Always retain the supplied starter setup as well as an edited session.
        if not any(r['nodes']==starter for r in routes):routes.insert(0,route)
        catalog=starter
        if (self.folder/'catalog.json').exists():
            d=read_json(self.folder/'catalog.json');catalog=fix(clean_nodes(d['nodes']))
        profile=dict(id=pid,name=seed.get('name','Altgard - Uruthumheim'),reference=reference_id(image) if seed.get('welcome') else REFERENCE,width=image.width,height=image.height,source_size=list(image.size),crop=[0,0,*image.size],catalog=catalog,routes=routes,current=current['id'],header=None if seed.get('welcome') else 'altgard')
        profile['zone_source']='welcome' if seed.get('welcome') else 'picture'
        return dict(format='aion2-profiles-v1',active=pid,profiles=[profile])
    def create(self,name,image,crop=None,catalog=None,nodes=None,zone_source='picture',map_world='',map_name=''):
        if len(self.profiles)>=100:raise ValidationError('Maximum 100 zone profiles.')
        box=crop or (0,0,image.width,image.height);x0,y0,x1,y1=map(int,box)
        if not 0<=x0<x1<=image.width or not 0<=y0<y1<=image.height or x1-x0<80 or y1-y0<80:raise ValidationError('Crop must be inside the source image and at least 80 x 80 pixels.')
        clean_catalog=clean_nodes([] if catalog is None else catalog,(x1-x0,y1-y0))
        clean_stops=clean_nodes([] if nodes is None else nodes,(x1-x0,y1-y0))
        if len(clean_stops)>1000:raise ValidationError('A route supports at most 1000 stops.')
        old_active=self.data.get('active')
        clipped=image.crop((x0,y0,x1,y1));pid=str(uuid.uuid4());ref=reference_id(clipped)
        route=dict(format='aion2-visual-route-v4',reference=ref,id=str(uuid.uuid4()),name='My route',nodes=clean_stops,loop=True,labels=True,filters={})
        p=dict(id=pid,name=plain_text(name,100).strip() or 'New zone',reference=ref,width=clipped.width,height=clipped.height,source_size=list(image.size),crop=[x0,y0,x1,y1],catalog=clean_catalog,routes=[route],current=route['id'],header=None)
        p.update(zone_source=zone_source,map_world=map_world,map_name=map_name);source_metadata(p)
        path=self.image_path(p);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(image_bytes(clipped))
        self.profiles.append(p);self.data['active']=pid
        try:self.write()
        except (OSError,ValueError):
            self.profiles.remove(p);self.data['active']=old_active;path.unlink(missing_ok=True);raise
        return p
    def export(self,p,path):
        # Public exports intentionally omit model prompts/tasks and unknown metadata.
        shared={k:p[k] for k in ('name','reference','width','height','source_size','crop','catalog','routes','current','header','id','minimap','overlay_mode','zone_source','map_world','map_name') if k in p}
        source_metadata(shared)
        shared['catalog']=clean_nodes(p['catalog'],(p['width'],p['height']))
        shared['routes']=[decode_route(r,p['reference'],(p['width'],p['height'])) for r in p['routes']]
        image=load_image(self.image_path(p))
        canonical=REFERENCE if p['reference']==REFERENCE else reference_id(image)
        shared['reference']=canonical
        for route in shared['routes']:route['reference']=canonical
        payload=dict(format='aion2-profile-v1',profile=shared,image=base64.b64encode(image_bytes(image)).decode('ascii'))
        if len(json.dumps(payload,indent=2).encode())>50_000_000:raise ValidationError('Profile export exceeds 50 MB. Use a smaller map or fewer routes.')
        atomic_json(path,payload)
    def import_file(self,path):
        path=Path(path)
        if path.stat().st_size>50_000_000:raise ValidationError('Profile file exceeds 50 MB.')
        d=read_json(path,50_000_000)
        if not isinstance(d,dict):raise ValidationError('Profile must be a JSON object.')
        if len(self.profiles)>=100:raise ValidationError('Maximum 100 zone profiles.')
        if d.get('format')!='aion2-profile-v1':raise ValidationError('Unsupported profile file.')
        raw=base64.b64decode(d['image'],validate=True)
        with Image.open(io.BytesIO(raw)) as im:
            if im.width*im.height>MAX_PIXELS or min(im.size)<80:raise ValidationError('Invalid profile image size.')
            im.load();matches=matching_reference(im,d.get('profile',{}).get('reference') if isinstance(d.get('profile'),dict) else None,raw);image=plain_image(im)
        original=d['profile']
        if not isinstance(original,dict):raise ValidationError('Invalid profile object.')
        p={k:original[k] for k in ('name','reference','width','height','source_size','crop','catalog','routes','current','header','id','minimap','overlay_mode','zone_source','map_world','map_name') if k in original}
        source_metadata(p)
        ref=p['reference']
        if not matches:raise ValidationError('The shared map picture does not match its profile.')
        validate_geometry(p,image.size)
        p['catalog']=clean_nodes(p.get('catalog',[]),image.size)
        if not isinstance(p.get('routes'),list) or len(p['routes'])>500:raise ValidationError('Maximum 500 routes per zone.')
        p['routes']=[decode_route(r,ref,image.size) for r in p['routes']]
        if ref!=REFERENCE:
            ref=reference_id(image);p['reference']=ref
            for route in p['routes']:route['reference']=ref
        if not p['routes']:raise ValidationError('A profile must contain a route.')
        p['minimap']=minimap_settings(p.get('minimap'))
        if p.get('overlay_mode','big') not in ('big','minimap'):raise ValidationError('Invalid overlay mode.')
        p.pop('planning',None)
        prefs=p.get('model_preferences',{})
        if not isinstance(prefs,dict):raise ValidationError('Invalid model preferences.')
        p['model_preferences']=dict(prompt=str(prefs.get('prompt',''))[:10000],source=str(prefs.get('source','Current route')),subset=bool(prefs.get('subset',False)),mode='image' if prefs.get('mode')=='image' else 'stops')
        p['id']=str(uuid.uuid4());p['name']=plain_text(p.get('name','Imported zone'),100);p['header']='altgard' if p.get('header')=='altgard' and ref==REFERENCE and (self.assets/'map-header.png').exists() else None
        current=p.get('current');mapping={}
        for r in p['routes']:
            old=r.get('id');r['id']=str(uuid.uuid4());mapping[old]=r['id']
        p['current']=mapping.get(current,p['routes'][0]['id'])
        path=self.image_path(p);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(image_bytes(image));old_active=self.data.get('active');self.profiles.append(p);self.data['active']=p['id']
        try:self.write()
        except (OSError,ValueError):
            self.profiles.remove(p);self.data['active']=old_active;path.unlink(missing_ok=True);raise
        return p
