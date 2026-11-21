"""Explicit unattended shutdown after a partial run requires a verified world."""
import json
import threading
import pytest
import chao2.workflows as flow
from chao2.policy import TaskBlocked,UserStopped
from test_configuration import screen
from test_task_interruptions_0985 import world


@pytest.mark.parametrize('allow,known,stopped,expected',[
    (False,True,False,False),(True,True,False,True),
    (True,False,False,False),(True,True,True,False)])
def test_partial_shutdown_is_explicit_safe_and_saves_first(tmp_path,monkeypatch,allow,known,stopped,expected):
    state={'ran':False};closes=[]
    monkeypatch.setattr(flow,'create_report',lambda:{'folder':tmp_path,'tasks':{},'events':[]})
    monkeypatch.setattr(flow.Backend,'connect',lambda _:None)
    monkeypatch.setattr(flow.Daily,'home',lambda _:world() if known or not state['ran'] else screen())
    monkeypatch.setattr(flow.Daily,'recover_failed_task',lambda _:world())
    monkeypatch.setattr(flow.Daily,'world_resources',lambda *_:{'stamina':0,'stamina_cap':166,'diamonds':300})
    monkeypatch.setattr(flow.Daily,'save_state',lambda _:None)
    def activity(self):
        state['ran']=True
        raise UserStopped('用户停止') if stopped else TaskBlocked('当前任务无法完成')
    monkeypatch.setattr(flow.Daily,'exploration',activity)
    def close(*a):
        saved=json.loads((tmp_path/'report.json').read_text('utf-8'))
        assert saved['status']=='partial' and saved['resources_end']['diamonds']==300
        closes.append('closed');return True
    monkeypatch.setattr(flow,'close_game_and_mumu',close)
    settings={'task_options':{'finish':{'close_on_partial':allow,'close_mumu':True,'close_app':True}}}
    report=flow.run_daily(settings,['exploration','finish'],threading.Event(),log=lambda _:None)
    assert bool(closes)==expected and bool(report.get('close_app_requested'))==expected
    assert report['status']==('stopped' if stopped else 'partial')
