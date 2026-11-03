"""Grade-only capture, free tribe chests, and task state backtracking."""
import copy
import threading
from types import SimpleNamespace
import cv2
import numpy as np
import pytest
from test_configuration import daily,captured,screen
from test_wild_capture import configured,page,entry,unreadable_title,unreadable_grade,prepare_frames
from chao2.wild_capture import wild_identity,wild_cards,is_wild_offer
from chao2.tribe_chests import tribe_chests
from chao2.policy import PageChanged,TaskBlocked,SafetyStop,UserStopped
from chao2.page_recovery import navigation_failure
from chao2.backend import MuMuController


@pytest.mark.parametrize('grade,hue',[('young',60),('phantom',105),('ultimate',136),('immortal',25),('awakened',2)])
def test_badge_grade_does_not_need_a_recognized_name(grade,hue):
    s=unreadable_title(page())
    s.image[22:57,524:559]=cv2.cvtColor(np.full((35,35,3),(hue,180,210),dtype=np.uint8),cv2.COLOR_HSV2BGR)
    assert wild_identity(s)=={'name':None,'rarity':grade}


def test_entire_capture_can_use_grade_without_any_name(tmp_path):
    d,inputs=configured(tmp_path,55);e=entry();e['name']='名称未识别'
    prepare_frames(d,[unreadable_title(page(55,87)),unreadable_title(page(55,87)),screen(('捕捉成功',500,200,150,45))])
    d.capture_wild(unreadable_title(page()),e,{'stamina':40})
    assert inputs==[(481,618),(836,632)] and e['status']=='captured'


def test_garbled_wild_card_and_offer_titles_are_navigable_without_guessing_name():
    s=captured('v097-wild-list',True)
    card=wild_cards(s)[0];card.text='野生-??0'
    assert wild_cards(s)==[card]
    s=captured('v097-wild-offer',True)
    next(w for w in s.words if w.text.startswith('野生-')).text='野生-??0'
    assert is_wild_offer(s) and wild_identity(s)['name'] is None
    assert wild_identity(s)['rarity']=='ultimate'


def test_real_chests_exclude_claimed_node_reward_popup_and_battle_node():
    before=tribe_chests(captured('v0962-tribe-chests',True))
    after=tribe_chests(captured('v0962-tribe-chest-after',True))
    assert len(before)==5 and len(after)==4
    assert not any(abs(p[0]-488)<12 for p in after)
    assert not any(abs(p[0]-970)<20 for p in before)
    assert not tribe_chests(captured('v0962-tribe-chest-reward',True))
    assert not tribe_chests(captured('v0962-exit-dialog',True))


def test_claim_records_actual_reward_and_never_challenges(tmp_path,monkeypatch):
    import chao2.tribe_chests as module
    d=daily(tmp_path);before=captured('v0962-tribe-chests',True)
    after=captured('v0962-tribe-chest-after',True);reward=captured('v0962-tribe-chest-reward',True)
    monkeypatch.setattr(module,'tribe_chests',lambda s:[(488,352)] if s is before else [])
    d.observe=lambda:before;inputs=[];d.b.click_at=lambda *a:inputs.append(a[1])
    d.wait_for_screen=lambda predicate,*a,**kw:reward if predicate(reward) else pytest.fail('Missing receipt')
    d.clear_tribe_reward=lambda s:after
    assert d.claim_visible_tribe_chests(before) is after and inputs==[(488,352)]
    assert d.report['tribe_chests'][0]['status']=='claimed' and d.battles==0


def test_full_chest_scan_reaches_both_edges_even_with_zero_orders(tmp_path):
    d=daily(tmp_path);d.b.tasker=object();s=captured('v0962-tribe-chest-after',True)
    d.tribe_map=lambda:s;directions=[];claims=[]
    d.claim_visible_tribe_chests=lambda q:claims.append(q) or q
    d.pan_tribe_map=lambda q,direction:directions.append(direction) or (q,False)
    d.check_budget=lambda *_:pytest.fail('Free chests do not need battle orders')
    assert d.collect_tribe_chests()==0 and directions==[1,-1] and len(claims)==2


@pytest.mark.parametrize('error',[PageChanged('复制此配置'),TaskBlocked('裂痕钥匙余额未读清'),TaskBlocked('部落地图未识别')])
def test_navigation_failures_are_recoverable(error):assert navigation_failure(error)


@pytest.mark.parametrize('error',[UserStopped('用户停止'),SafetyStop('裂痕开箱结果未确认'),
    TaskBlocked('捕兽夹使用后的概率+5%与库存-1未同时确认'),TaskBlocked('斗技场已结算，但免费次数变化未确认')])
def test_spend_uncertainty_and_user_stop_are_not_replayed(error):assert not navigation_failure(error)


def test_page_changed_returns_home_then_restarts_with_existing_counts(tmp_path):
    d=daily(tmp_path);d.b.tasker=object();d.b.controller=object();d.active_task='tribe'
    d.task_counts={'tribe':2};d.battles=2;calls=[];d.home=lambda:calls.append('home')
    def action():
        calls.append('task')
        if calls==['task']:raise PageChanged('复制此配置')
        assert d.task_counts=={'tribe':2} and d.battles==2
        return 'finished'
    assert d.with_page_recovery(action,'部落')=='finished'
    assert calls==['task','home','task'] and d.report['page_recoveries'][0]['status']=='reentered'


def test_repeated_failure_is_bounded_without_erasing_ledger(tmp_path):
    d=daily(tmp_path);d.b.tasker=object();d.b.controller=object();d.active_task='rift'
    d.task_counts={'rift':2};homes=[];d.home=lambda:homes.append(1)
    def action():raise TaskBlocked('钥匙余额未读清')
    with pytest.raises(TaskBlocked):d.with_page_recovery(action,'裂痕')
    assert len(homes)==3 and d.task_counts=={'rift':2}


def test_pending_key_spend_cannot_restart_task(tmp_path):
    d=daily(tmp_path);d.b.tasker=object();d.b.controller=object()
    d.report['rift_chests']=[{'status':'opening','keys_before':5}]
    assert not d.can_recover_page(TaskBlocked('页面未识别'))


def test_unknown_pages_backtrack_until_world_is_recognized(tmp_path):
    d=daily(tmp_path);d.b.tasker=object();d.b.controller=object();d.b.sleep=lambda _:None
    unknown=screen();world=captured('v089-world-misread')
    d.recover_world_navigation=lambda s:s
    from chao2 import workflows
    original=workflows.is_world
    # Synthetic stable world anchors; no new wild captures during recovery.
    world=screen(('任务挑战',1190,40,80,25),('世界回响',1190,130,80,25),('40/180',500,15,90,30))
    pages=iter([unknown]*6+[world]);d.observe=lambda:next(pages)
    backs=[];d.b.back=lambda s,reason:backs.append(s)
    assert d.home() is world and len(backs)==2


def test_other_completed_subtasks_are_not_replayed(tmp_path):
    d=daily(tmp_path)
    for key,value in d.options['other'].items():
        if type(value) is bool:d.options['other'][key]=False
    d.options['other'].update(collect_daily_single=True,collect_contract=True)
    d.report['other_tasks']={'daily_single':{'status':'done','message':'already claimed'}}
    d.collect_daily_single=lambda:pytest.fail('Completed reward must not run again')
    d.collect_contract=lambda:{'status':'done','message':'contract done'};d.home=lambda:None
    assert 'contract done' in d.other()


def test_visual_back_uses_game_arrow_and_unknown_frame_does_not_guess(tmp_path):
    d=daily(tmp_path);calls=[];d.b.click_at=lambda s,p,a,r:calls.append(p)
    s=captured('v0962-tribe-chests',True);s.words=[]
    d.b.back(s,'返回')
    assert len(calls)==1 and calls[0][0]<85 and calls[0][1]<60
    with pytest.raises(TaskBlocked,match='未确认返回'):d.b.back(screen(),'返回')


def test_quit_confirmation_is_cancelled_instead_of_exiting(tmp_path):
    from chao2.page_recovery import visual_return_control
    s=captured('v0962-exit-dialog',True)
    assert visual_return_control(s).text=='再玩一会'
