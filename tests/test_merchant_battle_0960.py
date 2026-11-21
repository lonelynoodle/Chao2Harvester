"""Merchant combat is settled inside its event, never as the original task."""
from types import SimpleNamespace
import pytest
from test_configuration import captured,screen
from test_merchant_event import setup,page,world
from chao2.backend import Word
from chao2.merchant import (merchant_choices,merchant_battle_phase,merchant_action,
                            merchant_return_page,is_merchant_reward)
from chao2.policy import TaskBlocked,UserStopped,EncounterInterrupted,SafetyStop


def choice():
    s=page('choice');old=merchant_choices(s)
    s.words=[w for w in s.words if w not in old]
    s.words.extend([Word('战斗',[830,100,80,35],.99),Word('离开',[830,205,80,35],.99)])
    return s


def combat():
    return screen(('00:11',590,5,110,35),('自动',80,590,70,35),('神秘商人',1120,5,140,30))


def reward():
    return screen(('获得奖励',520,135,220,45),('点击空白位置关闭',500,620,280,30))


class Event:
    def __init__(self,tmp_path,monkeypatch,*,outcome='victory',ticks=18,followup=True,swallowed=False):
        self.d,self.clicks=setup(tmp_path);self.d.active_task='main'
        self.d.b.settings['merchant_options']['mode']='random'
        self.phase='choice';self.ticks=ticks;self.outcome=outcome
        self.followup=followup;self.swallowed=swallowed;self.exits=0;self.waits=0
        monkeypatch.setattr('chao2.merchant.random.choice',lambda rows:next(w for w in rows if w.text=='战斗'))
        self.d.observe=self.observe;self.d.b.click_at=self.click;self.d.b.click_text=self.click_text
        self.d.resource_balance('main','地图体力',194)
    def observe(self,*args,**kwargs):
        if self.phase=='choice':return choice()
        if self.phase=='combat':
            self.waits+=1
            if self.waits>self.ticks:self.phase='result'
            else:return screen() if self.waits in (1,3) else combat()
        if self.phase=='result':return captured('v0960-merchant-victory' if self.outcome=='victory' else 'main-defeat')
        if self.phase=='farewell':return page('intro')
        if self.phase=='reward':return reward()
        return world()
    def click(self,s,point,anchors,reason,**kwargs):
        assert s.has(*anchors)
        self.clicks.append(reason)
        if self.phase=='choice':
            assert reason=='神秘商人随机选择：战斗';self.phase='combat'
        elif self.phase=='farewell':
            assert reason=='继续神秘商人对话';self.phase='reward'
        elif self.phase=='reward':
            assert reason=='关闭神秘商人奖励后继续';self.phase='world'
        else:pytest.fail('Unexpected combat input: '+reason)
    def click_text(self,s,pattern,*args,**kwargs):
        assert self.phase=='result' and pattern=='^退出$' and s.find(pattern)
        self.exits+=1;self.clicks.append('退出')
        if self.swallowed and self.exits==1:return
        self.phase='farewell' if self.followup else 'world'
    def run(self):return self.d.handle_merchant(self.observe())
    @property
    def row(self):return self.d.report['merchant_events'][0]


def test_captured_merchant_victory_is_a_result_and_not_a_dialogue_reward():
    s=captured('v0960-merchant-victory',True)
    assert merchant_battle_phase(s)=='result'
    assert not is_merchant_reward(s,battle_finished=True)
    assert merchant_return_page(s) is None


@pytest.mark.parametrize('s',[choice(),page('intro'),page('shop'),reward(),world(),screen(),
    screen(('战斗',830,100,80,35)),screen(('自动',80,590,70,35))])
def test_choices_tags_rewards_and_unknown_frames_do_not_start_combat_handler(s):
    assert merchant_battle_phase(s) is None


@pytest.mark.parametrize('outcome,ticks,followup,swallowed',[
    ('victory',18,True,False),('victory',0,False,False),
    ('failed',18,True,False),('failed',0,False,False),('victory',2,True,True)])
def test_random_combat_settles_then_handles_followup_without_counting_main(tmp_path,monkeypatch,outcome,ticks,followup,swallowed):
    g=Event(tmp_path,monkeypatch,outcome=outcome,ticks=ticks,followup=followup,swallowed=swallowed)
    assert merchant_return_page(g.run())=='world'
    assert g.row['status']=='completed' and g.row['battle_count']==1
    assert g.row['battles'][0]['status']=='settled' and g.row['battles'][0]['outcome']==outcome
    assert g.d.active_task=='main' and g.d.battles==0 and not g.d.task_counts
    assert not g.d.report.get('team_attempts') and not g.d.report.get('battles')
    assert g.d.report['resource_usage']['main']['地图体力']['spent']==0
    assert g.exits==1+int(swallowed)
    assert g.clicks.count('神秘商人随机选择：战斗')==1
    assert all(r['task']=='merchant' for r in g.d.report['result_exits'])
    if followup:
        assert g.row['rewards_closed']==1 and g.row['rewards'][0]['status']=='closed'
        assert g.clicks[-2:]==['继续神秘商人对话','关闭神秘商人奖励后继续']


def test_untitled_post_battle_reward_requires_event_battle_context(tmp_path):
    d,_=setup(tmp_path);s=reward()
    assert merchant_action(d.b,s,'random',{}) is None
    assert merchant_action(d.b,s,'random',{},battle_finished=True)[0]=='reward'
    s.words+=screen(('是否购买',400,300,200,40),('取消',400,440,90,40)).words
    with pytest.raises(SafetyStop):d.b.guard(s)


def test_combat_does_not_exhaust_dialogue_idle_or_duration_limits(tmp_path,monkeypatch):
    import chao2.merchant as merchant
    import chao2.battle_takeover as takeover
    g=Event(tmp_path,monkeypatch,ticks=26);clock=[0]
    clock_module=SimpleNamespace(monotonic=lambda:clock[0])
    monkeypatch.setattr(merchant,'time',clock_module);monkeypatch.setattr(takeover,'time',clock_module)
    g.d.b.settings['battle_timeout_seconds']=360
    g.d.b.sleep=lambda seconds:clock.__setitem__(0,clock[0]+(10 if g.phase=='combat' else seconds))
    g.run()
    assert clock[0]>240 and g.row['status']=='completed' and g.row['rewards_closed']==1


def test_merchant_long_battle_extends_configured_timeout_and_restores_task(tmp_path,monkeypatch):
    import chao2.battle_takeover as takeover
    g=Event(tmp_path,monkeypatch,ticks=18);clock=[0]
    monkeypatch.setattr(takeover,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    g.d.b.settings['battle_timeout_seconds']=4
    g.d.b.sleep=lambda seconds:clock.__setitem__(0,clock[0]+seconds)
    g.run()
    assert clock[0]>4 and g.d.active_task=='main' and g.exits==1
    assert g.row['status']=='completed' and g.d.report['battle_wait_extensions']
    assert g.d.task_counts=={}


def test_stop_in_combat_propagates_without_extra_input(tmp_path,monkeypatch):
    g=Event(tmp_path,monkeypatch,ticks=1000)
    def sleep(_):
        if g.waits>4:g.d.b.stop.set()
    g.d.b.sleep=sleep
    with pytest.raises(UserStopped):g.run()
    assert g.d.active_task=='main' and g.row['status']=='stopped'
    assert g.row['battles'][0]['status']=='stopped' and g.exits==0
    assert g.clicks==['神秘商人随机选择：战斗']


def test_missing_result_return_is_recorded_unknown_not_a_merchant_victory(tmp_path,monkeypatch):
    g=Event(tmp_path,monkeypatch,ticks=1000,followup=False);observe=g.observe
    def returned(*args,**kwargs):
        if g.waits>5:g.phase='world'
        return observe(*args,**kwargs)
    g.d.observe=returned
    g.run()
    battle=g.row['battles'][0]
    assert battle['status']=='returned_without_result' and battle['outcome'] is None
    assert g.row['status']=='completed' and g.exits==0


def test_original_battle_is_interrupted_after_merchant_combat_not_marked_won(tmp_path,monkeypatch):
    g=Event(tmp_path,monkeypatch,ticks=2,followup=False)
    with pytest.raises(EncounterInterrupted):g.d.battle('主线体力5')
    assert g.row['status']=='completed' and g.row['battles'][0]['outcome']=='victory'
    assert g.d.battles==0 and g.d.task_counts['main']==0
    assert not g.d.report.get('battles') and not g.d.report.get('team_attempts')


def test_main_start_keeps_original_target_when_merchant_battle_interrupts(tmp_path,monkeypatch):
    g=Event(tmp_path,monkeypatch,ticks=2,followup=False)
    detail=captured('v0959-main-blocked');click_text=g.d.b.click_text
    def click(s,pattern,*args,**kwargs):
        if '前往挑战' in pattern:return
        return click_text(s,pattern,*args,**kwargs)
    g.d.b.click_text=click
    with pytest.raises(EncounterInterrupted):g.d.start_challenge('main',detail,'主线体力5')
    assert g.d._main_interrupted_target=='639'
    assert g.d.report['challenge_starts'][0]['status']=='interrupted'
    assert g.d.task_counts=={} and g.d.battles==0 and g.row['status']=='completed'
