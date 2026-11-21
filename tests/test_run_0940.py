"""Actual 14:59 failures: level-gated tower, false checkbox and tribe header."""
from types import SimpleNamespace

import pytest

from chao2.anomalies import evolved_copy_without_instant,instant_checkbox_present,instant_frame
from chao2.backend import Backend,Word
from chao2.challenge_start import challenge_unlock_level
from chao2.policy import ChallengeLocked,TaskBlocked
from test_configuration import captured,daily,screen
from test_tower_flow import TowerGame,KINDS


def test_evolved_copy_background_is_not_a_checkbox(tmp_path):
    s=captured('v0940-copy-evolved',True)
    assert not instant_checkbox_present(s) and evolved_copy_without_instant(s)
    d=daily(tmp_path);d.b.match_template=lambda q,n,*a:n=='copy-own-exp50.png'
    d.observe=lambda:pytest.fail('The fully identified evolved detail needs no extra read')
    d.verify_instant_setting('copies',s)


@pytest.mark.parametrize('checked',[False,True])
def test_real_checkbox_rim_still_blocks_evolved_layout(tmp_path,checked):
    s=captured('v0940-copy-evolved',True);rim,_=instant_frame();h,w=rim.shape[:2]
    s.image[685:685+h,1010:1010+w]=rim
    if checked:s.image[695:704,1020:1029]=255
    assert instant_checkbox_present(s) and not evolved_copy_without_instant(s)
    d=daily(tmp_path);d.b.match_template=lambda q,n,*a:n=='copy-own-exp50.png'
    with pytest.raises(TaskBlocked,match='瞬破'):d.verify_instant_setting('copies',s)


def test_ordinary_copy_does_not_inherit_evolved_exemption(tmp_path):
    s=captured('v0940-copy-evolved',True)
    for w in s.words:
        if '暴进' in w.text:w.text='普通复制体'
    d=daily(tmp_path);d.b.match_template=lambda q,n,*a:n=='copy-own-exp50.png'
    d.observe=lambda:s;d.b.sleep=lambda _:None
    with pytest.raises(TaskBlocked,match='瞬破'):d.verify_instant_setting('copies',s)


def test_copied_tribe_short_header_is_a_valid_formation_page(tmp_path):
    d=daily(tmp_path);s=captured('v0940-tribe-copied',True)
    assert s.find('^部队$').center[0]==88
    d.observe=lambda:s;d.b.sleep=lambda _:None;d.active_task='tribe'
    assert d.formation_page() is s
    d.active_task='copies'
    with pytest.raises(TaskBlocked):d.formation_page()


@pytest.mark.parametrize('missing_reads',[0,1,2])
def test_actual_copied_lineup_survives_header_reflow_without_recopying(tmp_path,missing_reads):
    d=daily(tmp_path);d.active_task='tribe'
    source=captured('v0940-team-copy-source',True);target=captured('v0940-tribe-copied',True)
    missing=captured('v0940-tribe-copied',True);missing.words=[w for w in missing.words if w.text!='部队']
    frames=iter([source,source]+[missing]*missing_reads+[target]);d.observe=lambda:next(frames)
    d.b.sleep=lambda _:None;copies=[];d.b.click_text=lambda *a,**kw:copies.append(a[1])
    d.b.click_at=lambda *a,**kw:copies.append('^复制此配置$') if a[3].startswith('复制保存的') else None
    assert d.apply_saved_team(captured('tribe-formation'),1) is target
    check=d.report['team_copy_checks'][0]
    assert check['status']=='verified' and check['reads']==missing_reads+1
    assert check['matched_monsters']==5 and 'god_verified' not in check
    assert copies==['^复制此配置$']


def test_persistent_unknown_copy_page_remains_blocked_after_read_retries(tmp_path):
    d=daily(tmp_path);d.active_task='tribe'
    source=captured('v0940-team-copy-source',True);missing=screen()
    frames=iter([source,source,missing,missing,missing]);d.observe=lambda:next(frames)
    d.b.sleep=lambda _:None;copies=[];d.b.click_text=lambda *a,**kw:copies.append(a[1])
    d.b.click_at=lambda *a,**kw:copies.append('^复制此配置$') if a[3].startswith('复制保存的') else None
    with pytest.raises(TaskBlocked,match='重读3次'):d.apply_saved_team(captured('tribe-formation'),1)
    assert copies==['^复制此配置$'] and d.battles==0
    assert d.report['team_copy_checks'][0]['status']=='unconfirmed'


def test_tower_level_toast_is_detected_only_in_its_notification_band():
    assert challenge_unlock_level(captured('v0940-tower-locked'))==70
    assert challenge_unlock_level(screen(('探索者等级70解锁',550,150,180,22))) is None
    assert challenge_unlock_level(screen(('世界灾厄70分钟后',438,43,400,24))) is None


@pytest.mark.parametrize('already_visible',[False,True])
def test_tower_level_lock_has_no_battle_or_repeated_click(tmp_path,already_visible):
    d=daily(tmp_path);d.b.sleep=lambda _:None
    locked=captured('v0940-tower-locked',True)
    detail=captured('v0940-tower-locked',True)
    detail.words=[w for w in detail.words if '探索者等级' not in w.text]
    clicks=[];d.b.click_text=lambda *a,**kw:clicks.append(kw)
    d.observe=lambda:locked;d.resource_balance('tower','浮空羽毛',8)
    with pytest.raises(ChallengeLocked) as caught:
        d.start_challenge('tower',locked if already_visible else detail,'浮空羽毛')
    assert caught.value.level==70 and caught.value.screen is locked
    assert len(clicks)==int(not already_visible)
    if clicks:assert clicks[0]['settle_delay']==.15
    assert d.battles==0 and d.task_counts=={}
    assert d.report['challenge_starts'][0]['status']=='locked'
    assert d.report['challenge_locks'][0]['required_level']==70
    assert d.report['resource_usage']['tower']['浮空羽毛']['spent']==0


def test_level_gated_first_tower_checks_its_existing_secrets_then_other_tower(tmp_path):
    game=TowerGame(tmp_path,balance=2);game.floors['normal']=401
    observe=game.observe;click=game.d.b.click_text;locked=[False]
    def read(*a):
        s=observe(*a)
        if game.kind['id']=='normal' and locked[0]:
            s.words.append(Word('探索者等级70解锁',[550,348,180,22],.99))
        return s
    def tap(s,p,**kw):
        if game.kind['id']=='normal':locked[0]=True
        else:click(s,p,**kw)
    game.d.observe=read;game.d.b.click_text=tap
    message=game.d.tower()
    assert game.opened==['normal','dragon'] and game.secrets==['normal','dragon','puppet']
    assert len(game.challenges)==game.d.task_counts['tower']==2
    assert all(row[0]=='dragon' for row in game.challenges)
    assert '等级未解锁跳过1座塔' in message
    assert game.d.report['tower_summary']['level_locked']==[
        {'tower':'normal','floor':401,'required_level':70}]


def test_next_floor_level_gate_is_not_retried_or_counted_as_a_battle(tmp_path):
    d=daily(tmp_path);d.b.sleep=lambda _:None
    old=captured('tower-next-result');locked=captured('tower-next-result')
    locked.words.append(Word('探索者等级70解锁',[550,348,180,22],.99))
    d.observe=lambda:locked;clicks=[];d.b.click_text=lambda *a,**kw:clicks.append(kw)
    with pytest.raises(ChallengeLocked):d.tower_advance(old,KINDS[0],401)
    assert clicks==[{'settle_delay':.15}] and d.battles==0
    assert d.report['challenge_locks'][0]['target']=='浮空巨塔401'


def test_backend_click_preserves_guard_and_supports_prompt_toast_capture(tmp_path):
    d=daily(tmp_path);s=captured('v0940-tower-locked',True);inputs=[];delays=[]
    d.b.controller=SimpleNamespace(post_click=lambda x,y:inputs.append((x,y)))
    d.b.wait=lambda _:SimpleNamespace(succeeded=True);d.b.sleep=delays.append
    d.b.observe=lambda:s
    Backend.click_text(d.b,s,'^挑战$',settle_delay=.15)
    Backend.click_text(d.b,s,'^挑战$')
    assert inputs==[(976,616)]*2 and delays==[.15,2]
    d.b.stop.set()
    from chao2.policy import UserStopped
    with pytest.raises(UserStopped):Backend.click_text(d.b,s,'^挑战$',settle_delay=.15)
    assert len(inputs)==2
