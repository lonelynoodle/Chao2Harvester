"""Compact diamond wallets and recoverable, navigation-only shop retries."""
import pytest
from chao2.backend import Word
from chao2.compact_balance import displayed_balance,balance_delta_possible,read_displayed_balance
from chao2.policy import TaskBlocked,SafetyStop
from test_configuration import daily,captured,screen

@pytest.mark.parametrize('text',['1.02万','1.07万','1万','1.1亿'])
def test_compact_balances_keep_uncertainty(text):
    value=displayed_balance(text)
    assert isinstance(value,dict) and value['min']<=value['max'] and value['text']==text
    assert balance_delta_possible(value,value,-50)

@pytest.mark.parametrize('text',['1.万','1.02','1O2万','-10200','1.02万钻石','1/2万'])
def test_ambiguous_balances_are_not_guessed(text):
    assert displayed_balance(text) is None

def test_exact_wallet_changes_stay_exact_and_compact_inconsistent_changes_reject():
    assert displayed_balance('9205')==9205
    assert balance_delta_possible(9205,9155,-50)
    assert not balance_delta_possible(9205,9145,-50)
    assert balance_delta_possible(displayed_balance('1.02万'),displayed_balance('1.04万'),200)
    assert not balance_delta_possible(displayed_balance('1.02万'),displayed_balance('1.09万'),200)

def test_actual_maa_compact_world_wallet(tmp_path):
    from test_maa_recognition import Offline
    from maa.resource import Resource
    from maa.tasker import Tasker
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle('resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    d=daily(tmp_path);d.b.tasker=t;s=captured('v0955-wallet-compact',True)
    d.home=lambda:s
    assert d.piggy_wallet()==displayed_balance('1.02万')
    from chao2.star_shop import ultimate_candidates,ultimate_level
    purple=captured('v0955-star-purple',True)
    candidates=ultimate_candidates(purple)
    assert len(candidates)==1 and ultimate_level(d.b,purple,candidates[0])==1

def test_compact_ocr_conflict_stops_before_any_purchase(tmp_path):
    d=daily(tmp_path);s=captured('v0955-wallet-compact')
    d.b.read_text_crop=lambda *a:'1.07万'
    d.b.read_text_region=lambda *a,**kw:'1.07万'
    with pytest.raises(TaskBlocked,match='不一致'):read_displayed_balance(d.b,s,(235,0,90,55))

def test_compact_purchase_uses_exact_price_and_inventory_and_reward_checks(tmp_path):
    from test_piggy_bank import simulation
    d,state=simulation(tmp_path,wallet=10250)
    d.piggy_wallet=lambda:displayed_balance(f"{state['wallet']//100/100:.2f}万")
    old_observe=d.observe
    def observe():
        s=old_observe()
        if state['mode']=='offer':
            for word in s.words:
                if word.text=='9205':word.text='1.02万'
        return s
    d.observe=observe
    # simulation's local closure still emits the fixture during wait_for_screen.
    d.wait_for_screen=lambda predicate,*a,**kw:observe() if predicate(observe()) else None
    d.b.read_text_crop=lambda *a:'1.02万'
    row=d.collect_piggy_bank()
    assert row['status']=='done' and row['spent']==50 and row['diamonds_after']['text']=='1.04万'
    assert (state['purchases'],state['claims'],state['wallet'])==(1,1,10400)
    assert not d.state.get('piggy_pending')

def test_compact_wallet_does_not_let_missing_hammer_purchase_pass(tmp_path):
    from test_piggy_bank import simulation
    d,state=simulation(tmp_path,buy_stuck=True)
    d.piggy_wallet=lambda:displayed_balance('1.02万')
    # Offer balance must agree before the single transaction is sent.
    import chao2.piggy_bank as piggy
    from unittest.mock import patch
    with patch.object(piggy,'read_piggy_offer',return_value={'balance':displayed_balance('1.02万'),'remaining':3}):
        with pytest.raises(SafetyStop,match='未核实'):d.collect_piggy_bank()
    assert state['purchases']==1 and state['claims']==0 and d.state['piggy_pending']['phase']=='buy_requested'

def test_shop_caption_missing_in_fresh_frame_is_locally_confirmed_and_only_navigation_retried(tmp_path):
    from chao2.star_shop import star_shop_page
    d=daily(tmp_path);s=captured('v0955-star-altar')
    s.words=[w for w in s.words if w.text!='商店']
    def confirm(q,pattern,roi,**kw):
        if not q.find(pattern,roi):q.words.append(Word('商店',[30,635,55,30],.95))
    d.b.confirm_label=confirm;d.observe=lambda:s
    d.territory=lambda:pytest.fail('The altar has not changed')
    d.b.click_text=lambda *a,**kw:pytest.fail('No fragile full-frame caption recheck')
    clicks=[];d.b.click_at=lambda *a,**kw:clicks.append(a[3])
    destination=captured('v0926-star_spores-blocked')
    def wait(predicate,*a,**kw):
        assert 'retry_navigation' in kw
        kw['retry_navigation'](s)
        assert predicate(destination)
        return destination
    d.wait_for_screen=wait
    assert star_shop_page(d.open_star_shop())
    assert clicks==['进入饲星商店','进入饲星商店']
    assert not d.day.get('star_conversion_pending')

def test_shop_retry_never_clicks_over_purchase_confirmation(tmp_path):
    d=daily(tmp_path);s=captured('v0955-star-altar');d.observe=lambda:s
    d.b.click_at=lambda *a,**kw:None
    def wait(predicate,*a,**kw):
        s.words.append(Word('取消',[450,460,70,40],.99))
        d.b.click_at=lambda *a,**kw:pytest.fail('Do not navigate over a transaction')
        kw['retry_navigation'](s)
        return s
    d.wait_for_screen=wait
    d.open_star_shop()

@pytest.mark.parametrize('yield_value',[None,75,150])
def test_unknown_old_conversion_never_replays_or_clears_nonempty_altar(tmp_path,monkeypatch,yield_value):
    from chao2 import star_shop as shop
    d=daily(tmp_path);pending={'balance':140,'yield':75};d.day['star_conversion_pending']=pending.copy()
    d.open_star_shop=lambda:captured('v0926-star_spores-blocked')
    s=captured('v0955-star-altar');d.wait_for_screen=lambda *a,**kw:s
    d.b.click_at=lambda *a,**kw:None;d.b.sleep=lambda *a:None;d.observe=lambda:s
    monkeypatch.setattr(shop,'star_souls',lambda *a:245)
    monkeypatch.setattr(shop,'star_yield',lambda *a:yield_value)
    with pytest.raises(TaskBlocked,match='并非空白'):d.rebase_star_conversion_pending(pending,245)
    assert d.day['star_conversion_pending']==pending and not d.day.get('star_conversion_history')

def test_unknown_old_conversion_archives_after_empty_altar_and_stable_wallet(tmp_path,monkeypatch):
    from chao2 import star_shop as shop
    d=daily(tmp_path);pending={'balance':140,'yield':75};d.day['star_conversion_pending']=pending.copy()
    d.open_star_shop=lambda:captured('v0926-star_spores-blocked')
    s=captured('v0955-star-altar');d.wait_for_screen=lambda *a,**kw:s
    d.b.click_at=lambda *a,**kw:None;d.b.sleep=lambda *a:None;d.observe=lambda:s
    monkeypatch.setattr(shop,'star_souls',lambda *a:245)
    monkeypatch.setattr(shop,'star_yield',lambda *a:0)
    d.reconcile_star_conversion_pending()
    assert not d.day.get('star_conversion_pending')
    history=d.day['star_conversion_history'][0]
    assert history['previous']==pending and history['outcome']=='unknown' and history['current_balance']==245
    assert not d.report.get('other_tasks')  # No old conversion is counted as new work.

def test_rebase_requires_unchanging_wallet(tmp_path,monkeypatch):
    from chao2 import star_shop as shop
    d=daily(tmp_path);pending={'balance':140,'yield':75};d.day['star_conversion_pending']=pending.copy()
    d.open_star_shop=lambda:captured('v0926-star_spores-blocked')
    s=captured('v0955-star-altar');d.wait_for_screen=lambda *a,**kw:s
    d.b.click_at=lambda *a,**kw:None;d.b.sleep=lambda *a:None;d.observe=lambda:s
    amounts=iter([245,246]);monkeypatch.setattr(shop,'star_souls',lambda *a:next(amounts))
    monkeypatch.setattr(shop,'star_yield',lambda *a:0)
    with pytest.raises(TaskBlocked,match='期间'):d.rebase_star_conversion_pending(pending,245)
    assert d.day['star_conversion_pending']==pending and not d.day.get('star_conversion_history')

@pytest.mark.parametrize('values,expected',[
    (['等级1','等级1'],1),(['等级10','等级10'],10),(['等级1','等级10'],None),
    (['级1','等级1'],None),(['1','1'],None),(['等级1','1等级1'],None)])
def test_detected_level_fallback_requires_two_full_consistent_labels(values,expected):
    from types import SimpleNamespace
    from chao2.star_shop import ultimate_level
    values=iter(values)
    b=SimpleNamespace(read_text_crop=lambda *a:'1等级1',read_text_region=lambda *a,**kw:next(values))
    assert ultimate_level(b,None,{'level_roi':(1103,515,48,25)})==expected
