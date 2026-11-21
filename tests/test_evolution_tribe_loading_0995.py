"""Replay the real loading interruption and missed free reward dismissal offline."""
from types import SimpleNamespace
import cv2
import numpy as np
import pytest

from chao2 import navigation_retry,screen_loading
from chao2.activities import is_tribe_map,is_tribe_reward_overlay
from chao2.policy import TaskBlocked,UserStopped,PageChanged
from chao2.workflows import is_world
from test_configuration import daily,screen,captured


def world():
    return screen(('任务挑战',1196,42,80,24),('世界回响',1196,138,80,24),('35/187',500,12,80,28))


def loading():
    s=screen(('加载提示',450,570,300,24));s.image[112:606]=60
    icon=screen_loading._scene_indicator()
    assert icon is not None
    s.image[520:564,596:687]=icon
    return s


def clock(d,monkeypatch):
    now=[0.]
    monkeypatch.setattr(navigation_retry,'time',SimpleNamespace(monotonic=lambda:now[0]))
    d.b.sleep=lambda seconds:now.__setitem__(0,now[0]+seconds)
    d.resolve_path_event=lambda _:None
    return now


def tribe(amount=0):
    return screen(('部落',140,14,60,28),('部落大厅',1120,640,110,35),
                  ('遗迹占领奖励',1132,150,140,30),(str(amount),1228,125,30,25))


def reward():
    return screen(('部落',140,14,60,28),('获得奖励',518,123,240,59),
                  ('点击空白位置关闭',550,604,182,27))


def test_actual_interruption_is_a_scene_load_not_an_unknown_return_page():
    assert screen_loading.scene_loading(captured('v0995-evolution-loading',True))


@pytest.mark.parametrize('alteration',['blank','no_icon','no_bars','reward','world'])
def test_sparse_ocr_or_an_unrelated_overlay_is_not_a_scene_load(alteration):
    s=loading();assert screen_loading.scene_loading(s)
    if alteration=='blank':s=screen()
    elif alteration=='no_icon':s.image[520:564,596:687]=60
    elif alteration=='no_bars':s.image[:100]=120
    elif alteration=='reward':s.words+=reward().words
    elif alteration=='world':s.words+=world().words
    assert not screen_loading.scene_loading(s)


def test_home_waits_out_loading_without_sending_back_or_replaying_inputs(tmp_path,monkeypatch):
    d=daily(tmp_path);now=clock(d,monkeypatch);ready=world();assert is_world(ready)
    pages=iter([loading(),loading(),loading(),ready]);d.observe=lambda:next(pages)
    d.b.back=lambda *a:pytest.fail('No return input on loading')
    d.b.click_at=lambda *a,**k:pytest.fail('No click on loading')
    assert d.home() is ready and now[0]==1.5
    assert not d.report.get('page_backtracks')


def test_persistent_load_is_bounded_and_never_clicks_unknown_pixels(tmp_path,monkeypatch):
    d=daily(tmp_path);now=clock(d,monkeypatch);s=loading();d.observe=lambda:s
    d.b.back=lambda *a:pytest.fail('No return on load')
    with pytest.raises(TaskBlocked,match='场景加载超过2秒'):d.wait_for_scene_loading(s,timeout=2)
    assert now[0]==2


def test_user_stop_while_loading_is_honored(tmp_path,monkeypatch):
    d=daily(tmp_path);clock(d,monkeypatch);d.b.stop.set()
    with pytest.raises(UserStopped):d.wait_for_scene_loading(loading())


def test_unknown_page_does_not_inherit_the_loading_wait(tmp_path):
    d=daily(tmp_path);s=screen(('unknown',200,200,80,25))
    d.observe=lambda:pytest.fail('Only a verified load may trigger this wait')
    assert d.wait_for_scene_loading(s) is s


@pytest.mark.parametrize('misses',[0,1,2,3])
def test_reward_free_close_retries_with_offsets_and_stops_as_soon_as_map_returns(tmp_path,monkeypatch,misses):
    d=daily(tmp_path);clock(d,monkeypatch);ready=tribe();state=[reward()];clicks=[]
    d.observe=lambda:state[0]
    def click(s,point,anchors,reason):
        assert is_tribe_reward_overlay(s) and s.has(*anchors)
        assert 637<=point[0]<=643 and 657<=point[1]<=662
        clicks.append(point)
        if len(clicks)>misses:state[0]=ready
    d.b.click_at=click
    assert d.clear_tribe_reward(state[0]) is ready
    assert len(clicks)==misses+1 and len(set(clicks))==len(clicks)


def test_all_ignored_reward_closes_are_bounded(tmp_path,monkeypatch):
    d=daily(tmp_path);now=clock(d,monkeypatch);s=reward();d.observe=lambda:s;clicks=[]
    d.b.click_at=lambda s,p,*a:clicks.append(p)
    with pytest.raises(TaskBlocked,match='已重试3次'):d.clear_tribe_reward(s)
    assert len(clicks)==4 and now[0]==12


def test_reward_retry_does_not_click_after_page_changes_to_another_page(tmp_path,monkeypatch):
    d=daily(tmp_path);clock(d,monkeypatch);s=reward();other=world();state=[s];clicks=[]
    def click(*a):clicks.append(1);state[0]=other
    d.b.click_at=click;d.observe=lambda:state[0]
    with pytest.raises(TaskBlocked):d.clear_tribe_reward(s)
    assert clicks==[1]


def test_successful_close_can_raise_page_changed_without_replaying_it(tmp_path,monkeypatch):
    d=daily(tmp_path);clock(d,monkeypatch);s=reward();ready=tribe();d.observe=lambda:ready;clicks=[]
    def click(*a):clicks.append(1);raise PageChanged('already closed',ready)
    d.b.click_at=click
    assert d.clear_tribe_reward(s) is ready and clicks==[1]


def test_actual_occupation_receipt_survives_missed_close_and_continues_adventure(tmp_path,monkeypatch):
    d=daily(tmp_path);clock(d,monkeypatch);before=tribe(23);after=tribe()
    original=captured('v0995-tribe-reward',True)
    assert is_tribe_reward_overlay(original) and not is_tribe_map(original)
    state=[before];claims=[];closes=[]
    def click(s,point,anchors,reason):
        if point==(1214,123):claims.append(point);state[0]=original
        else:
            assert is_tribe_reward_overlay(s)
            closes.append(point)
            if len(closes)==2:state[0]=after
    d.b.click_at=click;d.observe=lambda:state[0]
    assert d.claim_tribe_occupation(before) is after
    assert len(claims)==1 and len(closes)==2
    row=d.report['tribe_occupation_rewards'][0]
    assert row['status']=='claimed' and row['claimed']==23


def info(hue):
    s=screen(('怪兽信息',110,10,180,30),('进化',1050,420,80,40))
    s.image[78:124,645:710]=cv2.cvtColor(np.uint8([[[hue,230,230]]]),cv2.COLOR_HSV2BGR)[0,0]
    return s


def roster():
    s=screen(('怪兽数量',10,80,120,30),('品质',180,120,80,30))
    color=cv2.cvtColor(np.uint8([[[100,230,230]]]),cv2.COLOR_HSV2BGR)[0,0]
    s.image[300:414,118:230]=color;s.image[310:404,128:220]=0
    return s


@pytest.mark.parametrize('already_in_roster',[False,True])
def test_next_blue_is_selected_from_existing_info_or_roster_without_world_trip(tmp_path,already_in_roster):
    d=daily(tmp_path);purple=info(145);blue=info(100);cards=roster();clicks=[]
    d.observe=lambda:cards if already_in_roster else purple
    d.territory=lambda:pytest.fail('No world/territory round trip after a confirmed evolution')
    d.b.read_number=lambda *a:pytest.fail('Standalone quality check does not need monster level OCR')
    d.b.click_at=lambda s,p,*a:clicks.append(p)
    pages=iter([cards,blue] if already_in_roster else [cards,cards,blue])
    def wait(predicate,*a,**kw):
        s=next(pages);assert predicate(s);return s
    d.wait_for_screen=wait
    assert d.one_blue_roster(level_one_only=False,skip_locked=True) is blue
    assert clicks==([(174,354),(1228,106)] if already_in_roster else [(60,674),(174,354),(1228,106)])


def test_partial_evolution_stats_and_run_status_remain_consistent_on_failure(tmp_path):
    from chao2.configuration import SPECS
    d=daily(tmp_path)
    for f in SPECS['other']['fields']:
        if f['type']=='bool':d.options['other'][f['key']]=False
    d.options['other']['evolve_blue_monsters']=True
    def partial(result):
        result['evolved']=7
        raise TaskBlocked('页面恢复失败')
    d._run_blue_evolution=partial;d.recover_failed_task=lambda:None
    with pytest.raises(TaskBlocked):d.other()
    assert d.report['blue_evolution_runs']['other']['status']=='blocked'
    assert d.report['blue_evolution_runs']['other']['evolved']==7
    assert d.report['other_tasks']['blue_evolution']['status']=='blocked'


def test_second_instance_failure_does_not_change_the_first_instances_success(tmp_path):
    d=daily(tmp_path);d.options['other']['evolve_blue_monsters']=True
    active=['first'];d.report_key=lambda _:active[0]
    def finished(result):result.update(status='done',evolved=1);return result
    d._run_blue_evolution=finished
    first=d.evolve_blue_monsters();active[0]='second'
    def blocked(result):raise TaskBlocked('尚待核实')
    d._run_blue_evolution=blocked
    with pytest.raises(TaskBlocked):d.evolve_blue_monsters()
    assert first['status']=='done' and first['evolved']==1
    assert d.report['blue_evolution_runs']['second']['status']=='blocked'
    assert d.report['blue_evolution_runs']['second']['evolved']==0
