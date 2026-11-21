"""Free notification navigation and core milestone receipt safeguards."""
import cv2
import pytest

from test_configuration import daily,screen,captured
from chao2.activities import BudgetReached
from chao2.configuration import normalize_settings
from chao2.policy import TaskBlocked
from chao2.tribe_notifications import (
    donation_rewards_page,donation_claim_state,tribe_auction_page,
    tribe_dynamics_page,tribe_tab_selected,tribe_loading,
)
from chao2.daily_challenges import ARENA_CARDS,arena_candidates


def core_rewards(ready=False):
    s=screen(('支配核心捐献奖励',450,25,380,40),
             ('全部领取',580,623,120,30),
             ('达成条件:支配核心捐献100',335,165,340,30))
    s.image[623:653,580:700]=240 if ready else 100
    return s


def test_defaults_preserve_existing_tribe_and_support_independent_switches():
    cfg=normalize_settings({'task_options':{'tribe':{'teams':[1],'reserve_orders':2,
                                                     'clear_auction_dot':False}}})
    options=cfg['task_options']['tribe']
    assert options['teams']==[1] and options['reserve_orders']==2
    assert not options['clear_auction_dot']
    assert options['clear_dynamics_dot'] and options['claim_donation_rewards']


def test_extras_run_before_adventure_even_without_orders(tmp_path):
    d=daily(tmp_path);calls=[]
    d.collect_tribe_extras=lambda:calls.append('extras')
    d.collect_tribe_chests=lambda:calls.append('chests')
    def no_orders():raise BudgetReached('战令已用完')
    d.tribe_detail=no_orders;d.home=lambda:None
    assert '战令已用完' in d.tribe()
    assert calls==['extras','chests']


@pytest.mark.parametrize('ready,expected',[(False,'empty'),(True,'ready')])
def test_milestone_button_state_requires_exact_modal_and_text(ready,expected):
    s=core_rewards(ready)
    assert donation_rewards_page(s) and donation_claim_state(s)==expected
    s.words=[w for w in s.words if '达成条件' not in w.text]
    assert donation_claim_state(s) is None


def test_empty_milestones_close_without_clicking_claim_or_donation(tmp_path):
    d=daily(tmp_path);s=core_rewards();closed=[]
    d.b.click_at=lambda *args,**kwargs:pytest.fail('No claim or donation is needed')
    d.close_donation_rewards=lambda q:closed.append(q) or q
    assert d.claim_tribe_donation_rewards(s) is s
    assert closed==[s] and d.report['tribe_donation_rewards'][0]['status']=='empty'


def test_earned_milestones_claim_once_and_require_actual_receipt(tmp_path):
    d=daily(tmp_path);ready=core_rewards(True);empty=core_rewards()
    receipt=screen(('获得奖励',560,100,160,55))
    frames=iter([ready,receipt]);d.observe=lambda:next(frames)
    d.dismiss_collection_reward=lambda s:(empty,1)
    d.close_donation_rewards=lambda s:s
    clicks=[];d.b.click_at=lambda s,p,*a,**kw:clicks.append(p)
    assert d.claim_tribe_donation_rewards(ready) is empty
    assert clicks==[(640,638)]
    assert d.report['tribe_donation_rewards'][0]['status']=='claimed'
    assert '获得奖励' in d.report['tribe_donation_rewards'][0]['reward_text']


def test_unknown_claim_result_does_not_submit_again(tmp_path):
    d=daily(tmp_path);s=core_rewards(True);d.observe=lambda:s;d.b.sleep=lambda _:None
    clicks=[];d.b.click_at=lambda *a,**kw:clicks.append(a[1])
    with pytest.raises(TaskBlocked,match='领取结果未确认'):d.claim_tribe_donation_rewards(s)
    with pytest.raises(TaskBlocked,match='上次领取结果未确认'):d.claim_tribe_donation_rewards(s)
    assert len(clicks)==1


def test_changed_milestone_state_never_clicks_stale_ready_button(tmp_path):
    d=daily(tmp_path);d.observe=lambda:core_rewards()
    d.b.click_at=lambda *a,**kw:pytest.fail('Stale button must not be clicked')
    with pytest.raises(TaskBlocked,match='页面状态改变'):
        d.claim_tribe_donation_rewards(core_rewards(True))


def test_selected_tab_with_loading_dots_is_not_ready_for_next_click():
    s=screen(('个人战报',30,225,94,27))
    s.image[215:255,5:145]=(130,190,215)
    assert tribe_tab_selected(s,'个人战报') and not tribe_loading(s)
    for point in [(640,307),(594,334),(594,386),(640,413),(686,386),(686,334)]:
        cv2.circle(s.image,point,9,(240,240,240),-1)
    assert tribe_loading(s)


def test_finished_gold_donation_still_checks_milestones_without_donating(tmp_path,monkeypatch):
    import chao2.star_shop as shop
    d=daily(tmp_path);d.options['other']['tribe_gold_donation']=True
    d.b.tasker=object();s=screen();claimed=[]
    d.open_tribe_donation=lambda:s
    monkeypatch.setattr(shop,'gold_donation_remaining',lambda q:(0,1))
    d.claim_tribe_donation_rewards=lambda q:claimed.append(q)
    d.b.click_at=lambda *a,**kw:pytest.fail('Already donated; must not donate again')
    assert d.tribe_gold_donation()['count']==0
    assert claimed==[s]


@pytest.mark.parametrize('kind,tabs',[
    ('auction',['竞拍','记录']),('dynamics',['我的消息','个人战报','部落战报','遗迹播报'])])
def test_notification_navigation_visits_every_category_and_returns(tmp_path,monkeypatch,kind,tabs):
    import chao2.tribe_notifications as notifications
    d=daily(tmp_path);current=[None];clicked=[]
    tribe=screen(('部落',140,10,70,32),('部落大厅',1120,650,130,38))
    page=screen(('拍卖所' if kind=='auction' else '部落动态',100,5,200,40),
                *((name,20,130+90*i,125,32) for i,name in enumerate(tabs)))
    page.selected=None
    d.tribe_map=lambda:tribe
    monkeypatch.setattr(notifications,'tribe_tab_selected',lambda s,name:s.selected==name)
    def enter(*args,**kwargs):current[0]=page
    def tab(s,pattern,**kwargs):
        name=pattern[1:-1];assert name in tabs;clicked.append(name);page.selected=name
    def wait(predicate,*args,**kwargs):
        assert predicate(current[0]);return current[0]
    d.b.click_at=enter;d.b.click_text=tab;d.wait_for_screen=wait
    d.b.back=lambda *a:current.__setitem__(0,tribe)
    assert d.read_tribe_notifications(kind) is tribe
    assert clicked==tabs
    assert d.report['tribe_notifications']==[{'kind':kind,'status':'read','tabs':tabs}]


def test_notification_tab_swallowed_click_is_retried_only_on_same_page(tmp_path,monkeypatch):
    import chao2.tribe_notifications as notifications
    d=daily(tmp_path);clicked=[];current=[None]
    tribe=screen(('部落',140,10,70,32),('部落大厅',1120,650,130,38))
    page=screen(('拍卖所',100,5,160,40),('竞拍',40,135,70,28),('记录',40,225,70,28))
    page.selected='竞拍';d.tribe_map=lambda:tribe
    monkeypatch.setattr(notifications,'tribe_tab_selected',lambda s,name:s.selected==name)
    d.b.click_at=lambda *a,**kw:current.__setitem__(0,page)
    def tab(s,pattern,**kwargs):
        clicked.append(pattern)
        if len(clicked)==2:page.selected='记录'
    def wait(predicate,*args,**kwargs):
        if not predicate(current[0]):kwargs['retry_navigation'](current[0])
        assert predicate(current[0]);return current[0]
    d.b.click_text=tab;d.wait_for_screen=wait
    d.b.back=lambda *a:current.__setitem__(0,tribe)
    assert d.read_tribe_notifications('auction') is tribe
    assert clicked==['^记录$','^记录$']


def test_actual_milestones_are_already_claimed_and_sidebar_selection_is_readable():
    s=captured('v0972-core-rewards',True)
    assert donation_rewards_page(s) and donation_claim_state(s)=='empty'
    s=captured('v0972-auction',True)
    assert tribe_auction_page(s) and tribe_tab_selected(s,'竞拍')
    s=captured('v0972-dynamics',True)
    assert tribe_dynamics_page(s) and tribe_tab_selected(s,'我的消息')


def test_actual_arena_six_digit_power_no_longer_blocks_list(tmp_path):
    d=daily(tmp_path);s=captured('v0972-arena-list',True)
    # Previously the 6 glyph failed the template cutoff and OCR lost a 9.
    assert [c['power'] for c in arena_candidates(s,d.read_arena_power)]==[171755,81708,92653,129962]
    assert d.read_arena_power(s,ARENA_CARDS[3][0])==129962
