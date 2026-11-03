"""Actual overview frames plus simulated navigation; no emulator input."""
from types import SimpleNamespace
import threading

import pytest

from test_configuration import daily,screen,captured
from chao2.configuration import normalize_settings
from chao2.overview import OVERVIEW_ROUTES,overview_matches,overview_fingerprint
from chao2.policy import TaskBlocked
import chao2.workflows as flow


def navigator(tmp_path,frames):
    d=daily(tmp_path);current=[frames[0]];queue=iter(frames[1:]);swipes=[];clicks=[]
    d.task_panel=lambda *a:current[0];d.observe=lambda *a:current[0];d.b.sleep=lambda _:None
    d.b.click_at=lambda s,p,a,r:clicks.append((p,r))
    def swipe(*args):
        swipes.append(args);current[0]=next(queue,current[0]);return SimpleNamespace(succeeded=True)
    d.b.controller=SimpleNamespace(post_swipe=swipe);d.b.wait=lambda x:x
    return d,swipes,clicks,current


def test_new_mode_defaults_off_and_rejects_non_boolean():
    assert normalize_settings({})['unordered_tasks'] is False
    assert normalize_settings({'unordered_tasks':True})['unordered_tasks'] is True
    for bad in (None,1,'yes',[]):
        with pytest.raises(ValueError,match='任务顺序'):normalize_settings({'unordered_tasks':bad})


def test_top_target_is_used_immediately_even_when_exploration_is_lower(tmp_path):
    top=captured('overview-top-current');d,swipes,clicks,current=navigator(tmp_path,[top])
    dest=screen(('永生之茧',124,14,90,30),('刷新',612,496,54,33))
    def click(s,p,a,r):clicks.append((p,r));current[0]=dest
    d.b.click_at=click
    assert d.enter_overview('^永生之茧$') is dest
    assert swipes==[] and clicks==[((738,137),'前往永生之茧')]


def test_misread_cocoon_overview_uses_local_confirmation_before_any_scroll(tmp_path):
    top=captured('v083-overview-cocoon');d,swipes,_,_=navigator(tmp_path,[top])
    reads=[];d.b.read_text_crop=lambda s,roi:reads.append(roi) or '永生之茧'
    found=d.find_overview_entry({'cocoon':'^永生之茧$'})
    assert found[1]=='cocoon' and found[2].text=='永生之茧'
    assert len(reads)==1 and swipes==[] and not top.find('^永生之茧$')


def test_ambiguous_local_label_does_not_authorize_overview_entry(tmp_path):
    top=captured('v083-overview-cocoon');d=daily(tmp_path)
    d.b.read_text_crop=lambda *a:'永生之萤'
    assert d.read_overview_labels(top,{'cocoon':'^永生之茧$'}) is top
    d.b.read_text_crop=lambda *a:pytest.fail('Other tasks do not need this recheck')
    assert d.read_overview_labels(top,{'hunt':'^狩猎$'}) is top


def test_ordered_search_only_scrolls_down_until_target(tmp_path):
    top=captured('overview-top-current');middle=captured('overview-middle-current')
    d,swipes,_,_=navigator(tmp_path,[top,middle])
    found=d.find_overview_entry({'hunt':'^狩猎$'})
    assert found[1:] == ('hunt',middle.find('^狩猎$',(350,80,180,490)))
    assert swipes==[(650,590,650,235,600)]


def test_partial_footer_title_and_duplicate_resource_label_are_not_click_targets():
    s=screen(('狩猎',370,620,65,30),('异象',550,180,45,25),('异象',370,195,65,30))
    hits=overview_matches(s,{'hunt':'^狩猎$','copies':'^异象$'})
    assert [k for k,_ in hits]==['copies'] and hits[0][1].center[0]==402


def test_missing_entry_checks_omitted_upper_portion_once(tmp_path):
    top=captured('overview-top-current');bottom=captured('overview-bottom-current')
    d,swipes,_,_=navigator(tmp_path,[top,bottom,bottom])
    assert d.find_overview_entry({'missing':'^不存在的任务$'}) is None
    assert swipes==[(650,590,650,235,600),(650,590,650,235,600),(700,590,700,235,800),(650,235,650,590,600)]
    # Quantities/timers are deliberately ignored by the end-of-list comparison.
    before=overview_fingerprint(bottom);bottom.words+=screen(('0:20:01',550,280,80,25)).words
    assert overview_fingerprint(bottom)==before


def test_swallowed_scroll_retries_another_lane_instead_of_false_missing(tmp_path):
    top=captured('overview-top-current');middle=captured('overview-middle-current')
    d,swipes,_,_=navigator(tmp_path,[top,top,middle])
    found=d.find_overview_entry({'hunt':'^狩猎$'})
    assert found[1]=='hunt'
    assert swipes==[(650,590,650,235,600),(700,590,700,235,800)]
    assert (tmp_path/'overview-scroll-stalled.json').exists()


def test_stationary_first_page_is_explicit_scroll_failure_not_missing_entry(tmp_path):
    top=captured('overview-top-current');d,swipes,_,_=navigator(tmp_path,[top,top,top])
    with pytest.raises(TaskBlocked,match='翻页未生效'):
        d.find_overview_entry({'copies':'^异象$'})
    assert len(swipes)==2


def test_late_scroll_animation_requires_no_second_gesture(tmp_path):
    top=captured('overview-top-current');middle=captured('overview-middle-current')
    d,swipes,_,_=navigator(tmp_path,[top,top])
    reads=iter([top,middle]);d.observe=lambda *a:next(reads)
    assert d.find_overview_entry({'hunt':'^狩猎$'})[1]=='hunt'
    assert len(swipes)==1


def test_unordered_mode_picks_first_visible_selected_card_not_fixed_queue_order(tmp_path):
    d,swipes,clicks,_=navigator(tmp_path,[captured('overview-top-current')])
    d.b.settings['unordered_tasks']=True
    assert d.next_daily_task(['tribe','copies','cocoon','rewards'])=='cocoon'
    assert d.overview_prepared_for('cocoon') and not clicks and not swipes


def test_unordered_mode_skips_unselected_top_card_and_protected_play_entries(tmp_path):
    d,swipes,clicks,_=navigator(tmp_path,[captured('overview-top-current')])
    d.b.settings['unordered_tasks']=True
    assert d.next_daily_task(['tribe','copies'])=='tribe'
    assert not clicks and not swipes


def test_disabled_mode_never_opens_overview_to_reorder(tmp_path):
    d=daily(tmp_path);d.task_panel=lambda *a:pytest.fail('Ordered scheduling must not add a scan')
    assert d.next_daily_task(['copies','cocoon'])=='copies'


def test_wake_and_rewards_keep_their_required_positions(tmp_path):
    d=daily(tmp_path,{'unordered_tasks':True})
    d.task_panel=lambda *a:pytest.fail('Independent tasks need no overview scan')
    assert d.next_daily_task(['rewards','startup','giant'])=='startup'
    assert d.next_daily_task(['rewards','giant'])=='giant'
    assert d.next_daily_task(['rewards'])=='rewards'


def test_selected_card_handoff_reuses_panel_without_closing_or_reopening(tmp_path):
    d=daily(tmp_path);s=captured('overview-top-current');d._overview_ready='cocoon'
    d.observe=lambda *a:s
    d.home=lambda *a:pytest.fail('Already on the prepared overview page')
    d.b.click_text=lambda *a,**kw:pytest.fail('Do not select the same tab again')
    assert d.task_panel() is s and d._overview_ready is None


def test_missing_entries_do_not_rescan_all_pages_for_each_remaining_task(tmp_path):
    d=daily(tmp_path,{'unordered_tasks':True});calls=[];d.home=lambda:None
    d.find_overview_entry=lambda patterns:calls.append(patterns) or None
    assert d.next_daily_task(['copies','tribe'])=='copies'
    assert d.next_daily_task(['tribe'])=='tribe'
    assert len(calls)==1


@pytest.mark.parametrize('key,title',[('arena','斗技场'),('nest','谜之巢穴')])
def test_building_task_uses_the_selected_overview_card(tmp_path,key,title):
    d=daily(tmp_path);d._overview_ready=key;dest=screen();calls=[]
    d.enter_overview=lambda pattern:calls.append(pattern) or dest
    d.territory=lambda:pytest.fail('Prepared entry must not detour through territory')
    assert d.enter_building(title) is dest and calls==[OVERVIEW_ROUTES[key][0]]


def test_tower_uses_prepared_entry_and_then_selects_configured_kind(tmp_path):
    d=daily(tmp_path);d._overview_ready='tower';calls=[]
    choice=screen(('选择挑战的塔',530,80,200,35),('无限制',610,343,65,24))
    tower=screen(('浮空巨塔',124,14,90,30))
    d.enter_overview=lambda p:calls.append(p) or choice;d.observe=lambda:tower
    d.b.click_text=lambda s,p:calls.append(p)
    d.territory=lambda:pytest.fail('Prepared tower must not go through world')
    assert d.open_tower({'id':'normal','label':'无限制'}) is tower
    assert calls==['^浮空巨塔$','^无限制$']


def test_navigation_waits_for_destination_instead_of_accepting_map_animation(tmp_path):
    d=daily(tmp_path);s=captured('overview-top-current');d.task_panel=lambda:s
    dest=screen(('永生之茧',124,14,90,30),('刷新',612,496,54,33))
    frames=iter([screen(('事件',1000,630,90,30)),screen(),dest])
    d.observe=lambda:next(frames);d.b.sleep=lambda _:None;clicks=[]
    d.b.click_at=lambda *a:clicks.append(a)
    assert d.enter_overview('^永生之茧$') is dest and len(clicks)==1


def test_wrong_destination_is_not_counted_as_success_or_reclicked(tmp_path):
    d=daily(tmp_path);d.task_panel=lambda:captured('overview-top-current')
    other=screen(('谜之巢穴',124,14,100,30),('暴走旷野',580,620,120,35))
    d.observe=lambda:other;d.b.sleep=lambda _:None;clicks=[]
    d.b.click_at=lambda *a:clicks.append(a)
    with pytest.raises(TaskBlocked,match='跳转未完成：永生之茧'):
        d.enter_overview('^永生之茧$')
    assert len(clicks)==1


def test_failed_downward_swipe_stops_before_selecting_another_task(tmp_path):
    d,_,_,_=navigator(tmp_path,[captured('overview-top-current')])
    d.b.controller.post_swipe=lambda *a:SimpleNamespace(succeeded=False)
    with pytest.raises(TaskBlocked,match='翻页失败'):
        d.find_overview_entry({'hunt':'^狩猎$'})


def test_actual_runner_refills_after_last_stamina_task_in_dynamic_order(tmp_path,monkeypatch):
    calls=[];order=['cocoon','main','copies','tower','rewards'];selections=[]
    monkeypatch.setattr(flow.Backend,'connect',lambda _:None)
    monkeypatch.setattr(flow,'create_report',lambda:{'folder':tmp_path,'tasks':{},'events':[]})
    monkeypatch.setattr(flow.Daily,'home',lambda _:screen())
    monkeypatch.setattr(flow.Daily,'world_resources',lambda *_:{'stamina':0,'stamina_cap':164,'diamonds':200})
    monkeypatch.setattr(flow.Daily,'restore_world_team',lambda _:None)
    monkeypatch.setattr(flow.Daily,'save_state',lambda _:None)
    def select(self,pending):
        key=order[len(selections)];assert key in pending
        selections.append(key);return key
    monkeypatch.setattr(flow.Daily,'next_daily_task',select)
    for key in ['startup',*order]:
        monkeypatch.setattr(flow.Daily,key,lambda self,key=key:calls.append(key) or 'done')
    monkeypatch.setattr(flow.Daily,'replenish_stamina',lambda _:calls.append('refill') or 'done')
    result=flow.run_daily({'unordered_tasks':True},['startup',*order],threading.Event(),log=lambda _:None)
    assert result['status']=='completed' and result['execution_mode']=='overview'
    assert result['execution_order']==['startup',*order]
    assert calls==['startup','cocoon','main','copies','refill','tower','rewards']


def test_refilled_stamina_tasks_also_use_dynamic_selection(tmp_path):
    d=daily(tmp_path,{'unordered_tasks':True});d.selected=['main','copies'];balance=[0];calls=[]
    d.home=lambda:screen();d.world_resources=lambda _:{'stamina':balance[0],'stamina_cap':164}
    d.stamina_offer=lambda:screen(('领取奖励',650,590,120,35))
    d.stamina_outlet_available=lambda *a:True
    d.b.click_text=lambda *a,**kw:balance.__setitem__(0,balance[0]+100)
    d.observe=lambda:screen()
    def select(pending):calls.append(('select',tuple(pending)));return 'main' if 'main' in pending else 'copies'
    def run(task):calls.append(('run',task));balance[0]-=20
    d.next_daily_task=select;d.execute_task=run
    d.replenish_stamina()
    assert calls==[('select',('copies','main')),('run','main'),('select',('copies',)),('run','copies')]
    assert balance[0]==60 and d.report['stamina_claims']==1
