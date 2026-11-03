"""World pathing can resume after a merchant with no hunt sidebar behind it."""
import copy
import pytest

from chao2.backend import Screen,Word
from chao2.merchant import merchant_return_page
from chao2.policy import EncounterInterrupted,TaskBlocked,SafetyStop,UserStopped
from chao2.result_navigation import exit_destination
from chao2.workflows import is_world
from chao2.world_events import is_map_choice,map_choice_controls,map_choice_hunt_target
from test_configuration import captured,daily,screen
from test_hunt_single_team import hunt_menu
from test_run_0950 import fast_waits


def choice():return captured('v0957-hunt-world-choice',True)
def world():return captured('v0957-merchant-world-return',True)


def detail(name='未知',balance=228,cost=10):
    return screen(('敌方阵容',1130,135,103,28),('排阵',824,614,61,34),
        ('前往挑战',1036,607,109,28),(name,134,136,90,30),
        ('09:35',602,135,72,26),(str(cost),1096,639,28,18),
        (f'{balance}/179',1185,17,76,22))


def test_actual_world_choice_uses_modal_anchors_without_sidebar():
    s=choice()
    assert not s.has('^商店$','^传送$')
    assert is_map_choice(s) and not is_world(s)
    assert map_choice_controls(s)[1].center==(745,246)
    assert map_choice_hunt_target(s).center==(612,395)
    assert exit_destination(s)==merchant_return_page(s)=='map_choice'
    s.words.extend(world().words)
    assert not is_world(s)  # Never click through readable background HUD.


@pytest.mark.parametrize('missing',['请选择','狩猎','未知'])
def test_own_text_and_icon_are_required_without_sidebar(missing):
    s=choice();s.words=[w for w in s.words if w.text!=missing]
    assert not is_map_choice(s) and map_choice_hunt_target(s) is None


def test_missing_hunter_icon_does_not_accept_only_two_labels_and_x():
    s=choice();s.image[375:452,430:510]=0
    assert not is_map_choice(s)


def test_close_icon_can_be_verified_when_ocr_misses_it():
    s=choice();s.words=[w for w in s.words if w.text!='x']
    assert is_map_choice(s)
    s.image[225:270,725:770]=0
    assert not is_map_choice(s)


@pytest.mark.parametrize('label',['取消','确定','购买','获得奖励','排阵','退出','敌方阵容'])
def test_other_modal_or_battle_is_never_selected_as_hunt(label):
    s=choice();s.words.append(Word(label,[600,450,100,35],.99))
    assert not is_map_choice(s)


def test_two_hunt_rows_are_not_guessed(tmp_path):
    d=daily(tmp_path);s=choice();s.words.append(Word('狩猎',[590,480,50,26],.99))
    assert is_map_choice(s) and map_choice_hunt_target(s) is None
    d.b.click_at=lambda *a:pytest.fail('Ambiguous target')
    with pytest.raises(TaskBlocked,match='唯一狩猎'):d.open_hunt_choice(s)


def test_home_closes_world_choice_before_returning_world(tmp_path):
    d=daily(tmp_path);dest=world();d.observe=lambda:dest;clicks=[]
    d.b.click_at=lambda s,p,*a:clicks.append(p)
    assert d.home(choice()) is dest and clicks==[(745,246)]
    assert d.battles==0 and not d.search_counts


@pytest.mark.parametrize('delay',[False,True])
def test_hunt_menu_accepts_world_after_close_and_reopens_overview(tmp_path,monkeypatch,delay):
    d=daily(tmp_path);d.active_task='hunt';fast_waits(d,monkeypatch)
    popup=choice();dest=world();menu=hunt_menu(1)
    frames=iter([popup,*([popup,screen()] if delay else []),dest]);clicks=[];opened=[]
    d.observe=lambda:next(frames)
    d.b.click_at=lambda s,p,*a:clicks.append(p)
    d.enter_overview=lambda p:opened.append(p) or menu
    assert d.hunt_menu() is menu and clicks==[(745,246)] and opened==['^狩猎$']
    assert not d.search_counts and not d.task_counts


def test_still_visible_close_retries_three_times_without_search(tmp_path,monkeypatch):
    d=daily(tmp_path);d.active_task='hunt';fast_waits(d,monkeypatch)
    d.observe=choice;clicks=[];d.b.click_at=lambda s,p,*a:clicks.append(p)
    d.enter_overview=lambda *a:pytest.fail('Modal still visible')
    with pytest.raises(TaskBlocked,match='重试3次'):d.hunt_menu()
    assert clicks==[(745,246)]*4 and not d.search_counts


def test_await_detail_selects_hunt_not_neighboring_world_stage(tmp_path,monkeypatch):
    d=daily(tmp_path);d.active_task='hunt';fast_waits(d,monkeypatch)
    dest=detail();frames=iter([choice(),choice(),screen(),dest]);d.observe=lambda:next(frames)
    clicks=[];d.b.click_at=lambda s,p,*a:clicks.append(p)
    assert d.await_detail(hunt_target=(1,0)) is dest and clicks==[(612,395)]
    assert d.battles==0 and not d.search_counts


@pytest.mark.parametrize('same_target',[True,False])
def test_interrupted_hunt_reopens_same_slot_and_rechecks_identity(tmp_path,same_target):
    d=daily(tmp_path);d.active_task='hunt';d.b.sleep=lambda _:None
    menu=hunt_menu(1);empty=hunt_menu(0);state=[menu];clicks=[];launches=[];teams=[];overviews=[]
    d.observe=lambda:state[0]
    d.hunt_stock=lambda s:0;d.hunt_search_offer=lambda s:None
    d.select_team=lambda s,t:teams.append(t) or s
    d.home=lambda:world()
    def overview(pattern):
        assert is_world(state[0]);overviews.append(pattern);state[0]=menu;return menu
    d.enter_overview=overview
    def click(s,p,anchors,reason):
        clicks.append(reason)
        if reason=='收起地图重叠目标选择框':state[0]=world()
        else:state[0]=detail('未知' if same_target or not launches else '其他猎物')
    d.b.click_at=click
    def start(*a):
        launches.append(a)
        if len(launches)==1:
            state[0]=choice()
            raise EncounterInterrupted('商人已结束，原寻路弹出重叠目标')
    d.start_challenge=start
    def battle(*a):
        d.battles+=1;d.task_counts['hunt']=1
        return screen(('胜利',100,200,100,40))
    d.battle=battle;d.exit_result=lambda s:state.__setitem__(0,empty)
    if same_target:
        assert '通关1次' in d.run_hunt()
        assert len(launches)==2 and d.battles==1 and len(d.report['team_attempts'])==1
        assert teams==[2,2] and d.report['hunt_batch']['remaining']==0
    else:
        with pytest.raises(TaskBlocked,match='猎物身份改变'):d.run_hunt()
        assert len(launches)==1 and d.battles==0 and not d.report.get('team_attempts')
    assert clicks==['检查猎物','收起地图重叠目标选择框','重试同一猎物']
    assert overviews==['^狩猎$'] and not d.search_counts


@pytest.mark.parametrize('destination',['detail','combat','changed','debit','cost'])
def test_choice_during_challenge_start_preserves_launch_checks(tmp_path,destination):
    d=daily(tmp_path);d.active_task='hunt';d.b.sleep=lambda _:None
    original=detail();state=[original];actions=[];checks=[]
    combat=screen(('自动',95,600,48,28),('01:50',600,10,80,30))
    next_page={'detail':original,'combat':combat,'changed':detail('其他猎物'),
               'debit':detail(balance=218),'cost':detail(cost=20)}[destination]
    d.observe=lambda:state[0]
    def launch(s,p,**kw):
        actions.append('challenge');state[0]=choice() if actions.count('challenge')==1 else combat
    d.b.click_text=launch
    def choose(s,p,*a):
        assert p==(612,395);actions.append('hunt');state[0]=next_page
    d.b.click_at=choose
    def verify(s):checks.append(s);d.verify_stamina_cost(s,10)
    if destination in ('changed','debit','cost'):
        with pytest.raises(TaskBlocked):d.start_challenge('hunt',original,'地图体力10',verify)
        assert actions==['challenge','hunt']
    else:
        assert d.start_challenge('hunt',original,'地图体力10',verify) is combat
        assert actions==(['challenge','hunt','challenge'] if destination=='detail' else ['challenge','hunt'])
        assert len(checks)==int(destination=='detail')
    assert d.battles==0 and not d.task_counts and not d.search_counts


def test_stop_prevents_modal_input(tmp_path):
    d=daily(tmp_path);d.observe=choice;d.b.stop.set()
    d.b.click_at=lambda *a:pytest.fail('Stopped')
    with pytest.raises(UserStopped):d.hunt_menu()


def test_real_maa_recognizes_standalone_hunter_modal():
    from test_maa_recognition import Offline
    from maa.resource import Resource
    from maa.tasker import Tasker
    from maa.pipeline import JOCR
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle('resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    original=choice()
    result=t.post_recognition('OCR',JOCR(roi=[0,0,1280,720],threshold=.5),original.image).wait().get()
    words=[Word(w.text,w.box,w.score) for n in result.nodes if n.recognition for w in n.recognition.all_results]
    actual=Screen(original.image,words,original.when)
    assert is_map_choice(actual) and map_choice_hunt_target(actual).center==(612,395)
    assert not is_world(actual)
