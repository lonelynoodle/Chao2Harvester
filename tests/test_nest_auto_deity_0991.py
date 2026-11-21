"""Auto release for nest and main only toggles a verified manual battle HUD."""
from copy import deepcopy
import time
import pytest
from chao2.backend import Word
from chao2.configuration import normalize_settings
from chao2.policy import UserStopped
from test_configuration import daily,screen,captured
from test_rift_main_0959 import offline_backend
from test_click_read_recovery_0987 import buff


def battle(mode='手动'):
    return screen(('08:06',600,5,78,33),(mode,94,604,44,23),('X2',10,600,50,28))


@pytest.mark.parametrize('task',['main','nest'])
def test_auto_deity_defaults_on_without_overwriting_explicit_queue_choice(task):
    settings={'allow_repeat_tasks':True,'task_options':{task:{'auto_deity':False}},
              'task_queue':[{'id':'n1','key':task,'options':{'auto_deity':False}},
                            {'id':'n2','key':task,'options':{}}]}
    original=deepcopy(settings);q=normalize_settings(settings)
    assert settings==original and not q['task_options'][task]['auto_deity']
    assert [r['options']['auto_deity'] for r in q['task_queue']]==[False,True]


@pytest.mark.parametrize('task',['main','nest'])
@pytest.mark.parametrize('value',[1,'yes',None])
def test_auto_deity_requires_boolean(task,value):
    with pytest.raises(ValueError):normalize_settings({'task_options':{task:{'auto_deity':value}}})


def test_manual_mode_clicks_only_its_control_then_confirms_auto(tmp_path):
    d=daily(tmp_path);calls=[];state={'clicks':0}
    d.b.click_at=lambda s,p,a,r:calls.append((s,p,a,r))
    s=battle();assert d.enable_battle_auto_deity('nest',s,state)
    assert calls[0][1]==s.find('^手动$').center and s.has(*calls[0][2])
    assert not d.enable_battle_auto_deity('nest',battle('自动'),state) and state['confirmed']
    assert not d.enable_battle_auto_deity('nest',battle(),state) and len(calls)==1


@pytest.mark.parametrize('mode',['自动','手动'])
def test_disabled_mode_does_not_inspect_or_click(tmp_path,mode):
    d=daily(tmp_path);d.options['nest']['auto_deity']=False
    d.b.click_at=lambda *a:pytest.fail('Disabled option must not toggle')
    assert not d.enable_battle_auto_deity('nest',battle(mode),{})


@pytest.mark.parametrize('change',['timer','detail','result','buff','modal','wrong_position'])
def test_mode_text_alone_cannot_authorize_a_toggle(tmp_path,change):
    d=daily(tmp_path);s=battle()
    if change=='timer':s.words=[w for w in s.words if w.text!='08:06']
    elif change=='detail':s.words.append(Word('排阵',[824,614,60,35],.99))
    elif change=='result':s.words.append(Word('退出',[1120,600,60,30],.99))
    elif change=='buff':s.words+=buff().words
    elif change=='modal':s.words.append(Word('确定',[700,480,60,30],.99))
    else:s.find('^手动$').box=[450,300,44,23]
    d.b.click_at=lambda *a:pytest.fail('Only a live left HUD may be tapped')
    assert not d.enable_battle_auto_deity('main',s,{})


def test_missed_click_retries_on_fresh_manual_frames_with_small_offsets(tmp_path,monkeypatch):
    d=daily(tmp_path);clock=[0];monkeypatch.setattr(time,'monotonic',lambda:clock[0])
    state={'clicks':0};points=[];d.b.click_at=lambda s,p,*a:points.append(p)
    for i in range(8):
        d.enable_battle_auto_deity('nest',battle(),state);clock[0]+=.5
    assert len(points)==2
    clock[0]=4;d.enable_battle_auto_deity('nest',battle(),state)
    clock[0]=6;assert not d.enable_battle_auto_deity('nest',battle(),state)
    assert len(set(points))==3 and state['status']=='unconfirmed'
    assert not d.enable_battle_auto_deity('nest',battle('自动'),state) and state['confirmed']


def test_stop_is_propagated_before_toggle(tmp_path):
    d=daily(tmp_path);d.b.stop.set();d.b.click_at=lambda *a:pytest.fail('Stopped')
    with pytest.raises(UserStopped):d.enable_battle_auto_deity('nest',battle(),{})


def test_real_local_ocr_recovers_auto_without_tapping(tmp_path,monkeypatch,offline_backend):
    d=daily(tmp_path);d.b=offline_backend;s=captured('v0987-live-battle',True)
    s.words=[w for w in s.words if w.text=='08:06'];original=deepcopy(s.words)
    monkeypatch.setattr(d.b,'click_at',lambda *a:pytest.fail('Already automatic'))
    state={};assert not d.enable_battle_auto_deity('main',s,state)
    assert state['confirmed'] and s.words==original


def test_battle_loop_checks_each_new_battle_once_and_keeps_waiting_for_result(tmp_path):
    d=daily(tmp_path);d.active_task='nest';clicks=[]
    result=screen(('退出',1120,600,60,30),('本场击破数',900,300,130,35),('本场金币奖励',900,400,130,35))
    d.battle_frames=lambda *a,**kw:iter([battle(),battle('自动'),battle('自动'),result])
    d.retry_battle_network=lambda *a:False;d.battle_return_page=lambda *a:False
    d.b.sleep=lambda _:None;d.b.click_at=lambda *a:clicks.append(a[1])
    assert d.rampage_battle() is result and d.rampage_battle() is result
    assert len(clicks)==2 and [r['clicks'] for r in d.report['nest_auto_deity']]==[1,1]
    assert all(r['confirmed'] for r in d.report['nest_auto_deity'])


@pytest.mark.parametrize('task,enabled,expected_clicks',[
    ('main',True,2),('main',False,0),('tower',True,0),
])
def test_world_main_toggles_each_battle_and_still_reads_victory(tmp_path,task,enabled,expected_clicks):
    d=daily(tmp_path,{'task_options':{'main':{'auto_deity':enabled}}})
    d.active_task=task
    victory=screen(('胜利',80,250,380,140),('获得奖励',700,270,145,45),('退出',1120,600,60,30))
    d.battle_frames=lambda *a,**kw:iter([battle(),battle('自动'),battle('自动'),victory])
    d.b.sleep=lambda _:None
    clicks=[]
    def toggle(s,point,anchors,reason):
        assert s.has(*anchors) and point==s.find('^手动$').center
        clicks.append(reason)
    d.b.click_at=toggle
    assert d.battle('挑战') is victory and d.battle('挑战') is victory
    assert clicks==['主线关卡：神灵释放切换为自动']*expected_clicks
    if task=='main':
        assert [r['status'] for r in d.report['main_auto_deity']]==['confirmed' if enabled else 'disabled']*2
    else:
        assert 'main_auto_deity' not in d.report
