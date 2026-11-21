"""Resume a particular queue instance, including duplicates, without game input."""
from copy import deepcopy

import pytest

from chao2.configuration import normalize_settings
from chao2.gui_worker import prepare_run_request
from chao2.task_queue import execution_entries


def request():
    queue=[
        {'id':'startup','key':'startup','enabled':True,'options':{}},
        {'id':'hunt_before','key':'hunt','enabled':True,'options':{'team':'1'}},
        {'id':'hunt_current','key':'hunt','enabled':True,'options':{'team':'2'}},
        {'id':'arena_off','key':'arena','enabled':False,'options':{}},
        {'id':'rift','key':'rift','enabled':True,'options':{'reserve_keys':2}},
        {'id':'hunt_after','key':'hunt','enabled':True,'options':{'team':'3'}},
        {'id':'rewards','key':'rewards','enabled':True,'options':{}},
        {'id':'finish','key':'finish','enabled':True,'options':{'close_mumu':False,'close_app':False}},
    ]
    return {'mode':'run','start_from':'hunt_current',
            'selected':['startup','hunt','rift','rewards','finish'],
            'settings':{'schema_version':8,'tasks':['startup','hunt','rift','rewards','finish'],
                        'allow_repeat_tasks':True,'unordered_tasks':True,'task_queue':queue,
                        'task_templates':[{'id':'saved','settings':{'task_queue':deepcopy(queue)}}]}}


def plan(value):
    settings,selected=prepare_run_request(value)
    return settings,execution_entries(normalize_settings(settings),selected,[])


def test_suffix_uses_instance_not_task_key_and_keeps_each_option():
    value=request();before=deepcopy(value)
    settings,entries=plan(value)
    assert [row['id'] for row in entries]==['hunt_current','rift','hunt_after','rewards','finish']
    assert [row['options']['team'] for row in entries if row['key']=='hunt']==['2','3']
    assert entries[1]['options']['reserve_keys']==2
    assert settings['unordered_tasks'] is False
    assert value==before
    assert settings['task_templates']==before['settings']['task_templates']
    settings['task_queue'][0]['options']['team']='5'
    assert value==before


@pytest.mark.parametrize('start,expected',[
    ('startup',['startup','hunt_before','hunt_current','rift','hunt_after','rewards','finish']),
    ('rewards',['rewards','finish']),
    ('finish',['finish']),
])
def test_first_and_last_task_boundaries(start,expected):
    value=request();value['start_from']=start
    _,entries=plan(value)
    assert [row['id'] for row in entries]==expected


def test_follows_custom_visible_order_and_does_not_enable_disabled_rows():
    value=request();queue=value['settings']['task_queue']
    queue[4],queue[6]=queue[6],queue[4]
    settings,entries=plan(value)
    assert [row['id'] for row in entries]==['hunt_current','rewards','hunt_after','rift','finish']
    assert next(row for row in settings['task_queue'] if row['id']=='arena_off')['enabled'] is False
    assert settings['tasks']==['hunt','rewards','rift','finish']


@pytest.mark.parametrize('invalid',['missing','',23,'arena_off'])
def test_invalid_or_disabled_start_is_rejected(invalid):
    value=request();value['start_from']=invalid
    with pytest.raises(ValueError):prepare_run_request(value)


def test_unselected_start_is_rejected_and_missing_queue_does_not_run_everything():
    value=request();value['selected'].remove('hunt')
    with pytest.raises(ValueError,match='未勾选'):prepare_run_request(value)
    value=request();value['settings'].pop('task_queue')
    with pytest.raises(ValueError,match='需要任务队列'):prepare_run_request(value)


def test_ambiguous_instance_is_rejected():
    value=request();value['settings']['task_queue'].append(deepcopy(value['settings']['task_queue'][2]))
    with pytest.raises(ValueError,match='重复'):prepare_run_request(value)


def test_normal_start_and_tools_keep_existing_request():
    for mode in ('run','diagnostic','launch','puzzle','tour','abyss'):
        value=request();value['mode']=mode;value['start_from']=None
        settings,selected=prepare_run_request(value)
        assert settings==value['settings'] and selected==value['selected']
        assert settings['unordered_tasks'] is True
        if mode!='run':
            value['start_from']='hunt_current'
            with pytest.raises(ValueError,match='只有任务执行'):prepare_run_request(value)
