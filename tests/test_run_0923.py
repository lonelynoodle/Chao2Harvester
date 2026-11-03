"""Captured regressions and transaction boundaries; no device inputs."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import cv2
import pytest
from test_configuration import captured, daily, screen
from chao2.backend import ROOT, Word
from chao2.configuration import SPECS, defaults
from chao2.policy import TaskBlocked, SafetyStop
from chao2.forest import forest_shift
from chao2.other_tasks import is_channel_account_panel
from chao2 import star_shop as shop


def templates(b):
    def match(s, name, roi, threshold=.88):
        x,y,w,h = roi
        template = cv2.imread(str(ROOT/'resource/image'/name))
        score = cv2.matchTemplate(s.image[y:y+h,x:x+w], template, cv2.TM_CCOEFF_NORMED)
        return cv2.minMaxLoc(score)[1] >= threshold
    b.match_template = match


def test_new_spending_options_are_explicit_and_nested():
    options = defaults('other')
    assert options['buy_star_spores']
    assert not options['convert_star_souls']
    assert not options['tribe_gold_donation']
    field = next(f for f in SPECS['other']['fields'] if f['key'] == 'convert_star_souls')
    assert field['enabled_when'] == 'buy_star_spores' and field['indent'] == 18


def test_actual_forest_repeated_icons_do_not_reverse_the_swipe():
    before = captured('v0923-forest-pan-before', True)
    after = captured('v0923-forest-pan-after', True)
    assert forest_shift(before, after) == pytest.approx((0, 378), abs=2)


def test_channel_drawer_only_closes_outside_account_controls(tmp_path):
    d = daily(tmp_path)
    s = captured('v0923-friend_coins-blocked', True)
    assert is_channel_account_panel(s)
    assert not is_channel_account_panel(captured('v0923-star-shop', True))
    clicks = []
    d.b.click_at = lambda s,p,a,r:clicks.append(p)
    d.wait_for_screen = lambda predicate,*a,**k:screen()
    d.close_channel_account_panel(s)
    assert clicks == [(970, 535)]


def test_actual_sold_spores_and_minimal_conversion_count(tmp_path):
    d = daily(tmp_path); templates(d.b)
    s = captured('v0923-star-shop', True)
    d.b.read_number = lambda s,roi:115
    assert shop.star_souls(d.b, s) == 115
    assert [(o['name'],o['remaining']) for o in shop.spore_offers(d.b, s)] == [
        ('进化孢子',0), ('强化孢子',0)]
    assert [shop.conversions_needed(60, n) for n in (0,10,59,60,115)] == [1,1,1,0,0]
    assert shop.conversions_needed(150, 75) == 1
    d.open_star_shop = lambda:s
    d.b.click_at = lambda *a:pytest.fail('Sold-out items must never be clicked')
    assert d.buy_star_spores()['spent'] == 0
    assert d.report['other_tasks']['star_spores']['converted'] == 0


def test_actual_purple_only_selection_and_yield(tmp_path):
    d = daily(tmp_path); templates(d.b)
    empty = captured('v0923-star-convert', True)
    selected = captured('v0923-star-selected', True)
    rows = shop.ultimate_candidates(empty)
    assert len(rows) == 1 and rows[0]['point'] == (971,289)
    assert shop.star_yield(d.b, empty) == 0
    d.b.read_number = lambda *a:75
    assert shop.star_yield(d.b, selected) == 75
    with pytest.raises(SafetyStop, match='未开启'):
        d.convert_one_ultimate(60, 0)


def test_purchase_modal_rejects_wrong_item_currency_quantity_or_price(tmp_path):
    d = daily(tmp_path); templates(d.b)
    wrong = captured('v0923-shop-preview', True)
    assert shop.spore_purchase_dialog(d.b, wrong, '进化孢子') is None
    s = deepcopy(wrong)
    s.words = [Word('进化孢子',w.box,w.score) if w.text == '幻化怪兽茧' else w for w in s.words]
    d.b.read_number = lambda s,roi:1 if roi[1] == 511 else 30
    assert shop.spore_purchase_dialog(d.b, s, '进化孢子')
    d.b.read_number = lambda s,roi:2 if roi[1] == 511 else 30
    assert shop.spore_purchase_dialog(d.b, s, '进化孢子') is None
    d.b.read_number = lambda s,roi:1 if roi[1] == 511 else 200
    assert shop.spore_purchase_dialog(d.b, s, '进化孢子') is None
    d.b.read_number = lambda s,roi:1 if roi[1] == 511 else 30
    s.image[640:682,600:645] = 0
    assert shop.spore_purchase_dialog(d.b, s, '进化孢子') is None


def test_donation_uses_left_count_currency_and_twenty_wan_only(tmp_path):
    d = daily(tmp_path); templates(d.b)
    s = captured('v0923-donation', True)
    assert shop.gold_donation_remaining(s) == (0,1)
    assert shop.gold_donation_offer(d.b, s) is None
    left = next(w for w in s.words if w.text == '剩余次数：0/1')
    left.text = '剩余次数：1/1'
    assert shop.gold_donation_offer(d.b, s) == (245,587)
    left.text = '剩余次数：5/5'
    assert shop.gold_donation_offer(d.b, s) is None
    left.text = '剩余次数：1/1'
    next(w for w in s.words if w.text == '20万').text = '200'
    assert shop.gold_donation_offer(d.b, s) is None


def test_donation_disabled_completed_and_pending_never_click(tmp_path):
    d = daily(tmp_path); templates(d.b)
    d.day = {}
    d.open_tribe_donation = lambda:pytest.fail('Disabled donation opened')
    assert d.tribe_gold_donation()['status'] == 'skipped'
    d.options['other']['tribe_gold_donation'] = True
    s = captured('v0923-donation', True)
    d.open_tribe_donation = lambda:s
    d.b.click_at = lambda *a:pytest.fail('Duplicate donation')
    assert d.tribe_gold_donation()['count'] == 0
    next(w for w in s.words if w.text == '剩余次数：0/1').text = '剩余次数：1/1'
    with pytest.raises(TaskBlocked, match='已有金币捐献记录'):
        d.tribe_gold_donation()
    d.day = {'tribe_donation_pending': True}
    with pytest.raises(TaskBlocked, match='未核实'):
        d.tribe_gold_donation()


def shop_machine(d, monkeypatch, *, balance=60, fail_receipt=False):
    state = {'balance':balance, 'counts':[1,1], 'clicks':[], 'item':None}
    s = captured('v0923-star-shop', True)
    def offers(*a):
        return [dict(name=name,remaining=state['counts'][i],price=30,point=(520+i*230,220))
                for i,name in enumerate(shop.SPORES)]
    monkeypatch.setattr(shop,'spore_offers',offers)
    monkeypatch.setattr(shop,'star_souls',lambda *a:state['balance'])
    monkeypatch.setattr(shop,'spore_purchase_dialog',lambda *a:SimpleNamespace(center=(640,630)))
    d.open_star_shop = lambda:s
    d.wait_for_screen = lambda *a,**k:s
    d.settle_star_receipt = lambda:s
    d.day = {}
    def click(q,p,anchors,reason):
        state['clicks'].append(reason)
        if '查看' in reason:
            state['item'] = next(i for i,n in enumerate(shop.SPORES) if n in reason)
        else:
            assert reason.startswith('购买1份') and '30饲星之魂' in reason
            if not fail_receipt:
                state['counts'][state['item']] -= 1
                state['balance'] -= 30
    d.b.click_at = click
    return state


def test_purchase_tracks_each_verified_cost_without_conversion(tmp_path, monkeypatch):
    d = daily(tmp_path)
    state = shop_machine(d, monkeypatch)
    d.convert_one_ultimate = lambda *a:pytest.fail('Conversion disabled')
    result = d.buy_star_spores()
    assert result['spent'] == 60 and result['remaining'] == 0
    assert result['purchased'] == {'进化孢子':1, '强化孢子':1}
    assert len(state['clicks']) == 4 and not d.day


def test_insufficient_currency_does_not_convert_without_opt_in(tmp_path, monkeypatch):
    d = daily(tmp_path)
    state = shop_machine(d, monkeypatch, balance=20)
    d.convert_one_ultimate = lambda *a:pytest.fail('Conversion disabled')
    result = d.buy_star_spores()
    assert result['status'] == 'skipped' and result['remaining'] == 20
    assert not state['clicks']


def test_conversion_only_fills_shortfall_then_buys(tmp_path, monkeypatch):
    d = daily(tmp_path)
    d.options['other']['convert_star_souls'] = True
    state = shop_machine(d, monkeypatch, balance=20)
    conversions = []
    def convert(required, before):
        conversions.append((required, before))
        state['balance'] += 75
        return state['balance']
    d.convert_one_ultimate = convert
    result = d.buy_star_spores()
    assert conversions == [(60,20)]
    assert result['converted'] == 1 and result['remaining'] == 35


def test_unconfirmed_purchase_is_not_replayed_on_retry(tmp_path, monkeypatch):
    d = daily(tmp_path)
    state = shop_machine(d, monkeypatch, fail_receipt=True)
    with pytest.raises(TaskBlocked, match='库存或余额'):
        d.buy_star_spores()
    assert d.day['star_purchase_pending']['name'] == '进化孢子'
    with pytest.raises(TaskBlocked, match='上次孢子购买'):
        d.buy_star_spores()
    assert len(state['clicks']) == 2


def test_conversion_confirmation_is_scoped_and_never_allows_diamonds():
    s = screen(('是否确认将选中怪兽用于饲星？',350,275,570,45),
               ('取消',420,480,70,35), ('确定',800,480,70,35))
    pending = {'rarity':'究极', 'count':1, 'yield':75}
    assert shop.star_conversion_confirmation(s,pending)
    assert shop.star_conversion_confirmation(s,None) is None
    assert shop.star_conversion_confirmation(s,{**pending,'count':2}) is None
    s.words[0].text = '是否消耗钻石给怪兽饲星？'
    assert shop.star_conversion_confirmation(s,pending) is None


def test_star_conversion_countdown_waits_without_click_and_keeps_guard_strict(tmp_path,monkeypatch):
    pending={'rarity':'究极','count':1,'yield':75}
    body=('怪兽饲星后将会消失，并获得该怪兽100%的怪兽经验，'
          '强化孢子、基因强化消耗的金币和对应的饲星之魂')
    waiting=screen((body,330,254,620,85),('是否确定进行怪兽饲星?',494,348,279,22),
                   ('取消',454,481,55,31),('00:01',765,484,63,25))
    ready=screen((body,330,254,620,85),('是否确定进行怪兽饲星?',494,348,279,22),
                 ('取消',454,481,55,31),('确定',765,484,63,25))
    empty=screen(('饲星坛',120,15,90,30),('怪兽饲星',10,335,110,35),
                 ('商店',20,630,70,30),('怪兽饲星',370,610,160,40))
    assert shop.star_conversion_countdown(waiting,pending)
    assert shop.star_conversion_confirmation(waiting,pending) is None
    d=daily(tmp_path);d.b.star_conversion_pending=pending
    d.b.guard(waiting)
    d.b.star_conversion_pending=None
    with pytest.raises(SafetyStop,match='补购或资源不足'):d.b.guard(waiting)
    d.b.star_conversion_pending=pending
    waiting.words[0].text+='；消耗钻石'
    with pytest.raises(SafetyStop,match='补购或资源不足'):d.b.guard(waiting)
    waiting.words[0].text=body
    frames=iter([waiting,ready,empty]);d.observe=lambda:next(frames)
    pauses=[];clicks=[];d.b.sleep=lambda n:pauses.append(n)
    d.b.click_at=lambda s,p,a,r:clicks.append(r)
    monkeypatch.setattr(shop,'star_yield',lambda b,s:0)
    assert d.settle_star_receipt() is empty
    assert pauses==[.5] and clicks==['确认仅转化已核实的1只究极怪兽']


def test_interrupted_star_confirmation_is_cancelled_before_new_attempt(tmp_path,monkeypatch):
    d=daily(tmp_path)
    d.day['star_conversion_pending']={'balance':100,'yield':75}
    modal=screen(('怪兽饲星后消失，并获得100%的怪兽经验和强化消耗的饲星之魂',330,254,620,85),
                 ('是否确定进行怪兽饲星?',494,348,279,22),
                 ('取消',454,481,55,31),('00:01',765,484,63,25))
    altar=screen(('饲星坛',120,15,90,30),('怪兽饲星',10,335,110,35),
                 ('商店',20,630,70,30),('怪兽饲星',370,610,160,40))
    d.observe=lambda:modal
    clicks=[];d.b.click_text=lambda s,p,**kw:clicks.append(p)
    d.wait_for_screen=lambda predicate,label,**kw:altar if predicate(altar) else None
    d.open_star_shop=lambda:screen(('商店',120,15,90,30))
    monkeypatch.setattr(shop,'star_souls',lambda b,s:100)
    d.reconcile_star_conversion_pending()
    assert clicks==['^取消$'] and 'star_conversion_pending' not in d.day
    assert d.b.star_conversion_pending is None


def test_conversion_waits_for_selected_monster_to_clear(tmp_path, monkeypatch):
    d = daily(tmp_path)
    selected = captured('v0923-star-selected', True)
    empty = captured('v0923-star-convert', True)
    states = iter([selected,empty]); pauses = []
    d.b.star_conversion_pending = {'rarity':'究极', 'count':1, 'yield':75}
    d.observe = lambda:next(states)
    d.b.sleep = lambda delay:pauses.append(delay)
    monkeypatch.setattr(shop,'star_yield',lambda b,s:75 if s is selected else 0)
    assert d.settle_star_receipt() is empty and pauses == [.5]


def test_tribe_stationary_drag_retries_before_declaring_an_edge(tmp_path, monkeypatch):
    from chao2 import activities
    d = daily(tmp_path)
    a = captured('v0923-tribe-blocked', True)
    b = captured('tribe-map-next', True)
    states = iter([a,a,b]); calls = []
    d.b.sleep = lambda *a:None
    d.b.wait = lambda job:SimpleNamespace(succeeded=True)
    d.b.controller = SimpleNamespace(post_swipe=lambda *args:calls.append(args))
    d.wait_for_screen = lambda *a,**k:next(states)
    result,moved = d.pan_tribe_map(a,1)
    assert result is b and moved and len(calls) == 3
