"""Whole-stack spore receipts and select-team-before-suppress control flow."""
from copy import deepcopy
import pytest
from chao2 import star_shop as shop
from chao2.policy import TaskBlocked,UserStopped
from chao2.team_switch import suppression_team_switch_dialog
from chao2.workflows import is_world
from test_configuration import daily,captured,screen
from test_abyss import flow,player


def world():
    return screen(('任务挑战',1196,42,80,25),('世界回响',1194,136,78,28),('8/181',500,15,80,25))


def batch_shop(d,monkeypatch,*,balance=300,stock=(5,5),receipt='ok'):
    state={'balance':balance,'stock':list(stock),'item':0,'quantity':1,'actions':[]}
    def offers(*a):
        return [dict(name=name,remaining=state['stock'][i],price=30,point=(520+i*230,220))
                for i,name in enumerate(shop.SPORES)]
    def view():
        s=captured('v0927-star_spores-blocked',True)
        for word in s.words:
            if word.text=='进化孢子':word.text=shop.SPORES[state['item']]
        return s
    monkeypatch.setattr(shop,'spore_offers',offers)
    monkeypatch.setattr(shop,'star_souls',lambda *a:state['balance'])
    d.b.read_number=lambda s,roi:state['quantity'] if roi[1]==511 else 30*state['quantity']
    d.b.match_template=lambda *a:True
    d.open_star_shop=d.settle_star_receipt=view
    def wait(predicate,*a,**kw):
        s=view()
        if not predicate(s):raise TaskBlocked('测试购买页面数量或总价未确认')
        return s
    d.wait_for_screen=wait
    def click_text(s,pattern,**kwargs):
        assert pattern=='^MAX$' and s.find(pattern,kwargs['roi'])
        state['quantity']=state['stock'][state['item']];state['actions'].append(('max',state['item']))
    d.b.click_text=click_text
    def click(s,point,anchors,reason):
        if reason.startswith('查看'):
            state['item']=next(i for i,name in enumerate(shop.SPORES) if name in reason)
            state['quantity']=1
        elif reason.startswith('增加'):
            state['quantity']+=1;state['actions'].append(('plus',state['item']))
        else:
            count=state['quantity'];cost=30*count
            assert reason==f'购买{count}份{shop.SPORES[state["item"]]}（{cost}饲星之魂）'
            assert d.day['star_purchase_pending']['count']==count and state['balance']>=cost
            state['actions'].append(('buy',state['item'],count,cost))
            if receipt in ('ok','stock_only'):state['stock'][state['item']]-=count
            if receipt in ('ok','money_only'):state['balance']-=cost
    d.b.click_at=click
    return state


def test_both_spores_buy_five_in_two_payments(tmp_path,monkeypatch):
    d=daily(tmp_path);state=batch_shop(d,monkeypatch)
    result=d.buy_star_spores()
    assert state['actions']==[('max',0),('buy',0,5,150),('max',1),('buy',1,5,150)]
    assert result['purchased']=={'进化孢子':5,'强化孢子':5} and result['spent']==300
    assert result['remaining']==0 and not d.day.get('star_purchase_pending')


def test_partial_day_stock_uses_remaining_three_and_two(tmp_path,monkeypatch):
    d=daily(tmp_path);state=batch_shop(d,monkeypatch,balance=200,stock=(3,2))
    result=d.buy_star_spores()
    assert [a for a in state['actions'] if a[0]=='buy']==[('buy',0,3,90),('buy',1,2,60)]
    assert result['remaining']==50


def test_insufficient_balance_batches_only_affordable_quantity(tmp_path,monkeypatch):
    d=daily(tmp_path);state=batch_shop(d,monkeypatch,balance=120)
    result=d.buy_star_spores()
    assert state['actions']==[('plus',0)]*3+[('buy',0,4,120)]
    assert result['purchased']=={'进化孢子':4} and result['status']=='skipped'


@pytest.mark.parametrize('receipt',['none','stock_only','money_only'])
def test_unconfirmed_whole_batch_is_never_paid_again(tmp_path,monkeypatch,receipt):
    d=daily(tmp_path);state=batch_shop(d,monkeypatch,receipt=receipt)
    with pytest.raises(TaskBlocked,match='库存或余额'):d.buy_star_spores()
    assert d.day['star_purchase_pending']['count']==5
    before=list(state['actions'])
    with pytest.raises(TaskBlocked,match='上次孢子'):d.buy_star_spores()
    assert state['actions']==before


@pytest.mark.parametrize('count',[1,5])
def test_pending_receipt_reconciles_even_when_both_items_are_sold_out(tmp_path,monkeypatch,count):
    d=daily(tmp_path);state=batch_shop(d,monkeypatch,balance=0,stock=(0,0))
    pending={'name':'进化孢子','price':30,'remaining':count,'balance':count*30}
    if count==5:pending['count']=count
    d.day['star_purchase_pending']=pending
    result=d.buy_star_spores()
    assert result['spent']==30*count and result['purchased']=={'进化孢子':count}
    assert not state['actions'] and not d.day.get('star_purchase_pending')
    d.day['star_purchase_pending']=deepcopy(pending)
    assert d.buy_star_spores()['spent']==30*count  # Report persisted before clearing the pending marker.


@pytest.mark.parametrize('quantity,total',[(1,30),(5,150),(3,90)])
def test_dialog_checks_selected_quantity_and_entire_price(tmp_path,quantity,total):
    from test_run_0923 import templates
    d=daily(tmp_path);templates(d.b);s=captured('v0927-star_spores-blocked',True)
    d.b.read_number=lambda s,roi:quantity if roi[1]==511 else total
    assert shop.spore_purchase_dialog(d.b,s,'进化孢子',quantity)
    assert shop.spore_purchase_dialog(d.b,s,'强化孢子',quantity) is None
    d.b.read_number=lambda s,roi:quantity if roi[1]==511 else total+30
    assert shop.spore_purchase_dialog(d.b,s,'进化孢子',quantity) is None


def test_each_abyss_team_is_selected_then_suppressed_then_challenged(tmp_path):
    p,_,_=flow(tmp_path,['failed','victory'],[100,100,50],teams=(2,1))
    actions=[];current=[None];suppressed=[None]
    def select(s,team,**kw):
        actions.append(('team',team));current[0]=team;suppressed[0]=None;return s
    def suppress(s):
        assert current[0] is not None
        actions.append(('suppress',current[0]));suppressed[0]=current[0];return s
    def start(*a):
        assert suppressed[0]==current[0]
        actions.append(('fight',current[0]))
    p.select_team=select;p.suppress=suppress;p.start_challenge=start
    p.play()
    assert actions==[('team',2),('suppress',2),('fight',2),('team',1),('suppress',1),('fight',1)]


def test_no_suppression_when_stamina_cannot_fund_challenge(tmp_path):
    p,chosen,clicks=flow(tmp_path,[],[8])
    p.suppress=lambda *a:pytest.fail('Insufficient stamina must not change suppression')
    assert '体力8/' in p.play() and not chosen and not clicks


def test_failed_team_selection_never_starts_suppression_or_battle(tmp_path):
    p,_,_=flow(tmp_path,[],[100])
    p.select_team=lambda *a,**kw:(_ for _ in ()).throw(UserStopped('用户停止'))
    p.suppress=p.start_challenge=lambda *a:pytest.fail('No suppression or challenge after stopped switch')
    with pytest.raises(UserStopped):p.play()


def test_real_warning_is_cancelled_on_return_without_switching_team(tmp_path):
    d=daily(tmp_path);warning=captured('v0965-team-suppression-warning',True);end=world()
    assert suppression_team_switch_dialog(warning) and not is_world(warning) and is_world(end)
    frames=iter([warning,end]);d.observe=lambda:next(frames);actions=[]
    d.b.click_text=lambda s,p,**kw:actions.append(p)
    d.b.click_at=lambda *a:pytest.fail('No click behind the modal')
    assert d.home() is end and actions==['^取消$']


def test_intended_team_change_confirms_warning_before_accepting_new_team(tmp_path):
    d=daily(tmp_path);warning=captured('v0965-team-suppression-warning',True)
    selected=screen(('排阵',145,15,47,26),('队伍1',969,83,57,25))
    frames=iter([warning,selected]);d.observe=lambda:next(frames);d.b.sleep=lambda _:None
    actions=[];d.b.click_text=lambda s,p,**kw:actions.append(p)
    assert d.await_world_team_switch('队伍1') is selected and actions==['^确定$']


def test_unrelated_confirmation_never_authorizes_switch(tmp_path):
    d=daily(tmp_path);warning=captured('v0965-team-suppression-warning',True)
    warning.words=[w for w in warning.words if '压制失效' not in w.text]
    d.observe=lambda:warning;d.b.sleep=lambda _:None
    d.b.click_text=lambda *a,**kw:pytest.fail('No generic confirmation')
    assert not suppression_team_switch_dialog(warning)
    with pytest.raises(TaskBlocked,match='切换未确认'):d.await_world_team_switch('队伍1')


def test_retired_team_restore_is_inert_even_for_old_helpers(tmp_path):
    d=daily(tmp_path);d.initial_team=1
    d.home=d.territory=d.observe=lambda *a:pytest.fail('Restoring a team must not navigate')
    d.restore_world_team()


def test_abyss_finish_keeps_selected_team(tmp_path):
    p=player(tmp_path);p.initial_team=1;p.last_team=2
    p.menu_page=lambda:captured('v099-abyss-menu')
    p.wait_screen=lambda *a:world();p.home=world;p.b.click_at=lambda *a:None
    p.restore_world_team=lambda:pytest.fail('Abyss must keep its final team')
    p.finish_world()
    assert p.report['resources_end']['stamina']==8
