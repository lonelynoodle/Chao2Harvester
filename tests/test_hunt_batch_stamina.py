"""A timed hunting batch is funded before search and never deferred to main."""
import time

import pytest

from chao2.activities import STAMINA_CLAIM
from chao2.policy import FightLost, SafetyStop, TaskBlocked, UserStopped
from test_configuration import captured, daily, screen


def hunt_session(tmp_path, *, balance=19, targets=0, servings=1, free_searches=1,
                 stock=0, auto_three_shots=True, auto_potions=False, cap=166):
    d=daily(tmp_path,{'task_options':{'hunt':{'auto_three_shots':auto_three_shots,
                                           'auto_potions':auto_potions}}})
    d.selected=['hunt'];d.active_task='hunt';d.wild_daily_active=True
    state=dict(balance=balance,targets=targets,servings=servings,free_searches=free_searches,
               stock=stock,page='menu',potion_stock=0,fail_first=False)
    actions=[]
    def menu():
        state['page']='menu'
        words=[('狩猎',970,19,63,39),('商店',1074,95,48,26),('传送',1218,340,48,30),
               (f'{state["balance"]}/{cap}',502,17,78,22)]
        words.extend(('10',1084,230+i*130,24,18) for i in range(state['targets']))
        if not state['targets']:
            words.extend([('猎物未出现',946,435,114,24),
                          ('免费搜索' if state['free_searches'] else '搜索',1055,665,110,30)])
        return screen(*words)
    def home():
        assert not d.wild_daily_active # No unrelated stamina spending while hunting.
        state['page']='world';return screen()
    def offer():
        actions.append('open-free');state['page']='offer'
        return screen(('领取奖励',650,590,120,35)) if state['servings'] else None
    def click(s,pattern,**kwargs):
        if pattern==STAMINA_CLAIM:
            assert state['page']=='offer'
            actions.append('claim-free');state['servings']-=1;state['balance']+=100
            state['page']='reward'
        elif pattern in ('^免费搜索$','^搜索$'):
            assert state['targets']==0 and state['balance']>=30
            assert d.limit-d.battles>=3
            actions.append('search')
            if pattern=='^免费搜索$':state['free_searches']-=1
            else:state['stock']-=1
            state['targets']=3;state['page']='menu'
        else:assert pattern=='^挑战$|^前往挑战$'
    def battle(resource):
        assert resource=='地图体力10' and state['balance']>=10
        actions.append('fight');state['targets']-=1;state['balance']-=10
        d.battles+=1;d.task_counts['hunt']=d.task_counts.get('hunt',0)+1
        if state['fail_first'] and d.battles==1:raise FightLost(screen(('失败',10,100,100,50)))
        return screen(('胜利',10,100,100,50))
    def potion():
        actions.append('check-potion')
        if not state['potion_stock']:return None
        state['potion_stock']-=1;state['balance']+=100;return 100
    d.hunt_menu=menu;d.home=home;d.stamina_offer=offer
    d.world_resources=lambda s:{'stamina':state['balance'],'stamina_cap':cap}
    d.observe=lambda:menu() if state['page']=='menu' else screen()
    d.b.read_number=lambda *a:state['stock'];d.b.sleep=lambda _:None
    d.b.click_text=click;d.b.click_at=lambda *a:actions.append('open-hunter')
    d.await_detail=lambda **_:screen(('敌方阵容',1130,135,103,28),('排阵',824,614,61,34),
        ('前往挑战',1036,607,109,28),('未知',134,136,58,30),('09:35',602,135,72,26),
        ('10',1096,639,28,18),(f'{state["balance"]}/{cap}',1185,17,76,22))
    d.select_team=lambda s,team:s;d.battle=battle;d.exit_result=lambda s:None
    d.start_challenge=lambda task,s,*a:d.b.click_text(s,'^挑战$|^前往挑战$')
    d.use_stamina_potion=potion
    d.execute_task=lambda task:pytest.fail('No task dispatch during a timed hunt: '+task)
    return d,state,actions


def test_reported_19_stamina_claims_before_free_search_then_finishes_three(tmp_path):
    d,state,actions=hunt_session(tmp_path)
    result=d.hunt()
    assert actions==['open-free','claim-free','search',*(['open-hunter','fight']*3)]
    assert state['targets']==0 and state['balance']==89
    assert '通关3次' in result and d.report['stamina_claims']==1
    assert d.report['hunt_batch']['remaining']==0
    assert d.report['resource_usage']['hunt']['狩猎令']['spent']==0
    assert not d.stamina_retry['hunt'] and d.wild_daily_active


@pytest.mark.parametrize('free_searches,stock',[(1,0),(0,2)])
def test_missing_free_stamina_never_activates_unfunded_batch(tmp_path,free_searches,stock):
    d,state,actions=hunt_session(tmp_path,servings=0,free_searches=free_searches,stock=stock)
    result=d.hunt()
    assert actions==['open-free'] and state['stock']==stock and not state['targets']
    assert '未开启新一批' in result and '没有可领取' in result


def test_existing_hunters_receive_inline_refill_before_next_fight(tmp_path):
    d,state,actions=hunt_session(tmp_path,balance=9,targets=2,free_searches=0)
    d.hunt()
    assert actions==['open-free','claim-free',*(['open-hunter','fight']*2)]
    assert state['balance']==89 and state['targets']==0


def test_unfunded_existing_batch_spends_usable_stamina_then_stops_other_tasks(tmp_path):
    d,state,actions=hunt_session(tmp_path,targets=3,servings=0,free_searches=0)
    with pytest.raises(SafetyStop,match='还有2只限时猎物.*没有可领取.*暂停后续任务'):
        d.hunt()
    assert actions==['open-free','open-hunter','fight']
    assert state['balance']==9 and state['targets']==2 and d.wild_daily_active


def test_refill_respects_hunt_switch_even_when_other_tasks_allow_free_stamina(tmp_path):
    d,state,actions=hunt_session(tmp_path,auto_three_shots=False)
    d.selected=['copies','hunt','main']
    assert '未开启自动领取每日三发' in d.hunt()
    assert actions==[] and state['balance']==19


def test_refill_uses_potion_only_if_enabled_after_free_is_empty(tmp_path):
    d,state,actions=hunt_session(tmp_path,servings=0,auto_potions=True)
    state['potion_stock']=1
    d.hunt()
    assert actions[:3]==['open-free','check-potion','search']
    assert actions.count('fight')==3 and d.report['stamina_potion_count']==1


@pytest.mark.parametrize('free_enabled',[False,True])
@pytest.mark.parametrize('verification',['confirmed','stock_unchanged','stamina_unchanged','no_potions'])
def test_real_potion_flow_confirms_inventory_and_stamina_before_search(tmp_path,free_enabled,verification):
    from copy import deepcopy
    from chao2.stamina_inventory import StaminaInventory
    d,state,actions=hunt_session(tmp_path,servings=0,auto_three_shots=free_enabled,auto_potions=True)
    bag=captured('v090-bag',True);after=deepcopy(bag)
    for word in after.words:
        if word.text=='已拥有152' and verification!='stock_unchanged':word.text='已拥有151'
    d.use_stamina_potion=StaminaInventory.use_stamina_potion.__get__(d)
    def inventory():
        actions.append('open-bag');state['page']='bag'
        return None if verification=='no_potions' else bag
    d.potion_inventory=inventory
    d.await_page=lambda *a:captured('v090-potion-dialog',True)
    original_read=d.b.read_number;original_click=d.b.click_text;original_observe=d.observe
    d.b.read_number=lambda s,roi:1 if roi==(615,352,55,45) else original_read(s,roi)
    def click(s,pattern,**kwargs):
        if pattern=='^使用$':
            actions.append('use-potion');state['page']='potion-dialog'
        elif pattern=='^确定$':
            actions.append('confirm-one-potion');state['page']='potion-result'
            if verification!='stamina_unchanged':state['balance']+=100
        else:original_click(s,pattern,**kwargs)
    d.b.click_text=click
    d.observe=lambda:after if state['page']=='potion-result' else original_observe()
    if verification in ('stock_unchanged','stamina_unchanged'):
        with pytest.raises(SafetyStop,match='未核实'):d.hunt()
        assert 'search' not in actions and 'fight' not in actions
        assert d.report['stamina_potions'][0]['status']=='confirming'
    elif verification=='no_potions':
        assert '未开启新一批' in d.hunt()
        assert actions==(['open-free'] if free_enabled else [])+['open-bag']
    else:
        d.hunt()
        assert actions==(['open-free'] if free_enabled else [])+[
            'open-bag','use-potion','confirm-one-potion','search',*(['open-hunter','fight']*3)]
        assert state['balance']==89 and state['targets']==0
        assert d.report['stamina_potion_count']==1
        assert d.report['stamina_potions'][0]['status']=='confirmed'
        assert d.report['stamina_potions'][0]['stock_after']==151


def test_funded_batch_does_not_open_free_page_and_defeat_still_advances(tmp_path):
    d,state,actions=hunt_session(tmp_path,balance=30,free_searches=0,stock=1)
    state['fail_first']=True
    result=d.hunt()
    assert actions==['search',*(['open-hunter','fight']*3)]
    assert '通关2次，未通过1个' in result and state['targets']==0
    assert d.report['resource_usage']['hunt']['狩猎令']['spent']==1


@pytest.mark.parametrize('constraint',['battle','time','capacity','three_claims'])
def test_batch_preflight_blocks_without_claiming_or_searching(tmp_path,constraint):
    d,state,actions=hunt_session(tmp_path,cap=60 if constraint=='capacity' else 166)
    if constraint=='battle':d.limit=50;d.battles=48  # An explicit internal bound, no longer the daily default.
    if constraint=='time':d.start_time=time.monotonic()-90*60+599
    if constraint=='three_claims':d.report['stamina_claims']=3
    assert '未开启新一批' in d.hunt()
    assert not actions and state['balance']==19


def test_search_primitive_also_rejects_19_stamina(tmp_path):
    d,state,actions=hunt_session(tmp_path)
    with pytest.raises(TaskBlocked,match='需要30体力'):
        d.search_hunters(d.hunt_menu())
    assert not actions


def test_stop_during_refill_never_searches_and_restores_capture_setting(tmp_path):
    d,state,actions=hunt_session(tmp_path)
    def stop():raise UserStopped('用户停止')
    d.stamina_offer=stop
    with pytest.raises(UserStopped):d.hunt()
    assert not actions and d.wild_daily_active


def test_unverified_claim_is_not_repeated_or_used_to_activate_search(tmp_path):
    d,state,actions=hunt_session(tmp_path)
    def no_gain(*a,**kw):actions.append('claim-unverified')
    d.b.click_text=no_gain
    with pytest.raises(TaskBlocked,match='到账未核实'):d.hunt()
    assert actions==['open-free','claim-unverified'] and state['targets']==0
    with pytest.raises(TaskBlocked,match='不重复领取'):d.claim_free_stamina()
    assert actions==['open-free','claim-unverified']


def test_real_batch_has_three_targets_and_cost_is_ten_each():
    from chao2.activities import hunt_rows,HUNT_BATCH_SIZE,HUNT_STAMINA_COST
    s=captured('hunt-targets')
    assert len(hunt_rows(s))==HUNT_BATCH_SIZE==3
    assert HUNT_STAMINA_COST==10
