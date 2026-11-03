import json
import threading
from types import SimpleNamespace
import pytest
from test_configuration import captured,daily,screen
from chao2.backend import Backend
from chao2.policy import TaskBlocked,UserStopped
from chao2.puzzle import is_puzzle,read_board,PuzzlePlayer,run_puzzle
from chao2.puzzle_solver import move_line,move,legal_moves,valid_transition,choose_move,validate_board,board_score

@pytest.mark.parametrize('row,result,score',[
    ((2,2,2),(4,2,0),4),((2,2,4),(4,4,0),4),((4,4,8),(8,8,0),8),
    ((0,2,2),(4,0,0),4),((2,0,4),(2,4,0),0),((0,0,0),(0,0,0),0)])
def test_slide_merges_each_tile_once(row,result,score):
    assert move_line(row)==(result,score)

def test_direction_and_spawn_validation():
    initial=(0,0,2,0,0,0,0,0,0)
    after=(2,0,0,0,0,0,0,2,0)
    assert move(initial,'left')==((2,0,0,0,0,0,0,0,0),0)
    assert valid_transition(initial,'left',after)
    assert not valid_transition(initial,'right',after)
    assert not valid_transition(initial,'left',(2,0,0,0,0,0,0,4,0))
    assert not valid_transition(initial,'left',(4,0,0,0,0,0,0,0,0))

def test_solver_has_only_legal_moves_and_handles_terminal_board():
    dead=(2,4,2,4,2,4,2,4,2)
    assert legal_moves(dead)==[] and choose_move(dead) is None
    board=(2,4,8,4,8,16,2,16,16)
    choice=choose_move(board,max_depth=4,time_budget=.2)
    assert choice['direction'] in {m[0] for m in legal_moves(board)}
    assert choice['depth']>=1
    for direction,after,_ in legal_moves(board):assert sum(board)==sum(after)

def test_search_respects_cancellation_and_rejects_non_game_numbers():
    with pytest.raises(UserStopped):choose_move((2,0,0,0,0,0,0,0,0),check_stop=lambda:(_ for _ in ()).throw(UserStopped('stop')))
    for bad in ([1]*9,[3]*9,[2]*8,[True]*9):
        with pytest.raises(ValueError):validate_board(bad)

def test_board_requires_game_title_and_rejects_rules_dialog():
    b=Backend({});b.read_number=lambda *a:pytest.fail('Do not OCR or input on unknown pages')
    assert is_puzzle(captured('puzzle-initial'))
    with pytest.raises(TaskBlocked,match='先.*打开'):read_board(b,captured('giant-menu'))
    with pytest.raises(TaskBlocked,match='弹窗'):read_board(b,captured('puzzle-rules'))

def test_puzzle_move_is_sent_once_then_waits_for_verified_transition(tmp_path,monkeypatch):
    import chao2.puzzle as puzzle
    before=(0,2,2,0,0,0,0,0,0);after=(4,0,0,0,0,0,0,2,0)
    b=Backend({});report={'folder':tmp_path};player=PuzzlePlayer(b,report)
    frames=iter([captured('puzzle-initial',True),captured('puzzle-initial',True),
                 captured('puzzle-initial',True),captured('puzzle-two-tiles',True),captured('puzzle-two-tiles',True)])
    b.observe=lambda *a:next(frames);b.sleep=lambda _:None
    monkeypatch.setattr(puzzle,'read_board',lambda b,s:after if len(s.words)==len(captured('puzzle-two-tiles').words) else before)
    monkeypatch.setattr(puzzle,'choose_move',lambda *a,**kw:{'direction':'left','depth':4})
    sent=[];b.controller=SimpleNamespace(post_swipe=lambda *a:sent.append(a) or SimpleNamespace(succeeded=True));b.wait=lambda x:x
    assert '完成4分目标' in player.play(4)
    assert len(sent)==1 and report['board']==list(after)
    assert report['score']==4 and report['score_source']=='verified_board'


def test_score_matches_real_game_and_each_confirmed_merge():
    boards=[(0,0,2,0,0,0,0,0,0), (2,2,8,0,2,8,8,128,32),
            (32,16,4,8,4,0,2,4,2)]
    assert [board_score(board) for board in boards]==[0,944,204]
    for board in boards:
        for direction,after,gain in legal_moves(board):
            assert board_score(after)==board_score(board)+gain
            for i,value in enumerate(after):
                if value==0:
                    spawned=after[:i]+(2,)+after[i+1:]
                    assert valid_transition(board,direction,spawned)
                    assert board_score(spawned)==board_score(board)+gain

def test_bad_transition_never_retries_swipe(tmp_path,monkeypatch):
    import chao2.puzzle as puzzle
    b=Backend({});s=captured('puzzle-initial');b.observe=lambda *a:s;b.sleep=lambda _:None
    monkeypatch.setattr(puzzle,'read_board',lambda *a:(2,0,0,0,0,0,0,0,0))
    b.controller=SimpleNamespace(post_swipe=lambda *a:pytest.fail('No extra swipe'))
    player=PuzzlePlayer(b,{'folder':tmp_path})
    with pytest.raises(TaskBlocked,match='不符'):player.stable_board((0,0,2,0,0,0,0,0,0),'left')

def test_standalone_tool_does_not_run_daily_tasks_or_navigate(tmp_path,monkeypatch):
    import chao2.workflows as flow
    import chao2.puzzle as puzzle
    monkeypatch.setattr(flow,'create_report',lambda:{'folder':tmp_path,'events':[],'tasks':{}})
    monkeypatch.setattr(Backend,'connect',lambda _:None)
    monkeypatch.setattr(Backend,'observe',lambda *a:captured('giant-menu'))
    monkeypatch.setattr(Backend,'click_at',lambda *a:pytest.fail('Manual opening is required'))
    result=run_puzzle({'close_mumu':True},threading.Event(),log=lambda _:None)
    assert result['status']=='blocked' and result['tasks']=={} and '先在游戏中打开' in result['reason']
    assert (tmp_path/'report.json').exists()
