from copy import deepcopy

import pytest

from chao2.configuration import normalize_settings
from chao2.trigger_events import triggered_event,rift_invitation,trigger_options,REFUSE_ROI
from chao2.policy import UserStopped,TaskBlocked,EncounterInterrupted
from chao2.workflows import is_world
from test_configuration import captured,daily,screen


def test_defaults_preserve_existing_merchant_strategy_and_other_configuration():
    saved={'trigger_events':{'sage_quiz':False},'merchant_options':{'mode':'stop'},'custom':'keep'}
    cfg=normalize_settings(saved)
    assert cfg['trigger_events']=={'sage_quiz':False,'merchant':True,'star_gift':True,'rift_invitation':True}
    assert cfg['merchant_options']['mode']=='stop' and cfg['custom']=='keep'
    assert cfg==normalize_settings(cfg) and saved['trigger_events']=={'sage_quiz':False}
    for invalid in (None,[],{'merchant':1},{'rift_invitation':'false'}):
        with pytest.raises(ValueError):trigger_options({'trigger_events':invalid})


def test_real_random_invitation_is_a_modal_not_the_result_or_a_friend_request():
    s=captured('v0922-rift-invitation',True)
    assert triggered_event(s)=='rift_invitation' and rift_invitation(s)
    assert not is_world(s)
    assert rift_invitation(captured('v0921-friend-confirm',True)) is None
    assert rift_invitation(captured('other-social-menu',True)) is None
    q=deepcopy(s);q.words=[w for w in q.words if w.text!='确定']
    assert rift_invitation(q) is None


def test_invitation_clicks_only_refusal_then_returns_original_page(tmp_path):
    d=daily(tmp_path);s=captured('v0922-rift-invitation',True)
    after=screen(('胜利',100,250,200,70),('退出',1100,600,100,40))
    d.b.observe=lambda:after;calls=[]
    d.b.click_text=lambda q,p,**kw:calls.append((p,kw['roi']))
    assert d.dismiss_triggered_popups(s) is after
    assert calls==[('^(?:取消|拒绝)$',REFUSE_ROI)]
    assert d.report['rejected_invitations'][0]['status']=='refused'


def test_invitation_retries_bounded_and_never_accepts(tmp_path):
    d=daily(tmp_path);s=captured('v0922-rift-invitation',True);calls=[]
    d.b.observe=lambda:s;d.b.sleep=lambda _:None;d.b.click_text=lambda q,p,**kw:calls.append(p)
    with pytest.raises(TaskBlocked,match='尝试3次'):d.refuse_rift_invitation(s)
    assert calls==['^(?:取消|拒绝)$']*3


def test_disabled_invitation_leaves_modal_and_stops_without_input(tmp_path):
    d=daily(tmp_path,{'trigger_events':{'rift_invitation':False}})
    d.b.click_text=lambda *a,**kw:pytest.fail('Disabled event must not click')
    with pytest.raises(UserStopped,match='已关闭自动处理'):d.dismiss_triggered_popups(captured('v0922-rift-invitation',True))


def test_read_only_observation_never_dismisses_an_invitation(tmp_path):
    d=daily(tmp_path);s=captured('v0922-rift-invitation',True)
    d.b.observe=lambda *a:s
    d.b.click_text=lambda *a,**kw:pytest.fail('Read-only observation must not click')
    assert d.observe(dismiss_popups=False) is s
    assert not d.report.get('rejected_invitations')


@pytest.mark.parametrize('key,fixture',[('merchant','v0911-merchant-intro'),('star_gift','v0921-star-gift'),('sage_quiz','v0915-sage-dominance')])
def test_classifier_and_independent_switches(key,fixture,tmp_path):
    d=daily(tmp_path,{'trigger_events':{key:False}});s=captured(fixture,True)
    assert triggered_event(s)==key
    d.b.click_at=lambda *a:pytest.fail('Disabled event clicked')
    with pytest.raises(UserStopped,match='已关闭自动处理'):d.dismiss_triggered_popups(s)


def test_question_interrupts_main_without_requiring_anomaly_task(tmp_path):
    d=daily(tmp_path);s=captured('v0915-sage-dominance',True);d.selected=['main'];calls=[]
    d.wandering_sage=lambda **kw:calls.append(kw['entry']) or '问答已完成'
    d.observe=lambda:screen()
    with pytest.raises(EncounterInterrupted):d.resolve_path_event(s)
    assert calls==[s] and d.report['anomaly_tasks']['sage']['resumed']


def test_quiz_handler_does_not_recursively_trigger_itself(tmp_path):
    d=daily(tmp_path);d._sage_active=True
    d.resume_sage_dialog=lambda *a:pytest.fail('Recursive quiz')
    assert d.resolve_path_event(captured('v0915-sage-dominance',True)) is None


def test_other_rewards_run_independently_and_before_inventory(tmp_path):
    d=daily(tmp_path,{'task_options':{'other':{'friend_management':False,'collect_contract':False,'daily_puzzle':False,'buy_star_spores':False}}})
    calls=[];d.home=lambda:None
    for method,key in [('collect_daily_single','single'),('collect_plane_lord','plane'),('clear_bag_notifications','bag')]:
        setattr(d,method,lambda k=key:calls.append(k) or {'status':'done','message':k})
    assert d.other()=='single；plane；bag' and calls==['single','plane','bag']
