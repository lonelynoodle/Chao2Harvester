"""The requested preset, its copy button and portraits must share one fresh frame."""
from copy import deepcopy
import pytest
from test_configuration import captured,daily,screen
from chao2.backend import Backend,ROOT,Word
from chao2.team_copy import saved_team_copy_target,is_saved_team_list
from chao2.policy import TaskBlocked,UserStopped


def source():return captured('v0961-tribe-copy-blocked',True)


def missing_button():
    s=source();s.words=[w for w in s.words if not(w.text=='复制此配置' and w.center[1]<180)]
    return s


def test_actual_announcement_frame_pairs_only_requested_team(tmp_path):
    d=daily(tmp_path);s=source()
    assert not s.find('^配置$') and is_saved_team_list(s)
    for team,y in ((1,120),(2,284),(3,447)):
        row,button=saved_team_copy_target(d.b,s,team)
        assert row.text=='队伍'+str(team) and abs(button.center[1]-y)<5
    assert saved_team_copy_target(d.b,s,4) is None  # clipped portraits


def test_actual_maa_rereads_missing_copy_label_only_in_target_row():
    from test_maa_recognition import Offline
    from maa.resource import Resource
    from maa.tasker import Tasker
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({},log=lambda _:None);b.tasker=t
    s=missing_button();assert is_saved_team_list(s)
    row,button=saved_team_copy_target(b,s,1)
    assert row.text=='队伍1' and 100<button.center[1]<145 and button.text=='复制此配置'


@pytest.mark.parametrize('delay',[0,1,2,3])
def test_missing_label_is_read_again_before_any_copy(tmp_path,delay):
    d=daily(tmp_path);d.b.sleep=lambda _:None;valid=source()
    pages=iter([missing_button()]*delay+[valid]);d.observe=lambda:next(pages)
    d.b.click_at=lambda *a:pytest.fail('Target lookup must not click')
    s,row,button=d.read_saved_team_copy_target(1)
    assert s is valid and row.text=='队伍1' and button.center[1]<145
    assert len(d.report.get('navigation_retries',[]))==delay


@pytest.mark.parametrize('change',['missing_button','missing_team','duplicate_team','unknown_page','clipped_row'])
def test_unconfirmed_target_never_uses_another_teams_copy_button(tmp_path,change):
    d=daily(tmp_path);d.b.sleep=lambda _:None;s=source()
    if change=='missing_button':s=missing_button()
    elif change=='missing_team':s.words=[w for w in s.words if w.text!='队伍1']
    elif change=='duplicate_team':s.words.append(Word('队伍1',[317,272,63,24],.99))
    elif change=='unknown_page':s=screen(('复制此配置',790,110,120,25))
    else:s.find('^队伍1$').box[1]=598
    d.observe=lambda:s;d.b.click_at=lambda *a:pytest.fail('No blind copy')
    with pytest.raises(TaskBlocked,match='重读3次'):d.read_saved_team_copy_target(1)
    assert len(d.report['navigation_retries'])==3


def test_moved_row_is_relocated_by_requested_team_not_old_button_position(tmp_path):
    d=daily(tmp_path);s=source()
    first=s.find('^队伍1$');second=s.find('^队伍2$')
    first.box[1],second.box[1]=second.box[1],first.box[1]
    d.observe=lambda:s
    _,row,button=d.read_saved_team_copy_target(1)
    assert row.text=='队伍1' and 270<button.center[1]<300


def test_stop_during_target_recovery_has_no_copy(tmp_path):
    d=daily(tmp_path);d.observe=missing_button
    d.b.sleep=lambda _:d.b.stop.set()
    d.b.click_at=lambda *a:pytest.fail('Stop forbids more input')
    with pytest.raises(UserStopped):d.read_saved_team_copy_target(1)


def test_copy_uses_fresh_source_and_does_not_repeat_text_only_recheck(tmp_path):
    d=daily(tmp_path);d.active_task='tribe';d.b.sleep=lambda _:None
    old=captured('v0940-team-copy-source',True);fresh=deepcopy(old)
    target=captured('v0940-tribe-copied',True)
    pages=iter([old,fresh,target]);d.observe=lambda:next(pages)
    d.b.read_text_crop=lambda *_:'';d.b.read_text_region=lambda *_:''
    calls=[];d.b.click_at=lambda *a:calls.append(a)
    d.b.click_text=lambda *a,**kw:pytest.fail('Text-only recheck loses team-row identity')
    assert d.apply_saved_team(captured('tribe-formation'),1) is target
    copies=[a for a in calls if a[3].startswith('复制保存的')]
    assert len(copies)==1 and copies[0][0] is fresh and '^队伍1$' in copies[0][2]
    assert d.report['team_copy_checks'][0]['status']=='verified'
    assert d.report['team_copy_checks'][0]['matched_monsters']==5


def test_empty_source_portraits_stop_before_copy(tmp_path):
    d=daily(tmp_path);d.active_task='tribe';s=captured('v0940-team-copy-source')
    d.observe=lambda:s;d.b.read_text_crop=lambda *_:'';d.b.read_text_region=lambda *_:''
    copies=[];d.b.click_at=lambda *a:copies.append(a[3])
    with pytest.raises(TaskBlocked,match='源配置头像'):d.apply_saved_team(captured('tribe-formation'),1)
    assert copies==['打开配置列表'] and d.battles==0
