"""2026-10-31 rift title, previous-stage fallback and first-clear OCR regressions."""
import pytest
from test_configuration import captured,daily,screen
from test_rift import fake_rift
from test_maa_recognition import Offline
from maa.resource import Resource
from maa.tasker import Tasker
from chao2.backend import Backend,ROOT
from chao2.activities import recover_main_detail,is_main_detail,main_identity,BudgetReached
from chao2.rift import recover_rift_detail,rift_detail,rift_level_locked,verify_free_rift
from chao2.policy import TaskBlocked,UserStopped


@pytest.fixture(scope='module')
def offline_backend():
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({},log=lambda _:None);b.tasker=t
    yield b


def test_actual_maa_recovers_both_31s_and_keeps_level_gate(offline_backend):
    original=captured('v0959-rift-blocked',True)
    assert rift_detail(original) is None
    fixed=recover_rift_detail(offline_backend,original)
    assert fixed is not original and fixed.when==original.when
    assert rift_detail(fixed)==31 and rift_level_locked(fixed)
    assert rift_detail(original) is None
    with pytest.raises(TaskBlocked,match='解锁等级'):verify_free_rift(offline_backend,fixed,31)


@pytest.mark.parametrize('name',['v0959-main-blocked','v0959-main-previous'])
def test_actual_maa_reads_complete_first_clear_label(offline_backend,name):
    original=captured(name,True)
    assert is_main_detail(original) and not original.find('^首通奖励$')
    fixed=recover_main_detail(offline_backend,original)
    assert fixed is not original and fixed.when==original.when
    assert fixed.find('^首通奖励$',(30,550,100,40))
    assert main_identity(fixed)==main_identity(original)
    assert not original.find('^首通奖励$')


def test_actual_completed_main_cannot_acquire_first_clear_rewards(offline_backend):
    original=captured('v091-completed-detail',True)
    assert is_main_detail(original)
    assert recover_main_detail(offline_backend,original) is original
    assert not original.find('^首通奖励$')


@pytest.mark.parametrize('reads',[
    ['31-凿星裂痕关卡3']*2,
    ['31-凿星裂痕关卡31','31-凿星裂痕关卡3'],
    ['30-凿星裂痕关卡30']*2,
    ['31-凿星裂痕关卡30']*2,
    ['',''],
])
def test_rift_crop_requires_agreement_on_both_numbers_and_original_prefix(tmp_path,reads):
    d=daily(tmp_path);d.b.tasker=object();source=captured('v0959-rift-blocked')
    answers=iter(reads);d.b.read_text_crop=lambda *_:next(answers)
    assert recover_rift_detail(d.b,source) is source
    assert rift_detail(source) is None


def test_rift_local_confirmation_does_not_ignore_stop(tmp_path):
    d=daily(tmp_path);d.b.tasker=object()
    def stopped(*_):raise UserStopped('用户停止')
    d.b.read_text_crop=stopped
    with pytest.raises(UserStopped):recover_rift_detail(d.b,captured('v0959-rift-blocked'))


@pytest.mark.parametrize('name',['v0959-rift-blocked','v0959-main-blocked'])
def test_observe_applies_calibration_to_all_navigation_and_saves_evidence(tmp_path,offline_backend,name):
    d=daily(tmp_path);d.b.tasker=offline_backend.tasker
    source=captured(name,True);saved=[]
    d.b.observe=lambda *_:source
    d.b.save_screen=lambda s,path:saved.append((s,path))
    d.calibrate_collection_reward=lambda s:s;d.recover_world_navigation=lambda s:s
    result=d.observe(dismiss_popups=False)
    assert result is not source and saved[-1][0] is result and d.last_screen is result
    if name=='v0959-rift-blocked':assert rift_detail(result)==31
    else:assert result.find('^首通奖励$')


def test_overview_accepts_the_recovered_main_detail(tmp_path,offline_backend):
    d=daily(tmp_path);fixed=recover_main_detail(offline_backend,captured('v0959-main-blocked',True))
    entry=screen(('玩法概览',300,50,100,30),('每日挑战',500,50,100,30),('世界关卡',360,100,120,30))
    d.find_overview_entry=lambda *_:(entry,'target',entry.find('世界关卡'))
    d.observe=lambda:fixed;d.resolve_path_event=lambda *_:None
    clicks=[];d.b.click_at=lambda *a:clicks.append(a)
    assert d.enter_overview('^世界关卡$') is fixed
    assert len(clicks)==1 and clicks[0][3]=='前往世界关卡'


@pytest.mark.parametrize('name,allowed',[
    ('v0959-main-blocked',True),('v0959-main-previous',True),('v091-completed-detail',False)])
def test_main_entry_still_requires_complete_first_clear_text(tmp_path,offline_backend,name,allowed):
    d=daily(tmp_path);fixed=recover_main_detail(offline_backend,captured(name,True))
    d.options['main']['max_nodes']=1
    d.overview_prepared_for=lambda *_:True;d.main_overview_detail=lambda:fixed
    d.observe=lambda:fixed;d.b.sleep=lambda _:None
    d.home=lambda:None;costs=[]
    d.verify_stamina_cost=lambda s,cost:costs.append(cost)
    def encounter(task,opener,resource,verify):verify(opener());return False
    d.play_encounter=encounter
    if allowed:
        d.main();assert costs==[5]
    else:
        with pytest.raises(TaskBlocked,match='首通奖励'):d.main()
        assert costs==[]


def test_level_gate_is_remembered_after_selecting_previous_stage(tmp_path,offline_backend):
    d=daily(tmp_path);menu=captured('v084-rift-map24')
    locked=captured('v084-rift-detail25-locked');opened=[]
    d.rift_map=lambda:menu;d.rift_locate=lambda s,n:(s,('next',(440,440)))
    d.rift_open_stage=lambda s,n:opened.append(n) or (locked if n==25 else captured('v084-rift-detail24'))
    assert d.rift_highest(menu)[1]==24
    assert d.rift_highest(menu)[1]==24
    assert opened==[25,24,24]
    assert d.report['rift_fallbacks']==[{'from':25,'to':24,'reason':'探索者等级不足'}]


def test_previous_stage_can_fall_back_again_and_only_wins_spend_keys(tmp_path,monkeypatch):
    d=daily(tmp_path);state=fake_rift(d,monkeypatch,keys=2,outcomes=['failed']*4)
    d.rift()
    assert state['opened']==[24,24,23,23,22,22]
    assert state['teams']==[2,1,2,1,2,2] and state['claimed']==[22,22]
    assert [(r['from'],r['to']) for r in d.report['rift_fallbacks']]==[(24,23),(23,22)]
    assert d.report['resource_usage']['rift']['裂痕钥匙']['spent']==2


def test_failed_stage_one_stops_without_zero_or_key_use(tmp_path,monkeypatch):
    d=daily(tmp_path);state=fake_rift(d,monkeypatch,outcomes=['failed']*2);state['stage']=1
    message=d.rift()
    assert state['opened']==[1,1] and state['claimed']==[] and state['keys']==5
    assert '第1关' in message and d.report['rift_fallbacks'][0]['to'] is None


def test_fallback_respects_key_reserve(tmp_path,monkeypatch):
    d=daily(tmp_path);d.options['rift']['reserve_keys']=3
    state=fake_rift(d,monkeypatch,outcomes=['failed']*2)
    d.rift()
    assert state['keys']==3 and state['claimed']==[23,23]


def test_run_limit_prevents_starting_previous_stage(tmp_path,monkeypatch):
    d=daily(tmp_path);d.options['rift']['max_runs']=2
    state=fake_rift(d,monkeypatch,outcomes=['failed']*2)
    d.rift()
    assert state['opened']==[24,24] and state['keys']==5 and state['starts']==2


def test_stage_ceiling_is_reset_for_next_run(tmp_path,monkeypatch):
    d=daily(tmp_path);state=fake_rift(d,monkeypatch,keys=1,outcomes=['failed']*2)
    d.rift();assert state['claimed']==[23]
    state=fake_rift(d,monkeypatch,keys=1)
    d.rift();assert state['opened']==[24] and state['claimed']==[24]
