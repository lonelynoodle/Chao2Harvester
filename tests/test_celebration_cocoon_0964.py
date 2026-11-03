"""World OCR regression and resource-driven cocoon/global limit migration."""
from copy import deepcopy
import pytest
from chao2.configuration import normalize_settings
from chao2.cocoon_settings import migrate_resource_limits,cocoon_reserve
from chao2.policy import TaskBlocked
from chao2.workflows import is_world
from test_configuration import daily,captured,screen
from test_rift_node_0961 import backend


def test_actual_maa_recovers_world_that_blocked_celebration(tmp_path,backend):
    d=daily(tmp_path);d.b.tasker=backend.tasker
    s=captured('v0964-world-celebration',True)
    assert not is_world(s) and s.find('^任务挑战-$')
    recovered=d.recover_world_navigation(s)
    assert is_world(recovered) and recovered.when==s.when
    assert len(recovered.words)>len(s.words)
    assert '局部识别确认' in d.report['events'][-1]['message']


@pytest.mark.parametrize('kind',['empty','overlay'])
def test_navigation_recovery_does_not_turn_unknown_or_overlay_into_world(tmp_path,kind):
    from chao2.backend import Word
    d=daily(tmp_path);s=screen() if kind=='empty' else captured('v0964-world-celebration',True)
    if kind=='overlay':
        s.words.extend([Word(t,[440,260+i*60,300,30],.99) for i,t in enumerate(('是否确认退出游戏','再玩一会','退出游戏'))])
    d.b.read_text_crop=lambda *a:pytest.fail('No OCR recovery on an unconfirmed map')
    assert d.recover_world_navigation(s) is s and not is_world(s)


def test_old_global_cap_does_not_stop_daily_after_fifty_attempts(tmp_path):
    d=daily(tmp_path,{'max_battles':50})
    d.battles=51;d.task_counts['cocoon']=51
    d.check_budget('cocoon')
    assert 'max_battles' not in d.b.settings


def test_limits_migrate_recursively_without_changing_choices_or_tool_limits():
    options={'teams':[2,1],'max_runs':3,'reserve_spikes':4,
        'targets':[{'id':'spore','enabled':True,'limit':5},{'id':'gold','enabled':False,'limit':2}]}
    snapshot={'max_battles':50,'tasks':['cocoon','main'],'task_options':{
        'cocoon':deepcopy(options),'main':{'max_runs':9}},'task_queue':[
        {'id':'cocoon_2','key':'cocoon','enabled':True,'options':deepcopy(options)}]}
    settings=deepcopy(snapshot);settings['task_templates']=[{'id':'keep','name':'保存模板','settings':deepcopy(snapshot)}]
    settings['tour_options']={'max_battles':25}
    migrate_resource_limits(settings)
    for item in (settings,settings['task_templates'][0]['settings']):
        assert 'max_battles' not in item and item['tasks']==snapshot['tasks']
        assert item['task_options']['main']=={'max_runs':9}
        for opts in (item['task_options']['cocoon'],item['task_queue'][0]['options']):
            assert 'max_runs' not in opts and opts['teams']==[2,1]
            assert opts['reserve_spikes_enabled'] is True and cocoon_reserve(opts)==4
            assert [(r['id'],r['enabled']) for r in opts['targets']]==[('spore',True),('gold',False)]
            assert all('limit' not in r for r in opts['targets'])
    assert settings['tour_options']=={'max_battles':25}
    once=deepcopy(settings);migrate_resource_limits(settings);assert settings==once


@pytest.mark.parametrize('value,enabled,effective',[(0,False,0),(4,True,4)])
def test_legacy_preserve_value_becomes_checkbox(value,enabled,effective):
    options=normalize_settings({'task_options':{'cocoon':{'reserve_spikes':value}}})['task_options']['cocoon']
    assert options['reserve_spikes_enabled'] is enabled and cocoon_reserve(options)==effective
    assert 'max_runs' not in options


def test_celebration_retries_child_navigation_and_does_not_replay_completed_children(tmp_path):
    d=daily(tmp_path,{'task_options':{'celebration':{'triad':True,'giant':True,'daily_puzzle':False}}})
    d.active_task='celebration';attempts=[];returns=[]
    def triad():
        attempts.append('triad')
        if len(attempts)==1:raise TaskBlocked('页面未识别')
        d.task_counts['triad']=1
        return '三阵已完成'
    d.triad=triad;d.giant=lambda:pytest.fail('Already completed giant must not replay')
    d.can_recover_page=lambda error:True;d.home=lambda:returns.append('home')
    d.report['celebration_tasks']={'celebration':{'giant':{'status':'done','message':'巨物已完成'}}}
    summary=d.celebration()
    assert attempts==['triad','triad'] and '三阵已完成' in summary
    assert len(d.report['page_recoveries'])==1 and d.task_counts['celebration']==1
    d.celebration();assert len(attempts)==2


def test_cocoon_retry_state_is_independent_for_each_queue_instance(tmp_path):
    d=daily(tmp_path)
    first={'id':'first','key':'cocoon','options':deepcopy(d.options['cocoon'])}
    second={**first,'id':'second'}
    with d.task_instance(first):
        d.report['cocoon_counts']={'gold':7};d.report['cocoon_failed']=['spore'];d.report['cocoon_refreshes']=2
    with d.task_instance(second):
        assert not d.report.get('cocoon_counts') and not d.report.get('cocoon_failed')
        d.report['cocoon_counts']={'gold':1}
    with d.task_instance(first):
        assert d.report['cocoon_counts']=={'gold':7} and d.report['cocoon_failed']==['spore']
        assert d.report['cocoon_refreshes']==2
