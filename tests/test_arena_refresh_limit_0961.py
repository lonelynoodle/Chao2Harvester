"""Three free refreshes per search, then the strongest currently weaker rival."""
import pytest
from chao2.daily_challenges import arena_opponent_key
from chao2.policy import UserStopped,TaskBlocked
from test_configuration import daily,captured
from test_arena_matching_0955 import rows


def search_setup(tmp_path,pages):
    d=daily(tmp_path);s=captured('arena-menu');pages=iter(pages);refreshes=[]
    d.options['arena'].update(opponent='power_gap',teams=[1])
    d.read_arena_candidates=lambda s:(s,next(pages))
    d.refresh_arena=lambda s,c:refreshes.append(c) or s
    return d,s,refreshes


def test_initial_matching_list_never_refreshes(tmp_path):
    d,s,refreshes=search_setup(tmp_path,[rows()])
    _,candidate,search=d.find_arena_opponent(s,1,100000,set())
    assert candidate['power']==90000 and not refreshes
    assert search['refreshes']==0 and not search['fallback']


def test_three_refreshes_choose_strongest_weaker_only_from_current_list(tmp_path):
    old=rows((99999,100001,200000,70000))
    current=rows((99000,100000,100001,20000))
    d,s,refreshes=search_setup(tmp_path,[old]*3+[current])
    _,candidate,search=d.find_arena_opponent(s,1,100000,set())
    assert len(refreshes)==3 and candidate is current[0]  # not old 99999
    assert search['fallback'] and search['selection_mode']=='strongest_below'


def test_range_still_takes_priority_on_third_refreshed_list(tmp_path):
    d,s,refreshes=search_setup(tmp_path,[rows((99000,100000,100001,20000))]*3+[rows()])
    _,candidate,search=d.find_arena_opponent(s,1,100000,set())
    assert len(refreshes)==3 and candidate['power']==90000 and not search['fallback']


def test_fallback_skips_failed_equal_and_stronger_opponents(tmp_path):
    current=rows((99000,98000,100000,100001))
    d,s,refreshes=search_setup(tmp_path,[current]*4)
    _,candidate,search=d.find_arena_opponent(s,1,100000,{arena_opponent_key(current[0])})
    assert candidate is current[1] and len(refreshes)==3


def test_no_weaker_candidate_ends_arena_without_challenge_or_fourth_refresh(tmp_path,monkeypatch):
    from test_daily_challenges import arena_run
    d,_=arena_run(tmp_path,['victory'],monkeypatch)
    d.options['arena'].update(opponent='power_gap',teams=[1])
    d.prepare_arena_team=lambda s,*a:(s,100000)
    d.read_arena_candidates=lambda s:(s,rows((100000,100001,110000,120000)))
    refreshes=[];d.refresh_arena=lambda s,c:refreshes.append(c) or s
    d.b.click_at=lambda *a:pytest.fail('No weaker candidate must not be challenged')
    d.pvp_battle=lambda *a:pytest.fail('No battle')
    message=d.arena()
    assert len(refreshes)==3 and '剩余1次' in message and '免费次数已用完' not in message
    assert d.report['arena_searches'][-1]['status']=='unmatched'
    assert not d.report.get('team_attempts')


def test_each_new_battle_has_its_own_three_refresh_limit(tmp_path,monkeypatch):
    from test_daily_challenges import arena_run
    d,_=arena_run(tmp_path,['victory','victory'],monkeypatch)
    d.options['arena'].update(opponent='power_gap',teams=[1])
    d.prepare_arena_team=lambda s,*a:(s,100000)
    d.read_arena_candidates=lambda s:(s,rows((3000,4000,5000,6000)))
    refreshes=[];d.refresh_arena=lambda s,c:refreshes.append(c) or s
    d.verify_arena_match=lambda s,c,own:d.verified_arena_detail(s,c)
    assert '2场' in d.arena() and len(refreshes)==6
    assert [s['refreshes'] for s in d.report['arena_searches']]==[3,3]
    assert all(r['fallback'] and r['power']==6000 for r in d.report['team_attempts'])
    assert d.report['resource_usage']['arena']['免费次数']['spent']==2


def test_interrupted_existing_search_does_not_reset_refresh_limit(tmp_path):
    d,s,refreshes=search_setup(tmp_path,[rows((3000,4000,5000,6000))])
    d.report['arena_searches']=[{'team':1,'own_power':100000,'mode':'power_gap',
        'instance_id':'arena','refreshes':21,'status':'searching','fallback':False}]
    _,candidate,search=d.find_arena_opponent(s,1,100000,set())
    assert not refreshes and candidate['power']==6000 and search['refreshes']==21
    assert len(d.report['arena_searches'])==1


@pytest.mark.parametrize('change',[{'team':2},{'own_power':150000},{'instance_id':'arena2'}])
def test_another_team_or_instance_does_not_inherit_pending_search(tmp_path,change):
    current=rows((3000,4000,5000,6000));d,s,refreshes=search_setup(tmp_path,[current]*4)
    d.report['arena_searches']=[{'team':1,'own_power':100000,'mode':'power_gap',
        'instance_id':'arena','refreshes':3,'status':'searching',**change}]
    d.find_arena_opponent(s,1,100000,set())
    assert len(refreshes)==3 and len(d.report['arena_searches'])==2


def test_stop_during_refresh_preserves_pending_count_and_never_challenges(tmp_path):
    current=rows((3000,4000,5000,6000));d,s,_=search_setup(tmp_path,[current]*4)
    d.refresh_arena=lambda s,c:d.b.stop.set() or s
    with pytest.raises(UserStopped):d.find_arena_opponent(s,1,100000,set())
    assert d.report['arena_searches'][-1]['refreshes']==1
    assert d.report['arena_searches'][-1]['status']=='searching'


def test_unreadable_list_is_not_used_for_fallback(tmp_path):
    d,s,_=search_setup(tmp_path,[rows()[:3]])
    with pytest.raises(TaskBlocked,match='四个'):d.find_arena_opponent(s,1,100000,set())
