"""Rank overlays must not hide the result or cause repeated match inputs."""
import pytest
from chao2.daily_challenges import rank_change_notice,origin_resume_state,pvp_result
from chao2.policy import TaskBlocked,SafetyStop,UserStopped
from chao2.workflows import is_world
from test_configuration import daily,captured,screen
from test_daily_challenges import origin_frame


@pytest.mark.parametrize('fixture,label',[('arena-promotion','段位提升'),('v0919-rank-demotion','段位下降')])
def test_captured_rank_overlays_are_not_world_or_battle_results(fixture,label):
    s=captured(fixture,True)
    assert rank_change_notice(s).text==label
    assert not is_world(s) and pvp_result(s) is None
    assert origin_resume_state(s)=='rank_change'


@pytest.mark.parametrize('text,x,y',[('段位下降奖励',560,500),('段位下降',30,40),('段位',560,500)])
def test_unrelated_rank_text_is_not_a_close_target(tmp_path,text,x,y):
    d=daily(tmp_path);s=screen((text,x,y,150,35))
    d.b.click_at=lambda *a:pytest.fail('Unrelated text must not trigger input')
    assert rank_change_notice(s) is None and d.dismiss_rank_change(s) is s


def test_demotion_waits_through_animation_then_confirms_real_defeat(tmp_path):
    d=daily(tmp_path);s=captured('v0919-rank-demotion',True)
    result=captured('v076-origin-failed',True)
    frames=iter([s,s,screen(),result]);d.observe=lambda:next(frames);d.b.sleep=lambda _:None
    clicks=[];d.b.click_at=lambda q,p,a,r:clicks.append((p,a))
    found,outcome=d.pvp_battle('origin',entry=s,verify_origin=True,allow_settle=False)
    assert found is result and outcome=='failed'
    assert clicks==[((935,545),['^段位下降$'])]
    assert d.task_counts['origin']==1 and not d.report.get('team_attempts')
    assert d.report['rank_changes'][0]['status']=='dismissed'


def test_unknown_result_after_rank_change_is_not_assumed_to_be_origin(tmp_path):
    d=daily(tmp_path);s=captured('v0919-rank-demotion',True)
    result=screen(('失败',80,250,400,200),('退出',1150,582,55,30))
    d.observe=lambda:result;clicks=[];d.b.click_at=lambda q,p,*a:clicks.append(p)
    with pytest.raises(TaskBlocked,match='未确认属于起源殿'):
        d.pvp_battle('origin',entry=s,verify_origin=True,allow_settle=False)
    assert clicks==[(935,545)] and not d.report.get('team_attempts')


def test_rank_close_retry_is_bounded_and_never_restarts_a_battle(tmp_path,monkeypatch):
    import chao2.navigation_retry as retry
    d=daily(tmp_path);s=captured('v0919-rank-demotion',True);clock=[0.0]
    monkeypatch.setattr(retry.time,'monotonic',lambda:clock[0])
    d.b.sleep=lambda seconds:clock.__setitem__(0,clock[0]+seconds)
    def observe():s.when=clock[0];return s
    d.observe=observe;clicks=[];d.b.click_at=lambda q,p,a,r:clicks.append((p,a))
    with pytest.raises(TaskBlocked,match='已重试3次'):d.dismiss_rank_change(s)
    assert clicks==[((935,545),['^段位下降$'])]*4
    assert d.report['rank_changes'][0]['close_attempts']==4
    assert len(d.report['navigation_retries'])==3 and not d.report.get('team_attempts')


def test_rank_close_can_recover_after_one_verified_navigation_retry(tmp_path,monkeypatch):
    import chao2.navigation_retry as retry
    d=daily(tmp_path);s=captured('v0919-rank-demotion',True);result=captured('v076-origin-failed',True)
    clock=[0.0];clicks=[];monkeypatch.setattr(retry.time,'monotonic',lambda:clock[0])
    d.b.sleep=lambda seconds:clock.__setitem__(0,clock[0]+seconds)
    def observe():
        q=result if len(clicks)>1 else s;q.when=clock[0];return q
    d.observe=observe;d.b.click_at=lambda q,p,*a:clicks.append(p)
    assert d.dismiss_rank_change(s) is result
    assert clicks==[(935,545)]*2 and d.report['rank_changes'][0]['status']=='dismissed'


@pytest.mark.parametrize('error',[SafetyStop('费用异常'),UserStopped('用户停止')])
def test_rank_dismissal_never_retries_a_guard_or_stop_request(tmp_path,error):
    d=daily(tmp_path);s=captured('v0919-rank-demotion',True)
    def guard(q):raise error
    d.b.guard=guard;d.b.click_at=lambda *a:pytest.fail('Guard must stop before input')
    with pytest.raises(type(error)):d.dismiss_rank_change(s)
    assert not d.report.get('navigation_retries')


def test_home_closes_rank_notice_before_using_world_buttons(tmp_path):
    d=daily(tmp_path);s=captured('v0919-rank-demotion',True);world=captured('v0913-main-world',True)
    d.observe=lambda:world;clicks=[];d.b.click_at=lambda q,p,*a:clicks.append(p)
    assert d.home(s) is world and clicks==[(935,545)]


def test_origin_restarts_from_demotion_without_spending_another_quota(tmp_path,monkeypatch):
    import chao2.daily_challenges as challenges
    d=daily(tmp_path);monkeypatch.setattr(challenges,'origin_is_open',lambda:True)
    d._origin_entry=captured('v0919-rank-demotion',True);result=captured('v076-origin-failed',True)
    d.observe=lambda:result;d.b.sleep=lambda _:None;clicks=[]
    d.b.click_at=lambda q,p,*a:clicks.append(p)
    d.b.click_text=lambda *a,**k:pytest.fail('Do not rematch')
    d.enter_building=lambda *a:pytest.fail('Do not navigate away from the result')
    d.select_team=lambda *a,**k:pytest.fail('Do not change an existing battle team')
    exits=[];d.exit_result=lambda q:exits.append(q)
    d.await_page=lambda *a:origin_frame(0);d.home=lambda:None
    assert '1场' in d.origin()
    assert exits==[result] and clicks==[(935,545)]
    assert d.report['team_attempts'][0]['outcome']=='failed'
    assert d.report['team_attempts'][0]['resumed']
    assert d.report['origin_remaining']==0
