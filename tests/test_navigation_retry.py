import pytest
from chao2.policy import TaskBlocked,SafetyStop,UserStopped
from test_configuration import daily,screen,captured


def clocked(d,monkeypatch):
    import chao2.navigation_retry as module
    clock=[0.0]
    monkeypatch.setattr(module.time,'monotonic',lambda:clock[0])
    d.b.sleep=lambda delay:clock.__setitem__(0,clock[0]+delay)
    return clock


def test_generic_wait_recovers_from_late_transition_without_replaying_input(tmp_path,monkeypatch):
    d=daily(tmp_path);clock=clocked(d,monkeypatch);blank=screen();target=screen(('背包',110,20,80,30))
    d.observe=lambda:target if clock[0]>=2.5 else blank
    d.b.click_at=lambda *args:pytest.fail('An observation retry cannot replay item use or challenge')
    assert d.await_page('^背包$',timeout=1) is target
    assert [r['attempt'] for r in d.report['navigation_retries']]==[1,2]


def test_wait_stops_after_three_retries_and_records_reason(tmp_path,monkeypatch):
    d=daily(tmp_path);clock=clocked(d,monkeypatch);s=screen();d.observe=lambda:s
    with pytest.raises(TaskBlocked,match='已重试3次'):d.await_page('^背包$',timeout=1)
    assert clock[0]==4 and len(d.report['navigation_retries'])==3


@pytest.mark.parametrize('error',[SafetyStop('费用未知'),UserStopped('手动停止')])
def test_stop_and_unsafe_dialog_never_get_retried(tmp_path,error):
    d=daily(tmp_path);d.observe=lambda:screen()
    def guard(s):raise error
    d.b.guard=guard
    with pytest.raises(type(error)):d.await_page('^背包$')
    assert not d.report.get('navigation_retries')


def test_home_recovers_after_three_unknown_retries_without_clicking(tmp_path,monkeypatch):
    d=daily(tmp_path);clock=clocked(d,monkeypatch);blank=screen();world=captured('v0913-main-world',True)
    count=[0]
    def observe():
        count[0]+=1;s=world if count[0]==11 else blank;s.when=clock[0];return s
    d.observe=observe;d.b.click_at=lambda *args:pytest.fail('Never guess a close button')
    assert d.home() is world
    assert [r['attempt'] for r in d.report['navigation_retries']]==[1,2,3]
