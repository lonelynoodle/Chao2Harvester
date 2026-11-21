"""Real startup failure and generic existing-battle takeover; no device input."""
import threading
import time
from types import SimpleNamespace

import pytest

from test_configuration import captured,daily,screen
from chao2.battle_takeover import takeover_phase,existing_result
from chao2.triad import is_triad_battle
from chao2.policy import TaskBlocked,UserStopped
from chao2.workflows import is_world


def tower():return captured('v0947-startup-tower-battle',True)
def world():return captured('v0913-main-world',True)
def victory():return captured('v0937-tower-400-result',True)


def test_reported_native_tower_fight_is_not_a_triad_match():
    s=tower()
    assert takeover_phase(s)=='battle' and not is_triad_battle(s)


@pytest.mark.parametrize('fixture,phase',[
    ('v0947-startup-tower-battle','battle'),
    ('v0942-triad-battle2','battle'),('v0942-triad-battle3','battle'),
    ('v0942-triad-battle5','battle'),('v0914-origin-matching','matching'),
    ('v0919-rank-demotion','rank'),('v076-origin-failed','result'),
    ('v0942-triad-victory','result'),('v0944-totem-score','tribe_score'),
    ('v0944-totem-reward','result'),('v084-rift-victory24','result'),
    ('rampage-result','result'),('v092-main-failed594','result'),
    ('v0946-main-blocked',None),('v0944-totem-detail',None),
    ('v0946-tower-blocked',None),('v0913-main-world',None),
    ('v0946-star_spores-blocked',None),('origin-menu',None),
    ('rampage-progress','rampage_buff'),
])
def test_captured_phases_do_not_confuse_ready_pages_with_combat(fixture,phase):
    assert takeover_phase(captured(fixture,True))==phase


def simulation(tmp_path,frames):
    d=daily(tmp_path);pages=iter(frames);g={'page':frames[0],'clicks':[],'reads':0}
    def observe(*args,**kwargs):
        g['page']=next(pages,g['page']);g['page'].when=time.monotonic();g['reads']+=1
        return g['page']
    d.observe=observe;d.b.sleep=lambda _:None
    def exit_result(s):
        assert existing_result(s)
        g['clicks'].append('退出');g['page']=world();return g['page']
    d.exit_result=exit_result
    d.b.click_at=lambda *a,**k:pytest.fail('No combat input before actual settlement')
    d.b.click_text=lambda *a,**k:pytest.fail('No retreat, rematch, team or purchase input')
    return d,g


def test_waits_through_combat_and_loading_then_exits_only_the_settled_fight(tmp_path):
    d,g=simulation(tmp_path,[tower(),screen(),tower(),victory()])
    assert is_world(d.finish_existing_battle(tower()))
    assert g['reads']==4 and g['clicks']==['退出']
    row=d.report['battle_takeovers'][0]
    assert row['status']=='settled' and row['result']=='victory'
    assert '浮空巨塔' in row['label'] and '三阵' not in row['label']
    assert row['resource_spend'] is None and not row['counted_as_task_attempt']
    assert d.battles==0 and d.task_counts=={} and not d.report.get('team_attempts')


def test_startup_can_wait_beyond_login_timeout_then_continue(tmp_path,monkeypatch):
    import chao2.workflows as flow
    d,g=simulation(tmp_path,[tower(),tower(),victory()]);clock=[0]
    # Use a local module proxy rather than changing captured timestamps.
    monkeypatch.setattr(flow,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    d.b.sleep=lambda seconds:clock.__setitem__(0,clock[0]+65)
    assert '跳过' in d.startup()
    assert clock[0]>60 and g['clicks']==['退出']
    assert d.report['startup_entered'] is False


def test_matching_waits_for_result_without_cancelling_or_assuming_origin(tmp_path):
    matching=captured('v0914-origin-matching',True)
    d,g=simulation(tmp_path,[matching,tower(),victory()])
    d.finish_existing_battle(matching)
    assert g['clicks']==['退出'] and d.task_counts=={}
    assert d.report['battle_takeovers'][0]['label']=='已有战斗'


def test_already_closed_result_is_not_fabricated_as_victory(tmp_path):
    d,g=simulation(tmp_path,[screen(),world()])
    assert is_world(d.finish_existing_battle(tower()))
    row=d.report['battle_takeovers'][0]
    assert row['status']=='returned_without_result' and 'result' not in row
    assert g['clicks']==[]


def test_stop_during_wait_remains_responsive_without_game_input(tmp_path):
    d,g=simulation(tmp_path,[tower()]);d.b.sleep=lambda _:d.b.stop.set()
    with pytest.raises(UserStopped):d.finish_existing_battle(tower())
    assert g['clicks']==[] and d.report['battle_takeovers'][0]['status']=='stopped'


def test_long_battle_keeps_waiting_without_retreat(tmp_path,monkeypatch):
    import chao2.battle_takeover as module
    d,g=simulation(tmp_path,[tower() for _ in range(16)]+[victory()]);clock=[0]
    monkeypatch.setattr(module,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    d.b.sleep=lambda seconds:clock.__setitem__(0,clock[0]+60)
    d.finish_existing_battle(tower())
    assert clock[0]>720 and g['clicks']==['退出']
    assert d.report['battle_takeovers'][0]['status']=='settled'
    assert d.report['battle_wait_extensions']
    assert any('等待结束' in row['message'] for row in d.report['events'])


def test_home_can_recover_existing_combat_without_startup_task(tmp_path):
    d,g=simulation(tmp_path,[tower(),victory()])
    assert is_world(d.home(tower())) and g['clicks']==['退出']


def test_rank_notice_then_defeat_is_closed_without_rematching(tmp_path):
    rank=captured('v0919-rank-demotion',True);failed=captured('v076-origin-failed',True)
    d,g=simulation(tmp_path,[failed]);d.b.click_at=lambda s,p,a,r:g['clicks'].append('段位关闭')
    assert is_world(d.finish_existing_battle(rank))
    assert g['clicks']==['段位关闭','退出']
    assert d.report['battle_takeovers'][0]['result']=='failed'


def test_tribe_damage_reveal_continues_to_reward_then_exits(tmp_path):
    score=captured('v0944-totem-score',True);reward=captured('v0944-totem-reward',True)
    d,g=simulation(tmp_path,[reward])
    d.b.click_at=lambda s,p,a,r:g['clicks'].append('成绩继续')
    assert is_world(d.finish_existing_battle(score))
    assert g['clicks']==['成绩继续','退出']


def test_triad_next_round_can_continue_without_starting_new_match(tmp_path):
    next_round=screen(('下一阵',1060,580,100,40))
    d,g=simulation(tmp_path,[captured('v0942-triad-battle3',True),captured('v0942-triad-victory',True)])
    d.b.click_at=lambda s,p,a,r:g['clicks'].append('下一阵')
    d.finish_existing_battle(next_round)
    assert g['clicks']==['下一阵','退出'] and d.battles==0


def test_rampage_buff_uses_saved_priority_then_waits_for_actual_result(tmp_path):
    from chao2.daily_challenges import rampage_buff
    buff=captured('rampage-progress',True)
    d,g=simulation(tmp_path,[tower(),captured('rampage-result',True)])
    expected,_=rampage_buff(buff,d.options['nest']['buff_priority'])
    def click(s,p,a,r):
        assert p==expected.center and s.has(*a)
        g['clicks'].append('增益')
    d.b.click_at=click
    d.finish_existing_battle(buff)
    assert g['clicks']==['增益','退出'] and d.battles==0


def test_paused_battle_is_resumed_instead_of_retreating(tmp_path):
    paused=screen(('暂停',550,200,100,40),('继续战斗',530,370,150,40),('退出',530,460,150,40))
    assert takeover_phase(paused)=='paused'
    d,g=simulation(tmp_path,[tower(),victory()])
    d.b.click_at=lambda s,p,a,r:g['clicks'].append(s.find('^继续战斗$').text)
    d.finish_existing_battle(paused)
    assert g['clicks']==['继续战斗','退出']


@pytest.mark.parametrize('startup',[False,True])
def test_real_queue_waits_and_keeps_selected_task_order_even_with_origin_selected(tmp_path,monkeypatch,startup):
    import chao2.workflows as flow
    calls=[];frames=iter([tower(),tower(),screen(),victory()]);current=[world()]
    def observe(self,*a,**k):
        s=next(frames,current[0]);s.when=time.monotonic();return s
    monkeypatch.setattr(flow,'create_report',lambda:{'folder':tmp_path,'tasks':{},'events':[]})
    monkeypatch.setattr(flow,'origin_is_open',lambda:True)
    monkeypatch.setattr(flow.Backend,'connect',lambda _:None)
    monkeypatch.setattr(flow.Backend,'sleep',lambda *a:None)
    monkeypatch.setattr(flow.Daily,'observe',observe)
    def exit_result(self,s):
        assert existing_result(s);calls.append('existing_exit');return current[0]
    monkeypatch.setattr(flow.Daily,'exit_result',exit_result)
    for key in ('rewards','origin'):
        monkeypatch.setattr(flow.Daily,key,lambda self,key=key:calls.append(key) or 'done')
    monkeypatch.setattr(flow.Daily,'maybe_capture_wild',lambda d,s:s)
    monkeypatch.setattr(flow.Daily,'maybe_free_summon',lambda d,s:s)
    monkeypatch.setattr(flow.Daily,'restore_world_team',lambda d:None)
    monkeypatch.setattr(flow.Daily,'save_state',lambda d:None)
    selected=(['startup'] if startup else [])+['rewards','origin']
    report=flow.run_daily({'task_order':['startup','rewards','origin']},selected,threading.Event(),log=lambda _:None)
    assert report['status']=='completed'
    assert calls==['existing_exit','rewards','origin']
    assert report['battle_takeovers'][0]['status']=='settled'
    assert not report['attempt_counts']
