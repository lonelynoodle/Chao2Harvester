"""Regression checks for per-task spending, settlement and daily leaf receipts."""
import copy
import json
import threading
from types import SimpleNamespace
import cv2
import numpy as np
import pytest
from test_configuration import daily,captured,screen
from chao2.configuration import normalize_settings,plan_tasks,RAMPAGE_BUFFS
from chao2.workflows import ORDER
from chao2.daily_challenges import rampage_buff
from chao2.policy import SafetyStop,TaskBlocked,is_stamina_potion_dialog,is_stamina_potion_confirmation
from chao2.puzzle import daily_leaves_claimed,puzzle_daily
from chao2.rift import rift_detail,rift_level_locked


def test_new_defaults_migrate_old_refill_preference_without_enabling_potions():
    old={'tasks':['main'],'stamina_settings':{'auto_three_shots':False},
         'task_options':{'main':{'teams':[3,2],'auto_three_shots':True}}}
    new=normalize_settings(old)
    assert new['task_options']['main']['teams']==[3,2]
    assert new['task_options']['main']['auto_three_shots']
    assert not new['task_options']['hunt']['auto_three_shots']
    assert not any(new['task_options'][t]['auto_potions'] for t in ('main','hunt','copies'))
    assert all(new['task_options'][t]['auto_settle'] for t in ('origin','arena'))
    assert new['tasks']==['main'] and 'finish' not in old['task_options']
    assert plan_tasks(new,['finish','main','other'],ORDER)==['main','other','finish']


def test_refill_does_not_probe_disabled_task_to_justify_claim(tmp_path):
    d=daily(tmp_path,{'task_options':{'copies':{'auto_three_shots':False},'main':{'auto_three_shots':True}}})
    d.selected=['copies','main'];d.home=lambda:screen()
    d.world_resources=lambda _:{'stamina':0,'stamina_cap':166}
    d.stamina_offer=lambda:screen(('领取',500,500,50,20))
    seen=[];d.stamina_outlet_available=lambda tasks,b:seen.append(tasks) or False
    d.b.click_text=lambda *a,**k:pytest.fail('No spendable outlet')
    d.use_stamina_potion=lambda:pytest.fail('Potions default off')
    d.replenish_stamina();assert seen==[['main']]


def test_disabled_potion_has_no_navigation(tmp_path):
    d=daily(tmp_path);d.selected=['main'];d.home=lambda:pytest.fail('No navigation')
    with pytest.raises(SafetyStop,match='未开启'):d.use_stamina_potion()


def test_potion_popup_exception_is_scoped_and_cannot_approve_other_consumption(tmp_path):
    d=daily(tmp_path);s=captured('v090-potion-dialog',True)
    assert is_stamina_potion_dialog(s)
    with pytest.raises(SafetyStop):d.b.guard(s)
    d.b.potion_dialog_active=True;d.b.guard(s)
    bad=copy.deepcopy(s);bad.words+=screen(('消耗钻石25',600,400,100,30)).words
    assert not is_stamina_potion_dialog(bad)
    with pytest.raises(SafetyStop):d.b.guard(bad)


def test_quantity_not_one_cancels_without_spending(tmp_path):
    d=daily(tmp_path,{'task_options':{'main':{'auto_potions':True}}});d.selected=['main']
    d.home=lambda:screen();d.world_resources=lambda _:{'stamina':0,'stamina_cap':166}
    d.potion_inventory=lambda:captured('v090-bag',True)
    d.await_page=lambda *a:captured('v090-potion-dialog',True)
    d.b.read_number=lambda *a:2;clicks=[]
    d.b.click_text=lambda s,p,**kw:clicks.append(p)
    with pytest.raises(TaskBlocked,match='不是1'):d.use_stamina_potion()
    assert clicks==['^使用$','^取消$'] and d.b.potion_dialog_active is False


def test_potion_wont_overflow(tmp_path):
    d=daily(tmp_path,{'task_options':{'main':{'auto_potions':True}}});d.selected=['main']
    d.home=lambda:screen();d.world_resources=lambda _:{'stamina':80,'stamina_cap':166}
    d.potion_inventory=lambda:pytest.fail('Would overflow')
    assert d.use_stamina_potion() is None


@pytest.mark.parametrize('balance,accepted',[(2,True),(36,False)])
def test_one_potion_second_confirmation_checks_capacity_then_verifies_receipt(tmp_path,balance,accepted):
    d=daily(tmp_path,{'task_options':{'main':{'auto_potions':True}}});d.selected=['main']
    bag=screen(('背包',132,12,60,30),('全部',30,196,50,28),('道具',38,310,55,35),
               ('元核',30,421,50,28),('移动力药水',850,103,140,26),
               ('使用后可获得100移动力',780,228,280,23),('已拥有6',850,150,135,25))
    quantity=screen(('移动力药水',570,273,139,27),('已拥有6',596,309,92,24),('使用数量',334,363,83,24),
                    ('取消',456,459,53,29),('确定',770,459,55,30))
    dialog=screen(('是否消耗移动力药水回复100移动力?',416,299,433,26),('取消',454,480,55,32),
                  ('确定',770,481,55,31),(f'{balance}/135',1206,15,56,26))
    assert is_stamina_potion_confirmation(dialog)
    with pytest.raises(SafetyStop):d.b.guard(dialog)
    after=copy.deepcopy(bag);after.words[-1].text='已拥有5'
    pages=iter([dialog,after]);clicks=[]
    resources=iter([{'stamina':2,'stamina_cap':135},{'stamina':102,'stamina_cap':135}])
    d.home=lambda:screen();d.world_resources=lambda _:next(resources)
    d.potion_inventory=lambda:bag;d.await_page=lambda *a:quantity
    d.observe=lambda:next(pages);d.b.read_number=lambda *a:1
    d.b.click_text=lambda s,p,**kw:clicks.append(p)
    d.b.click_at=lambda s,p,a,reason:clicks.append(reason)
    if accepted:
        assert d.use_stamina_potion()==100
        assert d.report['stamina_potions'][0]['stock_after']==5
        assert clicks[-1]=='确认使用一瓶库存药水恢复100移动力'
    else:
        with pytest.raises(TaskBlocked,match='可容纳100移动力'):d.use_stamina_potion()
        assert clicks[-1]=='取消库存药水使用'
    assert len(clicks)==3 and not d.b.potion_confirmation_active


@pytest.mark.parametrize('enabled',[True,False])
@pytest.mark.parametrize('task',['arena','origin'])
def test_pvp_settle_rechecks_visible_control_and_still_waits_for_result(tmp_path,enabled,task):
    d=daily(tmp_path);d.options[task]['auto_settle']=enabled
    battle=screen(('结算',145,594,85,32),('01:38',570,7,95,30))
    result=captured('v076-origin-failed',True)
    frames=iter([battle,battle,result]);d.observe=lambda:next(frames)
    d.b.sleep=lambda _:None;clicks=[];d.b.click_at=lambda s,p,*a:clicks.append(p)
    d.retry_battle_network=lambda *a:False
    assert d.pvp_battle(task)[1]=='failed'
    assert clicks==([battle.find('^结算$').center]*2 if enabled else [])
    assert d.battles==d.task_counts[task]==1


def test_settle_crop_requires_exact_label_and_battle_context():
    from chao2.daily_challenges import pvp_settle_button
    battle=screen(('结',165,604,32,20),('自动',94,602,46,25),('00:10',601,6,77,28))
    assert pvp_settle_button(battle,lambda *a:'结') is None
    assert pvp_settle_button(battle,lambda *a:'结算').center==(187,614)
    menu=screen(('结',165,604,32,20),('自动',94,602,46,25))
    assert pvp_settle_button(menu,lambda *a:pytest.fail('Not a battle')) is None


def test_rampage_priority_default_and_reorder_change_actual_choice():
    s=screen(('请选择一个暴走增益',400,100,400,30),
      ('怪兽攻击力提升10%',60,200,230,30),('点击选择',100,500,100,30),
      ('怪兽吸血提升10%',470,200,230,30),('点击选择',550,500,100,30),
      ('怪兽助战',900,200,230,30),('点击选择',1000,500,100,30))
    assert '助战' in rampage_buff(s)[1]
    opts=normalize_settings({})['task_options']['nest']['buff_priority']
    opts.sort(key=lambda r:r['id']!='attack')
    assert '攻击力' in rampage_buff(s,opts)[1]
    assert [r[0] for r in RAMPAGE_BUFFS[:4]]==['assist','lifesteal','attack','level']


def test_claimed_daily_puzzle_skips_without_play_or_claim(tmp_path):
    d=daily(tmp_path);s=captured('v090-leaf-done',True);d.observe=lambda:s
    d.b.click_at=lambda *a:pytest.fail('Already claimed')
    assert daily_leaves_claimed(s)
    assert '已全部领取' in puzzle_daily(d)['message']


def test_rift_locked_modal_is_identified_without_dim_header():
    s=captured('v090-rift-blocked',True)
    assert rift_detail(s)==25 and rift_level_locked(s)


def test_arena_59670_does_not_collapse_to_5670(tmp_path):
    from chao2.power_digits import arena_power_digits
    s=captured('v090-arena-blocked',True)
    assert arena_power_digits(s,(1112,432,91,35))==59670
    d=daily(tmp_path);d.b.read_text_region=lambda *a,**kw:pytest.fail('Use segmented digits')
    assert d.read_arena_power(s,(1112,432,91,35))==59670


def test_yellow_main_dot_with_red_swords_is_found():
    from chao2.activities import main_nodes
    points=main_nodes(captured('v090-main-yellow',True))
    assert any(abs(x-640)<5 and abs(y-360)<5 for x,y in points)


def test_unjoined_tribe_is_reported_without_challenge_or_join(tmp_path):
    from chao2.activities import BudgetReached
    d=daily(tmp_path);page=captured('v090-tribe-unjoined',True)
    d.observe=lambda:screen();d.territory=lambda:screen(('世界',1190,660,70,30),('排阵',710,660,70,30))
    def missing(*a):raise TaskBlocked('玩法概览中未找到入口：^部落冒险$')
    d.enter_overview=missing;clicks=[];d.b.click_at=lambda s,p,a,r:clicks.append(p)
    d.await_page=lambda *a:page
    with pytest.raises(BudgetReached,match='未加入部落'):d.tribe_detail()
    assert clicks==[(1042,535)]


def test_stamina_potion_success_verifies_one_stock_and_100_gain(tmp_path):
    d=daily(tmp_path,{'task_options':{'main':{'auto_potions':True}}});d.selected=['main']
    bag=captured('v090-bag',True);after=copy.deepcopy(bag)
    for w in after.words:
        if w.text=='已拥有152':w.text='已拥有151'
    d.home=lambda:screen();resources=iter([{'stamina':0,'stamina_cap':166},{'stamina':100,'stamina_cap':166}])
    d.world_resources=lambda _:next(resources);d.potion_inventory=lambda:bag
    d.await_page=lambda *a:captured('v090-potion-dialog',True);d.b.read_number=lambda *a:1
    d.observe=lambda:after;clicks=[];d.b.click_text=lambda s,p,**kw:clicks.append(p)
    assert d.use_stamina_potion()==100
    assert clicks==['^使用$','^确定$']
    assert d.report['stamina_potions'][0]['status']=='confirmed'
    assert d.report['stamina_potions'][0]['stock_after']==151


def test_forest_branch_registration_works_without_corner_features():
    from chao2.forest import forest_dense_shift
    s=captured('v090-forest-blocked',True);after=copy.deepcopy(s)
    after.image=cv2.warpAffine(s.image,np.float32([[1,0,-150],[0,1,-80]]),(1280,720))
    assert forest_dense_shift(s,after)==pytest.approx((-150,-80),abs=3)
    assert forest_dense_shift(screen(),screen()) is None


@pytest.mark.parametrize('blocked',[True,False])
def test_finish_saves_first_and_never_closes_on_partial_run(tmp_path,monkeypatch,blocked):
    import chao2.workflows as flow
    monkeypatch.setattr(flow,'create_report',lambda:{'folder':tmp_path,'tasks':{},'events':[]})
    monkeypatch.setattr(flow.Backend,'connect',lambda _:None)
    monkeypatch.setattr(flow.Daily,'home',lambda _:screen())
    monkeypatch.setattr(flow.Daily,'world_resources',lambda *_:{'stamina':0,'stamina_cap':166,'diamonds':300})
    monkeypatch.setattr(flow.Daily,'restore_world_team',lambda _:None)
    monkeypatch.setattr(flow.Daily,'save_state',lambda _:None)
    def activity(self):
        if blocked:raise TaskBlocked('unreadable')
        return 'done'
    monkeypatch.setattr(flow.Daily,'exploration',activity)
    closes=[]
    def close(*a):
        assert json.loads((tmp_path/'report.json').read_text('utf-8'))['resources_end']['diamonds']==300
        closes.append('closed');return True
    monkeypatch.setattr(flow,'close_game_and_mumu',close)
    report=flow.run_daily({},['finish','exploration'],threading.Event(),log=lambda _:None)
    assert report['tasks']['finish']['status']==('skipped' if blocked else 'done')
    assert bool(report.get('close_app_requested')) is not blocked
    assert closes==([] if blocked else ['closed'])
