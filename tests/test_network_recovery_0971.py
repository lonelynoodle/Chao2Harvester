"""Common reconnect prompts must not restart battles or repeat purchases."""
from copy import deepcopy
import pytest
from chao2.network_recovery import network_retry_button
from chao2.policy import SafetyStop,UserStopped
from test_configuration import daily,screen


def prompt(text='网络翻船中,是否重试?'):
    return screen((text,490,299,283,26),('取消',454,480,55,32),('确定',769,481,56,31))


def world():
    return screen(('任务挑战',1196,42,80,24),('世界回响',1196,138,80,24),('35/183',500,12,80,28))


@pytest.mark.parametrize('text',['网络翻船中,是否重试?','网络翻船中，是否重试？',
                               '网络翻船中, 是否重试？','网络翻船中 ， 是否重试 ?'])
def test_both_punctuation_forms_and_spaces_are_confirmed(text):
    assert network_retry_button(prompt(text)).text=='确定'


@pytest.mark.parametrize('text',['是否消耗50钻石购买？','网络重试礼包是否购买？','是否重试？','网络翻船中,是否重置?'])
def test_purchase_or_incomplete_prompts_are_not_network_confirmation(text):
    assert network_retry_button(prompt(text)) is None


@pytest.mark.parametrize('missing',['确定','取消'])
def test_both_controls_in_the_expected_dialog_are_required(missing):
    s=prompt();s.words=[w for w in s.words if w.text!=missing]
    assert network_retry_button(s) is None


def test_generic_task_observe_recovers_current_request_without_new_business_action(tmp_path):
    d=daily(tmp_path);d.active_task='rift';d.battles=1;d.task_counts={'rift':1}
    pending={'name':'进化孢子','count':5,'balance':1180}
    d.day['star_purchase_pending']=deepcopy(pending)
    after=world();frames=iter([prompt(),prompt(),after]);d.b.observe=lambda *a:next(frames)
    d.b.sleep=lambda *_:None;clicks=[]
    d.b.click_at=lambda s,p,a,r:clicks.append((p,a,r))
    d.dismiss_level_up=d.dismiss_triggered_popups=d.calibrate_collection_reward=d.recover_world_navigation=lambda s:s
    result=d.observe()
    assert result is after and d.last_screen is after
    assert len(clicks)==1 and clicks[0][0]==(797,496) and '网络翻船' in clicks[0][2]
    assert d.report['network_recoveries'][0]['status']=='recovered'
    assert d.battles==1 and d.task_counts=={'rift':1} and d.day['star_purchase_pending']==pending


def test_prompt_disappearing_before_click_does_not_reuse_its_coordinates(tmp_path):
    d=daily(tmp_path);after=world();d.b.observe=lambda:after
    d.b.click_at=lambda *a:pytest.fail('The dialog already disappeared')
    assert d.recover_network_dialog(prompt()) is after
    assert d.report['network_recoveries'][0]['attempts']==0


def test_swallowed_retry_is_rechecked_and_clicked_again(tmp_path):
    d=daily(tmp_path);after=world();frames=iter([prompt(),prompt(),prompt(),after])
    d.b.observe=lambda:next(frames);clicks=[]
    d.b.click_at=lambda *a:clicks.append(a)
    assert d.recover_network_dialog(prompt()) is after and len(clicks)==2
    assert d.report['network_recoveries'][0]['attempts']==2


def test_persistent_outage_is_bounded_and_keeps_request_unconfirmed(tmp_path):
    d=daily(tmp_path);s=prompt();d.b.observe=lambda:s;clicks=[]
    d.b.click_at=lambda *a:clicks.append(a)
    with pytest.raises(SafetyStop,match='连续重试3次'):d.recover_network_dialog(s)
    assert len(clicks)==3 and d.last_screen is s and d.battles==0
    assert d.report['network_recoveries'][0]['status']=='blocked'


def test_stop_interrupts_recovery_before_any_retry(tmp_path):
    d=daily(tmp_path);d.b.stop.set()
    d.b.observe=lambda:pytest.fail('Stopped run must not keep reading')
    with pytest.raises(UserStopped):d.recover_network_dialog(prompt())


def test_read_only_observation_preserves_prompt_and_sends_no_input(tmp_path):
    d=daily(tmp_path);s=prompt();d.b.observe=lambda *a:s
    d.b.click_at=lambda *a:pytest.fail('Read-only observation cannot reconnect')
    d.calibrate_collection_reward=d.recover_world_navigation=lambda s:s
    assert d.observe(dismiss_popups=False) is s
    assert not d.report.get('network_recoveries')


def test_network_retry_over_shop_does_not_allow_an_actual_purchase_prompt(tmp_path):
    d=daily(tmp_path);s=prompt();s.words+=screen(('购买',613,618,55,30)).words
    d.b.guard(s)  # The only active confirmation is the proven reconnect.
    with pytest.raises(SafetyStop):d.b.guard(prompt('是否消耗50钻石购买？'))


def test_legacy_battle_handler_also_accepts_ascii_comma(tmp_path):
    d=daily(tmp_path);clicks=[];d.b.click_text=lambda *a,**kw:clicks.append((a,kw))
    assert d.retry_battle_network(prompt(),0)
    assert len(clicks)==1 and clicks[0][0][1]=='^确定$'
