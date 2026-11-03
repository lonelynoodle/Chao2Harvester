import pytest
from test_configuration import captured,daily,screen
from chao2.policy import TaskBlocked,SafetyStop,EncounterInterrupted
from chao2.world_events import ambush_identity,is_ambush,is_map_choice,verify_ambush
from chao2.workflows import is_world
from chao2.activities import is_copy_list

def test_actual_ambush_requires_title_and_specific_controls(tmp_path):
    d=daily(tmp_path);s=captured('v082-ambush',True)
    assert is_ambush(s) and not is_world(s)
    assert ambush_identity(s)=='乱入-敌袭-破界沼地'
    assert not is_ambush(captured('v081-tour-detail'))
    s.words=[w for w in s.words if w.text!='逃跑']
    assert not is_ambush(s)

def test_ambush_only_uses_verified_free_button(tmp_path):
    d=daily(tmp_path);s=captured('v082-ambush');d.b.match_template=lambda *a:True
    assert verify_ambush(d.b,s,ambush_identity(s))==122
    with pytest.raises(TaskBlocked,match='目标'):verify_ambush(d.b,s,'乱入-敌袭-其他地点')
    d.b.match_template=lambda *a:False
    with pytest.raises(TaskBlocked,match='免费'):verify_ambush(d.b,s,ambush_identity(s))
    d.b.match_template=lambda *a:True;s.words.extend(screen(('25',1060,640,30,20)).words)
    with pytest.raises(SafetyStop,match='费用'):verify_ambush(d.b,s,ambush_identity(s))

def test_ambush_before_battle_is_separate_and_pending_attempt_is_not_counted(tmp_path):
    d=daily(tmp_path);d.active_task='copies';d.b.sleep=lambda _:None;d.b.match_template=lambda *a:True
    sequence=iter([captured('v082-ambush'),captured('v082-ambush'),
                   captured('v082-ambush-result'),captured('v082-map-choice')])
    d.observe=lambda *a:next(sequence);clicks=[];d.b.click_at=lambda *a:clicks.append(a[-1]);d.exit_result=lambda s:None
    d.checkpoint=lambda:None
    d.resource_balance('copies','地图体力',122)
    with pytest.raises(EncounterInterrupted):d.battle('地图体力20')
    assert clicks==['挑战免费敌袭乱入']
    assert d.battles==1 and d.task_counts=={'copies':0,'ambush':1} and d.active_task=='copies'
    assert d.report['team_attempts'][0]['task']=='ambush'
    assert len(d.report['battles'])==1 and d.report['battles'][0]['resource']=='敌袭乱入免费'
    assert d.report['ambushes'][0]['stamina_spent']==0
    assert d.report['resource_usage']['copies']['地图体力']['spent']==0

def test_failed_ambush_is_not_retried_or_counted_as_copy_victory(tmp_path):
    d=daily(tmp_path);d.active_task='copies';d.b.sleep=lambda _:None;d.b.match_template=lambda *a:True
    fail=screen(('失败',300,200,90,50),('退出',1100,600,90,40))
    sequence=iter([captured('v082-ambush'),captured('v082-ambush'),fail]);d.observe=lambda *a:next(sequence)
    clicks=[];d.b.click_at=lambda *a:clicks.append(a[-1]);d.exit_result=lambda s:pytest.fail('Keep failure scene')
    with pytest.raises(SafetyStop,match='未通过'):d.battle('地图体力20')
    assert len(clicks)==1 and d.report['ambushes'][0]['status']=='failed'
    assert d.active_task=='copies' and not d.report.get('team_attempts')

def test_world_target_selection_never_counts_as_available_background_map_or_copy_list():
    s=captured('v082-map-choice',True)
    assert is_map_choice(s) and not is_world(s) and not is_copy_list(s)

def test_home_handles_ambush_before_generic_detail_return(tmp_path):
    d=daily(tmp_path);calls=[]
    world=screen(('事件',1100,620,60,30),('领地',1200,620,60,30),('123/164',500,15,80,30))
    d.observe=lambda *a:world;d.handle_ambush=lambda s:calls.append('ambush')
    d.b.click_at=lambda *a:pytest.fail('Must not press the detail back button')
    assert d.home(captured('v082-ambush')) is world and calls==['ambush']

def test_map_choice_closes_only_the_observed_x(tmp_path):
    d=daily(tmp_path);s=captured('v082-map-choice');calls=[]
    d.b.click_at=lambda s,pt,*args:calls.append(pt);d.observe=lambda:s
    d.close_map_choice(s)
    assert calls==[(695,358)]

def test_task_resumes_navigation_after_event_without_duplicate_ui_task(tmp_path):
    d=daily(tmp_path);calls=[];d.home=lambda:None;d.checkpoint=lambda:None
    def copies():
        calls.append('copies')
        if len(calls)==1:raise EncounterInterrupted('ambush handled')
        return '原任务已继续'
    d.copies=copies;d.execute_task('copies')
    assert calls==['copies','copies'] and d.report['execution_order']==['copies']
    assert d.report['tasks']['copies']['status']=='done'

def test_pending_encounter_reopens_and_rechecks_same_team_after_event(tmp_path):
    d=daily(tmp_path,{'task_options':{'copies':{'teams':[1,2]}}})
    detail=captured('copy-current-detail');result=captured('v082-ambush-result');calls=[]
    d.select_team=lambda s,t:calls.append(('team',t)) or s
    d.verify_instant_setting=lambda *a:None;d.b.click_text=lambda *a:None
    d.exit_result=lambda *a:None;d.checkpoint=lambda:None
    outcomes=iter([EncounterInterrupted('event cleared'),result])
    def battle(*a):
        outcome=next(outcomes)
        if isinstance(outcome,Exception):raise outcome
        return outcome
    d.battle=battle
    d.start_challenge=lambda *a:None
    def opener():calls.append(('open',));return detail
    assert d.play_encounter('copies',opener,'地图体力20',lambda s:calls.append(('verify',)))
    assert calls==[('open',),('team',1),('verify',),('open',),('team',1),('verify',)]
    assert len(d.report['team_attempts'])==1 and d.report['team_attempts'][0]['task']=='copies'

def test_copy_overlap_selects_matching_name_once_despite_transition_delay(tmp_path):
    d=daily(tmp_path);d.b.sleep=lambda _:None;d.read_copy_names=lambda s:s
    listing=screen(('异象',970,20,60,30),('本周已获取友好点数910',890,80,250,30),
                   ('任梦漩',916,213,70,27),('20',1070,260,23,17))
    detail=captured('copy-current-detail');frames=iter([captured('v082-map-choice'),captured('v082-map-choice'),detail])
    d.observe=lambda *a:next(frames);calls=[];d.b.click_at=lambda s,pt,*a:calls.append((pt,a[-1]))
    assert d.open_copy_detail(listing,268) is detail
    assert len(calls)==2 and calls[1][1]=='选择重叠位置的原复制体'
    assert calls[1][0]==(562,531)

def test_unknown_copy_overlap_never_chooses_another_target(tmp_path):
    d=daily(tmp_path);d.read_copy_names=lambda s:s
    listing=screen(('异象',970,20,60,30),('本周已获取友好点数910',890,80,250,30),
                   ('另一个目标',916,213,100,27),('20',1070,260,23,17))
    d.observe=lambda *a:captured('v082-map-choice');calls=[];d.b.click_at=lambda *a:calls.append(a)
    with pytest.raises(TaskBlocked,match='名字'):d.open_copy_detail(listing,268)
    assert len(calls)==1
