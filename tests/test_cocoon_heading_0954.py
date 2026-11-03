"""Real cocoon two-formation headings must work for entry and returning home."""
import time

import pytest
from maa.pipeline import JOCR
from maa.resource import Resource
from maa.tasker import Tasker

from chao2.activities import enemy_formation
from chao2.backend import ROOT, Screen, Word
from chao2.result_navigation import exit_destination
from chao2.workflows import is_world, world_overlay_present
from test_configuration import captured, daily
from test_cocoon_refresh import CocoonGame
from test_maa_recognition import Offline


@pytest.mark.parametrize('name',['v0954-cocoon-detail','v0954-cocoon-night'])
def test_actual_merged_heading_is_a_challenge_detail(tmp_path,name):
    s=captured(name,True);d=daily(tmp_path)
    assert not s.find('^敌方阵容$')
    assert enemy_formation(s).text=='敌方阵容Q1'
    assert d.ensure_detail(s) is s
    assert exit_destination(s)=='detail' and world_overlay_present(s) and not is_world(s)


@pytest.mark.parametrize('missing',['排阵','挑战','可获得奖励','通关录像'])
def test_merged_heading_requires_every_layout_anchor(missing):
    s=captured('v0954-cocoon-detail')
    s.words=[w for w in s.words if w.text!=missing]
    assert enemy_formation(s) is None


@pytest.mark.parametrize('text',['敌方阵容提示','敌方阵容ABC','敌方阵容Q9','敌方阵容Q123456789','敌方阵客Q1'])
def test_heading_does_not_accept_arbitrary_suffix_or_wrong_title(text):
    s=captured('v0954-cocoon-detail')
    s.find('敌方阵容').text=text
    assert enemy_formation(s) is None


@pytest.mark.parametrize('text',['获得奖励','退出','请选择'])
def test_covered_detail_is_not_accepted(text):
    s=captured('v0954-cocoon-detail')
    s.words.append(Word(text,[500,200,150,30],.99))
    assert enemy_formation(s) is None


def test_merged_heading_must_still_be_in_monster_detail_header():
    s=captured('v0954-cocoon-detail');s.find('敌方阵容').box=[100,300,154,27]
    assert enemy_formation(s) is None


@pytest.mark.parametrize('name',['v0954-cocoon-detail','v0954-cocoon-night'])
def test_home_exits_actual_detail_without_challenge_or_title_guess(tmp_path,name):
    d=daily(tmp_path);detail=captured(name,True);world=captured('other-initial-world',True)
    state=[detail];clicks=[];d.observe=lambda:state[0]
    def click(s,p,anchors,reason):
        assert s is detail and s.has(*anchors)
        clicks.append((p,anchors));state[0]=world
    d.b.click_at=click
    assert d.home() is world
    assert clicks==[((45,28),['^敌方阵容Q1$'])]
    assert d.battles==0 and not d.task_counts


def test_three_dailies_run_with_actual_merged_heading_and_spike_cost(tmp_path,monkeypatch):
    g=CocoonGame(tmp_path,monkeypatch,spikes=6,options={'refresh_tasks':False})
    original=g.observe
    def observe(*args):
        if g.page!='detail':return original(*args)
        s=captured('v0954-cocoon-detail')
        s.find('^6/16$').text=f'{g.spikes}/16'
        return s
    g.observe=observe;g.d.observe=observe
    result=g.d.cocoon()
    assert g.inputs==['lower_left','lower_middle','lower_right']
    assert g.spikes==3 and g.books==1 and '通关3次' in result
    assert g.d.task_counts['cocoon']==3 and g.d.report['cocoon_refreshes']==0


def test_real_maa_recognizes_both_cocoon_failure_images():
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    for name in ('v0954-cocoon-detail','v0954-cocoon-night'):
        im=captured(name,True).image
        result=t.post_recognition('OCR',JOCR(roi=[0,0,1280,720],threshold=.5),im).wait().get()
        words=[Word(v.text,list(v.box),v.score) for n in result.nodes if n.recognition
               for v in n.recognition.all_results if getattr(v,'text','') and v.score>=.5]
        s=Screen(im,words,time.monotonic())
        assert enemy_formation(s) and exit_destination(s)=='detail',s.text
