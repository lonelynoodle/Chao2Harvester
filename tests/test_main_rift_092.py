"""Regression coverage for main fallback navigation and animated rift nodes."""
from types import SimpleNamespace
import pytest
from test_configuration import daily,captured,screen
from chao2.policy import TaskBlocked
from chao2.rift import rift_map_moved
from chao2.activities import main_identity,main_map_shift,main_nodes


def test_rift_repeated_stationary_map_does_not_swipe_seven_times(tmp_path,monkeypatch):
    import chao2.rift as module
    d=daily(tmp_path);s=captured('v092-rift-map25',True);swipes=[]
    d.observe=lambda:s;d.b.sleep=lambda *_:None
    d.b.controller=SimpleNamespace(post_swipe=lambda *a:swipes.append(a))
    d.b.wait=lambda *_:SimpleNamespace(succeeded=True)
    monkeypatch.setattr(module,'rift_node',lambda *a:None)
    with pytest.raises(TaskBlocked,match='连续两次未移动'):d.rift_locate(s,999)
    assert len(swipes)==2


def test_rift_motion_uses_nodes_not_top_progress_or_rank():
    a=screen(('25',624,35,34,28),('26',433,455,23,17),('29',782,463,27,22),('28',982,661,30,23))
    b=screen(('26',624,35,34,28),('26',434,454,23,17),('29',782,464,27,22),('27',982,661,30,23))
    assert rift_map_moved(a,b) is False
    b.words[1].box[0]+=100
    assert rift_map_moved(a,b) is True


def test_main_victory_without_next_button_can_return_home(tmp_path):
    from chao2.workflows import is_world
    d=daily(tmp_path);result=captured('v092-main-victory',True)
    pages=iter([result,captured('world-missed-label',True)])
    d.observe=lambda:next(pages);calls=[];d.exit_result=lambda s:calls.append(s)
    assert is_world(d.home()) and calls==[result]


def test_main_registers_camera_translation_before_reusing_node():
    import copy,cv2,numpy as np
    source=captured('v092-main-map594',True);moved=copy.deepcopy(source)
    moved.image=cv2.warpAffine(source.image,np.float32([[1,0,120],[0,1,-25]]),(1280,720))
    shift=main_map_shift(source,moved)
    assert shift is not None and shift==pytest.approx((120,-25),abs=2)
    assert min(((x-652)**2+(y-368)**2)**.5 for x,y in main_nodes(moved))<5


def test_main_node_at_top_edge_is_not_hidden_by_old_global_hud_mask():
    s=captured('v092-main-edge594',True)
    assert min(((x-659)**2+(y-166)**2)**.5 for x,y in main_nodes(s))<5


def test_main_arrival_tracks_the_node_when_walking_moves_camera(tmp_path,monkeypatch):
    import copy,cv2,numpy as np
    import chao2.activities as module
    d=daily(tmp_path);source=captured('v092-main-map594',True);moved=copy.deepcopy(source)
    moved.image=cv2.warpAffine(source.image,np.float32([[1,0,100],[0,1,20]]),(1280,720))
    detail=captured('v092-main-detail594',True)
    d.home=lambda:source;pages=iter([moved,moved,detail]);d.observe=lambda:next(pages)
    d.b.sleep=lambda *_:None;clicks=[];d.click_world=lambda s,p,why:clicks.append(p)
    monkeypatch.setattr(module,'main_nodes',lambda s:[(632,413)] if s is moved else [(532,393)])
    assert d.find_main_candidate(set(),wanted='594') is detail
    assert clicks==[(532,393),(632,413)]
    assert d.main_positions['594']==(632,413) and d.main_views['594'] is moved


def test_main_retry_uses_bound_node_without_overview_or_other_nodes(tmp_path):
    d=daily(tmp_path);s=captured('v092-main-map594',True);q=captured('v092-main-detail594',True)
    d.main_positions['594']=(532,393);d.main_views['594']=s
    d.home=lambda:s;d.await_detail=lambda:q;clicks=[]
    d.click_world=lambda s,p,why:clicks.append(p)
    d.enter_overview=lambda *a:pytest.fail('Overview must not replace the retry target')
    d.find_main_candidate=lambda *a,**k:pytest.fail('Known node must be tried first')
    assert d.last_main_detail('594') is q and clicks==[(532,393)]


def test_changed_node_identity_is_not_accepted_as_retry(tmp_path):
    d=daily(tmp_path);s=captured('v092-main-map594',True)
    d.main_positions['594']=(532,393);d.main_views['594']=s
    d.home=lambda:s;d.await_detail=lambda:captured('v091-completed-detail')
    d.click_world=lambda *a:None;closed=[];d.back_detail=lambda q:closed.append(q)
    d.find_main_candidate=lambda *a,**k:None
    d.enter_overview=lambda *a:pytest.fail('Do not ask overview for a replacement')
    with pytest.raises(TaskBlocked,match='原主线594'):d.last_main_detail('594')
    assert len(closed)==1


def test_remote_overview_stage_can_start_without_prebinding_local_camera(tmp_path):
    d=daily(tmp_path);d.active_task='main';d.options['main'].update(teams=[1,2],max_nodes=1)
    world=captured('v092-main-map594',True);target=captured('v092-main-detail594',True)
    import copy
    remote=copy.deepcopy(target)
    next(w for w in remote.words if w.text=='594').text='685'
    d.home=lambda:world;d.world_resources=lambda s:{'stamina':30}
    d.enter_overview=lambda *a:None;d.await_detail=lambda:remote;d.back_detail=lambda *_:None
    d.observe=lambda:remote;d.b.sleep=lambda _:None
    d.find_main_candidate=lambda *a,**kw:pytest.fail('No preflight local scan for a remote overview target')
    played=[]
    def fight(task,opener,resource,verify):
        q=opener();verify(q);played.append(main_identity(q));return True
    d.play_encounter=fight
    assert '通关1次' in d.main()
    assert played==['685'] and 'main_unlocated' not in d.report
