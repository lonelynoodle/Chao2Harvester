"""Captured live triad entry, quota, three-round HUD and result navigation."""
from datetime import datetime,timezone,timedelta

import pytest

from chao2.backend import Word
from chao2.event_hub import activity_entry,is_event_hub
from chao2.policy import TaskBlocked
from chao2.result_navigation import exit_destination
from chao2.triad import (triad_quota,triad_hud_round,triad_round,is_triad_battle,
                        triad_is_open,triad_settle_button,triad_result)
from test_configuration import captured,daily,screen
from test_triad import lobby,result


def test_partial_triad_title_on_actual_hub_opens_correct_entry(tmp_path):
    hub=captured('v0942-triad-hub',True);ready=captured('v0942-triad-lobby',True)
    assert is_event_hub(hub) and activity_entry(hub,'triad') is None
    d=daily(tmp_path);d.observe=lambda:hub;d.event_hub=lambda s:s
    d.wait_for_screen=lambda *a,**kw:ready;clicks=[]
    def click(s,point,anchors,reason):
        assert s.has(*anchors);clicks.append((point,reason))
    d.b.click_at=click
    assert d.triad_lobby() is ready
    assert clicks==[(hub.find('^阵入局$').center,'进入三阵入局')]
    assert d.report['triad_availability']=={'status':'open','entry':'阵入局'}


def test_missing_title_is_rechecked_without_claiming_event_ended(tmp_path):
    d=daily(tmp_path);hub=captured('v0942-triad-hub',True)
    hub.words=[w for w in hub.words if w.text!='阵入局']
    d.observe=lambda:hub;d.event_hub=lambda s:s;d.b.sleep=lambda _:None
    d.b.click_at=lambda *a:pytest.fail('No confirmed entry')
    assert '重新观察4次仍未识别' in d.triad()
    assert d.report['triad_availability']['status']=='not_visible'
    assert len(d.report['navigation_retries'])==3


def test_partial_title_requires_unique_confirmed_hub(tmp_path):
    d=daily(tmp_path);d.b.sleep=lambda _:None
    fake=screen(('阵入局',981,546,100,36))
    with pytest.raises(TaskBlocked,match='离开丰野间'):d.triad_hub_entry(fake)
    hub=captured('v0942-triad-hub',True)
    hub.words.append(Word('阵入局',[500,300,100,36],.99));d.observe=lambda:hub
    with pytest.raises(TaskBlocked,match='未完整确认'):d.triad_hub_entry(hub)


@pytest.mark.parametrize('caption',['活动已结束','尚未开放'])
def test_explicit_closed_caption_below_partial_title_is_respected(tmp_path,caption):
    d=daily(tmp_path);hub=captured('v0942-triad-hub',True)
    hub.words=[w for w in hub.words if not (w.box[0]>930 and 575<=w.center[1]<=610)]
    hub.words.append(Word(caption,[980,583,110,22],.99))
    d.observe=lambda:hub;d.event_hub=lambda s:s
    d.b.click_at=lambda *a:pytest.fail('Closed event must not be entered')
    assert d.triad_lobby() is None


@pytest.mark.parametrize('name,expected',[
    ('v0942-triad-battle2','1'),('v0942-triad-battle3','2'),('v0942-triad-battle5','3')])
def test_real_hud_round_identifies_units_despite_missing_timer_punctuation(name,expected):
    s=captured(name,True)
    assert triad_hud_round(s)==triad_round(s)==expected and is_triad_battle(s)


@pytest.mark.parametrize('name',['v0942-triad-hub','v0942-triad-lobby',
    'v0942-triad-preview','v0942-triad-victory'])
def test_other_real_pages_are_not_active_three_round_battles(name):
    s=captured(name,True)
    assert triad_hud_round(s) is None and not is_triad_battle(s)


def test_health_bar_borders_without_green_health_do_not_prove_battle():
    assert triad_hud_round(screen(('自动',85,600,50,35))) is None


def test_quota_reader_is_confined_to_explicit_free_counter():
    s=captured('v0942-triad-quota9',True);reads=[]
    assert triad_quota(s) is None
    assert triad_quota(s,lambda q,roi:reads.append(roi) or 9)==9
    assert reads==[(1170,654,40,30)]
    assert triad_quota(screen(('三阵入局',100,20,140,35),('匹配',1000,625,100,40),
        ('1/3',760,150,60,35)),lambda *a:pytest.fail('Score is not quota')) is None


@pytest.mark.parametrize('hour,minute,opened',[(16,59,False),(17,0,True),(22,59,True),(23,0,False)])
def test_actual_client_schedule_uses_beijing_time(hour,minute,opened):
    now=datetime(2026,10,23,hour,minute,tzinfo=timezone(timedelta(hours=8)))
    assert triad_is_open(captured('v0942-triad-lobby'),now)==opened


def test_ten_free_matches_are_not_limited_to_three_rounds(tmp_path):
    d=daily(tmp_path);d.home=lambda:None;matches=[]
    d.triad_lobby=lambda s=None:lobby(10-d.task_counts.get('triad',0))
    d.triad_match=lambda s:(matches.append('match') or result(),'victory',3)
    d.exit_result=lambda s:lobby(10-d.task_counts.get('triad',0))
    message=d.triad()
    assert len(matches)==d.task_counts['triad']==10
    assert d.report['triad_remaining']==0 and '已完成10场' in message
    assert d.report['resource_usage']['triad']['免费匹配次数']['spent']==10


def test_actual_result_returns_to_recognized_triad_lobby(tmp_path):
    d=daily(tmp_path);ready=captured('v0942-triad-quota9',True)
    d.observe=lambda:ready;d.b.sleep=lambda _:None;clicks=[]
    d.b.click_text=lambda s,p:clicks.append(p)
    assert exit_destination(ready)=='triad_lobby'
    assert d.exit_result(captured('v0942-triad-victory',True)) is ready
    assert clicks==['^退出$'] and d.report['result_exits'][0]['destination']=='triad_lobby'


def test_real_three_rounds_keep_settling_while_button_remains(tmp_path):
    d=daily(tmp_path);d.options['triad']['auto_settle']=True
    d.triad_lobby=lambda s=None:lobby(3)
    frames=[]
    for name in ('v0942-triad-battle2','v0942-triad-battle3','v0942-triad-battle5'):
        frames.extend([captured(name,True)]*3)
    frames.append(captured('v0942-triad-victory',True));frames=iter(frames)
    d.observe=lambda:next(frames);d.b.sleep=lambda _:None;d.retry_battle_network=lambda *a:False
    clicks=[];d.b.click_text=lambda *a,**kw:clicks.append('match')
    d.b.click_at=lambda *a,**kw:clicks.append('settle');d.b.read_text_crop=lambda *a:'结算'
    _,outcome,count=d.triad_match(lobby(3))
    assert outcome=='victory' and count==9 and clicks==['match']+['settle']*9


def test_zero_quota_never_starts_another_match(tmp_path):
    d=daily(tmp_path);d.triad_lobby=lambda s=None:lobby(0);d.home=lambda:None
    d.triad_match=lambda s:pytest.fail('No free attempts')
    assert '已用完' in d.triad() and d.report['triad_remaining']==0


@pytest.mark.parametrize('name,expected',[
    ('v0942-triad-failure','failed'),('v0942-triad-victory','victory')])
def test_actual_round_summary_and_score_identify_unreadable_result_graphics(name,expected):
    s=captured(name,True)
    s.words=[w for w in s.words if w.text not in ('胜利','失败')]
    assert triad_result(s)==expected
    s.words=[w for w in s.words if w.text!='5v5']
    assert triad_result(s) is None


def test_swallowed_match_button_retries_without_counting_or_extra_spend(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from test_triad import battle
    d=daily(tmp_path);d.options['triad']['auto_settle']=False
    d.triad_lobby=lambda s=None:lobby(3);d.b.sleep=lambda _:None
    d.retry_battle_network=lambda *a:False;clicks=[];battle_reads=[0]
    def read():
        if len(clicks)<2:return lobby(3)
        battle_reads[0]+=1
        return battle(1) if battle_reads[0]<=1 else result()
    d.observe=read;d.b.click_text=lambda *a,**kw:clicks.append('match')
    d.b.read_text_crop=lambda *a:''
    ticks=iter(i*.25 for i in range(10000))
    monkeypatch.setattr('chao2.navigation_retry.time',SimpleNamespace(monotonic=lambda:next(ticks)))
    assert d.triad_match(lobby(3))[1]=='victory'
    assert clicks==['match','match'] and d.battles==0


def test_changed_free_quota_during_match_retry_blocks_second_input(tmp_path,monkeypatch):
    from types import SimpleNamespace
    d=daily(tmp_path);d.triad_lobby=lambda s=None:lobby(3);d.b.sleep=lambda _:None
    d.observe=lambda:lobby(2);clicks=[];d.b.click_text=lambda *a,**kw:clicks.append('match')
    ticks=iter(i*.25 for i in range(10000))
    monkeypatch.setattr('chao2.navigation_retry.time',SimpleNamespace(monotonic=lambda:next(ticks)))
    with pytest.raises(TaskBlocked,match='次数已变化'):d.triad_match(lobby(3))
    assert clicks==['match']


def test_actual_maa_reads_isolated_seven_nine_and_unpunctuated_battle_controls(tmp_path):
    from test_maa_recognition import Offline
    from maa.resource import Resource
    from maa.tasker import Tasker
    from chao2.backend import Backend,ROOT
    from chao2.workflows import Daily
    c=Offline();assert c.post_connection().wait().succeeded
    resource=Resource();assert resource.post_bundle(ROOT/'resource').wait().succeeded
    tasker=Tasker();assert tasker.bind(resource,c)
    b=Backend({},log=lambda _:None);b.tasker=tasker
    d=Daily(b,{'folder':tmp_path,'events':[]})
    for name,expected in [('v0942-triad-quota9',9),('v0942-triad-quota7',7),('v0942-triad-quota1',1)]:
        s=captured(name,True)
        assert triad_quota(s) is None
        assert d.await_triad_quota(s)[1]==expected
    for name in ('v0942-triad-battle2','v0942-triad-battle5'):
        assert triad_settle_button(captured(name,True),b.read_text_crop).text=='结算'


def test_quota_preprocessing_does_not_treat_underline_or_empty_pixels_as_digits():
    from chao2.triad import triad_quota_digit_image
    s=screen();roi=(1168,654,40,30)
    assert triad_quota_digit_image(s,roi) is None
    s.image[680:682,1168:1208]=[30,180,255]
    assert triad_quota_digit_image(s,roi) is None
