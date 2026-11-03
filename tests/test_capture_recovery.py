"""A dropped ADB screenshot pipe must not replay a game input."""
from types import SimpleNamespace
import numpy as np
import pytest
from chao2.backend import Backend
from chao2.policy import SafetyStop,UserStopped

def reader(results,error='error: closed'):
    b=Backend({},log=lambda _:None);calls=[];sequence=iter(results)
    def capture():calls.append('read');return SimpleNamespace(succeeded=next(sequence))
    b.controller=SimpleNamespace(last_error=error,post_screencap=capture,cached_image=np.zeros((720,1280,3),np.uint8))
    b.tasker=SimpleNamespace(post_recognition=lambda *a:SimpleNamespace(get=lambda:None))
    b.wait=lambda job,*a:job;b.sleep=lambda seconds:None
    return b,calls

def test_transient_capture_failure_retries_only_a_read():
    b,calls=reader([False,True])
    assert b.observe().image.shape==(720,1280,3)
    assert calls==['read','read']

def test_persistent_capture_failure_stops_after_three_reads():
    b,calls=reader([False,False,False])
    with pytest.raises(SafetyStop,match='closed'):b.observe()
    assert len(calls)==3

def test_changed_game_screen_is_not_treated_as_a_transient_pipe():
    b,calls=reader([False],'超二屏幕已关闭或切换，停止输入')
    with pytest.raises(SafetyStop,match='屏幕已关闭'):b.observe()
    assert calls==['read']

def test_stop_interrupts_capture_retry():
    b,calls=reader([False,True])
    def stop(_):raise UserStopped('stop')
    b.sleep=stop
    with pytest.raises(UserStopped):b.observe()
    assert calls==['read']
