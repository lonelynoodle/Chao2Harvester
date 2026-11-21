from datetime import datetime

import pytest

from chao2.configuration import normalize_settings
from chao2.daily_upgrades import (
    BEIJING, daily_upgrade_progress, monster_slots,
)
from chao2.policy import TaskBlocked
from test_configuration import daily, screen


def test_daily_upgrades_are_off_by_default_and_core_order_is_validated():
    options = normalize_settings({})['task_options']['other']
    assert not options['daily_core_upgrade'] and not options['daily_monster_upgrade']
    assert options['daily_core_order'] == 'forward'
    with pytest.raises(ValueError):
        normalize_settings({'task_options': {'other': {'daily_core_order': 'random'}}})


def test_progress_uses_the_requested_row():
    s = screen(('每日挑战', 80, 520, 100, 30), ('本周活跃', 305, 103, 91, 24),
               ('任意怪兽提升1级(0/1)', 334, 321, 215, 26),
               ('任意元核强化1次', 333, 444, 180, 25),
               ('已领取', 788, 447, 50, 18))
    assert daily_upgrade_progress(s, 'monster') == 0
    assert daily_upgrade_progress(s, 'core') == 1
    s.words = [word for word in s.words if word.text != '已领取']
    assert daily_upgrade_progress(s, 'core') is None


@pytest.mark.parametrize('kind', ['core', 'monster'])
def test_completed_daily_challenge_spends_nothing(tmp_path, kind):
    d = daily(tmp_path)
    d.find_daily_upgrade_progress = lambda _: 1
    d.territory = lambda: pytest.fail('Completed row must not open the upgrade page')
    assert d.run_daily_upgrade(kind)['status'] == 'skipped'


def core_page(name, left=False, right=False):
    s = screen(('元核强化', 576, 59, 128, 32), ('元核属性', 694, 137, 83, 23),
               (name, 301, 502, 137, 27))
    if left:
        s.image[330:400, 22:76] = (40, 182, 230)
    if right:
        s.image[330:400, 1200:1258] = (40, 182, 230)
    return s


@pytest.mark.parametrize('order,expected', [('forward', '第二元核'), ('reverse', '第三元核')])
def test_core_traverses_in_requested_direction_until_single_upgrade(tmp_path, order, expected):
    d = daily(tmp_path, {'task_options': {'other': {'daily_core_order': order}}})
    pages = [core_page('第一元核', right=True), core_page('第二元核', left=True, right=True),
             core_page('第三元核', left=True)]
    grid = screen(('怪兽信息', 124, 14, 89, 28), ('筛选', 260, 91, 45, 25),
                  ('元核分解', 409, 90, 88, 26))
    grid.image[160:230, 56:133] = (80, 145, 200)
    details = screen(('元核属性', 146, 113, 84, 24), ('强化', 69, 516, 59, 30))
    d.await_page = lambda *a, **k: grid
    d.upgrade_swipe = lambda s, *a: s
    d.b.click_at = d.b.click_text = lambda *a, **k: None
    pending = iter([details, pages[0]])
    d.wait_for_screen = lambda *a, **k: next(pending)
    d.move_core = lambda s, direction: pages[next(i for i, page in enumerate(pages) if page is s)
                                            + (1 if direction == 'right' else -1)]
    inspected = []
    def offer(s):
        name = s.words[-1].text
        inspected.append(name)
        return {'name': name} if s is not pages[0] else None
    d.core_upgrade_offer = offer
    committed = []
    d.commit_daily_upgrade = lambda kind, offer, receipts: committed.append(offer['name']) or offer
    assert d.upgrade_one_core(grid, {})['name'] == expected
    assert committed == [expected]
    assert inspected == (['第一元核', expected] if order == 'forward' else [expected])


def monster_page(selected=174, level=10):
    s = screen(('怪兽信息', 124, 14, 89, 28), ('攻击力', 698, 230, 72, 24),
               ('体力', 700, 191, 48, 24), (str(level), 690, 416, 68, 39))
    for x in (174, 300, 426):
        s.image[696:704, x-55:x+55] = (150, 155, 200)
    s.image[584:596, selected-51:selected+51] = (245, 170, 50)
    return s


def test_monster_scans_left_to_right_and_stops_at_first_eligible(tmp_path):
    d = daily(tmp_path)
    s = monster_page()
    assert monster_slots(s) == [(174, 640), (300, 640), (426, 640)]
    current = [s]
    d.upgrade_swipe = lambda q, *a: q
    def wait(predicate, *a, **k):
        assert predicate(current[0])
        return current[0]
    d.wait_for_screen = wait
    clicks = []
    def select(q, point, *a):
        clicks.append(point)
        current[0] = monster_page(point[0])
    d.b.click_at = select
    checked = []
    def offer(q, point):
        checked.append(point)
        return {'slot': point} if point[0] > 250 else None
    d.monster_upgrade_offer = offer
    d.commit_daily_upgrade = lambda kind, row, *a: row
    assert d.upgrade_one_monster(s, {})['slot'] == (300, 640)
    assert checked == [(174, 640), (300, 640)] and clicks == [(300, 640)]


@pytest.mark.parametrize('leveled', [True, False])
def test_upgrade_submits_once_and_persists_pending_or_confirmed(tmp_path, leveled):
    d = daily(tmp_path)
    s = monster_page(level=10)
    q = monster_page(level=11 if leveled else 10)
    offer = {'level': 10, 'slot': (174, 640), 'price': 8500, 'point': (958, 436)}
    d.monster_upgrade_offer = lambda fresh, slot: offer
    d.observe = lambda: s
    def wait(predicate, *a, **k):
        if not predicate(q):
            raise TaskBlocked('level unchanged')
        return q
    d.wait_for_screen = wait
    d.find_daily_upgrade_progress = lambda _: 0
    sent = []
    d.b.click_at = lambda s, point, *a: sent.append(point)
    date = datetime.now(BEIJING).date().isoformat()
    receipts = d.state.setdefault(date, {}).setdefault('daily_upgrades', {})
    if leveled:
        assert d.commit_daily_upgrade('monster', offer, receipts)['new_level'] == 11
        assert d.daily_monster_upgrade()['status'] == 'skipped'
    else:
        with pytest.raises(TaskBlocked, match='待核实'):
            d.commit_daily_upgrade('monster', offer, receipts)
        with pytest.raises(TaskBlocked, match='待核实'):
            d.daily_monster_upgrade()
    assert sent == [(958, 436)] and d.state_file.exists()


def test_core_upgrade_checks_the_same_core_and_new_level(tmp_path):
    d = daily(tmp_path)
    s = core_page('测试元核')
    wrong = core_page('另一个元核')
    received = core_page('测试元核')
    for frame in (wrong, received):
        frame.words.extend(screen(('等级2', 366, 356, 86, 45)).words)
    offer = {'name': '测试元核', 'level': 1, 'price': 4800, 'point': (945, 594)}
    d.observe = lambda: s
    d.core_upgrade_offer = lambda _: offer
    def wait(predicate, *a, **k):
        assert not predicate(wrong)
        assert predicate(received)
    d.wait_for_screen = wait
    clicks = []
    d.b.click_at = lambda s, point, anchors, reason: clicks.append((point, anchors))
    assert d.commit_daily_upgrade('core', offer, {})['new_level'] == 2
    assert clicks == [((945, 594), ['^元核强化$', '^强化$', '^测试元核$'])]
