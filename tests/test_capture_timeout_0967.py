"""A slow MuMu screenshot must not abandon an otherwise recognizable result."""
import io
import subprocess
import threading
from types import SimpleNamespace
import pytest
from PIL import Image
from chao2.backend import Backend,MuMuController,PACKAGE,CAPTURE_BUDGET_SECONDS
from chao2.policy import SafetyStop,UserStopped,FightLost
from chao2.workflows import is_failure
from test_capture_recovery import reader
from test_configuration import daily,screen


def png():
    out=io.BytesIO();Image.new('RGB',(1280,720)).save(out,format='PNG');return out.getvalue()


def controller():
    c=MuMuController('adb','same-device',threading.Event());c.logical=2;c.physical='1002'
    return c


def test_verify_and_png_share_one_deadline_and_input_keeps_normal_timeout(monkeypatch):
    c=controller();clock=[0];calls=[];image=png()
    monkeypatch.setattr('chao2.backend.time.monotonic',lambda:clock[0])
    def run(args,**kw):
        calls.append((args,kw['timeout']))
        if 'dumpsys' in args:
            clock[0]+=6
            data=f'Display: mDisplayId=2\n mFocusedApp=App u0 {PACKAGE}/Activity'.encode()
        else:data=image if 'screencap' in args else b''
        return SimpleNamespace(returncode=0,stdout=data,stderr=b'')
    monkeypatch.setattr('chao2.backend.subprocess.run',run)
    assert c.screencap().shape==(720,1280,3)
    assert [t for _,t in calls]==[CAPTURE_BUDGET_SECONDS,CAPTURE_BUDGET_SECONDS-6]
    assert c._capture_deadline is None and not c.capture_timed_out
    assert c.click(20,20)
    assert calls[-1][1]==12 and calls[-1][0][-3:]==['tap','20','20']


@pytest.mark.parametrize('kind',['verify','png'])
def test_adb_timeout_is_a_read_failure_with_deadline_cleared(monkeypatch,kind):
    c=controller();calls=[]
    def run(args,**kw):
        calls.append(args)
        if kind=='verify' or 'screencap' in args:raise subprocess.TimeoutExpired(args,kw['timeout'])
        return SimpleNamespace(returncode=0,stdout=f'Display: mDisplayId=2\n mFocusedApp={PACKAGE}/Activity'.encode(),stderr=b'')
    monkeypatch.setattr('chao2.backend.subprocess.run',run)
    assert c.screencap().size==0 and c.capture_timed_out
    assert c.last_error=='MuMu取图超时' and c._capture_deadline is None
    assert not any('input' in args for args in calls)


def test_spent_verification_budget_does_not_start_a_new_png_command(monkeypatch):
    c=controller();clock=[0];calls=[]
    monkeypatch.setattr('chao2.backend.time.monotonic',lambda:clock[0])
    def run(args,**kw):
        calls.append(args);clock[0]=CAPTURE_BUDGET_SECONDS+1
        return SimpleNamespace(returncode=0,stdout=f'Display: mDisplayId=2\n mFocusedApp={PACKAGE}/Activity'.encode(),stderr=b'')
    monkeypatch.setattr('chao2.backend.subprocess.run',run)
    assert c.screencap().size==0 and c.capture_timed_out
    assert len(calls)==1 and c._capture_deadline is None


def test_timeout_retries_fresh_screenshots_before_reading_ocr():
    b,calls=reader([False,False,True],error='MuMu取图超时')
    b.controller.capture_timed_out=True
    seen=[];b.tasker.post_recognition=lambda *a:seen.append(1) or SimpleNamespace(get=lambda:None)
    assert b.observe().image.shape==(720,1280,3)
    assert calls==['read']*3 and seen==[1]


def test_repeated_timeouts_stop_after_three_reads_without_ocr_or_input():
    b,calls=reader([False]*3,error='MuMu取图超时');b.controller.capture_timed_out=True
    b.tasker.post_recognition=lambda *_:pytest.fail('Do not recognize a failed screenshot')
    with pytest.raises(SafetyStop,match='MuMu取图超时'):b.observe()
    assert len(calls)==3


def test_stop_after_failed_capture_prevents_retry():
    b,calls=reader([False,True],error='MuMu取图超时');b.controller.capture_timed_out=True
    original=b.controller.post_screencap
    def capture():
        result=original();b.stop.set();return result
    b.controller.post_screencap=capture
    with pytest.raises(UserStopped):b.observe()
    assert calls==['read']


def test_unsettled_native_wait_is_not_blindly_retried():
    b,calls=reader([True])
    def wait(*_):raise SafetyStop('操作超时，已中止')
    b.wait=wait
    with pytest.raises(SafetyStop,match='操作超时'):b.observe()
    assert calls==['read']


def test_cocoon_loss_without_readable_decorative_title_settles_after_retry(tmp_path):
    b,calls=reader([False,True],error='MuMu取图超时');b.controller.capture_timed_out=True
    result=screen(('通过下列方式提高战力',810,250,248,28),('重新挑战',600,590,110,30),
                  ('元核升级',750,435,90,24),('阵容调整',1025,435,90,24),('退出',1140,582,60,30),
                  ('3/16',1200,15,65,26))
    words=[SimpleNamespace(text=w.text,box=w.box,score=w.score) for w in result.words]
    b.tasker.post_recognition=lambda *_:SimpleNamespace(get=lambda:SimpleNamespace(nodes=[
        SimpleNamespace(recognition=SimpleNamespace(all_results=words))]))
    d=daily(tmp_path);d.b=b;d.active_task='cocoon';d.observe=b.observe
    d.resource_balance('cocoon','永生尖刺',3)
    with pytest.raises(FightLost) as error:d.battle('永生尖刺')
    assert is_failure(error.value.screen) and calls==['read','read']
    assert d.task_counts=={'cocoon':1} and d.report['battles'][0]['result']=='failed'
    assert d.report['resource_usage']['cocoon']['永生尖刺']['spent']==0
