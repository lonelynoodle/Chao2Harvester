"""One-line rift lore must claim its free reward and resume the same task."""
import pytest
from test_configuration import daily,screen,captured
from chao2.reward_collection import is_map_story
from chao2.story_cards import story_identity,map_story_chest_state,story_echo_upgrade,complete_story_card_reward
from chao2.trigger_events import triggered_event
from chao2.policy import TaskBlocked,UserStopped
from chao2.rift import is_rift_map


def story(state='ready',lines=1):
    s=screen(('凿星裂痕',125,17,87,22),('031',384,182,46,27),
             ('凿星前夜',385,214,168,45),('评论',240,377,44,25),
             *((f'裂痕已亮，前方净空，祝君武运昌隆，第{i}行。',396,291+35*i,620,22) for i in range(lines)))
    if state:s.words+=screen(('可领取' if state=='ready' else '已领取',212,622,46,14)).words
    return s


def rift_map():
    return screen(('凿星裂痕',125,17,87,22),('凿星裂痕当前通关',500,5,270,28),
                  ('匹配房间',1000,660,130,35),('创建队伍',1150,660,125,35),('33',615,42,50,30))


@pytest.mark.parametrize('lines',[1,2,3])
def test_story_classifier_accepts_short_and_long_body(lines):
    s=story(lines=lines)
    assert is_map_story(s) and story_identity(s)==('031','凿星前夜')
    assert triggered_event(s)=='story_card' and map_story_chest_state(s)=='ready'


@pytest.mark.parametrize('missing',['comment','number','title','body','echo'])
def test_short_story_still_requires_the_complete_fixed_layout(missing):
    s=story()
    patterns={'comment':'评论','number':'031','title':'凿星前夜'}
    if missing in patterns:s.words=[w for w in s.words if w.text!=patterns[missing]]
    elif missing=='body':s=story(lines=0)
    else:s.words+=screen(('遗落回响',110,10,120,32)).words
    assert not is_map_story(s) and map_story_chest_state(s) is None


def test_short_card_remains_recognizable_after_chest_label_disappears():
    assert is_map_story(story(state=None))
    assert map_story_chest_state(story(state=None)) is None
    s=story();next(w for w in s.words if w.text=='可领取').box[0]=970
    assert map_story_chest_state(s) is None


def test_actual_rift_story_031_is_short_and_reward_is_ready():
    s=captured('v0974-rift-story',True)
    assert story_identity(s)==('031','凿星前夜') and map_story_chest_state(s)=='ready'


def echo_upgrade(effect='移动力上限'):
    return screen(('回响等级',690,215,150,30),(effect,690,305,170,30),
                  ('点击空白位置关闭',540,605,230,30),('40',990,215,40,30),('41',1110,215,40,30))


def setup_game(d,*,initial=None,claim_works=True,upgrade=None):
    ready=initial or story();claimed=story(state='claimed');after=rift_map()
    receipt=screen(('获得奖励',520,110,230,65),('点击空白位置关闭',510,600,260,35))
    game={'screen':ready,'clicks':[]}
    d.b.observe=lambda *a:game['screen'];d.b.sleep=lambda _:None
    def click(s,point,anchors,reason):
        assert s is game['screen'] and s.has(*anchors)
        game['clicks'].append(point)
        if point==(235,588):
            if claim_works:game['screen']=echo_upgrade(upgrade) if upgrade else receipt
        elif point==(640,620):game['screen']=receipt
        elif point==(640,660):game['screen']=claimed
        elif point==(1210,650):game['screen']=after
        else:pytest.fail('Unexpected input')
    d.b.click_at=click
    return game,after


def test_claims_receipt_before_closing_and_resumes_rift_without_replaying_battle(tmp_path):
    d=daily(tmp_path);d.active_task='rift';d.active_task_id='rift-instance'
    d.task_counts={'rift':2};d.battles=2
    d.report['resource_usage']={'rift':{'裂痕钥匙':{'start':3,'spent':1,'remaining':2}}}
    game,after=setup_game(d)
    d.start_challenge=lambda *a,**kw:pytest.fail('Lore handling must not replay the fight')
    assert d.rift_wait_map() is after and is_rift_map(after)
    assert game['clicks']==[(235,588),(640,660),(1210,650)]
    assert d.task_counts=={'rift':2} and d.battles==2
    assert d.report['resource_usage']['rift']['裂痕钥匙']['spent']==1
    row=d.report['story_rewards'][0]
    assert row['status']=='claimed' and '获得奖励' in row['reward_text']
    assert row['source_task']=='rift' and row['instance_id']=='rift-instance'
    assert d.report['story_interruptions'][0]['status']=='closed'


@pytest.mark.parametrize('state',['claimed',None])
def test_collected_or_unknown_chest_only_closes_the_card(tmp_path,state):
    d=daily(tmp_path);game,after=setup_game(d,initial=story(state=state))
    assert d.observe() is after and game['clicks']==[(1210,650)]
    assert not d.report.get('story_rewards')


@pytest.mark.parametrize('effect',['移动力上限','黑暗森林探索点上限'])
def test_echo_upgrade_is_closed_before_receipt_and_story_are_processed(tmp_path,effect):
    d=daily(tmp_path);game,after=setup_game(d,upgrade=effect)
    assert d.observe() is after
    assert game['clicks']==[(235,588),(640,620),(640,660),(1210,650)]
    assert d.report['story_rewards'][0]['status']=='claimed'
    assert '回响等级' in d.report['story_rewards'][0]['level_ups'][0]


def test_new_run_dismisses_leftover_forest_echo_upgrade_without_claiming(tmp_path):
    d=daily(tmp_path);upgrade=echo_upgrade('黑暗森林探索点上限')
    game,after=setup_game(d,initial=upgrade)
    assert d.observe(dismiss_popups=False) is upgrade and game['clicks']==[]
    assert d.observe().find('^获得奖励$') and game['clicks']==[(640,620)]
    assert '黑暗森林探索点上限' in d.report['resumed_echo_upgrades'][0]
    assert not d.report.get('story_rewards')


@pytest.mark.parametrize('missing',['回响等级','移动力上限','点击空白位置关闭'])
def test_echo_upgrade_dismissal_requires_all_three_fixed_controls(missing):
    s=echo_upgrade();assert story_echo_upgrade(s)
    s.words=[w for w in s.words if w.text!=missing]
    assert not story_echo_upgrade(s)


def test_submitted_claim_can_finish_upgrade_and_receipt_without_reclaiming(tmp_path):
    d=daily(tmp_path);game,_=setup_game(d,initial=echo_upgrade())
    row={'number':'031','title':'凿星前夜','status':'unconfirmed'}
    d.report['story_rewards']=[row]
    result=complete_story_card_reward(d.b,d.report,row,checkpoint=d.checkpoint)
    assert story_identity(result)==('031','凿星前夜') and row['status']=='claimed'
    assert game['clicks']==[(640,620),(640,660)]


def test_claim_is_skipped_if_card_changes_during_fresh_check(tmp_path):
    d=daily(tmp_path);ready=story();after=rift_map();d.b.observe=lambda *a:after
    d.b.click_at=lambda *a:pytest.fail('No click against a changed card')
    assert d.close_map_story(ready) is after
    assert not d.report.get('story_rewards')


def test_missing_reward_confirmation_does_not_retry_or_close_the_card(tmp_path):
    d=daily(tmp_path);game,_=setup_game(d,claim_works=False)
    with pytest.raises(TaskBlocked,match='领取结果未确认'):d.observe()
    assert game['clicks']==[(235,588)] and d.report['story_rewards'][0]['status']=='unconfirmed'
    with pytest.raises(TaskBlocked,match='上次领取结果未确认'):d.observe()
    assert game['clicks']==[(235,588)] and not d.report.get('map_stories')


def test_read_only_and_user_stop_do_not_claim_the_ready_chest(tmp_path):
    d=daily(tmp_path);game,_=setup_game(d)
    assert d.observe(dismiss_popups=False) is game['screen'] and not game['clicks']
    d.b.stop.set()
    with pytest.raises(UserStopped):d.observe()
    assert not game['clicks']
