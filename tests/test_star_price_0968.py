"""The batch total must survive button decoration without guessing digits."""
import pytest
from chao2 import star_shop as shop
from chao2.policy import TaskBlocked,UserStopped
from test_configuration import daily,screen,captured
from test_rift_main_0959 import offline_backend


def modal(name='进化孢子'):
    return screen((name,490,84,102,32),('购买数量',386,528,86,22),
                  ('购买',613,618,55,30),('MAX',808,522,60,31))


def price_reader(tmp_path,*,quantity=5,legacy=None,reads=('150','150'),currency=True):
    d=daily(tmp_path);b=d.b;calls=[]
    b.read_number=lambda s,roi:quantity if roi[1]==511 else legacy
    b.match_template=lambda *a:currency
    def crop(s,roi):
        calls.append(roi);return reads[(len(calls)-1)%2]
    b.read_text_crop=crop
    return d,calls


@pytest.mark.parametrize('name',shop.SPORES)
@pytest.mark.parametrize('quantity',[1,2,3,4,5,10])
def test_agreeing_clean_total_reads_accept_both_spores(tmp_path,name,quantity):
    total=str(30*quantity)
    d,calls=price_reader(tmp_path,quantity=quantity,reads=(total,total))
    assert shop.spore_purchase_dialog(d.b,modal(name),name,quantity)
    assert calls==[(633,646,68,28),(630,648,75,26)]


@pytest.mark.parametrize('reads',[('150','50'),('150_','150_'),('',''),('1500','1500'),
                                ('I50','I50'),('0','0')])
def test_conflicting_incomplete_or_wrong_totals_never_authorize_payment(tmp_path,reads):
    d,_=price_reader(tmp_path,reads=reads)
    assert shop.spore_purchase_dialog(d.b,modal(),'进化孢子',5) is None


@pytest.mark.parametrize('legacy',[30,150,180,1500])
def test_numeric_primary_read_is_not_overridden_with_a_different_crop(tmp_path,legacy):
    d,calls=price_reader(tmp_path,legacy=legacy)
    assert bool(shop.spore_purchase_dialog(d.b,modal(),'进化孢子',5))==(legacy==150)
    assert not calls


@pytest.mark.parametrize('quantity,currency',[(1,True),(5,False)])
def test_quantity_and_currency_must_be_confirmed_before_price_recovery(tmp_path,quantity,currency):
    d,calls=price_reader(tmp_path,quantity=quantity,currency=currency)
    assert shop.spore_purchase_dialog(d.b,modal(),'进化孢子',5) is None
    assert not calls


def test_price_recovery_honors_user_stop(tmp_path):
    d,_=price_reader(tmp_path)
    def stop(*_):raise UserStopped('用户停止')
    d.b.read_text_crop=stop
    with pytest.raises(UserStopped):shop.spore_purchase_dialog(d.b,modal(),'进化孢子',5)


def test_actual_maa_recovers_decorated_150_from_original_failure(offline_backend):
    s=captured('v0968-spore-five',True)
    assert offline_backend.read_text_crop(s,(640,646,55,32))=='150_'
    assert offline_backend.read_number(s,(640,646,55,32)) is None
    assert shop.spore_purchase_dialog(offline_backend,s,'进化孢子',5)
    assert shop.spore_purchase_dialog(offline_backend,s,'进化孢子',1) is None


def batch(tmp_path,monkeypatch):
    import test_spore_abyss_0965 as old
    monkeypatch.setattr(old,'captured',lambda *a:modal())
    d=daily(tmp_path);state=old.batch_shop(d,monkeypatch,balance=1180)
    d.b.read_number=lambda s,roi:state['quantity'] if roi[1]==511 else None
    d.b.read_text_crop=lambda s,roi:str(30*state['quantity'])
    return d,state


def test_both_five_packs_are_bought_once_and_stock_and_money_reconciled(tmp_path,monkeypatch):
    d,state=batch(tmp_path,monkeypatch)
    result=d.buy_star_spores()
    assert state['actions']==[('max',0),('buy',0,5,150),('max',1),('buy',1,5,150)]
    assert result['purchased']=={'进化孢子':5,'强化孢子':5}
    assert result['spent']==300 and result['remaining']==880 and state['stock']==[0,0]
    assert 'star_purchase_pending' not in d.day


def test_bad_bulk_total_never_creates_pending_payment_or_charges(tmp_path,monkeypatch):
    d,state=batch(tmp_path,monkeypatch)
    d.b.read_text_crop=lambda s,roi:'30' if state['quantity']==1 else '150_'
    with pytest.raises(TaskBlocked):d.buy_star_spores()
    assert state['actions']==[('max',0)] and state['balance']==1180
    assert 'star_purchase_pending' not in d.day
