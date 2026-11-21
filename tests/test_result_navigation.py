"""The startup failure page and asynchronous free settlement exits."""
import pytest

from chao2.policy import PageChanged,SafetyStop,TaskBlocked,UserStopped
from chao2.result_navigation import result_shell,exit_destination
from test_configuration import captured,daily,screen


def result_game(tmp_path):
    d=daily(tmp_path);d.b.sleep=lambda _:None
    result=captured('v0939-startup-failure',True)
    world=captured('world-missed-label',True)
    state=[result];clicks=[]
    d.observe=lambda:state[0]
    d.b.click_text=lambda s,p:clicks.append(p)
    return d,result,world,state,clicks


def test_backend_page_change_retains_the_actual_frame_without_sending_input(tmp_path):
    d,result,world,state,clicks=result_game(tmp_path)
    d.b.observe=lambda:world
    d.b.click_at=lambda *a:pytest.fail('The disappearing exit must not be clicked')
    # Use the real implementation rather than the fake game's input method.
    from chao2.backend import Backend
    with pytest.raises(PageChanged) as caught:Backend.click_text(d.b,result,'^退出$')
    assert caught.value.screen is world and caught.value.pattern=='^退出$'


def test_startup_exits_existing_defeat_without_any_challenge_or_resource_spend(tmp_path):
    d,result,world,state,clicks=result_game(tmp_path)
    def click(s,p):clicks.append(p);state[0]=world
    d.b.click_text=click
    assert '跳过进入游戏' in d.startup()
    assert clicks==['^退出$'] and d.battles==0 and d.task_counts=={}
    assert d.report['result_exits'][0]['status']=='left'
    assert d.report['result_exits'][0]['destination']=='world'


def test_exit_button_vanishing_during_the_preclick_read_does_not_abort(tmp_path):
    d,result,world,state,clicks=result_game(tmp_path)
    calls=[]
    def click(s,p):
        calls.append(p)
        if len(calls)==1:clicks.append(p);return
        state[0]=world;raise PageChanged(p,world)
    d.b.click_text=click
    assert d.home(result) is world
    assert calls==['^退出$']*2 and clicks==['^退出$']
    row=d.report['result_exits'][0]
    assert row['clicks']==1 and row['preclick_rechecks']==1 and row['status']=='left'
    assert 'last_recheck_screenshot' in row


def test_long_exit_animation_with_missing_label_is_only_observed(tmp_path):
    d,result,world,state,clicks=result_game(tmp_path)
    faded=captured('v0939-startup-failure')
    faded.words=[w for w in faded.words if w.text!='退出']
    assert result_shell(faded)=='failed'
    frames=iter([faded]*10+[world,world]);d.observe=lambda:next(frames)
    assert d.exit_result(result) is world and clicks==['^退出$']


def test_blank_or_resource_only_frames_do_not_confirm_an_exit(tmp_path):
    d,result,world,state,clicks=result_game(tmp_path)
    blank=screen();hud=screen(('65/175',1194,13,68,28))
    frames=iter([blank]*5+[hud]*5+[world,world]);d.observe=lambda:next(frames)
    assert d.exit_result(result) is world and clicks==['^退出$']


def test_a_swallowed_free_exit_is_retried_after_source_confirmation(tmp_path):
    d,result,world,state,clicks=result_game(tmp_path)
    def click(s,p):
        clicks.append(p)
        if len(clicks)==2:state[0]=world
    d.b.click_text=click
    assert d.home(result) is world and clicks==['^退出$']*2
    assert len(d.report['navigation_retries'])==1 and d.battles==0


def test_seven_retries_then_preserve_scene_without_pressing_rematch(tmp_path):
    d,result,world,state,clicks=result_game(tmp_path)
    with pytest.raises(TaskBlocked,match='已重试7次'):d.exit_result(result)
    assert clicks==['^退出$']*8 and d.battles==0
    assert d.report['result_exits'][0]['status']=='blocked'


def test_late_page_change_before_retry_prevents_an_additional_input(tmp_path):
    d,result,world,state,clicks=result_game(tmp_path)
    frames=iter([result]*3+[world,world,world]);d.observe=lambda:next(frames)
    assert d.exit_result(result) is world and clicks==['^退出$']


def test_initial_exit_precheck_already_reaches_world_requires_no_input(tmp_path):
    d,result,world,state,clicks=result_game(tmp_path)
    def click(s,p):state[0]=world;raise PageChanged(p,world)
    d.b.click_text=click
    assert d.startup().startswith('已在游戏内')
    assert not clicks and d.report['result_exits'][0]['clicks']==0


def test_return_to_world_text_can_disappear_during_normal_navigation(tmp_path):
    d,result,world,state,clicks=result_game(tmp_path)
    territory=screen(('世界',1200,675,65,25),('永生之茧',300,300,120,30))
    def click(s,p):clicks.append(p);state[0]=world;raise PageChanged(p,world)
    d.b.click_text=click
    assert d.home(territory) is world and clicks==['^世界$']
    assert len(d.report['navigation_retries'])==1


@pytest.mark.parametrize('name,destination',[('giant-menu','giant_menu'),('copy-list','events'),
    ('v0914-map-story','story'),('v081-tour-story','tour_story'),('v082-map-choice','map_choice'),
    ('main-entry','detail'),('v084-rift-map24','menu:凿星裂痕'),('rampage-menu','menu:谜之巢穴')])
def test_known_post_battle_pages_are_not_mistaken_for_lingering_results(name,destination):
    s=captured(name)
    assert result_shell(s) is None and exit_destination(s)==destination


@pytest.mark.parametrize('error',[SafetyStop('发现补购或资源不足弹窗'),UserStopped('用户停止')])
def test_real_stop_conditions_are_not_swallowed_or_retried(tmp_path,error):
    d,result,world,state,clicks=result_game(tmp_path)
    d.b.click_text=lambda *a:(_ for _ in ()).throw(error)
    with pytest.raises(type(error)):d.exit_result(result)
    assert not clicks and not d.report.get('navigation_retries')
