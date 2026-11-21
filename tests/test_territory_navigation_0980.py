"""Local map captions and task failures must not abort a navigable queue."""
import threading
import re
from copy import deepcopy
import pytest
from chao2.backend import Word
from chao2.policy import TaskBlocked,PageChanged,SafetyStop,UserStopped,SessionUnavailable
from chao2.territory_labels import (TERRITORY_LABELS,label_pattern,is_territory,
                                   confirm_territory_label,recover_territory_labels)
from test_configuration import daily,screen,captured


def territory(missing=None):
    s=screen()
    for label in ('世界','排阵','怪兽','谜之巢穴','凿星裂痕','浮空巨塔','永生之茧','黑暗森林'):
        if label!=missing:s.words.append(Word(label,list(TERRITORY_LABELS[label]),.99))
    return s


@pytest.mark.parametrize('label',list(TERRITORY_LABELS))
def test_every_registered_caption_has_its_own_crop_and_reprojects_the_word(tmp_path,label):
    d=daily(tmp_path);s=territory(label);calls=[]
    def confirm(q,pattern,roi,**kw):
        calls.append((q,pattern,roi,kw))
        q.words.append(Word(label,list(roi),.95));return True
    d.b.confirm_label=confirm
    assert confirm_territory_label(d.b,s,label_pattern(label))
    assert len(calls)==1 and calls[0][2]==TERRITORY_LABELS[label]
    assert calls[0][3]=={'scale':3,'threshold':.8}
    assert s.find(label_pattern(label),TERRITORY_LABELS[label])


def test_failed_crop_gets_one_bounded_enlarged_retry(tmp_path):
    d=daily(tmp_path);calls=[]
    d.b.confirm_label=lambda *a,**kw:calls.append(kw['scale'])
    assert not confirm_territory_label(d.b,territory('斗技场'),'^斗技场$')
    assert calls==[3,4]


def test_all_missing_captions_are_supplemented_without_map_input(tmp_path):
    d=daily(tmp_path);s=territory();d.b.tasker=object();calls=[]
    def confirm(q,p,roi,**kw):
        label=next(k for k in TERRITORY_LABELS if label_pattern(k)==p)
        calls.append(label);q.words.append(Word(label,list(roi),.95));return True
    d.b.confirm_label=confirm
    assert recover_territory_labels(d.b,s) is s
    assert '斗技场' in calls
    assert all(s.find(label_pattern(label),roi) for label,roi in TERRITORY_LABELS.items())
    count=len(calls);recover_territory_labels(d.b,s)
    assert len(calls)==count


@pytest.mark.parametrize('overlay',['取消','探索者等级','点击空白位置关闭','玩法概览','选择挑战的塔'])
def test_captions_behind_overlays_cannot_authorize_map_clicks(tmp_path,overlay):
    d=daily(tmp_path);s=territory();s.words.append(Word(overlay,[450,280,200,35],.99))
    d.b.confirm_label=lambda *a,**k:pytest.fail('Must not read background captions through an overlay')
    assert not is_territory(s)
    assert not confirm_territory_label(d.b,s,'^斗技场$')
    recover_territory_labels(d.b,s)


def test_world_or_unrelated_text_does_not_authorize_registered_crops(tmp_path):
    d=daily(tmp_path)
    d.b.confirm_label=lambda *a,**k:pytest.fail('No map crop on an unrelated page')
    assert not confirm_territory_label(d.b,screen(('斗技场',100,100,100,30)),'^斗技场$')
    assert not confirm_territory_label(d.b,territory(),'^购买$')


def test_preclick_frame_gets_its_own_local_caption_read(tmp_path):
    d=daily(tmp_path);old=territory('斗技场');fresh=territory('斗技场');reads=[];clicks=[]
    def confirm(q,p,roi,**kw):
        reads.append(q);q.words.append(Word('斗技场',list(roi),.95));return True
    d.b.confirm_label=confirm;d.b.observe=lambda:fresh
    d.b.click_at=lambda q,point,*a,**k:clicks.append((q,point))
    d.b.click_text(old,'^斗技场$',roi=(170,35,990,590))
    assert len(reads)==2 and reads[0] is old and reads[1] is fresh
    assert len(clicks)==1 and clicks[0][0] is fresh
    assert clicks[0][1]==fresh.find('^斗技场$').center


def test_levelup_between_detection_and_click_sends_no_map_input(tmp_path):
    d=daily(tmp_path);old=territory();old.words.append(Word('斗技场',list(TERRITORY_LABELS['斗技场']),.99))
    fresh=deepcopy(old);fresh.words.append(Word('探索者等级',[680,200,200,40],.99))
    d.b.observe=lambda:fresh;d.b.click_at=lambda *a,**k:pytest.fail('No click through level-up')
    with pytest.raises(PageChanged):d.b.click_text(old,'^斗技场$')


@pytest.mark.parametrize('error',[TaskBlocked('未识别按钮：^斗技场$'),PageChanged('^斗技场$')])
def test_arena_missing_or_changed_entrance_uses_task_overview(tmp_path,error):
    d=daily(tmp_path);calls=[];s=territory();menu=screen(('斗技场',100,10,100,30),('挑战次数',780,660,100,30))
    d.territory=lambda:s
    def click(*a,**kw):raise error
    d.b.click_text=click
    d.overview_entry=lambda key,**kw:calls.append(key)
    d.await_page=lambda *a:menu
    assert d.enter_building('斗技场','挑战次数') is menu
    assert calls==['arena']


def test_overview_title_column_is_reocrd_before_declaring_entry_missing(tmp_path):
    d=daily(tmp_path);s=screen(('玩法概览',130,60,100,30),('每日挑战',130,160,100,30));calls=[]
    def confirm(q,p,roi,**kw):
        calls.append((p,roi,kw));q.words.append(Word('斗技场',[370,240,90,24],.95));return True
    d.b.confirm_label=confirm
    assert d.read_overview_labels(s,{'arena':'^斗技场$'}).find('^斗技场$',(350,80,180,490))
    assert calls==[('^斗技场$',(350,80,180,490),{'scale':3,'threshold':.8})]


@pytest.mark.parametrize('failure',['missing','changed','both_routes_failed','overview_sort_failed'])
def test_real_queue_continues_all_later_tasks_after_arena_failure(tmp_path,monkeypatch,failure):
    import chao2.workflows as w
    report={'folder':tmp_path,'tasks':{},'events':[]};seen=[]
    monkeypatch.setattr(w,'create_report',lambda:report)
    monkeypatch.setattr(w.Backend,'connect',lambda b:None)
    monkeypatch.setattr(w.Daily,'home',lambda d,*a,**k:screen())
    monkeypatch.setattr(w.Daily,'world_resources',lambda d,s:{'stamina':1,'stamina_cap':163,'diamonds':1000})
    monkeypatch.setattr(w.Daily,'maybe_capture_wild',lambda d,s:s)
    monkeypatch.setattr(w.Daily,'maybe_free_summon',lambda d,s:s)
    monkeypatch.setattr(w.Daily,'save_state',lambda d:None)
    def fail(d):
        d.last_screen=territory('斗技场')
        if failure=='changed':raise PageChanged('斗技场',d.last_screen)
        if failure=='both_routes_failed':
            d.territory=lambda:d.last_screen
            def overview(*a,**kw):raise TaskBlocked('玩法概览中未找到入口：斗技场')
            d.overview_entry=overview
            return d.enter_building('斗技场','挑战次数')
        d.b.click_text(d.last_screen,'^斗技场$')
    monkeypatch.setattr(w.Daily,'arena',fail)
    if failure=='overview_sort_failed':
        original=w.Daily.next_daily_task
        def select(d,pending):
            if d.b.settings['unordered_tasks']:raise TaskBlocked('玩法概览翻页未生效')
            return original(d,pending)
        monkeypatch.setattr(w.Daily,'next_daily_task',select)
    later=['hunt','main','nest','other','rewards']
    for name in later:
        def done(d,name=name):seen.append(name);return '已检查'
        monkeypatch.setattr(w.Daily,name,done)
    queue=[{'id':key,'key':key,'name':key,'enabled':True,
            'options':{'auto_three_shots':False,'auto_potions':False} if key in ('hunt','main') else {}}
           for key in ['arena',*later]]
    config={'task_queue':queue,'free_summon_enabled':False,'unordered_tasks':failure=='overview_sort_failed'}
    original_config=deepcopy(config)
    result=w.run_daily(config,['arena',*later],threading.Event(),log=lambda _:None)
    assert result['status']=='partial' and seen==later
    assert result['tasks']['arena']['status']=='blocked'
    assert all(result['tasks'][key]['status']=='done' for key in later)
    assert result['execution_order']==['arena',*later]
    assert config==original_config
    if failure=='overview_sort_failed':assert result['execution_mode_fallback']=='ordered'


@pytest.mark.parametrize('error',[UserStopped('用户停止'),SessionUnavailable('超二屏幕已关闭'),SessionUnavailable('账号已在其他设备登录')])
def test_stop_and_device_or_account_failure_still_propagate(tmp_path,error):
    d=daily(tmp_path)
    def fail():raise error
    d.arena=fail;d.home=lambda:pytest.fail('Must not hide a real stop')
    with pytest.raises(type(error)):d.execute_task('arena')


def test_unrecoverable_page_is_distinct_from_single_failed_task(tmp_path):
    d=daily(tmp_path)
    def fail():raise TaskBlocked('未识别斗技场入口')
    def unknown():raise TaskBlocked('当前页面无法识别或安全返回')
    d.arena=fail;d.home=unknown
    with pytest.raises(SafetyStop,match='无法识别'):d.execute_task('arena')
    assert 'recovery_error' in d.report['tasks']['arena']


def test_missing_anchor_before_input_is_page_change(tmp_path):
    d=daily(tmp_path)
    with pytest.raises(PageChanged):d.b.click_at(screen(),(100,100),['^不存在的控件$'],'导航')


@pytest.fixture
def local_backend():
    from maa.resource import Resource
    from maa.tasker import Tasker
    from chao2.backend import Backend,ROOT
    from test_maa_recognition import Offline
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({},log=lambda _:None);b.tasker=t;b.controller=c
    return b


def test_original_arena_failure_capture_local_ocr_and_fresh_frame(local_backend):
    s=captured('v0980-arena-entrance',True);fresh=captured('v0980-arena-entrance',True)
    assert not s.find('^斗技场$') and is_territory(s)
    assert confirm_territory_label(local_backend,s,'^斗技场$')
    assert s.find('^斗技场$',TERRITORY_LABELS['斗技场'])
    clicks=[];local_backend.observe=lambda:fresh
    local_backend.click_at=lambda q,p,*a,**kw:clicks.append((q,p))
    local_backend.click_text(s,'^斗技场$')
    assert len(clicks)==1 and clicks[0][0] is fresh
    assert fresh.find('^斗技场$',TERRITORY_LABELS['斗技场'])


@pytest.mark.parametrize('label',['斗技场','永生之茧','浮空巨塔','饲星坛','黑暗森林','部落'])
def test_missing_building_caption_on_actual_pixels(local_backend,label):
    s=captured('v0980-arena-entrance',True)
    pattern=label_pattern(label)
    s.words=[w for w in s.words if not re.search(pattern,w.text)]
    assert is_territory(s)
    assert confirm_territory_label(local_backend,s,pattern)


def test_exhausted_page_change_recovery_is_local_and_bounded(tmp_path):
    d=daily(tmp_path);calls=[];s=territory()
    d.b.tasker=object();d.b.controller=object();d.b.save_screen=lambda *a:None
    def fail():calls.append('arena');raise PageChanged('斗技场',s)
    d.arena=fail;d.home=lambda:s
    d.rewards=lambda:calls.append('rewards') or '已领取'
    d.execute_task('arena');d.execute_task('rewards')
    assert calls==['arena','rewards']
    assert not d.report.get('page_recoveries')
    assert d.report['tasks']['arena']['status']=='blocked'
    assert d.report['tasks']['rewards']['status']=='done'
