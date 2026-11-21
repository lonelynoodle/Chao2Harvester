import threading
from types import SimpleNamespace

import pytest

from chao2.policy import TaskBlocked, UserStopped
from chao2.stamina_inventory import potion_grid_tail, potion_stock
import chao2.workflows as flow
from test_configuration import daily, screen


def bag(*details, items=True):
    s = screen(('背包', 140, 14, 48, 27), ('全部', 14, 191, 58, 32), ('道具', 20, 321, 44, 20),
               ('元核', 20, 420, 46, 26), ('主要获得途径', 786, 382, 123, 23), *details)
    if items:
        s.image[265:360, :100] = (45, 190, 215)
    s.image[84:672, 140:715] = (65, 58, 44)
    for x in (145, 242, 339, 436, 533, 630):
        s.image[84:672, x:x+84] = (36, 32, 22)
    return s


def world():
    return screen(('任务挑战', 1196, 43, 78, 24), ('世界回响', 1191, 135, 72, 25), ('4/146', 510, 13, 85, 25))


def test_empty_inventory_returns_without_swiping_and_is_memoized_for_the_run(tmp_path):
    d = daily(tmp_path, {'task_options': {'main': {'auto_potions': True}}})
    d.selected = ['main']
    empty = bag(('已拥有860', 856, 146, 93, 23))
    opened = bag(items=False)
    d.home = lambda: world()
    d.await_page = lambda *a: opened
    d.observe = lambda: empty
    d.potion_icon = lambda _: None
    opens = []
    d.click_world = lambda *a: opens.append('bag')
    def click_text(s, pattern, **kwargs):
        assert pattern == '^道具$'
    d.b.click_text = click_text
    d.b.controller = SimpleNamespace(post_swipe=lambda *a: pytest.fail('Empty slots already establish the end'))
    assert potion_grid_tail(empty)
    assert d.use_stamina_potion() is None
    assert d.use_stamina_potion() is None
    assert opens == ['bag']
    assert d.stamina_potion_reason == '背包移动力药水库存为0'


def test_empty_grid_check_excludes_loading_other_tabs_and_last_visible_items():
    assert not potion_grid_tail(screen())
    assert not potion_grid_tail(bag(items=False))
    occupied = bag()
    occupied.image[610:658, 630:710] = (223, 185, 125)
    assert not potion_grid_tail(occupied)


@pytest.mark.parametrize('text', ['已拥有0', '已拥有 O'])
def test_zero_stock_from_potion_details(tmp_path, text):
    d = daily(tmp_path, {'task_options': {'main': {'auto_potions': True}}})
    d.selected = ['main']
    d.home = lambda: world()
    potion = bag(('移动力药水', 860, 108, 120, 28), (text, 856, 146, 93, 23),
                 ('使用后可获得100移动力', 757, 220, 220, 24))
    d.potion_inventory = lambda: potion
    d.b.click_text = lambda *a, **k: pytest.fail('Nothing in stock')
    assert potion_stock(potion) == 0
    assert d.use_stamina_potion() is None
    assert d._stamina_potions_unavailable


def test_returning_from_real_bag_layout_uses_back_instead_of_resource_description(tmp_path):
    d = daily(tmp_path)
    current = [bag(('已拥有860', 856, 146, 93, 23))]
    d.observe = lambda: current[0]
    clicks = []
    def click(s, point, anchors, reason):
        clicks.append((point, reason))
        current[0] = world()
    d.b.click_at = click
    assert flow.is_world(d.recover_failed_task())
    assert clicks == [((43, 28), '退出背包')]


def test_last_bottle_disappearing_does_not_read_stock_of_the_next_item(tmp_path):
    d = daily(tmp_path, {'task_options': {'main': {'auto_potions': True}}})
    d.selected = ['main']
    selected = bag(('移动力药水', 860, 108, 120, 28), ('已拥有1', 856, 146, 93, 23),
                   ('使用后可获得100移动力', 757, 220, 220, 24))
    after = bag(('饲星之魂', 854, 108, 110, 28), ('已拥有860', 856, 146, 93, 23))
    dialog = screen(('移动力药水', 570, 273, 139, 27), ('已拥有1', 596, 309, 92, 24),
                    ('使用数量', 334, 363, 83, 24), ('取消', 456, 459, 53, 29),
                    ('确定', 770, 459, 55, 30))
    resources = iter([{'stamina': 4, 'stamina_cap': 146}, {'stamina': 104, 'stamina_cap': 146}])
    d.home = lambda: world()
    d.world_resources = lambda _: next(resources)
    d.potion_inventory = lambda: selected
    d.potion_icon = lambda _: None
    d.await_page = lambda *a: dialog
    d.b.read_number = lambda *a: 1
    d.observe = lambda: after
    clicks = []
    d.b.click_text = lambda s, pattern, **kw: clicks.append(pattern)
    assert d.use_stamina_potion() == 100
    assert d.use_stamina_potion() is None
    assert clicks == ['^使用$', '^确定$']
    assert d.report['stamina_potions'][0]['stock_after'] == 0


@pytest.mark.parametrize('failure', [False, True])
def test_daily_queue_continues_after_stock_empty_or_refill_failure(tmp_path, monkeypatch, failure):
    current = [world()]
    actions = []
    monkeypatch.setattr(flow.Backend, 'connect', lambda _: None)
    monkeypatch.setattr(flow, 'create_report', lambda: {'folder': tmp_path, 'tasks': {}, 'events': []})
    monkeypatch.setattr(flow.Daily, 'observe', lambda self, *a, **kw: current[0])
    monkeypatch.setattr(flow.Daily, 'save_state', lambda _: None)
    monkeypatch.setattr(flow.Daily, 'stamina_outlet_available', lambda *a: True)
    monkeypatch.setattr(flow.Daily, 'main', lambda _: actions.append('main') or '体力不足5')
    monkeypatch.setattr(flow.Daily, 'exploration', lambda _: actions.append('exploration') or 'done')
    monkeypatch.setattr(flow.Daily, 'rewards', lambda _: actions.append('rewards') or 'done')
    def click(self, s, point, anchors, reason):
        assert point == (43, 28) and reason == '退出背包'
        actions.append('back')
        current[0] = world()
    monkeypatch.setattr(flow.Backend, 'click_at', click)
    def inventory(self):
        actions.append('bag')
        current[0] = bag(('已拥有860', 856, 146, 93, 23))
        if failure:
            raise TaskBlocked('药水数量未读清')
        return None
    monkeypatch.setattr(flow.Daily, 'potion_inventory', inventory)
    settings = {'unordered_tasks': False, 'wild_capture_enabled': False, 'free_summon_enabled': False,
                'task_queue': [{'id': 'main', 'key': 'main', 'enabled': True, 'options': {
                    'auto_three_shots': False, 'auto_potions': True}},
                    {'id': 'exploration', 'key': 'exploration', 'enabled': True},
                    {'id': 'rewards', 'key': 'rewards', 'enabled': True}]}
    report = flow.run_daily(settings, ['main', 'exploration', 'rewards'], threading.Event(), log=lambda _: None)
    assert actions == ['main', 'bag', 'back', 'exploration', 'rewards']
    assert report['stamina_refill']['potions'] == 0
    assert report['status'] == ('partial' if failure else 'completed')
    assert bool(report.get('stamina_refill_failures')) is failure


def test_refill_recovery_propagates_user_stop(tmp_path):
    d = daily(tmp_path)
    def stop():
        raise UserStopped('用户停止')
    d.use_stamina_potion = stop
    d.recover_failed_task = lambda: pytest.fail('A user stop is not a failed refill')
    with pytest.raises(UserStopped):
        d.try_stamina_refill('potion')
