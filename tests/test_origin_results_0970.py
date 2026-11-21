"""Task-time origin scheduling and common PvP defeat overlays."""
import threading
from copy import deepcopy
import pytest
from chao2 import workflows as flow,daily_challenges as pvp
from chao2.activities import recover_main_detail,main_identity,is_main_detail
from chao2.battle_takeover import existing_result
from chao2.rift import rift_node
from test_configuration import daily,screen,captured
from test_rift_main_0959 import offline_backend


def failure():
    return screen(('斗技场积分',718,254,130,28),('2131(-27)',1010,254,130,28),
                  ('怪兽培育',620,435,90,28),('元核升级',755,435,90,28),
                  ('神灵升阶',890,435,90,28),('阵容调整',1020,435,90,28),
                  ('黑暗森林',1150,435,90,28),('退出',1149,582,56,29),
                  ('02:18',600,7,80,28),('自动',95,600,50,28))


def test_actual_arena_failure_without_ornate_title_is_recognized():
    s=captured('v0970-arena',True)
    assert not s.find('失败|败退')
    assert pvp.pvp_result(s)=='failed' and flow.is_failure(s)
    assert existing_result(s)=='failed'


@pytest.mark.parametrize('task',['origin','arena'])
def test_shared_failure_layout_returns_immediately_instead_of_waiting_four_minutes(tmp_path,task):
    d=daily(tmp_path);s=failure();d.active_task=task;d.observe=lambda:s
    d.b.click_at=lambda *a:pytest.fail('Do not click background battle controls through the result')
    result,outcome=d.pvp_battle(task)
    assert result is s and outcome=='failed' and d.task_counts[task]==1
    assert d.report['pvp_settlements'][0]['clicks']==0


def test_defeat_overlay_takes_precedence_over_victory_word_in_background_chat():
    s=failure();s.words+=screen(('胜利者',50,680,80,20)).words
    assert pvp.pvp_result(s)=='failed'


@pytest.mark.parametrize('change',['missing_exit','two_links','outside_overlay'])
def test_partial_or_unrelated_improvement_text_cannot_prove_defeat(change):
    s=failure()
    if change=='missing_exit':s.words=[w for w in s.words if w.text!='退出']
    if change=='two_links':s.words=[w for w in s.words if w.text not in ('神灵升阶','阵容调整','黑暗森林')]
    if change=='outside_overlay':
        for w in s.words:
            if '升级' in w.text or w.text in ('怪兽培育','神灵升阶','阵容调整','黑暗森林'):w.box[1]=660
    assert pvp.pvp_result(s) is None


def test_main_badge_and_missing_enemy_heading_are_both_confirmed_from_actual_image(offline_backend):
    s=captured('v0970-main',True)
    assert main_identity(s) is None and not is_main_detail(s)
    fixed=recover_main_detail(offline_backend,s)
    assert main_identity(fixed)=='772' and is_main_detail(fixed) and fixed.when==s.when
    assert main_identity(s) is None


def test_incomplete_main_frame_cannot_gain_unverified_heading(tmp_path):
    d=daily(tmp_path);d.b.tasker=object()
    d.b.confirm_label=lambda *a,**kw:pytest.fail('Not enough detail anchors')
    s=screen(('通关录像',560,130,120,30),('排阵',810,610,80,30))
    assert recover_main_detail(d.b,s) is s


def test_actual_glowing34_uses_low_confidence_box_only_for_two_high_confidence_reads(offline_backend):
    s=captured('v0970-rift',True);label=s.find('^34$')
    assert .5<label.score<.8
    found=rift_node(offline_backend,s,34)
    assert found[0]=='next' and abs(found[1][0]-519)<5


@pytest.mark.parametrize('reads',[('34','3'),('34_','34_'),('','')])
def test_low_confidence_rift_box_still_requires_two_complete_matching_local_numbers(offline_backend,reads,monkeypatch):
    s=captured('v0970-rift',True);count=[0]
    def read(*args):
        value=reads[count[0]%2];count[0]+=1;return value
    monkeypatch.setattr(offline_backend,'read_text_crop',read)
    assert rift_node(offline_backend,s,34) is None


@pytest.mark.parametrize('initial_open,at_task_open',[(False,True),(True,False)])
def test_origin_is_checked_after_preceding_task_not_when_queue_starts(tmp_path,monkeypatch,initial_open,at_task_open):
    world=screen();clock={'open':initial_open};calls=[]
    monkeypatch.setattr(flow,'create_report',lambda:{'folder':tmp_path,'tasks':{},'events':[]})
    monkeypatch.setattr(flow,'origin_is_open',lambda:pytest.fail('No startup time check'))
    monkeypatch.setattr(pvp,'origin_is_open',lambda:calls.append(clock['open']) or clock['open'])
    monkeypatch.setattr(flow.Backend,'connect',lambda self:None)
    monkeypatch.setattr(flow.Daily,'home',lambda self,*a,**kw:world)
    monkeypatch.setattr(flow.Daily,'world_resources',lambda *a:{'stamina':20,'stamina_cap':100,'diamonds':100,'gold_text':'100'})
    monkeypatch.setattr(flow.Daily,'maybe_capture_wild',lambda self,s:s)
    monkeypatch.setattr(flow.Daily,'maybe_free_summon',lambda self,s:s)
    monkeypatch.setattr(flow.Daily,'save_state',lambda self:None)
    def preceding(self):clock['open']=at_task_open;return '前序任务完成'
    monkeypatch.setattr(flow.Daily,'exploration',preceding)
    navigated=[]
    monkeypatch.setattr(flow.Daily,'enter_building',lambda self,*a:navigated.append('origin') or world)
    monkeypatch.setattr(flow.Daily,'await_pvp_quota',lambda self,s,*a:(s,0))
    r=flow.run_daily({'unordered_tasks':False,'free_summon_enabled':False},['exploration','origin'],threading.Event(),log=lambda _:None)
    assert calls==[at_task_open]
    assert navigated==(['origin'] if at_task_open else [])
    assert r['tasks']['origin']['status']==('done' if at_task_open else 'skipped')
