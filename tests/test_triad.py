"""Offline checks for the additional Fengye event; never touch MuMu."""
import pytest

from test_configuration import daily,screen
from chao2.configuration import normalize_settings
from chao2.event_hub import activity_entry,activity_availability,is_event_hub
from chao2.policy import TaskBlocked
from chao2.activities import BudgetReached
from chao2.puzzle import puzzle_daily
from chao2.triad import (is_triad_lobby,is_triad_matching,is_triad_battle,
                         triad_quota,triad_result)


def lobby(remaining=3):
    return screen(('三阵入局',100,20,140,35),('剩余挑战次数',850,580,145,35),
                  (str(remaining),1004,580,25,35),('匹配',1000,625,100,40))


def battle(round_number=1,settle=True):
    words=[('01:52',560,20,80,35),('自动',80,600,50,35),
           (f'第{round_number}阵',550,110,100,35)]
    if settle:words.append(('结算',160,600,60,35))
    return screen(*words)


def result(outcome='胜利'):
    return screen((outcome,300,200,150,70),('退出',1100,580,110,60))


def test_legacy_events_group_under_celebration_with_only_triad_enabled():
    old={'tasks':['startup','giant','other'], 'task_order':['startup','giant','other'],
         'task_options':{'giant':{'auto_settle':False,'teams':[1,2]}},
         'task_queue':[{'id':'giant','key':'giant','name':'进击巨物','enabled':True,
                        'options':{'auto_settle':False,'teams':[1,2]}}]}
    migrated=normalize_settings(old)
    assert migrated['tasks']==['startup','celebration','other']
    assert migrated['task_order']==['startup','celebration','other']
    group=migrated['task_options']['celebration']
    assert group['giant_auto_settle'] is False
    assert group['triad'] and not group['giant'] and not group['daily_puzzle']
    assert migrated['task_queue'][0]['key']=='celebration'
    assert migrated['task_queue'][0]['id']=='giant'
    assert migrated['task_queue'][0]['name']=='庆典活动'
    assert migrated['task_queue'][0]['options']['giant_auto_settle'] is False
    assert 'daily_puzzle' not in migrated['task_options']['other']
    assert old['task_queue'][0]['key']=='giant'


def test_lobby_quota_and_result_require_specific_evidence():
    assert is_triad_lobby(lobby(3)) and triad_quota(lobby(3))==3
    assert triad_quota(lobby(0))==0
    assert is_triad_matching(screen(('正在匹配',450,180,180,45),('取消匹配',550,600,120,45)))
    assert is_triad_battle(battle()) and not is_triad_lobby(battle())
    assert triad_result(result())=='victory'
    assert triad_result(result('失败'))=='failed'
    assert triad_result(battle()) is None
    # 1/3 in a score field cannot be treated as remaining free matches.
    assert triad_quota(screen(('三阵入局',100,20,140,35),('1/3',760,150,60,35),
                              ('匹配',1000,625,100,40))) is None


def test_new_event_entry_requires_confirmed_hub_and_skips_paid_card(tmp_path):
    d=daily(tmp_path);hub=screen(('丰野间',540,20,190,55),('活动时间:10/20-11/1',430,115,320,35),
                                  ('三阵入局',1000,270,130,40))
    assert is_event_hub(hub) and activity_entry(hub,'triad')
    entered=[];d.observe=lambda:hub;d.event_hub=lambda s:hub
    d.b.click_at=lambda s,point,anchors,reason:entered.append(reason)
    d.wait_for_screen=lambda *a,**k:lobby(3)
    assert d.triad_lobby() is not None and entered==['进入三阵入局']
    paid=screen(('三阵入局',100,20,140,35),('剩余挑战次数',850,580,145,35),
                ('1',1004,580,25,35),('匹配',1000,625,100,40),('25钻石',1070,630,90,35))
    d.triad_lobby=lambda s=None:paid;d.b.click_text=lambda *a,**k:pytest.fail('paid match')
    with pytest.raises(TaskBlocked,match='付费'):d.triad_match(paid)


def test_retired_cards_stay_configurable_but_skip_when_absent(tmp_path):
    d=daily(tmp_path)
    hub=screen(('丰野间',540,20,190,55),('活动时间:10/20-11/1',430,115,320,35),
               ('三阵入局',1000,270,130,40))
    d.observe=lambda:screen()
    d.event_hub=lambda s:hub
    with pytest.raises(BudgetReached,match='已跳过'):d.giant_menu()
    assert puzzle_daily(d)['status']=='skipped'


@pytest.mark.parametrize('caption,expected',[
    ('活动已关闭','ended'),('活动未开启','not_open'),('敬请期待','not_open')])
def test_seasonal_card_opening_state_is_read_below_its_own_title(caption,expected):
    hub=screen(('进击巨物',1050,250,100,30),(caption,1050,283,120,28))
    assert activity_availability(hub,activity_entry(hub,'giant'))==expected


def test_one_match_can_quick_settle_three_distinct_rounds(tmp_path):
    d=daily(tmp_path);d.options['triad']['auto_settle']=True
    frames=iter([screen(('正在匹配',450,180,180,45),('取消匹配',550,600,120,45)),
                 battle(1),battle(1),battle(1,False),battle(2),
                 battle(2,False),battle(3),result()])
    d.observe=lambda:next(frames)
    d.b.guard=lambda _:None;d.b.sleep=lambda _:None
    d.b.read_text_crop=lambda *_:'';d.retry_battle_network=lambda *_:False
    clicked=[]
    d.b.click_text=lambda *a,**k:clicked.append('match')
    d.b.click_at=lambda *a,**k:clicked.append('settle')
    d.b.save_screen=lambda *a,**k:None
    d.triad_lobby=lambda s=None:lobby(3)
    _,outcome,count=d.triad_match(lobby(3))
    assert outcome=='victory' and count==4
    assert clicked==['match']+['settle']*4


def test_auto_settlement_can_be_disabled_and_daily_matching_is_capped(tmp_path):
    d=daily(tmp_path);d.options['triad']['auto_settle']=False
    d.triad_lobby=lambda s=None:lobby(3)
    frames=iter([battle(1),battle(2),result()]);d.observe=lambda:next(frames)
    d.b.guard=lambda _:None;d.b.sleep=lambda _:None;d.retry_battle_network=lambda *_:False
    clicked=[];d.b.click_text=lambda *a,**k:clicked.append('match')
    d.b.click_at=lambda *a,**k:clicked.append('settle')
    d.b.save_screen=lambda *a,**k:None;d.b.read_text_crop=lambda *_:''
    assert d.triad_match(lobby(3))[2]==0 and clicked==['match']
    d.triad_lobby=lambda s=None:lobby(max(0,3-d.task_counts.get('triad',0)))
    d.triad_match=lambda s:(result(),'victory',3)
    d.exit_result=lambda s:None;d.home=lambda:None
    summary=d.triad()
    assert d.task_counts['triad']==3 and '已完成3场' in summary
    assert d.report['triad_remaining']==0
