"""A real forest challenge detail must not cause three pointless map reentries."""
from copy import deepcopy
import time
import pytest
from chao2.backend import Screen
from chao2.dungeon_labels import recover_forest_heading
from chao2.forest import forest_detail
from chao2.policy import TaskBlocked
from test_configuration import daily,screen,captured
from test_rift_main_0959 import offline_backend


@pytest.mark.parametrize('name',['v0992-forest-detail','v0992-forest-duck'])
def test_real_truncated_forest_heading_recovers_locally(offline_backend,name):
    s=captured(name,True);original=deepcopy(s.words)
    assert forest_detail(s) is None
    q=recover_forest_heading(offline_backend,s)
    assert forest_detail(q)=='究极凶兽' and q.when==s.when and q.image is s.image
    assert s.words==original


@pytest.mark.parametrize('missing',['究极凶兽','排阵','挑战','可获得奖励'])
def test_incomplete_or_other_detail_cannot_gain_forest_heading(tmp_path,missing):
    d=daily(tmp_path);d.b.tasker=object();s=captured('v0992-forest-detail')
    s.words=[w for w in s.words if w.text!=missing]
    d.b.confirm_label=lambda *a,**kw:pytest.fail('Unknown detail must not read a background heading')
    assert recover_forest_heading(d.b,s) is s


@pytest.mark.parametrize('overlay',['获得奖励','退出','复制此配置','取消'])
def test_modal_blocks_forest_detail_recovery(tmp_path,overlay):
    d=daily(tmp_path);d.b.tasker=object();s=captured('v0992-forest-detail')
    s.words+=screen((overlay,450,300,180,35)).words
    d.b.confirm_label=lambda *a,**kw:pytest.fail('Covered detail')
    assert recover_forest_heading(d.b,s) is s


def test_real_observation_chain_accepts_open_detail_without_click_or_reentry(tmp_path,monkeypatch,offline_backend):
    d=daily(tmp_path);d.b=offline_backend;d.active_task='forest';raw=captured('v0992-forest-duck',True);reads=[]
    def observe(*a):
        reads.append(1);return Screen(raw.image,list(raw.words),time.monotonic())
    monkeypatch.setattr(d.b,'observe',observe)
    monkeypatch.setattr(d.b,'click_at',lambda *a,**kw:pytest.fail('Detail already open'))
    assert forest_detail(d.forest_wait_detail('究极凶兽'))=='究极凶兽'
    assert len(reads)==1 and not d.report.get('forest_simple_recoveries')
    assert not d.report.get('forest_detail_failures') and d.battles==0


def test_unrecognized_detail_is_saved_before_reentry_overwrites_latest(tmp_path):
    d=daily(tmp_path);s=captured('v0992-forest-detail');d.observe=lambda:s;d.b.sleep=lambda _:None
    with pytest.raises(TaskBlocked,match='森林节点详情未识别'):d.forest_wait_detail()
    row=d.report['forest_detail_failures'][0]
    assert row['screenshot']==str(tmp_path/'forest-detail-unrecognized-1.png')
    assert (tmp_path/'forest-detail-unrecognized-1.png').is_file()
    assert (tmp_path/'forest-detail-unrecognized-1.json').is_file()
