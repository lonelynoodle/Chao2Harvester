"""Replay storage missing 钻 and the swallowed close of an empty abyss menu."""
from copy import deepcopy
import time
import pytest
from chao2.backend import Screen
from chao2.abyss import AbyssPlayer
from chao2.piggy_bank import is_piggy_page,recover_piggy_storage,read_piggy_view
from test_configuration import daily,screen,captured
from test_rift_main_0959 import offline_backend
from test_task_interruptions_0985 import world


def test_real_storage_crops_recover_missing_diamond_character(offline_backend):
    s=captured('v0992-piggy',True);original=deepcopy(s.words)
    assert not is_piggy_page(s)
    q=recover_piggy_storage(offline_backend,s)
    assert is_piggy_page(q) and q.image is s.image and q.when==s.when and s.words==original
    assert read_piggy_view(offline_backend,q)=={'stored':50,'gold':50000,'stock':0,'quantity':1}


@pytest.mark.parametrize('reads',[
    ('已储存50钻石和50000金币','已储存200钻石和200000金币'),
    ('已储存200钻石和200000金币',)*2,
    ('已储存50钻石和5000金币',)*2,
    ('已储存50石和50000金币',)*2])
def test_storage_crops_cannot_guess_or_override_readable_amount(tmp_path,reads):
    d=daily(tmp_path);d.b.tasker=object();s=captured('v0992-piggy');answers=iter(reads)
    d.b.read_text_crop=lambda *a:next(answers)
    assert recover_piggy_storage(d.b,s) is s and not is_piggy_page(s)


@pytest.mark.parametrize('missing',['活动','电扑满','每次领取奖励消耗200活跃之星','1钻石和1000金币'])
def test_unverified_piggy_layout_cannot_recover_storage(tmp_path,missing):
    d=daily(tmp_path);d.b.tasker=object();s=captured('v0992-piggy')
    s.words=[w for w in s.words if w.text!=missing]
    d.b.read_text_crop=lambda *a:pytest.fail('Unknown page')
    assert recover_piggy_storage(d.b,s) is s


def test_real_low_storage_is_skipped_without_opening_purchase(tmp_path,monkeypatch,offline_backend):
    d=daily(tmp_path,{'task_options':{'other':{'piggy_bank':True}}});d.b=offline_backend
    raw=captured('v0992-piggy',True)
    monkeypatch.setattr(d.b,'observe',lambda *a:Screen(raw.image,list(raw.words),time.monotonic()))
    monkeypatch.setattr(d.b,'click_at',lambda *a,**kw:pytest.fail('50 stored is below 200'))
    monkeypatch.setattr(d.b,'click_text',lambda *a,**kw:pytest.fail('No purchase or claim'))
    d.piggy_wallet=lambda:6654;d.activity_tab=lambda _:d.observe()
    result=d.collect_piggy_bank()
    assert result['status']=='skipped' and result['stored']==50 and result['spent']==0 and result['claimed']==0
    assert not d.state.get('piggy_pending')


def test_abyss_finish_retries_current_panel_and_accepts_already_closed_world(tmp_path):
    d=daily(tmp_path);player=AbyssPlayer(d.b,d.report);raw=captured('v0992-abyss-close',True)
    state=[raw];points=[];player.observe=lambda *a,**kw:state[0]
    player.b.sleep=lambda _:None;player.world_resources=lambda s:{'stamina':2,'stamina_cap':191}
    def click(s,p,a,r):
        assert s is raw and s.has(*a)
        points.append(p)
        if len(points)==2:state[0]=world()
    player.b.click_at=click
    player.finish_world()
    assert points==[(770,680)]*2 and player.report['resources_end']['stamina']==2
    player.finish_world()
    assert len(points)==2
