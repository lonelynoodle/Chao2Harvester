"""Long combat and local failures must not discard the remaining task queue."""
import time
import threading
from types import SimpleNamespace
import pytest
from chao2.policy import SafetyStop,SessionUnavailable,UserStopped,IsolatedTaskError,TaskBlocked
from chao2.tribe_totems import tribe_result
from chao2.task_recovery import task_cancel_button
from chao2.workflows import is_world
from test_configuration import daily,screen,captured


def battle():return screen(('01:46',600,15,80,30),('自动',80,600,55,30))

def world():
    return screen(('任务挑战',1196,42,80,24),('世界回响',1196,138,80,24),('35/183',500,12,80,28))

def auction_result():
    return screen(('结算',40,232,440,227),('获得奖励',897,324,77,22),
                  ('掉落拍卖品',1149,63,112,24),('退出',1149,582,55,29))

def result():return screen(('胜利',100,240,200,60),('获得奖励',900,330,95,30),('退出',1149,582,55,29))

def simulate(tmp_path,monkeypatch,frames,step=100):
    d=daily(tmp_path);clock=[0.];pages=iter(frames)
    monkeypatch.setattr(time,'monotonic',lambda:clock[0])
    d.b.sleep=lambda _:clock.__setitem__(0,clock[0]+step)
    def observe(*a,**k):
        s=next(pages);s.when=clock[0];d.last_screen=s;return s
    d.observe=observe;d.b.save_screen=lambda *a:None
    d.b.click_at=lambda *a,**k:pytest.fail('No unsolicited input during combat')
    d.b.click_text=lambda *a,**k:pytest.fail('No rematch or retreat during combat')
    return d,clock


@pytest.mark.parametrize('task',['tribe','tower','cocoon','hunt','main','rift','forest','copies'])
def test_generic_fights_extend_repeatedly_until_real_result(tmp_path,monkeypatch,task):
    done=auction_result() if task=='tribe' else result()
    d,clock=simulate(tmp_path,monkeypatch,[battle() for _ in range(10)]+[done])
    d.active_task=task;d.options['hunt']['auto_settle']=False
    assert d.battle('部落战令' if task=='tribe' else '副本资源') is done
    assert clock[0]>720 and d.battles==d.task_counts[task]==1
    assert len(d.report['battle_wait_extensions'])>=3
    assert d.report['battles'][-1]['result']==('score' if task=='tribe' else 'victory')


@pytest.mark.parametrize('task',['origin','arena'])
def test_pvp_long_wait_records_one_real_result(tmp_path,monkeypatch,task):
    done=result();d,clock=simulate(tmp_path,monkeypatch,[battle() for _ in range(10)]+[done])
    d.active_task=task;d.options[task]['auto_settle']=False
    assert d.pvp_battle(task)==(done,'victory')
    assert clock[0]>720 and d.task_counts[task]==1
    assert d.report['pvp_settlements'][0]['outcome']=='victory'


def test_rampage_extends_twelve_minute_wait(tmp_path,monkeypatch):
    done=screen(('退出',1149,582,55,29),('本场击破数',800,350,140,30),('本场金币奖励',800,400,140,30))
    d,clock=simulate(tmp_path,monkeypatch,[battle() for _ in range(12)]+[done]);d.active_task='nest'
    assert d.rampage_battle() is done and clock[0]>720
    assert d.task_counts['nest']==1 and d.report['battle_wait_extensions']


def test_giant_extends_wait_and_reads_actual_score(tmp_path,monkeypatch):
    menu=screen(('进击巨物',100,15,130,30),('开始挑战',1000,600,130,30),('我的排名',800,450,100,30))
    d,clock=simulate(tmp_path,monkeypatch,[battle() for _ in range(10)]+[menu]);d.active_task='giant'
    d.options['giant']['auto_settle']=False
    monkeypatch.setattr('chao2.activities.giant_damage',lambda s:1234)
    assert d.giant_settlement()==1234 and clock[0]>720
    assert d.task_counts['giant']==1 and d.report['battle_wait_extensions']


def test_existing_combat_is_waited_out_before_backtracking(tmp_path,monkeypatch):
    d,clock=simulate(tmp_path,monkeypatch,[battle() for _ in range(10)]+[result()]);d.active_task='tribe'
    exits=[];d.exit_result=lambda s:exits.append(s) or world()
    assert is_world(d.finish_existing_battle(battle()))
    assert clock[0]>720 and len(exits)==1 and d.battles==0


def test_unknown_frame_at_deadline_is_not_mistaken_for_combat(tmp_path,monkeypatch):
    d,clock=simulate(tmp_path,monkeypatch,[screen() for _ in range(5)]);d.active_task='tribe'
    with pytest.raises(IsolatedTaskError,match='回退后继续下一项'):d.battle('部落战令')
    assert not d.report.get('battle_wait_extensions') and not d.report.get('battles')


def test_unmatched_lobby_is_not_an_infinite_battle(tmp_path,monkeypatch):
    matching=screen(('正在匹配',500,200,160,30),('取消匹配',500,550,160,30))
    d,clock=simulate(tmp_path,monkeypatch,[matching for _ in range(5)]);d.active_task='arena'
    with pytest.raises(IsolatedTaskError):d.pvp_battle('arena')
    assert not d.report.get('battle_wait_extensions')


@pytest.mark.parametrize('error',[SafetyStop('费用未核实'),TaskBlocked('任务无法完成'),RuntimeError('任务异常')])
def test_local_errors_backtrack_then_execute_next_task(tmp_path,error):
    d=daily(tmp_path);calls=[]
    def fail():raise error
    d.tribe=fail;d.home=lambda:calls.append('back') or world()
    d.rewards=lambda:calls.append('rewards') or '领奖完成'
    d.execute_task('tribe');d.execute_task('rewards')
    assert calls==['back','rewards']
    assert d.report['tasks']['tribe']['status']=='blocked'
    assert d.report['tasks']['rewards']['status']=='done'


@pytest.mark.parametrize('error',[UserStopped('停止'),SessionUnavailable('账号或设备不可用')])
def test_real_stop_does_not_send_backtracking_input(tmp_path,error):
    d=daily(tmp_path)
    def fail():raise error
    d.tribe=fail;d.home=lambda:pytest.fail('Stop forbids further game input')
    with pytest.raises(type(error)):d.execute_task('tribe')


def test_unknown_unrecoverable_page_stops_queue(tmp_path):
    d=daily(tmp_path);d.b.sleep=lambda _:None;d.observe=lambda:screen()
    d.tribe=lambda:(_ for _ in ()).throw(SafetyStop('任务异常'))
    with pytest.raises(SafetyStop,match='未配置返回规则'):d.execute_task('tribe')
    assert d.report['tasks']['tribe']['recovery_error']


def test_subtask_safety_error_does_not_skip_later_other_jobs(tmp_path):
    d=daily(tmp_path);calls=[]
    opts=d.options['other']
    for key,value in list(opts.items()):
        if type(value) is bool:opts[key]=False
    opts.update(piggy_bank=True,buy_star_spores=True,clear_bag_notifications=True)
    d.collect_piggy_bank=lambda:(_ for _ in ()).throw(SafetyStop('待核实交易'))
    d.buy_star_spores=lambda:calls.append('shop') or {'status':'done','message':'shop'}
    d.clear_bag_notifications=lambda:calls.append('bag') or {'status':'done','message':'bag'}
    d.home=lambda:calls.append('back') or world()
    d.execute_task('other')
    assert calls.index('back')<calls.index('shop')<calls.index('bag')
    assert d.report['other_tasks']['piggy_bank']['status']=='blocked'


def modal():return screen(('是否购买战令',420,270,350,35),('取消',450,480,60,32),('确定',765,480,65,32))

def test_recovery_can_only_cancel_a_known_confirmation(tmp_path):
    d=daily(tmp_path);s=modal();b=d.b;clicks=[]
    b.wait=lambda job:job;b.sleep=lambda _:None
    b.controller=SimpleNamespace(post_click=lambda x,y:clicks.append((x,y)) or SimpleNamespace(succeeded=True))
    b.task_cancel_only=True
    with pytest.raises(SafetyStop,match='仅允许取消'):b.click_at(s,(797,496),['^确定$'],'forbidden')
    b.click_at(s,task_cancel_button(s).center,['^取消$'],'cancel')
    assert clicks==[task_cancel_button(s).center]
    assert task_cancel_button(screen(('取消',450,480,60,32),('确定',765,480,65,32))) is None


def test_recovery_cancel_is_bounded_and_does_not_retry_purchase(tmp_path):
    d=daily(tmp_path);clicks=[];d._task_cancel_attempts=0;d.b.observe=lambda:modal()
    d.b.click_at=lambda s,p,a,r:clicks.append(p)
    with pytest.raises(IsolatedTaskError,match='3次取消'):d.cancel_failed_task_dialog(modal())
    assert len(clicks)==3 and not d.b.task_cancel_only


def test_auction_result_without_repeat_button_or_order_count_is_valid(tmp_path):
    d=daily(tmp_path);s=auction_result();assert tribe_result(s)
    d.b.click_at=lambda *a:pytest.fail('No missing repeat-checkbox click')
    assert d.tribe_settlement(s) is s
    assert not getattr(d,'tribe_repeat_disabled',False)
    assert not d.report.get('dungeon_resources')
    for missing in ('结算','掉落拍卖品','获得奖励','退出'):
        q=auction_result();q.words=[w for w in q.words if w.text!=missing]
        assert not tribe_result(q)


def test_actual_reported_auction_result_is_recognized():
    assert tribe_result(captured('v0985-tribe-auction-result',True))


def test_run_time_threshold_does_not_abort_a_known_battle(tmp_path,monkeypatch):
    d=daily(tmp_path);d.start_time=0
    monkeypatch.setattr(time,'monotonic',lambda:10000.)
    d.b.observe=lambda *a:battle();d.b.save_screen=lambda *a:None
    assert d.observe().find('^自动$') and d.observe().find('^自动$')
    assert sum('原时长阈值' in row['message'] for row in d.report['events'])==1


def test_optional_failure_is_recorded_and_returns_to_queue(tmp_path):
    d=daily(tmp_path);calls=[];d.home=lambda:calls.append('back') or world()
    def fail():raise SafetyStop('免费造唤结果未确认')
    assert is_world(d.optional_step('免费造唤',fail)) and calls==['back']
    assert len(d.report['optional_failures'])==1


@pytest.mark.parametrize('error',[SafetyStop('结算核验异常'),RuntimeError('任务执行异常')])
def test_actual_queue_continues_after_local_interruption(tmp_path,monkeypatch,error):
    import chao2.workflows as flow
    from test_startup import queue
    calls=queue(tmp_path,monkeypatch)
    def fail(self):calls.append('tribe');raise error
    monkeypatch.setattr(flow.Daily,'tribe',fail)
    config={'task_queue':[{'id':k,'key':k,'name':k,'enabled':True,'options':{}}
                          for k in ('tribe','rewards')], 'free_summon_enabled':False}
    report=flow.run_daily(config,['tribe','rewards'],threading.Event(),log=lambda _:None)
    assert report['status']=='partial' and report['execution_order']==['tribe','rewards']
    assert report['tasks']['tribe']['status']=='blocked' and report['tasks']['rewards']['status']=='done'
    assert calls==['home','tribe','home','rewards','home']


def test_matching_failure_cancels_known_match_then_goes_back(tmp_path):
    d=daily(tmp_path);d.b.sleep=lambda _:None;clicks=[]
    matching=screen(('正在匹配',500,200,160,30),('取消匹配',500,550,160,30))
    frames=iter([matching,world()]);d.observe=lambda:next(frames)
    d.b.click_at=lambda s,p,a,r:clicks.append(s.find('^取消匹配$').center)
    assert is_world(d.recover_failed_task()) and len(clicks)==1
    assert not d.report.get('battle_takeovers')


def test_network_failure_cancels_prompt_without_reissuing_request(tmp_path):
    d=daily(tmp_path);state=[screen(('网络翻船中，是否重试?',490,299,283,26),
                                  ('取消',454,480,55,32),('确定',769,481,56,31))];clicks=[]
    d.b.observe=lambda *a:state[0];d.b.save_screen=lambda *a:None
    def click(s,p,a,r):
        assert p==s.find('^取消$').center
        clicks.append(p);state[0]=world()
    d.b.click_at=click
    assert is_world(d.recover_failed_task()) and len(clicks)==1
    assert not d.report.get('network_recoveries') and not d.b.task_cancel_only


def test_recovery_waits_for_active_battle_before_leaving(tmp_path,monkeypatch):
    d,clock=simulate(tmp_path,monkeypatch,[battle() for _ in range(10)]+[result()]);exits=[]
    d.exit_result=lambda s:exits.append(s) or world()
    assert is_world(d.recover_failed_task()) and clock[0]>720 and len(exits)==1
    assert d.report['battle_takeovers'][0]['status']=='settled'


def test_stop_still_works_after_extending_long_battle(tmp_path,monkeypatch):
    d,clock=simulate(tmp_path,monkeypatch,[battle() for _ in range(12)]);d.active_task='tribe'
    def sleep(_):
        clock[0]+=100
        if clock[0]>700:d.b.stop.set()
    d.b.sleep=sleep
    with pytest.raises(UserStopped):d.battle('部落战令')
    assert d.report['battle_wait_extensions'] and not d.report.get('battles')


def test_celebration_safety_error_continues_next_child(tmp_path):
    d=daily(tmp_path);d.active_task='celebration';calls=[]
    d.options['celebration'].update(triad=True,giant=True,daily_puzzle=False)
    d.triad=lambda:(_ for _ in ()).throw(SafetyStop('三阵结算未确认'))
    d.giant=lambda:calls.append('giant') or '巨物已完成'
    d.home=lambda:calls.append('back') or world()
    d.execute_task('celebration')
    children=d.report['celebration_tasks']['celebration']
    assert children['triad']['status']=='blocked' and children['giant']['status']=='done'
    assert calls.index('back')<calls.index('giant')


def test_recovery_leaves_merchant_shop_without_new_purchase_or_encounter(tmp_path):
    d=daily(tmp_path);clicks=[]
    shop=screen(('神秘商人',100,15,150,35),('限购1件，购买后神秘商人消失',100,600,600,30),
                ('离开',1000,650,110,35))
    frames=iter([shop,world()]);d.observe=lambda:next(frames)
    def click(s,p,a,r):
        assert p==shop.find('^离开$').center and s.has(*a)
        clicks.append(r)
    d.b.click_at=click
    assert is_world(d.recover_failed_task()) and len(clicks)==1
    assert not d.report.get('merchant_events')


def test_account_guard_raises_a_session_stop_for_the_task_boundary(tmp_path):
    d=daily(tmp_path)
    account=screen(('账号在其他设备登录',400,230,440,35),('确定',610,480,80,35))
    with pytest.raises(SessionUnavailable):d.b.guard(account)


def test_unreadable_run_resources_do_not_prevent_actual_queue_tasks(tmp_path,monkeypatch):
    import chao2.workflows as flow
    from test_startup import queue
    calls=queue(tmp_path,monkeypatch)
    def unreadable(*a):raise TaskBlocked('体力余额未读清')
    monkeypatch.setattr(flow.Daily,'world_resources',unreadable)
    report=flow.run_daily({'free_summon_enabled':False},['rewards'],threading.Event(),log=lambda _:None)
    assert report['status']=='partial' and report['tasks']['rewards']['status']=='done'
    assert report['resources_start']['diamonds'] is None and report['resources_end']['stamina'] is None
    assert report['diamond_spend'] is None and len(report['optional_failures'])==2
    assert 'rewards' in calls
