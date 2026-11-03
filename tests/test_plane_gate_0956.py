"""The captured portal after a free ambush must not strand the original stage."""
import copy
import pytest
from chao2.backend import Word
from chao2.activities import main_identity,MainRetryUnavailable
from chao2.plane_gate import plane_gate_window,plane_gate_close
from chao2.policy import TaskBlocked,EncounterInterrupted,UserStopped
from chao2.workflows import is_world,world_overlay_present
from test_configuration import captured,daily,screen


def world():
    return screen(('事件',1100,620,60,30),('领地',1200,620,60,30),('223/179',500,15,80,30))


def test_captured_portal_is_an_overlay_and_x_is_read_from_pixels():
    s=captured('v0956-plane-gate',True)
    assert plane_gate_window(s) and world_overlay_present(s) and not is_world(s)
    assert plane_gate_close(s).center==(1038,78)
    s.words=[w for w in s.words if w.text!='x']
    assert plane_gate_close(s).center==(1038,78)
    s.words.extend(world().words)
    assert not is_world(s)  # Readable HUD behind the popup cannot authorize map clicks.


@pytest.mark.parametrize('missing',['歼误之门','解锁条件:世界总探索度到达125%','进入'])
def test_missing_own_anchors_cannot_authorize_portal_close(missing):
    s=captured('v0956-plane-gate',True);s.words=[w for w in s.words if w.text!=missing]
    assert plane_gate_window(s) is None and plane_gate_close(s) is None


@pytest.mark.parametrize('label',['取消','确定','购买','获得奖励','排阵','退出'])
def test_other_modal_or_challenge_controls_are_not_a_portal(label):
    s=captured('v0956-plane-gate',True);s.words.append(Word(label,[600,350,80,40],.99))
    assert plane_gate_window(s) is None


def test_portal_name_alone_or_unverified_close_never_authorizes_input(tmp_path):
    d=daily(tmp_path);s=captured('v0956-plane-gate')
    assert plane_gate_close(s) is None
    d.observe=lambda:s;d.b.click_at=lambda *a:pytest.fail('No X pixels')
    with pytest.raises(TaskBlocked,match='叉号'):d.close_plane_gate(s)
    s.words=[s.words[2]]
    assert plane_gate_window(s) is None


def test_home_closes_actual_gate_then_returns_to_world(tmp_path):
    d=daily(tmp_path);gate=captured('v0956-plane-gate',True);dest=world();frames=iter([gate,dest])
    d.observe=lambda:next(frames);clicks=[]
    d.b.click_at=lambda s,p,*a:clicks.append(p)
    assert d.home(gate) is dest
    assert clicks==[(1038,78)] and d.report['plane_gates'][0]['status']=='closed'
    assert d.battles==0 and d.task_counts=={}


def test_stale_portal_is_not_clicked_after_it_disappears(tmp_path):
    d=daily(tmp_path);gate=captured('v0956-plane-gate',True);dest=world();d.observe=lambda:dest
    d.b.click_at=lambda *a:pytest.fail('Window already gone')
    assert d.close_plane_gate(gate) is dest and d.report['plane_gates'][0]['clicks']==0


def test_temporary_missing_caption_is_not_mistaken_for_a_closed_portal(tmp_path):
    d=daily(tmp_path);gate=captured('v0956-plane-gate',True);dest=world()
    partial=copy.deepcopy(gate);partial.words=[w for w in partial.words if w.text!='进入']
    frames=iter([partial,gate,partial,dest]);d.observe=lambda:next(frames)
    clicks=[];d.b.click_at=lambda s,p,*a:clicks.append(p);d.b.sleep=lambda n:None
    assert d.close_plane_gate(gate) is dest and clicks==[(1038,78)]


def test_swallowed_close_is_retried_only_on_new_verified_portal_frames(tmp_path):
    d=daily(tmp_path);gate=captured('v0956-plane-gate',True);dest=world();clicks=[]
    d.observe=lambda:gate if len(clicks)<2 else dest;d.b.sleep=lambda n:None
    d.b.click_at=lambda s,p,*a:clicks.append(p)
    assert d.close_plane_gate(gate) is dest
    assert clicks==[(1038,78)]*2 and len(d.report['navigation_retries'])==1


def test_close_retry_is_bounded_and_obeys_stop(tmp_path):
    d=daily(tmp_path);gate=captured('v0956-plane-gate',True);clicks=[]
    d.observe=lambda:gate;d.b.sleep=lambda n:None;d.b.click_at=lambda s,p,*a:clicks.append(p)
    with pytest.raises(TaskBlocked,match='重试3次'):d.close_plane_gate(gate)
    assert len(clicks)==4
    clicks.clear();d.b.stop.set()
    with pytest.raises(UserStopped):d.close_plane_gate(gate)
    assert not clicks


def test_path_portal_closes_and_requests_same_target_relocation(tmp_path):
    d=daily(tmp_path);gate=captured('v0956-plane-gate',True);calls=[]
    d.close_plane_gate=lambda s:calls.append('close') or world()
    with pytest.raises(EncounterInterrupted,match='重新定位原目标'):d.resolve_path_event(gate)
    assert calls==['close']


def test_ambush_before_main_start_preserves_identity_without_counting_original_battle(tmp_path):
    d=daily(tmp_path);detail=captured('v0956-main-639');d.b.click_text=lambda *a:None
    d.observe=lambda:captured('v082-ambush')
    d.handle_ambush=lambda s:None
    with pytest.raises(EncounterInterrupted):d.start_challenge('main',detail,'主线体力5')
    assert d._main_interrupted_target=='639' and d.battles==0 and d.task_counts=={}
    assert d.report['challenge_starts'][0]['status']=='interrupted'


def test_interrupted_remote_stage_reopens_same_overview_target_before_local_markers(tmp_path):
    d=daily(tmp_path);target=captured('v0956-main-639')
    d._main_overview_target=d._main_interrupted_target='639'
    d.home=lambda:world();d.main_overview_detail=lambda:target
    d.find_main_candidate=lambda *a,**kw:pytest.fail('No unrelated local scan before direct relocation')
    assert d.last_main_detail('639') is target and d._main_interrupted_target is None


def test_direct_relocation_rejects_different_stage_and_never_challenges_it(tmp_path):
    d=daily(tmp_path);target=captured('v0956-main-639');other=copy.deepcopy(target)
    next(w for w in other.words if w.text=='639').text='640'
    d._main_overview_target=d._main_interrupted_target='639'
    d.home=lambda:world();frames=iter([other,target]);d.main_overview_detail=lambda:next(frames)
    closed=[];d.back_detail=lambda s:closed.append(main_identity(s))
    d.find_main_candidate=lambda *a,**kw:pytest.fail('Matched original stage needs no scan')
    d.start_challenge=lambda *a:pytest.fail('Relocation must not start any fight')
    assert d.last_main_detail('639') is target and closed==['640']


def test_interrupted_overview_can_find_original_after_more_than_four_suggestions(tmp_path):
    d=daily(tmp_path);target=captured('v0956-main-639')
    d._main_overview_target=d._main_interrupted_target='639';d.home=lambda:world()
    frames=[]
    for identity in ('641','665','693','722','730'):
        q=copy.deepcopy(target);next(w for w in q.words if w.text=='639').text=identity;frames.append(q)
    sequence=iter([*frames,target]);d.main_overview_detail=lambda:next(sequence)
    closed=[];d.back_detail=lambda q:closed.append(main_identity(q))
    d.find_main_candidate=lambda *a,**kw:pytest.fail('Original stage was found directly')
    assert d.last_main_detail('639') is target
    assert closed==['641','665','693','722','730']


def test_direct_lookup_stops_at_repeated_suggestion_without_challenging(tmp_path):
    d=daily(tmp_path);target=captured('v0956-main-639');other=copy.deepcopy(target)
    next(w for w in other.words if w.text=='639').text='641'
    d.main_overview_detail=lambda:other;closed=[];d.back_detail=lambda q:closed.append(main_identity(q))
    assert d.retry_main_overview_detail('639',max_lookups=20) is None
    assert closed==['641','641'] and d.report['main_retry_lookups'][0]['status']=='unavailable'


def test_real_maa_recognizes_portal_anchors_and_x():
    from test_maa_recognition import Offline
    from maa.resource import Resource
    from maa.tasker import Tasker
    from maa.pipeline import JOCR
    from chao2.backend import Screen
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle('resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    original=captured('v0956-plane-gate',True)
    result=t.post_recognition('OCR',JOCR(roi=[0,0,1280,720],threshold=.5),original.image).wait().get()
    words=[Word(w.text,w.box,w.score) for n in result.nodes if n.recognition for w in n.recognition.all_results]
    actual=Screen(original.image,words,original.when)
    assert plane_gate_window(actual) and plane_gate_close(actual).center==(1038,78)
