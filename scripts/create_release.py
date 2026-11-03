"""Package only public source and the current portable Windows application."""
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = ('assets','bin','chao2','frontend','licenses','resource','runtime','scripts','tests')
FILES = ('README.md','启动说明.txt','LICENSE','THIRD_PARTY_NOTICES.md','config.json',
         'app.py','start.pyw','build-frontend.ps1','requirements.lock','requirements-runtime.lock','pytest.ini')


def build():
    for required in ('bin/Chao2Harvester.exe','runtime/python/python.exe'):
        if not (ROOT/required).is_file():
            raise SystemExit('Missing build output: '+required)
    version=ET.parse(ROOT/'frontend/Chao2Harvester.csproj').findtext('.//Version')
    out=ROOT/'dist';out.mkdir(exist_ok=True)
    target=out/f'Chao2Harvester-v{version}-windows-x64.zip'
    with ZipFile(target,'w',ZIP_DEFLATED,compresslevel=6) as archive:
        paths=[ROOT/name for name in FILES]
        for name in DIRECTORIES:
            paths.extend(p for p in (ROOT/name).rglob('*') if p.is_file())
        for path in sorted(paths):
            relative=path.relative_to(ROOT)
            if '__pycache__' in relative.parts or path.suffix in ('.pyc','.pyo','.pdb','.log'):
                continue
            if relative.parts[:2] in (('frontend','bin'),('frontend','obj')):
                continue
            if relative.parts[:2]==('tests','fixtures') and path.suffix in ('.png','.json'):
                continue
            if path.is_symlink():
                raise SystemExit('Symlink is not permitted in release: '+str(relative))
            archive.write(path,relative.as_posix())
    print(target.name,round(target.stat().st_size/1024**2,1),'MiB')


if __name__=='__main__':
    build()
