"""A single-task launch scopes one instance and preserves the saved queue."""
from copy import deepcopy
import pytest
from chao2.gui_worker import prepare_run_request
from chao2.configuration import normalize_settings
from chao2.task_queue import execution_entries
from test_continue_from_task_0979 import request


def single(ident='hunt_current'):
    value=request();value.pop('start_from');value['only_task']=ident
    return value


@pytest.mark.parametrize('ident',['startup','hunt_before','hunt_current','hunt_after','arena_off','finish'])
def test_exact_instance_only_including_disabled_row_and_finish(ident):
    value=single(ident);value['settings']['close_mumu']=True;value['settings']['free_summon_enabled']=True
    original=deepcopy(value);settings,selected=prepare_run_request(value)
    entries=execution_entries(normalize_settings(settings),selected,[])
    assert [row['id'] for row in entries]==[ident] and entries[0]['enabled']
    source=next(row for row in value['settings']['task_queue'] if row['id']==ident)
    assert all(entries[0]['options'][k]==v for k,v in source['options'].items())
    assert value==original and settings['task_templates']==value['settings']['task_templates']
    assert not settings['unordered_tasks'] and not settings['close_mumu'] and not settings['free_summon_enabled']
    assert not settings['wild_capture_enabled']


def test_no_other_selected_tasks_are_required_for_single_launch():
    value=single('arena_off');value['selected']=[]
    settings,selected=prepare_run_request(value)
    assert selected==['arena'] and len(settings['task_queue'])==1


@pytest.mark.parametrize('ident',['',15,'missing'])
def test_bad_instance_rejected(ident):
    with pytest.raises(ValueError):prepare_run_request(single(ident))


def test_missing_queue_and_ambiguous_ids_rejected():
    value=single();value['settings'].pop('task_queue')
    with pytest.raises(ValueError,match='需要任务队列'):prepare_run_request(value)
    value=single();value['settings']['task_queue'].append(deepcopy(value['settings']['task_queue'][2]))
    with pytest.raises(ValueError,match='重复'):prepare_run_request(value)


def test_single_and_suffix_launch_are_mutually_exclusive():
    value=single();value['start_from']='hunt_current'
    with pytest.raises(ValueError,match='不能同时'):prepare_run_request(value)


@pytest.mark.parametrize('mode',['diagnostic','launch','puzzle','tour','abyss'])
def test_single_scope_cannot_be_used_by_tools(mode):
    value=single();value['mode']=mode
    with pytest.raises(ValueError,match='只有任务执行'):prepare_run_request(value)
