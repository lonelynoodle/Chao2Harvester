"""Node strategy, reserves, no-wait behavior and actual forest screenshots."""
import pytest
from test_configuration import daily,captured,screen
from chao2.configuration import normalize_settings
from chao2.forest import (ForestNode,ForestWaiting,select_forest_node,is_forest_map,forest_detail,
                         forest_kind,forest_timer,forest_shift,verify_free_forest,forest_points)
from chao2.policy import TaskBlocked,SafetyStop


def options(reserve=0,mode='overflow'):
    result=normalize_settings({})['task_options']['forest']
    result.update(reserve_points=reserve,strategy=mode)
    return result


def node(kind,cost=1,action='explore'):
    return ForestNode(kind,(640,350),action,cost,(640,350))


def test_node_mode_selects_highest_affordable_kind_at_any_balance():
    nodes=[node('spore'),node('beast'),node('unknown')]
    for balance in (1,6,15):assert select_forest_node(nodes,options(mode='node'),balance).kind=='beast'
    assert select_forest_node(nodes,options(5,'node'),5) is None


@pytest.mark.parametrize('reserve',[0,5])
def test_overflow_mode_spends_excess_instantly_and_last_by_priority(reserve):
    nodes=[node('beast'),node('spore'),node('unknown')]
    chosen=[]
    for balance in range(reserve+4,reserve,-1):
        chosen.append(select_forest_node(nodes,options(reserve),balance).kind)
    assert chosen==['spore','spore','spore','beast']
    assert select_forest_node(nodes,options(reserve),reserve) is None


def test_instant_highest_continues_to_reserve():
    opt=options(5);rows=opt['node_priority'];rows.insert(0,rows.pop(2))
    for balance in (8,7,6):assert select_forest_node([node('beast'),node('spore')],opt,balance).kind=='spore'
    assert select_forest_node([node('beast'),node('spore')],opt,5) is None


def test_all_modes_respect_actual_multi_point_cost():
    for mode in ('overflow','node'):
        assert select_forest_node([node('beast',3)],options(5,mode),7) is None
        assert select_forest_node([node('beast',3)],options(5,mode),8).cost==3
    assert select_forest_node([node('beast'),node('spore',3)],options(5),8).kind=='spore'


def test_no_instant_known_never_labels_a_question_instant():
    chosen=select_forest_node([node('unknown'),node('beast')],options(),12)
    assert chosen.kind=='beast'


def test_disabled_types_do_not_execute_and_waiting_allows_only_free_battles():
    opt=options();opt['node_priority'][1]['enabled']=False
    assert select_forest_node([node('beast'),node('unknown')],opt,1).kind=='unknown'
    assert select_forest_node([node('beast',0,'challenge')],opt,0) is None
    assert select_forest_node([node('beast',0,'challenge')],options(),0).action=='challenge'
    assert select_forest_node([node('beast',0,'challenge'),node('spore')],options(),15,True).action=='challenge'
    assert select_forest_node([node('spore')],options(),15,True) is None


def test_actual_map_does_not_accept_dim_modals():
    assert is_forest_map(captured('v085-forest-map',True))
    for name in ('info','collect','beast'):assert not is_forest_map(captured('v085-forest-'+name,True))
    assert forest_detail(captured('v085-forest-beast'))=='幼体凶兽'
    assert forest_timer(captured('v085-forest-timed',True))==1799
    assert forest_timer(captured('v085-forest-map',True)) is None


def test_actual_icons_distinguish_revealed_beasts_from_unknowns():
    s=captured('v085-forest-map',True)
    assert forest_kind(s,(109,165))=='beast'
    assert forest_kind(s,(61,292))=='beast'
    assert forest_kind(s,(394,299))=='unknown'
    assert forest_kind(s,(739,430))=='unknown'
    assert forest_kind(s,(640,350)) is None


def test_actual_panning_measures_clamped_motion():
    east1,east2,east3,top=[captured('v085-forest-'+name,True) for name in ('east1','east2','east3','top1')]
    assert forest_shift(east1,east2)==pytest.approx((-694,0),abs=2)
    assert forest_shift(east2,east3)==pytest.approx((-177,0),abs=2)
    assert forest_shift(east3,top)==pytest.approx((0,398),abs=2)
    assert forest_shift(east3,east3)==pytest.approx((0,0),abs=1)
    assert forest_shift(screen(),screen()) is None


def test_timed_node_checks_free_battles_without_waiting(tmp_path,monkeypatch):
    d=daily(tmp_path);s=captured('v085-forest-timed',True);d.forest_map=lambda:s
    d.options['forest'].update(mode='advanced',collect_resources=False)
    monkeypatch.setattr('chao2.forest.forest_nodes',lambda *_:[])
    d.home=lambda:None;scans=[];d.forest_scan=lambda s:scans.append(s) or s
    d.b.sleep=lambda *_:pytest.fail('Do not wait on exploration')
    message=d.forest()
    assert '不等待或加速' in message and scans and d.report['forest_waiting']['remaining_seconds']==1799
    assert d.report['resource_usage']['forest']['探索点']['remaining']==1


def test_offscreen_timer_from_overview_still_checks_free_battles(tmp_path,monkeypatch):
    d=daily(tmp_path);d.forest_map=lambda:captured('v085-forest-east1',True)
    d.options['forest'].update(mode='advanced',collect_resources=False)
    monkeypatch.setattr('chao2.forest.forest_nodes',lambda *_:[])
    d.forest_overview_state='状态 探索中 探索点 12';d.home=lambda:None
    scans=[];d.forest_scan=lambda s:scans.append(s) or s
    assert '计时探索' in d.forest() and scans


def test_starting_timed_node_confirms_cost_once_then_allows_free_battles(tmp_path):
    import chao2.forest as forest
    d=daily(tmp_path);before=captured('v085-forest-map',True);after=captured('v085-forest-timed',True)
    n=ForestNode('beast',(109,165),'explore',1,(109,165));inputs=[]
    d.forest_pool=[n];d.forest_ignored=[];d.forest_offset=[0.,0.]
    d.b.match_template=lambda *_:True
    d.b.read_number=lambda *_:None
    d.observe=lambda:after if inputs else before
    d.b.click_text=lambda *args:inputs.append(args)
    d.resource_balance('forest','探索点',2)
    assert d.forest_explore(before,n) is after and d.forest_waiting
    assert len(inputs)==1 and d.report['forest_explorations'][0]['status']=='confirmed'
    assert d.report['resource_usage']['forest']['探索点']['spent']==1


def test_node_reserve_is_checked_again_before_input(tmp_path):
    d=daily(tmp_path);d.options['forest']['reserve_points']=2
    d.b.click_text=lambda *_:pytest.fail('Must retain points')
    with pytest.raises(Exception,match='保留'):d.forest_explore(captured('v085-forest-map',True),node('beast'))


def test_free_beast_button_requires_identity_no_fee_and_template(tmp_path):
    d=daily(tmp_path);s=captured('v085-forest-beast');d.b.match_template=lambda *_:True
    verify_free_forest(d.b,s,'幼体凶兽')
    with pytest.raises(TaskBlocked):verify_free_forest(d.b,s,'幻化凶兽')
    s.words+=screen(('25钻石',1040,645,80,20)).words
    with pytest.raises(SafetyStop):verify_free_forest(d.b,s,'幼体凶兽')
