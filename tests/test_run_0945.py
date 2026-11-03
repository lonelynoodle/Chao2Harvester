"""Actual announcement-obscured config list and remote main-stage retries."""
import copy
import pytest
from test_configuration import captured,daily,screen
from chao2.team_copy import is_saved_team_list,saved_team_rows,saved_team_anchors
from chao2.activities import main_identity,main_nodes,MainRetryUnavailable
from chao2.policy import TaskBlocked,UserStopped
from chao2.workflows import is_world


def test_actual_server_announcement_does_not_hide_team_list():
    s=captured('v0945-team-announcement',True)
    assert not s.find('^配置$')
    assert is_saved_team_list(s) and not is_world(s)
    assert [row[0].text for row in saved_team_rows(s)]==['队伍1','队伍2','队伍3','队伍4']
    assert s.has(*saved_team_anchors(s))


def test_config_fallback_requires_separate_aligned_rows():
    s=captured('v0945-team-announcement')
    s.words=[w for w in s.words if w.text not in ('队伍2','队伍3','队伍4')]
    assert not is_saved_team_list(s)
    s=captured('v0945-team-announcement')
    for w in s.words:
        if w.text=='复制此配置':w.box[1]+=55
    assert not is_saved_team_list(s)


def test_existing_titled_config_remains_recognized():
    assert is_saved_team_list(captured('v0940-team-copy-source',True))
    assert not is_saved_team_list(captured('tribe-formation',True))
    assert not is_saved_team_list(captured('v0944-tribe-entry',True))


def test_announced_config_can_be_closed_during_recovery(tmp_path):
    d=daily(tmp_path);modal=captured('v0945-team-announcement',True)
    world=captured('v0913-main-world',True);d.observe=lambda:world
    clicks=[];d.b.click_at=lambda s,p,a,reason:clicks.append((p,a,reason))
    assert d.home(modal) is world
    assert clicks==[((960,54),saved_team_anchors(modal),'关闭复制配置')]


def test_config_read_retries_without_copying_or_reopening(tmp_path):
    d=daily(tmp_path);empty=screen();actual=captured('v0945-team-announcement')
    frames=iter([empty,empty,empty,actual]);d.observe=lambda:next(frames)
    d.b.sleep=lambda _:None;d.b.click_at=lambda *a:pytest.fail('Read-only retry')
    assert d.read_saved_team_list() is actual
    assert len(d.report['navigation_retries'])==3


def test_config_retry_exhaustion_and_user_stop_do_not_click(tmp_path):
    d=daily(tmp_path);d.observe=lambda:screen();d.b.sleep=lambda _:None
    d.b.click_at=lambda *a:pytest.fail('Never click unknown list')
    with pytest.raises(TaskBlocked,match='3次'):d.read_saved_team_list()
    d.b.stop.set()
    with pytest.raises(UserStopped):d.read_saved_team_list()


def test_title_covered_during_copy_still_verifies_portraits(tmp_path):
    d=daily(tmp_path);d.active_task='tribe'
    source=captured('v0940-team-copy-source',True)
    source.words=[w for w in source.words if w.text!='配置']
    dest=captured('v0940-tribe-copied',True)
    frames=iter([source,source,dest]);d.observe=lambda:next(frames);d.b.sleep=lambda _:None
    d.b.read_text_crop=lambda *_:'';d.b.read_text_region=lambda *_:''
    copies=[];d.b.click_at=lambda *a:copies.append('^复制此配置$') if a[3].startswith('复制保存的') else None
    d.b.click_text=lambda s,p,**kw:copies.append(p)
    assert d.apply_saved_team(captured('tribe-formation'),1) is dest
    assert copies==['^复制此配置$']
    assert d.report['team_copy_checks'][0]['status']=='verified'


def test_overview_records_the_verified_remote_identity(tmp_path):
    d=daily(tmp_path);target=captured('v092-main-detail594')
    d.enter_overview=lambda *_:None;d.await_detail=lambda:target
    assert d.main_overview_detail() is target and d._main_overview_target=='594'


def test_actual_pulsing_main_marker_is_not_lost_after_failure():
    s=captured('v0945-main-pulse',True)
    assert any(abs(x-586)<3 and abs(y-313)<3 for x,y in main_nodes(s))


def test_remote_main_prefers_local_node_without_new_overview_recommendation(tmp_path):
    d=daily(tmp_path);d._main_overview_target='594'
    d.home=lambda:captured('v0945-main-pulse',True)
    target=captured('v092-main-detail594')
    d.find_main_candidate=lambda *a,**kw:target
    d.main_overview_detail=lambda:pytest.fail('Local target must win over overview')
    assert d.last_main_detail('594') is target


def test_remote_failed_stage_uses_overview_only_after_local_scan(tmp_path):
    d=daily(tmp_path);world=captured('v0913-main-world',True)
    target=captured('v092-main-detail594');d._main_overview_target='594'
    d.home=lambda *a:world;d.main_overview_detail=lambda:target
    d.find_main_candidate=lambda *a,**kw:None
    assert d.last_main_detail('594') is target


def test_remote_overview_changed_suggestion_is_closed_never_challenged(tmp_path):
    d=daily(tmp_path);world=captured('v0913-main-world',True)
    target=captured('v092-main-detail594');other=copy.deepcopy(target)
    next(w for w in other.words if w.text=='594').text='595'
    d._main_overview_target='594';d.home=lambda *a:world
    d.main_overview_detail=lambda:other;closed=[]
    d.back_detail=lambda q:closed.append(main_identity(q))
    d.find_main_candidate=lambda *a,**kw:None
    d.start_challenge=lambda *a:pytest.fail('Wrong stage must not be fought')
    with pytest.raises(MainRetryUnavailable):d.last_main_detail('594')
    assert closed==['595']*4
    assert d.report['main_retry_lookups'][0]['status']=='unavailable'


def test_remote_overview_can_retry_changed_recommendations_until_same_stage(tmp_path):
    d=daily(tmp_path);d._main_overview_target='594'
    d.home=lambda:captured('v0945-main-pulse',True)
    wanted=captured('v092-main-detail594');other=copy.deepcopy(wanted)
    next(w for w in other.words if w.text=='594').text='595'
    d.find_main_candidate=lambda *a,**kw:None
    pages=iter([other,None,wanted]);d.main_overview_detail=lambda:next(pages)
    closed=[];d.back_detail=lambda s:closed.append(main_identity(s))
    assert d.last_main_detail('594') is wanted and closed==['595']
    assert d.report['main_retry_lookups'][0]['observed']==['595',None,'594']


def test_occupation_receipt_confirms_delivery_without_inventing_zero(tmp_path):
    from test_changes_0936 import tribe_map
    d=daily(tmp_path);before=tribe_map(10);after=tribe_map(0)
    after.words=[w for w in after.words if w.text!='遗迹占领奖励']
    reward=screen(('部落',140,14,60,28),('获得奖励',510,110,240,60))
    d.b.click_at=lambda *a:None
    d.wait_for_screen=lambda *a,**kw:reward
    d.clear_tribe_reward=lambda s:after
    assert d.claim_tribe_occupation(before) is after
    row=d.report['tribe_occupation_rewards'][0]
    assert row['status']=='received' and row['remaining'] is None and 'claimed' not in row
    assert row['clicks']==1


def test_report_write_retries_three_windows_sharing_locks(tmp_path,monkeypatch):
    import json
    from pathlib import Path
    from chao2 import file_io
    from chao2.workflows import write_report
    target=tmp_path/'report.json';target.write_text('{"old":true}')
    replace=Path.replace;calls=[];waits=[]
    def locked(source,dest):
        calls.append(source)
        assert json.loads(target.read_text())=={'old':True}
        if len(calls)<4:raise PermissionError(13,'temporary Windows sharing lock')
        return replace(source,dest)
    monkeypatch.setattr(Path,'replace',locked);monkeypatch.setattr(file_io.time,'sleep',waits.append)
    write_report({'folder':tmp_path,'status':'running','battles':[{'result':'victory'}]})
    assert len(calls)==4 and len(waits)==3 and len(set(calls))==1
    assert json.loads(target.read_text())['battles']==[{'result':'victory'}]
    assert not list(tmp_path.glob('*.tmp'))


def test_persistent_write_lock_preserves_old_report_and_pending_snapshot(tmp_path,monkeypatch):
    import json
    from pathlib import Path
    from chao2 import file_io
    target=tmp_path/'report.json';target.write_text('{"old":true}')
    calls=[]
    def locked(source,dest):
        calls.append(1);raise PermissionError(13,'permanent lock')
    monkeypatch.setattr(Path,'replace',locked);monkeypatch.setattr(file_io.time,'sleep',lambda _:None)
    with pytest.raises(PermissionError):file_io.atomic_json(target,{'new':True})
    assert len(calls)==4 and json.loads(target.read_text())=={'old':True}
    assert json.loads(next(tmp_path.glob('*.tmp')).read_text())=={'new':True}


def missing_quota_frame():
    s=captured('v0945-friend-quota',True)
    for word in s.words:
        if '本周已获取友好点数' in word.text:word.text='本周已获取友好点数'
    return s


def test_readable_friend_cap_does_not_reobserve_or_open_targets(tmp_path):
    d=daily(tmp_path);s=captured('v0945-friend-quota')
    d.observe=lambda:pytest.fail('Known quota needs no extra observation')
    d.b.click_at=lambda *a:pytest.fail('Quota reading must not click')
    assert d.read_copy_quota(s)==(s,(1000,1000))


def test_actual_gold_quota_is_recovered_by_local_ocr(tmp_path):
    from test_maa_recognition import Offline
    from chao2.backend import ROOT
    from maa.resource import Resource
    from maa.tasker import Tasker
    controller=Offline();assert controller.post_connection().wait().succeeded
    resource=Resource();assert resource.post_bundle(ROOT/'resource').wait().succeeded
    tasker=Tasker();assert tasker.bind(resource,controller)
    d=daily(tmp_path);d.options['copies']['include_friends']=True
    d.b.tasker=tasker;s=missing_quota_frame()
    d.observe=lambda:pytest.fail('Crop should recover the actual gold digits')
    d.b.click_at=lambda *a:pytest.fail('Quota reading must not click')
    assert d.read_copy_quota(s)==(s,(1000,1000))
    assert d.report['copy_friend_quota']['source']=='crop'


def test_friend_quota_gets_three_read_only_retries(tmp_path):
    d=daily(tmp_path);d.options['copies']['include_friends']=True
    bad=missing_quota_frame();good=captured('copy-list')
    pages=iter([bad,bad,good]);seen=[]
    d.observe=lambda:seen.append(1) or next(pages);d.b.sleep=lambda _:None
    d.b.click_at=lambda *a:pytest.fail('Do not open another target on unreadable quota')
    actual,quota=d.read_copy_quota(bad)
    assert actual is good and quota==(449,1000) and len(seen)==3


def test_unknown_quota_remains_unknown_and_ignores_numeric_player_name(tmp_path):
    from chao2.backend import Word
    d=daily(tmp_path);d.options['copies']['include_friends']=True
    s=missing_quota_frame();seen=[]
    s.words.append(Word('200',[913,210,80,25],.99))
    d.observe=lambda:seen.append(1) or s;d.b.sleep=lambda _:None
    assert d.read_copy_quota(s)==(s,(None,None)) and len(seen)==3


def test_friend_quota_disabled_does_not_delay_own_targets(tmp_path):
    d=daily(tmp_path);d.options['copies']['include_friends']=False;s=missing_quota_frame()
    d.observe=lambda:pytest.fail('Disabled friend targets require no quota retry')
    assert d.read_copy_quota(s)==(s,(None,None))


def test_friend_quota_retry_respects_user_stop(tmp_path):
    d=daily(tmp_path);d.options['copies']['include_friends']=True;d.b.sleep=lambda _:None
    d.observe=lambda:(_ for _ in ()).throw(UserStopped('stop'))
    with pytest.raises(UserStopped):d.read_copy_quota(missing_quota_frame())
