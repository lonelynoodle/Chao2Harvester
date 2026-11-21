"""Configuration behavior, budgets and real captured page recognition; no game input."""
import copy
import json
import time
from datetime import datetime
from pathlib import Path
import numpy as np
import pytest
from PIL import Image
from chao2.backend import Backend,Screen,Word,ROOT
from chao2.configuration import normalize_settings,plan_tasks,run_team_plan,team_order,selected_rows,SPECS,COCOON_CARDS
from chao2.activities import friend_quota,next_tower_floor,secret_candidates,main_nodes,main_identity,encounter_identity,giant_is_open,BudgetReached,DUNGEON_RESOURCES
from chao2.workflows import Daily,ORDER,is_failure
from chao2.policy import SafetyStop,UserStopped,FightLost,TaskBlocked

def screen(*texts):
    return Screen(np.zeros((720,1280,3),np.uint8),[Word(t,[x,y,w,h],.99) for t,x,y,w,h in texts],time.monotonic())

def captured(name,pixels=False):
    path=ROOT/'tests/fixtures'/name
    if not path.with_suffix('.json').is_file() or (pixels and not path.with_suffix('.png').is_file()):
        pytest.skip('Private game capture is not distributed: '+name,allow_module_level=True)
    words=[Word(**r) for r in json.loads(path.with_suffix('.json').read_text('utf-8'))]
    im=np.array(Image.open(path.with_suffix('.png')).convert('RGB'))[:,:,::-1].copy() if pixels else np.zeros((720,1280,3),np.uint8)
    return Screen(im,words,time.monotonic())

def daily(tmp_path,options=None):
    b=Backend(options or {});b.log=lambda _:None
    d=Daily(b,{'folder':tmp_path,'events':[]});d.state_file=tmp_path/'state.json'
    # Tests must not inherit unresolved transactions from the live account.
    d.state={};d.day=d.state.setdefault(d.date,{})
    return d

def test_migration_preserves_choices_and_connection_without_enabling_new_tasks():
    old={'address':'127.0.0.1:9999','tasks':['copies'],'close_mumu':False,'custom_key':'keep'}
    new=normalize_settings(old)
    assert all(new[k]==v for k,v in old.items())
    assert old=={'address':'127.0.0.1:9999','tasks':['copies'],'close_mumu':False,'custom_key':'keep'}
    assert set(new['task_options'])==set(ORDER)|{'giant','triad'}
    assert 'include_friends' in new['task_options']['copies']
    assert set(new['task_options']['copies'])=={'teams','wall_mode','max_runs','include_friends','challenge_copies','wandering_sage','sage_until_end','auto_three_shots','auto_potions'}

def test_stamina_priority_filters_disabled_tasks_and_preserves_other_task_order():
    s=normalize_settings({'stamina_order':['main','copies','hunt']})
    assert plan_tasks(s,['tower','copies','main','three_shots','rewards'],ORDER)==['main','copies','tower','rewards']
    assert plan_tasks(s,['hunt','idle','giant'],ORDER)==['hunt','celebration','rewards']

@pytest.mark.parametrize('bad',[
    {'stamina_order':['main','main','copies']},
    {'task_options':{'copies':{'include_friends':'yes'}}},
    {'task_options':{'tower':{'max_runs':-1}}},
    {'task_options':{'cocoon':{'reserve_spikes_enabled':'yes'}}},
    {'task_options':{'main':{'teams':[{'id':'1','enabled':True},{'id':'1','enabled':True}]}}},
    {'task_options':{'main':{'teams':[1,1]}}},
    {'task_options':{'main':{'teams':[6]}}},
    {'task_options':{'main':{'teams':[True]}}},
    {'stamina_settings':{'auto_three_shots':'yes'}},
    {'task_options':{'tower':{'reserve_feathers':-1}}},
    {'task_options':{'cocoon':{'reserve_spikes':1.5}}},
    {'task_options':{'tower':{'towers':[{'id':'normal'},{'id':'normal'}]}}},
])
def test_invalid_settings_rejected_before_device_connection(bad):
    with pytest.raises(ValueError):normalize_settings(bad)

def test_saved_team_order_and_empty_selection():
    s=normalize_settings({'task_options':{'main':{'teams':[{'id':'3','enabled':True},{'id':'1','enabled':True},{'id':'2','enabled':False}]}}})
    assert team_order(s['task_options']['main'])==[3,1]
    assert team_order(normalize_settings({})['task_options']['copies'])==[None]

def test_clear_stops_after_first_win_but_score_runs_all_teams():
    seen=[]
    def attempt(team):seen.append(team);return 'failed' if team==2 else 'victory'
    assert run_team_plan([2,1,3],'clear',attempt)==[(2,'failed'),(1,'victory')]
    assert seen==[2,1]
    seen.clear();run_team_plan([2,1,3],'score',attempt)
    assert seen==[2,1,3]
    assert len(run_team_plan([3,2,1],'clear',lambda _:'failed'))==3

@pytest.mark.parametrize('error',[UserStopped('stop'),SafetyStop('unknown page')])
def test_stop_or_unknown_never_advances_to_another_team(error):
    seen=[]
    def attempt(team):seen.append(team);raise error
    with pytest.raises(type(error)):run_team_plan([1,2,3],'clear',attempt)
    assert seen==[1]
    with pytest.raises(RuntimeError):run_team_plan([1,2],'clear',lambda _:'loading')

def test_real_captured_tower_and_secret_progress():
    assert next_tower_floor(captured('tower-map'))[0]==161
    assert secret_candidates(captured('secret-detail',True))==['塔中秘庭31','塔中秘庭32']

def test_map_candidates_do_not_include_completed_white_nodes_or_hud():
    assert main_nodes(captured('main-map',True))==[(746,402)]
    assert main_identity(captured('main-entry'))=='525'
    assert encounter_identity(captured('copy-current-detail'))=='Vesna'

def test_giant_uses_client_opening_time_including_boundary():
    s=captured('giant-menu')
    assert giant_is_open(s,datetime(2026,10,13,5,59)) is False
    assert giant_is_open(s,datetime(2026,10,13,6,0)) is True
    assert giant_is_open(s,datetime(2026,10,13,22,59)) is True
    assert giant_is_open(s,datetime(2026,10,13,23,0)) is False
    assert giant_is_open(screen()) is None

def test_weekly_cap_and_actual_positive_coin_are_both_required(tmp_path):
    assert friend_quota('本周已获取友好点数428')==(428,1000)
    assert friend_quota('本周已获得友好点数 998/1000')==(998,1000)
    assert friend_quota('额度未识别')==(None,None)
    d=daily(tmp_path,{'task_options':{'copies':{'include_friends':True}}})
    d.b.match_template=lambda s,name,*_:name=='copy-friend-coin.png'
    d.b.read_number=lambda *_:20
    assert d.copy_kind(screen(),(428,1000))=='friend'
    for quota in [(1000,1000),(None,None),(1001,1000)]:assert d.copy_kind(screen(),quota) is None
    d.b.read_number=lambda *_:0
    assert d.copy_kind(screen(),(428,1000)) is None
    d.b.read_number=lambda *_:None
    assert d.copy_kind(screen(),(428,1000)) is None
    d.b.match_template=lambda s,name,*_:name=='copy-own-exp50.png'
    assert d.copy_kind(screen(),(1000,1000))=='own'

def test_actual_encounter_rotation_obeys_total_attempt_budget(tmp_path):
    d=daily(tmp_path,{'task_options':{'main':{'max_runs':2}}})
    chosen=[]
    detail=screen(('敌方阵容',1100,135,100,30),('排阵',824,614,60,30),('前往挑战',1036,604,100,30))
    failure=screen(('挑战失败',100,200,400,50),('退出',1140,580,60,30))
    success=screen(('胜利',100,200,400,50),('获得奖励',900,300,100,30),('退出',1140,580,60,30))
    def select(s,team):chosen.append(team);d.observe=lambda:failure if team==1 else success;return s
    d.select_team=select;d.exit_result=lambda _:None;d.b.click_text=lambda *_:None
    # This test isolates attempt budgets; stage stability has dedicated coverage.
    d.stable_main_detail=lambda s,*args:s
    assert d.play_encounter('main',lambda:detail,'test') is True
    assert chosen==[1,2] and d.task_counts['main']==2
    with pytest.raises(BudgetReached):d.play_encounter('main',lambda:detail,'test')
    assert chosen==[1,2]

def test_disabled_secret_garden_never_enters_it_even_with_feathers_zero(tmp_path):
    d=daily(tmp_path);d.options['tower']['secret_garden']=False
    d.b.tasker=object();d.b.read_text_region=lambda *a,**kw:'0/20'
    d.options['tower']['towers']=[{'id':'dragon','label':'祖龙族','enabled':True}]
    opened=[]
    def open_tower(kind):opened.append(kind['id']);return screen(('浮空巨塔',124,14,90,30),('0/20',1124,15,56,26),('塔中秘庭31',950,580,160,36))
    d.open_tower=open_tower;d.home=lambda:None
    d.b.click_text=lambda *_:pytest.fail('Secret entry must not be clicked')
    assert '秘庭0关' in d.tower()
    assert opened==['dragon']

def test_cocoon_material_priority_and_client_quota_reach_actual_execution(tmp_path,monkeypatch):
    from tests.test_cocoon_refresh import CocoonGame
    g=CocoonGame(tmp_path,monkeypatch,spikes=3,quotas={'spore':1},options={
        'daily_tasks':False,'targets':[{'id':'spore','enabled':True},{'id':'gold','enabled':True}]})
    g.d.cocoon()
    assert g.inputs==['spore','gold','gold']
    assert g.d.report['cocoon_counts']=={'spore':1,'gold':2}


def test_main_failure_recognized_when_decorative_failure_title_is_missed(tmp_path):
    d=daily(tmp_path);s=captured('main-defeat');d.observe=lambda:s
    with pytest.raises(FightLost):d.battle('主线体力5')
    assert d.report['battles'][0]['result']=='failed'
    assert not is_failure(screen(('不怕失败',10,12,100,24),('暂停',1160,680,60,30)))

def test_giant_does_not_skip_later_teams_after_first_score(tmp_path,monkeypatch):
    d=daily(tmp_path)
    d.options['giant']['teams']=[1,2,3]
    menu=screen(('进击巨物',280,442,232,58),('开始挑战',334,627,136,33),('我的排名',894,669,83,24),('总伤害0',1165,671,88,22))
    later=screen(('进击巨物',280,442,232,58),('开始挑战',334,627,136,33),('我的排名',894,669,83,24),('总伤害1000',1150,671,105,22))
    detail=captured('v077-giant-ready')
    calls=[];d.giant_menu=lambda:menu if not calls else later
    d.giant_ready=lambda:detail
    def choose(s,t,return_page=None):
        calls.append(t);assert return_page is d.giant_ready;return return_page()
    d.select_team=choose;d.giant_settlement=lambda:1000;d.home=lambda:None;d.b.click_text=lambda *_:None
    d.start_challenge=lambda *a:None  # This test isolates formation order, not game entry.
    monkeypatch.setattr('chao2.activities.giant_is_open',lambda _:True)
    assert '3套' in d.giant() and calls==[1,2,3]
    calls.clear();d.giant_menu=lambda:later
    assert '跳过' in d.giant() and calls==[]

def test_three_shots_uses_selected_priority_after_actual_claim(tmp_path):
    d=daily(tmp_path,{'stamina_order':['main','hunt','copies']});d.selected=['main','copies']
    balance=[10];mode=['world'];called=[]
    d.home=lambda:screen();d.world_resources=lambda _:{'stamina':balance[0],'stamina_cap':161}
    d.stamina_outlet_available=lambda _,remaining:remaining<20
    d.stamina_offer=lambda:screen(('领取',500,500,70,25))
    def click_text(s,p,**kw):
        if p=='每日三发':mode[0]='claim'
        else:balance[0]+=100;mode[0]='reward'
    d.b.click_text=click_text;d.b.click_at=lambda *a,**kw:None
    d.click_world=lambda *a:None
    d.observe=lambda:screen(('领取',500,500,70,25)) if mode[0]=='claim' else screen(('获得',500,400,70,25))
    def run(key):called.append(key);balance[0]-=20;return key
    d.main=lambda:run('main');d.copies=lambda:run('copies');d.hunt=lambda:pytest.fail('Disabled hunt ran')
    assert '领取1份' in d.replenish_stamina()
    assert called==['main','copies'] and balance[0]==70
    assert d.report['stamina_claims']==1 and d.report['tasks']['copies']['status']=='done'

def test_removed_tasks_migrate_to_one_rewards_task_and_idle_defaults_on():
    old={'tasks':['idle','overview','daily_rewards','copies','rewards','three_shots'],
         'task_options':{'idle':{'min_minutes':1440},'overview':{'save_details':True}}}
    s=normalize_settings(old)
    assert s['tasks']==['rewards','copies'] and set(s['task_options'])==set(ORDER)|{'giant','triad'}
    assert s['task_options']['rewards']['collect_idle'] is True
    assert s['stamina_settings']['auto_three_shots'] is True
    assert normalize_settings(s)==s

def test_team_rows_can_be_added_removed_and_reordered_without_reappearing():
    s=normalize_settings({'task_options':{'main':{'teams':[5,2,3]}}})
    assert team_order(s['task_options']['main'])==[5,2,3]
    s['task_options']['main']['teams']=[]
    assert normalize_settings(s)['task_options']['main']['teams']==[]

def test_dungeon_lists_migrate_to_single_daily_checkbox_and_remove_material_limits():
    old={'schema_version':3,'task_options':{
        'tower':{'towers':[{'id':'dragon','enabled':True},{'id':'normal','enabled':False}]},
        'cocoon':{'targets':[{'id':'lower_right','enabled':True,'limit':0},
                            {'id':'gold','enabled':True,'limit':3},
                            {'id':'lower_left','enabled':False,'limit':0}]}}}
    new=normalize_settings(old)
    assert [r['id'] for r in new['task_options']['tower']['towers']]==['dragon']
    rows=new['task_options']['cocoon']['targets']
    assert [r['id'] for r in rows]==['gold'] and all('limit' not in r for r in rows)
    assert new['task_options']['cocoon']['daily_tasks'] is True
    assert new['task_options']['tower']['reserve_feathers']==0
    assert new['task_options']['cocoon']['reserve_spikes_enabled'] is False
    rows.reverse()
    assert normalize_settings(new)==new  # explicit new zero, order and deleted rows persist
    for task,key in [('tower','towers'),('cocoon','targets')]:
        new['task_options'][task][key]=[]
        assert normalize_settings(new)['task_options'][task][key]==[]
    defaults=normalize_settings({})['task_options']['cocoon']['targets']
    assert all(not r['id'].startswith('lower_') and 'limit' not in r for r in defaults)
    assert normalize_settings({})['task_options']['cocoon']['daily_tasks'] is True

def configure_fake_dungeon(d,task,balance,outcome='victory'):
    """Real task and team execution, with all device reads/input replaced in memory."""
    state={'balance':balance,'inputs':0,'page':'detail','teams':[],'floor':1}
    def detail():return screen(('敌方阵容',1130,136,100,28),('排阵',824,614,60,35),
                              ('挑战',1060,603,61,34),(f'浮空巨塔{state["floor"]}',233,105,151,28),
                              (f'{state["balance"]}/20',1210,15,60,26))
    def result():return screen(('胜利' if outcome=='victory' else '挑战失败',100,200,100,30),
                  ('获得奖励',900,300,100,30),('退出',1140,580,60,30),
                  (f'{state["balance"]}/20',1210,15,60,26))
    def menu():return screen(('浮空巨塔',124,14,90,30),(str(state['floor']),269,218,120,44),
                            ('已通关',290,360,80,28),(str(state['floor']-1),269,400,120,44),
                            (f'{state["balance"]}/20',1124,15,56,26))
    def leave(_):
        state.update(page='menu',floor=state['floor']+(outcome=='victory'))
        return d.observe()
    d.home=lambda:None;d.exit_result=leave
    d.b.sleep=lambda _:None
    def select(q,team):state['teams'].append(team);return q
    def enter(*args,**kwargs):state['page']='detail'
    def start(*args,**kwargs):state.update(balance=state['balance']-1,inputs=state['inputs']+1,page='result')
    d.select_team=select;d.b.click_at=enter;d.b.click_text=start
    d.observe=lambda *args:result() if state['page']=='result' else menu() if task=='tower' and state['page']=='menu' else detail()
    d.await_detail=lambda:detail()
    if task=='tower':
        d.b.tasker=object()
        d.b.read_text_region=lambda *a,**kw:f'{state["balance"]}/20'
        d.options[task]['secret_garden']=False
        d.options[task]['towers']=[{'id':'normal','label':'无限制','enabled':True}]
        d.open_tower=lambda _:menu()
    else:
        d.options[task]['daily_tasks']=False
        d.options[task]['refresh_tasks']=True
        d.options[task]['targets']=[{'id':'gold','label':'富有（金币）','enabled':True,'limit':0}]
        d.enter_overview=lambda _:screen(('永生之茧',124,14,90,30),('刷新',612,496,54,33),
                                         (f'{state["balance"]}/20',1001,15,45,26))
    return state

@pytest.mark.parametrize('task',['tower','cocoon'])
@pytest.mark.parametrize('reserve',[0,3,5,30])
def test_dungeon_executes_only_above_reserved_balance(tmp_path,task,reserve):
    d=daily(tmp_path);key,_=DUNGEON_RESOURCES[task];d.options[task][key]=reserve
    if task=='cocoon':d.options[task]['reserve_spikes_enabled']=reserve>0
    state=configure_fake_dungeon(d,task,7)
    getattr(d,task)()
    assert state['balance']==min(7,reserve)
    assert state['inputs']==7-min(7,reserve)
    assert d.report['dungeon_resources'][task]['remaining']==state['balance']

@pytest.mark.parametrize('task',['tower','cocoon'])
def test_failed_fight_does_not_spend_reserve_on_fallback_team(tmp_path,task):
    d=daily(tmp_path);key,_=DUNGEON_RESOURCES[task]
    d.options[task].update({key:3,'teams':[1,2,3]})
    if task=='cocoon':d.options[task]['reserve_spikes_enabled']=True
    state=configure_fake_dungeon(d,task,4,outcome='failed')
    try:getattr(d,task)()
    except BudgetReached:pass
    assert state['inputs']==1 and state['balance']==3
    assert [(a['team'],a['outcome']) for a in d.report['team_attempts']]==[(1,'failed')]

def test_tower_checks_secrets_while_leaving_feathers_at_reserve(tmp_path):
    d=daily(tmp_path);d.options['tower']['reserve_feathers']=5
    state=configure_fake_dungeon(d,'tower',5);d.options['tower']['secret_garden']=True
    called=[];d.tower_secrets=lambda kind,attempted:called.append(kind['id']) or 1
    assert '秘庭1关' in d.tower() and called==['normal']
    assert state['inputs']==0 and state['balance']==5

@pytest.mark.parametrize('task',['tower','cocoon'])
def test_unreadable_dungeon_resource_never_starts_battle(tmp_path,task):
    d=daily(tmp_path);d.options[task]['teams']=[1]
    detail=screen(('敌方阵容',1130,136,100,28),('排阵',824,614,60,35),('挑战',1060,603,61,34))
    d.select_team=lambda s,t:s;d.b.click_text=lambda *args:pytest.fail('Unreadable resource cannot be spent')
    with pytest.raises(TaskBlocked,match='余额未识别'):
        d.play_encounter(task,lambda:detail,'test',lambda s:d.verify_dungeon_resource(task,s))

@pytest.mark.parametrize('collect',[True,False])
def test_rewards_collects_idle_only_when_enabled_without_a_time_threshold(tmp_path,collect):
    d=daily(tmp_path,{'task_options':{'rewards':{'collect_idle':collect}}})
    calls=[]
    d.collect_idle=lambda:calls.append('idle') or '已收获'
    d.collect_task_tab=lambda tab,batches:calls.append(tab) or 1
    d.collect_world_echoes=lambda:''
    assert '3 批' in d.rewards()
    assert calls==(['idle'] if collect else [])+['每日挑战','支线冒险','主线任务']

def test_disabled_refill_never_navigates_or_claims(tmp_path):
    d=daily(tmp_path,{'stamina_settings':{'auto_three_shots':False}});d.selected=['main']
    d.home=lambda:pytest.fail('Disabled refill must not navigate')
    assert '关闭' in d.replenish_stamina()

@pytest.mark.parametrize('selected,balance,cap,outlet',[
    ([],0,161,True),(['main'],80,161,True),(['main'],0,161,False),(['main'],None,161,True)
])
def test_refill_does_not_claim_without_capacity_selection_and_target(tmp_path,selected,balance,cap,outlet):
    d=daily(tmp_path);d.selected=selected;d.home=lambda:screen()
    d.world_resources=lambda _:{'stamina':balance,'stamina_cap':cap}
    d.stamina_outlet_available=lambda *_:outlet
    d.stamina_offer=lambda:screen(('领取',500,500,70,25))
    d.b.click_at=lambda *a:pytest.fail('Unsafe or unnecessary refill')
    d.replenish_stamina()

def test_refill_stops_if_new_stamina_was_not_spent(tmp_path):
    d=daily(tmp_path);d.selected=['main'];balance=[0]
    d.home=lambda:screen();d.world_resources=lambda _:{'stamina':balance[0],'stamina_cap':161}
    d.stamina_outlet_available=lambda *_:True
    d.stamina_offer=lambda:screen(('领取',500,500,70,25))
    d.b.click_at=lambda *a:None
    d.click_world=lambda *a:None
    def click(s,p,**kw):
        if p!='每日三发':balance[0]+=100
    d.b.click_text=click;d.observe=lambda:screen(('领取',500,500,70,25))
    d.main=lambda:'无法继续'
    d.replenish_stamina()
    assert balance[0]==100 and d.report['stamina_claims']==1

def test_refill_checks_actual_need_and_budget_before_probing_target(tmp_path):
    d=daily(tmp_path)
    d.copy_targets=lambda *a:pytest.fail('Enough stamina or capped task should not be probed')
    assert not d.stamina_outlet_available(['copies'],20)
    d.options['copies']['max_runs']=1;d.task_counts['copies']=1
    assert not d.stamina_outlet_available(['copies'],0)

def test_hunt_refill_checks_search_offer_without_spending_until_hunt_resumes(tmp_path):
    d=daily(tmp_path);d.selected=['hunt'];calls=[]
    d.b.read_number=lambda *a:None
    empty=screen(('狩猎',970,19,63,39),('商店',1074,95,48,26),('猎物未出现',946,435,114,24),
                 ('免费搜索',1066,669,100,28),('100/166',502,17,90,22))
    prey=screen(('狩猎',970,19,63,39),('商店',1074,95,48,26),
                ('10',1084,234,24,17),('10',1084,366,24,17),('10',1084,501,24,17))
    d.hunt_menu=lambda:empty;d.home=lambda:None
    d.b.click_text=lambda s,p:calls.append(p);d.b.sleep=lambda _:None;d.observe=lambda:prey
    assert d.stamina_outlet_available(['hunt'],0) is True
    assert calls==[] and d.search_counts.get('hunt',0)==0
    d.search_hunters(empty)
    assert calls==['^免费搜索$'] and d.search_counts['hunt']==1
    d.options['hunt']['max_searches']=1
    assert d.stamina_outlet_available(['hunt'],0) is False
    assert len(calls)==1

@pytest.mark.parametrize('enabled',[True,False])
def test_real_daily_planner_refills_after_stamina_group_and_before_other_tasks(tmp_path,monkeypatch,enabled):
    import threading
    import chao2.workflows as flow
    calls=[]
    monkeypatch.setattr(flow.Backend,'connect',lambda _:None)
    monkeypatch.setattr(flow,'create_report',lambda:{'folder':tmp_path,'tasks':{},'events':[]})
    monkeypatch.setattr(flow.Daily,'home',lambda _:screen())
    monkeypatch.setattr(flow.Daily,'world_resources',lambda *_:{'stamina':0,'stamina_cap':161,'diamonds':200})
    monkeypatch.setattr(flow.Daily,'restore_world_team',lambda _:None)
    monkeypatch.setattr(flow.Daily,'save_state',lambda _:None)
    for key in ('copies','main','tower','rewards'):
        monkeypatch.setattr(flow.Daily,key,lambda self,key=key:calls.append(key) or 'done')
    monkeypatch.setattr(flow.Daily,'replenish_stamina',lambda _:calls.append('refill') or 'done')
    result=flow.run_daily({'stamina_order':['main','copies','hunt'],'stamina_settings':{'auto_three_shots':enabled}},
                          ['main','copies','tower','rewards'],threading.Event(),log=lambda _:None)
    assert result['status']=='completed'
    assert calls==['main','copies']+(['refill'] if enabled else [])+['tower','rewards']

def test_hunt_search_limit_is_shared_with_post_three_shots_rerun(tmp_path):
    d=daily(tmp_path);d.options['hunt']['max_searches']=1
    d.b.read_number=lambda *a:None
    state={'prey':0,'searches':0}
    def menu():
        common=[('狩猎',970,19,63,39),('商店',1074,95,48,26),('传送',1218,340,48,30),('161/161',502,17,78,22)]
        return screen(*common,*([('10',1084,234+i*130,24,17) for i in range(state['prey'])] if state['prey'] else [('猎物未出现',946,435,114,24),('免费搜索',1066,669,100,28)]))
    detail=screen(('敌方阵容',1130,135,103,28),('排阵',824,614,61,34),('前往挑战',1036,607,109,28),('未知',134,136,58,30),('09:35',602,135,72,26),('10',1096,639,28,18),('161/161',1185,17,76,22))
    def search(*a,**kw):state['prey']=3;state['searches']+=1
    d.b.click_text=search;d.b.click_at=lambda *a,**kw:None;d.b.sleep=lambda _:None
    d.hunt_menu=menu;d.observe=menu;d.await_detail=lambda **_:detail;d.home=lambda:None
    def play(task,opener,resource,verify):
        verify(opener());state['prey']-=1;return True
    d.play_encounter=play
    d.hunt();d.hunt()
    assert state['searches']==1 and d.search_counts['hunt']==1
