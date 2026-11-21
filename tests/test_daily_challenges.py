"""Time gates, free quotas, opponent choice and settled daily progress."""
import threading
from datetime import datetime,timezone
import pytest
from test_configuration import captured,daily,screen
from chao2.daily_challenges import origin_is_open,arena_candidates,choose_opponent,arena_quota,origin_quota,rampage_buff
from chao2.configuration import normalize_settings
from chao2.policy import TaskBlocked,SafetyStop,IsolatedTaskError
import chao2.daily_challenges as challenges
import chao2.workflows as flow

@pytest.mark.parametrize('hour,minute,expected',[(19,59,False),(20,0,True),(21,59,True),(22,0,False),(0,0,False)])
def test_origin_beijing_window(hour,minute,expected):
    assert origin_is_open(datetime(2026,10,14,hour,minute,tzinfo=challenges.BEIJING)) is expected

def test_origin_converts_utc_and_rejects_ambiguous_naive_clock():
    assert origin_is_open(datetime(2026,10,14,12,0,tzinfo=timezone.utc))
    assert not origin_is_open(datetime(2026,10,14,14,0,tzinfo=timezone.utc))
    with pytest.raises(ValueError):origin_is_open(datetime(2026,10,14,20,0))

def test_closed_origin_is_skipped_when_its_task_executes(tmp_path,monkeypatch):
    d=daily(tmp_path);monkeypatch.setattr(challenges,'origin_is_open',lambda:False)
    d.enter_building=lambda *a:pytest.fail('Closed task must not navigate')
    d.execute_task('origin')
    assert d.report['tasks']['origin']['status']=='skipped'
    assert d.report['tasks']['origin']['attempts']==0

def test_closed_origin_method_never_navigates(tmp_path,monkeypatch):
    d=daily(tmp_path);monkeypatch.setattr(challenges,'origin_is_open',lambda:False)
    d.enter_building=lambda *a:pytest.fail('No navigation outside window')
    assert '跳过' in d.origin()

def test_real_arena_powers_not_integral_scores(monkeypatch):
    candidates=arena_candidates(captured('arena-menu'))
    assert [c['power'] for c in candidates]==[3588,3743,3607,3547]
    assert choose_opponent(candidates,'weakest')['index']==3
    monkeypatch.setattr(challenges.random,'choice',lambda rows:rows[1])
    assert choose_opponent(candidates,'random')['index']==1
    assert arena_quota(captured('arena-menu'))==10
    assert arena_quota(captured('arena-detail'))==10
    assert origin_quota(captured('origin-menu'))==13

def test_missing_power_never_selects_a_partial_list():
    s=captured('arena-menu');s.words=[w for w in s.words if w.text!='3743']
    with pytest.raises(TaskBlocked,match='第2个'):arena_candidates(s)

def test_invalid_opponent_setting_fails_before_game_input():
    with pytest.raises(ValueError):normalize_settings({'task_options':{'arena':{'opponent':'refresh'}}})
    with pytest.raises(ValueError):normalize_settings({'task_options':{'arena':{'opponent':False}}})

def test_real_rampage_buff_prefers_permanent_levels():
    button,text=rampage_buff(captured('rampage-progress'))
    assert button.center[0]>1000 and '等级提升80' in text

def test_partial_buff_screen_blocks_instead_of_clicking_unrelated_control():
    s=captured('rampage-progress');s.words=[w for w in s.words if not(w.text=='点击选择' and w.center[0]<400)]
    with pytest.raises(TaskBlocked):rampage_buff(s)

def test_four_digit_rampage_score_crop_never_truncates_to_three_digits(tmp_path):
    d=daily(tmp_path);s=captured('rampage-completed')
    for w in s.words:
        if w.text=='t564':w.text='t1564'
    crops=[]
    def read(s,roi):
        crops.append(roi);return None if len(crops)==1 else 1564
    d.b.read_number=read
    assert d.rampage_score(s)==1564
    assert crops[-1][2]>=62

def test_rampage_result_requires_actual_settlement_and_records_rewards(tmp_path):
    d=daily(tmp_path);s=captured('rampage-result',True)
    d.observe=lambda:s
    result=d.rampage_battle()
    assert result is s and d.report['rampage_settlement']=={'kills':564,'gold':317486}

def test_arena_checks_cost_and_opponent_before_click(tmp_path):
    d=daily(tmp_path);s=captured('arena-detail');target=arena_candidates(captured('arena-menu'))[3]
    d.read_arena_power=lambda *a:3547
    d.b.read_number=lambda *a:1
    assert d.verify_arena_detail(s,target)==10
    d.b.read_number=lambda *a:25
    with pytest.raises(TaskBlocked,match='费用'):d.verify_arena_detail(s,target)
    d.b.read_number=lambda *a:1
    with pytest.raises(TaskBlocked,match='对手'):d.verify_arena_detail(s,{'power':9999})

def arena_frame(quota):
    s=captured('arena-menu')
    for w in s.words:
        if w.text=='10/15':w.text=f'{quota}/15'
    return s

def arena_run(tmp_path,outcomes,monkeypatch):
    d=daily(tmp_path,{'task_options':{'arena':{'teams':[2,3],'opponent':'weakest'}}})
    menus=iter(arena_frame(i) for i in range(len(outcomes)-1,-1,-1))
    d.enter_building=lambda *a:arena_frame(len(outcomes))
    d.arena_detail=lambda:captured('arena-detail')
    d.read_arena_candidates=lambda s:(s,arena_candidates(s))
    counter=[len(outcomes)]
    d.verify_arena_detail=lambda *a:counter[0]
    used=[];d.select_team=lambda s,t,return_page=None:used.append(t) or s
    d.b.click_at=lambda *a:None;d.b.click_text=lambda *a:None
    d.b.read_text_crop=lambda s,roi:s.region_text((785,655,115,55))
    results=iter(outcomes)
    def battle(task):
        counter[0]-=1;d.task_counts[task]=d.task_counts.get(task,0)+1
        return None,next(results)
    d.pvp_battle=battle;d.exit_result=lambda s:None
    d.start_challenge=lambda *a:None  # Entry/recognition is tested separately.
    d.await_page=lambda *a:next(menus);d.home=lambda:None
    return d,used

def test_arena_consumes_verified_free_count_and_rotates_even_after_loss(tmp_path,monkeypatch):
    d,teams=arena_run(tmp_path,['failed','victory','victory'],monkeypatch)
    assert '3场' in d.arena()
    assert teams==[2,3,2] and d.report['arena_remaining']==0
    assert [x['outcome'] for x in d.report['team_attempts']]==['failed','victory','victory']

def test_arena_does_not_continue_if_free_count_does_not_decrease(tmp_path,monkeypatch):
    d,teams=arena_run(tmp_path,['victory'],monkeypatch)
    d.await_page=lambda *a:arena_frame(1)
    d.observe=lambda:arena_frame(1);d.b.sleep=lambda _:None
    with pytest.raises(TaskBlocked,match='次数变化'):d.arena()
    assert teams==[2] and d.report['team_attempts'][0]['quota_verified'] is False
    assert d.report['team_attempts'][0]['outcome']=='victory'

def test_single_team_is_not_reselected_between_each_round(tmp_path,monkeypatch):
    d,teams=arena_run(tmp_path,['victory','victory'],monkeypatch)
    d.options['arena']['teams']=[2]
    assert '2场' in d.arena() and teams==[2]

def test_zero_arena_count_never_selects_opponent(tmp_path):
    d=daily(tmp_path);d.enter_building=lambda *a:arena_frame(0);d.home=lambda:None
    d.b.read_text_crop=lambda s,roi:'0/15'
    d.b.click_at=lambda *a:pytest.fail('No tickets')
    assert '0场' in d.arena()

def test_disagreeing_local_power_recognition_is_not_silently_accepted(tmp_path):
    d=daily(tmp_path);s=captured('arena-slanted-power')
    values=iter(['74793','14393']);d.b.read_text_region=lambda *a,**kw:next(values)
    assert d.read_arena_power(s,challenges.ARENA_CARDS[0][0]) is None

def test_loading_arena_list_is_reobserved_without_extra_navigation(tmp_path):
    d=daily(tmp_path);bad=captured('arena-menu');bad.words=[]
    good=captured('arena-menu');d.observe=lambda:good;d.b.sleep=lambda s:None
    d.read_arena_power=lambda s,roi:int(s.region_text(roi))
    result,rows=d.read_arena_candidates(bad)
    assert result is good and len(rows)==4

def origin_frame(quota):
    s=captured('origin-menu')
    for w in s.words:
        if w.text=='13':w.text=str(quota)
    return s

def test_origin_free_quota_loop_and_ending_at_22(tmp_path,monkeypatch):
    d=daily(tmp_path);d.enter_building=lambda *a:origin_frame(2)
    gates=iter([True,True,True,False]);monkeypatch.setattr(challenges,'origin_is_open',lambda:next(gates))
    d.select_team=lambda s,t,return_page=None:s;clicks=[]
    d.b.click_text=lambda s,p:clicks.append(p);d.exit_result=lambda *a:None
    d.pvp_battle=lambda task:(None,'failed');d.await_page=lambda *a:origin_frame(1);d.home=lambda:None
    assert '已到22:00' in d.origin()
    assert clicks==['^匹配$'] and len(d.report['team_attempts'])==1

def test_origin_zero_quota_and_unreadable_quota_never_match(tmp_path,monkeypatch):
    d=daily(tmp_path);monkeypatch.setattr(challenges,'origin_is_open',lambda:True)
    d.enter_building=lambda *a:origin_frame(0);d.home=lambda:None
    d.b.click_text=lambda *a:pytest.fail('Do not match without free quota')
    assert '0场' in d.origin()
    d.enter_building=lambda *a:screen(('起源殿',120,10,80,30),('匹配',1032,631,98,49))
    d.observe=lambda:d.enter_building();d.b.sleep=lambda _:None
    with pytest.raises(TaskBlocked,match='免费次数'):d.origin()

def test_unknown_pvp_settlement_times_out_without_recording_success(tmp_path,monkeypatch):
    d=daily(tmp_path);clock=[0]
    monkeypatch.setattr(challenges.time,'monotonic',lambda:clock[0])
    d.observe=lambda:screen(('连接中',400,300,100,30));d.b.guard=lambda s:None
    d.b.sleep=lambda seconds:clock.__setitem__(0,clock[0]+seconds)
    with pytest.raises(IsolatedTaskError,match='回退后继续下一项'):d.pvp_battle('origin')
    assert not d.report.get('team_attempts')

def test_rank_promotion_is_dismissed_before_counting_victory(tmp_path):
    d=daily(tmp_path);promotion=screen(('段位提升',565,470,165,34))
    result=screen(('胜利',80,250,400,200),('退出',1150,582,55,30))
    frames=iter([promotion,result]);d.observe=lambda:next(frames)
    clicks=[];d.b.click_at=lambda s,p,anchors,reason:clicks.append((p,anchors))
    found,outcome=d.pvp_battle('arena')
    assert found is result and outcome=='victory'
    assert clicks==[((935,545),['^段位提升$'])]

def test_network_retry_is_bounded_and_never_confirms_an_unrelated_dialog(tmp_path):
    d=daily(tmp_path);clicks=[]
    d.b.click_text=lambda s,p,roi=None:clicks.append(p)
    retry=screen(('网络翻船中，是否重试?',490,299,283,26),('取消',454,480,55,32),('确定',769,481,56,31))
    assert d.retry_battle_network(retry,0)
    with pytest.raises(SafetyStop,match='重试两次'):d.retry_battle_network(retry,2)
    purchase=screen(('是否消耗钻石？',490,299,283,26),('取消',454,480,55,32),('确定',769,481,56,31))
    assert not d.retry_battle_network(purchase,0)
    assert clicks==['^确定$']

def test_existing_rampage_score_skips_without_starting_fight(tmp_path):
    d=daily(tmp_path);s=rampage_menu(550);d.enter_building=lambda *a:s
    d.b.click_text=lambda *a,**k:pytest.fail('Already on the challenge page')
    d.home=lambda:None
    assert '已有550' in d.nest()


def rampage_menu(score):
    return screen(('谜之巢穴',124,14,90,24),('暴走旷野',961,82,89,23),
                  ('最高击破数',1002,412,91,19),('我的排名',1000,382,76,23),
                  ('挑战',1086,497,66,35),(str(score),1209,412,25,21))


def rampage_result(value):
    return screen(('本场击破数',665,365,113,24),('本场金币奖励',665,411,135,23),
                  ('退出',1149,582,55,29),(value,1057,365,148,22))


def test_rampage_retries_stale_score_until_observing_a_real_settlement(tmp_path):
    d=daily(tmp_path,{'task_options':{'nest':{'teams':[2],'repeat_challenge':True}}})
    ready=rampage_menu(550);done=rampage_result('467');launches=[];copies=[];exits=[]
    d.enter_building=lambda *a:ready
    d.apply_saved_team=lambda s,team:copies.append(team) or s
    d.start_challenge=lambda task,s,resource:launches.append(s)
    d.exit_result=lambda s:exits.append(s) or ready
    rounds=iter([ready,done]);d.battle_frames=lambda *a,**k:iter([next(rounds)])
    d.battle_return_page=lambda *a:True
    d.home=lambda:None
    assert '已完成1场' in d.nest()
    assert launches==[ready,ready] and copies==[2] and exits==[done]
    assert len(d.report['team_attempts'])==1 and d.report['team_attempts'][0]['kills']==467


def test_rampage_cross_day_restarts_from_current_lobby_and_records_new_day(tmp_path,monkeypatch):
    class Clock:
        @staticmethod
        def now(tz):return datetime(2026,11,21,0,9,tzinfo=tz)

    monkeypatch.setattr(challenges,'datetime',Clock)
    d=daily(tmp_path,{'task_options':{'nest':{'repeat_challenge':True}}})
    d.date='2026-11-20';d.day=d.state.setdefault(d.date,{})
    before=rampage_menu(1304);next_day=rampage_menu(0);after=rampage_menu(620)
    invalid=rampage_result('无法跨天结算');valid=rampage_result('新纪录620')
    d.enter_building=lambda *a:before
    launches=[];d.start_challenge=lambda task,s,resource:launches.append(s)
    rounds=iter([invalid,valid]);d.battle_frames=lambda *a,**k:iter([next(rounds)])
    def leave(s):
        if s is invalid:assert d.report['rampage_settlement']['status']=='cross_day'
        return next_day if s is invalid else after
    d.exit_result=leave;d.home=lambda:None
    assert '已完成1场，今日最高击破620' in d.nest()
    assert launches==[before,next_day] and d.task_counts['nest']==2
    assert not d.day.get('rampage_done') and d.state['2026-11-21']['rampage_done']
    assert any('无法跨天结算，补打' in event['message'] for event in d.report['events'])


@pytest.mark.parametrize('returns_to_territory',[False,True])
def test_gift_interrupting_nest_entry_keeps_the_mode_step(tmp_path,monkeypatch,returns_to_territory):
    from chao2.policy import PageChanged

    d=daily(tmp_path);d.active_task='nest';menu=rampage_menu(0)
    selector=screen(('谜之巢穴',124,14,90,24),('暴走旷野',592,620,98,40))
    gift=screen(('限时星礼',110,15,126,40),('三色孢子星礼',175,300,140,36),('核心延能星礼',495,300,140,36))
    territory=screen(('世界',1193,677,75,26),('永生之茧',858,209,107,26))
    state=[selector];clicks=[];reopened=[];clock=[0]
    monkeypatch.setattr('chao2.navigation_retry.time.monotonic',lambda:clock[0])
    d.b.guard=lambda s:None;d.b.sleep=lambda seconds:clock.__setitem__(0,clock[0]+seconds)
    d.observe=lambda:state[0];d.b.observe=lambda:state[0]
    d.home=lambda:pytest.fail('Resume in the nest selector')
    def enter(*args,source):
        assert source is territory
        reopened.append(source);state[0]=selector
        return selector
    d.enter_building=enter
    def choose(s,p,**kwargs):
        assert s is selector
        clicks.append(p)
        if clicks.count(p)==1:raise PageChanged(p,gift)
        state[0]=menu
    d.b.click_text=choose
    def close(*a):
        clicks.append('关闭礼包');state[0]=territory if returns_to_territory else selector
    d.b.click_at=close
    assert d.rampage_ready(selector) is menu
    assert clicks==['^暴走旷野$','关闭礼包','^暴走旷野$']
    assert len(reopened)==int(returns_to_territory)
    assert d.report['dismissed_offers'][0]['task']=='nest'

def test_rampage_gift_returning_to_buff_continues_same_battle(tmp_path):
    d=daily(tmp_path);d.active_task='nest'
    gift=screen(('限时星礼',110,15,126,40),('三色孢子星礼',175,300,140,36),('核心延能星礼',495,300,140,36))
    buff=screen(('请选择一个暴走增益',450,120,360,36))
    done=rampage_result('620');current=[gift];events=[]
    d.b.observe=lambda *a:current[0]
    def close(s,p,anchors,reason):
        assert s is gift and p==(43,28)
        events.append('gift');current[0]=buff
    def choose(s):
        assert s is buff
        events.append('buff');current[0]=done
    d.b.click_at=close;d.choose_rampage_buff=choose
    assert d.rampage_battle() is done
    assert events==['gift','buff'] and d.task_counts['nest']==1


def test_rampage_settled_once_records_daily_and_preserves_current_team(tmp_path):
    d=daily(tmp_path);s=rampage_menu(0);d.enter_building=lambda *a:s
    after=rampage_menu(620);d.rampage_battle=lambda:after
    d.exit_result=lambda *a:pytest.fail('The result was already closed')
    d.start_challenge=lambda *a:None
    d.apply_saved_team=lambda *a:pytest.fail('Keep existing formation and ally by default')
    d.home=lambda:None
    assert '620' in d.nest()
    assert len(d.report['team_attempts'])==1
