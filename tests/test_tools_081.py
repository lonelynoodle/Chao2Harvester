import threading
from types import SimpleNamespace
import pytest
from test_configuration import captured,screen
from chao2.backend import Backend
from chao2.policy import TaskBlocked,FightLost
from chao2.puzzle import PuzzlePlayer,is_puzzle_settlement,terminal_after_move
from chao2.puzzle_solver import board_score,legal_moves
from chao2.tour import TourPlayer,is_tour_list,environment_cards,tour_progress,tour_detail,verify_free_tour,tour_story,tour_rules
from chao2.tool_settings import puzzle_options,tour_options

def player(tmp_path):
    b=Backend({});b.log=lambda _:None;b.sleep=lambda _:None
    return PuzzlePlayer(b,{'folder':tmp_path})

@pytest.mark.parametrize('goal,board',[('300',(128,2,0,0,0,0,0,0,0)),('1500',(256,2,0,0,0,0,0,0,0))])
def test_score_goal_stops_before_any_extra_move(tmp_path,monkeypatch,goal,board):
    import chao2.puzzle as puzzle
    p=player(tmp_path);p.stable_board=lambda:(captured('puzzle-initial'),board)
    monkeypatch.setattr(puzzle,'choose_move',lambda *a,**k:pytest.fail('Goal was reached'))
    assert '完成'+goal+'分目标' in p.play(int(goal),3)
    assert p.report['goal_reached'] and p.report['moves']==0

def test_terminal_restarts_only_within_user_game_limit(tmp_path):
    p=player(tmp_path);s=captured('puzzle-initial');dead=(2,4,2,4,2,4,2,4,2)
    p.stable_board=lambda:(s,dead);calls=[];p.restart=lambda s:calls.append('restart') or (s,dead)
    assert '2局上限' in p.play(300,2)
    assert calls==['restart'] and len(p.report['games'])==2 and p.report['goal_reached'] is False

def test_restart_verifies_new_initial_board_and_does_not_double_click(tmp_path):
    p=player(tmp_path);calls=[];s=captured('puzzle-initial')
    p.b.click_text=lambda *a:calls.append('click')
    p.stable_board=lambda:(s,(4,0,0,0,0,0,0,0,0))
    with pytest.raises(TaskBlocked,match='新局'):p.restart(s)
    assert calls==['click']

@pytest.mark.parametrize('settings',[{'puzzle_goal':'all'},{'puzzle_max_games':-1},{'puzzle_max_games':True},{'puzzle_target_score':1.5}])
def test_invalid_puzzle_options_rejected_before_input(settings):
    with pytest.raises(ValueError):puzzle_options(settings)

def test_tour_settings_reuse_ordered_teams_and_have_a_real_limit():
    assert tour_options({})=={'teams':[1,2,3],'wall_mode':'ignore','max_battles':100}
    assert tour_options({'tour_options':{'teams':[],'max_battles':1}})=={'teams':[],'wall_mode':'ignore','max_battles':1}
    for bad in [{'teams':[1,1]},{'max_battles':0},{'max_battles':True},{'teams':[6]}]:
        with pytest.raises(ValueError):tour_options({'tour_options':bad})

def test_actual_environment_pages_include_right_side_and_ignore_cutoff_cards():
    names=[]
    for name in ['v081-tour-menu','v081-tour-menu-right1','v081-tour-menu-right2']:
        s=captured(name);assert is_tour_list(s)
        names.extend(c['name'] for c in environment_cards(s))
    assert names==['赛博环','源裂变','极巨化','盛夏诞','启程季','海鸣起']
    assert tour_progress(captured('v081-tour-cyber-map'))==(13,40)
    assert tour_detail(captured('v081-tour-detail'))==(14,'赛博环14')
    assert tour_progress(captured('v081-tour-detail')) is None

def test_tour_challenge_checks_exact_stage_and_free_template():
    b=Backend({});s=captured('v081-tour-detail');b.match_template=lambda *a:True
    verify_free_tour(b,s,14)
    with pytest.raises(TaskBlocked,match='目标关卡'):verify_free_tour(b,s,13)
    b.match_template=lambda *a:False
    with pytest.raises(TaskBlocked,match='免费'):verify_free_tour(b,s,14)
    b.match_template=lambda *a:True
    s.words.extend(screen(('25',1090,640,25,20)).words)
    with pytest.raises(TaskBlocked,match='费用'):verify_free_tour(b,s,14)

def test_tour_fallback_once_per_team_then_changes_environment(tmp_path,monkeypatch):
    import chao2.tour as tour
    b=Backend({'tour_options':{'teams':[1,2,3],'max_battles':10}});b.log=lambda _:None;b.sleep=lambda _:None
    p=TourPlayer(b,{'folder':tmp_path,'events':[]});menu=captured('v081-tour-menu');map_=captured('v081-tour-cyber-map');detail=captured('v081-tour-detail')
    p.stable_list=lambda:menu;p.map_page=lambda:map_;p.claim_milestones=lambda s:s;p.list_page=lambda:menu
    p.open_next=lambda *a:(detail,'battle');p.select_team=lambda d,t:d
    b.click_at=lambda *a:None;b.click_text=lambda *a:None
    monkeypatch.setattr(tour,'verify_free_tour',lambda *a:None)
    def fail(*a):p.battles+=1;raise FightLost(detail)
    p.battle=fail;p.exit_result=lambda *a:None
    p.start_challenge=lambda *a:None
    p.environment(environment_cards(menu)[0])
    assert [a['team'] for a in p.report['team_attempts']]==[1,2,3]
    assert p.report['environments'][0]['reason']=='第14关全部阵容未通过'

def test_tour_does_not_navigate_from_an_unrelated_game_screen(tmp_path):
    b=Backend({});b.sleep=lambda _:None;b.click_at=lambda *a:pytest.fail('Unknown page')
    p=TourPlayer(b,{'folder':tmp_path,'events':[]});p.observe=lambda:captured('puzzle-initial')
    with pytest.raises(TaskBlocked,match='启动'):p.list_page()

def test_story_overlay_is_closed_once_and_never_misread_as_map(tmp_path):
    b=Backend({});b.sleep=lambda _:None;b.log=lambda _:None
    p=TourPlayer(b,{'folder':tmp_path,'events':[]});s=captured('v081-tour-story')
    assert tour_story(s)==5 and tour_progress(s) is None
    calls=[];b.click_at=lambda s,pt,*a:calls.append(pt);p.map_page=lambda:captured('v081-tour-cyber-map')
    p.story(s,5)
    assert calls==[(1140,125)] and p.report['stories'][0]['stage']==5

def test_real_tour_rules_do_not_expose_background_cards_and_progress_bar_ocr():
    s=captured('v081-tour-rules')
    assert tour_rules(s) and not is_tour_list(s) and environment_cards(s)==[]
    assert tour_progress(captured('v081-tour-progress-17'))==(17,40)

def test_tour_visits_each_right_hand_environment_once_without_repeating_finished_ones(tmp_path):
    pages=[captured(n) for n in ['v081-tour-menu','v081-tour-menu-right1','v081-tour-menu-right2']]
    current=[1];b=Backend({});b.sleep=lambda _:None
    def swipe(x1,y1,x2,y2,duration):
        current[0]=max(0,min(2,current[0]+(1 if x1>x2 else -1)))
    b.controller=SimpleNamespace(post_swipe=swipe);b.wait=lambda x:x
    p=TourPlayer(b,{'folder':tmp_path,'events':[],'environments':[]})
    p.list_page=p.stable_list=lambda:pages[current[0]]
    def visit(card):
        p.report['environments'].append({'name':card['name'],'wins':0})
        return pages[current[0]]
    p.environment=visit
    assert '遍历6个环境' in p.play()
    assert [e['name'] for e in p.report['environments']]==['赛博环','源裂变','极巨化','盛夏诞','启程季','海鸣起']
    assert p.report['all_environments_checked'] is True

def test_tour_uses_later_story_landmark_to_pan_back_towards_missing_node(tmp_path,monkeypatch):
    import chao2.tour as tour
    b=Backend({});b.sleep=lambda _:None
    s=captured('v081-tour-progress-17');detail=captured('v081-tour-detail')
    p=TourPlayer(b,{'folder':tmp_path,'events':[]});frames=iter([s,detail]);p.observe=lambda:next(frames)
    found=iter([None,((370,380),'battle')]);monkeypatch.setattr(tour,'tour_node',lambda *a:next(found))
    swipes=[];b.controller=SimpleNamespace(post_swipe=lambda *a:swipes.append(a));b.wait=lambda x:x
    b.click_at=lambda *a:None
    assert p.open_next(s,18)==(detail,'battle')
    assert swipes==[(350,450,750,450,1400)]

def test_same_environment_with_two_real_ocr_names_is_not_visited_twice(tmp_path):
    p=TourPlayer(Backend({}),{'folder':tmp_path,'events':[]})
    first=p.cards(captured('v081-tour-name-a',True))
    second=p.cards(captured('v081-tour-name-b',True))
    assert any(c['name']=='绘嘛春' for c in first)
    assert any(c['name']=='绘嘛春' for c in second)
    assert not any(c['name']=='绘骤春' for c in second)
    # Other artwork and environmental names remain distinct.
    assert [c['name'] for c in p.cards(captured('v081-tour-menu',True))]==['赛博环','源裂变']

def test_real_terminal_overlay_is_verified_from_last_move_without_bad_score_ocr(tmp_path):
    s=captured('v081-puzzle-settlement',True)
    assert is_puzzle_settlement(s)
    before=(4,2,16,2,16,4,8,2,2)
    final=terminal_after_move(before,'left')
    assert board_score(final)==124 and not legal_moves(final)
    p=player(tmp_path);p.b.observe=lambda *a:s
    assert p.stable_board(before,'left')[1]==final
    with pytest.raises(TaskBlocked,match='结算页'):p.stable_board()
    with pytest.raises(TaskBlocked):terminal_after_move((2,0,0,0,0,0,0,0,0),'right')

def test_terminal_at_game_cap_keeps_settlement_without_starting_a_new_game(tmp_path):
    p=player(tmp_path);s=captured('v081-puzzle-settlement')
    final=terminal_after_move((4,2,16,2,16,4,8,2,2),'left')
    p.stable_board=lambda:(s,final)
    p.restart=lambda *a:pytest.fail('Game cap reached')
    assert '1局上限' in p.play(300,1)
    assert not p.report['goal_reached'] and p.report['score']==124

def test_terminal_acknowledgment_automatically_starts_one_game_without_extra_restart(tmp_path):
    p=player(tmp_path);s=captured('v081-puzzle-settlement')
    calls=[];p.b.click_at=lambda s,point,*a:calls.append(point)
    p.b.click_text=lambda *a:pytest.fail('Settlement already starts the next game')
    p.stable_board=lambda:(captured('v081-puzzle-after-settlement'),(2,0,0,0,0,0,0,0,0))
    p.restart(s)
    assert calls==[(640,570)]

@pytest.mark.parametrize('known',[True,False])
def test_blocked_environment_can_be_skipped_only_from_a_recognized_tour_page(tmp_path,known):
    b=Backend({});b.log=lambda _:None;b.sleep=lambda _:None;b.wait=lambda x:x
    b.controller=SimpleNamespace(post_swipe=lambda *a:None)
    p=TourPlayer(b,{'folder':tmp_path,'events':[],'environments':[]});menu=captured('v081-tour-menu')
    p.list_page=p.stable_list=lambda:menu
    p.observe=lambda:captured('v081-tour-cyber-map' if known else 'puzzle-initial')
    def blocked(card):
        p.report['environments'].append({'name':card['name']})
        raise TaskBlocked('关卡尚未解锁')
    p.environment=blocked
    if not known:
        with pytest.raises(TaskBlocked):p.play()
        assert len(p.report['environments'])==1
    else:
        assert '需检查' in p.play()
        assert p.report['incomplete_environments']==['赛博环','源裂变']
        assert p.report['all_environments_checked'] is True
