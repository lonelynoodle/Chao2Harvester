"""Actual failed screens from Oct 17/18 and stateful continuation regressions."""
import pytest
import chao2.daily_challenges as challenges
from chao2.configuration import normalize_settings,plan_tasks
from chao2.workflows import ORDER,is_world
from chao2.reward_collection import is_map_story
from chao2.forest import forest_collect_ready
from chao2.policy import TaskBlocked
from test_configuration import captured,daily,screen
from test_daily_challenges import origin_frame


def test_custom_queue_orders_stamina_tasks_without_reinserting_removed_tasks():
    s=normalize_settings({'task_order':['finish','main','tower','hunt','copies','startup']})
    assert plan_tasks(s,['tower','copies','main','startup','finish'],ORDER)==['startup','main','tower','copies','finish']
    assert plan_tasks(s,[],ORDER)==[]
    for queue in (['main','main'],['unknown'],'main'):
        with pytest.raises(ValueError):normalize_settings({'task_order':queue})


def test_actual_world_story_is_not_navigable_world():
    s=captured('v0914-map-story',True)
    assert is_map_story(s) and not is_world(s)
    assert not is_map_story(captured('v0913-main-world',True))
    assert not is_map_story(captured('v097-wild-success',True))
    s.words=[w for w in s.words if w.text!='评论']
    assert not is_map_story(s)


def test_story_closes_once_waits_for_animation_and_returns_world(tmp_path):
    d=daily(tmp_path);story=captured('v0914-map-story',True);world=captured('v0913-main-world',True)
    frames=iter([story,world]);d.b.observe=lambda *a:next(frames);d.b.sleep=lambda _:None
    clicks=[];d.b.click_at=lambda *args:clicks.append(args[1])
    assert d.home(story) is world
    assert clicks==[(1210,650)] and d.report['map_stories']==['丢下火花']


def test_stuck_story_retries_only_its_close_and_is_not_counted_as_passed(tmp_path):
    d=daily(tmp_path);s=captured('v0914-map-story',True);d.b.observe=lambda *a:s;d.b.sleep=lambda _:None
    clicks=[];d.b.click_at=lambda *a:clicks.append(a[1])
    with pytest.raises(TaskBlocked,match='重试3次'):d.close_map_story(s)
    assert len(clicks)==4 and not d.report.get('map_stories')


def test_forest_animation_uses_gold_button_and_local_text_together(tmp_path):
    d=daily(tmp_path);d.b.match_template=lambda *a:False
    assert forest_collect_ready(d.b,captured('v0914-forest-collect-glow',True))
    for name in ('collected','collect','beast','info','timed'):
        assert not forest_collect_ready(d.b,captured('v085-forest-'+name,True))
    s=captured('v0914-forest-collect-glow')
    assert not forest_collect_ready(d.b,s)  # Text alone cannot enable a grey button.


def test_forest_transient_recognition_retries_then_collects_only_once(tmp_path):
    d=daily(tmp_path);s=captured('v0914-forest-collect-glow',True)
    reward=captured('v085-forest-collect',True)
    frames=iter([screen(),screen(),s,reward]);d.observe=lambda:next(frames)
    d.b.match_template=lambda *a:False;d.b.sleep=lambda _:None
    d.forest_wait_map=lambda:s;clicks=[];d.b.click_at=lambda *a:clicks.append(a[3])
    assert d.forest_collect(s) is s
    assert clicks==['免费收取已探索森林资源','关闭森林收获奖励']
    assert len(d.report['forest_rewards'])==1


def test_forest_collect_button_gone_skips_but_unknown_page_stops_after_three_reads(tmp_path):
    d=daily(tmp_path);s=captured('v0914-forest-collect-glow',True)
    gone=captured('v085-forest-collected',True);d.b.match_template=lambda *a:False;d.b.sleep=lambda _:None
    calls=[];d.observe=lambda:(calls.append(1) or gone)
    d.b.click_at=lambda *a:pytest.fail('No click after the collection state disappeared')
    assert d.forest_collect(s) is gone and len(calls)==3
    calls.clear();d.observe=lambda:(calls.append(1) or screen())
    with pytest.raises(TaskBlocked,match='连续3次'):d.forest_collect(s)
    assert len(calls)==3


def test_origin_matching_fixture_needs_no_title_or_cancel_click():
    assert challenges.origin_resume_state(captured('v0914-origin-matching',True))=='matching'
    assert challenges.origin_resume_state(captured('v076-origin-failed',True))=='result'
    assert challenges.origin_resume_state(captured('origin-menu',True)) is None


@pytest.mark.parametrize('initial',['v0914-origin-matching','v076-origin-failed'])
def test_origin_resumes_existing_match_before_any_team_or_navigation(tmp_path,monkeypatch,initial):
    d=daily(tmp_path);monkeypatch.setattr(challenges,'origin_is_open',lambda:True)
    d._origin_entry=captured(initial,True);result=captured('v076-origin-failed',True)
    d.observe=lambda:result;d.b.sleep=lambda _:None
    d.enter_building=lambda *a:pytest.fail('An active match must not navigate away')
    d.select_team=lambda *a,**k:pytest.fail('Current battle keeps its original team')
    d.b.click_text=lambda *a,**k:pytest.fail('Do not rematch, cancel or spend a new quota')
    exits=[];d.exit_result=lambda s:exits.append(s)
    d.await_page=lambda *a:origin_frame(0);d.home=lambda:None
    assert '1场' in d.origin() and len(exits)==1
    assert d.task_counts['origin']==1
    assert d.report['team_attempts'][0]['resumed'] and d.report['origin_remaining']==0
    assert d.report['resource_usage']['origin']['免费次数']['unverified']==1


def test_unknown_existing_battle_waits_for_origin_proof_without_settling(tmp_path):
    d=daily(tmp_path);s=screen(('00:56',560,20,80,30),('自动',90,600,40,25),('结算',165,600,50,30))
    assert challenges.origin_resume_state(s)=='battle'
    wrong=screen(('胜利',80,250,400,200),('退出',1150,582,55,30))
    d.observe=lambda:wrong;d.b.sleep=lambda _:None
    d.b.click_at=lambda *a:pytest.fail('Unconfirmed in-flight battle should only be observed')
    with pytest.raises(TaskBlocked,match='未确认属于起源殿'):
        d.pvp_battle('origin',entry=s,verify_origin=True,allow_settle=False)


@pytest.mark.parametrize('enabled',[True,False])
def test_hunt_settle_obeys_switch_and_never_double_clicks(tmp_path,enabled):
    d=daily(tmp_path,{'task_options':{'hunt':{'auto_settle':enabled}}});d.active_task='hunt'
    battle=screen(('00:56',560,20,80,30),('自动',90,600,40,25),('结算',165,600,50,30))
    result=screen(('胜利',80,250,400,200),('退出',1150,582,55,30),('获得奖励',700,350,140,30))
    frames=iter([battle,battle,result]);d.observe=lambda:next(frames);d.b.sleep=lambda _:None
    clicks=[];d.b.click_at=lambda *a:clicks.append(a[1])
    assert d.battle('地图体力') is result
    assert len(clicks)==int(enabled)


@pytest.mark.parametrize('initial',['v0914-origin-matching','v0919-rank-demotion'])
def test_run_does_not_pull_origin_ahead_of_startup_for_shared_combat_hud(tmp_path,monkeypatch,initial):
    import chao2.workflows as workflows
    import threading
    report={'folder':tmp_path,'tasks':{},'events':[]}
    monkeypatch.setattr(workflows,'create_report',lambda:report)
    monkeypatch.setattr(workflows,'origin_is_open',lambda:True)
    monkeypatch.setattr(workflows.Backend,'connect',lambda s:None)
    monkeypatch.setattr(workflows.Daily,'observe',lambda *a,**k:captured(initial))
    calls=[]
    def execute(d,task):
        assert not getattr(d,'_origin_entry',None)
        calls.append(task);d.report['tasks'][task]={'status':'done'}
    def home(d,*a,**k):
        assert calls and calls[0]=='startup'
        return captured('v0913-main-world',True)
    monkeypatch.setattr(workflows.Daily,'execute_task',execute)
    monkeypatch.setattr(workflows.Daily,'home',home)
    monkeypatch.setattr(workflows.Daily,'maybe_capture_wild',lambda d,s:s)
    monkeypatch.setattr(workflows.Daily,'maybe_free_summon',lambda d,s:s)
    monkeypatch.setattr(workflows.Daily,'restore_world_team',lambda d:None)
    monkeypatch.setattr(workflows.Daily,'save_state',lambda d:None)
    actual=workflows.run_daily({'close_mumu':False},['startup','origin'],threading.Event(),log=lambda _:None)
    assert actual['status']=='completed' and calls==['startup','origin']
