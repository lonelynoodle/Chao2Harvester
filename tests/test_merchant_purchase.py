"""Buying is tested offline only; fixtures originate from the observed shop."""
import copy
import pytest
from chao2.backend import Word
from chao2.configuration import normalize_settings
from chao2.merchant import (merchant_choice, select_merchant_offer,
                            merchant_purchase_confirmation,merchant_return_page)
from chao2.merchant_settings import merchant_options
from chao2.policy import SafetyStop,UserStopped
from chao2.world_events import is_map_choice,map_choice_controls
from chao2.workflows import is_world
from test_configuration import daily,screen,captured
from test_merchant_event import setup,page,world


def buy_options(*ids,budget=240):
    return {'merchant_options':{'mode':'buy','diamond_budget':budget,
                               'items':[{'id':key,'enabled':True} for key in ids]}}


def buyer(tmp_path,*ids,budget=240):
    d,clicks=setup(tmp_path)
    d.b.settings=normalize_settings(buy_options(*(ids or ('spore',)),budget=budget))
    d.b.match_template=lambda *a:True
    return d,clicks


def after_purchase(balance=889):
    s=world()
    for w in s.words:
        if w.text=='1129':w.text=str(balance)
    return s


def confirmation(item='强化孢子',price=240):
    return screen((f'是否花费{price}钻石购买{item}？',340,280,580,40),
                  ('取消',420,460,80,40),('确定',760,460,80,40))


def test_new_settings_default_skip_no_selected_purchase_and_preserve_others():
    raw={'other':'keep','merchant_options':{'mode':'stop','items':[{'id':'gold','enabled':True}]}}
    expected=copy.deepcopy(raw)
    normalized=normalize_settings(raw)
    assert raw==expected and normalized['other']=='keep'
    assert normalized['merchant_options']['mode']=='stop' and normalized['merchant_options']['items'][0]['id']=='gold'
    options=merchant_options({})
    assert options['mode']=='skip' and not any(i['enabled'] for i in options['items'])


@pytest.mark.parametrize('bad',[{'mode':'unknown'},{'mode':True},{'diamond_budget':-1},{'diamond_budget':True},
                              {'items':['gold']},{'items':[{'id':'unknown','enabled':True}]},
                              {'items':[{'id':'gold','enabled':True},{'id':'gold','enabled':False}]},
                              {'items':[{'id':'gold','enabled':'yes'}]}])
def test_invalid_purchase_settings_rejected_before_game_connection(bad):
    with pytest.raises(ValueError):normalize_settings({'merchant_options':bad})


@pytest.mark.parametrize('name,expected',[('choice','绕着它转一圈'),('circle','再绕着它转三圈'),
                                        ('speed-again','继续加速'),('enter-shop','进店')])
def test_buy_only_enters_observed_route_when_requested(name,expected):
    assert merchant_choice(page(name),'buy').text==expected


def test_stop_mode_never_clicks_leaves_or_recovers_home(tmp_path):
    d,clicks=setup(tmp_path)
    d.b.settings['merchant_options']['mode']='stop'
    d.observe=lambda:pytest.fail('Stop immediately, do not navigate away')
    with pytest.raises(UserStopped,match='自动停止'):
        d.handle_merchant(page('shop'))
    assert not clicks and d.report['merchant_events'][0]['status']=='stopped'


def test_offer_selection_obeys_priority_enabled_flag_budget_and_currency(tmp_path):
    d,_=buyer(tmp_path,'spore','lifesteal_core')
    options=merchant_options(d.b.settings)
    shop=page('shop')
    assert select_merchant_offer(d.b,shop,options)['id']=='spore'
    options['items'][0]['enabled']=False
    assert select_merchant_offer(d.b,shop,options)['id']=='lifesteal_core'
    assert select_merchant_offer(d.b,shop,options,spent=41) is None
    d.b.match_template=lambda *a:False
    assert select_merchant_offer(d.b,shop,options) is None


def test_disabled_buy_or_unselected_items_never_press_price(tmp_path):
    d,_=buyer(tmp_path)
    for options in (merchant_options({}),merchant_options({'merchant_options':{'mode':'buy'}})):
        assert select_merchant_offer(d.b,page('shop'),options) is None
    options=merchant_options(d.b.settings)
    options['mode']='skip'
    assert select_merchant_offer(d.b,page('shop'),options) is None


def test_wrong_stock_price_unreadable_balance_and_unselected_items_block_purchase(tmp_path):
    d,_=buyer(tmp_path)
    options=merchant_options(d.b.settings)
    for changed in ('price','stock','name','confidence'):
        s=page('shop')
        for w in s.words:
            if w.text=='强化孢子' and changed=='name':w.text='未知孢子'
            if w.text=='剩余1' and 450<w.center[0]<600 and w.center[1]<200 and changed=='stock':w.text='剩余0'
            if w.text=='240' and 500<w.center[0]<600 and w.center[1]<230:
                if changed=='price':w.text='241'
                if changed=='confidence':w.score=.7
        assert select_merchant_offer(d.b,s,options) is None
    s=page('shop');s.words=[w for w in s.words if w.text!='1129']
    with pytest.raises(SafetyStop,match='余额'):select_merchant_offer(d.b,s,options)


def test_purchase_method_cannot_bypass_skip_mode(tmp_path):
    d,_=setup(tmp_path)
    with pytest.raises(SafetyStop,match='未开启'):
        d.purchase_merchant_item(page('shop'),{}, {},merchant_options(buy_options('spore')))


def test_only_exact_item_and_diamond_price_can_authorize_confirmation(tmp_path):
    d,_=buyer(tmp_path)
    offer=select_merchant_offer(d.b,page('shop'),merchant_options(d.b.settings))
    assert merchant_purchase_confirmation(confirmation(),offer)
    for bad in (confirmation(price=241),confirmation(item='领域石'),
                screen(('确定',760,460,80,40),('取消',420,460,80,40))):
        assert merchant_purchase_confirmation(bad,offer) is None
    with pytest.raises(SafetyStop):d.b.guard(confirmation())
    d.b.merchant_purchase_pending=offer
    d.b.guard(confirmation())
    with pytest.raises(SafetyStop):d.b.guard(confirmation(price=241))


@pytest.mark.parametrize('with_confirmation',[False,True])
def test_purchase_records_verified_charge_once_and_resumes(tmp_path,with_confirmation):
    d,clicks=buyer(tmp_path)
    options=merchant_options(d.b.settings)
    offer=select_merchant_offer(d.b,page('shop'),options)
    row={'purchases':0};d.report['merchant_events']=[row]
    frames=[page('shop')]
    if with_confirmation:frames.extend([confirmation(),confirmation()])
    frames.append(after_purchase())
    sequence=iter(frames);d.observe=lambda:next(sequence)
    result=d.purchase_merchant_item(page('shop'),row,offer,options)
    assert is_world(result) and len(clicks)==(2 if with_confirmation else 1)
    assert row['purchase']['confirmed'] and row['purchase']['balance_after']==889
    assert d.report['diamond_spend']==d.report['merchant_diamond_spend']==240
    assert d.b.merchant_purchase_pending is None


def test_changed_offer_never_buys_and_uncertain_result_never_retries(tmp_path):
    d,clicks=buyer(tmp_path)
    options=merchant_options(d.b.settings)
    offer=select_merchant_offer(d.b,page('shop'),options)
    changed=page('shop')
    for w in changed.words:
        if w.text=='强化孢子':w.text='其他东西'
    d.observe=lambda:changed
    with pytest.raises(SafetyStop,match='改变'):
        d.purchase_merchant_item(page('shop'),{},offer,options)
    assert not clicks
    row={'purchases':0};d.report['merchant_events']=[row]
    d.observe=lambda:page('shop')
    with pytest.raises(SafetyStop,match='未确认'):
        d.purchase_merchant_item(page('shop'),row,offer,options)
    assert len(clicks)==1 and row['purchases']==0 and not row['purchase']['confirmed']
    assert row['purchase']['status']=='unconfirmed' and d.report['diamond_spend'] is None


def test_wrong_charge_is_not_reported_as_success(tmp_path):
    d,clicks=buyer(tmp_path)
    options=merchant_options(d.b.settings);offer=select_merchant_offer(d.b,page('shop'),options)
    row={'purchases':0};d.report['merchant_events']=[row]
    frames=iter([page('shop'),after_purchase(1000)]);d.observe=lambda:next(frames)
    with pytest.raises(SafetyStop,match='不符'):
        d.purchase_merchant_item(page('shop'),row,offer,options)
    assert len(clicks)==1 and not d.report.get('merchant_diamond_spend')


def test_actual_return_to_three_overlapping_targets_is_completed_then_closed(tmp_path):
    d,clicks=setup(tmp_path)
    choice=captured('v0911-merchant-map-choice')
    assert is_map_choice(choice) and not is_world(choice) and merchant_return_page(choice)=='map_choice'
    frames=iter([page('shop'),world(),choice,choice])
    d.observe=lambda:next(frames)
    assert d.handle_merchant(page('shop')) is choice
    assert len(clicks)==1
    d.observe=world
    assert is_world(d.home(choice))
    assert len(clicks)==2 and clicks[-1][0]==map_choice_controls(choice)[1].center


def test_new_overlap_selects_same_copy_not_neighbor(tmp_path):
    d,clicks=setup(tmp_path)
    listing=screen(('异象',970,20,60,30),('本周已获取友好点数910',890,80,250,30),
                   ('阿宁早点睡',916,213,110,27),('20',1070,260,23,17))
    detail=captured('copy-current-detail')
    sequence=iter([captured('v0911-merchant-map-choice'),detail])
    d.observe=lambda:next(sequence);d.read_copy_names=lambda s:s
    assert d.open_copy_detail(listing,268) is detail
    assert clicks[-1][0]==(833,415)

def test_unreadable_x_uses_its_pixels_not_arbitrary_letter_o():
    s=captured('v0911-merchant-map-choice',True)
    for w in s.words:
        if w.text=='x':w.text='o'
    assert is_map_choice(s)
    assert map_choice_controls(s)[1].center==(967,243)
    s.image[:]=0
    assert not is_map_choice(s)
