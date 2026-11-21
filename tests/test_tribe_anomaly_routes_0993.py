"""Nov 16: overlapping troop caption and overview arriving at a map, not a list."""
import pytest
from chao2.team_copy import is_tribe_formation,source_lineup,copied_lineup
from chao2.policy import TaskBlocked,EncounterInterrupted
from chao2.activities import is_copy_list
from test_configuration import daily,captured,screen
from test_fixed_hud_no_god_0997 import lineup_images
from test_rift_main_0959 import offline_backend


def copy_list():
    return screen(('异象',950,15,100,30),('本周已获取友好点数100/1000',880,80,280,30))


def test_real_overlapping_troop_caption_is_an_independent_formation(tmp_path):
    d=daily(tmp_path);d.active_task='tribe';raw=captured('v0993-tribe-caption',True)
    assert not raw.find(r'^(?:空闲\s*[12]?|部队[12])$',(890,60,250,70))
    assert is_tribe_formation(raw)
    d.observe=lambda:raw
    assert d.formation_page() is raw
    calls=[];d.b.click_at=lambda s,p,a,r:calls.append((p,a))
    def modal():raise TaskBlocked('fixture: next step is saved configuration')
    d.read_saved_team_list=modal
    with pytest.raises(TaskBlocked,match='next step'):d.apply_saved_team(raw,1)
    assert calls==[((852,96),['^部队$'])]


@pytest.mark.parametrize('missing',['部队','可复制配置','起源核心','起源基石','撤离'])
def test_overlapped_caption_fallback_requires_complete_troop_layout(missing):
    s=captured('v0993-tribe-caption');s.words=[w for w in s.words if w.text!=missing]
    assert not is_tribe_formation(s)


def test_other_task_cannot_accept_a_troop_formation(tmp_path):
    d=daily(tmp_path);d.active_task='copies';s=captured('v0993-tribe-caption')
    d.observe=lambda:s;d.b.sleep=lambda _:None
    with pytest.raises(TaskBlocked,match='尚未加载'):d.formation_page()


@pytest.mark.parametrize('overlay',['取消','确定','获得奖励'])
def test_troop_caption_under_modal_is_not_a_ready_formation(overlay):
    s=captured('v0993-tribe-god');s.words+=screen((overlay,450,300,200,35)).words
    assert not is_tribe_formation(s)


def test_monster_match_is_sufficient_without_god_feature_check(tmp_path):
    d=daily(tmp_path);d.active_task='tribe';s=captured('v0993-tribe-god',True);src=captured('v0993-team-source',True)
    row=src.find('^队伍1$');source=source_lineup(src.image,row.center[1]);evidence=copied_lineup(source,s.image)
    assert evidence['matched_monsters']==5 and evidence['verified'] and 'god_verified' not in evidence
    button=src.find('^复制此配置$',(745,row.center[1]-27,200,54))
    d.read_saved_team_list=lambda:src;d.read_saved_team_copy_target=lambda _: (src,row,button)
    d.observe=lambda:s;d.b.sleep=lambda _:None;d.b.click_at=lambda *a:None
    d.b.read_text_crop=lambda *a:'159771'
    assert d.apply_saved_team(s,1,_copy_retry=2) is s
    assert d.report['team_copy_checks'][0]['status']=='verified' and d.battles==0
    assert not (tmp_path/'team-copy-unconfirmed-1.png').exists()


def test_deployed_troop_closes_copy_list_and_starts_with_existing_lineup(tmp_path):
    d=daily(tmp_path,{'task_options':{'tribe':{'teams':[1],'wall_mode':'attack'}}})
    d.active_task='tribe';d.b.sleep=lambda _:None
    detail=screen(('冒险关卡22',44,133,136,32),('敌方阵容',1128,133,105,31),
                  ('通关奖励（含拍卖和共享奖励）',41,565,260,18),('5/14',1200,15,50,25),
                  ('10/10',1130,555,60,20),('排阵',825,615,57,32),('挑战',1060,603,61,34),
                  ('1',1102,633,10,20))
    victory=screen(('胜利',90,245,120,40),('获得奖励',640,300,100,40),('退出',1120,605,60,30))
    source_pixels,ready_pixels=lineup_images()
    active=screen(('部队',145,14,44,27),('部队1',968,83,57,25),('撤离',984,128,48,26),
                  ('34681',1181,80,69,29))
    active.image[:]=ready_pixels
    active.image[590:610,722:752]=0
    active.image[590:610,922:952]=0
    source=screen(('配置',608,31,58,35),('队伍1',316,108,64,24),('45606',422,108,68,24),
                  ('复制此配置',794,111,116,22))
    source.image[:]=source_pixels
    current=[detail];calls=[]
    d.observe=lambda:current[0];d.await_detail=lambda:current[0]
    d.prepare_battle_wall=lambda *a:pytest.fail('Keep the deployed formation and current wall')
    d.exit_result=lambda s:calls.append('结算')
    def tap(s,point,anchors,reason):
        assert s.has(*anchors)
        calls.append(reason)
        if reason=='打开配置列表':current[0]=source
        elif reason=='复制保存的队伍1到独立配置':
            assert s is source
        elif reason=='收起配置':current[0]=active
        elif reason=='返回关卡':current[0]=detail
        else:pytest.fail(reason)
    def click_text(s,pattern,**kwargs):
        assert s is detail and s.find(pattern)
        calls.append(pattern)
        current[0]=active if pattern=='^排阵$' else victory
    d.b.click_at=tap;d.b.click_text=click_text
    assert d.play_encounter('tribe',lambda:detail,'部落战令',lambda s:d.verify_tribe_detail(s,'冒险关卡22'))
    assert calls==['^排阵$','打开配置列表','复制保存的队伍1到独立配置','收起配置',
                   '返回关卡','^挑战$|^前往挑战$','结算']
    check=d.report['team_copy_checks'][0]
    assert check['status']=='kept_deployed' and check['matched_monsters']==3 and check['reads']==1
    assert d.report['team_attempts']==[{'task':'tribe','team':None,'outcome':'victory',
                                         'target':'冒险关卡22','used_deployed_troop':True}]


def test_real_world_event_button_uses_its_lower_caption(tmp_path,monkeypatch,offline_backend):
    d=daily(tmp_path);d.b=offline_backend;s=captured('v0993-copy-world',True);points=[]
    monkeypatch.setattr(d,'click_world',lambda q,p,r:points.append(p))
    d.click_world_events(s,'test event entrance')
    assert len(points)==1 and 1060<=points[0][0]<=1160 and 630<=points[0][1]<=670


def test_portal_interruption_is_not_relabelled_as_overview_failure(tmp_path):
    d=daily(tmp_path);s=captured('v0993-copy-world');d.observe=lambda:s;d.overview_prepared_for=lambda _:False
    d.open_anomaly_list=lambda _:(_ for _ in ()).throw(EncounterInterrupted('位面传送门已关闭'))
    d.overview_entry=lambda *a,**kw:pytest.fail('The encounter retry loop must handle this interruption')
    with pytest.raises(EncounterInterrupted):d.copy_list()


@pytest.mark.parametrize('direct_list',[False,True])
def test_overview_map_only_arrival_opens_list_once_and_waits_out_transient_world(tmp_path,direct_list):
    d=daily(tmp_path);world=captured('v0993-copy-world');final=copy_list();opened=[];clicks=[]
    menu=screen(('玩法概览',20,470,100,30),('每日挑战',20,340,100,30),('异象',380,110,70,30))
    d.find_overview_entry=lambda _: (menu,'target',menu.find('^异象$'))
    pages=iter([world,final] if direct_list else [world,world]);d.observe=lambda:next(pages)
    d.b.click_at=lambda *a:clicks.append(a[1]);d.b.sleep=lambda _:None;d.resolve_path_event=lambda _:None
    def open_list(q,**kw):opened.append(kw);assert q is world;return final
    d.open_anomaly_list=open_list
    assert d.enter_overview('^异象$') is final and len(clicks)==1
    assert opened==([] if direct_list else [{'from_overview':True}])


def test_open_list_fast_path_does_not_replay_prepared_overview(tmp_path):
    d=daily(tmp_path);s=copy_list();assert is_copy_list(s)
    d.overview_prepared_for=lambda _:True;d.enter_overview=lambda _:pytest.fail('List is already open')
    assert d.open_anomaly_list(s) is s
