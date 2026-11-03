"""Compatibility launcher for the MAA-derived WPF frontend.

The frontend starts no game tasks until the user clicks a task action.
"""
from __future__ import annotations
import subprocess
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def frontend_executable(root=ROOT):
    current = root/'bin'/'Chao2Harvester.exe'
    if current.is_file():
        return current
    releases=[]
    for folder in root.glob('bin-v*'):
        match=re.fullmatch(r'bin-v(\d+)\.(\d+)\.(\d+)',folder.name)
        executable=folder/'Chao2Harvester.exe'
        if match and executable.is_file():
            releases.append((tuple(map(int,match.groups())),executable))
    return max(releases)[1] if releases else root/'bin'/'Chao2Harvester.exe'


def main():
    executable = frontend_executable()
    if not executable.is_file():
        raise FileNotFoundError('请先运行 build-frontend.ps1 构建 WPF 前端。')
    subprocess.Popen([str(executable)], cwd=ROOT, creationflags=subprocess.CREATE_NO_WINDOW)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
