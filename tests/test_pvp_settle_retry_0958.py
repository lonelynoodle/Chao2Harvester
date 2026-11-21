"""A sent settlement tap is not evidence that the client accepted it."""
import pytest

from chao2.backend import Screen,Word
from chao2.daily_challenges import pvp_settle_button,pvp_result
from chao2.policy import SafetyStop,UserStopped
from test_configuration import captured,daily,screen
from test_daily_challenges import origin_frame


def battle(*,button=True):
    words=[('00:01',600,5,80,30),('自动',90,600,50,30)]
    if button:words.append(('结算',161,599,52,31))
    return screen(*words)


def result():return captured('v0958-origin-result',True)


def setup(tmp_path,monkeypatch,task='origin'):
    d=daily(tmp_path);d.active_task=task;clock=[0.0];clicks=[]
    monkeypatch.setattr('chao2.daily_challenges.time.monotonic',lambda:clock[0])
    d.b.sleep=lambda seconds:clock.__setitem__(0,clock[0]+seconds)
    d.b.read_text_crop=lambda *a:''
    def click(s,p,anchors,reason):
        assert s.when==clock[0]
        clicks.append((clock[0],p,reason));d.b.sleep(2)
    d.b.click_at=click
    return d,clock,clicks


def frames(d,clock,sequence):
    iterator=iter(sequence)
    def observe():
        s=next(iterator);s.when=clock[0];return s
    d.observe=observe


@pytest.mark.parametrize('task',['origin','arena'])
def test_twelve_ignored_taps_are_retried_then_only_one_battle_is_counted(tmp_path,monkeypatch,task):
    d,clock,clicks=setup(tmp_path,monkeypatch,task);done=result()
    frames(d,clock,[battle() for _ in range(12)]+[done])
    assert d.pvp_battle(task)==(done,pvp_result(done))
    assert [(t,p) for t,p,_ in clicks]==[(n*2,(187,614)) for n in range(12)]
    assert d.battles==d.task_counts[task]==1
    assert d.report['pvp_settlements']==[{'task':task,'attempt':1,'clicks':12,'outcome':pvp_result(done)}]
    assert not d.report.get('team_attempts') and not d.report.get('resource_usage')


def test_disappeared_button_and_loading_frames_never_reuse_old_coordinates(tmp_path,monkeypatch):
    d,clock,clicks=setup(tmp_path,monkeypatch);done=result()
    frames(d,clock,[battle(),battle(),battle(button=False),screen(),battle(button=False),done])
    assert d.pvp_battle('origin')[0] is done
    assert len(clicks)==2 and clock[0]==10


def test_settlement_is_checked_before_button_text_left_in_result(tmp_path,monkeypatch):
    d,clock,clicks=setup(tmp_path,monkeypatch);done=result()
    done.words.extend(battle().words)
    frames(d,clock,[battle(),done])
    assert d.pvp_battle('origin')[0] is done and len(clicks)==1


@pytest.mark.parametrize('enabled,allowed',[(False,True),(True,False),(False,False)])
def test_disabled_auto_settle_and_unidentified_existing_fights_remain_observation_only(tmp_path,monkeypatch,enabled,allowed):
    d,clock,clicks=setup(tmp_path,monkeypatch);d.options['origin']['auto_settle']=enabled
    frames(d,clock,[battle(),battle(),result()])
    d.pvp_battle('origin',verify_origin=True,allow_settle=allowed)
    assert not clicks and d.report['pvp_settlements'][0]['clicks']==0


@pytest.mark.parametrize('overlay',['匹配','排阵','挑战','退出'])
def test_non_battle_controls_cannot_receive_settlement_taps(tmp_path,monkeypatch,overlay):
    d,clock,clicks=setup(tmp_path,monkeypatch);blocked=battle()
    blocked.words.append(Word(overlay,[900,400,80,35],.99))
    frames(d,clock,[battle(),blocked,result()])
    d.pvp_battle('origin')
    assert len(clicks)==1


def test_missing_timer_does_not_replay_settlement(tmp_path,monkeypatch):
    d,clock,clicks=setup(tmp_path,monkeypatch)
    unknown=screen(('结算',161,599,52,31),('自动',90,600,50,30))
    frames(d,clock,[battle(),unknown,result()]);d.pvp_battle('origin')
    assert len(clicks)==1


def test_crop_is_reread_after_each_partial_label_instead_of_latching_previous_read(tmp_path,monkeypatch):
    d,clock,clicks=setup(tmp_path,monkeypatch)
    partial=screen(('结',165,604,32,20),('自动',94,602,46,25),('00:10',601,6,77,28))
    later=screen(('结',165,604,32,20),('自动',94,602,46,25),('00:10',601,6,77,28))
    reads=iter(['结算','结']);d.b.read_text_crop=lambda *a:next(reads)
    frames(d,clock,[partial,later,result()]);d.pvp_battle('origin')
    assert len(clicks)==1


def test_user_stop_ends_repeated_taps_without_claiming_result(tmp_path,monkeypatch):
    d,clock,clicks=setup(tmp_path,monkeypatch)
    def observe():
        if len(clicks)==3:d.b.stop.set()
        s=battle();s.when=clock[0];return s
    d.observe=observe
    with pytest.raises(UserStopped):d.pvp_battle('origin')
    assert len(clicks)==3 and d.report['pvp_settlements'][0]['outcome'] is None
    assert d.task_counts['origin']==1 and not d.report.get('team_attempts')


def test_active_battle_keeps_waiting_after_old_timeout(tmp_path,monkeypatch):
    d,clock,clicks=setup(tmp_path,monkeypatch);d.b.settings['battle_timeout_seconds']=8
    done=result();frames(d,clock,[battle() for _ in range(12)]+[done])
    assert d.pvp_battle('origin')[0] is done
    assert len(clicks)==12 and clock[0]==24 and d.battles==1
    assert d.report['battle_wait_extensions']


def test_network_recovery_does_not_rematch_or_count_another_battle(tmp_path,monkeypatch):
    d,clock,clicks=setup(tmp_path,monkeypatch);network=[]
    retry=screen(('网络翻船中，是否重试?',490,299,283,26),('取消',454,480,55,32),('确定',769,481,56,31))
    d.b.click_text=lambda s,p,**kw:network.append(p)
    frames(d,clock,[battle(),retry,battle(),result()]);d.pvp_battle('origin')
    assert len(clicks)==2 and network==['^确定$'] and d.battles==1


def test_origin_free_quota_is_charged_once_after_multiple_settlement_taps(tmp_path,monkeypatch):
    d,clock,clicks=setup(tmp_path,monkeypatch);matching=[]
    monkeypatch.setattr('chao2.daily_challenges.origin_is_open',lambda:True)
    d.enter_building=lambda *a:origin_frame(1)
    d.select_team=lambda s,t,**kw:s
    d.b.click_text=lambda s,p,**kw:matching.append(p)
    d.exit_result=lambda s:None;d.await_page=lambda *a:origin_frame(0);d.home=lambda:None
    frames(d,clock,[battle(),battle(),battle(),result()])
    assert '已结算1场' in d.origin()
    assert matching==['^匹配$'] and len(clicks)==3
    assert d.task_counts['origin']==1 and len(d.report['team_attempts'])==1
    assert d.report['resource_usage']['origin']['免费次数']=={'start':1,'remaining':0,'spent':1,'unverified':0}


def test_actual_maa_reads_captured_early_battle_button_and_waits_for_real_result(tmp_path):
    from test_maa_recognition import Offline
    from maa.resource import Resource
    from maa.tasker import Tasker
    from maa.pipeline import JOCR
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle('resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    d=daily(tmp_path);d.b.tasker=t
    pages=[];points=[]
    for name in ('v0958-origin-before-settle','v0958-origin-settle-control'):
        original=captured(name,True)
        result_ocr=t.post_recognition('OCR',JOCR(roi=[0,0,1280,720],threshold=.5),original.image).wait().get()
        words=[Word(w.text,w.box,w.score) for n in result_ocr.nodes if n.recognition for w in n.recognition.all_results]
        actual=Screen(original.image,words,original.when)
        button=pvp_settle_button(actual,d.b.read_text_crop)
        assert button and 161<=button.center[0]<=213 and 599<=button.center[1]<=630
        points.append(button.center)
        assert pvp_result(actual) is None
        pages.append(actual)
    iterator=iter([*pages,result()]);d.observe=lambda:next(iterator);d.b.sleep=lambda _:None
    clicks=[];d.b.click_at=lambda s,p,*a:clicks.append(p)
    d.pvp_battle('origin')
    assert clicks==points and d.task_counts['origin']==1
