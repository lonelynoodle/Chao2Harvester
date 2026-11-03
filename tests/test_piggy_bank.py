"""Paid hammer boundaries, single-submit recovery and actual captured OCR."""
import json

import pytest

from chao2.backend import Backend,ROOT
from chao2.configuration import normalize_settings
from chao2.piggy_bank import (LEFT_CLAIM,is_piggy_page,
    piggy_purchase_confirmation,read_piggy_view,read_piggy_offer,piggy_claim_offer)
from chao2.policy import SafetyStop,TaskBlocked
from test_configuration import captured,daily


PENDING={'stored':230,'stock':0,'price':50,'quantity':1}


def test_actual_maa_piggy_storage_stock_price_currency_and_balance():
    from maa.resource import Resource
    from maa.tasker import Tasker
    from test_maa_recognition import Offline
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({});b.tasker=t
    s=captured('v0951-piggy-page',True)
    assert read_piggy_view(b,s)=={'stored':230,'gold':230000,'stock':0,'quantity':1}
    assert read_piggy_view(b,captured('v0951-piggy-stock-one',True))=={
        'stored':240,'gold':240000,'stock':1,'quantity':1}
    assert read_piggy_view(b,captured('v0951-piggy-claimed',True))=={
        'stored':40,'gold':40000,'stock':0,'quantity':1}
    offer=read_piggy_offer(b,captured('v0951-piggy-buy-dialog',True),PENDING)
    assert (offer['remaining'],offer['balance'])==(3,9205)
    # The top-right gold hammer is not accepted as the wooden-claim icon.
    assert not b.match_template(s,'piggy-wood-claim.png',[745,560,100,90],.9)
    assert not is_piggy_page(captured('v0951-piggy-rules'))
    assert piggy_claim_offer(b,captured('v0951-piggy-claim-offer',True),
        {'stored_before_claim':240,'stock_before_claim':1,'quantity':1})


@pytest.mark.parametrize('replacement',[
    '是否消耗60钻石购买1木锤?','是否消耗50钻石购买2木锤?',
    '是否消耗50钻石购买1金锤?','是否消耗50金币购买1木锤?',
])
def test_purchase_guard_rejects_other_price_quantity_currency_or_hammer(replacement):
    b=Backend({});b.piggy_purchase_pending=dict(PENDING)
    s=captured('v0951-piggy-buy-dialog')
    next(w for w in s.words if w.text.startswith('是否消耗')).text=replacement
    assert not piggy_purchase_confirmation(s,PENDING)
    with pytest.raises(SafetyStop):b.guard(s)


@pytest.mark.parametrize('pending',[None,{},dict(PENDING,stored=199),dict(PENDING,stock=1),
    dict(PENDING,price=100),dict(PENDING,quantity=2)])
def test_purchase_guard_needs_armed_eligible_transaction(pending):
    b=Backend({});b.piggy_purchase_pending=pending
    with pytest.raises(SafetyStop):b.guard(captured('v0951-piggy-buy-dialog'))


def test_purchase_guard_allows_only_verified_context():
    b=Backend({});b.piggy_purchase_pending=dict(PENDING)
    b.guard(captured('v0951-piggy-buy-dialog'))


def test_stock_fallback_confirms_new_hammer_and_rejects_hidden_leading_digit():
    b=Backend({});b.match_template=lambda *a:True
    b.read_text_crop=lambda *a:'已储存230钻石和230000金币'
    b.read_number=lambda s,roi:None if roi==(1050,5,80,34) else 1
    s=captured('v0951-piggy-page',True)
    assert read_piggy_view(b,s)['stock']==1
    s.image[15:28,1096:1100]=255
    with pytest.raises(TaskBlocked,match='前位数字'):read_piggy_view(b,s)


def simulation(tmp_path,*,stored=230,stock=0,wallet=9205,buy_stuck=False,claim_stuck=False,bad_charge=False):
    d=daily(tmp_path,{'task_options':{'other':{'piggy_bank':True}}})
    state={'stored':stored,'stock':stock,'wallet':wallet,'mode':'page','purchases':0,'claims':0}
    d.b.sleep=lambda *a:None;d.b.save_screen=lambda *a:None
    d.piggy_wallet=lambda:state['wallet']
    def observe():
        name={'offer':'buy-dialog','claim_offer':'claim-offer','page':'page'}[state['mode']]
        return captured('v0951-piggy-'+name)
    d.observe=observe;d.activity_tab=lambda name:observe()
    d.piggy_view=lambda s=None:(observe(),{'stored':state['stored'],'gold':state['stored']*1000,
        'stock':state['stock'],'quantity':1})
    d.wait_for_screen=lambda predicate,*a,**kw:observe() if predicate(observe()) else None
    d.b.match_template=lambda *a:True
    d.b.read_number=lambda s,roi:{(801,498,30,27):50,(565,306,50,30):200,
        (649,305,83,31):200000,(805,498,20,25):1}.get(roi,wallet)
    def open_offer(*a,**kw):
        assert state['stored']>=200 and state['stock']==0
        state['mode']='offer'
    d.b.click_at=open_offer
    def click(s,pattern,roi=None,**kw):
        journal=json.loads(d.state_file.read_text('utf-8'))['piggy_pending']
        if pattern=='^确定$':
            assert journal['phase']=='buy_requested'
            assert state['mode']=='offer' and state['purchases']==0
            state['purchases']+=1
            if not buy_stuck:
                state['stock']+=1;state['wallet']-=60 if bad_charge else 50;state['mode']='page'
        elif pattern=='^立即领取$':
            assert journal['phase']=='claim_preview' and roi==LEFT_CLAIM
            state['mode']='claim_offer'
        elif pattern=='^领取$':
            assert journal['phase']=='claim_requested' and roi==(680,440,250,100)
            assert state['stored']>=200 and state['stock']>=1 and state['claims']==0
            state['claims']+=1
            if not claim_stuck:
                state['stock']-=1;state['stored']-=200;state['wallet']+=200;state['mode']='page'
        else:raise AssertionError(pattern)
    d.b.click_text=click
    return d,state


@pytest.mark.parametrize('stored',[0,199])
def test_below_threshold_never_buys_or_uses_existing_stock(tmp_path,stored):
    for stock in (0,2):
        d,state=simulation(tmp_path,stored=stored,stock=stock)
        assert d.collect_piggy_bank()['status']=='skipped'
        assert state['purchases']==state['claims']==0


@pytest.mark.parametrize('stored',[200,230,600])
def test_one_purchase_and_one_claim_per_run_with_exact_wallet_change(tmp_path,stored):
    d,state=simulation(tmp_path,stored=stored)
    result=d.collect_piggy_bank()
    assert result['status']=='done' and result['spent']==50 and result['claimed']==1
    assert state['wallet']==9355 and state['stored']==stored-200
    assert state['purchases']==state['claims']==1
    assert not d.state.get('piggy_pending')
    assert d.report['diamond_spend']==50
    d.collect_piggy_bank()
    assert state['purchases']==state['claims']==1


def test_owned_hammer_works_with_no_purchase_and_less_than_50_diamonds(tmp_path):
    d,state=simulation(tmp_path,stock=2,wallet=10)
    assert d.collect_piggy_bank()['spent']==0
    assert state['purchases']==0 and state['claims']==1 and state['stock']==1
    assert state['wallet']==210


def test_insufficient_diamonds_skips_purchase(tmp_path):
    d,state=simulation(tmp_path,wallet=49)
    assert d.collect_piggy_bank()['status']=='skipped'
    assert state['purchases']==state['claims']==0


@pytest.mark.parametrize('case,phase,counts',[
    ({'buy_stuck':True},'buy_requested',(1,0)),
    ({'claim_stuck':True},'claim_requested',(1,1)),
    ({'bad_charge':True},'buy_requested',(1,0)),
])
def test_uncertain_result_is_journaled_and_never_replayed_after_restart(tmp_path,case,phase,counts):
    d,state=simulation(tmp_path,**case)
    with pytest.raises(SafetyStop):d.collect_piggy_bank()
    assert (state['purchases'],state['claims'])==counts
    saved=json.loads(d.state_file.read_text('utf-8'))
    assert saved['piggy_pending']['phase']==phase
    restarted,_=simulation(tmp_path)
    restarted.state=saved
    with pytest.raises(SafetyStop,match='上次'):restarted.collect_piggy_bank()
    assert (state['purchases'],state['claims'])==counts


def test_new_piggy_option_is_opt_in_and_preserves_other_settings():
    assert normalize_settings({})['task_options']['other']['piggy_bank'] is False
    settings=normalize_settings({'task_options':{'other':{'piggy_bank':True,'collect_contract':False}}})
    assert settings['task_options']['other']['piggy_bank'] is True
    assert settings['task_options']['other']['collect_contract'] is False


def test_disabled_feature_rejects_direct_invocation(tmp_path):
    d=daily(tmp_path)
    with pytest.raises(SafetyStop,match='未开启'):d.collect_piggy_bank()


def test_post_purchase_ocr_failure_stops_all_work_and_keeps_transaction(tmp_path):
    d,state=simulation(tmp_path)
    original=d.piggy_view
    def read(s=None):
        if state['purchases']:raise TaskBlocked('木锤库存未读清')
        return original(s)
    d.piggy_view=read
    with pytest.raises(SafetyStop,match='交易已提交'):d.collect_piggy_bank()
    assert state['purchases']==1 and state['claims']==0
    assert d.state['piggy_pending']['phase']=='buy_requested'


def test_verified_purchase_can_finish_from_current_wallet_without_buying_again(tmp_path):
    d,state=simulation(tmp_path,stock=1,wallet=9500)
    row={**PENDING,'spent':50,'claimed':0,'diamonds_before':9455,'diamonds_after_purchase':9405}
    d.report.setdefault('other_tasks',{})['piggy_bank']=row
    d.piggy_journal(row,'purchased')
    _,view=d.piggy_view()
    result=d._claim_piggy_bank(row,view,9500)
    assert result['diamonds_after']==9700 and result['spent']==50
    assert state['purchases']==0 and state['claims']==1


@pytest.mark.parametrize('roi,value',[
    ((565,306,50,30),199),((649,305,83,31),20000),((805,498,20,25),2),
])
def test_claim_confirmation_rejects_wrong_reward_or_hammer_count(tmp_path,roi,value):
    d,state=simulation(tmp_path)
    original=d.b.read_number
    d.b.read_number=lambda s,r:value if r==roi else original(s,r)
    assert not piggy_claim_offer(d.b,captured('v0951-piggy-claim-offer'),
        {'stored_before_claim':240,'stock_before_claim':1,'quantity':1})


def test_submitted_claim_can_be_verified_without_replaying_input(tmp_path):
    d,state=simulation(tmp_path,stored=40,stock=0,wallet=9605)
    row={'spent':50,'claimed':0,'quantity':1,'diamonds_before':9455}
    d.piggy_journal(row,'claim_requested')
    result=d._verify_piggy_claim(row,{'stored':240,'stock':1},9405)
    assert result['claimed']==1 and result['diamonds_after']==9605
    assert state['claims']==state['purchases']==0
