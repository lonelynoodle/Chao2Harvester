"""Regression for the user's 20:20 run: swallowed overview swipe and map OCR."""
import pytest
import time
from chao2.anomalies import is_event_panel
from chao2.activities import is_copy_list
from chao2.backend import Word
from chao2.workflows import is_world,world_anchors
from test_configuration import captured,daily


def test_map_recovery_reads_pixels_and_keeps_original_words(tmp_path):
    d=daily(tmp_path);s=captured('v089-world-misread',True)
    assert not is_world(s) and s.find('^世界向响$')
    calls=[];d.b.read_text_crop=lambda s,roi:calls.append(roi) or '事件'
    q=d.recover_world_navigation(s)
    assert is_world(q) and q.find('^世界向响$') and q.find('^事件$')
    assert len(world_anchors(q))==2 and len(calls)==1
    assert not s.find('^事件$')  # Retain the source OCR for diagnostics.


def test_second_bottom_label_is_tried_if_first_is_unreadable(tmp_path):
    d=daily(tmp_path);calls=[]
    def crop(s,roi):calls.append(roi);return '' if len(calls)==1 else '领地'
    d.b.read_text_crop=crop
    assert is_world(d.recover_world_navigation(captured('v089-world-misread',True)))
    assert len(calls)==2


def test_nonmatching_local_text_cannot_authorize_navigation(tmp_path):
    d=daily(tmp_path);d.b.read_text_crop=lambda *a:'事件奖励'
    s=captured('v089-world-misread',True)
    assert d.recover_world_navigation(s) is s and not is_world(s)


@pytest.mark.parametrize('overlay',['玩法概览','领取','敌方阵容','主要获得途径','本周已获取友好点数1000'])
def test_overlay_never_triggers_map_local_recovery(tmp_path,overlay):
    d=daily(tmp_path);s=captured('v089-world-misread',True)
    s.words.append(Word(overlay,[400,300,200,30],.99))
    d.b.read_text_crop=lambda *a:pytest.fail('Must not recognize/click the obscured map')
    assert d.recover_world_navigation(s) is s and not is_world(s)


def test_recovered_map_updates_observed_resource_feedback(tmp_path):
    d=daily(tmp_path);d.b.observe=lambda *a:captured('v089-world-misread',True)
    d.b.read_text_crop=lambda *a:'事件'
    s=d.observe()
    assert is_world(s) and d.report['resources_last_observed']['stamina']==61
    assert d.report['resources_last_observed']['diamonds']==2393


def test_captured_event_categories_are_recognized_without_world_false_positive():
    for name in ('v089-event-copies','v089-event-exploration'):
        s=captured(name,True);assert is_event_panel(s) and not is_world(s)


def test_world_opens_copies_in_one_event_click_without_overview(tmp_path):
    d=daily(tmp_path);world=captured('v089-world-misread',True)
    page=[world];clicks=[];d.b.read_text_crop=lambda *a:'事件'
    d.observe=lambda *a:page[0];d.home=lambda *a:d.recover_world_navigation(world)
    d.enter_overview=lambda *a:pytest.fail('Direct route must not open overview')
    def click(s,p,anchors,reason):
        assert is_world(s) and s.has(*anchors)
        clicks.append((p,reason));page[0]=captured('v089-event-copies',True)
    d.b.click_at=click
    assert is_copy_list(d.copy_list())
    assert clicks==[((1105,620),'从世界事件进入异象')]
    d.copy_list();assert len(clicks)==1  # Reuse already-open list.


def test_copy_event_entry_failure_falls_back_to_visual_overview_once(tmp_path):
    from chao2.policy import TaskBlocked
    d=daily(tmp_path);d.observe=lambda:captured('v089-world-misread')
    d.open_anomaly_list=lambda _s:(_ for _ in ()).throw(TaskBlocked('事件入口未确认'))
    calls=[]
    d.overview_entry=lambda key,reason='':calls.append((key,reason)) or captured('v089-event-copies')
    assert is_copy_list(d.copy_list()) and len(calls)==1 and calls[0][0]=='copies'


def test_prepared_copy_overview_failure_is_not_replayed(tmp_path):
    from chao2.policy import TaskBlocked
    d=daily(tmp_path);d._overview_ready='copies'
    d.observe=lambda:captured('v089-world-misread')
    d.open_anomaly_list=lambda _s:(_ for _ in ()).throw(TaskBlocked('概览入口未确认'))
    d.overview_entry=lambda *_a,**_k:pytest.fail('Do not repeat the same overview jump')
    with pytest.raises(TaskBlocked,match='概览入口未确认'):d.copy_list()


def test_exploration_event_panel_switches_category_without_world_detour(tmp_path):
    d=daily(tmp_path);page=[captured('v089-event-exploration',True)];clicks=[]
    d.observe=lambda *a:page[0]
    d.home=lambda *a:pytest.fail('Already inside event navigation')
    def click(s,pattern,roi=None):
        assert s.find(pattern,roi);clicks.append((pattern,roi))
        page[0]=captured('v089-event-copies',True)
    d.b.click_text=click
    assert is_copy_list(d.copy_list())
    assert clicks==[('^战斗$',(1200,95,80,70))]


def test_other_battle_subtab_selects_anomaly_tab_only(tmp_path):
    d=daily(tmp_path);s=captured('v089-event-copies',True)
    s.words=[w for w in s.words if not w.text.startswith('本周已获')]
    for w in s.words:
        if w.text=='异象' and w.box[1]<65:w.text='深渊先遣'
    page=[s];clicks=[];d.observe=lambda *a:page[0]
    d.home=lambda *a:pytest.fail('Do not close an event pane')
    def click(s,pattern,roi=None):
        assert s.find(pattern,roi);clicks.append((pattern,roi))
        page[0]=captured('v089-event-copies',True)
    d.b.click_text=click
    assert is_copy_list(d.copy_list())
    assert clicks==[('^异象$',(810,650,120,60))]


def test_prepared_overview_entry_is_still_reused_in_unordered_mode(tmp_path):
    d=daily(tmp_path);d._overview_ready='copies';calls=[]
    d.enter_overview=lambda p:calls.append(p) or captured('v089-event-copies')
    d.home=lambda *a:pytest.fail('Prepared arrow is already visible')
    assert is_copy_list(d.open_anomaly_list(captured('v089-overview-stalled')))
    assert calls==['^异象$']


@pytest.mark.parametrize('opens_after_retry',[True,False])
def test_swallowed_event_click_retries_once_only_on_verified_map(tmp_path,monkeypatch,opens_after_retry):
    clock=[0.0];monkeypatch.setattr(time,'monotonic',lambda:clock[0])
    d=daily(tmp_path);world=captured('v089-world-misread',True)
    world.words.append(Word('事件',[1070,628,75,40],.99))
    page=[world];clicks=[]
    d.observe=lambda:page[0];d.b.sleep=lambda t:clock.__setitem__(0,clock[0]+t)
    def click(s,p,reason):
        assert is_world(s);clicks.append(p)
        if len(clicks)==2 and opens_after_retry:page[0]=captured('v089-event-copies',True)
    d.click_world=click
    def observe():page[0].when=clock[0];return page[0]
    d.observe=observe
    if opens_after_retry:assert is_copy_list(d.open_world_events(world))
    else:
        from chao2.policy import TaskBlocked
        with pytest.raises(TaskBlocked,match='停止重试'):d.open_world_events(world)
    assert clicks==[(1105,620),(1105,646)]


def test_unrecognized_overlay_does_not_receive_event_retry(tmp_path,monkeypatch):
    from chao2.policy import TaskBlocked
    clock=[0.0];monkeypatch.setattr(time,'monotonic',lambda:clock[0])
    d=daily(tmp_path);s=captured('v089-world-misread',True)
    s.words.append(Word('请选择',[600,300,80,30],.99))
    calls=[];d.click_world=lambda *a:calls.append(a)
    def observe():s.when=clock[0];return s
    d.observe=observe;d.b.sleep=lambda t:clock.__setitem__(0,clock[0]+t)
    with pytest.raises(TaskBlocked,match='停止重试'):d.open_world_events(s)
    assert len(calls)==1
