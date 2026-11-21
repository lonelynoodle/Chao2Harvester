"""Replay the cocoon material and main 1065 failures without game input."""
from copy import deepcopy
from types import SimpleNamespace
import time

import pytest

from chao2.activities import enemy_formation,is_main_detail,main_identity,recover_main_detail
from chao2.backend import Screen,Word
from chao2.dungeon_labels import cocoon_detail_layout,recover_cocoon_heading
from chao2.policy import SessionUnavailable,TaskBlocked,UserStopped
from test_configuration import captured,daily,screen
from test_rift_main_0959 import offline_backend


def material():
    return screen(('地原石',149,136,87,29),('轮回',398,138,44,23),
                  ('~通关录像',568,137,114,23),('可获得奖励',42,565,88,18),
                  ('排阵',824,614,60,35),('挑战',1061,604,57,32),
                  ('剩余次数:5/5',1025,559,132,23),('2/17',1217,15,45,26))


def main():
    return screen(('1065',38,141,80,33),('狞笑之',117,132,92,36),
                  ('o通关录像',569,135,113,25),('首通奖励',40,565,70,18),
                  ('排阵',825,615,57,32),('前往挑战',1036,604,110,32))


@pytest.mark.parametrize('name,recover',[('cocoon',recover_cocoon_heading),('main',recover_main_detail)])
def test_actual_failure_recovers_missing_heading_without_changing_source(offline_backend,name,recover):
    s=captured('v0990-'+name,True);original=deepcopy(s.words)
    assert not enemy_formation(s)
    q=recover(offline_backend,s)
    assert enemy_formation(q) and q.image is s.image and q.when==s.when
    assert s.words==original
    if name=='main':assert is_main_detail(q) and main_identity(q)=='1065'
    else:assert cocoon_detail_layout(q) and q.find('^剩余次数:5/5$')


@pytest.mark.parametrize('name,recover',[('cocoon',recover_cocoon_heading),('main',recover_main_detail)])
def test_unverified_background_pixels_cannot_supply_a_heading_if_ocr_misses(tmp_path,monkeypatch,name,recover):
    d=daily(tmp_path);d.b.tasker=object();calls=[]
    monkeypatch.setattr(d.b,'confirm_label',lambda *a,**kw:calls.append(kw['scale']) or False)
    monkeypatch.setattr(d.b,'read_text_crop',lambda *a:pytest.fail('Missing heading must prevent badge calibration'))
    # The existing template has a different background. Its low scores on
    # these frames must not become a substitute for actual local OCR.
    source=captured('v0990-'+name,True);q=recover(d.b,source)
    assert q is source and not enemy_formation(q) and calls==[3,4]


@pytest.mark.parametrize('missing',['排阵','挑战','可获得奖励','~通关录像','剩余次数:5/5'])
def test_cocoon_recovery_requires_its_fixed_detail_controls(tmp_path,missing):
    d=daily(tmp_path);d.b.tasker=object();s=material()
    s.words=[w for w in s.words if w.text!=missing]
    d.b.confirm_label=lambda *a,**kw:pytest.fail('Incomplete detail must not read a background heading')
    assert not cocoon_detail_layout(s) and recover_cocoon_heading(d.b,s) is s


@pytest.mark.parametrize('make,recover',[(material,recover_cocoon_heading),(main,recover_main_detail)])
@pytest.mark.parametrize('overlay',['退出','获得奖励','取消','确定','复制此配置','请选择'])
def test_heading_recovery_does_not_read_through_a_modal(tmp_path,make,recover,overlay):
    d=daily(tmp_path);d.b.tasker=object();s=make()
    s.words.append(Word(overlay,[450,300,150,35],.99))
    d.b.confirm_label=lambda *a,**kw:pytest.fail('Modal must block local recovery')
    assert recover(d.b,s) is s and not enemy_formation(s)


@pytest.mark.parametrize('replay',['通关录像提示','其他通关录像','abc通关录像','o通关录像abc'])
def test_main_camera_prefix_does_not_accept_arbitrary_text(tmp_path,replay):
    d=daily(tmp_path);d.b.tasker=object();s=main();s.words[2].text=replay
    d.b.confirm_label=lambda *a,**kw:pytest.fail('Wrong replay label must not authorize recovery')
    assert recover_main_detail(d.b,s) is s


@pytest.mark.parametrize('make,recover',[(material,recover_cocoon_heading),(main,recover_main_detail)])
def test_replay_link_must_be_in_its_fixed_slot(tmp_path,make,recover):
    d=daily(tmp_path);d.b.tasker=object();s=make()
    s.find('通关录像').box=[400,300,140,30]
    d.b.confirm_label=lambda *a,**kw:pytest.fail('Wrong-position replay is insufficient')
    assert recover(d.b,s) is s


def test_cocoon_card_enters_actual_material_detail_via_real_observation_once(tmp_path,monkeypatch,offline_backend):
    d=daily(tmp_path);d.b=offline_backend;d.active_task='cocoon'
    raw=captured('v0990-cocoon',True);clicks=[]
    menu=screen(('永生之茧',120,15,120,30),('刷新',612,496,54,33))
    monkeypatch.setattr(d.b,'observe',lambda *a:Screen(raw.image,list(raw.words),time.monotonic()))
    monkeypatch.setattr(d.b,'click_at',lambda s,p,anchors,reason:clicks.append((p,reason)) if s.has(*anchors) else pytest.fail('Wrong page'))
    monkeypatch.setattr(d.b,'sleep',lambda _:None)
    q=d.cocoon_open_card(menu,'stone','一地原石')
    assert enemy_formation(q) and clicks==[((1110,433),'进入一地原石')]
    assert d.battles==0 and not d.report.get('team_attempts')


def test_main_stability_accepts_actual1065_through_real_observation(tmp_path,monkeypatch,offline_backend):
    d=daily(tmp_path);d.b=offline_backend;d.active_task='main';raw=captured('v0990-main',True);reads=[]
    def observe(*a):
        reads.append(1);return Screen(raw.image,list(raw.words),time.monotonic())
    monkeypatch.setattr(d.b,'observe',observe);monkeypatch.setattr(d.b,'sleep',lambda _:None)
    monkeypatch.setattr(d.b,'click_at',lambda *a,**kw:pytest.fail('Recognizing an open detail needs no click'))
    q=d.stable_main_detail(d.observe(),'1065','after-team')
    assert is_main_detail(q) and main_identity(q)=='1065' and len(reads)==2
    assert d.report['main_identity_checks'][0]['readings']==['1065','1065']
    assert d.battles==0


def test_open_but_unconfirmed_cocoon_detail_does_not_reclick_menu_coordinates(tmp_path):
    d=daily(tmp_path);d.b.tasker=object();s=material();calls=[];reads=[]
    menu=screen(('永生之茧',120,15,120,30),('刷新',612,496,54,33))
    d.observe=lambda:reads.append(1) or s;d.b.sleep=lambda _:None
    d.b.click_at=lambda *a:calls.append(a[1])
    with pytest.raises(TaskBlocked,match='已打开.*局部补读4次仍未确认'):
        d.cocoon_open_card(menu,'stone','一地原石')
    assert calls==[(1110,433)] and len(reads)==4 and d.battles==0
    assert not d.report.get('cocoon_counts') and not d.report.get('cocoon_unavailable')


@pytest.mark.parametrize('recover,make',[(recover_cocoon_heading,material),(recover_main_detail,main)])
@pytest.mark.parametrize('error',[UserStopped('用户停止'),SessionUnavailable('设备不可用')])
def test_local_heading_recovery_propagates_real_stop_and_device_failure(tmp_path,recover,make,error):
    d=daily(tmp_path);d.b.tasker=SimpleNamespace(post_recognition=lambda *a:object())
    d.b.wait=lambda *a:(_ for _ in ()).throw(error)
    with pytest.raises(type(error)):recover(d.b,make())
