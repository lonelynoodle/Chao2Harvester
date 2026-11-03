"""任务挑战兜底入口与黑暗森林普通模式。

The world-map HUD labels (世界 / 黑暗森林 / 永生之茧) are the least reliable
evidence in the game. Every task that can be reached from the 玩法概览 card
list must retry there instead of failing, and the forest keeps a simplified
mode that never depends on map registration or node-type recognition.
"""
import pytest

from test_configuration import daily,screen
from chao2.forest import ForestNode,ForestWaiting,pick_simple_forest_node
from chao2.overview import forest_overview_busy
from chao2.policy import TaskBlocked


def test_overview_busy_reads_the_card_status_column():
    for text in ('状态 探索中','正在探索','01:23:45','剩余 00:05:00'):
        assert forest_overview_busy(text) is True
    for text in ('空闲中','',None,'状态 空闲'):
        assert forest_overview_busy(text) is False


@pytest.mark.parametrize('status,should_enter',[('探索中',False),('空闲中',True)])
def test_forest_overview_status_controls_entry_before_click(tmp_path,status,should_enter):
    d=daily(tmp_path)
    panel=screen(('玩法概览',50,440,110,30),('每日挑战',60,520,110,30),
                 ('黑暗森林',370,200,105,30),(status,555,204,85,28))
    destination=screen(('黑暗森林',120,12,95,28),('信息',1200,80,50,25))
    d.task_panel=lambda:panel;d.observe=lambda:destination
    d.b.sleep=lambda *_:None;d.b.guard=lambda *_:None
    d.resolve_path_event=lambda q:None
    clicks=[];d.b.click_at=lambda *a:clicks.append(a)
    result=d.enter_overview('^黑暗森林$',skip_when=forest_overview_busy)
    assert (result is destination)==should_enter
    assert len(clicks)==int(should_enter)


def test_simple_pick_prefers_free_beasts_then_the_cheapest_visible_node():
    free=ForestNode('beast',(700,300),'challenge',0)
    cheap=ForestNode('spore',(300,300),'explore',1)
    pricey=ForestNode('divinity',(500,300),'explore',3)
    assert pick_simple_forest_node([pricey,cheap,free],9,0) is free
    assert pick_simple_forest_node([pricey,cheap],9,0) is cheap
    # A page with no affordable target asks the caller to pan onward.
    assert pick_simple_forest_node([pricey],2,0) is None
    # The reserve is a floor, not a target.
    assert pick_simple_forest_node([cheap],1,1) is None


def test_simple_pick_never_returns_an_already_clicked_node():
    node=ForestNode('spore',(300,300),'explore',1)
    assert pick_simple_forest_node([node],5,0) is node
    assert pick_simple_forest_node([node],5,0,[(300,300)]) is None


def test_simple_mode_clears_current_page_before_panning_without_global_registration(tmp_path,monkeypatch):
    import chao2.forest as module
    d=daily(tmp_path);s=screen()
    d.forest_map=lambda:s;d.home=lambda:None
    d.options['forest']['collect_resources']=False
    d.options['forest']['mode']='simple'
    d.options['forest']['collect_resources']=False
    nodes=[ForestNode('spore',(300,300),'explore',1)]
    monkeypatch.setattr(module,'forest_nodes',lambda *a:list(nodes))
    monkeypatch.setattr(module,'forest_points',lambda *a:4)
    explored=[]
    def explore(view,node):
        explored.append(node)
        nodes.remove(node)          # An explored node leaves the map.
        d.report.setdefault('forest_explorations',[]).append({'status':'confirmed'})
        return view
    d.forest_explore=explore
    pans=[]
    d.forest_simple_pan=lambda view,dx,dy:(pans.append((len(explored),dx,dy)) or view,False)
    def forbidden(*_a,**_k):pytest.fail('普通模式不得扫描地图或测量平移')
    d.forest_scan=forbidden;d.forest_reach=forbidden
    summary=d.forest()
    assert [n.kind for n in explored]==['spore']
    assert '森林探索1个节点' in summary
    assert pans and all(count==1 for count,_,_ in pans)
    assert '未找到可探索节点' in summary


def test_simple_mode_scans_for_free_battles_without_waiting_on_exploration(tmp_path):
    from test_configuration import captured
    d=daily(tmp_path)
    d.forest_map=lambda:captured('v085-forest-timed',True)
    d.home=lambda:None
    d.options['forest'].update(mode='simple',collect_resources=False)
    d.b.sleep=lambda *_:pytest.fail('普通模式遇到计时探索不得等待')
    pans=[];d.forest_simple_pan=lambda s,dx,dy:pans.append((dx,dy)) or (s,False)
    summary=d.forest()
    assert '不等待或加速' in summary and pans and d.report['forest_waiting']['remaining_seconds']==1799


def test_forest_map_enters_even_when_the_overview_reports_exploring(tmp_path):
    d=daily(tmp_path)
    d.observe=lambda:screen();d.b.guard=lambda *_:None
    clicks=[];d.b.click_at=lambda *a,**k:clicks.append(a)
    kwargs=[];d.enter_overview=lambda *a,**k:kwargs.append(k)
    destination=screen();d.forest_wait_map=lambda:destination
    d.forest_overview_state='状态 探索中'
    assert d.forest_map() is destination and kwargs==[{}]


def test_overview_entry_rejects_tasks_without_a_card():
    # 起源殿 is not in the 玩法概览 list, so the fallback must say so instead
    # of scrolling the whole list and failing later.
    import chao2.overview as overview
    assert 'origin' not in overview.OVERVIEW_ROUTES
    assert overview.OVERVIEW_ROUTES['tower'][0]=='^浮空巨塔$'
    assert overview.OVERVIEW_ROUTES['nest'][0]=='^[谜迷]之巢穴$'
    assert overview.OVERVIEW_ROUTES['forest'][0]=='^黑暗森林$'


def test_tower_selector_falls_back_to_task_challenge(tmp_path):
    d=daily(tmp_path)
    def no_territory():raise TaskBlocked('未识别领地')
    d.territory=no_territory
    seen=[]
    def overview_entry(key,reason=''):
        seen.append(key);return screen(('选择挑战的塔',100,100,80,20))
    d.overview_entry=overview_entry
    s=d.tower_selection()
    assert seen==['tower'] and s.find('选择挑战的塔')


def test_nest_falls_back_to_task_challenge_when_the_map_entry_fails(tmp_path):
    d=daily(tmp_path)
    def no_territory():raise TaskBlocked('未识别领地')
    d.territory=no_territory
    seen=[]
    d.overview_entry=lambda key,reason='': seen.append(key) or screen(('暴走旷野',100,100,80,20))
    d.await_page=lambda pattern,*a:screen(('暴走旷野',100,100,80,20))
    s=d.enter_building('谜之巢穴','^暴走旷野$')
    assert seen==['nest'] and s.find('^暴走旷野$')


def test_arena_entry_falls_back_too_but_unknown_buildings_still_raise(tmp_path):
    d=daily(tmp_path)
    def no_territory():raise TaskBlocked('未识别领地')
    d.territory=no_territory
    seen=[]
    d.overview_entry=lambda key,reason='': seen.append(key) or screen(('斗技场挑战',100,100,80,20))
    d.await_page=lambda pattern,*a:screen(('斗技场挑战',100,100,80,20))
    d.enter_building('斗技场','^挑战次数$')
    assert seen==['arena']
    # 起源殿 has no overview card; the original failure must surface unchanged.
    with pytest.raises(TaskBlocked,match='未识别领地'):
        d.enter_building('起源殿','^匹配$')
