"""Merged secret heading and the completely missed totem heading from Nov 14."""
from types import SimpleNamespace
import time
import pytest
from chao2.backend import Screen,Word
from chao2.policy import SafetyStop,SessionUnavailable,TaskBlocked,UserStopped
from chao2.activities import enemy_formation,is_tribe_detail,recover_tower_detail
from chao2.dungeon_labels import recover_totem_heading
from test_configuration import captured,daily,screen
from test_rift_main_0959 import offline_backend


def secret(heading='敌方阵容1（23'):
    return screen(('塔中秘庭100',233,105,155,28),('首通奖励',173,557,75,22),
                  (heading,782,104,258,27),('排阵',702,611,62,36),('挑战',946,611,62,36))


@pytest.mark.parametrize('heading',['敌方阵容','敌方阵容1（23','敌方阵容1234)5','敌方阵容Q1023)4'])
def test_secret_free_check_reuses_the_same_supported_heading_parser(tmp_path,heading):
    d=daily(tmp_path);s=secret(heading)
    assert enemy_formation(s)
    d.verify_tower_secret(s,'塔中秘庭100')
    assert d.battles==0 and d.task_counts=={}


def test_real_secret_failure_is_free_even_with_joined_formation_tabs(tmp_path):
    d=daily(tmp_path);s=captured('v0988-secret-free',True)
    assert s.find('^敌方阵容$') is None and enemy_formation(s).text=='敌方阵容1（23'
    d.verify_tower_secret(s,'塔中秘庭100')


@pytest.mark.parametrize('change',['cost','raised_button','wrong_title','unknown_heading','overlay'])
def test_secret_free_check_keeps_target_cost_and_page_guards(tmp_path,change):
    d=daily(tmp_path);s=secret()
    if change=='cost':s.words+=screen(('1',1000,642,20,20)).words
    elif change=='raised_button':s.find('^挑战$').box[1]=585
    elif change=='wrong_title':s.find('^塔中秘庭100$').text='塔中秘庭101'
    elif change=='unknown_heading':s.words[2].text='其他文字'
    else:s.words+=screen(('取消',420,450,80,30),('确定',760,450,80,30)).words
    with pytest.raises((TaskBlocked,SafetyStop)):d.verify_tower_secret(s,'塔中秘庭100')


def test_secret_missing_heading_is_read_in_its_own_local_region(offline_backend):
    s=captured('v0988-secret-free',True);s.words=[w for w in s.words if not w.text.startswith('敌方阵容')]
    fixed=recover_tower_detail(offline_backend,s)
    assert enemy_formation(s) is None and enemy_formation(fixed)
    assert fixed.when==s.when and fixed.image is s.image


def totem():
    return screen(('真实图腾',129,15,100,28),('真实图腾',125,135,111,31),
                  ('图腾共生',58,226,83,24),('比拼方式',57,362,84,24),
                  ('每次挑战奖励',41,565,108,18),('排阵',824,614,61,35),('挑战',1060,603,61,34),
                  ('剩余次数：9/10',1020,559,142,23),('5/16',1217,15,47,26))


def test_actual_totem_local_ocr_recovers_heading_and_verifies_one_order_cost(tmp_path,offline_backend):
    s=captured('v0988-totem-heading',True)
    assert not enemy_formation(s) and not is_tribe_detail(s)
    fixed=recover_totem_heading(offline_backend,s)
    assert fixed is not s and fixed.when==s.when and is_tribe_detail(fixed)
    assert fixed.find('^敌方阵容$').score>=.8 and not enemy_formation(s)
    d=daily(tmp_path);d.b=offline_backend
    d.verify_tribe_detail(fixed,'真实图腾')
    assert not d.report.get('team_attempts') and d.battles==0


def test_local_ocr_retries_a_second_scale_before_fallback(tmp_path,monkeypatch):
    d=daily(tmp_path);d.b.tasker=object();s=totem();calls=[]
    def confirm(q,pattern,roi,scale,threshold):
        calls.append((roi,scale,threshold))
        if scale==3:return False
        q.words.append(Word('敌方阵容',[1132,135,103,27],.95));return True
    d.b.confirm_label=confirm
    fixed=recover_totem_heading(d.b,s)
    assert is_tribe_detail(fixed) and [c[1] for c in calls]==[3,4]
    assert all(c[0]==(1080,115,200,80) and c[2]==.8 for c in calls)


def test_verified_heading_pixels_are_the_fallback_after_both_ocr_scales_fail(tmp_path):
    d=daily(tmp_path);d.b.tasker=object();calls=[]
    d.b.confirm_label=lambda *a,**k:calls.append(k['scale']) or False
    s=captured('v0988-totem-heading',True);fixed=recover_totem_heading(d.b,s)
    assert is_tribe_detail(fixed) and fixed.find('^敌方阵容$').score>=.93
    assert calls==[3,4]


@pytest.mark.parametrize('missing',['top_title','detail_title','图腾共生','比拼方式','每次挑战奖励','排阵','挑战'])
def test_incomplete_totem_layout_cannot_gain_a_heading_from_background_pixels(tmp_path,missing):
    d=daily(tmp_path);d.b.tasker=object();s=captured('v0988-totem-heading',True)
    if missing=='top_title':s.words=[w for w in s.words if not (w.text=='真实图腾' and w.center[1]<65)]
    elif missing=='detail_title':s.words=[w for w in s.words if not (w.text=='真实图腾' and w.center[1]>65)]
    else:s.words=[w for w in s.words if w.text!=missing]
    d.b.confirm_label=lambda *a,**k:pytest.fail('Do not read a partial or different detail')
    assert recover_totem_heading(d.b,s) is s and not enemy_formation(s)


@pytest.mark.parametrize('overlay',['取消','获得奖励','复制此配置'])
def test_totem_recovery_does_not_recognize_through_a_modal(tmp_path,overlay):
    d=daily(tmp_path);d.b.tasker=object();s=totem()
    s.words+=screen((overlay,500,300,140,30)).words
    d.b.confirm_label=lambda *a,**k:pytest.fail('No obscured heading')
    assert recover_totem_heading(d.b,s) is s


def test_unknown_pixels_are_not_treated_as_enemy_heading(tmp_path):
    d=daily(tmp_path);d.b.tasker=object();d.b.confirm_label=lambda *a,**k:False
    s=totem();assert recover_totem_heading(d.b,s) is s and not enemy_formation(s)


def test_real_totem_navigation_recovers_delayed_ocr_without_reclicking_the_map(tmp_path,monkeypatch,offline_backend):
    import chao2.activities as activities
    import chao2.dungeon_labels as labels
    d=daily(tmp_path);d.b=offline_backend;d.active_task='tribe';d._tribe_totem_kind='truth'
    initial=screen(('部落',110,15,100,30),('部落大厅',1100,650,110,30))
    raw=captured('v0988-totem-heading',True);pages=iter([initial,raw,raw]);clicks=[];calls=[]
    def observe(*a):
        s=next(pages);return Screen(s.image,list(s.words),time.monotonic())
    monkeypatch.setattr(d.b,'observe',observe);monkeypatch.setattr(d.b,'sleep',lambda _:None)
    monkeypatch.setattr(d.b,'click_at',lambda s,p,a,r:clicks.append((p,r)))
    monkeypatch.setattr(activities,'totem_nodes',lambda s:[{'kind':'truth','point':(900,300)}])
    monkeypatch.setattr(labels,'heading_template',lambda:None)
    original=d.b.confirm_label
    def confirm(*a,**kw):
        calls.append(kw['scale'])
        return False if len(calls)<=2 else original(*a,**kw)
    monkeypatch.setattr(d.b,'confirm_label',confirm)
    d.verify_dungeon_resource=lambda *a,**k:None
    detail=d.tribe_totem_detail(initial)
    assert is_tribe_detail(detail) and calls==[3,4,3]
    assert clicks==[((900,300),'打开随机图腾详情')]
    assert d.report['tribe_totem']['name']=='真实图腾'


@pytest.mark.parametrize('error',[UserStopped('停止'),SessionUnavailable('设备不可用')])
def test_local_label_recovery_does_not_swallow_stop_or_device_failure(tmp_path,error):
    d=daily(tmp_path);d.b.tasker=SimpleNamespace(post_recognition=lambda *a:object())
    d.b.wait=lambda *a:(_ for _ in ()).throw(error)
    with pytest.raises(type(error)):recover_totem_heading(d.b,totem())
