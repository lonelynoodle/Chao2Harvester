"""Exploration task: collect, dispatch, idle fallback; no emulator input."""
import pytest
from test_configuration import daily,captured,screen
from chao2.activities import is_exploration_menu,is_exploration_rewards,exploration_capacity
from chao2.workflows import is_world,ORDER
from chao2.configuration import normalize_settings,plan_tasks
from chao2.policy import TaskBlocked

def test_captured_menu_capacity_and_home(tmp_path):
    d=daily(tmp_path);menu=captured('exploration-menu');running=captured('exploration-start-all')
    assert is_exploration_menu(menu) and exploration_capacity(menu)==(2,11)
    assert exploration_capacity(running)==(0,11)
    assert not is_world(menu) and not is_world(captured('exploration-detail'))
    pages=iter([captured('exploration-detail'),menu,captured('world-missed-label',True)])
    d.observe=lambda:next(pages);clicks=[];d.b.click_at=lambda s,p,a,r:clicks.append(r)
    d.home();assert clicks==['关闭探索详情','收起探索列表']

def test_bulk_start_records_actual_dispatch_not_button_click(tmp_path):
    d=daily(tmp_path);d.enter_overview=lambda _:captured('exploration-menu')
    clicks=[];d.b.click_text=lambda s,p:clicks.append(p)
    d.observe=lambda:captured('exploration-start-all');d.home=lambda:None
    assert '新增指派2只' in d.exploration()
    assert d.report['exploration']['idle']==0
    assert d.report['exploration']['started_monsters']==2
    assert clicks==['^全部开始探索$','^全部领取$']

def test_all_running_is_not_cancelled_or_restarted(tmp_path):
    d=daily(tmp_path);d.enter_overview=lambda _:captured('exploration-start-all')
    d.observe=lambda:captured('exploration-start-all');d.home=lambda:None
    clicks=[];d.b.click_text=lambda s,p:clicks.append(p)
    assert '新增指派0只' in d.exploration()
    assert clicks==['^全部领取$']

def test_bulk_start_no_progress_uses_idle_assignment_once(tmp_path):
    d=daily(tmp_path);d.enter_overview=lambda _:captured('exploration-menu')
    d.observe=lambda:captured('exploration-menu');d.b.click_text=lambda *a:None;d.home=lambda:None
    attempts=[]
    def assign(s):attempts.append(True);return captured('exploration-start-all'),1
    d.exploration_assign_idle=assign
    # After successful assignment the next observation must remain the running menu.
    def observe():return captured('exploration-start-all') if attempts else captured('exploration-menu')
    d.observe=observe
    d.exploration();assert attempts==[True]
    assert d.report['exploration']['auto_assigned']==1

def test_unknown_exploration_page_blocks_before_click(tmp_path):
    d=daily(tmp_path);d.enter_overview=lambda _:screen(('开始探索',800,120,100,25))
    d.b.click_text=lambda *a:pytest.fail('Unknown screen must not click')
    with pytest.raises(TaskBlocked):d.exploration()


def test_idle_slots_without_confirmed_assignment_are_not_reported_done(tmp_path):
    d=daily(tmp_path);menu=captured('exploration-menu')
    d.enter_overview=lambda _:menu;d.observe=lambda:menu;d.b.click_text=lambda *a:None
    d.exploration_assign_idle=lambda s:(s,0)
    with pytest.raises(TaskBlocked,match='空闲名额'):d.exploration()

def test_exploration_does_not_enable_itself_in_existing_saved_queue():
    settings=normalize_settings({'tasks':['copies']})
    assert settings['tasks']==['copies'] and settings['task_options']['exploration']=={}
    assert plan_tasks(settings,['copies','exploration','rewards'],ORDER)==['exploration','copies','rewards']


@pytest.mark.parametrize('name',['exploration-rewards','exploration-rewards-scrolled'])
def test_real_reward_summary_is_not_the_menu_or_world(name):
    s=captured(name,True)
    assert is_exploration_rewards(s)
    assert not is_exploration_menu(s) and not is_world(s)
    # Dimmed background text can still be recognized in other animation frames.
    s.words+=screen(('剩余可指派怪兽0/11',908,80,190,19)).words
    assert not is_exploration_menu(s)


def test_unrelated_reward_title_does_not_trigger_exploration_close():
    assert not is_exploration_rewards(screen(('奖励',605,76,67,36)))
    assert not is_exploration_rewards(screen(('奖励',605,76,67,36),('探索',1220,565,45,26)))


def test_collect_summary_closes_once_then_starts_available_exploration(tmp_path):
    d=daily(tmp_path);d.enter_overview=lambda _:captured('exploration-start-all')
    pages=iter([captured('exploration-rewards'),captured('exploration-rewards-scrolled'),
                captured('exploration-menu'),captured('exploration-start-all'),
                captured('exploration-start-all')])
    d.observe=lambda:next(pages);d.home=lambda:None;d.b.sleep=lambda _:None
    clicks=[];d.b.click_text=lambda s,p:clicks.append(p)
    d.b.click_at=lambda s,p,a,r:clicks.append((p,r))
    assert '已领取1批，新增指派2只' in d.exploration()
    assert clicks==['^全部领取$',((884,100),'关闭探索奖励汇总'),'^全部开始探索$','^全部领取$']
    assert d.report['exploration']==dict(idle=0,capacity=11,collected_batches=1,started_monsters=2,auto_assigned=0)


def test_home_can_resume_from_the_stuck_summary(tmp_path):
    d=daily(tmp_path)
    pages=iter([captured('exploration-rewards'),captured('exploration-start-all'),
                captured('world-missed-label',True)])
    d.observe=lambda:next(pages);clicks=[]
    d.b.click_at=lambda s,p,a,r:clicks.append((p,r))
    assert is_world(d.home())
    assert clicks==[((884,100),'关闭探索奖励汇总'),((770,680),'收起探索列表')]
    assert d.report['exploration_reward_summaries_closed']==1


def test_failed_summary_close_retries_once_then_stops_without_reporting_success(tmp_path):
    d=daily(tmp_path);s=captured('exploration-rewards')
    d.observe=lambda:s;d.b.sleep=lambda _:None;clicks=[]
    d.b.click_at=lambda s,p,a,r:clicks.append(p)
    with pytest.raises(TaskBlocked,match='关闭探索奖励后未返回探索列表'):
        d.close_exploration_rewards(s)
    assert clicks==[(884,100),(884,100)]
    assert not d.report.get('exploration_reward_summaries_closed')
