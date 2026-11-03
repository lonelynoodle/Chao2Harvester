import pytest
from test_configuration import daily,captured,screen
from chao2.world_events import is_map_choice,map_choice_main_target
from chao2.workflows import is_world


def test_actual_blurred_stamina_does_not_hide_map_choice():
    s=captured('v0912-main-overlap',True)
    assert s.region_text((490,0,170,65))=='66'
    assert is_map_choice(s) and not is_world(s)
    target=map_choice_main_target(s)
    assert target and target.text=='龙帝的新装涂'


def test_home_dismisses_actual_modal_without_needing_background_resource(tmp_path):
    d=daily(tmp_path);s=captured('v0912-main-overlap',True);world=captured('v092-main-map594',True)
    d.observe=lambda:world;calls=[];d.b.click_at=lambda q,pt,*args:calls.append(pt)
    assert d.home(s) is world
    assert calls==[(750,331)]


def test_main_overlap_selects_sword_row_once_and_waits_for_delayed_close(tmp_path):
    d=daily(tmp_path);s=captured('v0912-main-overlap',True);detail=captured('v092-main-detail594')
    frames=iter([s,detail]);d.observe=lambda:next(frames);d.b.sleep=lambda *_:None
    calls=[];d.b.click_at=lambda q,pt,*args:calls.append(pt)
    assert d.open_main_choice(s) is detail
    assert calls==[map_choice_main_target(s).center]


def test_seen_different_stage_not_reopened_when_finding_specific_target(tmp_path):
    d=daily(tmp_path);s=captured('v092-main-map594',True)
    d.main_views['594']=s;d.main_positions['594']=(532,393)
    assert d.known_main_node(s,(532,393))=='594'
    assert d.known_main_node(s,(900,400)) is None


def test_unknown_choice_icon_never_selects_copy(tmp_path):
    d=daily(tmp_path);s=captured('v0912-main-overlap')
    assert is_map_choice(s) and map_choice_main_target(s) is None
    d.b.click_at=lambda *a:pytest.fail('No guessing between unrelated targets')
    from chao2.policy import TaskBlocked
    with pytest.raises(TaskBlocked,match='未确认主线'):d.open_main_choice(s)


def test_completed_node_is_not_reopened_in_later_pan_scan(tmp_path,monkeypatch):
    import chao2.activities as module
    d=daily(tmp_path);world=captured('v092-main-map594',True)
    completed=captured('v091-completed-detail')
    d.home=lambda *a:world;d.observe=lambda:completed;clicks=[]
    d.click_world=lambda s,pt,*a:clicks.append(pt)
    monkeypatch.setattr(module,'main_nodes',lambda s:[(532,393)])
    assert d.find_main_candidate(set()) is None
    assert d.find_main_candidate(set()) is None
    assert clicks==[(532,393)]


def test_main_without_result_hud_reconciles_once_from_world_balance(tmp_path):
    d=daily(tmp_path)
    d.resource_balance('main','地图体力',10)
    d.settle_battle_resource('main',captured('v092-main-victory'),'victory',10)
    row=d.report['resource_usage']['main']['地图体力']
    assert row['spent']==0 and row['unverified']==1
    d.reconcile_main_resource(5)
    assert row['spent']==5 and row['unverified']==0 and row['remaining']==5
    d.reconcile_main_resource(5)
    assert row['spent']==5


def test_main_unexpected_balance_does_not_invent_verified_consumption(tmp_path):
    d=daily(tmp_path)
    d.settle_battle_resource('main',captured('v092-main-victory'),'victory',10)
    d.reconcile_main_resource(2)
    assert d.report['resource_usage']['main']['地图体力']['unverified']==1
