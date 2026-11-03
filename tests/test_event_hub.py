"""Real failure: world announcements obscure the Fengye page heading."""
import pytest
from chao2.backend import Word
from chao2.event_hub import event_hub_anchors,is_event_hub
from chao2.policy import TaskBlocked
from test_configuration import captured,daily,screen


def test_covered_title_uses_multiple_positioned_entries_and_undimmed_close_area():
    s=captured('v0916-hub-covered',True)
    assert not s.find('^丰野间$') and is_event_hub(s)
    assert s.has(*event_hub_anchors(s))
    s.image[8:72,8:72]=0
    assert not is_event_hub(s)
    s=captured('v0916-hub-covered',True)
    s.words=[w for w in s.words if w.text not in ('幻境巡游','创世竞猜','暴走回廊','腾龙燃火')]
    assert not is_event_hub(s)


@pytest.mark.parametrize('text',['获得奖励','规则','请选择','确定','我的排名'])
def test_hub_does_not_dismiss_foreground_dialogues(tmp_path,text):
    s=captured('v0916-hub-covered',True);s.words.append(Word(text,[550,200,150,30],.99))
    assert not is_event_hub(s)
    d=daily(tmp_path);d.b.click_at=lambda *a:pytest.fail('Never close an unconfirmed page')
    with pytest.raises(TaskBlocked,match='未确认'):d.close_event_hub(s)


def test_hub_is_not_confused_with_world_or_giant_detail():
    assert not is_event_hub(captured('v0913-main-world',True))
    assert not is_event_hub(captured('v077-giant-ready',True))
    assert not is_event_hub(captured('giant-menu'))
    s=captured('v0916-hub-covered',True)
    for word in s.words:word.box[0]=10
    assert not is_event_hub(s)


def test_giant_opens_directly_from_covered_hub_without_world_detour(tmp_path):
    d=daily(tmp_path);hub=captured('v0916-hub-covered',True);menu=captured('giant-menu')
    d.observe=lambda:hub;d.await_page=lambda *args:menu
    d.home=lambda *args:pytest.fail('Reuse the current event hub')
    clicks=[]
    def click(s,point,anchors,reason):
        assert s.has(*anchors);clicks.append((point,reason))
    d.b.click_at=click
    assert d.giant_menu() is menu
    assert clicks==[(hub.find('^进击巨物$').center,'进入进击巨物')]
    assert not d.battles


def test_hub_wait_accepts_announcement_after_single_navigation_click(tmp_path):
    d=daily(tmp_path);world=captured('v0913-main-world',True);hub=captured('v0916-hub-covered',True)
    frames=iter([screen(),hub]);d.observe=lambda:next(frames);d.home=lambda s:s
    d.b.sleep=lambda _:None;clicks=[];d.click_world=lambda *args:clicks.append(args[1])
    assert d.event_hub(world) is hub and clicks==[(220,83)]
    assert d.report['event_hub_title_recovered']


def test_home_waits_for_close_animation_without_repeated_clicks(tmp_path):
    d=daily(tmp_path);hub=captured('v0916-hub-covered',True);world=captured('v0913-main-world',True)
    frames=iter([hub,hub,world]);d.observe=lambda:next(frames);d.b.sleep=lambda _:None
    clicks=[];d.b.click_at=lambda *args:clicks.append(args[1])
    assert d.home(hub) is world and clicks==[(45,28)]


def test_hub_close_retries_only_verified_hub_and_is_bounded(tmp_path,monkeypatch):
    import chao2.navigation_retry as hub_module
    d=daily(tmp_path);s=captured('v0916-hub-covered',True);clock=[0.0]
    monkeypatch.setattr(hub_module.time,'monotonic',lambda:clock[0])
    d.observe=lambda:s;d.b.sleep=lambda delay:clock.__setitem__(0,clock[0]+delay)
    clicks=[];d.b.click_at=lambda *args:clicks.append(args[1])
    with pytest.raises(TaskBlocked,match='已重试3次'):d.close_event_hub(s)
    assert clicks==[(45,28)]*4 and clock[0]==48
    assert len(d.report['navigation_retries'])==3


def test_hub_failed_navigation_reopens_only_from_confirmed_world(tmp_path,monkeypatch):
    import chao2.navigation_retry as recovery
    d=daily(tmp_path);world=captured('v0913-main-world',True);hub=captured('v0916-hub-covered',True)
    clock=[0.0];current=[world];clicks=[]
    monkeypatch.setattr(recovery.time,'monotonic',lambda:clock[0])
    d.observe=lambda:current[0];d.b.sleep=lambda delay:clock.__setitem__(0,clock[0]+delay)
    def click(s,point,reason):
        clicks.append(point);current[0]=hub
    d.click_world=click
    assert d.await_event_hub() is hub
    assert clicks==[(220,83)] and len(d.report['navigation_retries'])==1
