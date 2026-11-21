"""Unlocked portals after merchant rewards and battle exits; no live input."""
import pytest
from chao2.backend import Word
from chao2.plane_gate import (plane_gate_window,plane_gate_close,gate_close_template,
    recover_plane_gate_labels,GATE_TITLE,GATE_TITLE_ROI,GATE_ENTRY_ROI)
from chao2.merchant import merchant_return_page,merchant_battle_phase
from chao2.result_navigation import exit_destination
from chao2.workflows import is_world,world_overlay_present
from chao2.policy import EncounterInterrupted,TaskBlocked,UserStopped
from test_configuration import daily,screen,captured


def world():
    return screen(('事件',1100,630,60,30),('领地',1200,630,60,30),('39/187',500,15,80,30))


def portal(*,locked=False,icon=True):
    s=screen(('崩坠之门',234,80,128,32),('进入',606,443,58,32))
    s.words.extend(world().words)
    if locked:s.words.append(Word('解锁条件:世界总探索度到达125%',[502,173,316,22],.99))
    if icon:
        template=gate_close_template();assert template is not None
        h,w=template.shape[:2];s.image[60:60+h,1018:1018+w]=template
    return s


def merchant_reward():
    return screen(('神秘商人',20,20,180,40),('获得奖励',500,120,200,40),
                  ('点击空白位置关闭',450,620,380,40))


@pytest.mark.parametrize('locked',[False,True])
def test_both_gate_layouts_are_overlays_and_post_event_destinations(locked):
    s=portal(locked=locked)
    assert plane_gate_window(s) and plane_gate_close(s)
    assert world_overlay_present(s) and not is_world(s)
    assert merchant_return_page(s)=='plane_gate'
    assert merchant_battle_phase(s) is None
    assert exit_destination(s)=='plane_gate'


@pytest.mark.parametrize('missing',['title','entry','icon'])
def test_unlocked_layout_needs_title_entry_and_real_x(missing):
    s=portal(icon=missing!='icon')
    if missing=='title':s.words=[w for w in s.words if w.text!='崩坠之门']
    if missing=='entry':s.words=[w for w in s.words if w.text!='进入']
    assert plane_gate_window(s) is None and plane_gate_close(s) is None


@pytest.mark.parametrize('modal',['取消','确定','购买','获得奖励','退出','排阵'])
def test_other_modal_controls_still_prevent_gate_classification(modal):
    s=portal();s.words.append(Word(modal,[600,350,80,40],.99))
    assert plane_gate_window(s) is None and plane_gate_close(s) is None


def test_unlocked_layout_does_not_accept_an_unreadable_locked_button():
    s=portal();next(w for w in s.words if w.text=='进入').text='未解锁'
    assert plane_gate_window(s) is None
    s.words.append(Word('解锁条件:世界总探索度到达125%',[502,173,316,22],.99))
    assert plane_gate_window(s)


@pytest.mark.parametrize('missing',['title','entry','both'])
def test_gate_own_crops_recover_missing_full_frame_captions(tmp_path,missing):
    d=daily(tmp_path);s=portal();d.b.tasker=object();reads=[]
    s.words=[w for w in s.words if not ((missing in ('title','both') and w.text=='崩坠之门') or
                                        (missing in ('entry','both') and w.text=='进入'))]
    def confirm(q,p,roi,**kw):
        reads.append((p,roi,kw))
        if p==GATE_TITLE:q.words.append(Word('崩坠之门',[234,80,128,32],.99))
        elif roi==GATE_ENTRY_ROI:q.words.append(Word('进入',[606,443,58,32],.99))
    d.b.confirm_label=confirm
    q=recover_plane_gate_labels(d.b,s)
    assert plane_gate_window(q) and not plane_gate_window(s)
    assert reads and all(kw=={'scale':3,'threshold':.8} for _,_,kw in reads)
    assert set(roi for _,roi,_ in reads)<={GATE_TITLE_ROI,GATE_ENTRY_ROI}


def test_local_gate_reads_are_bounded_and_not_attempted_without_icon(tmp_path):
    d=daily(tmp_path);d.b.tasker=object();calls=[]
    d.b.confirm_label=lambda *a,**kw:calls.append(kw['scale'])
    blank=screen();assert recover_plane_gate_labels(d.b,blank) is blank and not calls
    partial=portal();partial.words=[]
    assert recover_plane_gate_labels(d.b,partial) is partial
    assert calls==[3,4]*3


def setup(tmp_path,*,real=False):
    d=daily(tmp_path);d.active_task='main'
    state=[captured('v0981-merchant-reward',True) if real else merchant_reward()];clicks=[]
    gate=captured('v0981-portal-unlocked',True) if real else portal()
    dest=world();close=plane_gate_close(gate).center
    d.b.sleep=lambda _:None;d.observe=lambda:state[0]
    def click(q,p,anchors,reason,**kw):
        if q is state[0] and q is gate and p==close:state[0]=dest
        elif q is state[0] and p==(640,660):state[0]=gate
        else:pytest.fail('Only reward close and the verified portal X are allowed: '+str((p,reason)))
        clicks.append((p,reason))
    d.b.click_at=click
    return d,state,gate,dest,clicks


@pytest.mark.parametrize('real',[False,True])
def test_merchant_reward_hands_off_to_portal_then_home_closes_once(tmp_path,real):
    d,state,gate,dest,clicks=setup(tmp_path,real=real)
    returned=d.handle_merchant(state[0])
    row=d.report['merchant_events'][0]
    assert returned is gate and row['status']=='completed' and row['returned_to']=='plane_gate'
    assert row['rewards_closed']==1 and row['rewards'][0]['status']=='closed'
    assert row['purchases']==0 and len(clicks)==1
    assert d.home(returned) is dest
    assert len(clicks)==2 and clicks[-1][0]==plane_gate_close(gate).center
    assert d.battles==0 and d.task_counts=={}
    assert not d.report.get('merchant_diamond_spend')


def test_merchant_to_portal_interrupt_skips_task_without_repeating_reward(tmp_path):
    d,state,gate,dest,clicks=setup(tmp_path);runs=[]
    def main():
        runs.append('main')
        if len(runs)==1:d.resolve_path_event(state[0])
        return '原任务已继续'
    d.main=main;d.rewards=lambda:'后续领奖已检查'
    d.execute_task('main');d.execute_task('rewards')
    assert runs==['main'] and len(clicks)==2
    assert d.report['tasks']['main']['status']=='blocked'
    assert d.report['tasks']['rewards']['status']=='done'
    assert len(d.report['merchant_events'])==1 and d.report['plane_gates'][0]['status']=='closed'


@pytest.mark.parametrize('locked',[False,True])
def test_battle_exit_recognizes_gate_and_does_not_wait_out_unknown_page_budget(tmp_path,locked):
    d=daily(tmp_path);d.active_task='main';gate=portal(locked=locked);dest=world();state=[gate];clicks=[]
    result=screen(('胜利',100,250,100,60),('退出',50,640,90,40))
    d.b.sleep=lambda _:None;d.observe=lambda:state[0]
    d.b.click_text=lambda q,p:clicks.append(p)
    assert d.exit_result(result) is gate
    assert d.report['result_exits'][0]['destination']=='plane_gate'
    assert d.report['result_exits'][0]['status']=='left' and clicks==['^退出$']
    def close(q,p,*a):
        assert p==plane_gate_close(gate).center
        clicks.append('X');state[0]=dest
    d.b.click_at=close
    assert d.home(gate) is dest and clicks==['^退出$','X']


def test_repeated_portal_interruptions_skip_source_task_and_continue_later_task(tmp_path):
    d,state,gate,dest,clicks=setup(tmp_path);runs=[]
    def main():
        runs.append('main');state[0]=gate;d.resolve_path_event(gate)
    d.main=main;d.rewards=lambda:'已继续后续任务'
    d.execute_task('main');d.execute_task('rewards')
    assert len(runs)==1 and len(clicks)==1
    assert d.report['tasks']['main']['status']=='blocked'
    assert d.report['tasks']['rewards']['status']=='done'
    assert all(row['status']=='closed' for row in d.report['plane_gates'])
    assert d.battles==0 and d.task_counts=={}


def test_unlocked_portal_close_retry_stays_bounded_and_obeys_stop(tmp_path):
    d=daily(tmp_path);gate=portal();clicks=[]
    d.observe=lambda:gate;d.b.sleep=lambda _:None;d.b.click_at=lambda *a:clicks.append(a[1])
    with pytest.raises(TaskBlocked,match='重试3次'):d.close_plane_gate(gate)
    assert clicks==[plane_gate_close(gate).center]*4
    clicks.clear();d.b.stop.set()
    with pytest.raises(UserStopped):d.close_plane_gate(gate)
    assert not clicks


@pytest.mark.parametrize('name',['unlocked','locked'])
def test_this_run_real_portal_screens_are_classified(name):
    s=captured('v0981-portal-'+name,True)
    assert plane_gate_window(s) and plane_gate_close(s)
    assert not is_world(s) and merchant_return_page(s)=='plane_gate'
    assert exit_destination(s)=='plane_gate'


def test_real_unlocked_gate_local_ocr_when_all_own_text_is_missing():
    from maa.resource import Resource
    from maa.tasker import Tasker
    from test_maa_recognition import Offline
    from chao2.backend import Backend,ROOT
    s=captured('v0981-portal-unlocked',True);s.words=[]
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({},log=lambda _:None);b.tasker=t;b.controller=c
    q=recover_plane_gate_labels(b,s)
    assert plane_gate_window(q) and plane_gate_window(q)[0].text=='崩坠之门'
    assert plane_gate_close(q)
