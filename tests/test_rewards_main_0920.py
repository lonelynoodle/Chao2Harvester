"""Regressions from the Oct 18 run; all inputs use isolated captured frames."""
import pytest

from chao2.backend import Word
from chao2.reward_collection import (CLAIM,CONTRACT_CLAIM_ROI,is_map_story,
    story_chest_state,echo_story_kind,ECHO_HUB_REGIONS)
from chao2.other_tasks import notification_badges
from chao2.policy import TaskBlocked
from test_configuration import captured,daily,screen


@pytest.mark.parametrize('title',['围猎','丢下火花','另一个未见过的故事'])
def test_map_story_uses_fixed_layout_not_the_title_or_body(title):
    s=captured('v0920-main-story',True)
    s.words=[Word(title,w.box,w.score) if 370<=w.box[0]<=400 and 210<w.box[1]<260 else
             Word('每张故事的正文都可以完全不同，不应将内容当成固定识别词。',w.box,w.score)
             if 365<=w.box[0]<=400 and 285<w.center[1]<590 else w for w in s.words]
    assert is_map_story(s)
    s.words=[w for w in s.words if w.text!='评论']
    assert not is_map_story(s)


def test_overview_closes_lore_during_travel_and_checks_fresh_stage(tmp_path):
    d=daily(tmp_path);d.active_task='main'
    panel=screen(('玩法概览',400,20,100,30),('每日挑战',100,80,100,30))
    word=Word('世界关卡',[370,300,90,30],.99)
    d.find_overview_entry=lambda _: (panel,'target',word)
    story=captured('v0920-main-story',True);detail=captured('main-entry')
    frames=iter([story,story,detail]);d.observe=lambda:next(frames);d.b.sleep=lambda _:None
    d.b.observe=lambda *a:next(frames)
    clicks=[];d.b.click_at=lambda s,p,a,r:clicks.append((p,r))
    assert d.enter_overview('^世界关卡$') is detail
    assert [p for p,_ in clicks]==[(738,345),(1210,650)]
    assert d.report['map_stories']==['围猎']


def test_await_main_detail_dismisses_lore_before_using_background_buttons(tmp_path):
    d=daily(tmp_path);d.active_task='main'
    story=captured('v0920-main-story',True);detail=captured('main-entry')
    frames=iter([story,detail]);d.observe=lambda:next(frames);d.b.sleep=lambda _:None
    d.b.observe=lambda *a:next(frames)
    clicks=[];d.b.click_at=lambda s,p,a,r:clicks.append(p)
    assert d.await_detail() is detail and clicks==[(1210,650)]


@pytest.mark.parametrize('stage_behind',[True,False])
def test_node_lore_reveals_stage_or_is_cached_without_reopening(tmp_path,monkeypatch,stage_behind):
    import chao2.activities as activities
    d=daily(tmp_path);d.active_task='main'
    world=captured('v0913-main-world',True);story=captured('v0920-main-story',True)
    after=captured('main-entry') if stage_behind else world
    frames=iter([story,after,world]);d.observe=lambda:next(frames);d.b.sleep=lambda _:None
    d.b.observe=lambda *a:next(frames)
    d.home=lambda *a:world
    monkeypatch.setattr(activities,'main_nodes',lambda _: [(600,300)])
    monkeypatch.setattr(activities,'main_map_shift',lambda *a:(0,0))
    clicks=[];d.click_world=lambda s,p,r:clicks.append(p)
    d.b.click_at=lambda s,p,a,r:clicks.append(p)
    assert d.find_main_candidate(set()) is (after if stage_behind else None)
    assert clicks==[(600,300),(1210,650)]
    if not stage_behind:
        assert d.find_main_candidate(set()) is None
        assert len(clicks)==2


@pytest.mark.parametrize('name',['contract-tasks','contract-loop'])
def test_missed_leading_stroke_on_contract_claim_is_accepted_only_in_claim_region(name):
    s=captured('v0920-'+name,True)
    assert s.find(CLAIM,CONTRACT_CLAIM_ROI).text=='键领取'
    assert not captured('v0920-contract-tasks-done',True).find(CLAIM,CONTRACT_CLAIM_ROI)
    for text in ('一键购买','超阶契约','购买等级','已领取','去完成'):
        import re
        assert not re.fullmatch(CLAIM,text)


def test_actual_pulsing_hub_and_story_badges_are_recognised():
    hub=captured('v0920-echo-hub',True)
    assert notification_badges(hub,ECHO_HUB_REGIONS['lost'])==[(151,216)]
    assert notification_badges(hub,ECHO_HUB_REGIONS['torrent'])==[(334,388)]
    assert not notification_badges(hub,ECHO_HUB_REGIONS['monument'])
    assert not notification_badges(hub,ECHO_HUB_REGIONS['notes'])
    assert notification_badges(captured('v0920-echoes-lost-top',True),(0,185,1280,510))==[(170,260)]


def test_actual_blue_story_chest_works_when_small_claim_text_is_missed():
    s=captured('v0920-lost-story-ready',True)
    assert echo_story_kind(s)=='lost' and not s.find('可领取')
    assert story_chest_state(s,'lost')=='ready'
    assert story_chest_state(s,'notes') is None
    # Old illustration colour must not be mistaken for a free chest.
    assert story_chest_state(captured('reward-lost-story-001',True),'lost') is None


def test_torrent_comment_icon_is_not_part_of_variable_story_content(tmp_path):
    s=captured('v0920-torrent-comment-icon',True)
    assert s.find('^日评论$') and echo_story_kind(s)=='torrent'
    d=daily(tmp_path);listing=captured('reward-torrent',True)
    d.observe=lambda:listing;clicks=[];d.b.click_at=lambda q,p,a,r:clicks.append(p)
    assert d.close_echo_story(s) is listing and clicks==[(1230,38)]


def test_story_claims_are_not_erased_by_following_category_recheck(tmp_path):
    from test_other_tasks import fake
    d=daily(tmp_path);d.report['world_echoes']={'lost':{'claimed':1}}
    hub=captured('reward-echoes',True);listing=captured('reward-echoes-lost',True)
    state,_=fake(d,listing);d.echo_hub=lambda *a:hub;d.b.click_text=lambda *a,**k:None
    result=d.collect_echo_category('lost')
    assert result['claimed']==1 and result['status']=='done'


def test_claimed_badge_batch_checks_hub_without_scanning_the_old_catalogue(tmp_path):
    from test_other_tasks import fake
    d=daily(tmp_path)
    hub=captured('v0920-echo-hub',True);clean=captured('reward-echoes',True)
    listing=captured('v0920-echoes-lost-top',True);story=captured('v0920-lost-story-ready',True)
    empty=captured('reward-echoes-lost',True)
    state,_=fake(d,listing);hubs=iter([hub,clean]);d.echo_hub=lambda *a:next(hubs)
    d.b.click_text=lambda *a,**k:None
    d.b.click_at=lambda *a:state.__setitem__(0,story)
    def claim(s,kind):
        d.record_echo_claim(kind);return s,1
    d.collect_story_chest=claim;d.close_echo_story=lambda _:empty
    d.echo_scroll=lambda *a,**k:pytest.fail('Clean hub does not require scanning hundreds of stories')
    result=d.collect_echo_category('lost')
    assert result['claimed']==1 and result['pages']==0 and result['status']=='done'


def test_echo_entry_waits_and_retries_only_the_confirmed_hub(tmp_path,monkeypatch):
    from test_navigation_retry import clocked
    d=daily(tmp_path);clocked(d,monkeypatch)
    hub=captured('reward-echoes',True);listing=captured('reward-monument',True)
    current=[hub];clicks=[]
    d.observe=lambda:current[0]
    def click(*a,**k):
        clicks.append(a[1])
        if len(clicks)==2:current[0]=listing
    d.b.click_text=click
    assert d.open_echo_category(hub,'monument') is listing
    assert clicks==['^世界丰碑$','^世界丰碑$']
    assert [r['attempt'] for r in d.report['navigation_retries']]==[1]


def test_echo_wrong_page_is_not_reclicked_as_a_hub(tmp_path,monkeypatch):
    from test_navigation_retry import clocked
    d=daily(tmp_path);clocked(d,monkeypatch);hub=captured('reward-echoes',True)
    d.observe=lambda:screen();clicks=[];d.b.click_text=lambda *a,**k:clicks.append(a[1])
    with pytest.raises(TaskBlocked,match='已重试3次'):d.open_echo_category(hub,'monument')
    assert len(clicks)==1


def test_unread_contract_claim_with_notification_cannot_report_done(tmp_path):
    from test_other_tasks import fake
    d=daily(tmp_path);tasks=captured('v0920-contract-tasks-done',True)
    rewards=captured('v0920-contract-loop',True)
    rewards.words=[w for w in rewards.words if w.text!='键领取']
    state,_=fake(d,rewards);d.contract_menu=lambda:state[0]
    d.b.click_text=lambda s,p,**k:state.__setitem__(0,rewards if p=='^奖励$' else tasks)
    with pytest.raises(TaskBlocked,match='仍有待领取提示'):d.collect_contract()
    assert d.report['other_tasks']['contract']['status']!='done'
