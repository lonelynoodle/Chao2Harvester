"""Five complete runs, one timestamped directory per run."""
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

REPORT_LIMIT=5
RUN_NAME=re.compile(r'^(?:\d{8}-\d{6}(?:-\d{3})?|\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2}(?:_\d{3})?)$')


def run_order(name):
    if not RUN_NAME.fullmatch(name):return None
    old='-' in name;base_length=15 if old else 19
    try:
        date=datetime.strptime(name[:base_length],'%Y%m%d-%H%M%S' if old else '%Y_%m_%d_%H_%M_%S')
        suffix=int(name[base_length+1:]) if len(name)>base_length else 0
        return date,suffix
    except ValueError:return None


def report_folders(root):
    root=Path(root).resolve()
    if not root.exists():return []
    return sorted((p for p in root.iterdir() if run_order(p.name) is not None
                   and p.is_dir() and not p.is_symlink() and not p.is_junction()
                   and p.resolve().parent==root and (p/'report.json').is_file()),
                  key=lambda p:run_order(p.name),reverse=True)


def reserve_report(root,now):
    """CLI runs reserve a new directory; the GUI may reserve before Python starts."""
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    reserved=os.environ.get('CHAO2_REPORT_FOLDER')
    if reserved:
        folder=Path(reserved)
        if (folder.is_symlink() or folder.is_junction() or folder.resolve().parent!=root or
                run_order(folder.name) is None):
            raise ValueError('前端运行记录路径无效')
        saved=json.loads((folder/'report.json').read_text('utf-8'))
        token=os.environ.get('CHAO2_RUN_TOKEN')
        if saved.get('status')!='starting' or not token or saved.get('session_token')!=token:
            raise ValueError('运行记录已被使用或不属于本次启动，未覆盖')
        return folder.resolve(),saved['started']
    stamp=now.strftime('%Y_%m_%d_%H_%M_%S')
    siblings=[run_order(p.name) for p in root.iterdir() if run_order(p.name) is not None]
    date=now.replace(tzinfo=None,microsecond=0)
    first=max((suffix for started,suffix in siblings if started==date),default=-1)+1
    for suffix in range(first,1000):
        folder=root/(stamp+(f'_{suffix:03}' if suffix else ''))
        try:folder.mkdir();return folder,now.isoformat()
        except FileExistsError:continue
    raise RuntimeError('无法创建唯一的运行记录目录')


def prune_reports(root,keep=REPORT_LIMIT):
    """Revalidate each absolute directory immediately before its recursive delete."""
    if not isinstance(keep,int) or isinstance(keep,bool) or keep<1:raise ValueError('至少保留一次运行记录')
    root=Path(root).resolve();removed=[];errors=[]
    for path in report_folders(root)[keep:]:
        try:
            if path.is_symlink() or path.is_junction() or path.resolve().parent!=root:
                raise ValueError('运行记录路径已改变，未清理')
            if not RUN_NAME.fullmatch(path.name) or not (path/'report.json').is_file():
                raise ValueError('运行记录目录未确认，未清理')
            shutil.rmtree(path)
            removed.append(path.name)
        except (OSError,ValueError) as exc:
            errors.append(f'{path.name}：{exc}')
    return {'removed':removed,'errors':errors}
