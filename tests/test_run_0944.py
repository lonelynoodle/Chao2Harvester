"""Real 2026-10-25 failures and the inspected tribe totem fallback."""
import copy
from types import SimpleNamespace

import pytest

from test_configuration import captured,daily
from test_maa_recognition import Offline
from chao2.backend import Backend,ROOT
from chao2.activities import tribe_identity,is_tribe_detail,BudgetReached,ResourceReserveReached
from chao2.tribe_totems import totem_nodes,totem_identity,totem_score
from chao2.configuration import normalize_settings
from chao2.daily_challenges import arena_candidates,choose_opponent
from chao2.abyss import abyss_empty,abyss_target,AbyssPlayer
from chao2.policy import TaskBlocked,UserStopped
from chao2.star_supply import blue_roster_cards
from chao2.challenge_start import battle_entry_state
from maa.resource import Resource
from maa.tasker import Tasker


@pytest.fixture(scope='module')
def recognition():
    controller=Offline();assert controller.post_connection().wait().succeeded
    resource=Resource();assert resource.post_bundle(ROOT/'resource').wait().succeeded
    tasker=Tasker();assert tasker.bind(resource,controller)
    backend=Backend({},log=lambda _:None);backend.tasker=tasker
    yield backend


def test_actual_arena_four_powers_include_two_narrow_ones(tmp_path,recognition):
    d=daily(tmp_path);d.b.tasker=recognition.tasker
    rows=arena_candidates(captured('v0944-arena-blocked',True),d.read_arena_power)
    assert [row['power'] for row in rows]==[141082,149565,98241,71105]
    assert choose_opponent(rows,'weakest')['index']==3


def test_arena_list_gets_three_read_only_retries(tmp_path):
    d=daily(tmp_path);bad=captured('v0944-arena-blocked');bad.words=[]
    seen=[];d.observe=lambda:seen.append(1) or bad;d.b.sleep=lambda _:None
    d.b.click_at=lambda *a:pytest.fail('No navigation or battle on unreadable cards')
    with pytest.raises(TaskBlocked,match='列表未确认'):d.read_arena_candidates(bad)
    assert len(seen)==3


def test_actual_scrolled_blue_cards_use_their_frame_position(recognition):
    s=captured('v0944-star_spores-blocked',True)
    rows=blue_roster_cards(s,recognition.read_text_crop)
    assert rows[0]['point']==(930,503) and rows[0]['level']==1
    assert all(row['point'][1] in (503,631) for row in rows)
    assert not any(row['point'][0]<930 and row['point'][1]==503 for row in rows)


def test_blue_level_requires_a_readable_label_not_a_bare_digit():
    s=captured('v0944-star_spores-blocked',True)
    s.words=[w for w in s.words if '等级' not in w.text]
    rows=blue_roster_cards(s,lambda *a:'1')
    assert rows and all(row['level'] is None for row in rows)


def test_blue_cards_track_scroll_offset_and_exclude_clipped_cards(recognition):
    s=captured('v0944-star_spores-blocked',True)
    original=s.image.copy();s.image[175:700]=0
    s.image[198:700]=original[175:677]
    s.words=[w for w in s.words if w.center[1]<175]
    rows=blue_roster_cards(s,recognition.read_text_crop)
    assert rows and rows[0]['point']==(930,526) and rows[0]['level']==1
    assert all(row['point'][1]==526 for row in rows)


def test_blue_unknown_level_retries_without_buying_more_eggs(tmp_path,monkeypatch):
    import chao2.star_shop as shop
    d=daily(tmp_path);s=captured('v0944-star_spores-blocked',True)
    d.territory=lambda:s;d.b.sleep=lambda _:None
    d.wait_for_screen=lambda *a,**kw:s
    d.b.click_at=d.b.click_text=lambda *a,**kw:None
    calls=[]
    def cards(*args):calls.append(1);return [{'point':(930,503),'level':None}]
    monkeypatch.setattr(shop,'blue_roster_cards',cards)
    with pytest.raises(TaskBlocked,match='未购买更多'):d.one_blue_roster()
    assert len(calls)==4


def test_real_abyss_empty_text_below_old_roi_is_completed_without_fight(tmp_path):
    d=daily(tmp_path);p=AbyssPlayer(d.b,d.report)
    empty=captured('v0944-abyss-blocked',True)
    assert abyss_empty(empty) and abyss_target(empty) is None
    p.menu_page=lambda:empty
    p.open_target=p.suppress=lambda *a:pytest.fail('No target: no fighting or suppression')
    assert '没有可挑战' in p.play()


@pytest.mark.parametrize('missing',['无','深渊先遣未出现'])
def test_abyss_empty_still_needs_both_client_markers(missing):
    s=captured('v0944-abyss-blocked',True)
    s.words=[w for w in s.words if w.text!=missing]
    assert not abyss_empty(s)


def test_daily_home_recovers_from_abyss_list(tmp_path):
    d=daily(tmp_path);empty=captured('v0944-abyss-blocked',True)
    world=captured('v0944-totem-after-world',True)
    d.observe=lambda:world;clicks=[]
    d.b.click_at=lambda s,p,a,r:clicks.append((p,r))
    assert d.home(empty) is world
    assert clicks==[((770,680),'收起深渊先遣列表')]


def test_totem_option_normalization_and_disable():
    assert normalize_settings({})['task_options']['tribe']['random_totem'] is True
    assert normalize_settings({'task_options':{'tribe':{'random_totem':False}}})['task_options']['tribe']['random_totem'] is False
    with pytest.raises(ValueError):normalize_settings({'task_options':{'tribe':{'random_totem':'yes'}}})


def test_totem_templates_find_map_crests_not_rewards_or_monsters():
    rows=totem_nodes(captured('v0944-tribe-entry',True))
    assert {row['kind'] for row in rows}=={'flame','spear'}
    assert totem_nodes(captured('v0944-totem-detail',True))==[]
    assert totem_nodes(captured('v0944-arena-blocked',True))==[]


def test_totem_identity_requires_matching_titles_and_reward_layout():
    s=captured('v0944-totem-detail',True)
    assert tribe_identity(s)=='抑制图腾' and is_tribe_detail(s)
    for missing in ['图腾共生','比拼方式','每次挑战奖励']:
        q=copy.deepcopy(s);q.words=[w for w in q.words if w.text!=missing]
        assert totem_identity(q) is None
    q=copy.deepcopy(s)
    for word in q.words:
        if word.text=='抑制图腾' and word.center[1]>100:word.text='治愈图腾'
    assert totem_identity(q) is None


def test_totem_resource_cost_remains_one_and_option_is_enforced(tmp_path,recognition):
    d=daily(tmp_path);d.b.tasker=recognition.tasker
    s=captured('v0944-totem-detail',True)
    d.verify_tribe_detail(s,'抑制图腾')
    d.options['tribe']['random_totem']=False
    with pytest.raises(TaskBlocked,match='未开启'):d.verify_tribe_detail(s)
    d.options['tribe']['random_totem']=True;d.options['tribe']['reserve_orders']=11
    with pytest.raises(ResourceReserveReached):d.verify_tribe_detail(s)
    d.options['tribe']['reserve_orders']=0;d.b.read_number=lambda *a:2
    with pytest.raises(TaskBlocked,match='消耗1战令'):d.verify_tribe_detail(s)


def tribe_scan(d):
    s=captured('v0944-tribe-entry',True)
    d.observe=lambda:s;d.claim_tribe_occupation=lambda q:q
    d.b.save_screen=lambda *a:None
    pans=[]
    d.pan_tribe_map=lambda q,direction:(pans.append(direction) or q,False)
    return s,pans


def test_no_adventure_chooses_random_totem_only_after_both_edges(tmp_path):
    d=daily(tmp_path);s,pans=tribe_scan(d);opened=[]
    detail=captured('v0944-totem-detail',True)
    d.tribe_totem_detail=lambda q,identity=None:opened.append(d._tribe_totem_kind) or detail
    assert d.tribe_detail() is detail
    assert pans==[1,-1] and len(opened)==1 and opened[0] in ('flame','spear')


def test_no_adventure_with_fallback_off_finishes_without_spending(tmp_path):
    d=daily(tmp_path);tribe_scan(d);d.options['tribe']['random_totem']=False;d.home=lambda:None
    d.tribe_totem_detail=lambda *a:pytest.fail('Fallback disabled')
    assert '随机挑战图腾未开启' in d.tribe()
    assert d.battles==0 and not d.report.get('challenge_starts')


def test_unknown_map_or_incomplete_scan_cannot_trigger_totem(tmp_path):
    d=daily(tmp_path);s,_=tribe_scan(d)
    d.pan_tribe_map=lambda q,direction:(q,True)
    d.tribe_totem_detail=lambda *a:pytest.fail('Unconfirmed map bounds')
    with pytest.raises(TaskBlocked,match='边界'):d.tribe_detail()


def test_totem_reentry_uses_verified_current_crest_and_same_identity(tmp_path):
    d=daily(tmp_path);s,_=tribe_scan(d);d._tribe_totem_kind='flame'
    detail=captured('v0944-totem-detail',True);clicks=[]
    d.wait_for_screen=lambda predicate,*a,**kw:detail if predicate(detail) else pytest.fail('Wrong detail predicate')
    d.b.click_at=lambda q,p,a,r:clicks.append((q,p))
    assert d.tribe_totem_detail(s,'抑制图腾') is detail
    assert clicks==[(s,(510,309))]
    with pytest.raises(TaskBlocked,match='图腾目标变化'):d.tribe_totem_detail(s,'治愈图腾')


def test_totem_score_and_reward_are_two_separate_confirmed_states(tmp_path):
    score=captured('v0944-totem-score',True);reward=captured('v0944-totem-reward',True)
    assert totem_score(score) and battle_entry_state(score)=='结算'
    assert not totem_score(reward) and not totem_score(captured('v0944-totem-detail',True))
    d=daily(tmp_path);d.active_task='tribe';d.tribe_orders_before=11
    frames=iter([score,reward]);d.observe=lambda:next(frames);d.b.sleep=lambda _:None
    clicks=[];d.b.click_at=lambda q,p,a,r:clicks.append(r)
    assert d.battle('部落战令') is reward
    assert clicks==['查看部落冒险结算奖励']
    assert d.report['dungeon_resources']['tribe']['remaining']==10


def test_totem_scan_honors_user_stop(tmp_path):
    d=daily(tmp_path);s,_=tribe_scan(d);d._tribe_totem_kind='flame'
    d.b.stop.set()
    with pytest.raises(UserStopped):d.tribe_totem_detail(s)
