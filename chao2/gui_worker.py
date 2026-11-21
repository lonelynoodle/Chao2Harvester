"""WPF stdio bridge. Opening the UI does not create a backend or touch the game."""
from __future__ import annotations
import contextlib
import json
import sys
import threading

PREFIX = '@chao2@'

def send(kind, data):
    # Native Maa output may share stdout; the prefix distinguishes bridge events.
    sys.__stdout__.write(PREFIX + json.dumps({'kind': kind, 'data': data}, ensure_ascii=False, default=str) + '\n')
    sys.__stdout__.flush()

def listen_stop(stop):
    for line in sys.stdin:
        try:
            if json.loads(line).get('command') == 'stop':
                stop.set()
        except (ValueError, AttributeError):
            pass
    # Parent exit or a broken pipe must not leave game input running.
    stop.set()

def prepare_run_request(request):
    settings=request['settings']
    selected=request.get('selected',[])
    if request.get('only_task') is not None:
        if request.get('mode')!='run':raise ValueError('只有任务执行支持仅运行本条')
        if request.get('start_from') is not None:raise ValueError('仅运行本条与从此任务开始不能同时指定')
        from .task_queue import single_task_request
        return single_task_request(settings,request['only_task'])
    if request.get('start_from') is not None:
        if request.get('mode')!='run':
            raise ValueError('只有任务执行支持从此任务开始')
        from .task_queue import continuation_request
        return continuation_request(settings,selected,request['start_from'])
    return settings,selected


def main():
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    request = json.loads(sys.stdin.readline())
    stop = threading.Event()
    mode = request.get('mode')
    if mode not in ('run', 'diagnostic', 'launch', 'puzzle', 'tour', 'abyss'):
        raise ValueError('无效运行模式')
    settings,selected=prepare_run_request(request)
    from .run_lock import GameRunLease
    with GameRunLease(settings):
        return execute_request(mode,settings,selected,stop)


def execute_request(mode,settings,selected,stop):
    # Imported only after an explicit request; native logs go to stderr.
    send('log','正在初始化识图组件…')
    send('phase','正在初始化识图组件')
    with contextlib.redirect_stdout(sys.stderr):
        from .backend import Backend
        from .workflows import run_daily, TASKS, create_report, write_report
        from .puzzle import run_puzzle
        from .tour import run_tour
        from .abyss import run_abyss
        # On Windows, importing NumPy's native DLL while another thread blocks
        # in stdin can deadlock DLL initialization. Import before starting the
        # cancellation listener; queued stop/EOF still cancels subsequent input.
        threading.Thread(target=listen_stop, args=(stop,), daemon=True).start()
        send('log','识图组件已就绪')
        if any(k not in TASKS for k in selected):
            raise ValueError('未知任务')
        log = lambda msg: send('log', str(msg))
        if mode == 'abyss':
            result=run_abyss(settings,stop,log,lambda kind,data:send(kind,data))
        elif mode == 'tour':
            result=run_tour(settings,stop,log,lambda kind,data:send(kind,data))
        elif mode == 'puzzle':
            result=run_puzzle(settings,stop,log,lambda kind,data:send(kind,data))
        elif mode == 'launch':
            result=create_report()
            send('phase','正在打开超二')
            Backend(settings, stop, log).launch_game()
            result['status']='launched';write_report(result)
        else:
            result = run_daily(settings, selected, stop, log,
                               lambda kind, data: send(kind, data),
                               diagnostic=mode == 'diagnostic')
        send('result', result)

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        send('result', {'status': 'blocked', 'reason': str(exc)})
        raise
