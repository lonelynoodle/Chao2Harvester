"""Reuse a confirmed wall across one run, including nested tool players."""
from copy import deepcopy
import json
import pytest
import chao2.battle_wall as walls
from chao2.abyss import AbyssPlayer
from chao2.workflows import Daily,write_report
from chao2.policy import IsolatedTaskError,SafetyStop,UserStopped
from test_configuration import daily,screen
from test_battle_wall_0983 import game,formation,wall_page


def forbid(*a,**k):pytest.fail('Matching per-run cache must not inspect or navigate')


def test_cache_hit_has_no_image_processing_screenshots_navigation_or_checkpoint(tmp_path,monkeypatch):
    d,state,clicks,_=game(tmp_path,'attack')
    d.prepare_battle_wall('nest',state[0]);original=screen()
    monkeypatch.setattr(walls,'formation_wall_mode',forbid)
    monkeypatch.setattr(walls,'formation_header',forbid)
    d.observe=d.formation_page=d.territory=d.checkpoint=forbid
    d.b.click_text=d.b.click_at=forbid
    assert d.prepare_battle_wall('nest',original) is original
    runtime=d.report['battle_wall_runtime']
    assert runtime['mode']=='attack' and runtime['confirmed']
    assert runtime['checks']==1 and runtime['cache_hits']==1 and not clicks
    assert len(d.report['battle_wall_checks'])==1


def test_cache_follows_real_switches_and_skip_uses_latest_type(tmp_path):
    d,state,clicks,switches=game(tmp_path,'attack')
    d.prepare_battle_wall('nest',state[0])
    d.options['nest']['wall_mode']='defense'
    d.prepare_battle_wall('nest',state[0])
    assert d.report['battle_wall_runtime']['mode']=='defense'
    d.prepare_battle_wall('nest',state[0])
    d.options['nest']['wall_mode']='attack'
    d.prepare_battle_wall('nest',state[0]);d.prepare_battle_wall('nest',state[0])
    runtime=d.report['battle_wall_runtime']
    assert switches==['attack','defense']
    assert runtime['checks']==3 and runtime['cache_hits']==2
    assert runtime['switch_attempts']==2 and runtime['mode']=='attack'
    assert 'invalidation_reason' not in runtime


def test_different_activity_and_task_instance_share_wall_cache(tmp_path,monkeypatch):
    d,state,_,_=game(tmp_path,'attack');d.prepare_battle_wall('nest',state[0])
    d.options['main']['wall_mode']='attack';d.active_task='main'
    monkeypatch.setattr(walls,'formation_wall_mode',forbid);d.observe=forbid
    d._active_instance={'key':'main','id':'main_second'}
    assert d.prepare_battle_wall('main',screen())
    assert d.report['battle_wall_runtime']['cache_hits']==1
    assert len(d.report['battle_wall_checks'])==1


def test_nested_abyss_uses_same_parent_run_record_without_resetting_it(tmp_path,monkeypatch):
    d,state,_,_=game(tmp_path,'attack');d.prepare_battle_wall('nest',state[0])
    child=AbyssPlayer(d.b,d.report)
    child.tool_options['wall_mode']='attack';child.observe=forbid
    monkeypatch.setattr(walls,'formation_wall_mode',forbid)
    assert child.prepare_battle_wall('abyss',screen())
    assert d.report['battle_wall_runtime']['checks']==1
    assert d.report['battle_wall_runtime']['cache_hits']==1


def test_new_run_rechecks_even_when_using_the_same_backend(tmp_path,monkeypatch):
    d,state,_,_=game(tmp_path,'attack');d.prepare_battle_wall('nest',state[0])
    report={'folder':tmp_path,'events':[]}
    later=Daily(d.b,report);later.active_task='nest'
    actual=walls.formation_wall_mode;calls=[]
    def detect(s):calls.append(s);return actual(s)
    monkeypatch.setattr(walls,'formation_wall_mode',detect)
    later.prepare_battle_wall('nest',formation('attack'))
    assert calls and report['battle_wall_runtime']['checks']==1
    assert report['battle_wall_runtime']['cache_hits']==0
    assert report['battle_wall_runtime'] is not d.report['battle_wall_runtime']


def test_ignore_neither_creates_nor_clears_current_run_record(tmp_path):
    d=daily(tmp_path);d.options['nest']['wall_mode']='ignore';s=screen()
    assert d.prepare_battle_wall('nest',s) is s
    assert 'battle_wall_runtime' not in d.report
    d.remember_wall('attack','test');before=deepcopy(d.report)
    d.prepare_battle_wall('nest',s)
    assert before==d.report


@pytest.mark.parametrize('failure',[SafetyStop('点击失败'),UserStopped('用户停止')])
def test_switch_attempt_invalidates_old_cache_before_sending_input(tmp_path,failure):
    d,state,_,_=game(tmp_path,'attack');d.prepare_battle_wall('nest',state[0])
    state[0]=wall_page('attack')
    def click(*a,**k):
        assert d.report['battle_wall_runtime']['confirmed'] is False
        raise failure
    d.b.click_at=click
    with pytest.raises(type(failure)):d.set_wall_page(state[0],'defense',{'switches':0})
    assert d.report['battle_wall_runtime']['mode'] is None
    assert d.report['battle_wall_runtime']['confirmed'] is False


def test_unverified_switch_cannot_be_reused_as_success(tmp_path):
    d,state,_,_=game(tmp_path,'defense',swallow=9)
    with pytest.raises(IsolatedTaskError):d.prepare_battle_wall('nest',state[0])
    runtime=d.report['battle_wall_runtime']
    assert runtime['mode'] is None and not runtime['confirmed']
    # A later observed, already-correct formation must still be inspected.
    state[0]=formation('attack');d.prepare_battle_wall('nest',state[0])
    assert runtime['checks']==2 and runtime['cache_hits']==0 and runtime['confirmed']


def test_record_is_saved_in_run_report_not_configuration_or_account_state(tmp_path):
    d,state,_,_=game(tmp_path,'attack');settings=deepcopy(d.b.settings);account=deepcopy(d.state)
    d.prepare_battle_wall('nest',state[0]);d.prepare_battle_wall('nest',state[0]);write_report(d.report)
    saved=json.loads((tmp_path/'report.json').read_text('utf-8'))['battle_wall_runtime']
    assert saved['mode']=='attack' and saved['cache_hits']==1 and saved['confirmed_at']
    assert d.b.settings==settings and d.state==account


def test_cache_hit_still_respects_user_stop(tmp_path):
    d,state,_,_=game(tmp_path,'attack');d.prepare_battle_wall('nest',state[0]);d.b.stop.set()
    with pytest.raises(UserStopped):d.prepare_battle_wall('nest',screen())
