"""Recover delayed egg receipts and claim free tribe occupation income."""
from types import SimpleNamespace
import pytest

from test_configuration import daily,captured,screen
from test_monster_boxes import flow
from chao2.monster_boxes import is_monster_box_result,monster_box_result_name
from chao2.policy import SafetyStop,TaskBlocked


def fake_navigation_clock(d,monkeypatch):
    import chao2.navigation_retry as nav
    now=[0.]
    monkeypatch.setattr(nav,'time',SimpleNamespace(monotonic=lambda:now[0]))
    d.b.sleep=lambda seconds:now.__setitem__(0,now[0]+seconds)


def test_egg_retry_closes_presentation_without_repeating_the_open(tmp_path,monkeypatch):
    d,item,state,clicks=flow(tmp_path);fake_navigation_clock(d,monkeypatch)
    early=captured('v0936-box-reward-early',True)
    ready=captured('v0936-box-reward-ready',True)
    selected=captured('v0917-box-selected',True)
    for word in selected.words:
        if word.text=='停顿':word.text='跃迁兽'
    assert is_monster_box_result(early,'跃迁兽') and monster_box_result_name(ready)=='跃迁兽'
    d.select_monster_box_target=lambda *args:selected
    after=captured('v0917-box-after',True);closed=[]
    def click(s,p,anchors,reason):
        assert s.has(*anchors);clicks.append(reason)
        if reason.startswith('开启1个'):state[0]=early
        else:
            closed.append(p)
            state[0]=ready if len(closed)==1 else after
    d.b.click_at=click
    result,left=d.open_one_monster_box(item,'跃迁兽','specified')
    assert result is after and left==3
    assert len(closed)==2 and sum(t.startswith('开启1个') for t in clicks)==1
    assert d.state['monster_box_opened_counts']['跃迁兽']==1


def test_receipt_dismissal_has_three_retries_then_preserves_pending_result(tmp_path,monkeypatch):
    d,item,state,clicks=flow(tmp_path);fake_navigation_clock(d,monkeypatch)
    reward=captured('v0917-box-result',True)
    def click(s,p,anchors,reason):
        clicks.append(reason);state[0]=reward
    d.b.click_at=click
    with pytest.raises(SafetyStop,match='未完整核实'):d.open_one_monster_box(item,'行尸','balanced')
    assert sum(t.startswith('开启1个') for t in clicks)==1
    assert clicks.count('关闭已获得怪兽展示')==4
    assert d.report['monster_boxes'][0]['status']=='reward_seen'
    assert not d.state['monster_box_opened_counts']


def test_home_resumes_a_previous_egg_display_before_other_tasks(tmp_path):
    d=daily(tmp_path);reward=captured('v0936-box-reward-ready',True)
    bag=captured('v0917-box-after',True);world=captured('world-missed-label',True)
    state=[reward];clicks=[];d.observe=lambda:state[0]
    d.b.click_at=lambda s,p,a,reason:(clicks.append(reason),state.__setitem__(0,bag if reason=='关闭已获得怪兽展示' else world))
    assert d.home(reward) is world
    assert clicks==['关闭已获得怪兽展示','返回上级']
    assert not d.report.get('monster_boxes')  # Do not invent a new opening.


def tribe_map(amount=10):
    s=captured('v0936-tribe-entry',True)
    s.words.extend(screen((str(amount),1230,126,30,24)).words)
    return s


def test_occupation_zero_and_unrelated_pages_never_click(tmp_path):
    d=daily(tmp_path);d.b.click_at=lambda *a:pytest.fail('No claim')
    empty=tribe_map(0)
    assert d.claim_tribe_occupation(empty) is empty
    detail=captured('tribe-active-detail')
    assert d.claim_tribe_occupation(detail) is detail
    assert not d.report.get('tribe_occupation_rewards')


def test_occupation_claim_confirms_popup_and_zero_before_returning(tmp_path):
    d=daily(tmp_path);before=tribe_map(10);after=tribe_map(0)
    reward=screen(('部落',140,14,60,28),('获得奖励',510,110,240,60),
                  ('点击空白位置关闭',460,630,320,35),('10',610,340,50,35))
    state=[before];clicks=[];d.observe=lambda:state[0]
    def click(s,p,anchors,reason):
        assert s.has(*anchors);clicks.append((p,reason))
        state[0]=reward if reason.startswith('领取右上角') else after
    d.b.click_at=click
    assert d.claim_tribe_occupation(before) is after
    row=d.report['tribe_occupation_rewards'][0]
    assert row['status']=='claimed' and row['claimed']==10 and row['remaining']==0
    assert [p for p,_ in clicks]==[(1214,123),(640,560)]


def test_occupation_retry_is_only_a_free_claim_on_same_known_map(tmp_path,monkeypatch):
    d=daily(tmp_path);fake_navigation_clock(d,monkeypatch)
    before=tribe_map(10);after=tribe_map(0);state=[before];clicks=[]
    d.observe=lambda:state[0]
    def click(s,p,a,r):
        clicks.append(p)
        if len(clicks)==2:state[0]=after
    d.b.click_at=click
    assert d.claim_tribe_occupation(before) is after
    assert clicks==[(1214,123)]*2 and d.report['tribe_occupation_rewards'][0]['status']=='claimed'
    # The same entry will not submit again even if a stale positive frame arrives.
    assert d.claim_tribe_occupation(before) is before and len(clicks)==2


def test_occupation_unknown_amount_is_not_invented_as_zero(tmp_path):
    d=daily(tmp_path);before=captured('v0936-tribe-entry',True)
    d.b.click_at=lambda *args:pytest.fail('Unknown amount')
    assert d.claim_tribe_occupation(before) is before
    assert d.report['tribe_occupation_rewards'][0]['status']=='unreadable'
    d.claim_tribe_occupation(tribe_map(0))
    assert d.report['tribe_occupation_rewards'][0]['status']=='readable'


def test_donation_entry_checks_occupation_rewards_first(tmp_path):
    d=daily(tmp_path);before=tribe_map();order=[]
    d.observe=lambda:before
    d.claim_tribe_occupation=lambda s:order.append('occupation') or s
    d.b.click_at=lambda *a:order.append('donation')
    d.wait_for_screen=lambda *a,**k:captured('v0923-donation',True)
    d.open_tribe_donation()
    assert order==['occupation','donation']
