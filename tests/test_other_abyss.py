"""Moving tools into Other must preserve opt-in, saved choices and run state."""
from copy import deepcopy

import pytest

from chao2.configuration import SPECS, OTHER_SETTING_GROUPS, normalize_settings
from chao2.policy import TaskBlocked, UserStopped
from chao2.tool_settings import abyss_options
from test_configuration import daily


def abyss_only():
    return {field['key']: field['key'] == 'challenge_abyss'
            for field in SPECS['other']['fields'] if field['type'] == 'bool'}


def test_move_preserves_existing_capture_probabilities_and_abyss_teams():
    raw = {'abyss_options': {'teams': [2, 1]}, 'wild_capture_enabled': True,
           'wild_capture': {'ultimate': {'enabled': True, 'probability': 85}},
           'task_options': {'other': {'inactive_days': 9}}}
    before = deepcopy(raw)
    result = normalize_settings(raw)
    assert raw == before
    assert abyss_options(result)['teams'] == [2, 1]
    assert result['wild_capture_enabled']
    assert result['wild_capture']['ultimate'] == {'enabled': True, 'probability': 85}
    assert result['task_options']['other']['inactive_days'] == 9
    assert not result['task_options']['other']['challenge_abyss']


def test_other_group_metadata_is_complete_and_keeps_dependencies():
    fields = {f['key']: f for f in SPECS['other']['fields']}
    assert all(f['compact'] for f in fields.values())
    for group, members in OTHER_SETTING_GROUPS.items():
        assert members[0] == group and fields[group]['type'] == 'bool'
        assert all(fields[key]['group'] == group for key in members)
    assert fields['inactive_days']['enabled_when'] == 'remove_inactive_friends'
    assert fields['buy_blue_eggs_for_star_souls']['enabled_when'] == 'evolve_blue_for_star_souls'


def test_other_runs_abyss_once_when_selected(tmp_path):
    d = daily(tmp_path, {'task_options': {'other': abyss_only()}})
    calls = []
    d.home = lambda: None
    d.challenge_abyss = lambda: calls.append('abyss') or {'status': 'done', 'message': '先遣完成'}
    assert d.other() == '先遣完成'
    assert calls == ['abyss']
    assert d.report['other_tasks']['abyss']['status'] == 'done'


def test_other_does_not_run_abyss_when_disabled(tmp_path):
    options = abyss_only()
    options['challenge_abyss'] = False
    d = daily(tmp_path, {'task_options': {'other': options}})
    d.challenge_abyss = lambda: pytest.fail('Disabled abyss must not execute')
    assert d.other() == '其他任务的子任务均未开启'


@pytest.mark.parametrize('outcome', ['completed', 'partial'])
def test_abyss_subtask_shares_connection_without_completing_outer_run(tmp_path, monkeypatch, outcome):
    d = daily(tmp_path, {'abyss_options': {'teams': [2, 1]}})
    d.report['status'] = 'running'
    d.battles = 4
    seen = []
    settings = d.b.settings

    def play(player):
        assert player.b is d.b and player.report is d.report
        assert player.b.settings is settings
        assert d.options is settings['task_options']
        assert player.state is d.state and player.day is d.day
        assert player.start_time == d.start_time
        assert player.tool_options['teams'] == [2, 1]
        assert player.battles == 4 and player.limit == 6
        player.battles += 1
        player.report['team_attempts'] = [{'task': 'abyss', 'outcome': 'victory'}]
        player.report['status'] = outcome
        return '先遣结果'

    def finish(player):
        assert d.report['status'] == 'running'
        seen.append('finish')

    monkeypatch.setattr('chao2.abyss.AbyssPlayer.play', play)
    monkeypatch.setattr('chao2.abyss.AbyssPlayer.finish_world', finish)
    result = d.challenge_abyss()
    assert seen == ['finish']
    assert result['status'] == ('done' if outcome == 'completed' else 'skipped')
    assert result['attempts'] == 1
    assert d.report['status'] == 'running' and d.battles == 5
    assert d.b.settings is settings and d.options is settings['task_options']


@pytest.mark.parametrize('error', [TaskBlocked('未识别'), UserStopped('用户停止')])
def test_abyss_failure_or_stop_restores_outer_status(tmp_path, monkeypatch, error):
    d = daily(tmp_path)
    d.report['status'] = 'running'

    def play(player):
        player.report['status'] = 'partial'
        raise error

    monkeypatch.setattr('chao2.abyss.AbyssPlayer.play', play)
    with pytest.raises(type(error)):
        d.challenge_abyss()
    assert d.report['status'] == 'running'
