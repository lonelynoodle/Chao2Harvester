"""The 红红 merchant must keep advancing a free skip until it actually exits."""
import pytest

from chao2.merchant import is_merchant,is_merchant_reward,merchant_choice,merchant_return_page
from chao2.policy import UserStopped,SafetyStop
from chao2.workflows import is_world
from test_configuration import captured
from test_merchant_event import setup,page,world


def test_current_red_merchant_refusal_includes_observed_ocr_variant():
    s=captured('v0925-merchant-red-choice',True)
    assert is_merchant(s)
    assert merchant_choice(s).text=='=口拒绝'
    for w in s.words:
        if w.text=='=口拒绝':w.text='一口拒绝'
    assert merchant_choice(s).text=='一口拒绝'
    assert merchant_choice(s,'buy') is None


@pytest.mark.parametrize('text',['购买后离开','不如买一个','不拒绝','拒绝免费奖励并购买','不知道'])
def test_skip_never_infers_no_purchase_from_ambiguous_substrings(text):
    s=captured('v0925-merchant-red-choice')
    for w in s.words:
        if w.text=='=口拒绝':w.text=text
    assert merchant_choice(s) is None


class RedMerchant:
    def __init__(self,tmp_path,swallowed='dialogue'):
        self.d,self.clicks=setup(tmp_path)
        self.page='dialogue';self.swallowed=swallowed;self.lost=False
        self.d.observe=self.observe;self.d.b.click_at=self.click
    def observe(self,*args):
        if self.page=='world':return world()
        if self.page=='shop':return page('shop')
        s=captured('v0925-merchant-red-'+('choice' if self.page=='choice' else 'dialogue'),True)
        if self.page=='farewell':
            for w in s.words:
                if '我的面具' in w.text:w.text='那好吧，我去问问别人。'
        return s
    def click(self,s,point,anchors,reason):
        assert s.has(*anchors)
        self.clicks.append((point,reason))
        if self.page==self.swallowed and not self.lost:self.lost=True;return
        self.page={'dialogue':'choice','choice':'farewell','farewell':'world','shop':'world'}[self.page]


@pytest.mark.parametrize('swallowed',['dialogue','choice','farewell'])
def test_red_merchant_skip_retries_lost_click_and_advances_to_actual_exit(tmp_path,swallowed):
    g=RedMerchant(tmp_path,swallowed)
    result=g.d.handle_merchant(g.observe())
    assert is_world(result) and len(g.clicks)==4
    row=g.d.report['merchant_events'][0]
    assert row['status']=='completed' and row['purchases']==0 and len(row['retries'])==1
    assert all('拒绝' in reason or reason=='继续神秘商人对话' for _,reason in g.clicks)
    assert g.d.battles==0 and not g.d.report.get('team_attempts')


def test_skip_shop_leave_can_retry_but_never_click_a_price(tmp_path):
    g=RedMerchant(tmp_path,'shop');g.page='shop'
    assert is_world(g.d.handle_merchant(g.observe()))
    assert len(g.clicks)==2 and all('不购买' in reason for _,reason in g.clicks)
    assert g.d.report['merchant_events'][0]['purchases']==0


def test_declined_choice_can_need_arrow_even_if_dialogue_text_does_not_change(tmp_path):
    g=RedMerchant(tmp_path,None);g.page='choice'
    observe=g.observe
    def unchanged(*args):
        s=observe()
        for w in s.words:
            if w.text=='那好吧，我去问问别人。':w.text='我的面具掉了,帮我一起找找吧'
        return s
    g.d.observe=unchanged
    assert is_world(g.d.handle_merchant(unchanged()))
    assert len(g.clicks)==2


def test_stop_setting_is_not_replaced_with_continuous_skip(tmp_path):
    g=RedMerchant(tmp_path)
    g.d.b.settings['merchant_options']['mode']='stop'
    with pytest.raises(UserStopped,match='自动停止'):g.d.handle_merchant(g.observe())
    assert not g.clicks


def test_trigger_disabled_still_leaves_merchant_untouched(tmp_path):
    g=RedMerchant(tmp_path)
    g.d.b.settings['trigger_events']['merchant']=False
    with pytest.raises(UserStopped,match='关闭自动处理'):g.d.handle_merchant(g.observe())
    assert not g.clicks


def test_payment_dialog_cannot_be_advanced_as_skip(tmp_path):
    g=RedMerchant(tmp_path)
    s=g.observe()
    from test_configuration import screen
    s.words.extend(screen(('是否花费240钻石购买',400,250,300,40),('取消',420,450,80,40)).words)
    with pytest.raises(SafetyStop):g.d.handle_merchant(s)
    assert not g.clicks


@pytest.mark.parametrize('start_on_reward,swallowed',[(False,False),(False,True),(True,False)])
def test_decline_reward_and_farewell_close_before_original_stage_resumes(tmp_path,start_on_reward,swallowed):
    d,clicks=setup(tmp_path)
    receipt=captured('v0925-merchant-red-reward',True)
    assert is_merchant(receipt) and is_merchant_reward(receipt)
    farewell=captured('v0925-merchant-red-dialogue',True)
    for w in farewell.words:
        if '我的面具' in w.text:w.text='它又马上回到草丛中窜来窜去了'
    frames=[captured('v0925-merchant-red-choice',True),receipt,farewell,
            captured('v0925-merchant-return-detail',True)]
    index=[1 if start_on_reward else 0];lost=[False]
    d.observe=lambda:frames[index[0]]
    def click(s,point,anchors,reason):
        assert s.has(*anchors)
        clicks.append((point,reason))
        if index[0]==1 and swallowed and not lost[0]:lost[0]=True;return
        index[0]+=1
    d.b.click_at=click
    assert merchant_return_page(d.handle_merchant(d.observe()))=='detail'
    row=d.report['merchant_events'][0]
    assert row['status']=='completed' and row['purchases']==0 and row['rewards_closed']==1
    assert len(row['rewards'])==1 and row['rewards'][0]['status']=='closed'
    assert len(clicks)==3-int(start_on_reward)+int(swallowed)
    assert d.battles==0


def test_non_merchant_reward_is_not_claimed_by_merchant_handler():
    s=captured('v0925-merchant-red-reward',True)
    s.words=[w for w in s.words if w.text!='神秘商人']
    assert not is_merchant_reward(s) and not is_merchant(s)
