"""Overview rotation retains each stage's remaining teams and search budget."""
from copy import deepcopy
import pytest
from chao2.configuration import normalize_settings,SPECS
from chao2.activities import BudgetReached,main_identity
from chao2.policy import EncounterInterrupted,TaskBlocked
from test_configuration import daily,screen


def detail(identity):
    return screen((identity,42,140,67,37),('敌方阵容',1100,135,100,28),
                  ('排阵',810,610,80,30),('前往挑战',1010,605,160,30),
                  ('首通奖励',40,565,72,18),('5',1100,638,20,20))


def game(tmp_path,sequence,outcomes,*,teams=(2,1),limit=50,enabled=False):
    d=daily(tmp_path);d.options['main'].update(teams=list(teams),search_limit_enabled=enabled,max_searches=limit)
    state={'stamina':1000,'played':[],'opened':[]};pages=iter(sequence)
    d.home=lambda *a,**kw:screen();d.world_resources=lambda *_:{'stamina':state['stamina']}
    d.overview_prepared_for=lambda *_:False;d.stable_main_detail=lambda s,**kw:s
    d.back_detail=lambda *_:None;d.checkpoint=lambda:None;d.verify_stamina_cost=lambda *a:None
    def overview():
        d.count_main_search('玩法概览');n=next(pages);state['opened'].append(n);return detail(n)
    d.main_overview_detail=overview
    def play(task,opener,resource,verify,*,teams_override):
        q=opener();verify(q);n=main_identity(q);assert len(teams_override)==1
        team=teams_override[0];state['played'].append((n,team))
        won=outcomes.get((n,team),False)
        d.report.setdefault('team_attempts',[]).append({'task':'main','target':n,'team':team,
            'outcome':'victory' if won else 'failed'})
        if won:state['stamina']=0
        return won
    d.play_encounter=play
    d.last_main_detail=lambda *_:pytest.fail('Do not search for an old target between teams')
    return d,state


def test_rotation_challenges_current_stage_then_returns_to_old_stage_with_next_team(tmp_path):
    d,state=game(tmp_path,['100','200','100'],{('100',1):True})
    assert '通关1次' in d.main()
    assert state['played']==[('100',2),('200',2),('100',1)]
    assert d.report['main_stage_progress']['200']['teams']==[2]
    assert '200' not in d.report['main_failed'] and d.report['main_examined']==2


def test_ambush_before_main_battle_resumes_same_stage_with_unspent_team(tmp_path):
    d,state=game(tmp_path,['242'],{('242',1):True},teams=(1,))
    play=d.play_encounter;reopened=[]

    def interrupted(task,opener,resource,verify,*,teams_override):
        s=opener();verify(s)
        assert teams_override==[1] and main_identity(s)=='242'
        if not reopened:
            d._main_interrupted_target='242'
            raise EncounterInterrupted('敌袭已处理')
        return play(task,lambda:s,resource,verify,teams_override=teams_override)

    def reopen(identity):
        reopened.append(identity)
        return detail(identity)

    d.play_encounter=interrupted;d.last_main_detail=reopen
    assert '通关1次' in d.main()
    assert reopened==['242'] and state['played']==[('242',1)]


def test_all_teams_failed_are_skipped_and_full_idle_rotation_finishes(tmp_path):
    d,state=game(tmp_path,['100']*5,{})
    message=d.main()
    assert state['played']==[('100',2),('100',1)]
    assert d.report['main_failed']==['100'] and '概览已轮回' in message


def test_search_limit_counts_repeated_stages_and_stops_before_extra_navigation(tmp_path):
    d,state=game(tmp_path,['100']*3,{},enabled=True,limit=2)
    message=d.main()
    assert '搜索达到设置的2次上限' in message
    assert state['opened']==['100','100'] and d.report['main_searches']==2
    assert state['played']==[('100',2),('100',1)]


def test_disabled_limit_can_count_more_than_fifty(tmp_path):
    d=daily(tmp_path);d.options['main'].update(search_limit_enabled=False,max_searches=50)
    d.checkpoint=lambda:None
    for _ in range(51):d.count_main_search('重复推荐')
    assert d.report['main_searches']==51 and not d.main_search_limit_reached()


def test_search_counter_counts_failed_entries_and_stops_without_entering_again(tmp_path):
    d=daily(tmp_path);d.options['main'].update(search_limit_enabled=True,max_searches=2)
    d.checkpoint=lambda:None;opened=[]
    world=screen(('任务挑战',1190,40,80,24),('世界回响',1190,130,80,24),('3/183',520,12,70,26))
    d.enter_overview=lambda *a:opened.append(1) or world
    assert d.main_overview_detail() is None and d.main_overview_detail() is None
    with pytest.raises(BudgetReached,match='搜索达到设置的2次'):d.main_overview_detail()
    assert len(opened)==2 and d.report['main_searches']==2


def test_settlement_before_exit_failure_preserves_tried_team_for_recovery(tmp_path):
    d,state=game(tmp_path,['100','100'],{('100',1):True})
    original=d.play_encounter
    def fail_exit(*args,**kw):
        original(*args,**kw);raise TaskBlocked('退出仍未确认')
    d.play_encounter=fail_exit
    with pytest.raises(TaskBlocked):d.main()
    d.play_encounter=original
    d.main()
    assert state['played']==[('100',2),('100',1)]


def test_default_and_legacy_settings_leave_new_search_limit_off():
    options=normalize_settings({'task_options':{'main':{'teams':[2,1],'max_nodes':20}}})['task_options']['main']
    assert options['teams']==[2,1] and options['search_limit_enabled'] is False
    assert options['max_searches']==50 and 'max_nodes' not in options
    spec=next(f for f in SPECS['main']['fields'] if f['key']=='max_searches')
    assert spec['enabled_when']=='search_limit_enabled' and spec['min']==1


def test_search_state_is_independent_for_each_main_instance(tmp_path):
    d=daily(tmp_path);d.checkpoint=lambda:None
    options=deepcopy(d.options['main']);options.update(search_limit_enabled=True,max_searches=2)
    a={'id':'main-a','key':'main','options':options};b={'id':'main-b','key':'main','options':options}
    with d.task_instance(a):
        d.count_main_search('a');d.report['main_stage_progress']={'100':{'teams':[2],'cleared':False}}
    with d.task_instance(b):
        assert d.report.get('main_searches',0)==0 and not d.report.get('main_stage_progress')
        d.count_main_search('b')
    with d.task_instance(a):
        assert d.report['main_searches']==1 and d.report['main_stage_progress']['100']['teams']==[2]


def test_reaching_search_limit_completes_main_and_allows_following_task(tmp_path):
    d,state=game(tmp_path,['100'],{},enabled=True,limit=1)
    d.execute_task('main')
    ran=[];d.exploration=lambda:ran.append('exploration') or '探索完成'
    d.execute_task('exploration')
    assert d.report['tasks']['main']['status']=='done' and ran==['exploration']
    assert d.report['tasks']['exploration']['status']=='done'
