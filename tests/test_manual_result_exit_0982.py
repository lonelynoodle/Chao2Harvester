"""Manual result exits must follow current pages and quotas, never invent losses."""
import time
from dataclasses import replace
import pytest
from chao2.policy import BattleReturned,PageChanged,TaskBlocked,IsolatedTaskError,UserStopped,SafetyStop
from chao2.result_navigation import exit_destination
from test_configuration import daily,screen,captured


def origin_menu(quota=0):
    return screen(('起源殿',130,10,110,35),('匹配',1000,640,100,40),
                  ('剩余免费挑战次数',980,570,170,30),(str(quota),1150,575,35,30))


def hud():
    return screen(('自动',80,600,65,30),('00:35',520,25,100,35))


def result():
    return screen(('胜利',160,220,200,60),('退出',1100,590,120,40),('获得奖励',650,300,150,40))


def clocked(d,monkeypatch,frames):
    clock=[time.monotonic()];sequence=iter(frames);last=[None]
    monkeypatch.setattr(time,'monotonic',lambda:clock[0])
    d.b.sleep=lambda seconds:clock.__setitem__(0,clock[0]+seconds)
    def observe(*a,**kw):
        last[0]=next(sequence,last[0])
        assert last[0] is not None
        return replace(last[0],when=clock[0])
    d.observe=d.observe_battle=observe
    return clock


@pytest.mark.parametrize('name',['起源殿','斗技场','斗技场挑战','浮空巨塔','永生之茧','部落','黑暗森林','凿星裂痕','谜之巢穴','进击巨物'])
def test_every_registered_menu_can_be_passed_to_exit_after_user_already_left(tmp_path,name):
    d=daily(tmp_path);menu=screen((name,130,10,180,35));d.observe=lambda:menu
    d.b.click_text=lambda *a,**k:pytest.fail('No stale exit or challenge click')
    assert d.exit_result(menu) is menu
    assert d.report['result_exits'][0]['clicks']==0
    assert d.report['result_exits'][0]['destination'].startswith('menu:')


def test_stale_result_after_manual_exit_observes_current_page_without_input(tmp_path):
    d=daily(tmp_path);old=result();old.when-=60;menu=origin_menu();d.observe=lambda:menu
    d.b.click_text=lambda *a,**k:pytest.fail('Expired result cannot be clicked')
    assert d.exit_result(old) is menu
    assert d.report['result_exits'][0]['clicks']==0


@pytest.mark.parametrize('error',[PageChanged('^退出$'),TaskBlocked('未识别按钮：^退出$')])
def test_user_exit_between_detection_and_click_reclassifies_page(tmp_path,error):
    d=daily(tmp_path);menu=origin_menu();d.observe=lambda:menu;calls=[]
    def click(*a):calls.append('exit');raise error
    d.b.click_text=click
    assert d.exit_result(result()) is menu
    assert calls==['exit'] and d.report['result_exits'][0]['preclick_rechecks']==1


def test_missing_exit_is_not_automatic_failure_and_can_reappear(tmp_path):
    d=daily(tmp_path);partial=result();partial.words=[w for w in partial.words if w.text!='退出']
    full=result();menu=origin_menu();state=[full];clicks=[]
    d.observe=lambda:state[0];d.b.sleep=lambda _:None
    def click(*a):clicks.append('exit');state[0]=menu
    d.b.click_text=click
    assert d.exit_result(partial) is menu and clicks==['exit']


def test_unknown_loading_frame_never_authorizes_new_challenge(tmp_path):
    d=daily(tmp_path);frames=iter([screen()]*4+[origin_menu()]*2);clicks=[]
    d.observe=lambda:next(frames);d.b.sleep=lambda _:None;d.b.click_text=lambda *a:clicks.append(a)
    assert exit_destination(d.exit_result(screen()))=='menu:起源殿'
    assert not clicks


@pytest.mark.parametrize('task',['origin','arena'])
def test_pvp_manual_exit_returns_unknown_outcome_instead_of_waiting_timeout(tmp_path,monkeypatch,task):
    d=daily(tmp_path);d.active_task=task;d.options[task]['auto_settle']=False
    menu=origin_menu() if task=='origin' else screen(('斗技场',130,10,150,30),('挑战次数',800,660,100,30))
    clock=clocked(d,monkeypatch,[hud(),menu,menu])
    start=clock[0];d.b.click_at=lambda *a,**k:pytest.fail('No rematch or settlement input')
    current,outcome=d.pvp_battle(task)
    assert outcome=='unobserved' and exit_destination(current).startswith('menu:')
    assert clock[0]-start<10 and d.report['pvp_settlements'][-1]['outcome']=='unobserved'


@pytest.mark.parametrize('remaining',[0,2])
def test_origin_rechecks_real_quota_then_finishes_or_continues(tmp_path,monkeypatch,remaining):
    import chao2.daily_challenges as pvp
    d=daily(tmp_path);d.active_task='origin';d.options['origin']['auto_settle']=False
    before=origin_menu(remaining+1);after=origin_menu(remaining);zero=origin_menu(0)
    clocked(d,monkeypatch,[hud(),after,after,hud(),zero,zero])
    monkeypatch.setattr(pvp,'origin_is_open',lambda:True)
    d.enter_building=lambda *a:before;d.select_team=lambda s,*a,**k:s;d.home=lambda *a,**k:screen()
    state=[before];matches=[]
    d.await_page=lambda *a:state[0]
    def quota(s,task,expected=None):
        value=int(s.words[-1].text)
        return s,value
    d.await_pvp_quota=quota
    original=d.pvp_battle
    def battle(*a,**k):
        s,outcome=original(*a,**k);state[0]=s;return s,outcome
    d.pvp_battle=battle
    d.b.click_text=lambda s,p:matches.append(p)
    # Pass-through is verified independently above; this keeps observations in
    # this test dedicated to the real battle wait and actual quota loop.
    d.exit_result=lambda s:s
    d.execute_task('origin')
    answer=d.report['tasks']['origin']['message']
    d.rewards=lambda:'已继续后续任务';d.execute_task('rewards')
    assert d.report['tasks']['origin']['status']=='done' and d.report['tasks']['rewards']['status']=='done'
    assert d.report['origin_remaining']==0
    assert len(matches)==(1 if remaining==0 else 2)
    assert all(row['outcome']=='unobserved' for row in d.report['team_attempts'])
    assert not any(row['outcome'] in ('failed','victory') for row in d.report['team_attempts'])
    assert '免费次数已用完' in answer


def test_unobserved_quota_uses_current_value_and_bounds_no_progress(tmp_path):
    d=daily(tmp_path)
    assert d.returned_quota_spent('origin',4,2,'unobserved')==2
    assert d.returned_quota_spent('origin',2,2,'unobserved')==0
    assert d.returned_quota_spent('origin',2,2,'unobserved')==0
    with pytest.raises(IsolatedTaskError):d.returned_quota_spent('origin',2,2,'unobserved')
    assert d.returned_quota_spent('origin',2,None,'unobserved') is None
    assert d.returned_quota_spent('origin',2,3,'unobserved') is None
    assert d.returned_quota_spent('origin',2,0,'victory') is None
    assert d.returned_quota_spent('origin',2,1,'victory')==1
    assert d.returned_quota_spent('origin',1,1,'unobserved')==0


@pytest.mark.parametrize('task',['main','hunt','tower','cocoon','tribe','rift','forest'])
def test_common_battle_wait_hands_current_page_to_resource_recheck(tmp_path,monkeypatch,task):
    d=daily(tmp_path);d.active_task=task
    if task=='hunt':d.options['hunt']['auto_settle']=False
    menu=origin_menu()  # A different known page must also be handled, never guessed as a win.
    clocked(d,monkeypatch,[hud(),menu,menu]);d.b.click_at=lambda *a,**k:pytest.fail('No replayed challenge')
    with pytest.raises(BattleReturned) as caught:d.battle('当前玩法资源')
    assert caught.value.task==task and exit_destination(caught.value.screen)=='menu:起源殿'
    assert d.report['battles'][-1]['result']=='unobserved'
    assert d.task_counts[task]==1 and not d.report.get('team_attempts')


@pytest.mark.parametrize('changing',[False,True])
def test_task_restarts_from_current_resources_and_does_not_mark_result_as_failure(tmp_path,changing):
    d=daily(tmp_path);menu=origin_menu();calls=[]
    def run():
        calls.append('main')
        if changing and len(calls)==6:return '资源已用完'
        before=100-len(calls)*5 if changing else 100
        raise BattleReturned(menu,'world',('world',before,'730'),'main','730')
    d.main=run;d.home=lambda *a,**k:menu;d.rewards=lambda:'后续任务已执行'
    d.execute_task('main');d.execute_task('rewards')
    assert len(calls)==(6 if changing else 3)
    assert d.report['tasks']['main']['status']==('done' if changing else 'blocked')
    assert d.report['tasks']['rewards']['status']=='done'
    assert all(row['outcome']=='unobserved' for row in d.report['team_attempts'])


@pytest.mark.parametrize('error',[UserStopped('用户停止'),SafetyStop('账号已在其他设备登录')])
def test_manual_exit_recovery_does_not_swallow_stop_conditions(tmp_path,error):
    d=daily(tmp_path)
    def fail(*a,**k):raise error
    d.b.click_text=fail
    with pytest.raises(type(error)):d.exit_result(result())


def test_original_origin_zero_quota_frame_is_a_return_destination(tmp_path,monkeypatch):
    d=daily(tmp_path);d.active_task='origin';d.options['origin']['auto_settle']=False
    menu=captured('v0982-origin-manual-exit',True)
    assert exit_destination(menu)=='menu:起源殿'
    clocked(d,monkeypatch,[hud(),menu,menu])
    current,outcome=d.pvp_battle('origin')
    assert outcome=='unobserved' and exit_destination(current)=='menu:起源殿'


def test_rampage_wait_rechecks_menu_after_manual_result_exit(tmp_path,monkeypatch):
    d=daily(tmp_path);d.active_task='nest';menu=screen(('谜之巢穴',130,10,180,35),('暴走旷野',930,110,180,35),('挑战',1000,630,100,30))
    clock=clocked(d,monkeypatch,[hud(),menu,menu,menu]);start=clock[0]
    assert exit_destination(d.rampage_battle())=='menu:谜之巢穴'
    assert clock[0]-start<12 and d.report['battle_returns'][0]['outcome']=='unobserved'


def test_giant_wait_reads_current_score_instead_of_waiting_for_closed_result(tmp_path,monkeypatch):
    import chao2.activities as activity
    d=daily(tmp_path);d.active_task='giant';menu=screen(('进击巨物',130,10,180,35),('开始挑战',1000,630,150,35),('我的排名',800,430,130,35))
    clocked(d,monkeypatch,[menu,menu,menu]);monkeypatch.setattr(activity,'giant_damage',lambda s:1234)
    assert d.giant_settlement()==1234
    assert d.report['battle_returns'][0]['outcome']=='unobserved'


def test_triad_wait_returns_to_quota_loop_after_manual_exit(tmp_path,monkeypatch):
    d=daily(tmp_path);d.active_task='triad';d.options['triad']['auto_settle']=False
    lobby=screen(('三阵入局',100,10,180,40),('匹配',800,500,130,40),('剩余免费匹配次数1',980,630,240,35))
    end=screen(('三阵入局',100,10,180,40),('匹配',800,500,130,40),('剩余免费匹配次数0',980,630,240,35))
    clocked(d,monkeypatch,[end,end]);d.triad_lobby=lambda s:s
    d.b.read_text_crop=lambda *a:''
    d.await_triad_quota=lambda s:(s,1);d.wait_for_screen=lambda *a,**k:hud();clicks=[]
    d.b.click_text=lambda *a,**k:clicks.append('match')
    current,outcome,settles=d.triad_match(lobby)
    assert outcome=='unobserved' and settles==0 and clicks==['match']
    assert exit_destination(current)=='triad_lobby'
