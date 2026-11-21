"""Captured abyss layouts and failure/cancellation/resource control flow."""
from datetime import datetime
import copy
import pytest

from chao2.abyss import (AbyssPlayer, abyss_target, is_abyss_menu, is_abyss_detail,
                         is_abyss_affixes, suppressed_slots, verify_abyss_entry,
                         next_refresh, abyss_empty)
from chao2.backend import Backend
from chao2.policy import TaskBlocked, UserStopped, FightLost
from chao2.tool_settings import abyss_options
from test_configuration import captured, screen


def player(tmp_path, teams=(1, 2, 3)):
    b = Backend({'abyss_options': {'teams': list(teams)}}, log=lambda _: None)
    b.sleep = lambda _: None
    b.save_screen = lambda *a: None
    b.match_template = lambda *a: True
    p = AbyssPlayer(b, {'folder': tmp_path, 'events': []})
    return p


def with_stamina(s, value):
    s = copy.deepcopy(s)
    for w in s.words:
        if '/166' in w.text:
            w.text = f'{value}/166'
    return s


def test_real_pages_are_distinct_and_list_target_excludes_header_and_tab():
    menu = captured('v099-abyss-menu', True)
    detail = captured('v099-abyss-detail', True)
    affixes = captured('v099-abyss-affixes-after', True)
    assert is_abyss_menu(menu) and abyss_target(menu).center == (893, 225)
    assert is_abyss_detail(detail) and is_abyss_affixes(affixes)
    assert not is_abyss_detail(menu) and not is_abyss_menu(detail)
    assert not is_abyss_menu(affixes) and abyss_target(affixes) is None
    for name in ('v089-event-copies', 'v081-tour-detail', 'puzzle-initial'):
        s = captured(name, True)
        assert not any((is_abyss_menu(s), is_abyss_detail(s), is_abyss_affixes(s)))


def test_suppressed_icons_are_read_from_both_scroll_positions():
    for name in ('before', 'after', 'bottom'):
        assert suppressed_slots(captured('v099-abyss-affixes-'+name, True)) == [1, 2, 5, 6]
    assert suppressed_slots(captured('v099-abyss-affixes-after')) is None
    assert suppressed_slots(captured('v099-abyss-menu', True)) is None


def test_already_full_suppression_preserves_user_selection(tmp_path):
    p = player(tmp_path)
    s = captured('v099-abyss-affixes-bottom', True)
    p.b.click_at = lambda *a: pytest.fail('Do not unload or replace four selected monsters')
    p.close_affixes = lambda q: q
    assert p.suppress(s) is s
    assert p.report['suppression']['after'] == [1, 2, 5, 6]


def test_partial_suppression_uses_one_client_auto_action_and_checks_result(tmp_path):
    p = player(tmp_path)
    before = captured('v099-abyss-affixes-after', True)
    after = captured('v099-abyss-affixes-after', True)
    # Simulate unassigned slots using an actual active-affix icon.
    before.image[114:156, 760:800] = before.image[114:156, 840:880]
    assert suppressed_slots(before) == [2, 5, 6]
    calls = []
    p.b.click_at = lambda s, pt, anchors, reason: calls.append((pt, reason))
    p.wait_screen = lambda predicate, message: after if predicate(after) else pytest.fail(message)
    p.close_affixes = lambda s: s
    p.suppress(before)
    assert len(calls) == 1 and calls[0][1] == '深渊先遣一键压制'
    assert p.report['suppression'] == {'before': [2, 5, 6], 'after': [1, 2, 5, 6], 'maximum': 4}


def test_unreadable_suppression_does_not_click(tmp_path):
    p = player(tmp_path)
    p.b.click_at = lambda *a: pytest.fail('Unknown icons must not authorize input')
    with pytest.raises(TaskBlocked, match='状态未读清'):
        p.suppress(captured('v099-abyss-affixes-after'))


def test_back_from_detail_accepts_preserved_event_panel_without_world_detour(tmp_path):
    p = player(tmp_path)
    detail, menu = captured('v099-abyss-detail'), captured('v099-abyss-menu')
    frames = iter([detail, menu])
    p.observe = lambda: next(frames)
    p.wait_screen = lambda predicate, message: menu if predicate(menu) else pytest.fail(message)
    clicks = []
    p.b.click_at = lambda s, pt, *a: clicks.append(pt)
    p.open_world_events = lambda *a: pytest.fail('Already in the right list')
    assert p.menu_page() is menu and clicks == [(43, 28)]


@pytest.mark.parametrize('missing', ['abyss-stamina.png', 'abyss-instant-off.png'])
def test_entry_blocks_unverified_cost_or_enabled_instant_break(missing):
    b = Backend({})
    b.match_template = lambda s, name, *a: name != missing
    with pytest.raises(TaskBlocked):
        verify_abyss_entry(b, captured('v099-abyss-detail', True))


def test_entry_blocks_wrong_price_even_if_currency_icon_matches():
    b = Backend({})
    b.match_template = lambda *a: True
    s = captured('v099-abyss-detail')
    for w in s.words:
        if w.text == '50' and w.box[1] < 680:
            w.text = '100'
    with pytest.raises(TaskBlocked, match='费用'):
        verify_abyss_entry(b, s)


def test_overflow_stamina_can_still_be_spent():
    b = Backend({})
    b.match_template = lambda *a: True
    assert verify_abyss_entry(b, with_stamina(captured('v099-abyss-detail'), 200)) == (200, 166)


def test_real_empty_page_skips_without_affix_or_battle_input(tmp_path):
    p = player(tmp_path)
    empty = captured('v099-abyss-empty', True)
    assert abyss_empty(empty) and abyss_target(empty) is None
    p.menu_page = lambda: empty
    p.suppress = p.open_target = lambda *a: pytest.fail('Completed round must not start again')
    assert '没有可挑战' in p.play()
    assert p.report['status'] == 'completed'


def test_blank_loading_card_is_not_reported_complete(tmp_path):
    p = player(tmp_path)
    s = captured('v099-abyss-empty', True)
    s.words = [w for w in s.words if w.text not in ('无', '深渊先遣未出现')]
    assert is_abyss_menu(s) and not abyss_empty(s)
    p.menu_page = p.observe = lambda: s
    p.suppress = p.open_target = lambda *a: pytest.fail('Loading is not an encounter')
    with pytest.raises(TaskBlocked, match='未将空白当成完成'):
        p.play()


def flow(tmp_path, outcomes, balances, teams=(1, 2, 3)):
    p = player(tmp_path, teams)
    index = [0]
    p.menu_page = lambda: with_stamina(captured('v099-abyss-menu'), balances[index[0]])
    p.suppress = lambda s: s
    p.open_target = lambda s: with_stamina(captured('v099-abyss-detail'), balances[index[0]])
    chosen = []
    p.select_team = lambda s, t, **kw: chosen.append(t) or s
    clicks = []
    p.b.click_text = lambda *a, **kw: clicks.append(a[1])
    p.exit_result = lambda s: None
    p.checkpoint = lambda: None
    def battle(*a, **kw):
        outcome = outcomes[index[0]]
        index[0] += 1
        p.battles += 1
        if outcome == 'failed':
            raise FightLost(screen(('失败', 100, 200, 200, 50), ('退出', 1100, 600, 100, 50)))
        if outcome == 'stop':
            raise UserStopped('用户停止')
        return screen(('胜利', 100, 200, 200, 50), ('获得奖励', 700, 200, 200, 50), ('退出', 1100, 600, 100, 50))
    p.battle = battle
    p.start_challenge=lambda task,s,*a:p.b.click_text(s,'^前往挑战$')
    return p, chosen, clicks


def test_victory_finishes_once_without_challenging_other_teams(tmp_path):
    p, chosen, clicks = flow(tmp_path, ['victory'], [60, 10])
    assert '胜利' in p.play()
    assert chosen == [1] and clicks == ['^前往挑战$']
    assert p.report['status'] == 'completed'
    assert p.report['team_attempts'][0]['stamina_spent'] == 50


def test_failure_tries_next_team_then_stops_on_victory(tmp_path):
    p, chosen, _ = flow(tmp_path, ['failed', 'victory'], [60, 60, 11])
    p.play()
    assert chosen == [1, 2]
    assert [r['stamina_spent'] for r in p.report['team_attempts']] == [0, 50]


def test_all_teams_fail_once_without_looping(tmp_path):
    p, chosen, _ = flow(tmp_path, ['failed']*3, [60]*4)
    assert '均未通过' in p.play()
    assert chosen == [1, 2, 3] and p.report['status'] == 'partial'


def test_insufficient_stamina_does_not_open_formation_or_fight(tmp_path):
    p, chosen, clicks = flow(tmp_path, [], [49])
    assert '49/166' in p.play()
    assert chosen == [] and clicks == [] and p.report['status'] == 'partial'


def test_after_charged_defeat_insufficient_stamina_prevents_fallback(tmp_path):
    p, chosen, clicks = flow(tmp_path, ['failed'], [60, 10])
    assert '体力10/166' in p.play()
    assert chosen == [1] and len(clicks) == 1


def test_stop_never_launches_fallback_team(tmp_path):
    p, chosen, clicks = flow(tmp_path, ['stop'], [60])
    with pytest.raises(UserStopped):
        p.play()
    assert chosen == [1] and len(clicks) == 1
    assert p.report['team_attempts'][0]['outcome'] == 'unconfirmed'


def test_empty_team_list_uses_current_formation(tmp_path):
    p, chosen, _ = flow(tmp_path, ['victory'], [60, 10], teams=())
    p.play()
    assert chosen == [None]


def test_invalid_options_rejected():
    assert abyss_options({}) == {'teams': [1, 2, 3], 'wall_mode': 'ignore'}
    for raw in ('bad', {'teams': [1, 1]}, {'teams': [True]}, {'teams': [6]}):
        with pytest.raises(ValueError):
            abyss_options({'abyss_options': raw})


@pytest.mark.parametrize('utc,expected', [
    ('2026-10-16T15:59:59+00:00', '2026-10-17T00:00:00+08:00'),
    ('2026-10-16T16:00:00+00:00', '2026-10-20T00:00:00+08:00'),
    ('2026-10-20T04:00:00+00:00', '2026-10-22T00:00:00+08:00'),
])
def test_next_refresh_uses_beijing_midnight_not_host_timezone(utc, expected):
    assert next_refresh(datetime.fromisoformat(utc)).isoformat() == expected
    with pytest.raises(ValueError):
        next_refresh(datetime(2026, 10, 17))
