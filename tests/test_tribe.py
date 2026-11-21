"""Tribe state-machine checks and captured 2026-10-14 game pages; no input."""
import pytest
from test_configuration import daily,screen,captured
from chao2.configuration import normalize_settings,plan_tasks
from chao2.workflows import ORDER
from chao2.policy import TaskBlocked,FightLost,dangerous_dialog
from chao2.activities import BudgetReached,tribe_identity,is_tribe_map,tribe_map_moved,tribe_nodes


def fixture_game(d,balance=7,remaining=10,outcomes=()):
    d.tribe_repeat_disabled=True  # A verified-off client, separate from unknown-state tests below.
    state={'balance':balance,'remaining':remaining,'starts':0,'teams':[],
           'name':'冒险关卡30','header':'部落','cost':'1','consume':True}
    results=iter(outcomes)
    def detail():
        return screen((state['header'],120,10,160,35),
            (state['name'],40,132,141,34),('敌方阵容',1140,140,100,25),
            ('通关奖励(含拍卖和共享奖励)',40,560,237,25),('排阵',830,610,70,30),('挑战',1060,605,70,30),
            (state['cost'],1098,640,15,25),(f"{state['balance']}/15",1180,10,90,30),
            (f"剩余次数：{state['remaining']}/10",1000,555,190,25))
    def enter(pattern):
        assert pattern=='^部落冒险$'
        return detail()
    def select(s,team):
        state['teams'].append(team)
        return detail()
    def click(s,pattern):
        assert pattern=='^挑战$|^前往挑战$'
        state['starts']+=1
        if state['consume']:state['balance']-=1;state['remaining']-=1
    def battle(resource):
        assert resource=='部落战令'
        d.battles+=1;d.task_counts['tribe']=d.task_counts.get('tribe',0)+1
        if next(results,'victory')=='failed':raise FightLost(screen())
        return screen()
    d.enter_overview=enter;d.tribe_detail=lambda identity=None:detail();d.select_team=select;d.b.click_text=click
    d.b.read_number=lambda *args:None
    d.battle=battle;d.exit_result=lambda _:None;d.home=lambda:None
    d.start_challenge=lambda task,s,*a:d.b.click_text(s,'^挑战$|^前往挑战$')
    return state,detail


@pytest.mark.parametrize('reserve',[0,3,5,20])
def test_tribe_retains_orders_after_every_fight(tmp_path,reserve):
    d=daily(tmp_path);d.options['tribe']['reserve_orders']=reserve
    state,_=fixture_game(d)
    d.tribe()
    assert state['balance']==min(7,reserve)
    assert state['starts']==7-min(7,reserve)
    assert all(team==2 for team in state['teams'])
    assert d.report['dungeon_resources']['tribe']['remaining']==state['balance']


def test_tribe_does_not_spend_reserved_orders_on_fallback(tmp_path):
    d=daily(tmp_path);d.options['tribe'].update(reserve_orders=3,teams=[2,1,3])
    state,_=fixture_game(d,balance=4,outcomes=['failed'])
    d.tribe()
    assert state['starts']==1 and state['balance']==3
    assert state['teams']==[2]


def test_tribe_fallback_stops_after_first_win_and_checks_budget(tmp_path):
    d=daily(tmp_path);d.options['tribe'].update(teams=[2,1,3],max_runs=2)
    state,_=fixture_game(d,outcomes=['failed','victory'])
    with pytest.raises(BudgetReached):d.tribe()
    assert state['teams']==[2,1] and state['starts']==2


def test_tribe_stops_when_all_selected_teams_lose(tmp_path):
    d=daily(tmp_path);d.options['tribe']['teams']=[2,3]
    state,_=fixture_game(d,outcomes=['failed','failed'])
    with pytest.raises(TaskBlocked,match='均未获得结算'):d.tribe()
    assert state['starts']==2


@pytest.mark.parametrize('change',[
    {'header':'部落战'},{'cost':'2'},{'name':''},
])
def test_tribe_rejects_unverified_page_or_cost(tmp_path,change):
    d=daily(tmp_path);state,_=fixture_game(d);state.update(change)
    with pytest.raises(TaskBlocked):d.tribe()
    assert state['starts']==0


def test_tribe_does_not_keep_farming_if_no_resource_was_spent(tmp_path):
    d=daily(tmp_path);state,_=fixture_game(d);state['consume']=False
    with pytest.raises(TaskBlocked,match='战令未减少'):d.tribe()
    assert state['starts']==1


def test_tribe_free_attempt_cap_prevents_purchase(tmp_path):
    d=daily(tmp_path);state,_=fixture_game(d,remaining=0)
    assert '免费挑战次数已用完' in d.tribe()
    assert state['starts']==0 and state['balance']==7
    assert state['starts']==0
    assert dangerous_dialog('购买战令') and dangerous_dialog('征战令不足')


def test_tribe_unknown_balance_blocks_input(tmp_path):
    d=daily(tmp_path);state,_=fixture_game(d);state['balance']='?'
    with pytest.raises(TaskBlocked,match='余额未识别'):d.tribe()
    assert state['starts']==0


def test_tribe_selection_and_settings_do_not_change_stamina_plan():
    settings=normalize_settings({'tasks':['tribe','hunt']})
    assert settings['task_options']['tribe']=={'teams':[2],'wall_mode':'ignore','max_runs':0,'reserve_orders':0,'random_totem':True,
                                            'clear_auction_dot':True,'clear_dynamics_dot':True,
                                            'claim_donation_rewards':True}
    assert plan_tasks(settings,settings['tasks'],ORDER)==['hunt','tribe']
    assert 'tribe' not in normalize_settings({'tasks':['hunt']})['tasks']
    for bad in [-1,1.5,True,10000]:
        with pytest.raises(ValueError):normalize_settings({'task_options':{'tribe':{'reserve_orders':bad}}})


def test_actual_tribe_map_and_detail_do_not_require_dimmed_header(tmp_path):
    d=daily(tmp_path);d.b.read_number=lambda s,roi:1
    assert is_tribe_map(captured('tribe-entry'))
    for name,stage in [('tribe-node','冒险关卡15'),('tribe-active-detail','冒险关卡30')]:
        s=captured(name)
        assert not is_tribe_map(s)
        assert tribe_identity(s)==stage
        assert not s.find('^部落$')
    d.verify_tribe_detail(captured('tribe-active-detail'),'冒险关卡30')
    with pytest.raises(TaskBlocked):d.verify_tribe_detail(captured('tribe-node'))
    with pytest.raises(TaskBlocked,match='目标变化'):d.verify_tribe_detail(captured('tribe-active-detail'),'冒险关卡29')


def test_actual_map_motion_ignores_same_position_and_detects_pan():
    a=captured('tribe-entry',True);b=captured('tribe-map-next',True)
    assert tribe_map_moved(a,b)
    assert not tribe_map_moved(b,b)


def test_actual_animated_markers_and_clan_crest():
    import math
    for name,expected in [('tribe-map-next',(601,379)),('tribe-map-scan2',(582,379)),
                          ('tribe-map-animated',(579,383)),('v083-tribe-dim',(995,247)),
                          ('v083-tribe-bright',(995,247))]:
        nodes=tribe_nodes(captured(name,True))
        assert len(nodes)==1 and math.dist(nodes[0],expected)<3
    for name in ['tribe-entry','tribe-node','tribe-active-detail','tribe-formation']:
        assert tribe_nodes(captured(name,True))==[]


def test_actual_tribe_idle_slot_is_only_accepted_for_tribe_task(tmp_path):
    d=daily(tmp_path);d.observe=lambda:captured('tribe-formation');d.b.sleep=lambda _:None
    d.active_task='tribe';assert d.formation_page().find('^部队$')
    d.active_task='copies'
    with pytest.raises(TaskBlocked,match='尚未加载'):d.formation_page()


def test_tribe_copies_world_team_to_independent_slot_and_verifies_power(tmp_path):
    d=daily(tmp_path);d.active_task='tribe'
    d.formation_page=lambda **kwargs:captured('tribe-formation')
    states=iter([captured('tribe-config-list',True),captured('tribe-config-list',True),captured('tribe-copied-formation',True)])
    d.observe=lambda:next(states);clicks=[]
    d.b.click_text=lambda s,p,roi=None:clicks.append((p,roi))
    d.b.click_at=lambda s,p,a,r:clicks.append((r,p))
    d.await_detail=lambda:captured('tribe-active-detail')
    assert tribe_identity(d.select_team(captured('tribe-active-detail'),2))=='冒险关卡30'
    assert d.initial_team is None
    assert any(p=='复制保存的队伍2到独立配置' for p,_ in clicks)
    assert clicks[-1][0]=='返回关卡'


def test_tribe_home_returns_from_detail_and_formation(tmp_path):
    from chao2.workflows import is_world
    d=daily(tmp_path)
    states=iter([captured('tribe-formation'),captured('tribe-active-detail'),captured('tribe-entry'),captured('world-missed-label',True)])
    clicks=[];d.observe=lambda:next(states);d.b.click_at=lambda s,p,a,r:clicks.append(r)
    assert is_world(d.home())
    assert clicks==['退出排阵','关闭部落冒险详情','返回上级']


@pytest.mark.parametrize('reserve,limit',[(3,0),(0,2)])
def test_unknown_client_repeat_cannot_bypass_reserve_or_run_limit(tmp_path,reserve,limit):
    d=daily(tmp_path);state,detail=fixture_game(d)
    d.tribe_repeat_disabled=False;d.options['tribe'].update(reserve_orders=reserve,max_runs=limit)
    with pytest.raises(TaskBlocked,match='重复挑战尚未确认关闭'):d.tribe()
    assert state['starts']==0


def test_client_repeat_is_accounted_from_actual_balance_and_switched_off(tmp_path):
    d=daily(tmp_path);d.active_task='tribe';d.tribe_orders_before=11
    d.battles=1;d.task_counts['tribe']=1
    on=captured('tribe-recover-0',True);off=captured('tribe-recover-0',True)
    # Simulate the acknowledged checkbox state; all result text/resource data are real.
    off.image[640:655,874:891]=0
    clicks=[];d.b.click_at=lambda s,p,a,r:clicks.append(r);d.observe=lambda:off
    assert d.tribe_settlement(on) is off
    assert d.battles==6 and d.task_counts['tribe']==6
    assert d.tribe_repeat_disabled and clicks==['关闭客户端重复挑战']
    assert d.report['dungeon_resources']['tribe']['remaining']==5


def test_tribe_data_layer_then_real_reward_is_score_not_victory(tmp_path):
    d=daily(tmp_path);d.active_task='tribe'
    frames=iter([screen(('点击空白位置继续',850,580,220,30),('防御值 -5',1100,412,160,30)),captured('tribe-recover-0')])
    d.observe=lambda:next(frames);d.b.sleep=lambda _:None
    clicks=[];d.b.click_at=lambda s,p,a,r:clicks.append(r)
    d.tribe_settlement=lambda s:s
    result=d.battle('部落战令')
    assert result.find('^退出$') and d.report['battles'][0]['result']=='score'
    assert clicks==['查看部落冒险结算奖励']


def test_tribe_pan_uses_clear_lane_and_opens_fresh_detected_node(tmp_path):
    from types import SimpleNamespace
    from chao2.activities import tribe_nodes
    d=daily(tmp_path)
    first=captured('tribe-entry',True);active=captured('tribe-map-scan2',True)
    assert not tribe_nodes(first) and tribe_nodes(active)
    frames=iter([first,active,active,captured('tribe-active-detail',True)])
    d.observe=lambda:next(frames);d.b.sleep=lambda _:None
    swipes=[];clicks=[]
    def swipe(*args):swipes.append(args);return SimpleNamespace(succeeded=True)
    d.b.controller=SimpleNamespace(post_swipe=swipe);d.b.wait=lambda j:j
    d.b.click_at=lambda s,p,a,r:clicks.append(r)
    assert tribe_identity(d.tribe_detail())=='冒险关卡30'
    assert swipes==[(850,90,550,90,1200)]
    assert clicks==['选择部落冒险可挑战节点']


def test_tribe_sword_pulse_between_frames_keeps_the_same_clickable_node(tmp_path):
    d=daily(tmp_path);bright=captured('v083-tribe-bright',True)
    d.observe=lambda:bright
    frame,point=d.stable_tribe_node(captured('v083-tribe-dim',True),(994,247))
    assert frame is bright and point==(995,247)


def test_tribe_node_waits_for_a_missing_frame_and_reacquires_after_motion(tmp_path):
    d=daily(tmp_path);d.b.sleep=lambda _:None
    missing=captured('tribe-entry',True);moved=captured('tribe-map-animated',True)
    frames=iter([missing,moved,moved]);d.observe=lambda:next(frames)
    frame,point=d.stable_tribe_node(captured('v083-tribe-dim',True),(994,247))
    assert frame is moved and point==(579,383)


def test_delayed_tribe_reward_interrupts_node_check_then_resumes_map(tmp_path):
    from chao2.activities import is_tribe_map,is_tribe_reward_overlay
    d=daily(tmp_path);d.b.sleep=lambda _:None
    reward=screen(('部落',146,15,44,26),('部落大厅',1120,640,110,35),
                  ('获得奖励',521,124,236,56))
    assert is_tribe_reward_overlay(reward) and not is_tribe_map(reward)
    ready=captured('v083-tribe-bright',True)
    d.observe=lambda:reward
    clicks=[];d.b.click_at=lambda s,p,a,r:clicks.append((p,r))
    d.wait_for_screen=lambda predicate,label,**kwargs:ready if predicate(ready) else None
    frame,point=d.stable_tribe_node(captured('v083-tribe-dim',True),(994,247))
    assert frame is ready and point==(995,247)
    assert clicks==[((640,560),'关闭部落冒险延迟奖励')]


def test_tribe_unconfirmed_marker_stops_without_clicking_old_coordinate(tmp_path):
    d=daily(tmp_path);d.b.sleep=lambda _:None;d.observe=lambda:captured('tribe-entry',True)
    d.b.click_at=lambda *a:pytest.fail('No stale node click')
    with pytest.raises(TaskBlocked,match='未稳定'):
        d.stable_tribe_node(captured('v083-tribe-dim',True),(994,247))
    d.observe=lambda:captured('tribe-active-detail')
    with pytest.raises(TaskBlocked,match='地图改变'):
        d.stable_tribe_node(captured('v083-tribe-dim',True),(994,247))


def test_actual_account_disconnect_stops_battle_without_confirmation_or_result(tmp_path):
    from chao2.policy import SafetyStop
    d=daily(tmp_path);d.active_task='tribe'
    d.observe=lambda:captured('v083-account-disconnected')
    d.b.click_at=lambda *a:pytest.fail('Do not acknowledge or reconnect the account')
    d.b.sleep=lambda _:pytest.fail('Do not wait for a battle result after disconnection')
    with pytest.raises(SafetyStop,match='其他设备登录'):d.battle('部落战令')
    assert not d.report.get('battles') and not d.report.get('team_attempts')


def test_disconnect_words_in_chat_are_not_an_account_dialog(tmp_path):
    d=daily(tmp_path)
    d.b.guard(screen(('账号在其他设备登录',70,650,240,25),('确定',612,481,56,31)))
