"""Build a clean, unsigned Windows executable from the public allowlist."""
from pathlib import Path
import hashlib
import importlib.metadata as metadata
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
import _tkinter
from package_release import members
from product import NAME, VERSION

ROOT=Path(__file__).resolve().parent

def installer_compiler():
    configured=shutil.which('ISCC.exe')
    if configured:return configured
    import os
    for key in ('ProgramFiles(x86)','ProgramFiles'):
        folder=os.environ.get(key)
        if folder:
            candidate=Path(folder)/'Inno Setup 6'/'ISCC.exe'
            if candidate.is_file():return str(candidate)
    raise SystemExit('Install Inno Setup 6, or add ISCC.exe to PATH, then run BUILD.cmd again.')

def collect_runtime_notices(dist,stage):
    target=dist/'THIRD_PARTY_LICENSES'/'Python-Tcl-Tk';target.mkdir(parents=True,exist_ok=True)
    python_license=Path(sys.base_prefix)/'LICENSE.txt'
    if not python_license.is_file():raise SystemExit('The installed Python LICENSE.txt is missing. Use a complete official Python installation.')
    shutil.copy2(python_license,target/'Python-LICENSE.txt')
    for name,family in (('tcl',_tkinter.TCL_VERSION),('tk',_tkinter.TK_VERSION)):
        installed=Path(sys.base_prefix)/'tcl'/(name+family)/'license.terms'
        fallback=stage/'runtime_notices'/(name+family+'-license.terms')
        notice=installed if installed.is_file() else fallback
        if not notice.is_file():raise SystemExit('Matching Tcl or Tk license notices are missing. Add upstream notices for this runtime before building.')
        shutil.copy2(notice,target/(name+family+'-license.terms'))

def build():
    if sys.platform!='win32':raise SystemExit('Build the Windows executable on Windows.')
    if not (3,11)<=sys.version_info[:2]<=(3,14) or sys.maxsize<=2**32:raise SystemExit('Use 64-bit Python 3.11 through 3.14.')
    compiler=installer_compiler()
    output=ROOT/'release';output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='aetherroute-build-') as temporary:
        stage=Path(temporary)/'source';stage.mkdir()
        for name,data in members().items():
            path=stage/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        version=stage/'version.rc'
        version.write_text("VSVersionInfo(ffi=FixedFileInfo(filevers=(0,9,0,6),prodvers=(0,9,0,6),mask=0x3f,flags=0x2,OS=0x40004,fileType=0x1,subtype=0x0,date=(0,0)),kids=[StringFileInfo([StringTable('040904B0',[StringStruct('FileDescription','AetherRoute route overlay'),StringStruct('FileVersion','"+VERSION+"'),StringStruct('ProductName','AetherRoute'),StringStruct('ProductVersion','"+VERSION+"'),StringStruct('OriginalFilename','AetherRoute.exe')])]),VarFileInfo([VarStruct('Translation',[1033,1200])])])")
        subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--windowed','--noupx',
            '--name',NAME,'--distpath',str(Path(temporary)/'dist'),'--workpath',str(Path(temporary)/'work'),
            '--specpath',str(Path(temporary)/'spec'),'--version-file',str(version),
            '--add-data',str(stage/'assets')+';assets','--add-data',str(stage/'maps')+';maps',
            '--hidden-import','mss.windows',str(stage/'app.py')],check=True,cwd=stage)
        dist=Path(temporary)/'dist'/NAME
        for name in ('README.txt','SECURITY.txt','RELEASE.txt','VALIDATION.txt','ADVANCED.txt','CATALOG-FORMAT.txt','Catalog.csv','LICENSE.txt','NOTICE.txt','MAP-PACKS.txt'):
            shutil.copy2(stage/name,dist/name)
        shutil.copytree(stage/'THIRD_PARTY_LICENSES',dist/'THIRD_PARTY_LICENSES')
        builder=metadata.distribution('PyInstaller')
        builder_notices=0
        for entry in builder.files or []:
            notice_name=Path(str(entry)).name.lower()
            if 'license' in notice_name or notice_name.startswith('copying'):
                path=Path(builder.locate_file(entry))
                if path.is_file():
                    target=dist/'THIRD_PARTY_LICENSES'/'PyInstaller'/str(entry)
                    if '..' not in Path(str(entry)).parts:
                        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target);builder_notices+=1
        if not builder_notices:raise SystemExit('PyInstaller license notices are missing. Reinstall the pinned builder before distributing.')
        collect_runtime_notices(dist,stage)
        # Check personal build paths in every shipped file, including binaries.
        private_paths={variant for p in (Path.home(),ROOT,Path(temporary)) for variant in (str(p),p.as_posix(),str(p).replace('\\','\\\\'))}
        signatures=[p.encode(encoding) for p in private_paths for encoding in ('utf-8','utf-16le')]
        for path in dist.rglob('*'):
            if path.is_file() and any(secret in path.read_bytes() for secret in signatures):
                raise SystemExit('A personal build path was found in the bundle. Rebuild in a neutral directory before distribution.')
        subprocess.run([str(dist/(NAME+'.exe')),'--self-test'],check=True,timeout=60,cwd=dist)
        (dist/'BUILD-INFO.json').write_text(json.dumps(dict(product=NAME,version=VERSION,python=sys.version.split()[0],pyinstaller=builder.version,signed=False),indent=2))
        hashes=''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(dist).as_posix()+'\n' for p in sorted(dist.rglob('*')) if p.is_file())
        (dist/'SHA256SUMS.txt').write_text(hashes)
        archive=output/(NAME+'-Windows-'+VERSION+'-unsigned.zip')
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as package:
            for path in sorted(dist.rglob('*')):
                if path.is_file():package.write(path,NAME+'/'+path.relative_to(dist).as_posix())
        subprocess.run([compiler,'/DSourceRoot='+str(dist),'/DOutputRoot='+str(output),'/DAppVersion='+VERSION,str(stage/'installer'/'AetherRoute.iss')],check=True)
        installer=output/(NAME+'-Setup-'+VERSION+'.exe')
        source=output/(NAME+'-Source-'+VERSION+'.zip')
        from package_release import build as build_source
        build_source(source)
        checksums=''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in (installer,archive,source))
        (output/'SHA256SUMS.txt').write_text(checksums,encoding='utf-8')
        print('Built installer, portable ZIP, source ZIP and checksums in '+str(output)+'. Test on Windows before publishing.')

if __name__=='__main__':build()
