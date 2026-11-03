"""Regression evidence from the user's 20:03 run. No real game input."""
import pytest
from test_configuration import daily,screen,captured
from test_copy_navigation import Game
from chao2.activities import tribe_identity,is_tribe_detail
from chao2.daily_challenges import pvp_result
from chao2.workflows import is_failure
from chao2.configuration import COCOON_DAILIES


def test_sequential_copy_starts_first_rewarded_row_without_scan_for_own(tmp_path,monkeypatch):
    g=Game(tmp_path,monkeypatch,[[('friend','friend'),('own','own')],[('another','friend')]])
    target=g.d.copy_targets('any',set())
    assert target['identity']=='friend' and g.opens==['friend'] and g.swipes==[]


def test_completed_copy_cannot_be_reopened_after_refill(tmp_path,monkeypatch):
    g=Game(tmp_path,monkeypatch,[[('old','own'),('next','friend')]])
    g.d.report['copy_completed']=['old']
    assert g.d.copy_targets('any',set())['identity']=='next'
    assert g.opens==['next']


def test_friend_cap_stops_at_first_friend_without_scanning_remaining_pages(tmp_path,monkeypatch):
    g=Game(tmp_path,monkeypatch,[[('friend','friend')],[('another','friend')]],quota=1000)
    assert g.d.copy_targets('any',set()) is None
    assert g.opens==['friend'] and g.swipes==[]


def test_actual_tribe_31_ocr_variant_is_valid_and_home_can_exit(tmp_path):
    s=captured('v076-tribe-31');d=daily(tmp_path);clicks=[]
    assert tribe_identity(s)=='冒险关卡31' and is_tribe_detail(s)
    world=captured('other-initial-world',True);state=[s]
    d.observe=lambda:state[0]
    def click(*a):clicks.append(a[1]);state[0]=world
    d.b.click_at=click
    assert d.home() is world and clicks==[(45,28)]


def test_unknown_tribe_number_is_not_guessed():
    s=captured('v076-tribe-31')
    for w in s.words:
        if w.text=='冒险关卡3]':w.text='冒险关卡??'
    assert tribe_identity(s) is None and not is_tribe_detail(s)


def test_cocoon_animation_requires_two_matching_observations(tmp_path):
    d=daily(tmp_path);menu=captured('v076-cocoon-completed')
    all_done=set(COCOON_DAILIES);frames=iter([all_done,{'lower_left','lower_right'},all_done])
    d.cocoon_daily_done=lambda _:next(frames);d.observe=lambda:menu;d.b.sleep=lambda _:None
    _,done=d.cocoon_daily_done_stable(menu)
    assert done==all_done
    frames=iter([all_done,set(),set()])
    _,done=d.cocoon_daily_done_stable(menu)
    assert done==set() # One stale frame cannot mark newly reset tasks complete.


def test_actual_origin_defeat_works_without_ocr_defeat_title(tmp_path):
    s=captured('v076-origin-failed');assert not s.find('失败')
    assert pvp_result(s)=='failed' and is_failure(s)
    d=daily(tmp_path);d.observe=lambda:s
    assert d.pvp_battle('origin')==(s,'failed')
    world=captured('other-initial-world',True);state=[s];clicks=[]
    d.observe=lambda:state[0]
    def exit_result(q,p,**kw):clicks.append(p);state[0]=world
    d.b.click_text=exit_result
    assert d.home() is world and clicks==['^退出$']


def test_origin_negative_score_alone_is_not_a_defeat_screen():
    s=captured('v076-origin-failed')
    s.words=[w for w in s.words if w.text not in ('怪兽培育','元核升级','神灵升阶','阵容调整','黑暗森林')]
    assert pvp_result(s) is None


@pytest.mark.parametrize('balance,stock,reason',[(2,3,'体力不足'),(45,0,'狩猎令已用完')])
def test_zero_hunt_explains_reason_and_reports_tokens(tmp_path,balance,stock,reason):
    d=daily(tmp_path,{'task_options':{'hunt':{'auto_three_shots':False}}})
    s=screen(('狩猎',974,18,70,30),('商店',1060,94,60,30),('传送',1218,340,48,30),
             ('猎物未出现',946,435,114,24),('搜索',1055,665,110,30),(f'{balance}/164',502,17,78,22))
    d.hunt_menu=lambda:s;d.b.read_number=lambda *a:stock;d.home=lambda:None
    d.b.click_text=lambda *a,**kw:pytest.fail('No affordable hunt/search')
    d.execute_task('hunt')
    result=d.report['tasks']['hunt']
    assert reason in result['message'] and result['attempts']==0
    assert f'狩猎令消耗0，剩余{stock}' in result['summary']
    assert d.stamina_retry['hunt'] is False # Hunt handles its own refill before search.


def test_refill_does_not_repeat_exhausted_hunt_or_finished_copies(tmp_path):
    d=daily(tmp_path);d.selected=['copies','hunt','main'];balance=[0];calls=[]
    d.stamina_retry={'copies':False,'hunt':False,'main':True}
    d.home=lambda:screen();d.world_resources=lambda _:{'stamina':balance[0],'stamina_cap':164}
    d.stamina_offer=lambda:screen(('领取奖励',650,590,120,35))
    d.stamina_outlet_available=lambda *a:True
    d.b.click_text=lambda *a,**kw:balance.__setitem__(0,balance[0]+100)
    d.observe=lambda:screen()
    def run(task):calls.append(task);balance[0]-=5
    d.execute_task=run
    d.replenish_stamina()
    assert calls==['main'] and balance[0]==95


def test_resource_summary_preserves_cumulative_spend_and_unverified_balance(tmp_path):
    d=daily(tmp_path);d.resource_balance('copies','地图体力',42)
    d.settle_battle_resource('copies',screen(('22/164',1190,15,75,25)),'victory',42)
    d.resource_balance('copies','地图体力',122) # free stamina is not negative spending
    d.settle_battle_resource('copies',screen(('103/164',1190,15,75,25)),'victory',122)
    assert '地图体力消耗40，剩余103' in d.task_summary('copies')
    d.settle_battle_resource('copies',screen(),'failed',103)
    assert '1场未核实' in d.task_summary('copies')


def test_retry_log_and_attempt_summary_are_cumulative(tmp_path):
    d=daily(tmp_path);d.home=lambda:None
    def run():
        d.task_counts['copies']=d.task_counts.get('copies',0)+1
        d.report.setdefault('team_attempts',[]).append({'task':'copies','outcome':'victory'})
        return '复制体通关1次，体力不足20'
    d.copies=run
    d.execute_task('copies');d.execute_task('copies')
    assert d.report['tasks']['copies']['attempts']==2
    assert '累计挑战2次，胜利2次' in d.report['tasks']['copies']['summary']
    assert any('补充免费体力后继续' in e['message'] for e in d.report['events'])
