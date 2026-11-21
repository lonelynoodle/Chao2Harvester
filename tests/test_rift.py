"""Rift highest-stage / fallback / chest accounting, using real captured UI."""
import pytest
from test_configuration import daily,screen,captured
from chao2.configuration import normalize_settings,plan_tasks
from chao2.workflows import ORDER
from chao2.policy import TaskBlocked,SafetyStop,FightLost
from chao2.activities import BudgetReached
from chao2.rift import (is_rift_map,rift_detail,is_rift_victory,rift_chest_keys,
                       rift_progress,rift_map_keys,verify_free_rift)


def test_defaults_preserve_existing_selection():
    s=normalize_settings({'tasks':['copies','cocoon']})
    assert s['tasks']==['copies','cocoon']
    assert s['task_options']['rift']=={'teams':[2,1],'wall_mode':'ignore','max_runs':0,'reserve_keys':0}
    assert plan_tasks(s,['rift'],ORDER)==['rift']


def test_captured_map_detail_and_chest_are_distinct():
    assert is_rift_map(captured('v084-rift-map23'))
    assert rift_detail(captured('v084-rift-detail24'))==24
    assert not is_rift_map(captured('v084-rift-detail24'))
    assert is_rift_victory(captured('v084-rift-victory24'))
    assert is_rift_victory(captured('v084-rift-reward24'))
    assert rift_chest_keys(captured('v084-rift-victory24'))==6
    assert rift_chest_keys(captured('v084-rift-reward24')) is None
    assert not is_rift_victory(captured('main-defeat'))


def test_highest_unlocked_next_is_chosen_before_cleared(tmp_path,monkeypatch):
    d=daily(tmp_path);opened=[]
    d.rift_locate=lambda s,n:(s,('next',(440,410)))
    d.rift_open_stage=lambda s,n:opened.append(n) or captured('v084-rift-detail24')
    _,stage=d.rift_highest(captured('v084-rift-map23'))
    assert stage==24 and opened==[24]


def test_locked_next_uses_highest_cleared_not_arbitrary_lower(tmp_path):
    d=daily(tmp_path);opened=[]
    d.rift_locate=lambda s,n:(s,('locked' if n==24 else 'open',(440,410)))
    d.rift_open_stage=lambda s,n:opened.append(n) or screen()
    _,stage=d.rift_highest(captured('v084-rift-map23'))
    assert stage==23 and opened==[23]


def test_missing_next_node_does_not_silently_downgrade(tmp_path):
    d=daily(tmp_path)
    def unknown(*_):raise TaskBlocked('节点未确认')
    d.rift_locate=unknown;d.rift_open_stage=lambda *_:pytest.fail('must not downgrade')
    with pytest.raises(TaskBlocked):d.rift_highest(captured('v084-rift-map23'))


def test_actual_level_gate_selects_24_and_never_challenges_25(tmp_path):
    d=daily(tmp_path);opened=[];menu=captured('v084-rift-map24')
    d.rift_locate=lambda s,n:(s,('next',(440,440)))
    d.rift_map=lambda:menu
    def open_stage(s,n):
        opened.append(n)
        return captured('v084-rift-detail25-locked' if n==25 else 'v084-rift-detail24')
    d.rift_open_stage=open_stage
    detail,stage=d.rift_highest(menu)
    assert stage==24 and opened==[25,24] and rift_detail(detail)==24
    with pytest.raises(TaskBlocked,match='等级'):
        verify_free_rift(d.b,captured('v084-rift-detail25-locked'),25)


def fake_rift(d,monkeypatch,keys=5,outcomes=(),advance=True):
    import chao2.rift as module
    state={'keys':keys,'stage':24,'teams':[],'opened':[],'claimed':[],'starts':0}
    result=iter(outcomes)
    d.rift_map=lambda:screen();d.rift_wait_map=lambda:screen();d.home=lambda:None
    monkeypatch.setattr(module,'rift_map_keys',lambda b,s:state['keys'])
    monkeypatch.setattr(module,'verify_free_rift',lambda *a:None)
    def highest(s):
        ceiling=getattr(d,'_rift_stage_ceiling',None)
        stage=min(state['stage'],ceiling) if ceiling is not None else state['stage']
        state['opened'].append(stage);return screen(),stage
    def open_stage(s,stage):state['opened'].append(stage);return screen()
    d.rift_highest=highest;d.rift_open_stage=open_stage
    def team(s,t,return_page=None):state['teams'].append(t);return s
    d.select_team=team;d.b.click_text=lambda *_:None;d.exit_result=lambda *_:None
    def battle(resource):
        assert resource=='裂痕挑战免费'
        state['starts']+=1;d.battles+=1;d.task_counts['rift']=d.task_counts.get('rift',0)+1
        if next(result,'victory')=='failed':raise FightLost(screen())
        return screen()
    def claim(s,stage):
        state['keys']-=1;state['claimed'].append(stage)
        if advance:state['stage']+=1
        d.report.setdefault('rift_chests',[]).append({'status':'claimed','stage':stage})
        d.resource_spent('rift','裂痕钥匙',1,state['keys'])
    d.battle=battle;d.rift_claim=claim
    d.start_challenge=lambda *a:None
    return state


@pytest.mark.parametrize('reserve',[0,3,5,10])
def test_victories_advance_and_obey_key_reserve(tmp_path,monkeypatch,reserve):
    d=daily(tmp_path);d.options['rift']['reserve_keys']=reserve
    state=fake_rift(d,monkeypatch);message=d.rift()
    count=max(0,5-reserve)
    assert state['keys']==min(5,reserve)
    assert state['teams']==[2]*count
    assert state['claimed']==list(range(24,24+count))
    assert f'已开箱{count}次' in message
    assert d.report['resource_usage']['rift']['裂痕钥匙']['spent']==count


def test_both_teams_failed_use_previous_stage_without_retrying_failed_high_stage(tmp_path,monkeypatch):
    d=daily(tmp_path);state=fake_rift(d,monkeypatch,outcomes=['failed','failed'])
    message=d.rift()
    assert state['teams']==[2,1]+[2]*5 and state['keys']==0
    assert state['opened']==[24,24]+[23]*5 and state['claimed']==[23]*5
    assert d.report['rift_failed_stage']==24 and '已开箱5次' in message
    assert d.report['rift_fallbacks']==[{'from':24,'to':23,'reason':'所选阵容均未通过'}]


def test_fallback_win_then_rechecks_new_highest(tmp_path,monkeypatch):
    d=daily(tmp_path);state=fake_rift(d,monkeypatch,keys=2,outcomes=['failed','victory','victory'])
    d.rift()
    assert state['teams']==[2,1,2] and state['claimed']==[24,25]
    assert state['opened']==[24,24,25]


def test_already_failed_team_is_not_retried_on_same_stage(tmp_path,monkeypatch):
    d=daily(tmp_path);state=fake_rift(d,monkeypatch,keys=3,outcomes=['failed','victory','victory','victory'],advance=False)
    d.rift()
    assert state['teams']==[2,1,1,1] and state['claimed']==[24,24,24]


def test_challenge_limit_includes_failed_attempts(tmp_path,monkeypatch):
    d=daily(tmp_path);d.options['rift']['max_runs']=1
    state=fake_rift(d,monkeypatch,outcomes=['failed'])
    with pytest.raises(BudgetReached):d.rift()
    assert state['teams']==[2] and state['keys']==5


def test_free_entry_requires_target_and_verified_button(tmp_path):
    d=daily(tmp_path);s=captured('v084-rift-detail24')
    d.b.match_template=lambda *_:True
    verify_free_rift(d.b,s,24)
    with pytest.raises(TaskBlocked):verify_free_rift(d.b,s,23)
    s.words+=screen(('25钻石',1110,651,80,25)).words
    with pytest.raises(SafetyStop):verify_free_rift(d.b,s,24)


def claim_flow(d,after=5,reward=True):
    initial=captured('v084-rift-victory24');opened=captured('v084-rift-reward24')
    current=screen(('凿星裂痕',120,10,120,30),('凿星裂痕当前通关',500,5,280,30),
                   ('24',610,40,50,30),('匹配房间',1090,650,100,40),('创建队伍',1190,650,90,40))
    d.b.read_resource_ratio=lambda *_:(after,9);d.rift_wait_map=lambda:current
    calls=[];d.observe=lambda:opened if calls and reward else initial
    d.b.click_at=lambda *a:calls.append(a);d.b.match_template=lambda *_:True
    d.b.sleep=lambda *_:None;d.exit_result=lambda *_:None
    return initial,calls


def test_chest_consumed_only_after_reward_and_one_key_delta(tmp_path):
    d=daily(tmp_path);s,calls=claim_flow(d)
    d.resource_balance('rift','裂痕钥匙',6);d.rift_claim(s,24)
    assert len(calls)==1 and d.report['rift_chests'][0]['status']=='claimed'
    assert d.report['resource_usage']['rift']['裂痕钥匙']=={'start':6,'remaining':5,'spent':1,'unverified':0}


@pytest.mark.parametrize('after',[6,4])
def test_wrong_key_delta_stops_and_does_not_reopen(tmp_path,after):
    d=daily(tmp_path);s,calls=claim_flow(d,after=after)
    with pytest.raises(SafetyStop,match='扣除'):d.rift_claim(s,24)
    assert len(calls)==1 and d.report['rift_chests'][0]['status']=='unverified'


def test_missing_reward_never_double_clicks_chest(tmp_path):
    d=daily(tmp_path);s,calls=claim_flow(d,reward=False)
    with pytest.raises(SafetyStop,match='开箱结果'):d.rift_claim(s,24)
    assert len(calls)==1 and d.report['rift_chests'][0]['status']=='opening'


def test_reserve_or_already_opened_reward_never_uses_key(tmp_path):
    d=daily(tmp_path);s,calls=claim_flow(d);d.options['rift']['reserve_keys']=6
    with pytest.raises(SafetyStop):d.rift_claim(s,24)
    with pytest.raises(TaskBlocked):d.rift_claim(captured('v084-rift-reward24'),24)
    assert calls==[]
