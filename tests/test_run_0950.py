"""October 27 failures: resource OCR, hunter overlap and delayed contract pages."""
from itertools import count
import time

import pytest

from chao2.backend import Backend, Word
from chao2.policy import SafetyStop, TaskBlocked, UserStopped
from chao2.result_navigation import exit_destination
from chao2.reward_collection import contract_page
from chao2.star_shop import star_souls
from chao2.world_events import is_map_choice, map_choice_hunt_target
from chao2.workflows import is_world
from test_configuration import captured, daily, screen
from test_hunt_single_team import hunt_menu
from test_run_0923 import templates


def fast_waits(d, monkeypatch):
    ticks=count()
    monkeypatch.setattr('chao2.navigation_retry.time.monotonic',lambda:next(ticks)*.5)
    d.b.sleep=lambda _:None


def fresh(s):
    s.when=time.monotonic()
    return s


def test_actual_hunter_overlap_is_a_post_result_destination():
    s=captured('v0950-hunt-blocked',True)
    assert is_map_choice(s) and not is_world(s)
    assert exit_destination(s)=='map_choice'
    assert map_choice_hunt_target(s).center==(672,360)


@pytest.mark.parametrize('missing',['请选择','狩猎'])
def test_hunt_choice_requires_its_own_modal_and_target_label(missing):
    s=captured('v0950-hunt-blocked',True)
    s.words=[w for w in s.words if w.text!=missing]
    assert not is_map_choice(s) and map_choice_hunt_target(s) is None


@pytest.mark.parametrize('missing',['传送','商店'])
def test_hunt_choice_uses_its_own_pixels_when_background_labels_disappear(missing):
    s=captured('v0950-hunt-blocked',True)
    s.words=[w for w in s.words if w.text!=missing]
    assert is_map_choice(s) and map_choice_hunt_target(s).center==(672,360)
    s.image[:]=0
    assert not is_map_choice(s)  # Missing sidebar evidence needs the real icon.


def test_hunt_choice_rejects_ambiguous_rows_and_never_chooses_terrain(tmp_path):
    d=daily(tmp_path);s=captured('v0950-hunt-blocked',True)
    s.words.append(Word('狩猎',[650,450,45,25],.99))
    d.b.click_at=lambda *a:pytest.fail('Ambiguous hunters must not be selected')
    assert is_map_choice(s) and map_choice_hunt_target(s) is None
    with pytest.raises(TaskBlocked,match='唯一狩猎'):d.open_hunt_choice(s)


def test_hunt_exit_resumes_same_list_without_a_search_or_new_battle(tmp_path):
    d=daily(tmp_path);d.active_task='hunt';d.b.sleep=lambda _:None
    result=captured('v082-ambush-result',True)
    choice=captured('v0950-hunt-blocked',True);menu=hunt_menu(2)
    state=[choice];actions=[]
    d.observe=lambda:fresh(state[0])
    d.b.click_text=lambda s,p:actions.append(p)
    assert d.exit_result(result) is choice
    def close(s,p,*a):
        actions.append(p);state[0]=menu
    d.b.click_at=close
    assert d.wait_hunter_removed(3) is menu
    assert actions==['^退出$',(803,212)]
    assert d.battles==0 and not d.search_counts
    assert d.report['result_exits'][0]['destination']=='map_choice'


def test_opening_a_hunter_selects_its_row_once_and_waits_through_loading(tmp_path,monkeypatch):
    d=daily(tmp_path);d.active_task='hunt';fast_waits(d,monkeypatch)
    choice=captured('v0950-hunt-blocked',True)
    detail=screen(('敌方阵容',1100,130,120,30),('排阵',820,610,65,35),
                  ('前往挑战',1035,610,115,30),('未知',135,135,60,30))
    frames=iter([choice,choice,screen(),detail]);actions=[]
    d.observe=lambda:next(frames)
    d.b.click_at=lambda s,p,*a:actions.append(p)
    assert d.await_detail() is detail and actions==[(672,360)]
    assert not d.search_counts and not d.task_counts


def test_swallowed_overlap_close_retries_only_the_verified_close(tmp_path,monkeypatch):
    d=daily(tmp_path);fast_waits(d,monkeypatch)
    choice=captured('v0950-hunt-blocked',True);menu=hunt_menu(2)
    state=[choice];clicks=[];d.observe=lambda:state[0]
    def close(s,p,*a):
        clicks.append(p)
        if len(clicks)==2:state[0]=menu
    d.b.click_at=close
    assert d.hunt_menu() is menu and clicks==[(803,212)]*2


def test_unknown_screen_after_overlap_close_is_not_clicked(tmp_path,monkeypatch):
    d=daily(tmp_path);fast_waits(d,monkeypatch)
    choice=captured('v0950-hunt-blocked',True);state=[choice];clicks=[]
    d.observe=lambda:fresh(state[0])
    def close(s,p,*a):clicks.append(p);state[0]=screen()
    d.b.click_at=close
    with pytest.raises(TaskBlocked,match='已重试3次'):d.hunt_menu()
    assert clicks==[(803,212)]


def contract_entry(d):
    loading=captured('v0950-contract-blocked',True)
    world=captured('other-initial-world',True)
    actions=[]
    d.home=lambda s:world
    d.click_world=lambda *a:actions.append('treasure')
    d.await_page=lambda *a:loading
    d.b.click_text=lambda s,p,**k:actions.append(p)
    return loading,actions


def test_contract_entry_waits_for_content_instead_of_failing_on_footer(tmp_path,monkeypatch):
    d=daily(tmp_path);fast_waits(d,monkeypatch)
    loading,actions=contract_entry(d)
    ready=captured('reward-contract-rewards',True)
    frames=iter([loading]*5+[ready]);d.observe=lambda:next(frames)
    assert d.contract_menu() is ready
    assert actions==['treasure','^蜕变契约$']
    assert not d.report.get('other_tasks')


def test_permanent_contract_loading_stops_without_claim_or_paid_clicks(tmp_path,monkeypatch):
    d=daily(tmp_path);fast_waits(d,monkeypatch)
    loading,actions=contract_entry(d);d.observe=lambda:fresh(loading)
    with pytest.raises(TaskBlocked,match='蜕变契约加载.*3次'):d.contract_menu()
    assert actions==['treasure','^蜕变契约$']
    assert len(d.report['navigation_retries'])==3


def test_contract_tabs_wait_for_content_and_never_replay_claims(tmp_path,monkeypatch):
    d=daily(tmp_path);fast_waits(d,monkeypatch)
    loading=captured('v0950-contract-blocked',True)
    tasks=captured('reward-contract-tasks',True)
    rewards=captured('reward-contract-rewards',True)
    d.contract_menu=lambda:rewards;actions=[];frames=iter([])
    def click(s,p,**k):
        nonlocal frames
        actions.append(p)
        frames=iter([loading]*3+[rewards if p=='^奖励$' else tasks])
    d.b.click_text=click;d.observe=lambda:fresh(next(frames))
    result=d.collect_contract()
    assert result['status']=='done' and result['task_batches']==result['reward_batches']==0
    assert actions==['^任务$','^每日任务$','^每周任务$','^挑战任务$','^奖励$']


@pytest.mark.parametrize('error',[UserStopped('用户停止'),SafetyStop('发现补购弹窗')])
def test_contract_wait_honors_real_stop_conditions(tmp_path,monkeypatch,error):
    d=daily(tmp_path);fast_waits(d,monkeypatch)
    loading,actions=contract_entry(d);calls=[]
    def observe():
        if calls:raise error
        calls.append(1);return loading
    d.observe=observe
    with pytest.raises(type(error)):d.contract_menu()
    assert actions==['treasure','^蜕变契约$']


@pytest.mark.parametrize('reads,expected',[
    (['17/20','17/20'],(17,20)),
    (['1720','1720'],None),
    (['17/20','12/20'],None),
    (['12/20','12/20'],None),
    (['17/0','17/0'],None),
    (['17/20 extra','17/20 extra'],None),
])
def test_missing_slash_needs_matching_literal_ratio_reads(reads,expected):
    b=Backend({});b.tasker=object()
    s=captured('v0950-tower-blocked')
    values=iter(reads);calls=[]
    def read(s,roi,scale=1,threshold=.65):
        calls.append((scale,threshold));return next(values)
    b.read_text_region=read
    assert b.read_resource_ratio(s,(1030,0,170,65))==expected
    assert calls==[(2,.8),(3,.8)]


def test_ratio_without_digits_is_not_guessed_from_nearby_balance():
    b=Backend({});b.tasker=object()
    b.read_text_region=lambda *a,**k:pytest.fail('No numeric anchor')
    assert b.read_resource_ratio(screen(('1720',500,10,60,25)),(1030,0,170,65)) is None


def test_missing_star_digit_still_requires_currency_and_second_read(tmp_path):
    d=daily(tmp_path);s=captured('v0950-star_spores-blocked',True);templates(d.b)
    def supplement(s,*a,**kw):
        assert kw['threshold']==.8
        s.words.append(Word('5',[1247,17,17,24],.99));return True
    d.b.confirm_label=supplement;d.b.read_number=lambda *a:6
    with pytest.raises(TaskBlocked,match='两次识别不一致'):star_souls(d.b,s)
    s=captured('v0950-star_spores-blocked',True);s.image[:58]=0
    d.b.confirm_label=lambda *a,**kw:pytest.fail('Unverified currency')
    with pytest.raises(TaskBlocked,match='图标未确认'):star_souls(d.b,s)


def test_actual_maa_recovers_today_resource_readings_without_device_input(tmp_path):
    from test_maa_recognition import Offline
    from maa.resource import Resource
    from maa.tasker import Tasker
    from chao2.backend import ROOT
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    d=daily(tmp_path);d.b.tasker=t
    tower=captured('v0950-tower-blocked',True)
    assert d.b.read_resource_ratio(tower,(1030,0,170,65))==(17,20)
    d.verify_dungeon_resource('tower',tower,(1030,0,170,65))
    assert d.report['dungeon_resources']['tower']['remaining']==17
    shop=captured('v0950-star_spores-blocked',True)
    assert shop.find(r'^\d+$',(1180,0,100,52)) is None
    assert star_souls(d.b,shop)==5
    assert not d.task_counts and d.battles==0
