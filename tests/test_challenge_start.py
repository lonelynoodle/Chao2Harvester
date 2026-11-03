"""Battle entry must be observed before counting; source-only taps may retry."""
import pytest

from chao2.challenge_start import challenge_identity,is_challenge_ready,battle_entry_state
from chao2.policy import TaskBlocked,SafetyStop,EncounterInterrupted,UserStopped,FightLost
from test_configuration import captured,daily,screen
from test_tower_flow import TowerGame


def combat():
    return screen(('自动',95,600,48,28),('01:50',600,10,80,30))


def result(balance=5):
    return screen(('胜利',100,200,100,30),('获得奖励',900,300,100,30),
                  ('退出',1140,580,60,30),(f'{balance}/20',1210,15,60,26))


def setup_launch(tmp_path):
    d=daily(tmp_path);d.b.sleep=lambda _:None
    detail=captured('v0938-tower-401-detail',True);state=[detail];clicks=[]
    d.observe=lambda:state[0]
    d.b.click_text=lambda s,p,**kw:clicks.append((s,p))
    d.resource_balance('tower','浮空羽毛',6)
    return d,detail,state,clicks


def test_real_401_detail_retries_then_only_one_feather_and_attempt(tmp_path):
    d,detail,state,clicks=setup_launch(tmp_path)
    def click(s,p,**kw):
        clicks.append((s,p))
        if len(clicks)==2:state[0]=combat()
    d.b.click_text=click
    started=d.start_challenge('tower',detail,'浮空羽毛',lambda q:d.verify_dungeon_resource('tower',q))
    assert started is state[0] and len(clicks)==2 and d.task_counts=={} and d.battles==0
    state[0]=result()
    d.battle('浮空羽毛')
    assert d.task_counts['tower']==d.battles==1
    assert d.report['resource_usage']['tower']['浮空羽毛']['spent']==1
    assert d.report['challenge_starts'][0]['status']=='started'


def test_permanently_swallowed_challenge_click_has_three_retries_and_zero_attempts(tmp_path):
    d,detail,state,clicks=setup_launch(tmp_path)
    with pytest.raises(TaskBlocked,match='已重试3次'):d.start_challenge('tower',detail,'浮空羽毛')
    assert len(clicks)==4 and d.battles==0 and d.task_counts=={}
    assert len(d.report['navigation_retries'])==3
    assert d.report['challenge_starts'][0]['clicks']==4
    assert d.report['challenge_starts'][0]['status']=='blocked'
    assert d.report['resource_usage']['tower']['浮空羽毛']['spent']==0


def test_loading_screen_is_waited_through_without_reclicking(tmp_path):
    d,detail,state,clicks=setup_launch(tmp_path)
    ready=combat();frames=iter([screen()]*12+[ready]);d.observe=lambda:next(frames)
    assert d.start_challenge('tower',detail,'浮空羽毛') is ready
    assert len(clicks)==1 and not d.report.get('navigation_retries')
    assert any('页面已变化' in e['message'] for e in d.report['events'])


def test_transition_arriving_on_final_pre_retry_read_prevents_second_tap(tmp_path):
    d,detail,state,clicks=setup_launch(tmp_path)
    ready=combat();frames=iter([detail]*3+[ready]);d.observe=lambda:next(frames)
    assert d.start_challenge('tower',detail,'浮空羽毛') is ready
    assert len(clicks)==1


def test_transition_during_backend_button_recheck_returns_to_waiting(tmp_path):
    d,detail,state,clicks=setup_launch(tmp_path)
    def click(s,pattern,**kw):
        if not clicks:clicks.append((s,pattern));return
        state[0]=combat()
        raise SafetyStop('点击前页面改变：^挑战$|^前往挑战$')
    d.b.click_text=click
    assert d.start_challenge('tower',detail,'浮空羽毛') is state[0]
    row=d.report['challenge_starts'][0]
    assert len(clicks)==row['clicks']==1 and row['preclick_rechecks']==1


def test_exhausted_attempt_budget_prevents_even_the_first_launch_input(tmp_path):
    d,detail,state,clicks=setup_launch(tmp_path);d.battles=d.limit
    with pytest.raises(TaskBlocked,match='战斗上限'):d.start_challenge('tower',detail,'浮空羽毛')
    assert not clicks


def test_confirmed_free_giant_entry_can_retry_without_a_resource_counter(tmp_path):
    d,detail,state,clicks=setup_launch(tmp_path)
    detail=captured('v077-giant-ready');state[0]=detail;checks=[]
    def click(s,p,**kw):
        clicks.append((s,p))
        if len(clicks)==2:state[0]=combat()
    d.b.click_text=click
    assert d.start_challenge('giant',detail,'巨物免费挑战',lambda q:checks.append(q)) is state[0]
    assert len(clicks)==2 and checks==[detail]


def test_resource_debit_on_still_visible_detail_prevents_additional_taps(tmp_path):
    d,detail,state,clicks=setup_launch(tmp_path)
    debited=captured('v0938-tower-401-detail')
    for w in debited.words:
        if w.text=='6/20':w.text='5/20'
    ready=combat();frames=iter([debited]*8+[ready]);d.observe=lambda:next(frames)
    assert d.start_challenge('tower',detail,'浮空羽毛') is ready and len(clicks)==1
    assert any('资源已扣除' in e['message'] for e in d.report['events'])


@pytest.mark.parametrize('kind',['different_target','missing_balance'])
def test_different_or_unreadable_target_never_authorizes_another_tap(tmp_path,kind):
    d,detail,state,clicks=setup_launch(tmp_path)
    changed=captured('v0938-tower-401-detail')
    if kind=='different_target':
        for w in changed.words:
            if w.text=='浮空巨塔401':w.text='浮空巨塔402'
    else:changed.words=[w for w in changed.words if w.text!='6/20']
    state[0]=changed
    with pytest.raises(TaskBlocked,match='未追加点击'):d.start_challenge('tower',detail,'浮空羽毛')
    assert len(clicks)==1 and d.battles==0


def test_retry_reapplies_cost_verification_before_sending_input(tmp_path):
    d,detail,state,clicks=setup_launch(tmp_path)
    def verify(q):raise TaskBlocked('费用发生变化')
    with pytest.raises(TaskBlocked,match='费用发生变化'):d.start_challenge('tower',detail,'浮空羽毛',verify)
    assert len(clicks)==1 and d.task_counts=={}


def test_retry_refuses_an_instant_checkbox_that_changed(tmp_path):
    d,detail,state,clicks=setup_launch(tmp_path)
    d.verify_instant_setting=lambda *a:(_ for _ in ()).throw(TaskBlocked('瞬破未确认关闭'))
    with pytest.raises(TaskBlocked,match='瞬破'):d.start_challenge('tower',detail,'浮空羽毛')
    assert len(clicks)==1


def test_fast_result_is_cached_and_counted_once_without_an_extra_read(tmp_path):
    d,detail,state,clicks=setup_launch(tmp_path);state[0]=result()
    d.start_challenge('tower',detail,'浮空羽毛')
    d.observe=lambda:pytest.fail('The already confirmed settlement must be consumed first')
    assert d.battle('浮空羽毛') is state[0]
    assert d.battles==d.task_counts['tower']==1 and len(clicks)==1


def test_failed_battle_is_counted_once_and_never_relaunched_by_entry_recovery(tmp_path):
    d,detail,state,clicks=setup_launch(tmp_path)
    state[0]=screen(('挑战失败',100,200,300,50),('退出',1140,580,60,30),('5/20',1210,15,60,26))
    d.start_challenge('tower',detail,'浮空羽毛')
    with pytest.raises(FightLost):d.battle('浮空羽毛')
    assert len(clicks)==1 and d.task_counts['tower']==1


def test_interruption_or_user_stop_does_not_count_a_battle(tmp_path):
    d,detail,state,clicks=setup_launch(tmp_path)
    d.resolve_path_event=lambda s:(_ for _ in ()).throw(EncounterInterrupted('商人已处理'))
    with pytest.raises(EncounterInterrupted):d.start_challenge('tower',detail,'浮空羽毛')
    assert d.report['challenge_starts'][0]['status']=='interrupted' and d.battles==0
    d.resolve_path_event=lambda s:None
    def observe():d.b.stop.set();return detail
    d.observe=observe
    with pytest.raises(UserStopped):d.start_challenge('tower',detail,'浮空羽毛')
    assert d.battles==0 and d.task_counts=={}


def test_confirmed_start_integrates_with_tower_chain_without_reselecting_teams(tmp_path):
    game=TowerGame(tmp_path,balance=3);old_click=game.d.b.click_text;attempts=[0]
    def click(s,pattern,**kwargs):
        if '下一' not in pattern and '挑战' in pattern and attempts[0]<1:
            attempts[0]+=1;return
        return old_click(s,pattern,**kwargs)
    game.d.b.click_text=click
    game.d.tower()
    assert len(game.challenges)==game.d.task_counts['tower']==3 and game.balance==0
    assert game.secrets==['normal'] and game.detail_entries==1
    assert game.d.report['challenge_starts'][0]['clicks']==2


@pytest.mark.parametrize('name,task',[('v0938-tower-401-detail','tower'),('tower-secret-free','tower'),
    ('main-entry','main'),('copy-current-detail','copies'),('tribe-active-detail','tribe'),
    ('v077-giant-ready','giant'),('rampage-menu','nest'),('v084-rift-detail24','rift'),
    ('v085-forest-beast','forest'),('v081-tour-detail','tour'),('v099-abyss-detail','abyss')])
def test_observed_ready_pages_have_a_source_identity(name,task):
    s=captured(name)
    assert is_challenge_ready(s) and challenge_identity(s,task)
    assert battle_entry_state(s) is None


def test_faded_original_detail_with_background_auto_is_not_battle_evidence():
    s=screen(('挑战',950,600,60,30),('自动',95,600,48,28))
    assert battle_entry_state(s) is None
