"""No emulator access: verify the new worker cancellation and manifest contract."""
import io
import json
import threading
import os
import queue
import subprocess
import sys
import time
import pytest
from pathlib import Path
from chao2 import gui_worker
from chao2.workflows import TASKS, ORDER
from chao2.configuration import SPECS

def test_stop_and_parent_eof(monkeypatch):
    stop = threading.Event()
    monkeypatch.setattr(gui_worker.sys, 'stdin', io.StringIO('{"command":"stop"}\n'))
    gui_worker.listen_stop(stop)
    assert stop.is_set()
    stop.clear()
    monkeypatch.setattr(gui_worker.sys, 'stdin', io.StringIO(''))
    gui_worker.listen_stop(stop)
    assert stop.is_set(), 'A disappearing frontend must cancel game input'

def test_prefixed_json_unicode_and_newlines(monkeypatch):
    output = io.StringIO()
    monkeypatch.setattr(gui_worker.sys, '__stdout__', output)
    gui_worker.send('log', '中文\n第二行')
    lines = output.getvalue().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0][len(gui_worker.PREFIX):]) == {'kind': 'log', 'data': '中文\n第二行'}

def test_frontend_manifest_matches_real_tasks():
    tasks = json.loads((Path(__file__).resolve().parents[1] / 'frontend/tasks.json').read_text('utf-8'))
    assert tasks == [{'key': k, 'name': TASKS[k][0], 'description': TASKS[k][1], 'settings': SPECS[k]} for k in ORDER]
    assert all(callable(getattr(__import__('chao2.workflows',fromlist=['Daily']).Daily,k,None)) for k in ORDER if k!='finish')
    assert ORDER[-1]=='finish'  # Post-report action, never a normal navigation task.

@pytest.mark.parametrize('reserved',[False,True])
def test_real_worker_initializes_and_reports_error_while_stdin_remains_open(tmp_path,reserved):
    """Regress the Windows NumPy-import/stdin-listener deadlock; no ADB exists here."""
    root=Path(__file__).resolve().parents[1]
    # An offline initialization check must not share the real MuMu control
    # lease. The missing executable prevents any ADB connection or input.
    request={'mode':'diagnostic','settings':{'adb':str(tmp_path/'missing-adb.exe'),
             'address':'offline-gui-bridge:'+tmp_path.name},'selected':[]}
    environment={**os.environ,'PYTHONUTF8':'1','CHAO2_REPORT_ROOT':str(tmp_path/'reports')}
    if reserved:
        folder=tmp_path/'reports'/'2026_10_26_04_04_54';folder.mkdir(parents=True)
        (folder/'report.json').write_text(json.dumps({'status':'starting','session_token':'test-session',
            'started':'2026-10-26T04:04:54.1234567+08:00','folder':str(folder)}))
        environment.update(CHAO2_REPORT_FOLDER=str(folder),CHAO2_RUN_TOKEN='test-session')
    child=subprocess.Popen([sys.executable,'-u','-m','chao2.gui_worker'],cwd=root,
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',
        env=environment,creationflags=subprocess.CREATE_NO_WINDOW)
    lines=queue.Queue();errors=[];events=[]
    def read_output():
        for line in child.stdout:
            if line.startswith(gui_worker.PREFIX):lines.put(json.loads(line[len(gui_worker.PREFIX):]))
    def read_errors():errors.extend(child.stderr.readlines())
    threading.Thread(target=read_output,daemon=True).start()
    threading.Thread(target=read_errors,daemon=True).start()
    try:
        child.stdin.write(json.dumps(request)+'\n');child.stdin.flush()
        until=time.monotonic()+15
        while time.monotonic()<until:
            try:event=lines.get(timeout=.1)
            except queue.Empty:continue
            events.append(event)
            if event['kind']=='result':break
        else:pytest.fail('Real worker stalled with open stdin: '+''.join(errors))
        assert events[0]['kind']=='log' and '初始化' in events[0]['data'],events
        assert any(e['kind']=='log' and e['data']=='识图组件已就绪' for e in events)
        assert any(e['kind']=='phase' and '连接 MuMu' in e['data'] for e in events)
        assert events[-1]['data']['status']=='blocked'
        assert events[-1]['data']['tasks']=={}
        child.wait(timeout=5)
        records=list((tmp_path/'reports').iterdir())
        assert len(records)==1 and records[0].is_dir()
        assert '-' not in records[0].name and '_' in records[0].name
        if reserved:assert records[0]==folder
        assert json.loads((records[0]/'report.json').read_text('utf-8'))['status']=='blocked'
    finally:
        child.stdin.close()
        if child.poll() is None:
            child.kill();child.wait(timeout=5)
