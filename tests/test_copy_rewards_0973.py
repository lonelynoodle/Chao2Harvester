"""Copy chests are free claims, independent of battle selection and budgets."""
import cv2
import pytest

from test_configuration import daily,screen,captured
from chao2.copy_rewards import copy_reward_rows,copy_chest_template
from chao2.policy import TaskBlocked


def page(*names,points=1000,stamina=0):
    s=screen(('异象',970,20,75,35),
             (f'本周已获取友好点数{points}',892,80,240,25),
             (f'{stamina}/184',510,10,90,30),
             *((text,x,y,w,h) for i,name in enumerate(names) for text,x,y,w,h in [
                 (name,920,215+142*i,200,28),
                 ('被探索者翰墨击破',920,269+142*i,235,24)]))
    template=copy_chest_template();h,w=template.shape[:2]
    for i in range(len(names)):s.image[234+142*i:234+142*i+h,831:831+w]=template
    return s


def test_claimable_chests_have_no_20_stamina_marker():
    s=page('first','second')
    assert len(copy_reward_rows(s))==2
    assert [r['name'] for r in copy_reward_rows(s)]==['first','second']
    assert not s.find('^20$')


@pytest.mark.parametrize('change',['no_list','no_icon','no_status','receipt','clipped','loading'])
def test_no_chest_click_from_unverified_or_covered_row(change):
    s=page('first')
    if change=='no_list':s.words=[w for w in s.words if w.text!='异象']
    if change=='no_icon':s.image[:]=0
    if change=='no_status':s.words=[w for w in s.words if not w.text.startswith('被探索者')]
    if change=='receipt':s.words+=screen(('获得奖励',550,105,170,55)).words
    if change=='clipped':
        next(w for w in s.words if w.text.startswith('被探索者')).box[1]=190
    if change=='loading':
        for point in [(640,307),(594,334),(594,386)]:cv2.circle(s.image,point,9,(240,240,240),-1)
    assert copy_reward_rows(s)==[]


def test_claims_two_collapsing_rows_with_receipts_and_no_fights(tmp_path):
    d=daily(tmp_path);before=page('first','second');after=page('second');empty=page()
    frames=iter([before,after]);d.observe=lambda:next(frames)
    receipts=iter([after,empty]);reward=screen(('获得奖励',550,105,170,55),('50',450,365,30,22))
    d.wait_for_screen=lambda predicate,*a,**kw:reward if predicate(reward) else pytest.fail('Missing receipt')
    d.dismiss_collection_reward=lambda s:(next(receipts),1)
    clicks=[];d.b.click_at=lambda s,p,anchors,reason:clicks.append((p,reason))
    d.check_budget=lambda *_:pytest.fail('Free claims do not use fight budgets')
    d.read_copy_quota=lambda *_:pytest.fail('Friend-point cap does not apply')
    assert d.claim_visible_copy_rewards(before) is empty
    assert len(clicks)==2 and all(p==(863,258) for p,_ in clicks)
    assert [r['status'] for r in d.report['copy_rewards']]==['claimed','claimed']
    assert d.battles==0 and not d.report.get('resource_usage')


def test_expired_reward_row_is_not_clicked_at_old_coordinates(tmp_path):
    d=daily(tmp_path);before=page('first');empty=page();d.observe=lambda:empty
    d.b.click_at=lambda *a:pytest.fail('Expired chest must not be clicked')
    assert d.claim_visible_copy_rewards(before) is empty
    assert not d.report.get('copy_rewards')


def test_missing_receipt_stops_without_resubmitting(tmp_path):
    d=daily(tmp_path);s=page('first');d.observe=lambda:s;clicks=[]
    d.b.click_at=lambda *a:clicks.append(a[1])
    def no_receipt(*a,**kw):raise TaskBlocked('No receipt')
    d.wait_for_screen=no_receipt
    with pytest.raises(TaskBlocked,match='领取结果未确认'):d.claim_visible_copy_rewards(s)
    with pytest.raises(TaskBlocked,match='领取结果未确认'):d.claim_visible_copy_rewards(s)
    assert len(clicks)==1 and d.report['copy_rewards'][0]['status']=='unconfirmed'


@pytest.mark.parametrize('retry_state',['same','changed','receipt','loading'])
def test_retry_rechecks_same_free_chest_and_never_replays_on_changed_page(tmp_path,retry_state):
    d=daily(tmp_path);s=page('first');empty=page();reward=screen(('获得奖励',550,105,170,55))
    retry=s if retry_state=='same' else page('another') if retry_state=='changed' else reward
    if retry_state=='loading':
        retry=page('first')
        for point in [(640,307),(594,334),(594,386)]:cv2.circle(retry.image,point,9,(240,240,240),-1)
    d.observe=lambda:s;clicks=[];d.b.click_at=lambda *a:clicks.append(a[1])
    def wait(predicate,*a,**kwargs):
        kwargs['retry_navigation'](retry);assert predicate(reward);return reward
    d.wait_for_screen=wait;d.dismiss_collection_reward=lambda s:(empty,1)
    assert d.claim_visible_copy_rewards(s) is empty
    assert len(clicks)==(2 if retry_state=='same' else 1)
    assert d.report['copy_rewards'][0]['clicks']==len(clicks)


def test_free_rewards_only_check_visible_chests_without_any_scrolling(tmp_path):
    d=daily(tmp_path);d.b.tasker=object();d.options['copies'].update(include_friends=False,max_runs=1)
    d.task_counts['copies']=1;s=page('top');claimed=[]
    d.copy_list=lambda:s
    def collect(s):
        if not claimed:
            claimed.append('top');d.report.setdefault('copy_rewards',[]).append({'status':'claimed'})
        return s
    d.claim_visible_copy_rewards=collect
    d.copy_scroll=lambda *a,**kw:pytest.fail('Free reward checks must not scroll')
    d.copy_first_page=lambda *a:pytest.fail('Free reward checks must not rewind')
    d.check_budget=lambda *_:pytest.fail('Fight cap must not prevent free claims')
    d.read_copy_quota=lambda *_:pytest.fail('No quota lookup is required')
    assert d.collect_copy_rewards()==1
    assert d.collect_copy_rewards()==0
    assert len(d.report['copy_reward_checks'])==2


def test_chests_are_checked_before_insufficient_stamina_exit(tmp_path):
    d=daily(tmp_path);seen=[];s=page(stamina=0)
    d.collect_copy_rewards=lambda:seen.append('free claims')
    d.observe=lambda:seen.append('stamina check') or s;d.home=lambda:None
    d.copy_targets=lambda *a:pytest.fail('No paid battle should be attempted')
    assert '不足20' in d.copy_battles()
    assert seen[:2]==['free claims','stamina check']


def test_target_scan_checks_visible_chests_before_friend_cap_filter(tmp_path):
    d=daily(tmp_path);s=page(points=1000);seen=[]
    d.copy_list=lambda:s;d.copy_first_page=lambda q:q
    d.claim_visible_copy_rewards=lambda q:seen.append(q) or q
    assert d.copy_targets('friend',set()) is None
    assert seen==[s]


def test_actual_game_rows_and_receipt_exclude_live_targets():
    before=captured('v0973-copy-chests',True)
    assert len(copy_reward_rows(before))==2
    assert not copy_reward_rows(captured('v0973-copy-receipt',True))
