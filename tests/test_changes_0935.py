"""Copied lineup, opportunistic forest traversal and grouped Fengye tasks."""
import pytest
from test_configuration import captured,daily,screen
from chao2.activities import BudgetReached
from chao2.configuration import normalize_settings
from chao2.forest import ForestNode,ForestWaiting,pick_simple_forest_node
from chao2.policy import TaskBlocked,SafetyStop
from chao2.team_copy import source_lineup,copied_lineup


def test_copied_lineup_accepts_actual_91767_failure_frame_and_rejects_other_team():
    source=captured('v0935-team-copy-source',True)
    target=captured('v0935-tribe-copied',True)
    lineup=source_lineup(source.image,source.find('^队伍1$').center[1])
    assert copied_lineup(lineup,target.image)['verified']
    assert not copied_lineup(lineup,captured('tribe-copied-formation',True).image)['verified']
    wrong=target.image.copy();wrong[70:300,230:510]=0
    evidence=copied_lineup(lineup,wrong)
    assert evidence['matched_monsters']==5 and evidence['verified']


def test_actual_lineup_continues_when_destination_power_is_unreadable(tmp_path):
    d=daily(tmp_path);d.active_task='tribe'
    source=captured('v0935-team-copy-source',True);target=captured('v0935-tribe-copied',True)
    target.words=[w for w in target.words if w.text!='9I767']
    frames=iter([source,source,target]);d.observe=lambda:next(frames)
    d.b.read_text_crop=lambda *_:'';d.b.sleep=lambda _:None
    clicks=[];d.b.click_text=lambda *args,**kw:clicks.append('copy')
    d.b.click_at=lambda *args,**kw:clicks.append('copy') if args[3].startswith('复制保存的') else None
    assert d.apply_saved_team(captured('tribe-formation'),1) is target
    check=d.report['team_copy_checks'][0]
    assert check['status']=='verified' and check['actual_power'] is None
    assert check['expected_power']==91767 and clicks==['copy']


def setup_simple(d,monkeypatch):
    import chao2.forest as f
    view=screen();balance=[4]
    d.options['forest'].update(mode='simple',collect_resources=False)
    d.forest_map=lambda:view;d.home=lambda:None;d.forest_record_view=lambda _:None
    monkeypatch.setattr(f,'forest_points',lambda *args:balance[0])
    return f,view,balance


def test_simple_mode_prefers_an_instant_node_over_cheaper_unknown():
    instant=ForestNode('spore',(600,350),'explore',3)
    waiting=ForestNode('unknown',(400,350),'explore',1)
    assert pick_simple_forest_node([waiting,instant],4,0) is instant


def test_simple_mode_pans_to_first_actionable_page_and_uses_all_points(tmp_path,monkeypatch):
    d=daily(tmp_path);f,empty,balance=setup_simple(d,monkeypatch);visible=screen()
    node=ForestNode('spore',(500,300),'explore',1)
    monkeypatch.setattr(f,'forest_nodes',lambda b,s:[node] if s is visible and balance[0]>0 else [])
    pans=[];d.forest_simple_pan=lambda s,dx,dy:(pans.append((dx,dy)) or visible,balance[0]>0)
    def explore(s,n):
        balance[0]-=1
        d.report.setdefault('forest_explorations',[]).append({'status':'confirmed'})
        # Newly unlocked nodes need different coordinates on this page.
        node.point=(node.point[0]+45,node.point[1])
        return s
    d.forest_explore=explore
    # Newly unlocked nodes must not inherit the previously clicked coordinate.
    def nodes(b,s):
        return [ForestNode('spore',(500+(4-balance[0])*45,300),'explore',1)] if s is visible and balance[0]>0 else []
    monkeypatch.setattr(f,'forest_nodes',nodes)
    summary=d.forest()
    assert balance[0]==0 and len(pans)>1 and '探索4个节点' in summary


def test_simple_mode_reenters_after_stall_and_reconciles_delayed_exploration(tmp_path,monkeypatch):
    d=daily(tmp_path);f,view,balance=setup_simple(d,monkeypatch)
    d.report['forest_explorations']=[{'status':'started','before':5,'cost':1}]
    d.forest_simple_reenter(TaskBlocked('探索结果未确认'))
    row=d.report['forest_explorations'][0]
    assert row['status']=='confirmed' and row['confirmation']=='reentry_points'
    assert d.report['resource_usage']['forest']['探索点']['spent']==1


def test_simple_mode_recovery_is_bounded_and_never_uses_reset(tmp_path,monkeypatch):
    d=daily(tmp_path);f,view,balance=setup_simple(d,monkeypatch)
    monkeypatch.setattr(f,'forest_nodes',lambda *_:[ForestNode('spore',(500,300),'explore',1)])
    d.forest_explore=lambda *_:(_ for _ in ()).throw(TaskBlocked('节点未响应'))
    with pytest.raises(TaskBlocked,match='3次'):d.forest()
    assert len(d.report['forest_simple_recoveries'])==3
    assert all(row['status']=='reentered' for row in d.report['forest_simple_recoveries'])


def test_celebration_default_runs_only_triad_and_restores_parent_task(tmp_path):
    d=daily(tmp_path);calls=[]
    d.triad=lambda:calls.append('triad') or '三阵已完成'
    d.giant=lambda:pytest.fail('巨物默认关闭')
    d.home=lambda:calls.append('home')
    old=d.options
    assert d.celebration()=='三阵已完成'
    assert calls==['triad','home'] and d.options is old and d.active_task=='celebration'


def test_celebration_skips_ended_giant_and_collects_per_activity_feedback(tmp_path):
    d=daily(tmp_path);d.options['celebration'].update(triad=False,giant=True)
    d.giant=lambda:(_ for _ in ()).throw(BudgetReached('进击巨物活动已结束，已跳过'))
    d.home=lambda:None
    assert '已结束' in d.celebration()
    assert d.report['celebration_tasks']['celebration']['giant']['status']=='skipped'


def test_celebration_migration_consolidates_legacy_slots_without_duplicate_execution():
    saved={'tasks':['giant','triad','other'],'task_order':['giant','main','triad','other'],
           'task_options':{'other':{'daily_puzzle':True}},'task_queue':[
               {'id':k,'key':k,'name':k,'enabled':True,'options':{}} for k in ('giant','main','triad','other')]}
    new=normalize_settings(saved)
    assert new['task_order']==['celebration','main','other']
    assert [r['key'] for r in new['task_queue']]==['celebration','main','other']
    new['task_options']['celebration'].update(triad=False,giant=True)
    again=normalize_settings(new)
    assert again['task_options']['celebration']['giant'] and not again['task_options']['celebration']['triad']
