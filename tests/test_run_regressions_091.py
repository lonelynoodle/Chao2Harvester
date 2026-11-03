"""Actual 14:02 run regressions; no live account input."""
import pytest
from test_configuration import captured,daily,screen
from chao2.activities import is_main_detail,exploration_card_point,exploration_card_running
from chao2.workflows import is_world
from chao2.anomalies import evolved_copy_without_instant,instant_frame
from chao2.policy import TaskBlocked


def test_evolved_roman_one_read_as_capital_l_still_requires_no_checkbox(tmp_path):
    d=daily(tmp_path);s=captured('v091-evolved-copy',True)
    assert evolved_copy_without_instant(s)
    d.b.match_template=lambda s,n,*a:n=='copy-own-exp50.png'
    d.verify_instant_setting('copies',s)
    rim,_=instant_frame();s.image[685:685+rim.shape[0],1010:1010+rim.shape[1]]=rim
    assert not evolved_copy_without_instant(s)
    with pytest.raises(TaskBlocked,match='瞬破'):d.verify_instant_setting('copies',s)


def test_exploration_swallowed_close_retries_only_same_popup(tmp_path):
    d=daily(tmp_path);popup=captured('v091-exploration-rewards',True)
    menu=captured('v091-exploration-menu',True)
    pages=iter([popup]*4+[menu]);d.observe=lambda:next(pages)
    d.b.sleep=lambda _:None;clicks=[];d.b.click_at=lambda s,p,a,r:clicks.append(p)
    assert d.close_exploration_rewards(popup) is menu
    assert clicks==[(884,100),(884,100)]
    assert d.report['exploration_reward_summaries_closed']==1


def test_exploration_changed_page_does_not_repeat_dismissal(tmp_path):
    d=daily(tmp_path);d.observe=lambda:screen();d.b.sleep=lambda _:None
    clicks=[];d.b.click_at=lambda s,p,a,r:clicks.append(p)
    with pytest.raises(TaskBlocked):d.close_exploration_rewards(captured('v091-exploration-rewards',True))
    assert clicks==[(884,100)]


def test_completed_main_detail_can_return_without_fighting(tmp_path):
    d=daily(tmp_path);detail=captured('v091-completed-detail',True)
    assert is_main_detail(detail) and not detail.find('首通奖励')
    pages=iter([detail,captured('world-missed-label',True)]);d.observe=lambda:next(pages)
    clicks=[];d.b.click_at=lambda s,p,a,r:clicks.append((p,r))
    assert is_world(d.home())
    assert clicks==[((45,28),'关闭已通主线关卡详情')]
    assert not is_main_detail(screen(('敌方阵容',1130,136,100,28),('排阵',824,614,61,35),('挑战',1061,616,57,32)))


def test_partial_exploration_card_target_cannot_hit_bottom_tabs():
    title=screen(('虚言葬地',832,572,130,24)).words[0]
    assert exploration_card_point(title)==(1000,619)
    assert exploration_card_point(screen(('未知探索区',832,600,130,24)).words[0])[1]<=625


def test_exploration_timer_skips_running_area_but_duration_does_not():
    s=screen(('虚言葬地',832,205,130,24),('11:52:52',889,234,90,25))
    assert exploration_card_running(s,s.words[0])
    s.words[1].text='12小时'
    assert not exploration_card_running(s,s.words[0])


def test_spare_capacity_with_all_areas_running_is_not_a_failure(tmp_path):
    d=daily(tmp_path);menu=captured('exploration-menu')
    d.enter_overview=lambda _:menu;d.observe=lambda:menu;d.b.click_text=lambda *a:None;d.home=lambda:None
    def assign(s):
        d.report['exploration_scan']={'complete':True,'areas':11,'running':11}
        return s,0
    d.exploration_assign_idle=assign
    assert '11个探索区均在倒计时' in d.exploration()


def test_cancellation_drains_native_job_before_unwinding(tmp_path):
    from types import SimpleNamespace
    from chao2.policy import UserStopped
    d=daily(tmp_path)
    class Job:
        polls=0
        @property
        def done(self):self.polls+=1;return self.polls>=3
    job=Job();stopping=Job()
    d.b.tasker=SimpleNamespace(post_stop=lambda:stopping);d.b.stop.set()
    with pytest.raises(UserStopped):d.b.wait(job)
    assert job.done and stopping.done
