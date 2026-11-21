"""One OS-owned game-control lease shared by CLI, frontend and all tools."""
import hashlib
import json
import os
from pathlib import Path
import tempfile


class RunAlreadyActive(RuntimeError):
    pass


_active={}


class GameRunLease:
    def __init__(self,settings,*,lock_dir=None):
        address=str(settings.get('address','127.0.0.1:16384')).strip().lower().replace('localhost:','127.0.0.1:')
        key=hashlib.sha256(address.encode()).hexdigest()[:20]
        self.directory=Path(lock_dir) if lock_dir is not None else Path(tempfile.gettempdir())/'Chao2Harvester'
        self.path=self.directory/('game-'+key+'.lock');self.owner=self.path.with_suffix('.json')
        self.address=address;self.handle=None

    def busy(self):
        try:pid=json.loads(self.owner.read_text('utf-8')).get('pid')
        except (OSError,ValueError):pid=None
        return RunAlreadyActive('已有脚本正在控制当前MuMu'+(f'（PID {pid}）' if pid else '')+'，请先停止该脚本；本次未启动第二个实例')

    def __enter__(self):
        self.directory.mkdir(parents=True,exist_ok=True)
        if str(self.path) in _active:raise self.busy()
        handle=self.path.open('a+b',buffering=0)
        try:
            if self.path.stat().st_size==0:handle.write(b'0')
            handle.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            handle.close();raise self.busy() from None
        self.handle=handle;_active[str(self.path)]=self
        try:self.owner.write_text(json.dumps({'pid':os.getpid(),'address':self.address}),encoding='utf-8')
        except Exception:self.close();raise
        return self

    def close(self):
        if self.handle is None:return
        handle=self.handle;self.handle=None
        try:
            self.owner.unlink(missing_ok=True)
            handle.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
        finally:
            handle.close();_active.pop(str(self.path),None)

    def __exit__(self,*args):self.close()
