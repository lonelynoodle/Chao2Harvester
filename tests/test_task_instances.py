"""Repeated queue entries execute independently, including resource refills."""
import threading
import pytest
from test_configuration import daily,captured
from chao2.configuration import normalize_settings
from chao2.task_queue import execution_entries
from chao2.workflows import ORDER


def row(ident,key='main',**options):
    return {'id':ident,'key':key,'name':ident,'enabled':True,'options':options}


def test_repeat_switch_keeps_topmost_even_if_it_is_unchecked():
    first=row('main_first');first['enabled']=False
    raw={'task_queue':[first,row('main_second')]}
    assert [r['id'] for r in normalize_settings(raw)['task_queue']]==['main_first']
    assert execution_entries(normalize_settings(raw),['main'],ORDER)==[]
    raw['allow_repeat_tasks']=True
    assert [r['id'] for r in execution_entries(normalize_settings(raw),['main'],ORDER)]==['main_second']


def test_instance_options_are_normalized_independently_and_validate_before_connect():
    settings=normalize_settings({'allow_repeat_tasks':True,'task_queue':[row('a',teams=[1],max_runs=1),row('b',teams=[3],max_runs=2)]})
    a,b=settings['task_queue']
    assert a['options']['teams']==[1] and b['options']['teams']==[3]
    a['options']['teams'].append(2)
    assert b['options']['teams']==[3]
    for queue in ([row('same'),row('same')],[row('../bad')],[row('x',auto_potions='yes')]):
        with pytest.raises(ValueError):normalize_settings({'allow_repeat_tasks':True,'task_queue':queue})


def test_repeated_tasks_have_separate_budgets_reports_and_options(tmp_path):
    d=daily(tmp_path,{'allow_repeat_tasks':True,'task_queue':[row('main_a',teams=[1],max_runs=1),row('main_b',teams=[3],max_runs=2)]})
    seen=[];d.b.guard=lambda s:None
    def run():
        opt=d.options['main'];seen.append(opt['teams'])
        start=d.task_counts.get('main',0)
        for i in range(opt['max_runs']-start):
            d.check_budget('main');d.battles+=1
            d.task_counts['main']=d.task_counts.get('main',0)+1
            d.resource_balance('main','地图体力',100-5*(d.battles-1))
            d.resource_spent('main','地图体力',5,100-5*d.battles)
            d.report.setdefault('team_attempts',[]).append({'task':'main','team':opt['teams'][0],'outcome':'victory'})
        return '已执行所选次数'
    d.main=run
    entries=d.b.settings['task_queue']
    for entry in entries:d.execute_entry(entry)
    assert seen==[[1],[3]] and d.task_counts['main']==3
    assert d.report['execution_order']==['main_a','main_b']
    assert d.report['tasks']['main_a']['attempts']==d.report['tasks']['main_a']['victories']==1
    assert d.report['tasks']['main_b']['attempts']==d.report['tasks']['main_b']['victories']==2
    assert '消耗5' in d.report['tasks']['main_a']['summary'] and '消耗10' in d.report['tasks']['main_b']['summary']
    assert d.report['resource_usage']['main']['地图体力']['spent']==15
    d.execute_entry(entries[0])
    assert d.task_counts['main']==3 and d.report['resource_usage']['main']['地图体力']['spent']==15


def test_run_daily_emits_each_instance_in_queue_order(tmp_path,monkeypatch):
    import chao2.workflows as workflows
    report={'folder':tmp_path,'tasks':{},'events':[]};events=[];seen=[]
    monkeypatch.setattr(workflows,'create_report',lambda:report)
    monkeypatch.setattr(workflows.Backend,'connect',lambda s:None)
    monkeypatch.setattr(workflows.Daily,'home',lambda *a,**k:captured('v0913-main-world',True))
    monkeypatch.setattr(workflows.Daily,'maybe_capture_wild',lambda d,s:s)
    monkeypatch.setattr(workflows.Daily,'maybe_free_summon',lambda d,s:s)
    monkeypatch.setattr(workflows.Daily,'restore_world_team',lambda d:None)
    monkeypatch.setattr(workflows.Daily,'save_state',lambda d:None)
    def tower(d):seen.append(d.options['tower']['reserve_feathers']);return '本次无羽毛'
    monkeypatch.setattr(workflows.Daily,'tower',tower)
    settings={'close_mumu':False,'allow_repeat_tasks':True,'task_queue':[row('tower_second','tower',reserve_feathers=5),row('tower_first','tower',reserve_feathers=1)]}
    result=workflows.run_daily(settings,['tower'],threading.Event(),log=lambda _:None,emit=lambda *a:events.append(a))
    assert result['status']=='completed' and seen==[5,1]
    assert [r[1][0] for r in events if r[0]=='task' and r[1][1]=='运行中']==['tower_second','tower_first']
    assert set(result['tasks'])=={'tower_second','tower_first'}


def test_queue_refill_uses_each_instances_own_permission_and_log_group(tmp_path):
    d=daily(tmp_path,{'allow_repeat_tasks':True,'task_queue':[row('a',auto_three_shots=False,auto_potions=False),row('b',auto_three_shots=True,auto_potions=False),row('c','hunt',auto_three_shots=False,auto_potions=True)]})
    seen=[]
    def refill():
        key=d.selected[0];seen.append((d.report_key(key),d.options[key]['auto_three_shots'],d.options[key]['auto_potions']))
        return 'checked'
    d.selected=['main','hunt'];d.replenish_stamina=refill
    d.replenish_queue_stamina(d.b.settings['task_queue'])
    assert seen==[('c',False,True),('b',True,False)] and d.selected==['main','hunt']


def test_repeated_hunt_search_and_main_failure_limits_are_isolated(tmp_path):
    d=daily(tmp_path,{'allow_repeat_tasks':True,'task_queue':[row('a'),row('b')]})
    a,b=d.b.settings['task_queue']
    with d.task_instance(a):
        d.report['main_examined']=20;d.report['main_failed']=['123']
        d.search_counts['hunt']=1;d.stamina_retry['main']=False
        d.report['forest_explorations']=[{'node':'first'}]
        assert len(d.instance_rows('forest_explorations'))==1
    with d.task_instance(b):
        assert d.report.get('main_examined',0)==0 and not d.report.get('main_failed')
        assert d.search_counts.get('hunt',0)==0 and d.stamina_retry.get('main',True)
        assert not d.instance_rows('forest_explorations')
        d.search_counts['hunt']=2
    with d.task_instance(a):
        assert d.report['main_examined']==20 and d.report['main_failed']==['123']
        assert d.search_counts['hunt']==1 and not d.stamina_retry['main']
        assert len(d.instance_rows('forest_explorations'))==1
    assert d.search_counts['hunt']==3
