"""Full-width wallet reads and local piggy failures must not abort the queue."""
from types import SimpleNamespace
import pytest
from test_configuration import daily,screen,captured
from test_rift_main_0959 import offline_backend
from chao2.configuration import SPECS
from chao2.compact_balance import read_fixed_balance,displayed_balance
from chao2.piggy_bank import WORLD_WALLET_ROI,piggy_cancel_button
from chao2.policy import TaskBlocked,SafetyStop,UserStopped,IsolatedTaskError
from chao2.page_recovery import navigation_failure


def modal(price=50):
    return screen(('活动',110,10,90,35),(f'是否消耗{price}钻石购买1木锤?',400,260,480,35),
                  ('今天还能购买3次',500,320,280,30),('取消',450,480,60,32),
                  ('确定',765,480,65,32),('7883',1205,10,60,30))


def simulation(tmp_path,*,bad_charge=False,buy_stuck=False,claim_stuck=False):
    opts={f['key']:False for f in SPECS['other']['fields'] if f['type']=='bool'}
    opts.update(piggy_bank=True,buy_star_spores=True,clear_bag_notifications=True)
    d=daily(tmp_path,{'task_options':{'other':opts}})
    state={'wallet':7883,'stock':0,'stored':210,'mode':'page','purchases':0,'claims':0,'cancels':0}
    d.b.sleep=lambda _:None;d.b.save_screen=lambda *a:None
    def observe(*a,**kw):
        if state['mode']=='offer':return modal()
        if state['mode']=='claim':
            return screen(('活动',110,10,90,35),('可获得奖励',520,200,230,35),
                          ('200',550,310,60,25),('200000',650,310,100,25),
                          ('取消',450,480,60,32),('领取',765,480,65,32))
        return screen(('活动',110,10,90,35),('屯屯扑满',230,140,210,40),
                      (f'已储存{state["stored"]}钻石和{state["stored"]*1000}金币',550,400,370,25),
                      ('每次领取奖励消耗200活跃之星',550,440,370,25),
                      ('1钻石和1000金币',950,275,230,25),('立即领取',500,600,140,40))
    d.observe=observe;d.b.observe=observe;d.activity_tab=lambda name:observe();d.home=lambda:screen()
    d.piggy_wallet=lambda:state['wallet']
    d.piggy_view=lambda s=None:(observe(),{'stored':state['stored'],'gold':state['stored']*1000,
                                         'stock':state['stock'],'quantity':1})
    def wait(predicate,*a,**kw):
        s=observe()
        if not predicate(s):raise TaskBlocked('模拟页面未确认')
        return s
    d.wait_for_screen=wait;d.b.match_template=lambda *a:True
    numbers={(801,498,30,27):50,(565,306,50,30):200,(649,305,83,31):200000,(805,498,20,25):1}
    d.b.read_number=lambda s,roi:numbers.get(roi,state['wallet'])
    d.b.click_at=lambda *a,**kw:state.update(mode='offer')
    def click(s,pattern,roi=None,**kw):
        if pattern=='^确定$':
            assert state['purchases']==0 and d.state['piggy_pending']['phase']=='buy_requested'
            state['purchases']+=1
            if not buy_stuck:
                state.update(stock=1,wallet=state['wallet']-(60 if bad_charge else 50),mode='page')
        elif pattern=='^立即领取$':state['mode']='claim'
        elif pattern=='^领取$':
            assert state['claims']==0 and d.state['piggy_pending']['phase']=='claim_requested'
            state['claims']+=1
            if not claim_stuck:state.update(stock=0,stored=10,wallet=state['wallet']+200,mode='page')
        elif pattern=='^取消$':state['cancels']+=1;state['mode']='page'
        else:pytest.fail('Unexpected input: '+pattern)
    d.b.click_text=click
    return d,state


@pytest.mark.parametrize('texts,expected',[
    (['7833','7833'],7833),(['','7833','7833'],7833),
    (['1.02万','1.02万'],displayed_balance('1.02万')),
])
def test_wallet_uses_full_fixed_hud_not_truncated_global_words(tmp_path,texts,expected):
    d=daily(tmp_path);s=screen(('783',268,19,34,16));d.home=lambda:s;values=iter(texts);calls=[]
    def local(q,roi,scale=1,threshold=.65):calls.append((roi,scale,threshold));return next(values)
    d.b.read_text_region=local;d.world_resources=lambda *_:pytest.fail('Unverified global integer is not a wallet')
    assert d.piggy_wallet()==expected
    assert all(roi==WORLD_WALLET_ROI and threshold==.8 for roi,_,threshold in calls)


@pytest.mark.parametrize('texts',[['7833','783'],['','',''],['7833','','']])
def test_conflicting_or_missing_wallet_stays_unconfirmed(tmp_path,texts):
    d=daily(tmp_path);values=iter(texts);d.b.read_text_region=lambda *a,**kw:next(values)
    with pytest.raises(TaskBlocked,match='固定区域'):read_fixed_balance(d.b,screen(),WORLD_WALLET_ROI)


def test_purchase_and_claim_still_require_exact_50_and_inventory_changes(tmp_path):
    d,state=simulation(tmp_path)
    row=d.collect_piggy_bank()
    assert (state['purchases'],state['claims'],state['wallet'])==(1,1,8033)
    assert row['spent']==50 and row['claimed']==1 and not d.state.get('piggy_pending')


@pytest.mark.parametrize('failure',[{'bad_charge':True},{'buy_stuck':True},{'claim_stuck':True}])
def test_failed_transaction_keeps_journal_without_retrying_but_other_jobs_and_rewards_continue(tmp_path,failure):
    d,state=simulation(tmp_path,**failure);calls=[]
    d.buy_star_spores=lambda:calls.append('shop') or {'status':'done','message':'shop done'}
    d.clear_bag_notifications=lambda:calls.append('bag') or {'status':'done','message':'bag done'}
    d.rewards=lambda:calls.append('rewards') or 'rewards done'
    d.execute_task('other');d.execute_task('rewards')
    assert calls==['shop','bag','rewards']
    assert state['purchases']==1 and state['claims']==int(failure.get('claim_stuck',False))
    assert d.state.get('piggy_pending') and not d.report.get('page_recoveries')
    assert d.report['other_tasks']['piggy_bank']['status']=='blocked'
    assert d.report['tasks']['other']['status']=='blocked' and d.report['tasks']['rewards']['status']=='done'


def test_pending_transaction_on_restart_is_isolated_and_never_purchased_again(tmp_path):
    d,state=simulation(tmp_path);d.state['piggy_pending']={'phase':'buy_requested','price':50}
    with pytest.raises(IsolatedTaskError,match='上次'):d.collect_piggy_bank()
    assert state['purchases']==state['claims']==0 and d.state['piggy_pending']['phase']=='buy_requested'
    assert not navigation_failure(IsolatedTaskError('屯屯扑满未确认'))


@pytest.mark.parametrize('error',[UserStopped('用户停止'),SafetyStop('账号已在其他设备登录')])
def test_user_or_session_stop_is_not_swallowed_as_piggy_error(tmp_path,error):
    d,state=simulation(tmp_path)
    def fail():raise error
    d._collect_piggy_bank=fail
    with pytest.raises(type(error)):d.collect_piggy_bank()
    assert state['purchases']==state['claims']==0


def test_error_cleanup_can_only_cancel_even_if_the_offer_changes_price(tmp_path):
    d=daily(tmp_path);s=modal(60);b=d.b;clicks=[]
    with pytest.raises(SafetyStop):b.guard(s)
    b.piggy_cancel_only=True;b.wait=lambda job:job;b.sleep=lambda _:None
    b.controller=SimpleNamespace(post_click=lambda x,y:clicks.append((x,y)) or SimpleNamespace(succeeded=True))
    with pytest.raises(SafetyStop,match='仅允许取消'):b.click_at(s,(797,496),['^确定$'],'must not confirm')
    assert clicks==[]
    b.click_at(s,piggy_cancel_button(s).center,['^取消$'],'cancel only')
    assert clicks==[piggy_cancel_button(s).center]
    unrelated=screen(('活动',110,10,90,35),('是否购买体力',400,260,450,35),
                     ('取消',450,480,60,32),('确定',765,480,65,32))
    with pytest.raises(SafetyStop):b.guard(unrelated)


def test_actual_failure_frame_is_7833_not_the_global_783(offline_backend,tmp_path):
    d=daily(tmp_path);d.b=offline_backend;s=captured('v0978-piggy-wallet',True);d.home=lambda:s
    assert s.region_text((250,0,75,60))=='783'
    assert d.piggy_wallet()==7833
