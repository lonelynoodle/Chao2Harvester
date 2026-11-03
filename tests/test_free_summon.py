"""Free-draw guards and real cooldown screen; no game input."""
import copy
import time
import pytest
from test_configuration import daily,screen,captured
from chao2.configuration import normalize_settings
from chao2.free_summon import (free_summon_enabled,cooldown_seconds,overview_summon_state,
    is_summon_page,free_summon_button,summon_balance)
from chao2.policy import SafetyStop


def summon(free=True):
    s=screen(('造唤台',130,14,70,28),('卡池详情',1120,451,90,24),('造唤十次',762,611,92,29),
        ('造唤一次',425,614,100,28),('1129',864,18,42,20),('0',1025,18,15,20),('2',1165,18,15,20))
    s.words+=screen(('免费' if free else '1',452,650,45,23)).words
    if not free:s.words+=screen(('下次免费43:42:26',402,678,140,22)).words
    return s


def test_default_disabled_and_invalid_rejected():
    assert not free_summon_enabled({}) and not normalize_settings({})['free_summon_enabled']
    assert normalize_settings({'free_summon_enabled':True})['free_summon_enabled']
    for value in ('true',1,None,[]):
        with pytest.raises(ValueError):normalize_settings({'free_summon_enabled':value})


def test_disabled_tool_has_no_navigation_or_extra_reads(tmp_path):
    d=daily(tmp_path);world=captured('v092-main-map594')
    d.find_overview_entry=lambda *_:pytest.fail('Disabled must do no I/O')
    assert d.maybe_free_summon(world) is world
    assert 'free_summons' not in d.report


def test_actual_overview_timer_and_available_count():
    s=captured('overview-middle-current');title=s.find('^免费造唤$',(350,80,180,490))
    assert overview_summon_state(s,title)=={'available':0,'cooldown':57320}
    s=captured('v083-overview-cocoon');title=s.find('^免费造唤$',(350,80,180,490))
    assert overview_summon_state(s,title)=={'available':1,'cooldown':None}
    s.words=[w for w in s.words if w.text!='1']
    assert overview_summon_state(s,title) is None


def test_cooldown_supports_more_than_twentyfour_hours():
    assert cooldown_seconds('下次免费43:42:26')==157346
    assert cooldown_seconds('00:00:00')==0
    assert cooldown_seconds('01:65:02') is None
    assert cooldown_seconds('下次免费') is None


def test_only_explicit_free_single_draw_allowed():
    free=summon();assert free_summon_button(free) and summon_balance(free)==[1129,0,2]
    assert free_summon_button(summon(False)) is None
    paid=summon(False);paid.words[-1].text='下次免费00:00:00'
    assert free_summon_button(paid) is None
    free.words+=screen(('1',510,648,20,22)).words
    assert free_summon_button(free) is None
    assert free_summon_button(screen(('免费',450,650,45,23))) is None


def test_actual_cooldown_page_never_draws_even_with_tickets():
    s=captured('v0912-summon-cooldown',True)
    assert is_summon_page(s)
    assert free_summon_button(s) is None
    assert cooldown_seconds(s.text)==157346


def setup_check(d):
    d.b.settings['free_summon_enabled']=True
    d.checkpoint=lambda:None;d.b.sleep=lambda *_:None
    d.summon_page_ready=lambda s:s
    d.home=lambda:captured('v092-main-map594')
    overview=captured('v083-overview-cocoon')
    title=overview.find('^免费造唤$',(350,80,180,490))
    d.find_overview_entry=lambda *_:(overview,'free_summon',title)
    calls=[];d.b.click_at=lambda s,pt,a,reason:calls.append(reason)
    return calls


def test_timer_schedules_next_check_without_entering_summon(tmp_path):
    d=daily(tmp_path);calls=setup_check(d)
    overview=captured('overview-middle-current');title=overview.find('^免费造唤$',(350,80,180,490))
    d.find_overview_entry=lambda *_:(overview,'free_summon',title)
    world=d.home();d.maybe_free_summon(world)
    assert not calls and d.report['free_summons'][0]['status']=='cooldown'
    d.find_overview_entry=lambda *_:pytest.fail('Must wait for countdown')
    d.maybe_free_summon(world)
    assert len(d.report['free_summons'])==1


def test_overview_free_but_actual_paid_is_skipped(tmp_path):
    d=daily(tmp_path);calls=setup_check(d)
    d.summon_wait_page=lambda:summon(False)
    d.maybe_free_summon(d.home())
    assert calls==['前往当前有免费次数的造唤台']
    assert d.report['free_summons'][0]['status']=='blocked'


def test_button_changes_before_click_never_draws(tmp_path):
    d=daily(tmp_path);calls=setup_check(d)
    d.summon_wait_page=lambda:summon();d.observe=lambda:summon(False)
    d.maybe_free_summon(d.home())
    assert len(calls)==1


def test_single_draw_verified_by_new_cooldown_and_unchanged_balances(tmp_path):
    d=daily(tmp_path);calls=setup_check(d)
    d.summon_wait_page=lambda:summon();d.observe=lambda:summon()
    d.finish_free_summon=lambda row:summon(False)
    d.maybe_free_summon(d.home())
    assert calls==['前往当前有免费次数的造唤台','免费造唤一次']
    row=d.report['free_summons'][0]
    assert row['status']=='done' and row['summons']==1 and row['resources_before']==row['resources_after']
    assert d._summon_check_after>time.monotonic()+150000


def test_unconfirmed_draw_stops_without_repeating_or_reporting_zero_spend(tmp_path):
    d=daily(tmp_path);calls=setup_check(d)
    d.summon_wait_page=lambda:summon();d.observe=lambda:summon()
    after=summon(False);after.words[4].text='1128'
    d.finish_free_summon=lambda row:after
    with pytest.raises(SafetyStop,match='资源'):d.maybe_free_summon(d.home())
    assert len(calls)==2 and d.report['free_summons'][0]['status']=='unconfirmed'
    assert d.report['free_summons'][0]['summons']==0
