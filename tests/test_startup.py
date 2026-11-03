"""Title-entry transitions and task ordering; these tests never connect to MuMu."""
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

import chao2.workflows as flow
from chao2.backend import Backend, Screen, Word
from chao2.policy import SafetyStop, TaskBlocked, UserStopped

TITLE = [('进入游戏',584,602,112,31)]
WORLD = [('任务挑战',1190,40,80,24),('世界回响',1190,130,80,24),('37/161',520,12,70,26)]

def screen(words):
    return Screen(np.zeros((720,1280,3),np.uint8),[Word(t,[x,y,w,h],.99) for t,x,y,w,h in words],time.monotonic())

def routine(tmp_path,monkeypatch,frames):
    clock=[0.0];index=[0];clicks=[]
    monkeypatch.setattr(time,'monotonic',lambda:clock[0])
    b=Backend({},log=lambda _:None)
    d=flow.Daily(b,{'folder':tmp_path,'tasks':{},'events':[]})
    d.state_file=tmp_path/'state.json'
    d.observe=lambda *a:screen(frames[min(index[0],len(frames)-1)])
    def sleep(seconds):clock[0]+=seconds;index[0]+=1
    b.sleep=sleep
    b.click_text=lambda s,p,roi=None:clicks.append(s.find(p,roi).text)
    b.click_at=lambda *a:clicks.append('navigate')
    return d,clicks

def test_title_clicks_once_through_loading_and_confirms_world(tmp_path,monkeypatch):
    d,clicks=routine(tmp_path,monkeypatch,[TITLE,TITLE,[],TITLE,WORLD])
    assert '确认世界地图' in d.startup()
    assert clicks==['进入游戏']
    assert d.report['startup_entered'] is True

def test_already_in_world_needs_no_click(tmp_path,monkeypatch):
    d,clicks=routine(tmp_path,monkeypatch,[WORLD])
    assert '跳过' in d.startup()
    assert clicks==[] and d.report['startup_entered'] is False

def test_already_in_territory_uses_existing_navigation(tmp_path,monkeypatch):
    territory=[('永生之茧',860,200,100,30),('世界',1190,645,65,30)]
    d,clicks=routine(tmp_path,monkeypatch,[territory,WORLD])
    def click(s,p,roi=None):
        clicks.append(s.find(p,roi).text);d.b.sleep(2)
    d.b.click_text=click
    assert '跳过' in d.startup()
    assert clicks==['世界']

@pytest.mark.parametrize('frames,expected_clicks',[
    ([TITLE],['进入游戏']),
    ([[]],[]),
    ([[('进入游戏',20,80,112,31)]],[]),
])
def test_unconfirmed_entry_times_out_without_repeated_or_unrelated_clicks(tmp_path,monkeypatch,frames,expected_clicks):
    d,clicks=routine(tmp_path,monkeypatch,frames)
    with pytest.raises(TaskBlocked,match='60秒'):d.startup()
    assert clicks==expected_clicks
    assert 'startup_entered' not in d.report

@pytest.mark.parametrize('overlay',['请输入手机号','是否消耗25钻石购买体力？取消'])
def test_authentication_and_purchase_overlays_block_title_click(tmp_path,monkeypatch,overlay):
    d,clicks=routine(tmp_path,monkeypatch,[TITLE+[(overlay,400,300,400,30)]])
    with pytest.raises(SafetyStop):d.startup()
    assert clicks==[]

def test_stop_during_loading_does_not_click_again(tmp_path,monkeypatch):
    d,clicks=routine(tmp_path,monkeypatch,[TITLE])
    d.b.sleep=lambda _:d.b.stop.set()
    with pytest.raises(UserStopped):d.startup()
    assert clicks==['进入游戏']

def test_home_does_not_enter_game_when_startup_is_unselected(tmp_path,monkeypatch):
    d,clicks=routine(tmp_path,monkeypatch,[TITLE])
    with pytest.raises(TaskBlocked,match='勾选'):d.home()
    assert clicks==[]

def queue(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(flow.Backend,'connect',lambda b:setattr(b,'controller',SimpleNamespace(get_custom_info=lambda:{})))
    monkeypatch.setattr(flow,'create_report',lambda:{'folder':tmp_path,'tasks':{},'events':[]})
    monkeypatch.setattr(flow.Daily,'home',lambda _:calls.append('home') or screen(WORLD))
    monkeypatch.setattr(flow.Daily,'world_resources',lambda *_:{'diamonds':200})
    monkeypatch.setattr(flow.Daily,'restore_world_team',lambda _:None)
    monkeypatch.setattr(flow.Daily,'save_state',lambda _:None)
    for key in ('startup','rewards'):
        monkeypatch.setattr(flow.Daily,key,lambda self,key=key:calls.append(key) or 'done')
    return calls

def test_startup_runs_once_before_navigation_and_later_tasks(tmp_path,monkeypatch):
    calls=queue(tmp_path,monkeypatch)
    result=flow.run_daily({},['rewards','startup'],threading.Event(),log=lambda _:None)
    assert result['status']=='completed'
    assert result['plan']==['startup','rewards']
    assert calls==['startup','home','rewards','home']

def test_failed_startup_is_reported_and_stops_rest_of_queue(tmp_path,monkeypatch):
    calls=queue(tmp_path,monkeypatch)
    def fail(self):raise TaskBlocked('进入超时')
    monkeypatch.setattr(flow.Daily,'startup',fail)
    result=flow.run_daily({},['startup','rewards'],threading.Event(),log=lambda _:None)
    assert result['status']=='blocked' and result['tasks']['startup']['status']=='blocked'
    assert calls==[]

def test_diagnostic_stays_read_only_even_with_startup_selected(tmp_path,monkeypatch):
    calls=queue(tmp_path,monkeypatch)
    monkeypatch.setattr(flow.Daily,'observe',lambda *a,**kw:screen(TITLE))
    result=flow.run_daily({},['startup'],threading.Event(),log=lambda _:None,diagnostic=True)
    assert result['status']=='diagnostic' and result['tasks']=={}
    assert calls==[]


def test_failure_on_second_execution_cannot_retain_first_completed_status(tmp_path,monkeypatch):
    from chao2.policy import SafetyStop
    queue(tmp_path,monkeypatch)
    def rewards(self):
        self.task_counts['rewards']=self.task_counts.get('rewards',0)+1
        if self.task_counts['rewards']==2:raise SafetyStop('第二轮结算超时')
        return '第一轮完成'
    monkeypatch.setattr(flow.Daily,'rewards',rewards)
    import chao2.task_queue as queue_module
    monkeypatch.setattr(queue_module,'plan_tasks',lambda *a:['rewards','rewards'])
    result=flow.run_daily({},['rewards'],threading.Event(),log=lambda _:None)
    assert result['status']=='blocked'
    assert result['tasks']['rewards']['status']=='blocked'
    assert result['tasks']['rewards']['message']=='第二轮结算超时'
    assert result['tasks']['rewards']['attempts']==2
