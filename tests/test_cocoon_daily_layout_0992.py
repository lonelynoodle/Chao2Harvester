"""Daily cocoon encounters shift their formation heading left of numbered tabs."""
from copy import deepcopy
import time
import pytest
from chao2.activities import enemy_formation
from chao2.backend import Screen
from chao2.dungeon_labels import cocoon_daily_detail_layout,recover_cocoon_heading
from test_configuration import daily,screen,captured
from test_rift_main_0959 import offline_backend


def test_actual_daily_heading_recovers_in_left_crop_without_material_quota(offline_backend):
    s=captured('v0992-cocoon-daily',True);original=deepcopy(s.words)
    assert not enemy_formation(s) and not s.find('剩余次数') and cocoon_daily_detail_layout(s)
    q=recover_cocoon_heading(offline_backend,s)
    assert enemy_formation(q) and enemy_formation(q).center[0]<1140
    assert q.image is s.image and q.when==s.when and s.words==original
    assert q.find('^1/17$') and not q.find('剩余次数')


@pytest.mark.parametrize('missing',['title','好友助战','1/17','排阵','挑战','可获得奖励','通关录像'])
def test_daily_variant_needs_its_own_layout_anchors(tmp_path,missing):
    d=daily(tmp_path);d.b.tasker=object();s=captured('v0992-cocoon-daily')
    name='火海一条龙服务' if missing=='title' else missing
    s.words=[w for w in s.words if w.text!=name]
    d.b.confirm_label=lambda *a,**kw:pytest.fail('Partial daily layout cannot authorize a heading')
    assert not cocoon_daily_detail_layout(s) and recover_cocoon_heading(d.b,s) is s


@pytest.mark.parametrize('overlay',['获得奖励','取消','复制此配置'])
def test_daily_variant_does_not_recover_through_overlay(tmp_path,overlay):
    d=daily(tmp_path);d.b.tasker=object();s=captured('v0992-cocoon-daily')
    s.words+=screen((overlay,450,300,200,35)).words
    d.b.confirm_label=lambda *a,**kw:pytest.fail('Covered heading')
    assert recover_cocoon_heading(d.b,s) is s


def test_daily_card_waits_for_fresh_local_read_without_reclicking(tmp_path,monkeypatch,offline_backend):
    import chao2.dungeon_labels as labels
    d=daily(tmp_path);d.b=offline_backend;d.active_task='cocoon'
    raw=captured('v0992-cocoon-daily',True);calls=[];points=[]
    menu=screen(('永生之茧',120,15,120,30),('刷新',612,496,54,33))
    monkeypatch.setattr(d.b,'observe',lambda *a:Screen(raw.image,list(raw.words),time.monotonic()))
    monkeypatch.setattr(d.b,'click_at',lambda s,p,a,r:points.append(p))
    monkeypatch.setattr(d.b,'sleep',lambda _:None)
    monkeypatch.setattr(labels,'heading_template',lambda:None)
    original=d.b.confirm_label
    def confirm(*a,**kw):
        calls.append((a[2],kw['scale']))
        return False if len(calls)<=2 else original(*a,**kw)
    monkeypatch.setattr(d.b,'confirm_label',confirm)
    q=d.cocoon_open_card(menu,'lower_middle','每日任务·中')
    assert enemy_formation(q) and points==[(640,635)]
    assert calls==[((1010,115,140,70),3),((1010,115,140,70),4),((1010,115,140,70),3)]
    assert d.battles==0
