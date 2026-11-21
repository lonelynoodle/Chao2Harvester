"""Swallowed settlement inputs must not leave the third round disarmed."""
from types import SimpleNamespace
import pytest
from chao2.policy import SafetyStop,UserStopped
from chao2.triad import triad_round
from test_configuration import daily,screen
from test_triad import battle,lobby,result


def simulation(tmp_path,frames,enabled=True):
    d=daily(tmp_path);d.options['triad']['auto_settle']=enabled
    d.triad_lobby=lambda s=None:lobby(3)
    frames=iter(frames);d.observe=lambda:next(frames)
    d.b.sleep=lambda _:None;d.retry_battle_network=lambda *a:False
    d.b.read_text_crop=lambda *a:'';d.b.save_screen=lambda *a:None
    clicks=[];matches=[]
    d.b.click_text=lambda *a,**kw:matches.append('match')
    def click(s,point,anchors,reason):
        assert s.has(*anchors)
        assert point==s.find('^结算$',(130,555,120,100)).center
        clicks.append(s)
    d.b.click_at=click
    return d,clicks,matches


def test_third_round_retries_more_than_three_times_on_fresh_observations(tmp_path):
    frames=[battle(1),battle(2)]+[battle(3) for _ in range(12)]+[result()]
    d,clicks,matches=simulation(tmp_path,frames)
    _,outcome,count=d.triad_match(lobby(3))
    assert outcome=='victory' and count==14 and matches==['match']
    assert clicks==frames[:-1] and len({id(s) for s in clicks})==14
    assert [triad_round(s) for s in clicks]==['1','2']+['3']*12
    # Click retries are not extra matches or resource deductions.
    assert d.battles==0 and d.task_counts.get('triad',0)==0
    assert not d.report.get('resource_usage')


def test_button_disappears_and_reappears_without_readable_round(tmp_path):
    def unknown_round(settle):
        s=battle(3,settle)
        s.words=[w for w in s.words if w.text!='第3阵']
        return s
    a=unknown_round(True);gap=unknown_round(False);b=unknown_round(True)
    d,clicks,matches=simulation(tmp_path,[a,gap,b,result()])
    assert d.triad_match(lobby(3))[2]==2
    assert clicks==[a,b] and matches==['match']


def test_absent_control_or_nonbattle_text_is_never_reused_as_a_target(tmp_path):
    first=battle(3)
    d,clicks,_=simulation(tmp_path,[first,battle(3,False),
        screen(('结算',160,600,60,35)),screen(('结算',800,300,60,35)),result()])
    assert d.triad_match(lobby(3))[2]==1 and clicks==[first]


def test_disabled_auto_settlement_never_retries_visible_button(tmp_path):
    d,clicks,matches=simulation(tmp_path,[battle(3) for _ in range(12)]+[result()],False)
    assert d.triad_match(lobby(3))[2]==0
    assert not clicks and matches==['match']


def test_user_stop_interrupts_continuous_retry_before_another_click(tmp_path):
    d,clicks,_=simulation(tmp_path,[battle(3) for _ in range(10)])
    click=d.b.click_at
    def stop_after_two(*args):
        click(*args)
        if len(clicks)==2:d.b.stop.set()
    d.b.click_at=stop_after_two
    with pytest.raises(UserStopped):d.triad_match(lobby(3))
    assert len(clicks)==2


def test_continuous_retry_keeps_waiting_for_a_long_active_match(tmp_path,monkeypatch):
    d,clicks,_=simulation(tmp_path,[battle(3) for _ in range(40)]+[result()])
    d.b.settings['battle_timeout_seconds']=1
    ticks=iter(range(0,20000,25))
    monkeypatch.setattr('chao2.triad.time',SimpleNamespace(monotonic=lambda:next(ticks)))
    assert d.triad_match(lobby(3))[1]=='victory'
    assert len(clicks)==40 and d.battles==0 and d.report['battle_wait_extensions']


def test_retries_count_one_finished_match_and_one_free_attempt(tmp_path):
    d,clicks,matches=simulation(tmp_path,[battle(3) for _ in range(8)]+[result()])
    d.triad_lobby=lambda s=None:lobby(1-d.task_counts.get('triad',0))
    d.exit_result=lambda s:lobby(0);d.home=lambda:None
    assert '已完成1场' in d.triad()
    assert d.task_counts['triad']==1 and d.battles==1 and matches==['match']
    assert len(clicks)==8 and d.report['resource_usage']['triad']['免费匹配次数']['spent']==1
