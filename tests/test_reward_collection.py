"""Free-only reward navigation, receipts, duplicate prevention and UI migration."""
from copy import deepcopy

import pytest

from test_configuration import daily,screen,captured
from test_other_tasks import fake
from chao2.configuration import normalize_settings,SPECS,selected_rows
from chao2.policy import TaskBlocked,SafetyStop
from chao2.reward_collection import (ECHO_NAMES,CONTRACT_CLAIM_ROI,CLAIM,
    echo_header,echo_story_kind,is_echo_hub,contract_page,story_chest_state,
    echo_list_signature)


def test_existing_preferences_preserved_and_new_claims_enabled():
    old={'tasks':['other'],'task_options':{'other':{'friend_management':False},'rewards':{'collect_idle':False}}}
    new=normalize_settings(old)
    assert new['tasks']==['other'] and not new['task_options']['other']['friend_management']
    assert new['task_options']['other']['collect_contract']
    assert not new['task_options']['rewards']['collect_idle']
    assert [r['id'] for r in selected_rows(new['task_options']['rewards'],'world_echoes')]==list(ECHO_NAMES)
    fields=[f['key'] for f in SPECS['other']['fields']]
    assert fields.index('collect_contract')<fields.index('clear_bag_notifications')
    assert 'daily_puzzle' not in fields
    assert 'collect_contract' not in old['task_options']['other']


@pytest.mark.parametrize('kind,name',[('monument','monument'),('lost','echoes-lost'),('torrent','torrent'),('notes','notes')])
def test_captured_echo_lists_and_hub_are_distinct(kind,name):
    s=captured('reward-'+name,pixels=True)
    assert echo_header(s)==kind and echo_story_kind(s) is None
    assert echo_list_signature(s,kind)
    assert is_echo_hub(captured('reward-echoes',pixels=True))


@pytest.mark.parametrize('name,kind',[('lost-story-001','lost'),('notes-story-001','notes'),('torrent-chapter1','torrent')])
def test_story_identification_and_no_false_gold_from_illustrations(name,kind):
    s=captured('reward-'+name,pixels=True)
    assert echo_story_kind(s)==kind
    assert story_chest_state(s,kind) in (None,'claimed')
    assert story_chest_state(s,'monument') is None


@pytest.mark.parametrize('name,page',[('contract-rewards','rewards'),('contract-tasks','tasks'),('contract-weekly','tasks'),('contract-challenges','tasks')])
def test_contract_controls_do_not_treat_paid_buttons_or_go_complete_as_claim(name,page):
    s=captured('reward-'+name,pixels=True)
    assert contract_page(s)==page
    assert s.find(CLAIM,CONTRACT_CLAIM_ROI) is None


def test_contract_runs_before_bag_independently_of_friend_switch(tmp_path):
    d=daily(tmp_path,{'task_options':{'other':{'friend_management':False,'daily_puzzle':False,'collect_daily_single':False,'collect_plane_lord':False,'buy_star_spores':False}}});calls=[]
    d.home=lambda:None
    d.collect_contract=lambda:calls.append('contract') or {'status':'done','message':'contract'}
    d.clear_bag_notifications=lambda:calls.append('bag') or {'status':'done','message':'bag'}
    assert d.other()=='contract；bag' and calls==['contract','bag']


def test_contract_partial_claims_survive_failure_and_bag_still_runs(tmp_path):
    d=daily(tmp_path,{'task_options':{'other':{'friend_management':False,'daily_puzzle':False,'collect_daily_single':False,'collect_plane_lord':False,'buy_star_spores':False}}});d.home=lambda:None
    def partial():
        d.report.setdefault('other_tasks',{})['contract']={'task_batches':1,'reward_batches':0}
        raise TaskBlocked('reward page missing')
    d.collect_contract=partial
    d.clear_bag_notifications=lambda:{'status':'done','message':'bag'}
    with pytest.raises(TaskBlocked):d.other()
    assert d.report['other_tasks']['contract']['task_batches']==1
    assert d.report['other_tasks']['bag']['status']=='done'


def test_contract_claims_all_task_categories_before_rewards_and_no_purchase(tmp_path):
    d=daily(tmp_path);tasks=captured('reward-contract-tasks',pixels=True)
    rewards=captured('reward-contract-rewards',pixels=True)
    state,inputs=fake(d,rewards);d.contract_menu=lambda:state[0]
    claimed=[]
    def select(s,pattern,**kw):
        inputs.append(pattern)
        state[0]=deepcopy(rewards if pattern=='^奖励$' else tasks)
        if pattern not in ('^任务$','^每周任务$','^挑战任务$'):
            state[0].words+=screen(('领取',65,370,65,30)).words
    def claim(s,roi,validate):
        assert roi==CONTRACT_CLAIM_ROI and validate(s)
        claimed.append(contract_page(s));state[0].words=[w for w in state[0].words if w.text!='领取']
        return state[0]
    d.b.click_text=select;d.claim_collection_text=claim
    result=d.collect_contract()
    assert claimed==['tasks','rewards']
    assert inputs==['^任务$','^每日任务$','^每周任务$','^挑战任务$','^奖励$']
    assert result['task_batches']==result['reward_batches']==1


def test_unchanged_claim_button_is_never_clicked_twice_or_counted(tmp_path):
    d=daily(tmp_path);s=captured('reward-contract-tasks',pixels=True)
    s.words+=screen(('领取',65,370,65,30)).words
    state,inputs=fake(d,s)
    with pytest.raises(TaskBlocked,match='未重复点击'):d.claim_collection_text(s,CONTRACT_CLAIM_ROI,lambda q:contract_page(q)=='tasks')
    assert len(inputs)==1


def test_claim_receipt_with_next_reward_at_same_position_counts_once(tmp_path):
    d=daily(tmp_path);s=captured('reward-monument',pixels=True)
    s.words+=screen(('领取',1090,230,70,32)).words
    overlay=screen(('获得奖励',550,120,180,45))
    state,inputs=fake(d,s)
    d.b.click_text=lambda *a,**kw:state.__setitem__(0,overlay)
    def close(*a):inputs.append('close');state[0]=s
    d.b.click_at=close
    assert d.claim_collection_text(s,(1010,180,270,505),lambda q:echo_header(q)=='monument') is s
    assert inputs==['close']


def test_story_free_chest_requires_verified_page_and_collection_confirmation(tmp_path):
    d=daily(tmp_path);claimed=captured('reward-notes-story-001',pixels=True)
    ready=deepcopy(claimed);ready.words=[w for w in ready.words if w.text!='已领取']
    ready.words+=screen(('领取',215,615,50,25)).words
    state,inputs=fake(d,ready)
    def click(s,p,anchors,reason):inputs.append(p);state[0]=claimed
    d.b.click_at=click
    after,n=d.collect_story_chest(ready,'notes')
    assert after is claimed and n==1 and inputs==[(237,572)]
    assert d.collect_story_chest(claimed,'notes')==(claimed,0) and len(inputs)==1


def test_dark_unreadable_chest_is_not_assumed_unclaimed(tmp_path):
    d=daily(tmp_path);s=captured('reward-lost-story-001',pixels=True);state,inputs=fake(d,s)
    d.b.read_text_region=lambda *a,**kw:''
    with pytest.raises(TaskBlocked,match='未盲点'):d.collect_story_chest(s,'lost')
    assert not inputs


@pytest.mark.parametrize('name,point',[('lost-story-001',(1210,650)),('notes-story-001',(1210,650)),('torrent-chapter1',(1230,38))])
def test_home_closes_story_overlay_before_back_navigation(tmp_path,name,point):
    d=daily(tmp_path);s=captured('reward-'+name,pixels=True);state,inputs=fake(d,s)
    kind=echo_story_kind(s)
    listing=captured('reward-'+{'lost':'echoes-lost','notes':'notes','torrent':'torrent'}[kind],pixels=True)
    def close(q,p,a,r):inputs.append(p);state[0]=listing
    d.b.click_at=close
    assert d.close_echo_story(s) is listing and inputs==[point]


@pytest.mark.parametrize('kind',list(ECHO_NAMES))
def test_no_notification_checks_first_page_without_scrolling_entire_catalog(tmp_path,kind):
    d=daily(tmp_path);hub=captured('reward-echoes',pixels=True)
    page=captured('reward-'+{'monument':'monument','lost':'echoes-lost','torrent':'torrent','notes':'notes'}[kind],pixels=True)
    state,inputs=fake(d,hub);d.echo_hub=lambda *a:hub
    d.b.click_text=lambda *a,**kw:state.__setitem__(0,page)
    d.echo_scroll=lambda *a,**kw:pytest.fail('No notification: do not scan old catalogue')
    result=d.collect_echo_category(kind)
    assert result['claimed']==0 and result['status']=='done' and result['pages']==0


def test_disabled_echoes_never_navigate_and_partial_failure_continues(tmp_path):
    d=daily(tmp_path);d.home=lambda:None;d.echo_hub=lambda *a:None;calls=[]
    d.options['rewards']['world_echoes'][1]['enabled']=False
    def category(key):
        calls.append(key)
        if key=='monument':raise TaskBlocked('claim unclear')
        return {'status':'done','claimed':0,'message':key}
    d.collect_echo_category=category
    with pytest.raises(TaskBlocked,match='世界丰碑'):d.collect_world_echoes()
    assert calls==['monument','torrent','notes']
    assert d.report['world_echoes']['notes']['status']=='done'
    for row in d.options['rewards']['world_echoes']:row['enabled']=False
    assert d.collect_world_echoes()=='' and calls==['monument','torrent','notes']


def test_paid_dialog_blocks_before_claim_input(tmp_path):
    d=daily(tmp_path);s=captured('reward-contract-rewards',pixels=True)
    s.words+=screen(('是否购买超阶契约',500,300,230,40),('领取',65,370,65,30)).words
    inputs=[];d.b.controller=type('NoInputs',(),{'post_click':lambda *a:inputs.append(a)})()
    with pytest.raises(SafetyStop,match='补购'):d.claim_collection_text(s,CONTRACT_CLAIM_ROI,lambda q:True)
    assert not inputs


def mark(s,point):
    source=captured('other-initial-world',pixels=True)
    x,y=point
    s.image[y:y+21,x:x+26]=source.image[85:106,1250:1276]
    return s


def test_marked_story_is_opened_and_claimed_without_clicking_comments(tmp_path):
    d=daily(tmp_path);hub=mark(captured('reward-echoes',pixels=True),(1180,330))
    clean_hub=captured('reward-echoes',pixels=True)
    listing=captured('reward-notes',pixels=True);marked=mark(deepcopy(listing),(191,260))
    ready=captured('reward-notes-story-001',pixels=True)
    ready.words=[w for w in ready.words if w.text!='已领取']
    ready.words+=screen(('领取',215,615,50,25)).words
    claimed=captured('reward-notes-story-001',pixels=True)
    state,inputs=fake(d,hub);hubs=iter([hub,clean_hub]);d.echo_hub=lambda *a:next(hubs)
    d.b.click_text=lambda *a,**kw:state.__setitem__(0,marked)
    def click(s,p,anchors,reason):
        inputs.append((p,reason))
        if p==(1210,650):state[0]=listing
        elif p==(237,572):state[0]=claimed
        else:state[0]=ready
    d.b.click_at=click;d.echo_scroll=lambda *a,**kw:listing
    result=d.collect_echo_category('notes')
    assert result['claimed']==1 and result['status']=='done'
    assert len(inputs)==3 and '提示' in inputs[0][1]
    assert all(not 350<p[1]<430 for p,_ in inputs)


def test_persistent_unhandled_badge_is_reported_as_blocked_not_completed(tmp_path):
    d=daily(tmp_path);hub=mark(captured('reward-echoes',pixels=True),(1180,330))
    listing=captured('reward-notes',pixels=True);state,inputs=fake(d,listing)
    d.echo_hub=lambda *a:hub;d.b.click_text=lambda *a,**kw:None
    d.echo_scroll=lambda *a,**kw:listing
    with pytest.raises(TaskBlocked,match='入口仍有提示'):d.collect_echo_category('notes')
    assert d.report['world_echoes']['notes']['status']!='done'


def test_story_claim_count_remains_when_later_navigation_fails(tmp_path):
    d=daily(tmp_path);claimed=captured('reward-notes-story-001',pixels=True)
    ready=deepcopy(claimed);ready.words=[w for w in ready.words if w.text!='已领取']
    ready.words+=screen(('领取',215,615,50,25)).words
    state,inputs=fake(d,ready);d.b.click_at=lambda *a:state.__setitem__(0,claimed)
    d.collect_story_chest(ready,'notes')
    assert d.report['world_echoes']['notes']['claimed']==1
