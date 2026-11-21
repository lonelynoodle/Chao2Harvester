"""Check refill order using the actual 20:14 offer and interrupted run flow."""
import threading
import pytest
import chao2.workflows as flow
from chao2.activities import stamina_servings
from chao2.policy import UserStopped
from test_configuration import daily,captured,screen


def test_reported_offer_is_one_free_serving_with_capacity():
    s=captured('v094-stamina-one',True)
    assert stamina_servings(s)==1
    assert s.find('^领取奖励$') and s.find('^2/166$')


def test_check_target_before_opening_offer_then_claim_on_first_visit(tmp_path):
    d=daily(tmp_path);d.selected=['main']
    state={'balance':2,'page':'world'};actions=[]
    def home():state['page']='world';return screen()
    d.home=home
    d.world_resources=lambda _:{'stamina':state['balance'],'stamina_cap':166}
    d.stamina_outlet_available=lambda *a:actions.append('check-target') or True
    def offer():
        actions.extend(['open-activity','open-offer']);state['page']='offer'
        return captured('v094-stamina-one',True)
    d.stamina_offer=offer
    def click(s,pattern,**kw):
        if pattern=='每日三发':
            actions.append('open-offer');state['page']='offer'
        else:
            assert state['page']=='offer'
            actions.append('claim');state.update(balance=state['balance']+100,page='reward')
    d.b.click_text=click
    d.observe=lambda:captured('v094-stamina-one',True) if state['page']=='offer' else screen(('获得奖励',500,350,100,30))
    d.b.click_at=lambda *a:actions.append('close-reward')
    def run(task):actions.append(task);state['balance']-=5
    d.execute_task=run
    d.replenish_stamina()
    assert actions==['check-target','open-activity','open-offer','claim','close-reward','main']
    assert d.report['stamina_claims']==1 and state['balance']==97
    assert d.report['stamina_refill']['status']=='done'


def test_no_outlet_leaves_free_reward_page_unopened(tmp_path):
    d=daily(tmp_path);d.selected=['main'];d.home=lambda:screen()
    d.world_resources=lambda _:{'stamina':2,'stamina_cap':166}
    d.stamina_outlet_available=lambda *a:False
    d.stamina_offer=lambda:pytest.fail('Do not open before finding a usable outlet')
    d.replenish_stamina()
    assert d.report['stamina_refill']['claimed']==0
    assert any('暂未找到可继续挑战' in e['message'] for e in d.report['events'])


def test_stop_while_checking_target_records_reason_and_does_not_open_offer(tmp_path,monkeypatch):
    monkeypatch.setattr(flow.Backend,'connect',lambda _:None)
    monkeypatch.setattr(flow,'create_report',lambda:{'folder':tmp_path,'tasks':{},'events':[]})
    monkeypatch.setattr(flow.Daily,'home',lambda _:screen())
    monkeypatch.setattr(flow.Daily,'world_resources',lambda *_:{'stamina':2,'stamina_cap':166,'diamonds':4839})
    monkeypatch.setattr(flow.Daily,'main',lambda _:'体力不足5')
    def stop(*args):raise UserStopped('用户停止')
    monkeypatch.setattr(flow.Daily,'stamina_outlet_available',stop)
    monkeypatch.setattr(flow.Daily,'stamina_offer',lambda _:pytest.fail('Stopped before offer'))
    report=flow.run_daily({},['main'],threading.Event(),log=lambda _:None)
    assert report['status']=='stopped' and report['tasks']['main']['status']=='done'
    assert report['stamina_refill']['status']=='stopped'
    assert report['stamina_refill']['phase']=='checking_target'
    assert report['stamina_refill']['claimed']==0
    assert '停止时' in report['stamina_refill']['message']


def test_empty_three_shots_can_fall_back_only_to_enabled_potions(tmp_path):
    d=daily(tmp_path,{'task_options':{'main':{'auto_potions':True}}});d.selected=['main']
    balance=[2];calls=[]
    d.home=lambda:screen();d.world_resources=lambda _:{'stamina':balance[0],'stamina_cap':166}
    d.stamina_outlet_available=lambda *a:True
    d.stamina_offer=lambda:calls.append('empty-offer')
    def potion():calls.append('potion');balance[0]+=100;return 100
    d.use_stamina_potion=potion
    d.execute_task=lambda task:balance.__setitem__(0,balance[0]-5)
    d.replenish_stamina()
    assert calls==['empty-offer','potion']
    assert d.report['stamina_refill']=={'status':'done','claimed':0,'potions':1}


def test_unverified_stamina_gain_is_not_counted_as_a_successful_claim(tmp_path):
    d=daily(tmp_path);d.selected=['main'];calls=[]
    d.home=lambda:screen();d.world_resources=lambda _:{'stamina':2,'stamina_cap':166}
    d.stamina_outlet_available=lambda *a:True
    d.stamina_offer=lambda:captured('v094-stamina-one',True)
    d.b.click_text=lambda *a,**kw:calls.append('claim')
    d.observe=lambda:screen()
    d.replenish_stamina()
    assert calls==['claim'] and d.report.get('stamina_claims',0)==0
    assert d.report['stamina_refill_failures']==[{'source':'free','task':None,'reason':'100体力到账未核实'}]
