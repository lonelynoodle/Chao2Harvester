"""Reward completion with an unchanged point balance, from the 22:57 run.

The saved after-frame is real. The missing before-frame is reconstructed with
an unopened node from that same capture; it is a simulated state, not live proof.
"""
from copy import deepcopy

import pytest

import chao2.forest as forest
from chao2.forest import ForestNode,forest_nodes,forest_reward_at,forest_shift
from chao2.policy import SafetyStop,TaskBlocked,UserStopped
from test_configuration import captured,daily,screen


@pytest.mark.parametrize('name,point',[
    ('v096-forest-revealed',(479,136)),
    ('v096-forest-explore-2',(736,348)),
])
def test_real_reward_tiles_are_recognized_at_the_original_node(name,point):
    assert forest_reward_at(captured(name,True),point)


@pytest.mark.parametrize('name,point',[
    ('v096-forest-revealed',(558,205)),
    ('v096-forest-revealed',(258,336)),
    ('v096-forest-revealed',(570,449)),
    ('v096-forest-revealed',(1101,336)),
    ('v085-forest-map',(109,165)),
    ('v085-forest-map',(394,299)),
    ('v085-forest-map',(640,350)),
    ('v096-forest-revealed',(15,50)),
])
def test_unopened_nodes_branches_and_edges_are_not_completion(name,point):
    assert not forest_reward_at(captured(name,True),point)


def revealed_game(tmp_path):
    d=daily(tmp_path);after=captured('v096-forest-revealed',True)
    before=deepcopy(after)
    # Reconstruct the unknown icon and its text at the clicked position.
    before.image[66:181,419:539]=after.image[135:250,498:618].copy()
    before.words+=screen(('开始探索',435,124,88,24),('1',484,150,20,18)).words
    n=ForestNode('unknown',(479,136),'explore',1,(479,136))
    d.forest_pool=[n];d.forest_ignored=[];d.forest_offset=[0.,0.]
    d.b.match_template=lambda *_:True;d.b.read_number=lambda *_:None
    d.b.sleep=lambda _:None
    inputs=[];reads=[]
    d.b.click_text=lambda *a:inputs.append(a)
    def observe():
        q=after if inputs else before
        reads.append(q);return q
    d.observe=observe
    d.resource_balance('forest','探索点',6)
    assert any(x.point==n.point for x in forest_nodes(d.b,before))
    assert not forest_reward_at(before,n.point)
    assert forest_shift(before,after)==pytest.approx((0,0),abs=.5)
    return d,before,after,n,inputs,reads


def test_reward_confirmed_twice_continues_without_replaying_or_inventing_cost(tmp_path):
    d,before,after,n,inputs,reads=revealed_game(tmp_path)
    assert d.forest_explore(before,n) is after
    assert len(inputs)==1 and sum(q is after for q in reads)==2
    record=d.report['forest_explorations'][0]
    assert record['status']=='confirmed' and record['confirmation']=='reward'
    assert record['before']==record['after']==6
    assert d.report['resource_usage']['forest']['探索点']=={
        'start':6,'remaining':6,'spent':0,'unverified':1}
    assert n.world in d.forest_ignored
    assert all(x.world!=n.world for x in d.forest_pool)
    assert (tmp_path/'forest-explore-1-before.png').exists()
    assert (tmp_path/'forest-explore-1.png').exists()


def test_expected_point_deduction_remains_confirmed_normally(tmp_path):
    d,before,after,n,inputs,reads=revealed_game(tmp_path)
    next(w for w in after.words if w.text=='6/15').text='5/15'
    d.forest_explore(before,n)
    assert len(inputs)==1 and sum(q is after for q in reads)==1
    assert d.report['forest_explorations'][0]['confirmation']=='points'
    assert d.report['resource_usage']['forest']['探索点']['spent']==1
    assert d.report['resource_usage']['forest']['探索点']['unverified']==0


def test_unchanged_node_and_balance_do_not_count_as_completed(tmp_path):
    d,before,after,n,inputs,reads=revealed_game(tmp_path)
    d.observe=lambda:before
    with pytest.raises(TaskBlocked,match='消耗未确认'):d.forest_explore(before,n)
    assert len(inputs)==1 and not d.forest_ignored
    assert d.report['forest_explorations'][0]['status']=='started'


def test_one_reward_frame_followed_by_original_node_is_not_enough(tmp_path):
    d,before,after,n,inputs,reads=revealed_game(tmp_path)
    frames=iter([before,after]+[before]*9);d.observe=lambda:next(frames)
    with pytest.raises(TaskBlocked,match='消耗未确认'):d.forest_explore(before,n)
    assert len(inputs)==1 and not d.forest_ignored


@pytest.mark.parametrize('shift',[None,(8,0),(0,-10)])
def test_camera_motion_or_unverified_map_does_not_complete_another_node(tmp_path,monkeypatch,shift):
    d,before,after,n,inputs,reads=revealed_game(tmp_path)
    monkeypatch.setattr(forest,'forest_shift',lambda *a:shift)
    with pytest.raises(TaskBlocked,match='消耗未确认'):d.forest_explore(before,n)
    assert len(inputs)==1 and not d.forest_ignored


def test_unexpected_extra_spend_still_stops_even_when_reward_is_visible(tmp_path):
    d,before,after,n,inputs,reads=revealed_game(tmp_path)
    next(w for w in after.words if w.text=='6/15').text='4/15'
    with pytest.raises(SafetyStop,match='费用不符'):d.forest_explore(before,n)
    assert len(inputs)==1 and not d.forest_ignored


def test_stop_during_result_confirmation_does_not_repeat_input(tmp_path):
    d,before,after,n,inputs,reads=revealed_game(tmp_path)
    def observe():
        if inputs:raise UserStopped('用户停止')
        return before
    d.observe=observe
    with pytest.raises(UserStopped):d.forest_explore(before,n)
    assert len(inputs)==1 and not d.forest_ignored


def test_already_revealed_target_cannot_start_another_exploration(tmp_path):
    d,before,after,n,inputs,reads=revealed_game(tmp_path)
    d.observe=lambda:after
    with pytest.raises(TaskBlocked,match='节点或费用改变'):d.forest_explore(after,n)
    assert inputs==[] and 'forest_explorations' not in d.report
