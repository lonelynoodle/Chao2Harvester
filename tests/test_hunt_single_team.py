"""Single-attempt hunt flow and migration; no device input."""
from copy import deepcopy

import pytest

from chao2.activities import BudgetReached
from chao2.configuration import normalize_settings, team_order
from chao2.policy import FightLost, SafetyStop, TaskBlocked, UserStopped
from test_configuration import daily, screen


@pytest.mark.parametrize('saved,expected',[
    ({'teams':[3,2], 'max_runs':1}, '3'),
    ({'teams':[{'id':'1','enabled':False},{'id':'4','enabled':True}]}, '4'),
    ({'teams':[]}, '2'),
    ({}, '2'),
    ({'team':'5','teams':[2],'max_runs':2}, '5'),
])
def test_legacy_hunt_keeps_first_selected_team_without_challenge_limit(saved,expected):
    raw={'task_options':{'hunt':saved,'main':{'teams':[1,2,3],'max_runs':4}},
         'tasks':['hunt','forest'],'max_battles':50}
    original=deepcopy(raw)
    new=normalize_settings(raw)
    hunt=new['task_options']['hunt']
    assert hunt['team']==expected and team_order(hunt)==[int(expected)]
    assert 'teams' not in hunt and 'max_runs' not in hunt
    assert new['task_options']['main']['teams']==[1,2,3]
    assert new['task_options']['main']['max_runs']==4
    assert new['tasks']==raw['tasks'] and 'max_battles' not in new
    assert normalize_settings(new)==new and raw==original


@pytest.mark.parametrize('team',['0','6','',2,True,['2']])
def test_hunt_rejects_invalid_single_team(team):
    with pytest.raises(ValueError,match='hunt.team'):
        normalize_settings({'task_options':{'hunt':{'team':team}}})


def hunt_menu(count):
    words=[('狩猎',970,19,63,39),('商店',1074,95,48,26),
           ('传送',1218,340,48,30),('100/166',502,17,78,22)]
    words.extend(('10',1084,230+i*110,24,18) for i in range(count))
    if not count:words.append(('猎物未出现',946,435,114,24))
    return screen(*words)


def hunt_game(tmp_path,stale=False):
    d=daily(tmp_path,{'task_options':{'hunt':{'teams':[3,2], 'max_runs':1}}})
    remaining=['甲','乙'];teams=[];opened=[]
    d.hunt_menu=lambda:hunt_menu(2 if stale else len(remaining))
    d.b.read_number=lambda *a:0
    d.b.sleep=lambda _:None
    d.home=lambda:None
    def open_hunter(s,point,*a):
        # Both victory and defeat remove the top card; next target is still top.
        assert point==(1000,204)
        opened.append(remaining[0])
    d.b.click_at=open_hunter
    d.await_detail=lambda **_:screen(
        ('敌方阵容',1130,135,103,28),('排阵',824,614,61,34),
        ('前往挑战',1036,607,109,28),(remaining[0],134,136,58,30),
        ('09:35',602,135,72,26),('10',1096,639,28,18),('100/166',1185,17,76,22))
    d.ensure_detail=lambda s:s
    def select_team(s,team):teams.append(team);return s
    d.select_team=select_team
    d.b.click_text=lambda *a:None
    def battle(resource):
        assert resource=='地图体力10'
        d.battles+=1;d.task_counts['hunt']=d.task_counts.get('hunt',0)+1
        hunter=remaining.pop(0)
        if hunter=='甲':raise FightLost(screen(('失败',50,100,100,50)))
        return screen(('胜利',50,100,100,50))
    d.battle=battle;d.exit_result=lambda s:None
    d.start_challenge=lambda *a:None
    return d,teams,opened


def test_defeated_hunter_is_not_retried_or_skipped_over_next_card(tmp_path):
    d,teams,opened=hunt_game(tmp_path)
    result=d.hunt()
    assert opened==['甲','乙'] and teams==[3,3]
    assert d.task_counts['hunt']==2 # Old per-hunt max_runs=1 no longer applies.
    assert [r['outcome'] for r in d.report['team_attempts']]==['failed','victory']
    assert '通关1次，未通过1个猎物' in result and '狩猎令已用完' in result


def test_stale_settled_hunter_is_only_observed_not_challenged_again(tmp_path):
    d,teams,opened=hunt_game(tmp_path,stale=True)
    with pytest.raises(SafetyStop,match='列表重读3次'):
        d.hunt()
    assert opened==['甲'] and teams==[3] and d.task_counts['hunt']==1
    assert (tmp_path/'hunt-list-not-refreshed.png').exists()


def test_delayed_hunter_disappearance_can_recover_on_third_reread(tmp_path):
    d=daily(tmp_path);frames=iter([hunt_menu(2),hunt_menu(2),hunt_menu(2),hunt_menu(1)])
    sleeps=[];d.hunt_menu=lambda:next(frames);d.b.sleep=sleeps.append
    result=d.wait_hunter_removed(2)
    assert result.find('10') and len(sleeps)==3


def test_unreadable_empty_list_is_not_treated_as_confirmed_disappearance(tmp_path):
    d=daily(tmp_path);d.hunt_menu=lambda:screen();d.b.sleep=lambda _:None
    with pytest.raises(TaskBlocked,match='未确认减少'):
        d.wait_hunter_removed(1)


def test_hunt_still_obeys_global_budget_and_stop(tmp_path):
    d=daily(tmp_path);d.battles=d.limit
    with pytest.raises(BudgetReached,match='本轮战斗上限'):d.check_budget('hunt')
    def stop():raise UserStopped('用户停止')
    d.b.check_stop=stop
    d.hunt_menu=lambda:pytest.fail('Stopped before observing')
    with pytest.raises(UserStopped):d.wait_hunter_removed(2)


def test_refill_resumes_single_team_hunt_without_old_cap_key(tmp_path):
    d=daily(tmp_path);d.selected=['hunt'];balance=[0];calls=[]
    d.home=lambda:screen()
    d.world_resources=lambda _:{'stamina':balance[0],'stamina_cap':166}
    d.hunt_menu=lambda:hunt_menu(1)
    d.stamina_offer=lambda:screen(('领取奖励',650,590,120,35))
    d.b.click_text=lambda *a,**kw:balance.__setitem__(0,balance[0]+100)
    d.observe=lambda:screen()
    def run(task):calls.append(task);balance[0]-=10
    d.execute_task=run
    d.replenish_stamina()
    assert calls==['hunt'] and balance[0]==90 and d.report['stamina_claims']==1
    assert 'max_runs' not in d.options['hunt']


@pytest.mark.parametrize('balance',[10,20,100])
def test_hunt_does_not_probe_or_claim_when_stamina_is_sufficient(tmp_path,balance):
    d=daily(tmp_path);d.selected=['hunt']
    d.home=lambda:screen()
    d.world_resources=lambda _:{'stamina':balance,'stamina_cap':166}
    d.hunt_menu=lambda:pytest.fail('Enough stamina: no target check needed')
    d.stamina_offer=lambda:pytest.fail('Enough stamina: must not open free offer')
    d.replenish_stamina()
    assert d.report['stamina_refill']['claimed']==0
