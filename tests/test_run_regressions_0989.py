"""Replay complete failure frames from the run, not just isolated title crops."""
from types import SimpleNamespace
import time
import pytest
from chao2.backend import Screen
from chao2.activities import enemy_formation,BudgetReached
from chao2.dungeon_labels import recover_timed_encounter_heading
from chao2.forest import forest_points
from chao2.rift import rift_node
from chao2.policy import TaskBlocked,ResourceReadError
from test_configuration import daily,screen,captured
from test_rift_main_0959 import offline_backend
from test_forest_points_0977 import forest_map
from chao2.configuration import selected_rows


@pytest.mark.parametrize('task,fixture',[('copies','copy'),('hunt','hunt')])
def test_full_open_detail_recovers_before_real_await_detail(tmp_path,monkeypatch,offline_backend,task,fixture):
    s=captured('v0989-'+fixture,True)
    assert not enemy_formation(s)
    d=daily(tmp_path);d.b=offline_backend;d.active_task=task
    monkeypatch.setattr(d.b,'observe',lambda *a:Screen(s.image,list(s.words),time.monotonic()))
    monkeypatch.setattr(d.b,'click_at',lambda *a,**kw:pytest.fail('The detail is already open'))
    q=d.await_detail(timeout=3)
    assert enemy_formation(q) and q.find('^前往挑战$') and not enemy_formation(s)


@pytest.mark.parametrize('missing',['name','timer','reward','challenge'])
def test_timed_detail_recovery_requires_a_complete_encounter(tmp_path,missing):
    s=screen(('name',140,135,160,25),('O17:52:11',565,136,121,24),('可获得奖励',42,565,90,18),
             ('排阵',822,614,63,35),('前往挑战',1036,607,109,28))
    patterns={'name':'name','timer':'O17:52:11','reward':'可获得奖励','challenge':'前往挑战'}
    s.words=[w for w in s.words if w.text!=patterns[missing]]
    d=daily(tmp_path);d.b.tasker=object()
    d.b.confirm_label=lambda *a,**kw:pytest.fail('Incomplete page cannot recover a heading')
    assert recover_timed_encounter_heading(d.b,s) is s


def test_actual_zero_points_need_both_wide_and_independent_digit_read(offline_backend):
    s=captured('v0989-forest',True)
    assert forest_points(offline_backend,s)==0


@pytest.mark.parametrize('narrow',['1/17','0/16','','17','0/17.'])
def test_narrow_forest_fallback_cannot_override_the_wide_ratio(tmp_path,narrow):
    d=daily(tmp_path);d.b.tasker=object();answers=iter(['','0/17',''])
    d.b.read_text_region=lambda *a,**kw:next(answers)
    d.b.read_text_crop=lambda *a:narrow
    with pytest.raises(ResourceReadError):forest_points(d.b,forest_map())


def test_conflicting_wide_forest_reads_do_not_trigger_fallback(tmp_path):
    d=daily(tmp_path);d.b.tasker=object();answers=iter(['0/17','1/17'])
    d.b.read_text_region=lambda *a,**kw:next(answers)
    d.b.read_text_crop=lambda *a:pytest.fail('Conflicting wide values must stop')
    with pytest.raises(ResourceReadError):forest_points(d.b,forest_map())


def test_purple_road_36_uses_shape_and_two_exact_digit_reads(offline_backend):
    s=captured('v0989-rift36',True)
    assert rift_node(offline_backend,s,36)==('next',(534,450))
    assert rift_node(offline_backend,s,35)[0]=='open'
    assert rift_node(offline_backend,s,37)[0]=='locked'


def secret_map(clipped):
    s=screen(('浮空巨塔',124,14,120,30),('塔中秘庭10' if clipped else '塔中秘庭100',1142 if clipped else 650,540,138,30),
             ('塔中秘庭101',900,540,140,30))
    x=(1142 if clipped else 650)+69;y=555
    s.image[y-155:y-100,x-35:x+36]=[235,210,160]
    s.image[400:455,935:1006]=[200,180,170]
    return s


def test_secret_selection_centers_truncated10_and_verifies_actual100(tmp_path):
    d=daily(tmp_path);d.active_task='tower';edge=secret_map(True);center=secret_map(False)
    state={'page':edge};swipes=[];opened=[];verified=[]
    detail=screen(('塔中秘庭100',233,105,155,28),('首通奖励',173,557,75,22),
                  ('敌方阵容123',782,104,250,27),('排阵',702,611,62,36),('挑战',946,611,62,36))
    def swipe(*args):swipes.append(args);state['page']=center;return SimpleNamespace(succeeded=True)
    d.b.controller=SimpleNamespace(post_swipe=swipe);d.b.wait=lambda job:job;d.b.sleep=lambda _:None
    d.open_tower=lambda kind:edge;d.tower_secret_list=lambda *a:state['page']
    d.observe=lambda:state['page'];d.await_detail=lambda:detail
    d.b.click_at=lambda s,p,a,r:opened.append(r)
    d.b.read_resource_ratio=lambda *a:(5,20)
    def play(task,opener,resource,verify,**kw):
        q=opener();verify(q);verified.append(q.find('^塔中秘庭100$').text);return False
    d.play_encounter=play
    kind=selected_rows(d.options['tower'],'towers')[0]
    assert d.tower_secrets(kind,set())==0
    assert len(swipes)==1 and verified==['塔中秘庭100']
    assert opened==['打开已稳定的塔中秘庭100'] and d.battles==0


def test_secret_recentering_is_bounded_and_never_clicks_old_truncated_name(tmp_path):
    d=daily(tmp_path);s=secret_map(True);swipes=[]
    d.b.controller=SimpleNamespace(post_swipe=lambda *a:swipes.append(a) or SimpleNamespace(succeeded=True))
    d.b.wait=lambda job:job;d.b.sleep=lambda _:None;d.tower_secret_list=lambda:s
    d.b.click_at=lambda *a:pytest.fail('Do not use the clipped target')
    with pytest.raises(TaskBlocked,match='居中3次'):d.center_secret_nodes(s)
    assert len(swipes)==3


def test_secret_detail100_still_rejects_an_uncorrected_list_target10(tmp_path):
    d=daily(tmp_path);s=captured('v0988-secret-free',True)
    with pytest.raises(TaskBlocked):d.verify_tower_secret(s,'塔中秘庭10')
