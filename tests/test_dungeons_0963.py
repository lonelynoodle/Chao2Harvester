"""Actual zero-point/timed forest challenges and flickering rift node OCR."""
import pytest
from test_configuration import daily,captured,screen
from test_rift_node_0961 import backend as offline_backend
from test_rift import fake_rift
from chao2.forest import forest_nodes,forest_timer,pick_simple_forest_node,select_forest_node
from chao2.rift import rift_node
from chao2.page_recovery import navigation_failure
from chao2.policy import TaskBlocked,UserStopped


def test_real_zero_point_map_has_both_challenges_including_lower_label(tmp_path):
    d=daily(tmp_path);s=captured('v0963-forest-zero-ready',True)
    ready=[n for n in forest_nodes(d.b,s) if n.action=='challenge']
    assert len(ready)==2 and any(n.point[1]>=615 for n in ready)
    assert pick_simple_forest_node(ready,0,0).action=='challenge'


def test_real_timer_and_lower_free_challenge_coexist(tmp_path):
    d=daily(tmp_path);s=captured('v0963-forest-timed-challenge',True)
    assert forest_timer(s)==1799  # Clock icon was merged as ')00:29:59'.
    ready=forest_nodes(d.b,s)
    assert len(ready)==1 and ready[0].action=='challenge' and ready[0].point[1]==620
    assert select_forest_node(ready,d.options['forest'],0,waiting=True) is ready[0]


def test_lower_challenge_is_locally_reread_when_full_frame_ocr_misses_it(offline_backend):
    s=captured('v0963-forest-timed-challenge',True)
    s.words=[w for w in s.words if w.text!='挑战']
    nodes=forest_nodes(offline_backend,s)
    assert len(nodes)==1 and nodes[0].action=='challenge' and nodes[0].point[1]>=615


@pytest.mark.parametrize('mode',['simple','advanced'])
@pytest.mark.parametrize('restriction',['zero','timer','reserve','exploration_limit'])
def test_free_fights_survive_exploration_restrictions(tmp_path,monkeypatch,mode,restriction):
    import chao2.forest as module
    d=daily(tmp_path);s=captured('v0963-forest-zero-ready',True);fights=[]
    d.options['forest'].update(mode=mode,collect_resources=False)
    d.forest_map=lambda:s;d.home=lambda:None;d.forest_scan=lambda q:q
    if restriction=='timer':d.forest_overview_state='探索中'
    if restriction=='reserve':d.options['forest']['reserve_points']=3
    if restriction=='exploration_limit':
        d.options['forest']['max_explorations']=1
        d.report['forest_explorations']=[{'status':'confirmed'}]
    balance=0 if restriction=='zero' else 3
    monkeypatch.setattr(module,'forest_points',lambda *_:balance)
    initial=forest_nodes(d.b,s)
    monkeypatch.setattr(module,'forest_nodes',lambda *_:[n for n in initial if n.point not in fights])
    d.forest_simple_pan=lambda q,*_:(q,False)
    d.forest_explore=lambda *_:pytest.fail('No exploration input allowed')
    def fight(q,n):
        fights.append(n.point)
        q.words=[w for w in q.words if w.center!=n.point]
        d.forest_ignored.append(n.world);d.forest_pool=[]
        d.report.setdefault('team_attempts',[]).append({'task':'forest','outcome':'victory'})
        return q
    d.forest_challenge=fight
    d.forest()
    assert len(fights)==2 and len(set(fights))==2


def test_zero_points_scans_other_pages_for_free_challenge(tmp_path,monkeypatch):
    import chao2.forest as module
    d=daily(tmp_path);d.options['forest'].update(mode='simple',collect_resources=False)
    empty=screen();ready=captured('v0963-forest-timed-challenge',True)
    d.forest_map=lambda:empty;d.home=lambda:None
    monkeypatch.setattr(module,'forest_points',lambda *_:0)
    pans=[];fights=[];initial=forest_nodes(d.b,ready)
    monkeypatch.setattr(module,'forest_nodes',lambda b,s:initial if s is ready and not fights else [])
    def pan(s,*_):
        pans.append(1)
        return (ready,True) if len(pans)==1 else (s,False)
    d.forest_simple_pan=pan
    def fight(s,n):
        fights.append(n);s.words=[w for w in s.words if w.text!='挑战'];return s
    d.forest_challenge=fight
    d.forest()
    assert len(fights)==1 and pans


def test_real_garbled31_is_confirmed_by_exact_crop_reads(offline_backend):
    s=captured('v0963-rift-node31',True)
    assert s.find(r'^3\]$')
    assert rift_node(offline_backend,s,31)==('open',(391,405))
    assert rift_node(offline_backend,s,30)[0]=='open'
    assert rift_node(offline_backend,s,33)[0]=='locked'


def test_garbled_label_itself_cannot_authorize_a_rift_click(offline_backend):
    s=captured('v0963-rift-node31',True)
    offline_backend.read_text_crop=lambda *_:'3]'
    assert rift_node(offline_backend,s,31) is None


@pytest.mark.parametrize('observed,point',[
    ([None,('open',(391,405))],(391,405)),
    ([('open',(425,405)),('open',(425,405))],(425,405)),
])
def test_preclick_rift_reobserves_and_only_clicks_stable_confirmed_node(tmp_path,monkeypatch,observed,point):
    import chao2.rift as module
    d=daily(tmp_path);s=captured('v0963-rift-node31');reads=iter(observed);clicks=[]
    d.rift_locate=lambda q,n:(q,('open',(391,405)))
    d.observe=lambda:s;d.b.sleep=lambda _:None;d.rift_wait_detail=lambda _:s
    monkeypatch.setattr(module,'rift_node',lambda *_:next(reads))
    d.b.click_at=lambda q,p,*_:clicks.append(p)
    assert d.rift_open_stage(s,31) is s and clicks==[point]
    assert len(d.report['navigation_retries'])==1 and d.battles==0


@pytest.mark.parametrize('node',[None,('locked',(391,405))])
def test_rift_persistent_preclick_failure_is_bounded_and_recoverable(tmp_path,monkeypatch,node):
    import chao2.rift as module
    d=daily(tmp_path);s=captured('v0963-rift-node31');reads=[]
    d.rift_locate=lambda q,n:(q,('open',(391,405)))
    d.observe=lambda:reads.append(1) or s;d.b.sleep=lambda _:None
    monkeypatch.setattr(module,'rift_node',lambda *_:node)
    d.b.click_at=lambda *_:pytest.fail('Unconfirmed node')
    with pytest.raises(TaskBlocked,match='重读3次') as e:d.rift_open_stage(s,31)
    assert navigation_failure(e.value) and len(reads)==4


def test_rift_recovery_remembers_the_fallback_ceiling(tmp_path,monkeypatch):
    d=daily(tmp_path);state=fake_rift(d,monkeypatch,keys=1,advance=False)
    highest=d.rift_highest
    def interrupted(s):
        d.rift_fallback(24,'探索者等级不足')
        raise TaskBlocked('节点未确认')
    d.rift_highest=interrupted
    with pytest.raises(TaskBlocked):d.rift()
    d.rift_highest=highest;d.rift()
    assert state['opened']==[23] and state['claimed']==[23]


def test_rift_recovery_does_not_replay_an_already_failed_team(tmp_path,monkeypatch):
    d=daily(tmp_path);state=fake_rift(d,monkeypatch,keys=1,outcomes=['failed'],advance=False)
    opener=d.rift_open_stage
    d.rift_open_stage=lambda *_:(_ for _ in ()).throw(TaskBlocked('节点未确认'))
    with pytest.raises(TaskBlocked):d.rift()
    d.rift_open_stage=opener;d.rift()
    assert state['teams']==[2,1] and state['claimed']==[24]


def test_stop_during_rift_preclick_retry_is_not_ignored(tmp_path,monkeypatch):
    import chao2.rift as module
    d=daily(tmp_path);s=captured('v0963-rift-node31')
    d.rift_locate=lambda q,n:(q,('open',(391,405)))
    d.observe=lambda:s;d.b.sleep=lambda _:d.b.stop.set()
    monkeypatch.setattr(module,'rift_node',lambda *_:None)
    with pytest.raises(UserStopped):d.rift_open_stage(s,31)
