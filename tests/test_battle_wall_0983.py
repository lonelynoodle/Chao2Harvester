"""Wall defaults, no-op ignore, verified switching and both navigation routes."""
from copy import deepcopy
import cv2
import pytest
from chao2.backend import ROOT
from chao2.configuration import normalize_settings,SPECS
from chao2.wall_settings import validate_wall_mode
from chao2.battle_wall import formation_wall_mode,wall_page_mode,wall_icon
from chao2.policy import TaskBlocked,IsolatedTaskError
from chao2.tool_settings import tour_options,abyss_options
from test_configuration import daily,screen,captured


def formation(mode='defense',nest=True):
    s=screen(('谜之巢穴' if nest else '排阵',130,10,180,35),
             ('暴走旷野' if nest else '队伍1',920,80,170,35),
             ('最高击破数',1030,410,120,30),('挑战',1040,500,100,35))
    template=wall_icon(mode,'nest' if nest else 'formation');assert template is not None
    x,y=(56,546) if nest else (56,471);h,w=template.shape[:2]
    s.image[y:y+h,x:x+w]=template
    return s


def wall_page(mode='defense'):
    s=screen(('战墙',130,10,110,35),('切换',80,104,70,30),('效果总览',350,105,110,30),('加固',310,300,85,35))
    s.image[100:136,20:150]=(45,60,150) if mode=='attack' else (150,70,45)
    return s


def game(tmp_path,mode='defense',swallow=0):
    d=daily(tmp_path);d.active_task='nest';state=[formation(mode)];clicks=[];switches=[]
    d.observe=lambda:state[0];d.b.sleep=lambda _:None
    def click(s,point,anchors,reason,**kw):
        clicks.append(reason)
        if reason=='从队伍页打开战墙配置':state[0]=wall_page(formation_wall_mode(state[0]))
        elif reason.startswith('切换到'):
            current=wall_page_mode(state[0]);switches.append(current)
            if len(switches)>swallow:state[0]=wall_page('attack' if current=='defense' else 'defense')
        elif reason=='返回队伍，复核战墙类型':state[0]=formation(wall_page_mode(state[0]))
        else:pytest.fail('Only model entry, switch and back may be clicked: '+reason)
    d.b.click_at=click
    return d,state,clicks,switches


def test_default_only_rampage_requires_attack_and_other_teams_ignore():
    original={'task_options':{'main':{'teams':[3,1]}},'custom':'keep'};before=deepcopy(original)
    settings=normalize_settings(original)
    assert settings['task_options']['nest']['wall_mode']=='attack'
    for task,options in settings['task_options'].items():
        if task!='nest' and 'wall_mode' in options:assert options['wall_mode']=='ignore'
    assert original==before and settings['task_options']['main']['teams']==[3,1]
    assert tour_options({})['wall_mode']==abyss_options({})['wall_mode']=='ignore'


def test_wall_choice_follows_team_setting_in_every_task():
    for task,spec in SPECS.items():
        keys=[field['key'] for field in spec['fields']]
        index=next((i for i,key in enumerate(keys) if key in ('teams','team')),None)
        if index is not None:
            assert keys[index+1]=='wall_mode'
            assert len(spec['fields'][index+1]['choices'])==3


@pytest.mark.parametrize('task',[k for k,s in SPECS.items() if any(f['key']=='wall_mode' for f in s['fields']) and k!='nest'])
def test_ignore_performs_no_screen_read_navigation_or_switch(tmp_path,task):
    d=daily(tmp_path);s=screen();d.observe=d.territory=d.formation_page=lambda *a,**k:pytest.fail('Ignore must not inspect')
    d.b.click_at=d.b.click_text=d.checkpoint=lambda *a,**k:pytest.fail('Ignore must be a no-op')
    assert d.prepare_battle_wall(task,s) is s
    assert not d.report.get('battle_wall_checks')


@pytest.mark.parametrize('mode',['ignore','attack','defense'])
def test_explicit_wall_preferences_survive_instances_and_normalization(mode):
    settings=normalize_settings({'task_queue':[{'id':'nest','key':'nest','name':'暴走','enabled':True,'options':{'wall_mode':mode}}]})
    assert settings['task_queue'][0]['options']['wall_mode']==mode
    assert validate_wall_mode(mode)==mode


@pytest.mark.parametrize('invalid',['',None,True,1,'random'])
def test_invalid_wall_mode_is_rejected_before_navigation(invalid):
    with pytest.raises(ValueError):normalize_settings({'task_options':{'nest':{'wall_mode':invalid}}})


@pytest.mark.parametrize('mode',['attack','defense'])
@pytest.mark.parametrize('nest',[False,True])
def test_icon_shapes_distinguish_both_wall_modes_and_team_layouts(mode,nest):
    assert formation_wall_mode(formation(mode,nest))==mode
    assert wall_page_mode(wall_page(mode))==mode
    assert formation_wall_mode(screen()) is None and wall_page_mode(screen()) is None


def test_primary_route_switches_defense_to_attack_and_keeps_it(tmp_path):
    d,state,clicks,switches=game(tmp_path)
    returned=d.prepare_battle_wall('nest',state[0])
    assert returned is state[0] and formation_wall_mode(returned)=='attack'
    assert switches==['defense'] and len(clicks)==3
    assert d.report['battle_wall_checks'][-1]['status']=='verified'
    assert d.report['battle_wall_checks'][-1]['route']=='formation'
    d.prepare_battle_wall('nest',returned)
    assert len(clicks)==3  # Already correct: no menu round trip or restore.


def test_defense_choice_switches_the_other_direction(tmp_path):
    d,state,clicks,switches=game(tmp_path,'attack');d.options['nest']['wall_mode']='defense'
    assert formation_wall_mode(d.prepare_battle_wall('nest',state[0]))=='defense'
    assert switches==['attack']


def test_team_copy_reuses_the_confirmed_global_wall_type(tmp_path):
    d,state,clicks,switches=game(tmp_path)
    d.prepare_battle_wall('nest',state[0])
    state[0]=formation('attack')  # Copying another lineup keeps the global wall.
    assert formation_wall_mode(d.prepare_battle_wall('nest',state[0]))=='attack'
    assert switches==['defense']
    assert d.report['battle_wall_runtime']['cache_hits']==1


def test_explicit_ignore_on_rampage_is_also_a_true_noop(tmp_path):
    d=daily(tmp_path);d.options['nest']['wall_mode']='ignore';s=screen()
    d.observe=lambda *a:pytest.fail('Ignore must not read even on rampage')
    assert d.prepare_battle_wall('nest',s) is s


def test_swallowed_switch_retries_only_while_old_mode_is_confirmed(tmp_path):
    d,state,clicks,switches=game(tmp_path,swallow=1)
    assert formation_wall_mode(d.prepare_battle_wall('nest',state[0]))=='attack'
    assert switches==['defense','defense']


def test_switch_that_never_takes_effect_blocks_challenge_and_is_bounded(tmp_path):
    d,state,clicks,switches=game(tmp_path,swallow=9)
    with pytest.raises(IsolatedTaskError):d.prepare_battle_wall('nest',state[0])
    assert len(switches)==2 and not d.report.get('challenge_starts')
    assert d.report['battle_wall_checks'][-1]['status']=='blocked'


def test_unknown_mode_never_guesses_a_toggle(tmp_path):
    d=daily(tmp_path);s=wall_page();s.image[:]=0;d.observe=lambda:s
    d.b.click_at=lambda *a,**k:pytest.fail('Unknown mode cannot authorize a switch')
    with pytest.raises(IsolatedTaskError):d.set_wall_page(s,'attack',{'switches':0})


def test_territory_fallback_sets_wall_and_returns_to_same_rampage_page(tmp_path):
    d,state,clicks,switches=game(tmp_path);original=state[0]
    def unavailable(*a):raise TaskBlocked('队伍入口未识别')
    d.wall_in_formation=unavailable
    d.territory=lambda:screen(('战墙',530,480,90,30))
    def text(s,p,**kw):
        if p=='^战墙$':state[0]=wall_page('defense')
        elif p=='^暴走旷野$':state[0]=formation('attack')
        else:pytest.fail('Unexpected navigation: '+p)
    d.b.click_text=text;original_click=d.b.click_at
    def click(s,point,anchors,reason,**kw):
        if reason=='战墙切换后返回领地':return
        return original_click(s,point,anchors,reason,**kw)
    selector=screen(('谜之巢穴',124,14,90,24),('暴走旷野',592,620,98,40))
    d.b.click_at=click;d.home=lambda *a:screen();d.enter_building=lambda *a:selector
    assert formation_wall_mode(d.prepare_battle_wall('nest',original))=='attack'
    assert d.report['battle_wall_checks'][-1]['route']=='territory' and len(switches)==1


def test_no_challenge_is_sent_before_wall_requirement_passes(tmp_path):
    d=daily(tmp_path)
    def blocked(*a):raise IsolatedTaskError('必须确认进攻型战墙')
    d.prepare_battle_wall=blocked;d.b.click_text=lambda *a,**k:pytest.fail('No battle with wrong wall')
    with pytest.raises(IsolatedTaskError):d.start_challenge('nest',screen(),'暴走免费挑战')
    assert d.battles==0 and d.task_counts=={}


@pytest.mark.parametrize('kind',['formation','nest','wall'])
@pytest.mark.parametrize('mode',['attack','defense'])
def test_actual_game_pixels_confirm_wall_mode(kind,mode):
    s=captured('v0983-'+kind+'-'+mode,True)
    assert (wall_page_mode(s) if kind=='wall' else formation_wall_mode(s))==mode


def test_animated_nest_background_does_not_force_slow_fallback():
    s=captured('v0983-nest-animated-defense',True)
    assert formation_wall_mode(s)=='defense'
