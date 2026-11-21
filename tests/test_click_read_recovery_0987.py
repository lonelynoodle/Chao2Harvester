"""Read-only native recovery and bounded same-control offset taps; no MuMu."""
import time
from types import SimpleNamespace
import pytest
from chao2.backend import Backend,Word
from chao2.control_retry import retry_point
from chao2.policy import NativeOperationTimeout,SessionUnavailable,IsolatedTaskError,TaskBlocked,UserStopped
from chao2.daily_challenges import rampage_buff
from chao2.team_copy import is_saved_team_list
from test_configuration import daily,screen,captured
from test_capture_recovery import reader
from test_rift_main_0959 import offline_backend


@pytest.mark.parametrize('box',[(20,20,100,32),(0,0,1,1),(1278,718,8,8),(-3,-3,10,10)])
def test_offsets_remain_inside_the_same_visible_control(box):
    word=Word('control',list(box),1.)
    for attempt in range(12):
        x,y=retry_point(word,attempt)
        assert max(0,box[0])<=x<min(1280,box[0]+box[2])
        assert max(0,box[1])<=y<min(720,box[1]+box[3])
        assert abs(x-word.center[0])<=4 and abs(y-word.center[1])<=4
    if box==(20,20,100,32):assert len({retry_point(word,i) for i in range(4)})==4


def test_invalid_button_cannot_authorize_an_offset():
    with pytest.raises(TaskBlocked):retry_point(Word('bad',[1300,20,50,30],1),1)


def test_late_finished_read_is_discarded_and_a_new_frame_is_captured(tmp_path):
    b,calls=reader([True,True]);logs=[];audit=[];b.log=logs.append;b.audit=audit.append
    jobs=[]
    def recognize(*a):
        job=SimpleNamespace(kind='ocr',get=lambda:SimpleNamespace(nodes=[SimpleNamespace(recognition=SimpleNamespace(
            all_results=[SimpleNamespace(text='new-frame',box=[20,20,100,30],score=.99)]))]))
        jobs.append(job);return job
    b.tasker.post_recognition=recognize
    def wait(job,*a):
        if getattr(job,'kind',None)=='ocr' and len(jobs)==1:
            raise NativeOperationTimeout('late OCR',settled=True)
        return job
    b.wait=wait
    s=b.observe(tmp_path/'frame.png')
    assert s.find('^new-frame$') and calls==['read','read']
    assert len(audit)==1 and audit[0]['stage']=='OCR' and logs
    assert (tmp_path/'frame.json').exists()


def test_unsettled_native_job_is_not_overlapped_or_replayed():
    b,calls=reader([True,True])
    b._observe_once=lambda *a:(_ for _ in ()).throw(NativeOperationTimeout('unfinished',settled=False))
    with pytest.raises(SessionUnavailable):b.observe()
    assert calls==[]


def test_three_drained_read_timeouts_skip_task_and_next_task_runs(tmp_path):
    d=daily(tmp_path);reads=[];d.b.sleep=lambda _:None
    world=screen(('任务挑战',1196,42,80,24),('世界回响',1196,138,80,24),('35/187',500,12,80,28))
    def read(*a):
        reads.append(1)
        if len(reads)<=3:raise NativeOperationTimeout('read stalled',settled=True)
        return world
    d.b._observe_once=read;d.tribe=lambda:d.b.observe()
    d.home=lambda:d.b.observe();d.rewards=lambda:'next completed'
    d.execute_task('tribe');d.execute_task('rewards')
    assert len(reads)==4
    assert d.report['tasks']['tribe']['status']=='blocked' and d.report['tasks']['rewards']['status']=='done'


def test_stop_during_timeout_cleanup_prevents_another_read():
    b,_=reader([True]);reads=[]
    def read(*a):
        reads.append(1);b.stop.set();raise NativeOperationTimeout('read',settled=True)
    b._observe_once=read
    with pytest.raises(UserStopped):b.observe()
    assert len(reads)==1


def test_input_timeout_is_never_automatically_replayed(tmp_path):
    b=Backend({});sent=[]
    b.controller=SimpleNamespace(post_click=lambda x,y:sent.append((x,y)) or object())
    b.wait=lambda *a:(_ for _ in ()).throw(NativeOperationTimeout('uncertain input',settled=True))
    with pytest.raises(SessionUnavailable):b.click_at(screen(('确定',750,450,100,35)),(800,467),['^确定$'],'input')
    assert sent==[(800,467)]


def test_native_wait_records_that_timeout_cleanup_really_finished(monkeypatch):
    b=Backend({});clock=[0.]
    monkeypatch.setattr('chao2.backend.time',SimpleNamespace(monotonic=lambda:clock[0]))
    job=SimpleNamespace(done=False);stopping=SimpleNamespace(done=True)
    def stop():job.done=True;return stopping
    b.tasker=SimpleNamespace(post_stop=stop,stopping=False)
    def wait(_):clock[0]+=2;return False
    b.stop=SimpleNamespace(wait=wait,is_set=lambda:False)
    with pytest.raises(NativeOperationTimeout) as error:b.wait(job,1)
    assert error.value.settled and job.done


def test_real_native_recognition_can_resume_after_a_completed_stop(offline_backend):
    s=captured('v0987-live-battle',True)
    assert offline_backend.tasker.post_stop().wait().succeeded
    assert not offline_backend.tasker.stopping
    assert offline_backend.read_text_crop(s,(590,0,100,45))=='08:06'


def formation():return screen(('部队',110,15,100,30),('空闲1',920,80,100,30))


def preset():
    return screen(('配置',570,30,140,35),('队伍1',320,110,70,30),
                  ('复制此配置',800,110,120,30))


@pytest.mark.parametrize('misses',[0,1,2,3])
def test_config_close_rechecks_and_offsets_until_window_disappears(tmp_path,misses):
    d=daily(tmp_path);state=[preset()];points=[]
    def click(s,p,a,r):
        assert is_saved_team_list(s) and s.has(*a);points.append(p)
        if len(points)>misses:state[0]=formation()
    d.b.click_at=click;d.observe=lambda:state[0];d.b.sleep=lambda _:None
    assert d.close_saved_team_list(state[0]).find('^部队$')
    assert len(points)==misses+1 and points[0]==(960,54)
    assert len(set(points))==len(points)


def test_config_close_stops_tapping_when_page_changes(tmp_path):
    d=daily(tmp_path);points=[];d.b.click_at=lambda s,p,a,r:points.append(p)
    unknown=screen(('other-page',400,300,100,30));d.observe=lambda:unknown
    assert d.close_saved_team_list(preset()) is unknown and len(points)==1


def test_config_close_is_bounded_when_all_four_inputs_are_ignored(tmp_path):
    d=daily(tmp_path);s=preset();points=[];d.observe=lambda:s
    d.b.click_at=lambda q,p,a,r:points.append(p)
    with pytest.raises(IsolatedTaskError):d.close_saved_team_list(s)
    assert len(points)==4


def copy_game(tmp_path,monkeypatch,required):
    import chao2.activities as activities
    d=daily(tmp_path);d.active_task='tribe';state={'page':formation(),'copies':0,'points':[]}
    d.observe=lambda:state['page'];d.b.sleep=lambda _:None
    d.b.read_text_crop=lambda *a:'';d.b.read_text_region=lambda *a:''
    monkeypatch.setattr(activities,'source_lineup',lambda *a:object())
    monkeypatch.setattr(activities,'copied_lineup',lambda *a:{'verified':state['copies']>=required})
    def click(s,p,a,r):
        assert s.has(*a)
        if r=='打开配置列表':state['page']=preset()
        elif r.startswith('复制保存的'):
            assert s.find('^队伍1$') and is_saved_team_list(s)
            state['copies']+=1;state['points'].append(p)
        elif r=='收起配置':state['page']=formation()
        else:pytest.fail(r)
    d.b.click_at=click
    return d,state


def test_same_preset_is_recopied_only_after_destination_lineup_mismatch(tmp_path,monkeypatch):
    d,state=copy_game(tmp_path,monkeypatch,2)
    assert d.apply_saved_team(state['page'],1).find('^部队$')
    assert state['copies']==2 and state['points']==[(860,125),(856,125)]
    assert [r['status'] for r in d.report['team_copy_checks']]==['retrying','verified']


def test_persistent_lineup_mismatch_cannot_repeat_copy_forever(tmp_path,monkeypatch):
    d,state=copy_game(tmp_path,monkeypatch,99)
    with pytest.raises(TaskBlocked,match='未确认'):d.apply_saved_team(state['page'],1)
    assert state['copies']==3 and len(set(state['points']))==3


def test_real_reported_config_modal_is_recognized_and_closed_with_offset_retry(tmp_path):
    d=daily(tmp_path);s=captured('v0987-config-close',True);state=[s];points=[]
    assert is_saved_team_list(s)
    def click(q,p,a,r):
        assert q.has(*a);points.append(p)
        if len(points)==2:state[0]=formation()
    d.b.click_at=click;d.observe=lambda:state[0]
    assert d.close_saved_team_list(s).find('^部队$') and points==[(960,54),(956,54)]


def buff():
    return screen(('请选择一个暴走增益',450,110,300,35),
                  ('怪兽攻击力提升10%',60,220,220,35),('点击选择',170,500,100,32),
                  ('怪兽生命提升10%',480,220,220,35),('点击选择',590,500,100,32),
                  ('怪兽体型提升10%',900,220,220,35),('点击选择',1010,500,100,32))


def test_buff_missed_clicks_are_reobserved_and_offset_in_same_card(tmp_path,monkeypatch):
    import chao2.navigation_retry as navigation
    d=daily(tmp_path);d.active_task='nest';state=[buff()];points=[];clock=[0]
    monkeypatch.setattr(navigation,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    d.b.sleep=lambda seconds:clock.__setitem__(0,clock[0]+seconds)
    d.observe=lambda:state[0]
    expected=rampage_buff(state[0],d.options['nest']['buff_priority'])[0]
    def click(s,p,a,r):
        assert s is state[0] and s.has(*a)
        assert expected.box[0]<=p[0]<expected.box[0]+expected.box[2]
        points.append(p)
        if len(points)==3:state[0]=screen(('08:06',600,5,78,33),('自动',94,604,44,23))
    d.b.click_at=click
    assert d.choose_rampage_buff(state[0]).find('^自动$')
    assert points==[retry_point(expected,n) for n in range(3)]
    assert d.report['rampage_buff_selections'][0]['status']=='advanced'


def test_new_buff_page_does_not_reuse_previous_card_offset(tmp_path):
    d=daily(tmp_path);s=buff();q=buff();q.words[1].text='怪兽攻击力提升20%'
    points=[];d.b.click_at=lambda s,p,a,r:points.append(p);d.observe=lambda:q
    assert d.choose_rampage_buff(s) is q and len(points)==1


def test_stop_after_buff_click_sends_no_second_input(tmp_path):
    d=daily(tmp_path);s=buff();points=[];d.observe=lambda:s
    def click(s,p,a,r):points.append(p);d.b.stop.set()
    d.b.click_at=click
    with pytest.raises(UserStopped):d.choose_rampage_buff(s)
    assert len(points)==1
