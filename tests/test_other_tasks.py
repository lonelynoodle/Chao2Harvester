"""Friend/inventory regression checks with captured pages and simulated input."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from test_configuration import daily,screen,captured
from chao2.backend import Word
from chao2.configuration import normalize_settings,plan_tasks
from chao2.workflows import ORDER,is_world
from chao2.other_tasks import (friend_count,friend_rows,inactive_days,recommendation_rows,
    has_add_cross,notification_badges,is_bag,green_button_enabled)
from chao2.policy import TaskBlocked


def friends(days=6,count=56,name='星空'):
    return screen(('好友',135,10,55,33),('好友数量',153,95,84,22),
                  (f'{count}/60',289,92,61,25),('一键赠送',320,641,95,24),
                  (name,221,457,70,22),(f'{days}天前',406,492,51,24))


def fake(d,first):
    state=[first];inputs=[]
    d.observe=lambda *a:state[0];d.await_page=lambda *a,**kw:state[0]
    d.b.sleep=lambda _:None;d.b.save_screen=lambda *a:None;d.checkpoint=lambda:None
    d.b.read_text_crop=lambda q,roi:q.region_text(roi)
    d.b.click_at=lambda s,p,a,r:inputs.append(('point',p,r))
    d.b.click_text=lambda s,p,**kw:inputs.append(('text',p))
    return state,inputs


def test_new_subtasks_defaults_and_inactive_days_validation():
    settings=normalize_settings({'tasks':['copies']})
    assert settings['tasks']==['copies']
    options=settings['task_options']['other']
    assert options['inactive_days']==5 and options['remove_inactive_friends'] is False
    assert options['friend_management'] and options['clear_bag_notifications']
    for bad in (0,-1,366,2.5,True,'5'):
        with pytest.raises(ValueError):normalize_settings({'task_options':{'other':{'inactive_days':bad}}})


@pytest.mark.parametrize('text,eligible',[
    ('5天前',False),('6天前',True),('120小时前',False),('121小时前',True),
    ('在线',False),('刚刚',False),('20分钟前',False),('3大前',False),('时间未知',False),
])
def test_only_strictly_older_known_times_are_eligible(text,eligible):
    days=inactive_days(text)
    assert (days is not None and days>5) is eligible


def test_actual_pages_distinguish_friend_count_pending_requests_and_item_art():
    friends_page=captured('other-friends-bottom',pixels=True)
    assert friend_count(friends_page)==(56,60)
    assert not any(r['days']>5 for r in friend_rows(friends_page))
    assert not green_button_enabled(friends_page,(300,632,145,40))
    social=captured('other-social-menu',pixels=True)
    targets=[r for r in recommendation_rows(social) if not r['pending'] and has_add_cross(social,r['point'])]
    assert [r['name'] for r in targets]==['天外飞仙2']
    for name in ('other-bag-menu','other-bag-cores'):
        bag=captured(name,pixels=True)
        assert is_bag(bag) and not is_world(bag)
        assert notification_badges(bag,(140,90,580,565))==[]
    world=captured('other-initial-world',pixels=True)
    assert len(notification_badges(world,(1200,60,80,580)))==3
    assert notification_badges(world,(10,230,90,70))==[]


@pytest.mark.parametrize('days,count',[(5,56),(6,55)])
def test_removal_rechecks_age_and_count_before_any_input(tmp_path,days,count):
    d=daily(tmp_path);state,inputs=fake(d,friends(days,count=count))
    with pytest.raises(TaskBlocked):d.remove_friend(friend_rows(friends())[0],(56,60))
    assert inputs==[]


def test_wrong_profile_name_never_deletes(tmp_path):
    d=daily(tmp_path);state,inputs=fake(d,friends())
    profile=captured('other-friend-profile')
    for w in profile.words:
        if w.text=='星空':w.text='另一位好友'
    def avatar(s,p,a,r):inputs.append(('avatar',p));state[0]=profile
    d.b.click_at=avatar
    with pytest.raises(TaskBlocked,match='身份不符'):d.remove_friend(friend_rows(friends())[0],(56,60))
    assert len(inputs)==1 and inputs[0][0]=='avatar'


@pytest.mark.parametrize('confirmation',[False,True])
def test_removal_requires_named_profile_and_verified_count_change(tmp_path,confirmation):
    d=daily(tmp_path);state,inputs=fake(d,friends())
    profile=captured('other-friend-profile');prompt=deepcopy(profile)
    prompt.words+=screen(('确定删除好友星空吗',370,285,390,40),('确定',740,465,80,35),('取消',440,465,80,35)).words
    d.b.click_at=lambda *a:state.__setitem__(0,profile)
    def click(s,p,**kw):
        inputs.append(p)
        state[0]=prompt if p=='^删除好友$' and confirmation else friends(count=55)
    d.b.click_text=click
    result=d.remove_friend(friend_rows(friends())[0],(56,60))
    assert friend_count(result)==(55,60)
    assert inputs==['^删除好友$']+(['^确定$'] if confirmation else [])
    assert d.report['friends_removed'][0]['after']==55


def test_unchanged_friend_count_after_delete_is_not_reported_as_removed(tmp_path):
    d=daily(tmp_path);state,inputs=fake(d,friends());profile=captured('other-friend-profile')
    d.b.click_at=lambda *a:state.__setitem__(0,profile)
    d.b.click_text=lambda *a,**kw:state.__setitem__(0,friends())
    with pytest.raises(TaskBlocked,match='数量变化不符'):d.remove_friend(friend_rows(friends())[0],(56,60))
    assert not d.report.get('friends_removed')


def test_no_friend_removal_at_exact_threshold_and_stable_bottom_stops(tmp_path):
    d=daily(tmp_path);s=captured('other-friends-bottom',pixels=True)
    state,inputs=fake(d,s);d.friend_menu=lambda **kw:s
    d.remove_friend=lambda *a:pytest.fail('Exactly five days must be retained')
    d.b.controller=SimpleNamespace(post_swipe=lambda *a:inputs.append('swipe') or SimpleNamespace(succeeded=True))
    d.b.wait=lambda x:x
    result=d.clear_inactive_friends()
    assert result['removed']==0 and inputs==['swipe']


def test_no_exchange_click_when_daily_button_is_disabled(tmp_path):
    d=daily(tmp_path);s=captured('other-friends-bottom',pixels=True);state,inputs=fake(d,s)
    d.friend_menu=lambda:s
    assert d.exchange_friend_coins()['actions']==[] and not inputs


def test_cleanup_reopens_existing_scrolled_list_once_before_scanning(tmp_path):
    d=daily(tmp_path);bottom=captured('other-friends-bottom',pixels=True)
    world=captured('other-initial-world',pixels=True);top=friends(0)
    state,inputs=fake(d,bottom)
    def home(s=None):inputs.append('home');state[0]=world;return world
    def open_friends(s,p,r):inputs.append('open');state[0]=top
    d.home=home;d.click_world=open_friends
    assert d.friend_menu(reset=True) is top
    assert inputs.count('open')==1
    assert d.friend_menu() is top and inputs.count('open')==1


def test_existing_friend_page_with_unreadable_count_blocks(tmp_path):
    d=daily(tmp_path);s=friends()
    s.words=[w for w in s.words if w.text!='56/60']
    state,inputs=fake(d,s)
    with pytest.raises(TaskBlocked,match='数量或上限'):d.friend_menu()
    assert not inputs


def test_exchange_waits_for_disabled_result_and_never_clicks_chat(tmp_path):
    d=daily(tmp_path);s=friends();s.image[641:660,330:400]=(0,230,50)
    state,inputs=fake(d,s);d.friend_menu=lambda:state[0]
    def click(q,p,**kw):inputs.append((p,kw['roi']));state[0]=friends()
    d.b.click_text=click
    assert d.exchange_friend_coins()['actions']==['一键赠送']
    assert inputs==[(r'^[一－—-]?键(?:赠送|收取|领取)(?:并收取)?$',(165,620,390,65))]


def test_full_friends_never_open_recommendations(tmp_path):
    d=daily(tmp_path);d.friend_menu=lambda:friends(count=60)
    d.social_menu=lambda:pytest.fail('At capacity')
    assert d.add_friends_to_capacity()['requested']==[]


def test_send_only_new_request_and_report_waiting_not_full(tmp_path):
    d=daily(tmp_path);s=captured('other-social-menu',pixels=True);state,inputs=fake(d,s)
    d.friend_menu=lambda:friends();d.social_menu=lambda:state[0]
    def add(q,p,a,r):
        inputs.append((p,r));state[0]=deepcopy(s)
        state[0].words.append(Word('已申请',[600,510,73,28],.99))
    d.b.click_at=add
    result=d.add_friends_to_capacity()
    assert result['requested']==['天外飞仙2'] and result['status']=='waiting'
    assert result['count']==(56,60)
    assert [x for x in inputs if x[0]!='text']==[((635,523),'申请添加推荐好友')]


def test_ambiguous_request_result_is_reported_without_blocking_other_tasks(tmp_path):
    d=daily(tmp_path);s=captured('other-social-menu',pixels=True);state,inputs=fake(d,s)
    d.friend_menu=lambda:friends();d.social_menu=lambda:s
    result=d.add_friends_to_capacity()
    assert result['status']=='waiting' and not result['requested']
    assert '已跳过' in result['message']
    requests=[item for item in inputs if item[0]=='point']
    assert 1<=len(requests)<=2 and len({item[1] for item in requests})==1


def test_request_accepts_visible_applied_state_when_name_ocr_flickers(tmp_path):
    d=daily(tmp_path);before=captured('other-social-menu',pixels=True)
    row=next(r for r in recommendation_rows(before) if not r['pending'])
    after=deepcopy(before)
    after.words=[w for w in after.words if w.text!=row['name']]
    after.words.append(Word('已申请',[600,row['point'][1]-14,73,28],.99))
    frames=iter([before,after]);d.observe=lambda:next(frames)
    d.b.guard=lambda *_:None;d.b.sleep=lambda *_:None
    clicks=[];d.b.click_at=lambda *a:clicks.append(a)
    assert d.request_friend(row)=='sent' and len(clicks)==1


def test_request_count_cannot_exceed_remaining_friend_slots(tmp_path):
    d=daily(tmp_path);s=captured('other-social-menu',pixels=True);state,inputs=fake(d,s)
    d.friend_menu=lambda:friends(count=59);d.social_menu=lambda:state[0]
    def add(q,p,a,r):
        inputs.append(p);state[0]=deepcopy(s)
        state[0].words.append(Word('已申请',[600,510,73,28],.99))
    d.b.click_at=add
    d.b.click_text=lambda *a,**kw:pytest.fail('One remaining slot: do not refresh or keep applying')
    result=d.add_friends_to_capacity()
    assert len(result['requested'])==1 and result['count']==(59,60)
    assert result['status']=='waiting' and len(inputs)==1


def test_accept_existing_applications_verifies_count_then_stops_at_capacity(tmp_path):
    d=daily(tmp_path);s=captured('other-social-menu',pixels=True)
    s.words=[w for w in s.words if w.text!='无']
    s.words.append(Word('申请人',[790,180,90,25],.99))
    s.image[640:670,1100:1200]=(0,230,50)
    state,inputs=fake(d,s);counts=iter([59,60,60])
    d.friend_menu=lambda:friends(count=next(counts));d.social_menu=lambda:state[0]
    d.b.click_at=lambda *a:pytest.fail('At capacity after accepting: no outgoing request')
    result=d.add_friends_to_capacity()
    assert inputs==[('text','^全部同意$')]
    assert result['accepted']==1 and result['count']==(60,60) and result['status']=='done'


def test_absent_bag_indicator_needs_no_item_click(tmp_path):
    d=daily(tmp_path);s=captured('other-initial-world',pixels=True);state,inputs=fake(d,s)
    d.home=lambda:s
    assert d.clear_bag_notifications()['cleared']==0 and not inputs


def test_inventory_acknowledgement_clicks_only_left_item_grid(tmp_path):
    d=daily(tmp_path);clean=captured('other-bag-menu',pixels=True)
    marked=deepcopy(clean);world=captured('other-initial-world',pixels=True)
    # Use the client's actual badge pixels at an item corner to test the flow.
    marked.image[94:115,208:234]=world.image[85:106,1250:1276]
    assert len(notification_badges(marked,(140,90,580,565)))==1
    state,inputs=fake(d,marked);d.home=lambda:world
    d.b.click_text=lambda *a,**kw:None
    def select(s,p,a,r):inputs.append(p);state[0]=clean
    d.b.click_at=select
    d.b.controller=SimpleNamespace(post_swipe=lambda *a:SimpleNamespace(succeeded=True))
    d.b.wait=lambda x:x
    result=d.clear_bag_notifications()
    assert result['cleared']==1
    assert len(inputs)==1 and 140<=inputs[0][0]<715 and 90<=inputs[0][1]<675


def test_master_switch_skips_all_friend_actions_and_bag_stays_independent(tmp_path):
    d=daily(tmp_path,{'task_options':{'other':{'friend_management':False,'collect_contract':False,'daily_puzzle':False,'collect_daily_single':False,'collect_plane_lord':False,'buy_star_spores':False}}});calls=[]
    d.exchange_friend_coins=lambda:pytest.fail('Friend management disabled')
    d.add_friends_to_capacity=lambda:pytest.fail('Friend management disabled')
    d.home=lambda:None
    d.clear_bag_notifications=lambda:calls.append('bag') or {'status':'done','message':'bag done'}
    assert d.other()=='bag done' and calls==['bag']


def test_one_blocked_subtask_does_not_skip_bag_or_claim_all_done(tmp_path):
    d=daily(tmp_path,{'task_options':{'other':{'auto_add_friends':False,'collect_contract':False,'daily_puzzle':False,'collect_daily_single':False,'collect_plane_lord':False,'buy_star_spores':False}}});d.home=lambda:None
    def blocked():raise TaskBlocked('unreadable')
    d.exchange_friend_coins=blocked
    d.clear_bag_notifications=lambda:{'status':'done','message':'bag done'}
    with pytest.raises(TaskBlocked,match='部分未完成'):d.other()
    assert d.report['other_tasks']['friend_coins']['status']=='blocked'
    assert d.report['other_tasks']['bag']['status']=='done'


def test_other_runs_after_rewards_in_both_execution_modes(tmp_path):
    settings=normalize_settings({})
    assert plan_tasks(settings,['other','rewards','giant'],ORDER)==['celebration','rewards','other']
    d=daily(tmp_path,{'unordered_tasks':True})
    assert d.next_daily_task(['other','rewards','giant'])=='giant'
    assert d.next_daily_task(['other','rewards'])=='rewards'
    assert d.next_daily_task(['other'])=='other'
