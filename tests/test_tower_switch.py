"""Free tower navigation must follow the real landing page after each back."""
import re
from types import SimpleNamespace

import pytest

from chao2.policy import TaskBlocked,UserStopped
from test_configuration import captured,daily,screen


KINDS=[{'id':'normal','label':'无限制'},{'id':'dragon','label':'祖龙族'}]


class TowerNavigationGame:
    def __init__(self,tmp_path,monkeypatch,*,start='secrets',secret_exit='floors',floor_exit='territory',drops=0):
        self.d=daily(tmp_path);self.d.active_task='tower';self.d._tower_kind='normal'
        self.page=start;self.secret_exit=secret_exit;self.floor_exit=floor_exit;self.drops=drops
        self.inputs=[];self.frames=[];self.fallbacks=0
        self.pages={'floors':captured('tower-map'),'secrets':captured('tower-secrets-seen',True),
            'detail':captured('tower-puppet-detail'),
            'territory':captured('v0941-switch-territory',True),
            'world':captured('world-missed-label',True),'blank':screen(),
            'selector':screen(('选择挑战的塔',450,80,350,45),
                              ('无限制',280,300,80,30),('祖龙族',480,300,80,30))}
        d=self.d;d.observe=self.observe;d.b.sleep=lambda _:None
        d.b.click_at=self.click_at;d.b.click_text=self.click_text;d.tower_selection=self.fallback
        # Advance only the bounded navigation wait's clock; real screen guards
        # still use actual capture age and no emulator connection is available.
        ticks=iter(i*.25 for i in range(10000))
        monkeypatch.setattr('chao2.navigation_retry.time',SimpleNamespace(monotonic=lambda:next(ticks)))

    def observe(self,*args):return self.frames.pop(0) if self.frames else self.pages[self.page]

    def click_at(self,s,point,anchors,reason,**kwargs):
        assert s.has(*anchors)
        if point==(45,28):
            page=self.d.tower_navigation_state(s)
            assert page in ('detail','floors','secrets'),'Never back from a changed/unknown page'
            self.inputs.append(('back',page))
            if self.drops:self.drops-=1;return
            self.page={'detail':'floors','secrets':self.secret_exit,'floors':self.floor_exit}[page]
        else:
            assert point==(724,130) and self.d.tower_territory(s)
            self.inputs.append(('enter','territory'));self.page='selector'

    def click_text(self,s,pattern,**kwargs):
        assert self.d.tower_navigation_state(s)=='selector' and s.find(pattern)
        name=next(k['label'] for k in KINDS if re.search(pattern,k['label']))
        self.inputs.append(('select',name));self.page='floors'

    def fallback(self):
        assert self.page=='world'
        self.fallbacks+=1;self.page='territory';return self.pages['territory']


@pytest.mark.parametrize('name,state',[('tower-map','floors'),('tower-secrets-seen','secrets'),
    ('tower-puppet-detail','detail'),('v0941-switch-territory','territory')])
def test_actual_captured_tower_navigation_pages(tmp_path,name,state):
    d=daily(tmp_path)
    assert d.tower_navigation_state(captured(name))==state


def test_real_failure_landing_reenters_selector_and_selects_requested_race(tmp_path,monkeypatch):
    game=TowerNavigationGame(tmp_path,monkeypatch)
    assert game.d.open_tower(KINDS[1]) is game.pages['floors']
    assert game.inputs==[('back','secrets'),('back','floors'),('enter','territory'),('select','祖龙族')]
    assert game.d._tower_kind=='dragon'
    assert [r['destination'] for r in game.d.report['tower_navigation']]==['floors','territory']
    assert not game.d.report.get('challenge_starts') and game.d.battles==0


def test_secret_back_landing_directly_in_territory_sends_no_extra_back(tmp_path,monkeypatch):
    game=TowerNavigationGame(tmp_path,monkeypatch,secret_exit='territory')
    game.d.open_tower(KINDS[1])
    assert game.inputs==[('back','secrets'),('enter','territory'),('select','祖龙族')]


def test_back_to_selector_does_not_reenter_territory(tmp_path,monkeypatch):
    game=TowerNavigationGame(tmp_path,monkeypatch,start='floors',floor_exit='selector')
    game.d.open_tower(KINDS[1])
    assert game.inputs==[('back','floors'),('select','祖龙族')]


def test_back_landing_on_world_uses_known_navigation_fallback(tmp_path,monkeypatch):
    game=TowerNavigationGame(tmp_path,monkeypatch,start='floors',floor_exit='world')
    game.d.open_tower(KINDS[1])
    assert game.fallbacks==1 and game.inputs==[('back','floors'),('enter','territory'),('select','祖龙族')]


def test_already_in_requested_tower_needs_no_navigation(tmp_path,monkeypatch):
    game=TowerNavigationGame(tmp_path,monkeypatch,start='floors')
    game.d.open_tower(KINDS[0]);assert game.inputs==[]


def test_lingering_source_and_blank_transition_frames_do_not_trigger_more_back(tmp_path,monkeypatch):
    game=TowerNavigationGame(tmp_path,monkeypatch,start='floors')
    p=game.pages
    game.frames=[p['floors']]*3+[p['blank']]*4+[p['territory'],p['blank'],p['territory'],p['territory']]
    assert game.d.tower_back_page(p['floors']) is p['territory']
    assert game.inputs==[('back','floors')]
    assert game.d.report['tower_navigation'][0]['destination']=='territory'


def test_swallowed_back_retries_only_on_same_confirmed_source(tmp_path,monkeypatch):
    game=TowerNavigationGame(tmp_path,monkeypatch,start='floors',drops=1)
    game.d.open_tower(KINDS[1])
    assert game.inputs==[('back','floors')]*2+[('enter','territory'),('select','祖龙族')]
    assert game.d.report['tower_navigation'][0]['clicks']==2


def test_permanently_ignored_back_has_three_retries_and_no_other_input(tmp_path,monkeypatch):
    game=TowerNavigationGame(tmp_path,monkeypatch,start='floors',drops=100)
    with pytest.raises(TaskBlocked,match='已重试3次'):game.d.open_tower(KINDS[1])
    assert game.inputs==[('back','floors')]*4 and game.d.battles==0
    assert game.d.report['tower_navigation'][0]['status']=='blocked'


def test_unknown_successor_is_not_clicked_or_claimed_as_arrived(tmp_path,monkeypatch):
    game=TowerNavigationGame(tmp_path,monkeypatch,start='floors',floor_exit='blank')
    with pytest.raises(TaskBlocked):game.d.open_tower(KINDS[1])
    assert game.inputs==[('back','floors')]
    assert game.d.report['tower_navigation'][0]['status']=='blocked'


def test_requesting_current_map_recovers_same_tower_after_unexpected_exit(tmp_path,monkeypatch):
    game=TowerNavigationGame(tmp_path,monkeypatch,secret_exit='territory')
    assert game.d.tower_map() is game.pages['floors']
    assert game.inputs==[('back','secrets'),('enter','territory'),('select','无限制')]
    assert game.d._tower_kind=='normal'


def test_map_recovery_does_not_guess_when_previous_tower_is_unknown(tmp_path,monkeypatch):
    game=TowerNavigationGame(tmp_path,monkeypatch,secret_exit='territory');game.d._tower_kind=None
    with pytest.raises(TaskBlocked,match='原塔类型未确认'):game.d.tower_map()
    assert game.inputs==[('back','secrets')]


def test_user_stop_interrupts_return_without_a_second_click(tmp_path,monkeypatch):
    game=TowerNavigationGame(tmp_path,monkeypatch,start='floors')
    click=game.d.b.click_at
    def stop_after_click(*args,**kw):click(*args,**kw);game.d.b.stop.set()
    game.d.b.click_at=stop_after_click
    with pytest.raises(UserStopped):game.d.open_tower(KINDS[1])
    assert game.inputs==[('back','floors')]
    assert game.d.report['tower_navigation'][0]['status']=='stopped'
