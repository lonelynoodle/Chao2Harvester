"""Copy the active Windows Python and required packages into a portable runtime."""
from importlib import metadata
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'runtime' / 'python'
PACKAGES = ('MaaAgentBinary', 'MaaFw', 'numpy', 'opencv-python-headless', 'pillow', 'StrEnum')


def build():
    if sys.platform != 'win32':
        raise SystemExit('Build the Windows release on Windows.')
    if DEST.exists():
        raise SystemExit('runtime/python already exists; use an empty destination for a new build.')
    base = Path(sys.base_prefix)
    DEST.mkdir(parents=True)
    excluded = shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo', 'site-packages', 'test', 'tests')
    for name in ('Lib', 'DLLs'):
        shutil.copytree(base / name, DEST / name, ignore=excluded)
    for name in ('python.exe', 'pythonw.exe', 'python3.dll', 'python312.dll',
                 'vcruntime140.dll', 'vcruntime140_1.dll', 'LICENSE.txt'):
        shutil.copy2(base / name, DEST / name)
    site = DEST / 'Lib' / 'site-packages'
    site.mkdir()
    for name in PACKAGES:
        dist = metadata.distribution(name)
        source_site = Path(dist.locate_file('')).resolve()
        roots = {str(f).replace('\\', '/').split('/')[0] for f in dist.files or ()}
        for item in sorted(roots):
            if item in ('..', '.', ''):
                continue
            source = source_site / item
            target = site / item
            if target.exists():
                continue
            if source.is_dir():
                shutil.copytree(source, target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
            elif source.is_file():
                shutil.copy2(source, target)
        print(f'{name} {dist.version}')
    print('Portable Python ready: runtime/python/python.exe')


if __name__ == '__main__':
    build()
