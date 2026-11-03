"""All-task lore interruptions, using the actual failed evolution screenshot."""
from copy import deepcopy
import time

import pytest

from chao2.backend import Word,Screen
from chao2.policy import TaskBlocked,UserStopped,SafetyStop
from chao2.puzzle import PuzzlePlayer
from chao2.reward_collection import is_map_story,echo_story_kind
from chao2.story_cards import story_identity
from chao2.trigger_events import triggered_event
from chao2.workflows import ORDER
from test_configuration import captured,daily,screen
from test_run_0946 import recognition
from maa.pipeline import JOCR


def story_game(d,after,*,drops=0,story=None):
    story=story or captured('v0948-evolution-story',True)
    game={'screen':story,'clicks':[]}
    d.b.observe=lambda *a:game['screen']
    d.b.sleep=lambda _:None
    def click(s,point,anchors,reason):
        assert s is game['screen'] and s.has(*anchors)
        assert point==(1210,650) and '关闭' in reason
        game['clicks'].append(point)
        if len(game['clicks'])>drops:game['screen']=after
    d.b.click_at=click
    d.home=lambda *a,**kw:pytest.fail('A story must not leave or restart the task')
    return game


@pytest.mark.parametrize('task',ORDER)
def test_every_daily_task_observes_underlying_page_after_incidental_story(tmp_path,task):
    d=daily(tmp_path);d.active_task=task;d.active_task_id='instance-2'
    after=captured('main-entry');game=story_game(d,after)
    d.task_counts={task:2};d.report['resource_usage']={task:{'spent':5}}
    before=deepcopy(d.options)
    assert d.observe() is after and game['clicks']==[(1210,650)]
    assert d.active_task==task and d.active_task_id=='instance-2'
    assert d.task_counts=={task:2} and d.report['resource_usage']=={task:{'spent':5}}
    assert d.options==before and d.report['map_stories']==['进化啦?']
    row=d.report['story_interruptions'][0]
    assert row['number']=='143' and row['source_task']==task
    assert row['instance_id']=='instance-2' and row['close_attempts']==1 and row['status']=='closed'


@pytest.mark.parametrize('name',['v0914-map-story','v0920-main-story','v0948-evolution-story'])
def test_card_classifier_uses_shared_layout_and_not_background_task(name):
    s=captured(name,True)
    assert is_map_story(s) and triggered_event(s)=='story_card'
    identity=story_identity(s)
    s.words=[Word('另一张不同的事件卡',w.box,w.score) if w.text==identity[1] else
             Word('新的剧情内容完全不同，但故事卡的结构和评论位置不变。',w.box,w.score)
             if 365<=w.box[0]<=400 and 285<=w.center[1]<=590 and len(w.text)>=12 else w
             for w in s.words]
    assert triggered_event(s)=='story_card'


def test_actual_evolution_story_pixels_are_recognized_by_maa(recognition):
    image=captured('v0948-evolution-story',True).image
    result=recognition.wait(recognition.tasker.post_recognition(
        'OCR',JOCR(roi=[0,0,1280,720],threshold=.5),image),20).get()
    words=[Word(v.text,list(v.box),v.score) for n in result.nodes if n.recognition
           for v in n.recognition.all_results if getattr(v,'text','') and v.score>=.5]
    observed=Screen(image,words,time.monotonic())
    assert story_identity(observed)==('143','进化啦?')
    assert triggered_event(observed)=='story_card'


@pytest.mark.parametrize('drops',[1,3])
def test_lost_story_close_retries_three_times_only_on_same_card(tmp_path,drops):
    d=daily(tmp_path);after=captured('main-entry');game=story_game(d,after,drops=drops)
    assert d.observe() is after and len(game['clicks'])==drops+1
    assert len(d.report['story_interruptions'])==1


def test_story_read_only_diagnostic_and_stop_never_click(tmp_path):
    d=daily(tmp_path);game=story_game(d,screen())
    assert d.observe(dismiss_popups=False) is game['screen'] and not game['clicks']
    d.b.stop.set()
    with pytest.raises(UserStopped):d.observe()
    assert not game['clicks']


def test_story_then_purchase_modal_stops_without_clicking_modal(tmp_path):
    d=daily(tmp_path)
    modal=screen(('是否购买体力',450,280,200,40),('取消',450,480,80,40),('确定',770,480,80,40))
    game=story_game(d,modal)
    with pytest.raises(SafetyStop,match='补购'):d.observe()
    assert game['clicks']==[(1210,650)]


def test_blank_transition_is_waited_out_without_another_close(tmp_path):
    d=daily(tmp_path);story=captured('v0948-evolution-story');after=captured('main-entry')
    frames=iter([story,screen(),screen(),after]);d.b.observe=lambda *a:next(frames)
    d.b.sleep=lambda _:None;clicks=[];d.b.click_at=lambda *a:clicks.append(a[1])
    assert d.observe() is after and clicks==[(1210,650)]


def test_persistently_blank_transition_does_not_replay_close(tmp_path):
    d=daily(tmp_path);game=story_game(d,screen())
    with pytest.raises(TaskBlocked,match='尚未稳定'):d.observe()
    assert len(game['clicks'])==1 and not d.report.get('map_stories')


def test_consecutive_different_cards_close_each_once_without_recursion(tmp_path):
    d=daily(tmp_path)
    first=captured('v0948-evolution-story');second=captured('v0920-main-story');after=captured('main-entry')
    frames=iter([first,second,after]);d.b.observe=lambda *a:next(frames)
    d.b.sleep=lambda _:None;clicks=[];d.b.click_at=lambda *a:clicks.append(a[1])
    assert d.observe() is after and clicks==[(1210,650)]*2
    assert d.report['map_stories']==['进化啦?','围猎']
    assert [r['close_attempts'] for r in d.report['story_interruptions']]==[1,1]


@pytest.mark.parametrize('name',['reward-lost-story-001','v0920-lost-story-ready','v0920-torrent-comment-icon'])
def test_explicit_echo_reward_story_is_left_to_reward_collection(tmp_path,name):
    d=daily(tmp_path);s=captured(name,True)
    assert echo_story_kind(s) and not is_map_story(s)
    d.b.observe=lambda *a:s
    d.b.click_at=lambda *a:pytest.fail('Do not skip the story reward collection')
    assert d.observe() is s


def test_global_story_then_invitation_still_applies_refusal(tmp_path):
    d=daily(tmp_path);invite=captured('v0922-rift-invitation');after=captured('main-entry')
    game=story_game(d,invite);refusals=[]
    def refuse(s,pattern,**kw):
        assert s is invite and '取消' in pattern and '拒绝' in pattern
        refusals.append(kw['roi']);game['screen']=after
    d.b.click_text=refuse
    assert d.observe() is after and len(refusals)==1
    assert game['clicks']==[(1210,650)] and d.report['rejected_invitations'][0]['status']=='refused'


@pytest.mark.parametrize('story_after_reveal',[False,True])
def test_sixing_evolution_continues_in_same_call_after_story(tmp_path,recognition,story_after_reveal):
    d=daily(tmp_path);d.active_task='other';d.b.tasker=recognition.tasker
    d.b.read_number=lambda *a:1;d.b.sleep=lambda _:None
    story=captured('v0948-evolution-story',True)
    reveal=captured('v0948-darkdragon-reveal',True)
    info=captured('v0927-purple-info',True)
    game={'screen':reveal if story_after_reveal else story,'clicks':[]}
    d.b.observe=lambda *a:game['screen']
    d.day['star_evolution_pending']={'name':'暗黑龙','gold':85000,'spores':45,'status':'submitted'}
    def click(s,point,anchors,reason):
        assert s is game['screen'] and s.has(*anchors) and '关闭' in reason
        game['clicks'].append(point)
        if point==(1210,650):game['screen']=info if story_after_reveal else reveal
        elif point==(640,660):game['screen']=story if story_after_reveal else info
        else:pytest.fail('No repeat evolution or navigation input')
    d.b.click_at=click
    d.one_blue_roster=lambda:pytest.fail('No repeat selection or evolution')
    d.home=lambda *a,**kw:pytest.fail('Resume evolution before leaving the page')
    assert d.complete_star_evolution(d.observe(),submitted_now=True) is info
    assert 'star_evolution_pending' not in d.day
    assert d.report['other_tasks']['star_spores']['evolved']==1
    assert not d.report['star_evolutions'][0]['resumed']
    assert len(game['clicks'])==2


def test_standalone_puzzle_resumes_verified_board_after_story(tmp_path,monkeypatch):
    import chao2.puzzle as puzzle
    d=daily(tmp_path);after=captured('puzzle-initial');game=story_game(d,after)
    player=PuzzlePlayer(d.b,d.report)
    board=(2,0,0,0,0,0,0,0,0)
    monkeypatch.setattr(puzzle,'read_board',lambda *a:board)
    s,result=player.stable_board()
    assert s is after and result==board and game['clicks']==[(1210,650)]
    assert d.report['story_interruptions'][0]['source_task']=='puzzle'
