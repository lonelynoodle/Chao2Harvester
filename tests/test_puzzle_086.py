"""Score-only goals, optional game caps and migration from forced old caps."""
import threading
import pytest
from test_configuration import captured
from test_tools_081 import player
from chao2.backend import Backend
from chao2.policy import TaskBlocked,UserStopped
from chao2.puzzle import run_puzzle
from chao2.puzzle_solver import MAX_SCORE,board_score,legal_moves
from chao2.tool_settings import PUZZLE_SPEC,puzzle_options,normalize_puzzle_settings

FULL=(512,256,128,64,32,16,8,4,2)
DEAD=(2,4,2,4,2,4,2,4,2)


def test_theoretical_ceiling_is_the_merge_score_of_the_full_staircase():
    assert MAX_SCORE==board_score(FULL)==7172
    assert not legal_moves(FULL)
    assert puzzle_options({})==(7172,0)
    assert len(PUZZLE_SPEC['fields'])==2


@pytest.mark.parametrize('score',[0,7173,True,1500.5,'1500'])
def test_invalid_score_fails_before_any_game_connection(tmp_path,monkeypatch,score):
    import chao2.workflows as flow
    monkeypatch.setattr(flow,'create_report',lambda:{'folder':tmp_path,'events':[],'tasks':{}})
    monkeypatch.setattr(Backend,'connect',lambda _:pytest.fail('Validate before connecting'))
    result=run_puzzle({'puzzle_target_score':score},threading.Event(),log=lambda _:None)
    assert result['status']=='blocked' and '目标分数' in result['reason']


@pytest.mark.parametrize('old,score',[('300',300),('1500',1500),('first',7172)])
def test_legacy_goals_migrate_and_remove_forced_steps_and_round_cap(old,score):
    original={'puzzle_goal':old,'puzzle_max_games':100,'puzzle_max_moves':3000,'tasks':['copies'],'close_mumu':False}
    migrated=normalize_puzzle_settings(original)
    assert puzzle_options(original)==puzzle_options(migrated)==(score,0)
    assert 'puzzle_max_moves' not in migrated and 'puzzle_goal' not in migrated
    assert migrated['tasks']==original['tasks'] and migrated['close_mumu'] is False
    assert original['puzzle_max_moves']==3000


def test_new_custom_limits_survive_reload_and_obsolete_values_have_no_effect():
    settings={'puzzle_target_score':3456,'puzzle_max_games':7,'puzzle_goal':'first','puzzle_max_moves':1}
    result=normalize_puzzle_settings(settings)
    assert puzzle_options(result)==(3456,7)
    assert normalize_puzzle_settings(result)==result
    assert puzzle_options({'puzzle_target_score':1})==(1,0)


def test_default_retries_beyond_old_hundred_round_cap_until_exact_target(tmp_path):
    p=player(tmp_path);s=captured('puzzle-initial');calls=[]
    p.stable_board=lambda:(s,DEAD)
    def restart(_):
        calls.append('restart')
        return s,FULL if len(calls)==101 else DEAD
    p.restart=restart
    assert '第102局已达7172分' in p.play()
    assert len(calls)==101 and p.report['goal_reached']
    assert p.report['max_games']==0 and len(p.report['games'])==102
    assert p.report['games'][-1]['outcome']=='target_reached' and p.report['best_score']==7172


def test_goal_on_final_allowed_round_wins_over_game_cap_without_restart(tmp_path):
    p=player(tmp_path);p.stable_board=lambda:(captured('v081-puzzle-settlement'),FULL)
    p.restart=lambda *_:pytest.fail('Already at target')
    assert '完成7172分目标' in p.play(7172,1)
    assert p.report['goal_reached'] and p.report['score_source']=='verified_moves'


def test_unlimited_retry_still_obeys_manual_stop_before_another_restart(tmp_path):
    p=player(tmp_path);s=captured('puzzle-initial');p.stable_board=lambda:(s,DEAD);restarts=[]
    p.restart=lambda s:restarts.append(1) or (s,DEAD)
    def stop():
        if len(restarts)==3:raise UserStopped('用户停止')
    p.b.check_stop=stop
    with pytest.raises(UserStopped):p.play()
    assert len(restarts)==3 and not p.report.get('goal_reached',False)


def test_impossible_score_is_not_reported_as_target_reached(tmp_path):
    p=player(tmp_path);p.stable_board=lambda:(captured('puzzle-initial'),(1024,0,0,0,0,0,0,0,0))
    with pytest.raises(TaskBlocked,match='超过7172'):p.play()
    assert not p.report.get('goal_reached',False)
