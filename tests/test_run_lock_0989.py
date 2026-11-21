"""A live OS lease must reject overlapping frontend and CLI workers."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from chao2.run_lock import GameRunLease,RunAlreadyActive

ROOT=Path(__file__).resolve().parents[1]


def test_same_device_aliases_cannot_run_twice_and_release_after_exit(tmp_path):
    with GameRunLease({'address':'LOCALHOST:16384'},lock_dir=tmp_path) as first:
        with pytest.raises(RunAlreadyActive,match=str(os.getpid())):
            with GameRunLease({'address':'127.0.0.1:16384'},lock_dir=tmp_path):pass
        assert first.handle is not None
    with GameRunLease({'address':'localhost:16384'},lock_dir=tmp_path):pass


def test_other_device_has_its_own_lease_and_exception_releases_owner(tmp_path):
    with pytest.raises(ValueError):
        with GameRunLease({'address':'a'},lock_dir=tmp_path):
            with GameRunLease({'address':'b'},lock_dir=tmp_path):pass
            raise ValueError('caller failed')
    with GameRunLease({'address':'a'},lock_dir=tmp_path):pass


def test_another_process_cannot_acquire_a_live_lease(tmp_path):
    code="""import sys
from chao2.run_lock import GameRunLease,RunAlreadyActive
try:
 with GameRunLease({'address':'test'},lock_dir=sys.argv[1]): print('BAD')
except RunAlreadyActive:
 print('blocked');sys.exit(7)
"""
    with GameRunLease({'address':'test'},lock_dir=tmp_path):
        child=subprocess.run([sys.executable,'-c',code,str(tmp_path)],cwd=ROOT,capture_output=True,text=True,timeout=10)
    assert child.returncode==7 and child.stdout.strip()=='blocked'


def test_killed_owner_does_not_leave_a_permanent_lock(tmp_path):
    code="""import sys
from chao2.run_lock import GameRunLease
with GameRunLease({'address':'test'},lock_dir=sys.argv[1]):
 print('ready',flush=True);sys.stdin.read(1)
"""
    child=subprocess.Popen([sys.executable,'-c',code,str(tmp_path)],cwd=ROOT,
                           stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    try:
        assert child.stdout.readline().strip()=='ready'
        with pytest.raises(RunAlreadyActive):
            with GameRunLease({'address':'test'},lock_dir=tmp_path):pass
        child.kill();child.wait(timeout=5)
        with GameRunLease({'address':'test'},lock_dir=tmp_path):pass
    finally:
        if child.poll() is None:child.kill();child.wait(timeout=5)
        child.stdin.close();child.stdout.close()


def test_real_frontend_worker_rejects_overlap_before_connecting_or_creating_report(tmp_path):
    settings={'address':'127.0.0.1:49987','adb':str(tmp_path/'missing-adb.exe')}
    request={'mode':'run','settings':settings,'selected':['tower']}
    environment={**os.environ,'PYTHONIOENCODING':'utf-8','CHAO2_REPORT_ROOT':str(tmp_path/'reports')}
    with GameRunLease(settings):
        child=subprocess.run([sys.executable,'-u','-m','chao2.gui_worker'],cwd=ROOT,
            input=json.dumps(request)+'\n',capture_output=True,text=True,encoding='utf-8',env=environment,timeout=10)
    events=[json.loads(line[len('@chao2@'):]) for line in child.stdout.splitlines() if line.startswith('@chao2@')]
    assert events[-1]['kind']=='result' and events[-1]['data']['status']=='blocked'
    assert '已有脚本' in events[-1]['data']['reason'] and not (tmp_path/'reports').exists()
    assert not any(event['kind']=='phase' and '连接' in event['data'] for event in events)


def test_real_cli_uses_the_same_lease_and_does_not_connect(tmp_path):
    settings={'address':'127.0.0.1:49988','adb':str(tmp_path/'missing-adb.exe'),'tasks':['tower']}
    (tmp_path/'config.json').write_text(json.dumps(settings),encoding='utf-8')
    code="""import sys
from pathlib import Path
import chao2.cli as cli
cli.ROOT=Path(sys.argv[1]);sys.argv=['cli','--run','tower'];raise SystemExit(cli.main())
"""
    with GameRunLease(settings):
        child=subprocess.run([sys.executable,'-u','-c',code,str(tmp_path)],cwd=ROOT,
                             capture_output=True,text=True,encoding='utf-8',env={**os.environ,'PYTHONIOENCODING':'utf-8'},timeout=15)
    assert child.returncode==2 and '已有脚本' in child.stdout and '连接 MuMu' not in child.stdout
