"""Regressions from the 2026-10-17 14:33 daily run, with actual saved frames."""
import time
import pytest
from test_configuration import daily,captured,screen
from chao2.activities import formation_power,main_nodes
from chao2.workflows import is_world,is_level_up
from chao2.policy import TaskBlocked
from chao2.wild_capture import wild_absent,is_wild_list


def test_actual_upgrade_is_a_closeable_overlay_not_world():
    s=captured('v0913-level-up',True)
    assert is_level_up(s) and not is_world(s)
    assert not is_level_up(captured('v097-wild-success',True))
    s.words=[w for w in s.words if w.text!='怪兽等级上限']
    assert not is_level_up(s)


def test_diagnostic_observer_keeps_upgrade_read_only(tmp_path):
    d=daily(tmp_path);up=captured('v0913-level-up',True)
    d.b.observe=lambda *a:up
    d.b.click_at=lambda *a:pytest.fail('Read-only observation must not close any popup')
    assert d.observe('diagnostic',dismiss_popups=False) is up
    assert not d.report.get('level_ups')


def test_observer_closes_upgrade_once_then_returns_underlying_reward(tmp_path):
    d=daily(tmp_path);up=captured('v0913-level-up',True)
    reward=screen(('获得奖励',500,100,170,35),('点击空白位置关闭',550,604,180,27))
    frames=iter([up,up,reward]);d.b.observe=lambda *a:next(frames)
    d.b.sleep=lambda _:None;clicks=[]
    d.b.click_at=lambda *a:clicks.append(a[3])
    assert d.observe() is reward and clicks==['关闭探索者升级提示']
    assert d.report['level_ups'][0]=={'from':'57','to':'58','status':'closed'}


def test_upgrade_not_dismissed_repeatedly_if_client_is_stuck(tmp_path):
    d=daily(tmp_path);up=captured('v0913-level-up')
    d.b.observe=lambda *a:up;d.b.sleep=lambda _:None;clicks=[]
    d.b.click_at=lambda *a:clicks.append(a[1])
    with pytest.raises(TaskBlocked,match='未重复领取'):d.dismiss_level_up(up)
    assert len(clicks)==1


@pytest.mark.parametrize('after',['world','star','reward'])
def test_star_claim_with_upgrade_continues_without_reclaim(tmp_path,after):
    d=daily(tmp_path);world=captured('v0913-main-world',True)
    star=screen(('星律',124,14,90,30),('收获',1000,600,100,40))
    reward=screen(('获得奖励',500,100,170,35),('点击空白位置关闭',550,604,180,27))
    result={'world':world,'star':star,'reward':reward}[after]
    # Exercise the real observer, including the automatic upgrade close.
    frames=iter([star,captured('v0913-level-up'),result])
    d.b.observe=lambda *a:next(frames);d.home=lambda *a:world
    d.b.sleep=lambda _:None;claims=[];clicks=[]
    d.click_world=lambda *a:None
    d.b.click_text=lambda s,p:claims.append(p)
    d.b.click_at=lambda *a:clicks.append(a[3])
    assert '已执行' in d.collect_idle()
    assert claims==['^收获$'] and clicks.count('关闭探索者升级提示')==1


@pytest.mark.parametrize('text,number',[('7437I',74371),('7437|',74371),('74371',74371),('战力74371',None),('74_71',None)])
def test_power_only_normalizes_isolated_numeric_field(text,number):
    assert formation_power(text)==number


@pytest.mark.parametrize('power',['7437I','74370',''])
def test_independent_copy_uses_lineup_even_when_power_disagrees(tmp_path,power):
    d=daily(tmp_path);d.active_task='tribe'
    config=captured('v0913-team-config',True)
    row=config.find('^队伍1$',(285,80,200,590))
    for w in config.words:
        if 395<=w.center[0]<510 and abs(w.center[1]-row.center[1])<22:w.text='74371'
    copied=captured('v0913-tribe-power',True)
    frames=iter([config,config,copied,copied,copied]);d.observe=lambda:next(frames)
    d.b.read_number=lambda *a:None;d.b.read_text_crop=lambda *a:power
    d.b.sleep=lambda _:None;copies=[]
    d.b.click_at=lambda *a:copies.append('^复制此配置$') if a[3].startswith('复制保存的') else None
    d.b.click_text=lambda s,p,roi=None:copies.append(p)
    assert d.apply_saved_team(captured('tribe-formation'),1) is copied
    assert copies==['^复制此配置$']
    assert d.report['team_copy_checks'][0]['status']=='verified'
    assert d.report['team_copy_checks'][0]['matched_monsters']==5


def test_main_overview_world_timeout_falls_back_but_unknown_overlay_does_not(tmp_path):
    d=daily(tmp_path);world=captured('v0913-main-world',True)
    assert is_world(world) and main_nodes(world)
    overview=screen(('玩法概览',80,400,120,30),('每日挑战',80,100,120,30),('世界关卡',370,300,100,30))
    d.find_overview_entry=lambda p:(overview,'target',overview.find('世界关卡'))
    d.b.click_at=lambda *a:None;d.b.sleep=lambda _:None;d.observe=lambda:world
    d.await_detail=lambda:pytest.fail('A world-only jump must use map search')
    assert d.main_overview_detail() is None
    d.observe=lambda:screen(('未识别页面',500,300,200,30))
    with pytest.raises(TaskBlocked,match='跳转未完成'):d.main_overview_detail()


def test_source_power_flame_is_excluded_and_trailing_one_is_preserved(tmp_path):
    d=daily(tmp_path);d.active_task='tribe'
    frames=iter([captured('v0913-team-config',True),captured('v0913-team-config',True),captured('v0913-tribe-power',True)])
    d.observe=lambda:next(frames);d.b.click_at=lambda *a:None;d.b.click_text=lambda *a,**kw:None
    reads=[]
    def crop(s,roi):
        reads.append(roi)
        assert roi in ((426,103,72,32),(1178,77,80,35))
        return '7437I'
    d.b.read_text_crop=crop;d.b.read_number=lambda *a:None
    d.apply_saved_team(captured('tribe-formation'),1)
    assert d.report['team_copy_checks'][0]['expected_power']==74371
    assert d.report['team_copy_checks'][0]['status']=='verified'


def test_event_navigation_recovers_delayed_overview_return(tmp_path):
    d=daily(tmp_path);world=captured('v0913-main-world',True)
    overview=captured('overview-top-current');menu=captured('v0913-wild-empty',True)
    frames=iter([overview,menu]);d.observe=lambda:next(frames)
    d.home=lambda s:world;clicks=[];d.click_world=lambda s,p,r:clicks.append((p,r))
    assert d.open_world_events(world) is menu and len(clicks)==2
    assert '返回世界后' in clicks[1][1]


def wild_daily(tmp_path):
    d=daily(tmp_path,{'wild_capture_enabled':True,'wild_capture':{'ultimate':{'enabled':True}}})
    d.b.sleep=lambda _:None
    world=captured('v0913-main-world',True)
    d.home=lambda *a:world;d.close_wild=lambda s:world
    return d,world


def test_actual_empty_wild_list_is_normal_skip_without_fake_monster(tmp_path):
    d,world=wild_daily(tmp_path);empty=captured('v0913-wild-empty',True)
    assert wild_absent(empty) and is_wild_list(empty)
    d.open_wild_list=lambda s:empty;d.observe=lambda:empty
    assert d.maybe_capture_wild(world) is world
    assert d.report['wild_checks'][-1]['status']=='absent'
    assert not d.report.get('wild_captures')


def test_wild_navigation_failure_is_not_unknown_monster_or_absence(tmp_path):
    d,world=wild_daily(tmp_path)
    def fail(s):raise TaskBlocked('事件列表未打开')
    d.open_wild_list=fail
    assert d.maybe_capture_wild(world) is world
    assert d.report['wild_checks'][-1]['status']=='navigation_failed'
    assert '是否刷新尚未确认' in d.report['wild_checks'][-1]['message']
    assert not d.report.get('wild_captures')


def test_blank_or_loading_wild_list_cannot_be_reported_as_absent(tmp_path):
    d,world=wild_daily(tmp_path);empty=captured('v0913-wild-empty',True)
    empty.words=[w for w in empty.words if w.text!='野生怪兽未出现']
    d.open_wild_list=lambda s:empty;d.observe=lambda:empty
    d.maybe_capture_wild(world)
    assert d.report['wild_checks'][-1]['status']=='navigation_failed'
