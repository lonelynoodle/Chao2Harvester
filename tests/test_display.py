from threading import Event
from types import SimpleNamespace

import pytest

from chao2 import backend
from chao2.backend import Backend, GAME_PACKAGES, MuMuController, PACKAGE, display_blocks
from chao2.policy import SessionUnavailable
from chao2.workflows import close_game_and_mumu

def test_separate_game_displays_do_not_share_focus():
    text=f'''Display: mDisplayId=0 rootTasks=1
    mFocusedApp=ActivityRecord{{u0 app.lawnchair/.Home}}
  Display: mDisplayId=3 rootTasks=1
    mCurrentFocus=Window{{u0 com.hypergryph.arknights/.Game}}
  Display: mDisplayId=4 rootTasks=1
    mFocusedApp=ActivityRecord{{u0 {PACKAGE}/.AppActivity}}'''
    blocks=dict(display_blocks(text))
    assert set(blocks)=={0,3,4}
    assert PACKAGE not in blocks[3]
    assert PACKAGE in blocks[4]


@pytest.mark.parametrize('version,expected_display', [(None, 3), ('1.88', 4)])
def test_selected_version_uses_its_display_when_both_versions_are_open(version, expected_display):
    package = GAME_PACKAGES[version or '1.86']
    controller = MuMuController('adb', 'same-device', Event(), **({'game_version': version} if version else {}))
    other_package = GAME_PACKAGES['1.88'] if package == PACKAGE else PACKAGE
    windows = f'''Display: mDisplayId=3 rootTasks=1
    mFocusedApp=ActivityRecord{{u0 {PACKAGE}/.AppActivity}}
  Display: mDisplayId=4 rootTasks=1
    mCurrentFocus=Window{{u0 {GAME_PACKAGES['1.88']}/.AppActivity}}'''
    viewports = "DisplayViewport{displayId=3, uniqueId='local:1003'} DisplayViewport{displayId=4, uniqueId='local:1004'}"

    def command(*args):
        return windows if args[-1] == 'displays' else viewports

    controller.cmd = command
    controller.discover()
    controller.verify()
    assert controller.get_custom_info() == {'package': package, 'display': expected_display, 'physical': str(expected_display + 1000)}

    windows = f'Display: mDisplayId={expected_display}\n mCurrentFocus=Window{{u0 {other_package}/.AppActivity}}'
    with pytest.raises(SessionUnavailable, match='屏幕已关闭或切换'):
        controller.verify()


@pytest.mark.parametrize('use_manager', [False, True])
def test_launch_uses_selected_version(monkeypatch, tmp_path, use_manager):
    adb = tmp_path / 'adb.exe'
    if use_manager:
        adb.with_name('MuMuManager.exe').touch()
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        output = b'{"is_android_started": true}' if command[1] == 'info' else b'{"errcode": 0}'
        return SimpleNamespace(stdout=output, stderr=b'', returncode=0)

    monkeypatch.setattr(backend.subprocess, 'run', run)
    Backend({'adb': str(adb), 'game_version': '1.88'}).launch_game()
    assert calls[-1][-2:] == ['-pkg' if use_manager else '-p', GAME_PACKAGES['1.88']]


def test_close_selected_version_keeps_other_version_and_mumu_open():
    new_package = GAME_PACKAGES['1.88']
    calls, logs = [], []

    def command(*args):
        calls.append(args)
        return f'''Display: mDisplayId=3
    mCurrentFocus=Window{{u0 {PACKAGE}/.AppActivity}}
  Display: mDisplayId=4
    mFocusedApp=ActivityRecord{{u0 {new_package}/.AppActivity}}'''

    controller = SimpleNamespace(package=new_package, cmd=command)
    assert close_game_and_mumu(SimpleNamespace(controller=controller), logs.append) is False
    assert calls == [('shell', 'dumpsys', 'window', 'displays'), ('shell', 'am', 'force-stop', new_package)]
    assert PACKAGE in logs[0]
