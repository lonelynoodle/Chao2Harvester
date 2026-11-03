"""2026-10-26 captured regressions; offline OCR and bounded navigation only."""
import copy
from types import SimpleNamespace

import pytest

from test_configuration import captured,daily,screen
from test_maa_recognition import Offline
from test_tower_switch import TowerNavigationGame,KINDS
from chao2.backend import Backend,ROOT,Word
from chao2.policy import TaskBlocked,UserStopped
from chao2.rift import rift_node
from chao2.star_supply import evolution_result_name
from chao2.wild_settings import wild_options,required_traps
from maa.resource import Resource
from maa.tasker import Tasker


@pytest.fixture(scope='module')
def recognition():
    controller=Offline();assert controller.post_connection().wait().succeeded
    resource=Resource();assert resource.post_bundle(ROOT/'resource').wait().succeeded
    tasker=Tasker();assert tasker.bind(resource,controller)
    b=Backend({},log=lambda _:None);b.tasker=tasker
    yield b


def test_tower_recognizes_actual_overview_landing(tmp_path):
    d=daily(tmp_path)
    assert d.tower_navigation_state(captured('v0946-tower-blocked'))=='overview'


@pytest.mark.parametrize('reopen_same',[False,True])
def test_tower_return_to_overview_reenters_once_without_extra_back(tmp_path,monkeypatch,reopen_same):
    g=TowerNavigationGame(tmp_path,monkeypatch,start='secrets',floor_exit='overview')
    g.pages['overview']=captured('v0946-tower-blocked')
    def entry(key,**kw):
        assert key=='tower' and g.page=='overview'
        g.inputs.append(('enter','overview'));g.page='selector'
        return g.pages['selector']
    g.d.overview_entry=entry
    if reopen_same:
        g.secret_exit='overview';g.d.tower_map()
        assert g.inputs==[('back','secrets'),('enter','overview'),('select','无限制')]
    else:
        g.d.open_tower(KINDS[1])
        assert g.inputs==[('back','secrets'),('back','floors'),('enter','overview'),('select','祖龙族')]
    assert g.d.report['tower_navigation'][-1]['destination']=='overview'


def test_actual_main_five_cost_uses_verified_local_ocr(tmp_path,recognition):
    d=daily(tmp_path);d.b.tasker=recognition.tasker
    s=captured('v0946-main-blocked',True)
    assert not s.find('^5$',(1020,625,160,45))
    d.verify_stamina_cost(s,5)


@pytest.mark.parametrize('change',['different_cost','no_icon','wrong_page'])
def test_main_cost_fallback_does_not_bypass_fee_checks(tmp_path,recognition,change):
    d=daily(tmp_path);d.b.tasker=recognition.tasker;s=captured('v0946-main-blocked',True)
    if change=='different_cost':s.words.append(Word('50',[1100,637,28,25],.99))
    if change=='no_icon':s.image[630:670,1060:1105]=0
    if change=='wrong_page':s.words=[w for w in s.words if w.text!='敌方阵容']
    with pytest.raises(TaskBlocked,match='只消耗5'):d.verify_stamina_cost(s,5)


def test_actual_glowing_rift30_label_is_fully_read(recognition):
    kind,point=rift_node(recognition,captured('v0946-rift-blocked',True),30)
    assert kind=='next' and point==pytest.approx((481,432),abs=2)
    assert rift_node(recognition,captured('v0946-rift-blocked',True),31)[0]=='locked'


def test_visible_rift_target_is_reobserved_three_times_never_swiped(tmp_path,monkeypatch):
    import chao2.rift as module
    d=daily(tmp_path);s=captured('v0946-rift-blocked',True);reads=[]
    d.observe=lambda:reads.append(1) or s;d.b.sleep=lambda _:None
    d.b.controller=SimpleNamespace(post_swipe=lambda *a:pytest.fail('Visible target must not be panned away'))
    monkeypatch.setattr(module,'rift_node',lambda *a:None)
    with pytest.raises(TaskBlocked,match='原地|重读3次'):d.rift_locate(s,30)
    assert len(reads)==3


def test_rift_visible_glow_can_stabilize_on_retry(tmp_path,monkeypatch):
    import chao2.rift as module
    d=daily(tmp_path);s=captured('v0946-rift-blocked');reads=[]
    answers=iter([None,None,('next',(481,432))])
    monkeypatch.setattr(module,'rift_node',lambda *a:next(answers))
    d.observe=lambda:reads.append(1) or s;d.b.sleep=lambda _:None
    assert d.rift_locate(s,30)[1]==('next',(481,432)) and len(reads)==2


def test_actual_evolution_reveal_uses_badge_despite_ocr_typo(recognition):
    s=captured('v0946-star_spores-blocked',True)
    assert not s.find('^究极$') and evolution_result_name(recognition,s)=='极限'
    s.image[55:135,12:90]=0
    assert evolution_result_name(recognition,s) is None


def evolution_game(tmp_path,monkeypatch,recognition,drops=0):
    d=daily(tmp_path);d.b.tasker=recognition.tasker
    reveal=captured('v0946-star_spores-blocked',True)
    info=captured('v0927-purple-info',True)
    d.b.read_number=lambda *a:1;d.b.sleep=lambda _:None
    d.day['star_evolution_pending']={'name':'极限','gold':85000,'spores':45,'status':'submitted'}
    g={'page':reveal,'clicks':0};d.observe=lambda *a:g['page']
    def click(s,point,anchors,reason):
        assert point==(640,660) and s.has(*anchors) and '关闭' in reason
        g['clicks']+=1
        if g['clicks']>drops:g['page']=info
    d.b.click_at=click
    d.one_blue_roster=lambda:pytest.fail('Never replay an evolution')
    ticks=iter(i*.5 for i in range(2000))
    monkeypatch.setattr('chao2.navigation_retry.time',SimpleNamespace(monotonic=lambda:next(ticks)))
    return d,g,reveal,info


@pytest.mark.parametrize('drops',[0,1,3])
def test_evolution_reveal_close_retries_without_spending_again(tmp_path,monkeypatch,recognition,drops):
    d,g,reveal,info=evolution_game(tmp_path,monkeypatch,recognition,drops)
    assert d.complete_star_evolution(reveal) is info
    assert g['clicks']==drops+1 and 'star_evolution_pending' not in d.day
    assert d.report['other_tasks']['star_spores']['evolved']==1
    assert d.report['star_evolutions'][0]['resumed']


def test_evolution_reveal_close_is_bounded_and_keeps_pending(tmp_path,monkeypatch,recognition):
    d,g,reveal,_=evolution_game(tmp_path,monkeypatch,recognition,99)
    with pytest.raises(TaskBlocked,match='重试3次'):d.complete_star_evolution(reveal)
    assert g['clicks']==4 and d.day['star_evolution_pending']['reveal_seen']
    assert not d.report.get('star_evolutions')


def test_wrong_evolution_name_does_not_clear_transaction_or_click(tmp_path,monkeypatch,recognition):
    d,g,reveal,_=evolution_game(tmp_path,monkeypatch,recognition)
    d.day['star_evolution_pending']['name']='轮脉'
    with pytest.raises(TaskBlocked,match='尚未'):d.complete_star_evolution(reveal)
    assert g['clicks']==0 and d.day['star_evolution_pending']['name']=='轮脉'


def test_evolution_recovery_honors_stop(tmp_path,monkeypatch,recognition):
    d,g,reveal,_=evolution_game(tmp_path,monkeypatch,recognition)
    d.b.stop.set()
    with pytest.raises(UserStopped):d.complete_star_evolution(reveal)
    assert g['clicks']==0 and 'star_evolution_pending' in d.day


def test_home_recovers_pending_evolution_before_other_navigation(tmp_path,recognition):
    from chao2.workflows import is_world
    d=daily(tmp_path);d.b.tasker=recognition.tasker
    reveal=captured('v0946-star_spores-blocked',True);world=captured('v0913-main-world',True)
    d.day['star_evolution_pending']={'name':'极限'};called=[]
    def complete(s):
        called.append(s);d.day.pop('star_evolution_pending');return world
    d.complete_star_evolution=complete
    assert is_world(d.home(reveal)) and called==[reveal]


@pytest.mark.parametrize('before,after',[(5,90),(80,90),(85,90),(90,90),(95,95),(100,100)])
def test_blue_capture_minimum_migrates_without_changing_selection(before,after):
    raw={'wild_capture':{'phantom':{'enabled':True,'probability':before},
                         'ultimate':{'enabled':False,'probability':80}}}
    original=copy.deepcopy(raw);result=wild_options(raw)
    assert raw==original and result['phantom']=={'enabled':True,'probability':after}
    assert result['ultimate']==raw['wild_capture']['ultimate']
    assert required_traps(90,result['phantom']['probability'])==(after-90)//5
