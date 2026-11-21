"""Sequential copies and the opt-in repeat-rampage setting."""
from copy import deepcopy
import pytest
from chao2.configuration import normalize_settings,SPECS
from chao2.activities import encounter_identity
from test_configuration import daily,screen
from test_copy_navigation import Game


def test_repeat_switch_replaces_old_limit_in_saved_options_queue_and_templates():
    nest={'teams':[2,1],'max_runs':1}
    saved={'task_options':{'nest':deepcopy(nest)},
           'task_queue':[{'id':'nest','key':'nest','options':deepcopy(nest)}],
           'task_templates':[{'id':'custom','name':'keep','settings':{
               'task_options':{'nest':deepcopy(nest)},
               'task_queue':[{'id':'nest2','key':'nest','options':{**nest,'repeat_challenge':True}}]}}]}
    before=deepcopy(saved);fixed=normalize_settings(saved)
    assert saved==before
    nodes=[fixed['task_options']['nest'],fixed['task_queue'][0]['options'],
           fixed['task_templates'][0]['settings']['task_options']['nest'],
           fixed['task_templates'][0]['settings']['task_queue'][0]['options']]
    assert all('max_runs' not in options and options['teams']==[2,1] for options in nodes)
    assert [options['repeat_challenge'] for options in nodes]==[False,False,False,True]
    assert normalize_settings(fixed)==fixed
    assert 'max_runs' not in {field['key'] for field in SPECS['nest']['fields']}


@pytest.mark.parametrize('bad',[1,'yes',None])
def test_repeat_flag_rejects_non_boolean_values(bad):
    with pytest.raises(ValueError):normalize_settings({'task_options':{'nest':{'repeat_challenge':bad}}})


def rampage_game(tmp_path,*,repeat=False,teams=(),score=550):
    d=daily(tmp_path,{'task_options':{'nest':{'teams':list(teams),'repeat_challenge':repeat,'max_runs':1}}})
    s=screen(('谜之巢穴',110,15,150,40),('暴走旷野',961,82,89,23),('最高击破数',1002,412,91,19),
             ('挑战',1086,497,66,35))
    result=screen(('本场击破数',665,365,113,24),('本场金币奖励',665,411,135,23))
    calls=[];d.enter_building=lambda *a:s;d.rampage_score=lambda q:score
    d.b.click_text=lambda *a:None;d.home=lambda:None;d.exit_result=lambda *a:s
    d.apply_saved_team=lambda q,team:calls.append(('team',team)) or q
    d.start_challenge=lambda *a:calls.append(('challenge',None))
    def battle():
        d.task_counts['nest']=d.task_counts.get('nest',0)+1
        d.report['rampage_settlement']={'kills':score,'gold':1000}
        return result
    d.rampage_battle=battle
    d.day['rampage_done']=True
    return d,calls


def test_existing_score_still_skips_by_default(tmp_path):
    d,calls=rampage_game(tmp_path)
    assert '已有550' in d.nest() and calls==[]


def test_repeat_enabled_runs_once_even_with_existing_daily_score(tmp_path):
    d,calls=rampage_game(tmp_path,repeat=True)
    assert '已完成1场' in d.nest()
    assert calls==[('challenge',None)]
    assert len(d.report['team_attempts'])==1 and d.report['rampage_score_end']==550


def test_repeat_runs_one_round_of_selected_teams_without_old_single_fight_cap(tmp_path):
    d,calls=rampage_game(tmp_path,repeat=True,teams=[2,1])
    assert '已完成2场' in d.nest()
    assert calls==[('team',2),('challenge',None),('team',1),('challenge',None)]
    assert [r['team'] for r in d.report['team_attempts']]==[2,1]


def test_current_copy_is_used_then_rewardless_friend_is_skipped_without_scrolling(tmp_path,monkeypatch):
    g=Game(tmp_path,monkeypatch,[[('own','own'),('no-reward','friend'),('reward','friend')]])
    g.d.copy_first_page=lambda *a:pytest.fail('Sequential selection must not rewind')
    g.b.read_number=lambda s,*a:0 if encounter_identity(s)=='no-reward' else 20
    first=g.d.copy_targets('any',set())
    assert first['identity']=='own' and first['kind']=='own'
    g.d.back_detail(first['screen'])
    second=g.d.copy_targets('any',{'own'})
    assert second['identity']=='reward' and second['kind']=='friend'
    assert g.opens==['own','no-reward','reward'] and g.swipes==[]


def test_copy_search_only_moves_down_when_no_visible_targets_remain(tmp_path,monkeypatch):
    g=Game(tmp_path,monkeypatch,[[('failed','own')],[('next','friend')]])
    g.d.copy_first_page=lambda *a:pytest.fail('Sequential selection must not rewind')
    target=g.d.copy_targets('any',{'failed'})
    assert target['identity']=='next' and g.swipes==['down']
