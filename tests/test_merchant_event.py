"""Captured merchant screens and interruption recovery; no live device inputs."""
import pytest

from chao2.backend import Word
from chao2.merchant import (is_merchant, is_merchant_shop, merchant_action,
                            merchant_choice, merchant_choices)
from chao2.policy import EncounterInterrupted, SafetyStop, UserStopped
from chao2.workflows import is_world
from chao2.activities import is_copy_list
from test_configuration import captured, daily, screen


def page(name):
    return captured('v0911-merchant-'+name)


def world():
    return screen(('事件', 1100, 620, 60, 30), ('领地', 1200, 620, 60, 30),
                  ('97/166', 500, 15, 80, 30), ('1129', 250, 15, 70, 30))


def setup(tmp_path):
    d = daily(tmp_path)
    d.active_task = 'copies'
    d.b.sleep = lambda _: None
    d.b.match_template = lambda s, name, *a: name == 'merchant-dialogue-arrow.png'
    d.b.save_screen = lambda *a: None
    d.checkpoint = lambda: None
    clicks = []
    d.b.click_at = lambda s, point, anchors, reason: clicks.append((point, reason))
    return d, clicks


@pytest.mark.parametrize('name', ['intro', 'choice', 'circle', 'circle-five', 'speed',
                                  'speed-again', 'keep-turning', 'enter-shop', 'shop'])
def test_actual_merchant_frames_never_count_as_world_or_copy_list(name):
    s = page(name)
    assert is_merchant(s) and not is_world(s) and not is_copy_list(s)
    assert is_merchant_shop(s) == (name == 'shop')
    # Even with readable world HUD anchors behind the dialogue, no map clicks.
    s.words.extend(world().words)
    assert not is_world(s)


def test_similar_pages_and_misplaced_titles_are_not_merchants():
    for name in ('v082-ambush', 'v082-map-choice', 'copy-current-detail'):
        assert not is_merchant(captured(name))
    s = page('intro')
    for w in s.words:
        if w.text == '神秘商人':
            w.box[1] = 300
    assert not is_merchant(s)
    assert not is_merchant(screen(('神秘商人', 20, 20, 180, 45)))


@pytest.mark.parametrize('name,expected', [
    ('choice', '不管它离开'), ('circle', '再绕着它转三圈'),
    ('circle-five', '继续绕着它转五圈'), ('speed', '加速'),
    ('speed-again', '停下离开'), ('keep-turning', '帮它填'),
    ('enter-shop', '表示下次再去'),
])
def test_leave_at_first_chance_and_resume_only_observed_middle_choices(name, expected):
    assert merchant_choice(page(name)).text == expected


def test_unknown_choices_or_other_npc_do_not_use_first_option(tmp_path):
    d, clicks = setup(tmp_path)
    s = page('circle')
    for w in s.words:
        if w.text == '再绕着它转三圈':
            w.text = '花费25钻石'
    assert merchant_action(d.b, s) is None
    s = page('keep-turning')
    for w in s.words:
        if '转转' in w.text:
            w.text = '其他商人'
    assert merchant_action(d.b, s) is None and not clicks


def test_options_loading_and_missing_header_never_advance_dialogue_arrow(tmp_path):
    d, _ = setup(tmp_path)
    s = page('choice')
    choices = merchant_choices(s)
    s.words = [w for w in s.words if w not in choices]
    assert merchant_action(d.b, s) is None  # Header only; animation in progress.
    s = page('choice')
    s.words = [w for w in s.words if w.text != '请选择']
    assert merchant_action(d.b, s) is None  # Choice text still visible.
    s.words = [w for w in s.words if w not in merchant_choices(s)]
    d.b.match_template = lambda *a: True  # Choice-header pixels still visible.
    assert merchant_action(d.b, s) is None


def test_dialogue_requires_actual_arrow_and_shop_uses_only_leave(tmp_path):
    d, _ = setup(tmp_path)
    assert merchant_action(d.b, page('intro'))[0] == 'dialogue'
    d.b.match_template = lambda *a: False
    assert merchant_action(d.b, page('intro')) is None
    s = page('shop')
    action = merchant_action(d.b, s)
    assert action[0] == 'shop' and action[1] == s.find('^离开$').center
    assert '极化石' in s.text and '240' in s.text  # Paid goods are not clicked.


def test_full_interruption_flow_waits_out_animation_and_does_not_repeat_clicks(tmp_path):
    d, clicks = setup(tmp_path)
    frames = iter([page('intro'), page('intro'), page('choice'), page('choice'),
                   page('choice'), screen(), world(), world()])
    d.observe = lambda *a: next(frames)
    returned = d.handle_merchant(page('intro'))
    assert is_world(returned)
    assert [reason for _, reason in clicks] == ['继续神秘商人对话', '神秘商人选择：不管它离开']
    assert d.active_task == 'copies' and d.battles == 0 and not d.task_counts
    row = d.report['merchant_events'][0]
    assert row['status'] == 'completed' and row['purchases'] == 0
    assert not d.report.get('battles') and not d.report.get('team_attempts')


def test_shop_only_leaves_and_does_not_report_tag_text_as_rewards(tmp_path):
    d, clicks = setup(tmp_path)
    frames = iter([page('shop'), page('shop'), world(), world()])
    d.observe = lambda *a: next(frames)
    d.handle_merchant(page('shop'))
    assert len(clicks) == 1 and clicks[0][0] == page('shop').find('^离开$').center
    assert not d.report.get('rewards') and d.report['merchant_events'][0]['purchases'] == 0


def test_choice_disappearing_before_dialogue_changes_is_not_clicked_again(tmp_path):
    d, clicks = setup(tmp_path)
    selected = page('speed-again')
    transition = page('speed-again')
    transition.words = [w for w in transition.words if w not in merchant_choices(transition) and w.text != '请选择']
    frames = iter([selected, transition, transition, world(), world()])
    d.observe = lambda *a: next(frames)
    d.handle_merchant(selected)
    assert len(clicks) == 1 and clicks[0][1] == '神秘商人选择：停下离开'


def test_unchanging_skip_page_retries_three_times_without_false_completion(tmp_path):
    d, clicks = setup(tmp_path)
    d.observe = lambda *a: page('choice')
    with pytest.raises(SafetyStop, match='已重试3次'):
        d.handle_merchant(page('choice'))
    assert len(clicks) == 4 and d.report['merchant_events'][0]['status'] == 'blocked'


def test_unknown_options_keep_scene_and_record_reason(tmp_path):
    d, clicks = setup(tmp_path)
    s = page('choice')
    for w in merchant_choices(s):
        w.text = '未知选项'
    d.observe = lambda *a: s
    with pytest.raises(SafetyStop, match='神秘商人'):
        d.handle_merchant(s)
    assert not clicks and d.report['merchant_events'][0]['status'] == 'blocked'


def test_user_stop_and_purchase_confirmation_are_never_handled_as_dialogue(tmp_path):
    d, clicks = setup(tmp_path)
    d.b.stop.set()
    with pytest.raises(UserStopped):
        d.handle_merchant(page('intro'))
    d.b.stop.clear()
    s = page('intro')
    s.words.extend(screen(('是否购买', 400, 250, 200, 40), ('取消', 430, 450, 80, 40)).words)
    with pytest.raises(SafetyStop, match='补购'):
        d.handle_merchant(s)
    assert not clicks


def test_merchant_before_requested_battle_rolls_back_attempt_not_a_copy_win(tmp_path):
    d, _ = setup(tmp_path)
    frames = iter([page('shop'), page('shop'), page('shop'), world(), world()])
    d.observe = lambda *a: next(frames)
    d.resource_balance('copies', '地图体力', 97)
    with pytest.raises(EncounterInterrupted):
        d.battle('地图体力20')
    assert d.battles == 0 and d.task_counts['copies'] == 0
    assert not d.report.get('battles') and not d.report.get('team_attempts')
    assert d.report['resource_usage']['copies']['地图体力']['spent'] == 0
    assert d.report['merchant_events'][0]['source_task'] == 'copies'


@pytest.mark.parametrize('method', ['home', 'await_detail', 'ensure_detail', 'await_page', 'sage_wait'])
def test_navigation_recovers_merchant_before_unknown_or_task_page_checks(tmp_path, method):
    d, clicks = setup(tmp_path)
    handled = []
    d.handle_merchant = lambda s: handled.append(s) or world()
    d.observe = lambda *a: page('intro')
    if method == 'home':
        assert is_world(d.home(page('intro')))
    else:
        with pytest.raises(EncounterInterrupted):
            if method == 'ensure_detail':
                d.ensure_detail(page('intro'))
            elif method == 'await_page':
                d.await_page('^异象$')
            elif method == 'sage_wait':
                d.sage_wait(lambda _: False, 'not ready')
            else:
                d.await_detail()
    assert len(handled) == 1 and not clicks


def test_overview_recovers_event_without_reopening_wrong_destination(tmp_path):
    d, clicks = setup(tmp_path)
    overview = screen(('玩法概览', 350, 20, 100, 30), ('每日挑战', 540, 20, 100, 30),
                      ('世界关卡', 350, 100, 100, 30))
    d.find_overview_entry = lambda _: (overview, 'target', overview.find('世界关卡'))
    d.observe = lambda: page('intro')
    handled = []
    d.handle_merchant = lambda s: handled.append(s)
    with pytest.raises(EncounterInterrupted):
        d.enter_overview('^世界关卡$')
    assert len(handled) == len(clicks) == 1


def test_anomaly_and_active_hunt_do_not_swallow_navigation_interruption(tmp_path):
    d, _ = setup(tmp_path)
    def interrupt():
        raise EncounterInterrupted('merchant handled')
    d.copy_battles = interrupt
    with pytest.raises(EncounterInterrupted):
        d.copies()
    d.run_hunt = interrupt
    d.report['hunt_batch'] = {'remaining': 3}
    d.wild_daily_active = True
    with pytest.raises(EncounterInterrupted):
        d.hunt()
    assert d.wild_daily_active and d.report['hunt_batch']['remaining'] == 3


def test_original_target_reopens_with_same_team_and_only_real_battle_is_counted(tmp_path):
    d, _ = setup(tmp_path)
    d.options['copies']['teams'] = [2]
    detail = captured('copy-current-detail')
    frames = iter([page('intro'), captured('v082-ambush-result')])
    d.observe = lambda *a: next(frames)
    d.handle_merchant = lambda s: None
    d.exit_result = lambda s: None
    d.verify_instant_setting = lambda *a: None
    d.b.click_text = lambda *a: None
    calls = []
    d.select_team = lambda s, team: calls.append(('team', team)) or s
    def opener():
        calls.append(('open',))
        return detail
    assert d.play_encounter('copies', opener, '地图体力20')
    assert calls == [('open',), ('team', 2), ('open',), ('team', 2)]
    assert d.battles == d.task_counts['copies'] == 1
    assert len(d.report['team_attempts']) == len(d.report['battles']) == 1
