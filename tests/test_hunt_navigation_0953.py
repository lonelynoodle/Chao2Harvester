"""Lost hunt navigation must retry the pending card, never its paid search."""
from copy import deepcopy

import pytest

from chao2.activities import hunt_rows
from chao2.backend import Word
from chao2.policy import TaskBlocked, UserStopped
from test_configuration import captured, daily, screen


def setup_navigation(tmp_path,monkeypatch):
    d=daily(tmp_path);d.active_task='hunt';clock=[0.0]
    monkeypatch.setattr('chao2.activities.time.monotonic',lambda:clock[0])
    d.b.sleep=lambda seconds:clock.__setitem__(0,clock[0]+seconds)
    d.ensure_detail=lambda s:s
    d.b.click_text=lambda *a:pytest.fail('Navigation must not search or challenge')
    menu=captured('v0953-hunt-navigation',True)
    detail=screen(('敌方阵容',1100,130,120,30),('排阵',820,610,65,35),
                  ('前往挑战',1035,610,115,30),('未知',135,135,60,30))
    state=[menu];clicks=[]
    def observe():
        s=deepcopy(state[0]);s.when=clock[0];return s
    d.observe=observe
    def click(s,p,*a):
        assert s.when==clock[0]
        clicks.append((s,p));state[0]=detail
    d.b.click_at=click
    return d,clock,state,clicks,menu,detail


def test_actual_failed_map_recovers_same_hunter_without_search_or_challenge(tmp_path,monkeypatch):
    d,clock,state,clicks,menu,detail=setup_navigation(tmp_path,monkeypatch)
    assert len(hunt_rows(menu))==3
    result=d.await_detail(hunt_target=(3,0))
    assert result.text==detail.text and [p for _,p in clicks]==[(1000,207)]
    assert clock[0]>=8 and len(d.report['navigation_retries'])==1
    assert not d.search_counts and not d.task_counts and d.battles==0


def test_three_retries_are_spaced_and_bounded_then_preserve_pending_batch(tmp_path,monkeypatch):
    d,clock,state,clicks,menu,_=setup_navigation(tmp_path,monkeypatch)
    d.report['hunt_batch']={'remaining':3,'status':'active'}
    d.b.click_at=lambda s,p,*a:clicks.append((clock[0],p))
    with pytest.raises(TaskBlocked,match='重新定位同一猎物3次'):
        d.await_detail(hunt_target=(3,0))
    assert clicks==[(8,(1000,207)),(16,(1000,207)),(24,(1000,207))]
    assert d.report['hunt_batch']=={'remaining':3,'status':'active'}
    assert clock[0]==35 and not d.search_counts and d.battles==0


@pytest.mark.parametrize('missing',['狩猎','商店','传送','45/177'])
def test_incomplete_map_does_not_reuse_old_coordinates(tmp_path,monkeypatch,missing):
    d,_,state,clicks,menu,_=setup_navigation(tmp_path,monkeypatch)
    menu.words=[w for w in menu.words if w.text!=missing]
    with pytest.raises(TaskBlocked,match='寻路或打开关卡未完成'):
        d.await_detail(hunt_target=(3,0))
    assert not clicks and not d.report.get('navigation_retries')


@pytest.mark.parametrize('modal',['请选择','获得奖励','取消','提示','排阵','退出'])
def test_overlay_never_replays_background_hunter_card(tmp_path,monkeypatch,modal):
    d,_,_,clicks,menu,_=setup_navigation(tmp_path,monkeypatch)
    menu.words.append(Word(modal,[400,240,200,30],.99))
    assert not d.retry_hunt_navigation(menu,(3,0),1) and not clicks


def test_list_changed_during_navigation_is_not_retargeted(tmp_path,monkeypatch):
    d,_,_,clicks,menu,_=setup_navigation(tmp_path,monkeypatch)
    menu.words=[w for w in menu.words if not (800<w.center[0]<1200 and 430<w.center[1]<570)]
    assert len(hunt_rows(menu))==2
    with pytest.raises(TaskBlocked,match='猎物已离开或列表改变'):
        d.await_detail(hunt_target=(3,0))
    assert not clicks


def test_loading_and_arriving_detail_are_observed_without_extra_input(tmp_path,monkeypatch):
    d,clock,_,clicks,_,detail=setup_navigation(tmp_path,monkeypatch)
    blank=screen()
    def observe():
        s=deepcopy(detail if clock[0]>=10 else blank);s.when=clock[0];return s
    d.observe=observe
    assert d.await_detail(hunt_target=(3,0)).text==detail.text and not clicks


def test_unscoped_navigation_keeps_observation_only_behavior(tmp_path,monkeypatch):
    d,_,_,clicks,_,_=setup_navigation(tmp_path,monkeypatch)
    with pytest.raises(TaskBlocked,match='寻路或打开关卡未完成'):d.await_detail()
    assert not clicks


def test_user_stop_ends_navigation_retries_immediately(tmp_path,monkeypatch):
    d,_,_,clicks,_,_=setup_navigation(tmp_path,monkeypatch)
    d.b.click_at=lambda s,p,*a:clicks.append((s,p))
    old=d.b.guard
    def guard(s):
        if clicks:raise UserStopped('用户停止')
        old(s)
    d.b.guard=guard
    with pytest.raises(UserStopped):d.await_detail(hunt_target=(3,0))
    assert len(clicks)==1 and not d.search_counts
