"""Regressions from the four failed tasks on 2026-10-21."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from test_configuration import captured, daily, screen
from test_forest_retry import pan_runner
from chao2.backend import Word
from chao2.policy import TaskBlocked, UserStopped
from chao2.forest import forest_shift
from chao2.daily_challenges import arena_rating
from chao2.other_tasks import friend_scroll_overlap, friend_name_rows, notification_badges
from chao2.puzzle import puzzle_daily_best, await_daily_best
from chao2.reward_collection import echo_story_kind, story_chest_state
from chao2 import star_shop


def test_dark_branches_establish_vertical_motion_despite_repeated_question_marks():
    assert forest_shift(captured('v0926-forest-pan-before',True),
                        captured('v0926-forest-pan-after',True)) == pytest.approx((0,375),abs=2)


def test_implausible_first_registration_rereads_without_another_swipe(tmp_path,monkeypatch):
    d,s,inputs,reads,_=pan_runner(tmp_path,monkeypatch,[True],[(-412,-4),(0,375)])
    assert d.forest_pan(s,0,380)[1]
    assert len(inputs)==1 and len(reads)==2 and d.forest_offset==[10,-355]


def test_actual_rank_emblem_is_not_a_different_opponent(tmp_path):
    s=captured('v0926-arena-blocked',True);d=daily(tmp_path)
    assert arena_rating(s,(790,410,100,50))==1966
    d.read_arena_power=lambda *args:11412
    d.b.read_number=lambda *args:1
    assert d.verify_arena_detail(s,{'power':1412,'name':'可乐味耀变体','rating':1966})==1
    with pytest.raises(TaskBlocked,match='对手'):
        d.verify_arena_detail(s,{'power':1412,'name':'其他玩家','rating':1966})
    with pytest.raises(TaskBlocked,match='对手'):
        d.verify_arena_detail(s,{'power':1412,'name':'可乐味耀变体','rating':1967})

def test_actual_double_one_power_stays_five_digits(tmp_path,monkeypatch):
    from chao2 import power_digits
    from chao2.daily_challenges import ARENA_CARDS
    d=daily(tmp_path)
    for name,roi in [('v0926-arena-live-list',ARENA_CARDS[1][0]),
                     ('v0926-arena-verified',(1112,432,91,35))]:
        assert d.read_arena_power(captured(name,True),roi)==11474
    monkeypatch.setattr(power_digits,'arena_power_digits',lambda *a:None)
    d.b.read_text_region=lambda *a,**k:'1474'
    assert d.read_arena_power(captured('v0926-arena-verified',True),(1112,432,91,35)) is None


def test_arena_reread_never_starts_a_fight_on_changed_identity(tmp_path):
    d=daily(tmp_path);s=captured('v0926-arena-blocked')
    d.b.sleep=lambda _:None;d.arena_detail=lambda:s
    d.b.click_at=lambda *a:pytest.fail('Verification must not click')
    calls=[]
    def verify(*a):
        calls.append(1)
        if len(calls)<3:raise TaskBlocked('对手姓名未读清')
        return 1
    d.verify_arena_detail=verify
    assert d.verified_arena_detail(s,{})==(s,1) and len(calls)==3
    def stopped(*a):raise UserStopped('stop')
    d.verify_arena_detail=stopped
    with pytest.raises(UserStopped):d.verified_arena_detail(s,{})


def test_torrent_long_flick_reproduces_hidden_badge_and_short_overlap_finds_it():
    assert not notification_badges(captured('v0926-torrent-list',True),(0,185,1280,510))
    assert not notification_badges(captured('v0926-torrent-scrolled',True),(0,185,1280,510))
    assert notification_badges(captured('v0926-torrent-badge',True),(0,185,1280,510))==[(379,416)]


def test_torrent_scroll_keeps_card_and_story_badges_in_overlapping_viewports(tmp_path):
    d=daily(tmp_path);calls=[]
    d.b.wait=lambda *a:SimpleNamespace(succeeded=True);d.b.sleep=lambda _:None
    d.b.controller=SimpleNamespace(post_swipe=lambda *args:calls.append(args))
    s=captured('v0926-torrent-list',True);d.observe=lambda:s
    d.echo_scroll(s,'torrent')
    assert calls==[(740,550,740,370,1000)]
    chapter=captured('v0926-torrent-chapter',True)
    assert echo_story_kind(chapter)=='torrent' and story_chest_state(chapter,'torrent')=='ready'
    assert notification_badges(chapter,(10,120,310,380))
    d.echo_scroll(chapter,'torrent',chapter=True)
    assert calls[-1]==(205,440,205,300,1000)

def test_pulsing_hub_badge_gets_full_scan_before_being_reported_blocked(tmp_path):
    d=daily(tmp_path)
    clean=captured('reward-echoes',True);marked=captured('v0926-echo-torrent-blocked',True)
    listing=captured('v0926-torrent-list',True)
    hubs=iter([clean,marked,marked,marked]);opened=[];scrolled=[]
    d.echo_hub=lambda *a:next(hubs)
    d.open_echo_category=lambda *a:opened.append(1) or listing
    d.echo_scroll=lambda *a:scrolled.append(1) or listing
    with pytest.raises(TaskBlocked,match='入口仍有提示'):
        d.collect_echo_category('torrent')
    assert len(opened)==2 and len(scrolled)==1


def test_numeric_and_low_confidence_names_only_extend_navigation_not_deletion():
    after=captured('v0926-inactive_friends-blocked')
    assert '123' not in {r['name'] for r in friend_name_rows(after)}
    before=deepcopy(after)
    before.words=[Word(w.text,[w.box[0],w.box[1]+175,w.box[2],w.box[3]],w.score)
                  for w in after.words if w.text=='123']
    assert friend_scroll_overlap(before,after)
    assert not friend_scroll_overlap(after,before)
    assert not friend_scroll_overlap(after,after)


def test_friend_gap_restarts_at_top_with_shorter_drag_before_processing(tmp_path):
    d=daily(tmp_path);a=captured('v0922-friends-top');b=captured('v0926-inactive_friends-blocked')
    menus=[];swipes=[];states=iter([b,b,b,b,a])
    d.friend_menu=lambda **k:menus.append(k) or a
    d.settle_friend_list=lambda s:s
    d.observe=lambda:next(states)
    d.b.sleep=lambda _:None;d.b.wait=lambda *a:SimpleNamespace(succeeded=True)
    d.b.controller=SimpleNamespace(post_swipe=lambda *args:swipes.append(args))
    d.verified_friend_rows=lambda s:[]
    d.remove_friend=lambda *a:pytest.fail('Never delete from an unverified page')
    result=d.clear_inactive_friends()
    assert result['removed']==0 and menus==[{'reset':True},{'reset':True}]
    assert [s[3] for s in swipes]==[440,485]


def test_unreadable_daily_score_does_not_become_zero(tmp_path):
    d=daily(tmp_path);s=captured('v0926-daily_puzzle-blocked')
    d.b.read_number=lambda *a:None
    d.b.read_text_region=lambda *a,**k:'o'
    assert puzzle_daily_best(d.b,s)==0
    d.b.read_text_region=lambda *a,**k:'8'
    assert puzzle_daily_best(d.b,s) is None
    d.b.read_text_region=lambda *a,**k:''
    assert puzzle_daily_best(d.b,s) is None
    d.observe=lambda:s;d.b.sleep=lambda _:None
    assert await_daily_best(d,s)[1] is None
    assert len(d.report['events'])==3


def test_price_fallback_cannot_truncate_300_to_30(tmp_path):
    d=daily(tmp_path);s=captured('v0926-star_spores-blocked')
    d.b.read_number=lambda s,roi:None if roi[2]==60 else 30
    d.b.match_template=lambda *a:True
    d.b.read_text_region=lambda *a,**k:'300'
    with pytest.raises(TaskBlocked,match='价格'):star_shop.spore_offers(d.b,s)
    d.b.read_text_region=lambda *a,**k:'30'
    assert [r['remaining'] for r in star_shop.spore_offers(d.b,s)]==[5,5]
    d.b.match_template=lambda *a:False
    with pytest.raises(TaskBlocked,match='价格'):star_shop.spore_offers(d.b,s)


def test_shop_retries_reads_without_repeating_a_purchase(tmp_path,monkeypatch):
    d=daily(tmp_path);s=captured('v0926-star_spores-blocked')
    d.b.sleep=lambda _:None;d.observe=lambda:s;calls=[]
    d.b.click_at=lambda *a:pytest.fail('No purchase during recognition retry')
    def offers(*a):
        calls.append(1)
        if len(calls)<4:raise TaskBlocked('价格未确认')
        return [{'price':30}]
    monkeypatch.setattr(star_shop,'spore_offers',offers)
    assert d.read_star_offers(s)==(s,[{'price':30}]) and len(calls)==4
