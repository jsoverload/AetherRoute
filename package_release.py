"""Create a public source release using only explicit, reviewed files.

Never zip the working directory: it may contain personal maps and test captures.
"""
from pathlib import Path
import hashlib
import importlib.metadata as metadata
import io
import json
import sys
import zipfile
from PIL import Image, ImageDraw, ImageFont
from product import NAME, VERSION

ROOT=Path(__file__).resolve().parent
FILES=('app.py','tracking.py','minimap.py','motion.py','routes.py','profiles.py',
       'profile_ui.py','model_routes.py','map_visuals.py','planner.py','windows.py','icon_types.py','map_data.py','map_ui.py',
       'security.py','instance.py','product.py','world_maps.py','ui_settings.py','desktop_ui.py',
       'requirements.txt','requirements-windows.lock','requirements-build-windows.lock','START.cmd','README.txt',
       'ADVANCED.txt','CATALOG-FORMAT.txt','Catalog.csv','SECURITY.txt',
       'RELEASE.txt','VALIDATION.txt','package_release.py',
       'build_windows.py','BUILD.cmd','LICENSE.txt','README.md','NOTICE.txt',
       '.gitignore','.gitattributes','.github/workflows/windows.yml',
       '.github/dependabot.yml','installer/AetherRoute.iss','tests/test_profiles.py','tests/test_map_data.py','tests/test_model_exports.py','MAP-PACKS.txt',
       'tests/test_desktop_workflow.py','tests/test_windows_checkout.py','maps/index.json','maps/altgard.map.json','maps/verteron.map.json','maps/NOTICE.txt',
       'runtime_notices/tcl8.6-license.terms','runtime_notices/tk8.6-license.terms',
       'runtime_notices/SOURCES.txt',
       'docs/images/game-overview.png','docs/images/overlay-in-game.png',
       'docs/images/route-editor.png','docs/images/overlay-settings.png',
       'docs/images/interactive-map.png','docs/images/minimap-area.png')
DEPENDENCIES={'numpy':'2.3.5','opencv-python-headless':'5.0.0.93','Pillow':'12.3.0','mss':'10.2.0'}

def welcome_image():
    im=Image.new('RGB',(720,520),'#141b28');draw=ImageDraw.Draw(im)
    large=ImageFont.load_default(size=34);small=ImageFont.load_default(size=19)
    points=[(68,105),(110,165),(152,100),(194,165),(238,105)]
    draw.line(points,fill='#40dbf1',width=5)
    for x,y in points:draw.ellipse((x-6,y-6,x+6,y+6),fill='#e7edf5')
    draw.text((68,215),'Welcome to '+NAME,font=large,fill='#e7edf5')
    lines=['1. Open Interactive maps and choose a world.',
           '2. Select resources and create a zone / route.',
           'Or add a screenshot with New zone / picture.',
           'Your saved zones are kept when upgrading.']
    for i,line in enumerate(lines):draw.text((68,285+i*35),line,font=small,fill='#b7c5d8')
    out=io.BytesIO();im.save(out,format='PNG');return out.getvalue()

def license_files():
    result={}
    for name,expected in DEPENDENCIES.items():
        dist=metadata.distribution(name)
        if dist.version!=expected:raise RuntimeError('Install the pinned dependencies before packaging.')
        for entry in dist.files or []:
            if 'license' in Path(str(entry)).name.lower() or Path(str(entry)).name.lower().startswith('copying'):
                path=Path(dist.locate_file(entry))
                if path.is_file():
                    safe=str(entry).replace('\\','/')
                    if '..' not in Path(safe).parts:result['THIRD_PARTY_LICENSES/'+name+'/'+safe]=path.read_bytes()
    result['THIRD_PARTY_LICENSES/README.txt']=b'Dependency notices from the pinned source-release environment. Runtime wheels install their own platform notices. BUILD.cmd recollects the installed Windows notices for the executable. Retain these notices when redistributing.\n'
    return result

def members():
    result={name:(ROOT/name).read_bytes() for name in FILES}
    result.update(license_files())
    result['assets/reference.png']=welcome_image()
    result['assets/starter-nodes.json']=b'[]\n'
    result['assets/seed.json']=b'{"welcome":true,"name":"Welcome to AetherRoute"}\n'
    result['RELEASE-MANIFEST.json']=json.dumps(dict(product=NAME,version=VERSION,
        kind='Windows source release candidate',dependencies=DEPENDENCIES,
        bundled_user_maps=False,bundled_routes=False,bundled_third_party_icons=False,
        bundled_worlds=['Altgard','Verteron'],bundled_game_map_artwork=True,
        license='MIT application; third-party map data/artwork retain their original rights'),indent=2).encode()+b'\n'
    result['SHA256SUMS.txt']=''.join(hashlib.sha256(data).hexdigest()+'  '+name+'\n' for name,data in sorted(result.items())).encode()
    return result

def build(path):
    contents=members();path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    # Deterministic timestamps and entry ordering; never include workstation paths.
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name,data in sorted(contents.items()):
            entry=zipfile.ZipInfo(NAME+'/'+name,date_time=(2026,10,6,0,0,0))
            entry.compress_type=zipfile.ZIP_DEFLATED;entry.external_attr=0o644<<16
            archive.writestr(entry,data)
    return path

if __name__=='__main__':
    output=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT.parent/(NAME+'-Windows-RC.zip')
    print(str(build(output)))
