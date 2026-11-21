"""The reported glowing 35 node and a completed merchant on a copy route."""
import time
from types import SimpleNamespace
import pytest
import chao2.rift as rift
from chao2.backend import Screen
from chao2.policy import EncounterInterrupted,TaskBlocked,SafetyStop,UserStopped,FightLost
from chao2.activities import encounter_identity
from chao2.world_events import is_map_choice,map_choice_controls
from test_configuration import daily,screen,captured
from test_rift_main_0959 import offline_backend


def map_screen():
    return screen(('凿星裂痕',120,15,160,30),('凿星裂痕当前通关',500,5,280,30),
                  ('34',620,40,40,30),('匹配房间',1070,690,80,24),('创建队伍',1180,690,90,24),
                  ('35',529,476,21,19))


def test_real_failure_frame_has_wide35_but_one_empty_tight_crop(offline_backend):
    s=captured('v0986-rift-node35',True);b=offline_backend
    assert b.read_text_crop(s,(527,474,25,23))=='35'
    assert b.read_text_crop(s,(526,473,27,25))==''
    assert b.read_text_crop(s,(519,467,42,28))==b.read_text_crop(s,(519,469,42,28))=='35'
    assert rift.rift_node(b,s,35)==('next',(540,445))
    assert rift.rift_node(b,s,34)[0]=='open'
    assert rift.rift_node(b,s,36)[0]=='locked'


@pytest.mark.parametrize('remove_label',[False,True])
def test_real_glowing_node_rechecked_before_one_click_without_downgrade(tmp_path,monkeypatch,offline_backend,remove_label):
    s=captured('v0986-rift-node35',True)
    if remove_label:s.words=[w for w in s.words if w.text!='35']
    d=daily(tmp_path);d.b=offline_backend;clicks=[]
    d.observe=lambda:Screen(s.image,s.words,time.monotonic())
    d.rift_wait_detail=lambda stage:stage
    monkeypatch.setattr(d.b,'click_at',lambda q,p,a,r:clicks.append((p,r)))
    assert d.rift_open_stage(s,35)==35
    assert clicks==[((540,445),'打开裂痕35关')]
    assert not d.report.get('rift_fallbacks') and not d.report.get('rift_chests')


def node_backend(read):
    def recognize(_,spec,image):
        matches=[SimpleNamespace(box=(526,423,29,45),score=.95)] if 'next' in spec.template[0] else []
        result=SimpleNamespace(nodes=[SimpleNamespace(recognition=SimpleNamespace(filtered_results=matches))])
        return SimpleNamespace(get=lambda:result)
    return SimpleNamespace(tasker=SimpleNamespace(post_recognition=recognize),wait=lambda job,*a:job,read_text_crop=read)


@pytest.mark.parametrize('valid_group',['wide','tight'])
def test_each_crop_group_still_needs_two_exact_reads(valid_group):
    wide={(519,467,42,28),(519,469,42,28)}
    tight={(527,474,25,23),(526,473,27,25)}
    selected=wide if valid_group=='wide' else tight
    b=node_backend(lambda s,roi:'35' if tuple(roi) in selected else '')
    assert rift.rift_node(b,map_screen(),35)==('next',(540,445))


@pytest.mark.parametrize('answers',[('35','','35',''),('3','35','35','3'),('','','',''),('36','36','36','36')])
def test_global_label_or_single_crop_cannot_authorize_a_node(answers):
    rois=[(519,467,42,28),(519,469,42,28),(527,474,25,23),(526,473,27,25)]
    reads=dict(zip(rois,answers))
    assert rift.rift_node(node_backend(lambda s,roi:reads.get(tuple(roi),'')),map_screen(),35) is None


def world(balance):
    return screen(('任务挑战',1196,42,80,24),('世界回响',1196,138,80,24),(f'{balance}/187',500,12,85,28))


def copy_detail(name,balance):
    return screen(('敌方阵容',1100,120,120,30),('排阵',830,610,80,30),('挑战',1060,605,80,30),
                  ('可获得奖励',40,560,150,30),
                  (name,140,135,240,25),(f'{balance}/187',1175,17,90,24),('20',1096,639,28,18))


def choice():
    return screen(('请选择',720,360,70,30),('×',880,360,30,30),
                  ('复制体',740,495,70,25),('pending',700,530,150,25))


def copies_game(tmp_path,*,where='start',failure=None,fail_first_team=False,cap_after_event=False):
    d=daily(tmp_path,{'task_options':{'copies':{'teams':[2,1],'wandering_sage':False,
                                              'auto_three_shots':False}}})
    d.active_task='copies'
    state={'balance':160,'events':0,'wins':[],'fights':[],'selected':[],
           'page':world(160),'opens':[],'quota':(400,1000),'closes':0}
    d.b.sleep=lambda _:None;d.b.save_screen=lambda *a:None
    d.observe=lambda *a:state['page']
    def click(s,p,a,r,**kw):
        assert s.has(*a)
        if is_map_choice(s):
            assert p==map_choice_controls(s)[1].center;state['closes']+=1
        else:assert '返回' in r or '关闭' in r
        state['page']=world(state['balance'])
    d.b.click_at=click
    merchant=screen(('神秘商人',100,20,160,35),('掠夺',600,500,65,30),
                    ('交易',700,500,65,30),('物品奖励',800,500,120,30))
    def handled(s):
        state['events']+=1;state['balance']+=100;state['page']=choice()
        if cap_after_event:state['quota']=(1000,1000)
        return state['page']
    d.handle_merchant=handled
    def event():d.resolve_path_event(merchant)
    def targets(wanted,excluded):
        assert wanted=='any'
        if is_map_choice(state['page']):d.home(state['page'])
        for name,kind in [('already','own'),('pending','own'),('friend','friend')]:
            if name in excluded or name in d.report.get('copy_completed',[]):continue
            if kind=='friend' and state['quota'][0]>=state['quota'][1]:continue
            if name=='pending' and where=='list' and not state['events']:event()
            state['opens'].append(name)
            detail=copy_detail(name,state['balance']);state['page']=detail
            return {'identity':name,'kind':kind,'quota':state['quota'],'screen':detail}
    d.copy_targets=targets
    d.copy_kind=lambda s,quota:'friend' if encounter_identity(s)=='friend' and quota[0]<quota[1] else (
        'own' if encounter_identity(s)!='friend' else None)
    d.ensure_detail=lambda s:s
    d.verify_instant_setting=lambda *a:None
    def select(s,team):state['selected'].append((encounter_identity(s),team));return s
    d.select_team=select
    def start(task,s,*args):
        name=encounter_identity(s)
        if name=='pending':
            if failure is not None:raise failure
            if where=='always' or (where=='start' and not state['events'] and (
                    not fail_first_team or state['selected'][-1][1]==1)):event()
    d.start_challenge=start
    def fight(resource):
        assert resource=='地图体力20'
        name=encounter_identity(state['page']);team=state['selected'][-1][1]
        state['fights'].append((name,team));state['balance']-=20
        d.battles+=1;d.task_counts['copies']=d.task_counts.get('copies',0)+1
        d.resource_spent('copies','地图体力',20,state['balance'])
        if name=='pending' and team==2 and fail_first_team:raise FightLost(screen(('失败',100,200,200,60)))
        state['wins'].append(name)
        return screen(('胜利',100,200,200,60),('退出',1149,582,55,29))
    d.battle=fight;d.exit_result=lambda s:state.update(page=world(state['balance']))
    return d,state


@pytest.mark.parametrize('where',['start','list'])
def test_completed_merchant_resumes_fresh_list_without_replaying_done_copy(tmp_path,where):
    d,state=copies_game(tmp_path,where=where)
    d.execute_task('copies')
    assert d.report['tasks']['copies']['status']=='done'
    assert state['events']==1 and state['closes']==1
    assert state['wins']==d.report['copy_completed']==['already','pending','friend']
    assert d.task_counts['copies']==d.battles==3
    assert d.report['resource_usage']['copies']['地图体力']['spent']==60
    assert state['balance']==200 and len(d.report['copy_path_handoffs'])==1
    assert not d.report.get('copy_failed')


def test_resumed_copy_does_not_retry_a_team_that_already_lost(tmp_path):
    d,state=copies_game(tmp_path,fail_first_team=True)
    d.execute_task('copies')
    assert state['fights']==[('already',2),('pending',2),('pending',1),('friend',2)]
    assert d.task_counts['copies']==4 and state['events']==1
    assert sum(r['outcome']=='failed' for r in d.report['team_attempts'])==1
    assert d.report['tasks']['copies']['status']=='done'


def test_resume_rechecks_friend_cap_but_still_finishes_own_copies(tmp_path):
    d,state=copies_game(tmp_path,cap_after_event=True)
    d.execute_task('copies')
    assert state['wins']==['already','pending'] and state['events']==1
    assert not any(name=='friend' for name,_ in state['fights'])
    assert d.report['tasks']['copies']['status']=='done'


@pytest.mark.parametrize('failure',[TaskBlocked('目标页面未识别'),SafetyStop('费用未核实')])
def test_actual_task_failure_still_goes_back_and_runs_next_task(tmp_path,failure):
    d,state=copies_game(tmp_path,failure=failure);later=[]
    d.rewards=lambda:later.append('rewards') or '已继续领奖'
    d.execute_task('copies');d.execute_task('rewards')
    assert d.report['tasks']['copies']['status']=='blocked' and later==['rewards']
    assert state['fights']==[('already',2)] and state['events']==0
    assert not d.report.get('copy_path_handoffs')


def test_repeated_path_events_are_bounded_and_later_queue_still_runs(tmp_path):
    d,state=copies_game(tmp_path,where='always')
    d.rewards=lambda:'已继续领奖'
    d.execute_task('copies');d.execute_task('rewards')
    assert state['events']==3 and state['wins']==['already']
    assert len(d.report['copy_path_handoffs'])==3
    assert d.report['tasks']['copies']['status']=='blocked'
    assert d.report['tasks']['rewards']['status']=='done'


def test_user_stop_cannot_be_retried_as_a_handled_path_event(tmp_path):
    d,state=copies_game(tmp_path,failure=UserStopped('用户停止'))
    with pytest.raises(UserStopped):d.execute_task('copies')
    assert state['events']==0 and not d.report.get('copy_path_handoffs')


def test_real_post_merchant_overlap_can_be_closed_without_selecting_background_stage(tmp_path):
    d=daily(tmp_path);s=captured('v0986-copy-after-merchant',True);clicks=[]
    assert is_map_choice(s)
    d.observe=lambda:world(366)
    d.b.click_at=lambda q,p,a,r:clicks.append((p,r))
    assert d.home(s).find('^任务挑战$')
    assert clicks==[(map_choice_controls(s)[1].center,'收起地图重叠目标选择框')]
