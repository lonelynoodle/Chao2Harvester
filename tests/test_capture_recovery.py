"""A dropped ADB screenshot pipe must not replay a game input."""
from types import SimpleNamespace
import numpy as np
import pytest
from chao2.backend import Backend
from chao2.policy import SafetyStop,TaskBlocked,UserStopped
from test_configuration import screen

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


def gold_details():
    return screen(('金币',490,103,62,32),('已拥有123456',494,145,125,22),
                  ('主要获得途径',410,338,128,24),('购买',401,389,57,32))


def test_gold_popup_closes_during_preclick_read_and_reuses_revealed_source():
    b=Backend({},log=lambda _:None,recover_gold_details=True)
    source=screen(('背包',100,55,64,30))
    popup=gold_details()
    frames=iter([popup,source])
    b._observe_once=lambda _:next(frames)
    clicks=[]
    b.click_at=lambda s,point,anchors,reason,**_:clicks.append((s,point))
    b.click_text(source,'^背包$')
    assert clicks==[(popup,(640,650)),(source,(132,70))]


@pytest.mark.parametrize('read_only',[False,True])
def test_gold_cleanup_does_not_click_resource_confirmation_or_read_only(read_only):
    popup=gold_details()
    if not read_only:popup.words+=screen(('确定',775,470,90,33)).words
    b=Backend({},log=lambda _:None,recover_gold_details=not read_only)
    b._observe_once=lambda _:popup
    b.click_at=lambda *a,**k:pytest.fail('Do not dismiss this screen')
    assert b.observe() is popup


def test_same_gold_popup_gets_at_most_three_blank_taps():
    popup=gold_details()
    b=Backend({},log=lambda _:None,recover_gold_details=True)
    b._observe_once=lambda _:popup
    points=[]
    b.click_at=lambda s,point,*a,**k:points.append(point)
    with pytest.raises(TaskBlocked,match='连续3次'):
        b.observe()
    assert points==[(640,650)]*3
