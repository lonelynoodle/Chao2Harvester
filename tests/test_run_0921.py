"""October 19 failures reproduced from the original run, with guarded inputs."""
from copy import deepcopy

import pytest

from chao2.activities import (main_unlock_level,is_main_detail,is_tribe_detail,
    enemy_formation,next_tower_floor,main_identity)
from chao2.backend import Word
from chao2.forest import ForestNode,recover_forest_node
from chao2.other_tasks import friend_delete_confirmation,friend_rows,friend_count
from chao2.policy import TaskBlocked,SafetyStop
from chao2.reward_collection import task_claim_slot,daily_activity_chests,CLAIM
from chao2.transient_popups import is_star_gift
from chao2.workflows import is_world
from test_configuration import captured,daily,screen
from test_other_tasks import fake,friends


def test_actual_level_locked_main_is_not_a_stamina_price_error(tmp_path):
    d=daily(tmp_path);d.active_task='main';s=captured('v0921-main-locked',True)
    assert is_main_detail(s) and main_unlock_level(s)==73 and main_identity(s)=='622'
    d.observe=lambda:s
    assert d.await_detail() is s
    with pytest.raises(TaskBlocked,match='尚未解锁'):d.ensure_detail(s)
    assert d.record_locked_main(s) and d.report['main_locked']=={'622':{'required_level':73}}
    assert main_unlock_level(captured('main-entry')) is None
    s.words=[Word(w.text,[10,10,160,30],w.score) if '73开启' in w.text else w for w in s.words]
    assert main_unlock_level(s) is None


def test_main_skips_locked_stage_and_continues_another_node(tmp_path):
    d=daily(tmp_path);world=captured('v0913-main-world',True)
    locked=captured('v0921-main-locked',True);valid=captured('main-entry')
    d.options['main']['max_nodes']=2;d.home=lambda *a:world
    d.main_overview_detail=lambda:locked;d.find_main_candidate=lambda excluded:valid
    frames=iter([locked,valid]);d.observe=lambda:next(frames);d.b.sleep=lambda _:None
    d.back_detail=lambda _:world;attempts=[]
    d.play_encounter=lambda task,opener,*args:attempts.append(main_identity(opener())) or True
    d.main()
    assert attempts==[main_identity(valid)] and '622' not in attempts
    assert d.report['main_locked']['622']['required_level']==73


def test_actual_tower_ignores_clipped_bottom_number():
    s=captured('v0921-tower-clipped',True)
    assert s.find('^320$').box[1]==694
    assert next_tower_floor(s)[0]==302
    s.words=[w for w in s.words if w.text!='0302']
    assert next_tower_floor(s) is None


def test_missing_enemy_prefix_only_allowed_on_verified_tribe_detail(tmp_path):
    s=captured('v0921-tribe-detail',True);d=daily(tmp_path)
    assert enemy_formation(s).text=='方阵容' and is_tribe_detail(s) and not is_world(s)
    assert d.ensure_detail(s) is s
    inputs=[];d.b.click_at=lambda s,p,a,r:inputs.append((p,a));d.observe=lambda:s
    d.back_detail(s)
    assert inputs==[((45,28),['^方阵容$'])]
    s.words=[w for w in s.words if not w.text.startswith('通关奖励')]
    assert enemy_formation(s) is None and not is_tribe_detail(s)


def test_gift_popup_only_exits_through_back_and_confirms_closed(tmp_path):
    d=daily(tmp_path);gift=captured('v0921-star-gift',True);world=captured('v0913-main-world',True)
    assert is_star_gift(gift) and not is_world(gift)
    frames=iter([gift,world]);d.b.observe=lambda *a:next(frames);d.b.sleep=lambda _:None
    inputs=[];d.b.click_at=lambda s,p,a,r:inputs.append(p)
    assert d.dismiss_star_gift(gift) is world and inputs==[(43,28)]
    assert d.report['dismissed_offers'][0]['status']=='closed'
    gift.words=[w for w in gift.words if w.text!='限时星礼']
    assert not is_star_gift(gift)


def test_stuck_gift_has_only_three_verified_exit_clicks(tmp_path):
    d=daily(tmp_path);gift=captured('v0921-star-gift',True)
    d.b.observe=lambda *a:gift;d.b.sleep=lambda _:None;inputs=[]
    d.b.click_at=lambda s,p,a,r:inputs.append(p)
    with pytest.raises(TaskBlocked,match='已尝试3次'):d.dismiss_star_gift(gift)
    assert inputs==[(43,28)]*3


def test_offer_consumed_territory_navigation_reenters_after_close(tmp_path):
    d=daily(tmp_path);world=captured('v0913-main-world',True)
    territory=screen(('世界',1180,650,65,30),('永生之茧',320,250,100,30))
    d.home=lambda:world;calls=[];frames=iter([world,territory])
    def observe():
        s=next(frames)
        if s is world:d.report['dismissed_offers']=[{'status':'closed'}]
        return s
    d.observe=observe;d.click_world=lambda s,p,r:calls.append(p)
    assert d.territory() is territory and calls==[(1230,625)]*2


def test_offer_does_not_replay_world_navigation_on_an_unknown_page(tmp_path):
    d=daily(tmp_path);world=captured('v0913-main-world',True);unknown=screen()
    d.home=lambda:world;calls=[]
    def observe():d.report['dismissed_offers']=[{'status':'closed'}];return unknown
    d.observe=observe;d.click_world=lambda s,p,r:calls.append(p)
    def wait(predicate,label,**kwargs):kwargs['retry_navigation'](unknown);raise TaskBlocked('unknown')
    d.wait_for_screen=wait
    with pytest.raises(TaskBlocked,match='unknown'):d.territory()
    assert calls==[(1230,625)]


def test_leftover_generic_friend_dialog_is_cancelled_never_confirmed(tmp_path):
    d=daily(tmp_path);prompt=captured('v0921-friend-confirm',True);world=captured('v0913-main-world',True)
    assert friend_delete_confirmation(prompt) and not is_world(prompt)
    d.observe=lambda:world;inputs=[];d.b.click_text=lambda s,p,**kw:inputs.append(p)
    assert d.home(prompt) is world and inputs==['^取消$']


def test_generic_confirmation_uses_the_profile_verified_in_this_transaction(tmp_path):
    d=daily(tmp_path);state,inputs=fake(d,friends())
    profile=captured('other-friend-profile');prompt=captured('v0921-friend-confirm',True)
    d.b.click_at=lambda *a:state.__setitem__(0,profile)
    def click(s,p,**kw):
        inputs.append(p);state[0]=prompt if p=='^删除好友$' else friends(count=55)
    d.b.click_text=click
    assert friend_count(d.remove_friend(friend_rows(friends())[0],(56,60)))==(55,60)
    assert inputs==['^删除好友$','^确定$']


def test_wrong_named_confirmation_is_cancelled_even_with_old_profile_visible(tmp_path):
    d=daily(tmp_path);state,inputs=fake(d,friends());profile=captured('other-friend-profile')
    prompt=deepcopy(profile)
    prompt.words+=screen(('是否删除好友另一个人?',370,285,390,40),('确定',740,465,80,35),('取消',440,465,80,35)).words
    d.b.click_at=lambda *a:state.__setitem__(0,profile)
    def click(s,p,**kw):inputs.append(p);state[0]=prompt
    d.b.click_text=click
    with pytest.raises(TaskBlocked,match='身份不符，已取消'):d.remove_friend(friend_rows(friends())[0],(56,60))
    assert inputs==['^删除好友$','^取消$']


def test_forest_node_recognition_retries_three_times_without_replaying_input(tmp_path,monkeypatch):
    import chao2.forest as module
    d=daily(tmp_path);s=captured('v0921-forest-ocr',True)
    d.forest_offset=[0.,0.];d.b.sleep=lambda _:None;reads=[]
    d.forest_wait_map=lambda:reads.append(1) or s
    monkeypatch.setattr(module,'forest_nodes',lambda *a:[])
    monkeypatch.setattr(module,'recover_forest_node',lambda *a:None)
    monkeypatch.setattr(module,'forest_shift',lambda *a:(0,0))
    d.b.click_at=lambda *a:pytest.fail('No input without a re-detected target')
    node=ForestNode('beast',(376,130),'challenge',0,(376,130))
    with pytest.raises(TaskBlocked,match='连续3次重试'):d.forest_reach(s,node)
    assert len(reads)==3 and len(d.report['navigation_retries'])==3


def test_forest_late_recognition_reconciles_camera_shift(tmp_path,monkeypatch):
    import chao2.forest as module
    d=daily(tmp_path);s=captured('v0921-forest-ocr',True);q=deepcopy(s)
    d.forest_offset=[0.,0.];d.b.sleep=lambda _:None;d.forest_wait_map=lambda:q
    node=ForestNode('beast',(376,130),'challenge',0,(376,130))
    now=ForestNode('beast',(416,130),'challenge')
    monkeypatch.setattr(module,'forest_nodes',lambda b,frame:[now] if frame is q else [])
    monkeypatch.setattr(module,'recover_forest_node',lambda *a:None)
    monkeypatch.setattr(module,'forest_shift',lambda *a:(40,0))
    after,target=d.forest_reach(s,node)
    assert after is q and target.point==(416,130) and d.forest_offset==[-40,0]


def test_daily_claim_accepts_missing_leading_stroke_and_only_free_rewards():
    ready=captured('v0921-daily-ready',True)
    assert task_claim_slot(ready)==(0,65,250,90)
    assert task_claim_slot(captured('v0921-daily-chest-done',True)) is None
    assert daily_activity_chests(ready)==[]
    assert daily_activity_chests(captured('v0921-daily-after-bulk',True))==[(100,(582,130))]
    assert daily_activity_chests(captured('v0921-daily-chest-done',True))==[]
    assert daily_activity_chests(captured('v0921-daily-chest-open',True))==[]
    assert task_claim_slot(captured('v0921-star-gift',True)) is None


def test_daily_reward_batch_count_only_after_receipt_then_activity_check(tmp_path):
    d=daily(tmp_path);ready=captured('v0921-daily-ready',True);done=captured('v0921-daily-chest-done',True)
    d.task_panel=lambda _:ready;d.home=lambda:None;d.save_state=lambda:None;calls=[]
    d.claim_collection_text=lambda s,roi,page:calls.append(('claim',roi)) or done
    d.collect_daily_activity=lambda s:calls.append(('activity',s)) or s
    assert d.collect_task_tab('每日挑战')==1
    assert [c[0] for c in calls]==['claim','activity']
    assert not d.report['task_rewards']['每日挑战']['remaining_claims']


def test_daily_activity_claim_needs_receipt_and_disappeared_glow(tmp_path):
    d=daily(tmp_path);ready=captured('v0921-daily-after-bulk',True)
    reward=captured('v0921-daily-chest-open',True);done=captured('v0921-daily-chest-done',True)
    frames=iter([ready,reward,done]);d.observe=lambda:next(frames);inputs=[]
    d.b.click_at=lambda s,p,a,r:inputs.append(p)
    assert d.collect_daily_activity(ready) is done
    assert inputs==[(582,130),(640,660)] and d.report['daily_activity_claimed']==[100]


def test_same_claim_label_can_lose_leading_stroke_between_frames(tmp_path):
    d=daily(tmp_path);ready=captured('v0921-daily-ready',True)
    done=captured('v0921-daily-chest-done',True);inputs=[]
    d.b.click_text=lambda s,p,**kw:inputs.append(p);d.observe=lambda:done
    d.claim_collection_text(ready,(0,65,250,90),lambda q:True)
    assert inputs==[CLAIM]


def test_forest_special_explorer_is_a_known_challenge_not_any_special_event(tmp_path):
    from chao2.forest import forest_detail,verify_free_forest
    d=daily(tmp_path);event=captured('v0921-forest-explorer',True)
    name=forest_detail(event)
    assert name=='其他探索者（特殊事件'
    event.words.append(Word('消耗100',[1030,645,150,30],.99))
    with pytest.raises(SafetyStop,match='出现费用'):verify_free_forest(d.b,event,name)
    event.words=[Word('未知特殊事件',w.box,w.score) if '其他探索者' in w.text else w for w in event.words]
    assert forest_detail(event) is None
