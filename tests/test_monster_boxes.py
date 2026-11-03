from copy import deepcopy
from collections import Counter
from types import SimpleNamespace
import pytest
from chao2.configuration import normalize_settings
from chao2.monster_boxes import (is_monster_box_item,monster_box_stock,monster_choice_name,
    monster_carousel_points,is_monster_box_result,next_box_monster)
from chao2.monster_box_settings import MONSTER_BOX_NAMES
from chao2.policy import SafetyStop,TaskBlocked
from test_configuration import daily,captured,screen


def test_live_pages_separate_inventory_chooser_detail_and_actual_reward():
    item=captured('v0917-box-item',True);selected=captured('v0917-box-selected',True)
    assert is_monster_box_item(item) and monster_box_stock(item)==4
    assert monster_box_stock(captured('v0917-box-after',True))==3
    assert monster_choice_name(selected)=='停顿' and not is_monster_box_item(selected)
    assert not is_monster_box_result(selected,'停顿')
    assert is_monster_box_result(captured('v0917-box-result',True),'行尸')
    assert not is_monster_box_result(captured('v0917-box-result',True),'暴龙')
    for name,first in [('v0917-box-left',169),('v0917-box-right',99)]:
        points=monster_carousel_points(captured(name,True))
        assert len(points)==4 and abs(points[0][0]-first)<4
    assert not monster_carousel_points(selected) and not monster_carousel_points(item)
    # An unrelated blue object, including potions and high-grade chests, cannot
    # be spent just because its icon is blue or its detail has a Use button.
    item.words=[w for w in item.words if w.text!='幻化怪兽茧']
    assert not is_monster_box_item(item) and monster_box_stock(item) is None


def test_modes_are_configurable_opt_in_and_survive_normalization():
    opts=normalize_settings({})['task_options']['other']
    assert not opts['open_monster_boxes'] and opts['monster_box_limit']==0
    for mode in ('specified','balanced','random'):
        opts.update(open_monster_boxes=True,monster_box_mode=mode,monster_box_target='停顿',monster_box_limit=2)
        assert normalize_settings({'task_options':{'other':opts}})['task_options']['other']==opts
    for bad in ({'monster_box_target':'不朽怪兽'},{'monster_box_mode':'all'},{'monster_box_limit':-1},{'monster_box_limit':1.5}):
        with pytest.raises(ValueError):normalize_settings({'task_options':{'other':bad}})


def test_even_distribution_remembers_previous_openings_and_random_uses_valid_pool():
    counts=Counter({'暴龙':3,'行尸':1});opts={'monster_box_mode':'balanced'}
    for _ in range(29):counts[next_box_monster(opts,counts)]+=1
    assert set(counts)==set(MONSTER_BOX_NAMES) and max(counts.values())-min(counts.values())<=1
    assert next_box_monster({'monster_box_mode':'specified','monster_box_target':'虚刃'},counts)=='虚刃'
    pools=[]
    assert next_box_monster({'monster_box_mode':'random'},counts,lambda xs:pools.append(xs) or xs[-1])=='停顿'
    assert pools==[MONSTER_BOX_NAMES]


def flow(tmp_path):
    d=daily(tmp_path,{'task_options':{'other':{'open_monster_boxes':True}}})
    d.state['monster_box_opened_counts']={}
    item=captured('v0917-box-item',True);carousel=captured('v0917-box-carousel',True)
    selected=captured('v0917-box-selected',True)
    for w in selected.words:
        if w.text=='停顿':w.text='行尸'
    reward=captured('v0917-box-result',True);after=captured('v0917-box-after',True)
    state=[item];clicks=[];d.observe=lambda:state[0];d.b.sleep=lambda _:None
    def text(s,p,**kw):clicks.append(p);state[0]=carousel
    def choose(s,name):state[0]=selected;return selected
    def click(s,p,anchors,reason):
        assert s.has(*anchors);clicks.append(reason)
        state[0]=reward if reason.startswith('开启1个') else after
    d.b.click_text=text;d.select_monster_box_target=choose;d.b.click_at=click
    return d,item,state,clicks


def test_one_box_confirms_reward_and_stock_before_advancing_even_distribution(tmp_path):
    d,item,state,clicks=flow(tmp_path)
    result,remaining=d.open_one_monster_box(item,'行尸','specified')
    assert remaining==3 and result is state[0]
    assert sum(x.startswith('开启1个') for x in clicks)==1
    assert d.report['monster_boxes'][0]['status']=='confirmed'
    assert d.state['monster_box_opened_counts']['行尸']==1


def test_wrong_monster_selection_stops_before_spending(tmp_path):
    d,item,state,clicks=flow(tmp_path)
    d.select_monster_box_target=lambda *a:captured('v0917-box-selected',True)
    with pytest.raises(SafetyStop,match='名称不符'):d.open_one_monster_box(item,'行尸','specified')
    assert clicks==['^使用$'] and not d.report.get('monster_boxes')


def test_inventory_full_does_not_open_or_navigate_to_chooser(tmp_path):
    d,item,state,clicks=flow(tmp_path)
    next(w for w in item.words if w.text=='170/800').text='800/800'
    with pytest.raises(TaskBlocked,match='背包已满'):d.open_one_monster_box(item,'行尸','specified')
    assert not clicks


def test_uncertain_spending_result_is_not_retried_or_reported_as_success(tmp_path):
    d,item,state,clicks=flow(tmp_path);original=d.wait_for_screen
    def wait(predicate,label,**kwargs):
        if label=='幻化怪兽茧库存减少1':raise TaskBlocked('库存仍为4')
        return original(predicate,label,**kwargs)
    d.wait_for_screen=wait
    with pytest.raises(SafetyStop,match='未完整核实'):d.open_one_monster_box(item,'行尸','balanced')
    assert sum(x.startswith('开启1个') for x in clicks)==1
    assert d.report['monster_boxes'][0]['status']=='reward_seen'
    assert not d.state.get('monster_box_opened_counts')


def test_last_box_waits_for_delayed_stock_update_then_verifies_absence(tmp_path):
    d,item,state,clicks=flow(tmp_path)
    next(w for w in item.words if w.text=='已拥有4').text='已拥有1'
    empty=captured('v0917-box-after',True)
    next(w for w in empty.words if w.text=='已拥有3').text='已拥有0'
    original=d.wait_for_screen;checked=[]
    def wait(predicate,label,**kwargs):
        if label=='最后一个幻化怪兽茧库存更新':
            assert not predicate(item) and predicate(empty)
            state[0]=empty;checked.append(label)
        return original(predicate,label,**kwargs)
    d.wait_for_screen=wait;d.monster_box_inventory=lambda:None
    result,remaining=d.open_one_monster_box(item,'行尸','random')
    assert result is None and remaining==0 and len(checked)==1
    assert sum(x.startswith('开启1个') for x in clicks)==1


def test_quantity_limit_and_remaining_are_reported(tmp_path):
    d=daily(tmp_path,{'task_options':{'other':{'open_monster_boxes':True,'monster_box_limit':2}}})
    d.state['monster_box_opened_counts']={}
    item=captured('v0917-box-item',True);d.monster_box_inventory=lambda:item;calls=[]
    def open_one(s,name,mode):
        calls.append(name);d.state.setdefault('monster_box_opened_counts',{})[name]=1
        return item,4-len(calls)
    d.open_one_monster_box=open_one
    result=d.open_monster_boxes()
    assert calls==['暴龙','轰龙'] and result['opened']==2 and result['remaining']==2
    assert '已达到设置上限' in result['message']


def test_absent_box_and_disabled_feature_never_try_another_blue_item(tmp_path):
    d=daily(tmp_path)
    d.monster_box_inventory=lambda:pytest.fail('Disabled')
    with pytest.raises(SafetyStop):d.open_monster_boxes()
    d.options['other']['open_monster_boxes']=True;d.monster_box_inventory=lambda:None
    assert d.open_monster_boxes()['opened']==0


def test_box_subtask_runs_before_bag_red_dot_cleanup(tmp_path):
    d=daily(tmp_path,{'task_options':{'other':{'friend_management':False,'collect_contract':False,'daily_puzzle':False,'open_monster_boxes':True,'collect_daily_single':False,'collect_plane_lord':False,'buy_star_spores':False}}})
    order=[];d.home=lambda:None
    d.open_monster_boxes=lambda:order.append('box') or {'message':'opened'}
    d.clear_bag_notifications=lambda:order.append('bag') or {'message':'cleared'}
    d.other();assert order==['box','bag']
