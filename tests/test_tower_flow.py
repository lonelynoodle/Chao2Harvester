"""Tower navigation, shared feathers and secret scope use a simulated device."""
import re

import pytest

from test_configuration import daily,screen,captured
from chao2.activities import secret_candidates,secret_locked_nodes,tower_floor_number,is_tower_secret_list
from chao2.policy import TaskBlocked


KINDS=[{'id':'normal','label':'无限制','enabled':True},
       {'id':'dragon','label':'祖龙族','enabled':True},
       {'id':'puppet','label':'木偶族','enabled':True}]


class TowerGame:
    def __init__(self,tmp_path,balance=4,teams=(1,),reserve=0,failures=(),next_mode='battle',max_runs=0):
        self.d=daily(tmp_path,{'task_options':{'tower':{'teams':list(teams),'reserve_feathers':reserve,
            'towers':KINDS,'secret_garden':True,'max_runs':max_runs}}})
        self.balance=balance;self.kind=KINDS[0];self.team=None;self.floors={k['id']:1 for k in KINDS}
        self.failures=set(failures);self.page='map';self.passed=True;self.next_mode=next_mode
        self.opened=[];self.secrets=[];self.selected=[];self.challenges=[];self.next_clicks=0
        self.exits=0;self.detail_entries=0;self.home_calls=0
        d=self.d;d.open_tower=self.open;d.home=self.home;d.select_team=self.select
        d.tower_secrets=lambda k,a:self.secrets.append(k['id']) or 1
        d.observe=self.observe;d.await_detail=self.observe
        d.b.click_at=self.click_at;d.b.click_text=self.click_text;d.b.sleep=lambda _:None
        d.b.tasker=object()
        d.b.read_text_region=lambda *a,**kw:f'{self.balance}/20'

    def home(self):self.home_calls+=1

    def open(self,kind):
        self.opened.append(kind['id']);self.kind=kind;self.page='map'
        return self.observe()

    def select(self,s,team):self.team=team;self.selected.append((self.kind['id'],team));return s

    def observe(self,*args):
        n=self.floors[self.kind['id']]
        resource=(f'{self.balance}/20',1210,15,60,26)
        if self.page=='result':
            words=[('胜利' if self.passed else '挑战失败',100,200,100,30),
                   ('获得奖励',900,300,100,30),('退出',1140,580,60,30),resource]
            if self.passed and self.next_mode!='absent':words.append(('怼下一关',880,580,110,30))
            return screen(*words)
        if self.page=='detail':
            prefix='' if self.kind['id']=='normal' else self.kind['label']+'-'
            return screen((prefix+f'浮空巨塔{n}',233,105,300,28),('敌方阵容',1040,110,100,28),
                          ('首通奖励',174,555,74,23),('排阵',702,611,62,36),('挑战',946,601,62,36),resource)
        return screen(('浮空巨塔',124,14,90,30),(str(n),270,218,120,44),
                      ('已通关',290,360,80,28),(str(n-1),269,400,120,44),
                      (f'{self.balance}/20',1124,15,56,26))

    def click_at(self,s,point,anchors,reason):
        assert point[0]==505,'Unexpected tower/world navigation: '+reason
        self.detail_entries+=1;self.page='detail'

    def start(self):
        assert self.balance>0
        key=(self.kind['id'],self.floors[self.kind['id']],self.team)
        self.challenges.append(key);self.balance-=1;self.page='result'
        self.passed=key not in self.failures

    def click_text(self,s,pattern,**kwargs):
        assert s.find(pattern),pattern
        if '下一' in pattern:
            self.next_clicks+=1;self.floors[self.kind['id']]+=1
            if self.next_mode=='detail':self.page='detail'
            else:self.start()
        elif '退出' in pattern:
            self.exits+=1;self.page='map'
            if self.passed:self.floors[self.kind['id']]+=1
        else:
            assert '挑战' in pattern
            self.start()


@pytest.mark.parametrize('mode',['battle','detail'])
def test_continuous_floors_use_next_button_and_one_team_selection(tmp_path,mode):
    game=TowerGame(tmp_path,next_mode=mode)
    assert game.d.tower()=='巨塔通关4层，秘庭3关；停止原因：浮空羽毛剩余0，已用完'
    assert game.next_clicks==3 and game.detail_entries==1 and game.exits==0
    assert game.selected==[('normal',1)] and game.opened==['normal']
    assert game.secrets==['normal','dragon','puppet'] and game.home_calls==1
    assert game.d.report['dungeon_resources']['tower']['remaining']==0
    assert game.d.task_counts['tower']==4


def test_missing_next_button_returns_only_to_current_tower_map(tmp_path):
    game=TowerGame(tmp_path,balance=3,next_mode='absent')
    game.d.tower()
    assert game.opened==['normal'] and game.detail_entries==3 and game.exits==2
    assert game.home_calls==1 and game.selected==[('normal',1)]


def test_failure_rotates_locally_then_next_floor_restarts_team_priority(tmp_path):
    game=TowerGame(tmp_path,balance=4,teams=(1,2),failures={('normal',1,1)})
    game.d.tower()
    assert game.challenges==[('normal',1,1),('normal',1,2),('normal',2,1),('normal',3,1)]
    assert game.opened==['normal'] and game.secrets==['normal','dragon','puppet']
    assert game.selected==[('normal',1),('normal',2),('normal',1)]


def test_all_teams_fail_switches_tower_and_checks_selected_secrets(tmp_path):
    game=TowerGame(tmp_path,balance=4,teams=(1,2),failures={('normal',1,1),('normal',1,2)})
    game.d.tower()
    assert game.opened==['normal','dragon'] and game.secrets==['normal','dragon','puppet']
    assert game.challenges[-2:]==[('dragon',1,1),('dragon',2,1)]
    assert game.d.report['tower_visited']==['normal','dragon']


def test_failed_floor_checks_its_secret_before_the_next_tower(tmp_path):
    game=TowerGame(tmp_path,balance=4,teams=(1,),
                   failures={('normal',1,1)},next_mode='absent')
    order=[];open_tower=game.d.open_tower
    def open_and_record(kind):
        order.append(('tower',kind['id']))
        return open_tower(kind)
    def secret_and_record(kind,attempted):
        order.append(('secret',kind['id']))
        return 1
    game.d.open_tower=open_and_record
    game.d.tower_secrets=secret_and_record
    game.d.tower()
    assert order[:4]==[('tower','normal'),('secret','normal'),
                       ('tower','dragon'),('secret','dragon')]
    assert game.challenges[0]==('normal',1,1)
    assert game.challenges[1][0]=='dragon'


@pytest.mark.parametrize('balance,reserve',[(0,0),(3,3),(2,5)])
def test_shared_feathers_at_reserve_skip_floors_and_check_selected_secrets(tmp_path,balance,reserve):
    game=TowerGame(tmp_path,balance=balance,reserve=reserve)
    game.d.tower()
    assert game.opened==['normal'] and not game.challenges
    assert game.balance==balance and game.secrets==['normal','dragon','puppet']


def test_last_feather_loss_stops_team_rotation_and_other_towers(tmp_path):
    game=TowerGame(tmp_path,balance=4,reserve=3,teams=(1,2),failures={('normal',1,1)})
    game.d.tower()
    assert game.challenges==[('normal',1,1)] and game.balance==3
    assert game.opened==['normal'] and game.secrets==['normal','dragon','puppet']


def test_budget_blocks_next_click_before_it_can_consume_an_extra_feather(tmp_path):
    game=TowerGame(tmp_path,balance=5,max_runs=2)
    game.d.tower()
    assert len(game.challenges)==2 and game.balance==3 and game.next_clicks==1
    assert not game.secrets


def test_disabled_secrets_stay_disabled_after_spending_all_feathers(tmp_path):
    game=TowerGame(tmp_path,balance=1);game.d.options['tower']['secret_garden']=False
    game.d.tower()
    assert not game.secrets


@pytest.mark.parametrize('max_runs',[0,1])
def test_zero_feathers_still_starts_and_settles_an_unlocked_free_secret(tmp_path,max_runs):
    d=daily(tmp_path,{'task_options':{'tower':{'towers':[KINDS[0]],'max_runs':max_runs}}})
    floors=screen(('浮空巨塔',124,14,90,30),('塔中秘庭31',950,580,160,36))
    ready=screen(('浮空巨塔',124,14,90,30),('塔中秘庭31',240,450,140,30),
                 ('塔中秘庭32',650,450,140,30))
    ready.image[310:365,275:346]=(235,210,160)
    ready.image[310:365,685:756]=(185,160,145)
    settled=screen(*[(w.text,*w.box) for w in ready.words])
    settled.image[310:365,685:756]=(185,160,145)
    detail=screen(('塔中秘庭31',220,103,160,30),('敌方阵容',1025,112,100,30),
                  ('首通奖励',174,555,74,23),('排阵',702,611,62,36),('挑战',946,613,62,36))
    result=screen(('胜利',100,200,100,30),('获得奖励',900,300,100,30),('退出',1140,580,60,30))
    current=[floors];actions=[]
    d.open_tower=lambda kind:current[0]
    d.observe=lambda *a:current[0]
    d.b.tasker=object();d.b.read_text_region=lambda *a,**kw:'0/20'
    d.b.sleep=lambda _:None;d.home=lambda:None
    def click_text(s,pattern,**kw):
        assert s is current[0] and s.find(pattern)
        actions.append(pattern)
        if s is floors:current[0]=ready
        elif s is detail:current[0]=result
        else:
            assert s is result
            current[0]=settled
    def click_node(s,point,anchors,reason):
        assert s is ready and reason=='打开已稳定的塔中秘庭31'
        current[0]=detail
    d.b.click_text=click_text;d.b.click_at=click_node
    message=d.tower()
    assert '巨塔通关0层，秘庭1关' in message
    if max_runs:assert '达到该玩法设置的挑战次数' in message
    assert actions==['^塔中秘庭31$','^挑战$|^前往挑战$','^退出$']
    assert d.task_counts['tower']==1
    assert d.report['resource_usage']['tower']['浮空羽毛']['spent']==0


def test_real_secret_nodes_remain_available_without_new_unlock_label():
    seen=captured('tower-secrets-seen',True)
    assert not seen.find('^新解锁$') and is_tower_secret_list(seen)
    assert secret_candidates(seen)==['塔中秘庭32','塔中秘庭33','塔中秘庭34']
    assert secret_candidates(captured('secret-detail',True))==['塔中秘庭31','塔中秘庭32']
    assert secret_locked_nodes(captured('secret-detail',True))==['塔中秘庭33']
    assert secret_locked_nodes(seen)==[]


def test_race_tower_title_and_free_secret_layout_from_real_screens(tmp_path):
    puppet=captured('tower-puppet-detail')
    assert tower_floor_number(puppet,KINDS[2])==6
    assert tower_floor_number(puppet,KINDS[0]) is None
    d=daily(tmp_path);d.verify_tower_secret(captured('tower-secret-free'),'塔中秘庭32')
    with pytest.raises(TaskBlocked):d.verify_tower_secret(puppet,'塔中秘庭32')
    assert captured('tower-next-result').find(r'下一[关层]$')


def test_next_transition_does_not_accept_the_old_result_with_background_auto_text(tmp_path):
    d=daily(tmp_path);d.b.sleep=lambda _:None;clicks=[]
    old=screen(('胜利',100,200,100,30),('退出',1140,580,60,30),('怼下一关',880,580,110,30),
               ('自动',100,30,60,30),('3/20',1210,15,60,26))
    combat=screen(('自动',100,30,60,30))
    frames=iter([old,old,combat]);d.observe=lambda:next(frames)
    d.b.click_text=lambda *a,**kw:clicks.append(a)
    result,started=d.tower_advance(old,KINDS[0],2)
    assert started and result is combat and len(clicks)==1


def test_unchanged_next_click_has_three_verified_retries_then_stops(tmp_path):
    d=daily(tmp_path);d.b.sleep=lambda _:None;clicks=[]
    old=captured('tower-next-result');d.observe=lambda:old
    d.b.click_text=lambda *a,**kw:clicks.append(a)
    with pytest.raises(TaskBlocked,match='已重试3次'):d.tower_advance(old,KINDS[0],201)
    assert len(clicks)==4 and len(d.report['navigation_retries'])==3


def test_known_lock_boundary_stops_scrolling_after_current_unlocked_nodes_checked(tmp_path):
    d=daily(tmp_path);s=captured('secret-detail',True)
    d.open_tower=lambda kind:s;d.tower_secret_list=lambda *a:s;d.b.sleep=lambda _:None
    d.play_encounter=lambda *a,**kw:pytest.fail('Already attempted nodes must not be repeated')
    # The real list also contains locked 33. A controller is deliberately absent:
    # trying to swipe farther right would fail this test.
    assert d.tower_secrets(KINDS[0],{'塔中秘庭31','塔中秘庭32'})==0


def test_secret_node_waits_for_swipe_to_settle_and_uses_new_position(tmp_path):
    d=daily(tmp_path);d.b.sleep=lambda _:None
    def secret_map(x):
        s=screen(('浮空巨塔',124,14,90,30),('塔中秘庭76',190,540,140,36),
                 ('塔中秘庭77',x-70,360,140,36))
        s.image[223:278,x-35:x+36]=[235,210,160]
        return s
    frames=iter([secret_map(510),secret_map(508)])
    d.observe=lambda:next(frames)
    clicked=[]
    d.b.click_at=lambda s,point,anchors,reason:clicked.append((point,reason))
    d.click_tower_secret_node(secret_map(900),'塔中秘庭77')
    assert clicked==[((508,378),'打开已稳定的塔中秘庭77')]


def test_secret_node_disappearing_after_swipe_is_never_clicked(tmp_path):
    d=daily(tmp_path);d.b.sleep=lambda _:None
    moving=screen(('浮空巨塔',124,14,90,30),('塔中秘庭76',190,540,140,36),
                  ('塔中秘庭77',830,360,140,36))
    moving.image[223:278,865:936]=[235,210,160]
    locked=screen(('浮空巨塔',124,14,90,30),('塔中秘庭76',190,540,140,36),
                  ('塔中秘庭77',438,360,140,36))
    d.observe=lambda:locked
    d.b.click_at=lambda *args:pytest.fail('A locked or vanished node must not be clicked')
    with pytest.raises(TaskBlocked,match='持续移动或未解锁'):
        d.click_tower_secret_node(moving,'塔中秘庭77')


def test_secret_ocr_suffix_does_not_create_a_false_floor():
    s=screen(('塔中秘庭7695',190,540,190,36))
    s.image[403:458,250:321]=[235,210,160]
    assert secret_candidates(s)==[]


def test_slow_secret_overlay_does_not_toggle_entrance_twice(tmp_path):
    d=daily(tmp_path);d.b.sleep=lambda _:None;clicks=[]
    base=screen(('浮空巨塔',124,14,90,30),('塔中秘庭32',952,582,164,36))
    opened=captured('tower-secrets-seen',True)
    frames=iter([base,base,opened]);d.observe=lambda:next(frames)
    d.b.click_text=lambda *a,**kw:clicks.append(a)
    assert d.tower_secret_list(base) is opened and len(clicks)==1


def test_slow_detail_return_does_not_send_a_second_back_to_world(tmp_path):
    d=daily(tmp_path);d.b.sleep=lambda _:None;clicks=[]
    detail=captured('tower-puppet-detail');base=captured('tower-map')
    frames=iter([detail,detail,base,base]);d.observe=lambda:next(frames)
    d.b.click_at=lambda *a:clicks.append(a)
    assert d.tower_map(detail) is base and len(clicks)==1
