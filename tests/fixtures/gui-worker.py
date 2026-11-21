"""Offline subprocess fixture for the WPF bridge smoke check. Never imports Maa/ADB."""
import json
import sys
import time
sys.stdin.reconfigure(encoding='utf-8')
sys.stdout.reconfigure(encoding='utf-8')
request = json.loads(sys.stdin.readline())
def emit(kind, data):
    print('@chao2@' + json.dumps({'kind': kind, 'data': data}, ensure_ascii=False), flush=True)
emit('log','正在连接 MuMu…')
emit('phase','正在连接 MuMu')
if request['settings'].get('_smoke_stall'):
    time.sleep(30)  # The WPF watchdog must terminate only this fixture process.
    raise SystemExit(4)
if request['mode']=='abyss':
    assert request['settings']['abyss_options']['teams']==[1,2,3]
    emit('log','深渊先遣：已选择压制词缀')
    emit('result',{'status':'completed','reason':'离线先遣桥接验证完成'})
elif request['mode']=='tour':
    emit('log','幻境巡游完成：已检查6个环境')
    emit('result',{'status':'completed','reason':'离线巡游完成验证'})
elif request['mode']=='puzzle':
    emit('puzzle',{'board':[8,4,2,4,2,0,0,0,2],'score':24,'moves':10,'max_tile':8})
    emit('log','拼二第10步：向左；得分24')
    emit('result',{'status':'completed','reason':'离线拼二反馈验证'})
elif request['mode'] == 'diagnostic':
    emit('result', {'status': 'diagnostic', 'resources_start': {'stamina': 7, 'stamina_cap': 161, 'diamonds': 2125, 'gold_text': '540万'}})
elif request.get('only_task') is not None:
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
    from chao2.gui_worker import prepare_run_request
    from chao2.configuration import normalize_settings
    from chao2.task_queue import execution_entries
    scoped,selected=prepare_run_request(request)
    entries=execution_entries(normalize_settings(scoped),selected,[])
    assert [row['id'] for row in entries]==[request['settings']['_smoke_expected_single_task']]
    emit('log','离线单条队列已核对：'+entries[0]['id'])
    time.sleep(.3)
    emit('result',{'status':'completed','queue_plan':entries,'plan':selected})
elif request.get('start_from') is not None:
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
    from chao2.gui_worker import prepare_run_request
    from chao2.configuration import normalize_settings
    from chao2.task_queue import execution_entries
    scoped,selected=prepare_run_request(request)
    entries=execution_entries(normalize_settings(scoped),selected,[])
    ids=[row['id'] for row in entries]
    assert ids==request['settings']['_smoke_expected_suffix'],ids
    assert scoped['unordered_tasks'] is False
    emit('log','离线续跑队列已核对：'+','.join(ids))
    time.sleep(.3)
    emit('result',{'status':'completed','queue_plan':entries,'plan':selected})
else:
    emit('phase','正在执行：任务领奖')
    emit('task', ['rewards', '运行中'])
    command = json.loads(sys.stdin.readline())
    assert command['command'] == 'stop'
    emit('result', {'status': 'stopped'})
