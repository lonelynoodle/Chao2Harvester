import io
import threading
from PIL import Image
from chao2.backend import MuMuController,PACKAGE

def controller(focus):
    c=MuMuController('unused','same-emulator',threading.Event());c.logical=3;c.physical='1003'
    output=io.BytesIO();Image.new('RGB',(1280,720)).save(output,format='PNG');calls=[]
    def command(*args,**kwargs):
        calls.append(args)
        if args==('shell','dumpsys','window','displays'):return focus
        if args==('shell','dumpsys','display'):return "DisplayViewport{displayId=4, uniqueId='local:1004'}"
        if args[:2]==('exec-out','screencap'):return output.getvalue()
        if args[:2]==('shell','input'):return ''
        raise AssertionError(args)
    c.cmd=command;return c,calls

def test_recreated_display_requires_fresh_capture_before_new_input():
    c,calls=controller(f'Display: mDisplayId=3\n mCurrentFocus=null\nDisplay: mDisplayId=4\n mFocusedApp=App u0 {PACKAGE}/Activity')
    assert c.click(100,100) is False
    assert not any(a[:2]==('shell','input') for a in calls)
    assert c.screencap().shape==(720,1280,3)
    assert c.logical==4 and c.physical=='1004' and c.display_reconnected==(3,4)
    assert c.click(100,100) is True
    assert calls[-1]==('shell','input','-d',4,'tap',100,100)

def test_another_app_or_ambiguous_game_displays_do_not_rebind():
    for focus in ('Display: mDisplayId=4\n mFocusedApp=App u0 other.app/Activity',
                  f'Display: mDisplayId=4\n mFocusedApp=App u0 {PACKAGE}/Activity\nDisplay: mDisplayId=5\n mFocusedApp=App u0 {PACKAGE}/Activity'):
        c,calls=controller(focus)
        assert c.screencap().size==0 and c.logical==3
        assert not any(a[:2]==('shell','input') for a in calls)

def test_stopped_controller_never_rebinds_or_captures():
    c,calls=controller('');c.stop.set()
    assert c.screencap().size==0 and calls==[]
