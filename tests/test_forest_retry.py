"""Forest navigation retries must reconcile the screen before replaying input."""
from types import SimpleNamespace
import pytest
import chao2.forest as forest
from chao2.backend import MuMuController
from chao2.policy import SafetyStop,TaskBlocked,UserStopped
from test_configuration import captured,daily,screen


def pan_runner(tmp_path,monkeypatch,replies,shifts):
    d=daily(tmp_path);s=captured('v085-forest-east2',True)
    replies=iter(replies);shifts=iter(shifts);inputs=[];reads=[];audit=[]
    d.forest_offset=[10.,20.];d.b.sleep=lambda *_:None
    d.b.wait=lambda job:job;d.b.audit=audit.append
    def swipe(*args):
        inputs.append(args)
        return SimpleNamespace(succeeded=next(replies))
    d.b.controller=SimpleNamespace(post_swipe=swipe,last_error='error: closed')
    def read():reads.append(True);return s
    d.forest_wait_map=read
    monkeypatch.setattr(forest,'forest_shift',lambda *args:next(shifts))
    return d,s,inputs,reads,audit


def test_three_retries_then_success_continue_from_same_scan(tmp_path,monkeypatch):
    d,s,inputs,reads,audit=pan_runner(tmp_path,monkeypatch,
        [False,False,False,True],[(0,0)]*6+[(-580,0)])
    q,moved=d.forest_pan(s,-600,0)
    assert moved and len(inputs)==4 and len(reads)==7
    assert d.forest_offset==[590,20]
    assert [r['attempt'] for r in d.report['forest_pan_errors']]==[1,2,3]
    assert d.report['forest_pan_recoveries'][0]['retries']==3
    assert [e['attempt'] for e in audit if e['status']=='requested']==[1,2,3,4]
    assert '（3/3）' in '\n'.join(e['message'] for e in d.report['events'])


def test_four_failed_attempts_record_error_and_stop_without_advancing_offset(tmp_path,monkeypatch):
    d,s,inputs,reads,audit=pan_runner(tmp_path,monkeypatch,[False]*4,[(0,0)]*8)
    with pytest.raises(TaskBlocked,match='已重试3次：error: closed'):d.forest_pan(s,-600,0)
    assert len(inputs)==4 and len(reads)==8 and d.forest_offset==[10,20]
    assert len(d.report['forest_pan_errors'])==4
    assert 'forest_pan_recoveries' not in d.report
    assert (tmp_path/'forest-pan-1-attempt-4.png').exists()


@pytest.mark.parametrize('shifts',[[(-585,0)],[(0,0),(-585,0)]])
def test_failed_reply_after_actual_movement_never_replays_swipe(tmp_path,monkeypatch,shifts):
    d,s,inputs,reads,audit=pan_runner(tmp_path,monkeypatch,[False],shifts)
    assert d.forest_pan(s,-600,0)[1]
    assert len(inputs)==1 and d.forest_offset==[595,20]
    assert not d.report['forest_pan_recoveries'][0]['reply_succeeded']


def test_unreadable_shift_retries_reads_three_times_not_swipes(tmp_path,monkeypatch):
    d,s,inputs,reads,audit=pan_runner(tmp_path,monkeypatch,[True],[None]*4)
    with pytest.raises(TaskBlocked,match='已重新识别3次'):d.forest_pan(s,-600,0)
    assert len(inputs)==1 and len(reads)==4 and d.forest_offset==[10,20]
    assert (tmp_path/'forest-pan-after.png').exists()


def test_late_registration_continues_without_extra_input(tmp_path,monkeypatch):
    d,s,inputs,reads,audit=pan_runner(tmp_path,monkeypatch,[True],[None,None,None,(-590,0)])
    assert d.forest_pan(s,-600,0)[1]
    assert len(inputs)==1 and len(reads)==4 and d.forest_offset==[600,20]


def test_small_drift_from_failed_attempt_is_counted_only_once(tmp_path,monkeypatch):
    d,s,inputs,reads,audit=pan_runner(tmp_path,monkeypatch,[False,True],[(-2,0),(-3,0),(-595,0)])
    assert d.forest_pan(s,-600,0)[1]
    assert d.forest_offset==[605,20] and len(inputs)==2


def test_successful_zero_motion_is_boundary_not_three_redundant_retries(tmp_path,monkeypatch):
    d,s,inputs,reads,audit=pan_runner(tmp_path,monkeypatch,[True],[(0,0)])
    assert not d.forest_pan(s,-600,0)[1]
    assert len(inputs)==1 and len(reads)==1


@pytest.mark.parametrize('shift',[(0,50),(70,0),(-1200,0)])
def test_unexpected_displacement_does_not_replay_navigation(tmp_path,monkeypatch,shift):
    d,s,inputs,reads,audit=pan_runner(tmp_path,monkeypatch,[False],[shift]*4)
    with pytest.raises(TaskBlocked,match='非预期位移'):d.forest_pan(s,-600,0)
    assert len(inputs)==1 and len(reads)==4 and d.forest_offset==[10,20]


def test_page_changed_after_failure_does_not_swipe_a_dialog(tmp_path,monkeypatch):
    d,s,inputs,reads,audit=pan_runner(tmp_path,monkeypatch,[False],[])
    del d.forest_wait_map
    d.observe=lambda:captured('v085-forest-beast',True)
    with pytest.raises(TaskBlocked,match='森林未返回地图'):d.forest_pan(s,-600,0)
    assert len(inputs)==1


def test_paid_dialog_and_user_stop_are_not_retried(tmp_path,monkeypatch):
    for error in (SafetyStop('发现购买弹窗'),UserStopped('用户停止')):
        d,s,inputs,reads,audit=pan_runner(tmp_path,monkeypatch,[False],[])
        def stopped():raise error
        d.forest_wait_map=stopped
        with pytest.raises(type(error),match=str(error)):d.forest_pan(s,-600,0)
        assert len(inputs)==1


def test_changed_point_balance_prevents_replay(tmp_path,monkeypatch):
    d,s,inputs,reads,audit=pan_runner(tmp_path,monkeypatch,[False],[(0,0),(0,0)])
    balances=iter([1,2,1]);monkeypatch.setattr(forest,'forest_points',lambda *args:next(balances))
    with pytest.raises(TaskBlocked,match='探索点发生消耗'):d.forest_pan(s,-600,0)
    assert len(inputs)==1


def test_timed_node_after_failed_gesture_finishes_without_replay(tmp_path,monkeypatch):
    d,s,inputs,reads,audit=pan_runner(tmp_path,monkeypatch,[False],[(0,0),(0,0)])
    d.forest_wait_map=lambda:captured('v085-forest-timed',True)
    with pytest.raises(TaskBlocked,match='出现计时探索'):d.forest_pan(s,-600,0)
    assert len(inputs)==1 and d.report['forest_waiting']['remaining_seconds']==1799


def test_successful_controller_swipe_clears_previous_error():
    commands=[]
    c=SimpleNamespace(last_error='old error',logical=2,verify=lambda:None,cmd=lambda *a:commands.append(a))
    assert MuMuController.swipe(c,940,350,340,350,1000)
    assert c.last_error=='' and commands==[('shell','input','-d',2,'swipe',940,350,340,350,1000)]
