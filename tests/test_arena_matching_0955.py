"""Opponent selection, real slanted digits, cold refreshes and team identity."""
import time
import pytest
from chao2.configuration import normalize_settings
from chao2.daily_challenges import choose_opponent,ARENA_CARDS,arena_candidates,arena_opponent_key
from chao2.policy import TaskBlocked,SafetyStop,UserStopped
from test_configuration import captured,daily

def rows(powers=(110000,90000,80000,99000)):
    return [dict(index=i,power=p,name=str(i),rating=2000,point=(427,452)) for i,p in enumerate(powers)]

def test_new_defaults_and_legacy_saved_mode_and_instance_migration():
    settings=normalize_settings({});a=settings['task_options']['arena']
    assert (a['opponent'],a['power_gap_min'],a['power_gap_max'])==('power_gap',10000,20000)
    saved=normalize_settings({'task_options':{'arena':{'opponent':'weakest','teams':[3]}}})
    assert saved['task_options']['arena']['opponent']=='weakest'
    assert saved['task_options']['arena']['teams']==[3]
    q=normalize_settings({'task_queue':[{'id':'arena1','key':'arena','options':{'opponent':'strongest_below'}}]})
    assert q['task_queue'][0]['options']['power_gap_min']==10000

@pytest.mark.parametrize('values',[{'power_gap_min':20001},{'power_gap_min':0},
    {'power_gap_max':-1},{'power_gap_min':True},{'power_gap_max':1.5},{'power_gap_max':100000000}])
def test_invalid_gap_rejected_before_connection(values):
    with pytest.raises(ValueError):normalize_settings({'task_options':{'arena':values}})

def test_strongest_eligible_and_inclusive_gap_and_no_silent_fallback():
    opponents=rows()
    assert choose_opponent(opponents,'strongest_below',100000)['power']==99000
    assert choose_opponent(opponents,'power_gap',100000)['power']==90000
    assert choose_opponent(rows((90001,89999,80000,79999)),'power_gap',100000)['power']==89999
    assert choose_opponent(rows((80000,100000,100001,79999)),'power_gap',100000)['power']==80000
    assert choose_opponent(rows((100000,110000,120000,130000)),'strongest_below',100000) is None
    assert choose_opponent(rows((90001,100000,20000,79999)),'power_gap',100000) is None
    assert choose_opponent(opponents,'power_gap',100000,15000,21000)['power']==80000
    with pytest.raises(TaskBlocked):choose_opponent(opponents,'power_gap')

def test_failed_opponent_is_excluded_only_for_the_selected_team():
    opponents=rows();losses={2:{arena_opponent_key(opponents[1])}}
    assert choose_opponent(opponents,'power_gap',100000,excluded=losses[2])['power']==80000
    assert choose_opponent(opponents,'power_gap',100000,excluded=losses.get(3,set()))['power']==90000

def test_actual_maa_power_digits_and_free_control(tmp_path):
    from test_maa_recognition import Offline
    from maa.resource import Resource
    from maa.tasker import Tasker
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle('resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    d=daily(tmp_path);d.b.tasker=t
    s=captured('v0955-arena-list',True)
    assert [d.read_arena_power(s,roi) for roi,_ in ARENA_CARDS]==[121280,70599,33966,63403]
    detail=captured('v0955-arena-own-team',True)
    assert d.arena_own_power(detail)==104970
    assert d.read_arena_power(detail,(1112,432,91,35))==112291
    ready=captured('v0955-arena-refresh',True);cooldown=captured('v0955-arena-cooldown',True)
    assert [d.read_arena_power(ready,roi) for roi,_ in ARENA_CARDS]==[112291,121280,165847,32099]
    assert d.b.match_template(ready,'arena-free-refresh.png',[1170,620,100,90],.90)
    assert not d.b.match_template(cooldown,'arena-free-refresh.png',[1170,620,100,90],.90)
    d.b.confirm_label(ready,'^换一批$',(1160,610,120,110),threshold=.8)
    assert ready.find('^换一批$',(1160,610,120,110))

def test_team_is_applied_before_reading_attacking_power(tmp_path):
    d=daily(tmp_path);s=captured('arena-menu');detail=captured('v0955-arena-own-team');events=[]
    d.read_arena_candidates=lambda s:(s,rows())
    d.b.click_at=lambda *a,**kw:events.append('navigate')
    d.arena_detail=lambda:detail;d.select_team=lambda s,t,**kw:events.append(('team',t)) or s
    d.arena_own_power=lambda s:events.append('own_power') or 104970
    d.b.save_screen=lambda *a:None;d.await_page=lambda *a:s
    assert d.prepare_arena_team(s,3,True)==(s,104970)
    assert events==['navigate',('team',3),'own_power','navigate']

def test_power_change_after_matching_blocks_challenge(tmp_path):
    d=daily(tmp_path);s=captured('arena-detail');candidate=rows()[1]
    d.verified_arena_detail=lambda s,c:(s,5)
    d.arena_own_power=lambda s:100001
    with pytest.raises(TaskBlocked,match='己方'):d.verify_arena_match(s,candidate,100000)
    d.arena_own_power=lambda s:100000;d.read_arena_power=lambda *a:95000
    with pytest.raises(TaskBlocked,match='对手战力'):d.verify_arena_match(s,candidate,100000)

def refresh_simulation(tmp_path,monkeypatch):
    from chao2 import daily_challenges as module
    from chao2.backend import Word
    clock=[0];monkeypatch.setattr(module.time,'monotonic',lambda:clock[0])
    d=daily(tmp_path);s=captured('v0955-arena-refresh');cool=captured('v0955-arena-cooldown')
    s.words.append(Word('换一批',[1180,675,70,25],.99))
    clicks=[];d.read_pvp_quota=lambda *a:5
    d.b.match_template=lambda q,*a:q is s;d.b.confirm_label=lambda *a,**kw:False
    d.b.click_at=lambda *a,**kw:clicks.append(a[1])
    d.b.sleep=lambda n:clock.__setitem__(0,clock[0]+n)
    def observe():
        q=cool if clicks or clock[0]<10 else s;q.when=clock[0];return q
    d.observe=observe
    d.read_arena_candidates=lambda q:(q,rows((95000,92000,85000,81000)))
    return d,s,cool,clock,clicks

def test_refresh_waits_cooldown_sends_once_and_verifies_new_list(tmp_path,monkeypatch):
    d,s,cool,clock,clicks=refresh_simulation(tmp_path,monkeypatch)
    assert d.refresh_arena(cool,rows()) is cool
    assert clock[0]>=10 and len(clicks)==1 and d.report['arena_refreshes']==1
    assert d.battles==0 and d.task_counts.get('arena',0)==0

def test_unknown_or_paid_refresh_is_not_clicked(tmp_path,monkeypatch):
    from chao2.backend import Word
    d,s,cool,clock,clicks=refresh_simulation(tmp_path,monkeypatch)
    s.words.append(Word('50钻石',[1180,640,70,25],.99))
    def observe():s.when=clock[0];return s
    d.observe=observe
    with pytest.raises(TaskBlocked,match='未就绪'):d.refresh_arena(s,rows())
    assert not clicks

def test_stop_and_empty_quota_interrupt_search_without_click(tmp_path,monkeypatch):
    d,s,cool,clock,clicks=refresh_simulation(tmp_path,monkeypatch)
    d.read_pvp_quota=lambda *a:0
    with pytest.raises(TaskBlocked,match='无免费次数'):d.refresh_arena(s,rows())
    d.read_pvp_quota=lambda *a:5
    d.check_budget=lambda *a:(_ for _ in ()).throw(UserStopped('stop'))
    with pytest.raises(UserStopped):d.refresh_arena(cool,rows())
    assert not clicks

def test_arena_repeats_refresh_until_match_and_rechecks_each_fight(tmp_path,monkeypatch):
    from test_daily_challenges import arena_run
    d,teams=arena_run(tmp_path,['victory','victory'],monkeypatch)
    d.options['arena'].update(opponent='power_gap',teams=[2,3])
    powers=iter([100000,150000]);previews=[]
    def prepare(s,team,change):
        previews.append((team,change));return s,next(powers)
    d.prepare_arena_team=prepare
    sets=iter([rows((200000,120000,50000,79999)),rows((100001,99000,75000,74000)),rows(),rows((160000,140000,130000,150000))])
    d.read_arena_candidates=lambda s:(s,next(sets));refresh=[]
    d.refresh_arena=lambda s,c:refresh.append(c) or s
    d.verify_arena_match=lambda s,c,own:d.verified_arena_detail(s,c)
    assert '2场' in d.arena()
    assert len(refresh)==2 and previews==[(2,True),(3,True)]
    assert [x['power'] for x in d.report['team_attempts']]==[90000,140000]
    assert [x['power_gap'] for x in d.report['team_attempts']]==[10000,10000]
    assert not teams  # Selection happened during preparation, before matching.
