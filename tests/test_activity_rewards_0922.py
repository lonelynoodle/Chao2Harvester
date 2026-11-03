from copy import deepcopy
from types import SimpleNamespace

import pytest

from test_configuration import captured,daily,screen
from chao2.backend import Word
from chao2.policy import TaskBlocked
from chao2.activity_rewards import (activity_page,is_activity,daily_claim_state,is_plane,
                                    plane_regions,plane_reward_state)
from chao2.activities import stamina_servings
from chao2.other_tasks import friend_name_rows,friend_rows,same_friend_positions
from test_other_tasks import fake,friends


def test_real_pages_require_content_title_not_duplicate_sidebar_label():
    world=captured('v0922-stamina-world',True)
    daily_page=captured('v0922-daily-single-empty',True)
    stamina=captured('v0922-stamina-offer',True)
    assert not is_activity(world)
    assert not activity_page(daily_page,'每日三发')
    assert daily_claim_state(daily_page)=='empty'
    assert activity_page(stamina,'每日三发') and stamina_servings(stamina)==2
    assert daily_claim_state(stamina) is None


def test_activity_navigation_waits_for_entrance_and_retries_only_sidebar(tmp_path):
    d=daily(tmp_path);world=captured('v0922-stamina-world',True)
    menu=captured('v0922-daily-single-empty',True);offer=captured('v0922-stamina-offer',True)
    d.observe=lambda:world;inputs=[]
    d.open_world_page=lambda *a:inputs.append('open') or menu
    d.b.click_text=lambda s,p,**kw:inputs.append((p,kw['roi']))
    def wait(predicate,label,**kw):
        assert not predicate(menu) and predicate(offer)
        kw['retry_navigation'](world)  # Must not replay tab coordinates on map.
        kw['retry_navigation'](menu)
        return offer
    d.wait_for_screen=wait
    assert d.activity_tab('每日三发') is offer
    assert inputs==['open',('^每日三发$',(0,75,170,605)),('^每日三发$',(0,75,170,605))]


def test_stamina_unknown_page_cannot_be_reported_as_no_free_servings(tmp_path):
    d=daily(tmp_path);d.activity_tab=lambda _:None
    def wait(predicate,label,**kw):
        assert not predicate(captured('v0922-stamina-world',True))
        raise TaskBlocked('page never opened')
    d.wait_for_screen=wait
    with pytest.raises(TaskBlocked,match='never opened'):d.stamina_offer()
    assert 'stamina_servings_available' not in d.report


def test_daily_single_empty_never_clicks_and_default_settings_are_independent(tmp_path):
    d=daily(tmp_path);empty=captured('v0922-daily-single-empty',True)
    d.activity_tab=lambda _:empty;d.wait_for_screen=lambda *a,**kw:empty
    d.b.click_text=lambda *a,**kw:pytest.fail('Disabled reward must not be clicked')
    assert d.collect_daily_single()['claimed']==0
    assert d.options['other']['collect_daily_single'] and d.options['other']['collect_plane_lord']


def ready_daily():
    s=captured('v0922-daily-single-empty',True)
    w=s.find('^领取奖励$');x,y,width,h=w.box
    s.image[y:y+h,x:x+width]=220
    return s


def test_daily_single_requires_receipt_and_disabled_button_after_one_click(tmp_path):
    d=daily(tmp_path);ready=ready_daily();empty=captured('v0922-daily-single-empty',True)
    d.activity_tab=lambda _:ready;d.wait_for_screen=lambda *a,**kw:ready
    d.observe=lambda:empty;d.dismiss_collection_reward=lambda s:(s,1);inputs=[]
    d.b.click_text=lambda s,p,**kw:inputs.append((p,kw['roi']))
    assert d.collect_daily_single()['claimed']==1
    assert inputs==[('^领取奖励$',(950,565,250,90))]


def test_unconfirmed_daily_single_does_not_loop_claim(tmp_path):
    d=daily(tmp_path);ready=ready_daily();calls=[]
    d.activity_tab=lambda _:ready;d.wait_for_screen=lambda *a,**kw:ready
    d.observe=lambda:ready;d.dismiss_collection_reward=lambda s:(s,0);d.b.sleep=lambda _:None
    d.b.click_text=lambda *a,**kw:calls.append('claim')
    with pytest.raises(TaskBlocked,match='未重复领取'):d.collect_daily_single()
    assert calls==['claim'] and d.report['other_tasks']['daily_single']['status']=='confirming'


def test_plane_free_upper_track_and_region_selection(tmp_path):
    first=captured('v0922-plane-first',True);third=captured('v0922-plane-third',True)
    assert is_plane(first)
    assert [r['name'] for r in plane_regions(first) if r['selected']]==['源初之地']
    d=daily(tmp_path);progress,marks=d.plane_marks(third)
    assert progress==36 and [m[0] for m in marks]==[35,40,45,50,55]
    assert plane_reward_state(third,marks[0][1])=='claimed'
    assert plane_reward_state(third,marks[1][1])=='diamond'
    assert plane_reward_state(captured('v0922-stamina-world',True),625) is None
    # Locked 40% card remains unclicked when progress is 36%.
    d.plane_scroll=lambda s,**kw:s
    d.b.click_at=lambda *a:pytest.fail('No locked or paid reward input')
    with pytest.raises(TaskBlocked,match='起点'):d.plane_claim_region(third,'歼误之地',{'receipts':[],'claimed':0})


def test_plane_mark_near_left_border_has_consistent_reward_hit_area(tmp_path):
    d=daily(tmp_path);s=captured('v0922-plane-left-edge',True)
    progress,marks=d.plane_marks(s)
    assert progress==38 and marks[0][0]==15
    assert all(plane_reward_state(s,x)=='claimed' for value,x in marks if value<=progress)


def test_plane_does_not_treat_failed_region_switch_as_old_region_success(tmp_path):
    d=daily(tmp_path);s=captured('v0922-plane-first',True);calls=[]
    d.observe=lambda:s;d.b.sleep=lambda _:None
    d.b.click_text=lambda *a,**kw:calls.append(kw['roi'])
    assert d.plane_select_region(s,plane_regions(s)[4]) is None
    assert calls==[(310,600,915,65)]*2


def test_plane_failed_swipe_rechecks_page_and_stops_before_unknown_input(tmp_path):
    d=daily(tmp_path);s=captured('v0922-plane-third',True);calls=[]
    d.b.controller=SimpleNamespace(post_swipe=lambda *a:calls.append(a) or SimpleNamespace(succeeded=False))
    d.b.wait=lambda job:job;d.observe=lambda:screen()
    with pytest.raises(TaskBlocked,match='页面改变'):d.plane_scroll(s)
    assert len(calls)==1


def test_plane_unconfirmed_reward_is_never_repeated_on_task_recovery(tmp_path):
    d=daily(tmp_path)
    d.report['other_tasks']={'plane_lord':{'receipts':[{'status':'confirming'}]}}
    d.activity_tab=lambda *a:pytest.fail('Cannot repeat an unconfirmed claim')
    with pytest.raises(TaskBlocked,match='不重复领取'):d.collect_plane_lord()


def available_plane():
    s=captured('v0922-plane-third',True)
    # Move the captured 35%-55% page to an equivalent initial 5%-25% page;
    # only 5% is eligible. Keep the real upper-track diamond pixels.
    for w in s.words:
        if w.text=='36%':w.text='5%'
        elif 365<=w.center[0]<=1230 and 395<=w.center[1]<445 and w.text.endswith('%'):
            w.text=str(int(w.text[:-1])-30)+'%'
    s.words=[w for w in s.words if not (w.text.startswith('已领') and 400<w.center[0]<500 and 285<w.center[1]<343)]
    s.image[290:334,434:489]=[240,210,30]
    return s


@pytest.mark.parametrize('confirmed',[True,False])
def test_plane_claims_only_reached_free_milestone_once_and_checks_receipt(tmp_path,confirmed):
    d=daily(tmp_path);ready=available_plane();after=deepcopy(ready)
    d.b.sleep=lambda _:None;inputs=[]
    if confirmed:after.words.append(Word('已领取',[437,304,52,20],.99))
    d.observe=lambda:after if inputs else ready
    d.b.click_at=lambda s,p,*args:inputs.append(p)
    d.dismiss_collection_reward=lambda s:(s,1 if confirmed else 0)
    result={'receipts':[],'claimed':0}
    if confirmed:
        d.plane_claim_region(ready,'歼误之地',result)
        assert result['claimed']==1 and result['receipts'][0]['status']=='confirmed'
    else:
        with pytest.raises(TaskBlocked,match='未重复领取'):d.plane_claim_region(ready,'歼误之地',result)
        assert result['claimed']==0 and result['receipts'][0]['status']=='confirming'
    assert len(inputs)==1 and inputs[0][1]==312


def test_name_rows_recover_low_confidence_time_and_keep_scroll_overlap():
    top=captured('v0922-friends-top',True)
    assert len(friend_rows(top))==3 and len(friend_name_rows(top))==4
    a=captured('v0922-friends-page2',True);b=captured('v0922-friends-page3',True)
    overlap={r['name'] for r in friend_name_rows(a)}&{r['name'] for r in friend_name_rows(b)}
    assert overlap=={'大锅盔`','奥比'} and not same_friend_positions(a,b)


def test_disagreeing_or_unreadable_friend_time_cannot_delete(tmp_path):
    d=daily(tmp_path);s=friends(3);state,inputs=fake(d,s)
    d.b.read_text_crop=lambda *a:'8天前'
    assert d.verified_friend_rows(s)==[]
    assert d.report['friend_time_unreadable']==['星空']
    with pytest.raises(TaskBlocked,match='未登录时间'):d.remove_friend(friend_rows(friends(8))[0],(56,60))
    assert not inputs


def test_deletion_rechecks_same_day_reading_not_just_above_threshold(tmp_path):
    d=daily(tmp_path);s=friends(8);state,inputs=fake(d,s)
    with pytest.raises(TaskBlocked,match='未登录时间'):d.remove_friend(friend_rows(friends(6))[0],(56,60))
    assert not inputs


def test_friend_list_waits_until_names_stop_moving(tmp_path):
    d=daily(tmp_path);s=friends();moving=deepcopy(s)
    for w in moving.words:
        if w.text in ('星空','6天前'):w.box[1]-=12
    frames=iter([moving,s,s]);d.observe=lambda:next(frames);d.b.sleep=lambda _:None
    assert d.settle_friend_list(moving) is moving
    assert d.settle_friend_list(moving) is s
