"""Replay of the 2026-10-21 15:xx run: full-frame OCR dropped the golden
永生之茧 map label, so the tower entrance silently stopped clicking and the
nest entrance failed its anchor check; the forest gave up on an unreachable
boundary node instead of trying the next one."""
import pytest

from test_configuration import daily,screen
from chao2.backend import Backend
from chao2.forest import ForestNode
from chao2.policy import TaskBlocked


def test_confirm_label_is_a_safe_no_op_without_a_tasker():
    b=Backend({},log=lambda _:None)
    s=screen(('世界',1206,671,52,30))
    assert b.confirm_label(s,'^永生之茧$',(780,140,210,170)) is False
    assert len(s.words)==1


def test_tower_territory_keeps_requiring_all_anchors_without_reocr(tmp_path):
    d=daily(tmp_path)
    good=screen(('世界',1206,671,52,30),('黑暗森林',850,479,71,18),('永生之茧',872,212,63,17))
    assert d.tower_territory(good) is True
    missing=screen(('世界',1206,671,52,30),('黑暗森林',850,479,71,18))
    assert d.tower_territory(missing) is False
    wordless=screen(('黑暗森林',850,479,71,18))
    assert d.tower_territory(wordless) is False


def test_forest_skips_unreachable_node_and_tries_the_next(tmp_path,monkeypatch):
    import chao2.forest as module
    d=daily(tmp_path);s=screen()
    d.forest_map=lambda:s;d.forest_scan=lambda _:s;d.forest_wait_map=lambda:s
    d.home=lambda:None
    d.options['forest']['collect_resources']=False
    d.options['forest']['mode']='advanced'
    unreachable=ForestNode('lamp',(100,100),'explore',1,(100,100))
    reachable=ForestNode('spore',(200,200),'explore',1,(200,200))
    targets=iter([unreachable,reachable])
    monkeypatch.setattr(module,'forest_points',lambda *a:9)
    monkeypatch.setattr(module,'forest_nodes',lambda *a:[])
    monkeypatch.setattr(module,'select_forest_node',lambda pool,opt,bal,**kw:next(targets,None))
    def reach(s,t):
        if t.kind=='lamp':raise TaskBlocked('森林目标未进入可操作范围')
        return s,t
    d.forest_reach=reach
    explored=[]
    def explore(s,t):
        explored.append(t)
        d.report.setdefault('forest_explorations',[]).append({'status':'confirmed'})
        return s
    d.forest_explore=explore
    summary=d.forest()
    assert [t.kind for t in explored]==['spore']
    assert len(d.report['forest_skipped'])==1
    assert d.report['forest_skipped'][0]['kind']=='lamp'
    assert unreachable.world in d.forest_ignored
    assert '森林探索1个节点' in summary


def test_forest_still_stops_on_map_or_input_failures(tmp_path,monkeypatch):
    import chao2.forest as module
    d=daily(tmp_path);s=screen()
    d.forest_map=lambda:s;d.forest_scan=lambda _:s;d.home=lambda:None
    d.options['forest']['collect_resources']=False
    d.options['forest']['mode']='advanced'
    targets=iter([ForestNode('lamp',(100,100),'explore',1,(100,100))])
    monkeypatch.setattr(module,'forest_points',lambda *a:9)
    monkeypatch.setattr(module,'forest_nodes',lambda *a:[])
    monkeypatch.setattr(module,'select_forest_node',lambda pool,opt,bal,**kw:next(targets,None))
    def reach(s,t):raise TaskBlocked('森林地图滑动失败，已重试3次：adb 失败')
    d.forest_reach=reach
    with pytest.raises(TaskBlocked,match='滑动失败'):
        d.forest()
    assert not d.report.get('forest_skipped')
