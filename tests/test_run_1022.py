"""Regressions from the 2026-10-22 completed run; all inputs are offline."""
import pytest

from test_configuration import daily,screen
from chao2.activities import enemy_formation,BudgetReached
from chao2.event_hub import activity_entry,activity_availability
from chao2.policy import TaskBlocked
from chao2.puzzle import puzzle_daily
from chao2.star_shop import star_souls


def test_secret_detail_accepts_formation_heading_with_ocr_marker_noise(tmp_path):
    d=daily(tmp_path)
    s=screen(('塔中秘庭74',232,104,141,31),('首通奖励',173,555,73,23),
             ('排阵',702,611,62,36),('挑战',946,611,62,36),
             ('敌方阵容Q1023)4',782,103,303,28))
    assert enemy_formation(s).text=='敌方阵容Q1023)4'
    assert d.ensure_detail(s) is s
    s.words=[w for w in s.words if w.text!='首通奖励']
    assert enemy_formation(s) is None


def test_formation_click_retries_only_on_same_tribe_stage(tmp_path):
    d=daily(tmp_path);d.active_task='tribe'
    detail=screen(('冒险关卡42',44,133,136,32),('敌方阵容',1128,133,105,31),
                  ('通关奖励（含拍卖和共享奖励',41,565,237,18),
                  ('排阵',825,615,57,32),('挑战',1060,603,61,34))
    other=screen(('冒险关卡43',44,133,136,32),('敌方阵容',1128,133,105,31),
                 ('排阵',825,615,57,32),('挑战',1060,603,61,34))
    formation=screen(('部队',125,15,65,30),('空闲1',930,88,80,25))
    clicks=[];d.b.click_text=lambda s,pattern:clicks.append(pattern)
    d.b.click_at=lambda *args:None
    d.apply_saved_team=lambda s,team:s
    d.await_detail=lambda:detail
    def wait(predicate,label,**kwargs):
        assert label=='排阵配置' and not predicate(detail)
        kwargs['retry_navigation'](other)
        assert len(clicks)==1
        kwargs['retry_navigation'](detail)
        assert predicate(formation)
        return formation
    d.wait_for_screen=wait
    assert d.select_team(detail,1) is detail
    assert clicks==['^排阵$','^排阵$']


def test_finished_giant_and_unopened_puzzle_are_skipped_from_same_hub(tmp_path):
    hub=screen(('丰野间',541,27,193,69),
               ('进击巨物',1102,270,102,23),('活动已结束',1102,295,98,25),
               ('拼二大作战',69,618,136,34),('11月19日开启',81,653,113,19),
               ('龙宵大作战',180,547,141,32),('活动已结束',206,578,94,22))
    giant=activity_entry(hub,'giant');puzzle=activity_entry(hub,'puzzle')
    assert activity_availability(hub,giant)=='ended'
    assert activity_availability(hub,puzzle)=='not_open'
    d=daily(tmp_path);d.observe=lambda:hub;d.event_hub=lambda s:hub
    d.b.click_at=lambda *args:pytest.fail('Closed or unopened event must not be clicked')
    with pytest.raises(BudgetReached,match='活动已结束'):d.giant_menu()
    assert puzzle_daily(d)=={'status':'skipped','message':'拼二大作战尚未开放，已跳过'}


def test_star_soul_balance_accepts_0_8_confidence_but_rechecks_number(tmp_path):
    d=daily(tmp_path)
    s=screen(('100',1225,14,39,25));s.words[0].score=.897375
    d.b.match_template=lambda *args:True
    d.b.read_number=lambda *args:100
    assert star_souls(d.b,s)==100
    d.b.read_number=lambda *args:101
    with pytest.raises(TaskBlocked,match='两次识别不一致'):star_souls(d.b,s)
    s.words[0].score=.79
    with pytest.raises(TaskBlocked,match='余额未读清'):star_souls(d.b,s)
