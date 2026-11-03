"""Regressions from the 21:07 run: giant lobby and missed PvP quotas."""
import pytest
from test_configuration import captured,daily,screen
from test_daily_challenges import arena_frame,origin_frame
from chao2.activities import is_giant_ready
from chao2.daily_challenges import origin_quota


def test_giant_ready_uses_its_own_lobby_instead_of_enemy_lineup():
    s=captured('v077-giant-ready')
    assert not s.find('敌方阵容') and is_giant_ready(s)
    for text in ('进击巨物','比拼方式','前往挑战'):
        changed=captured('v077-giant-ready')
        changed.words=[w for w in changed.words if w.text!=text]
        assert not is_giant_ready(changed)
    assert not is_giant_ready(captured('arena-detail'))


def test_giant_ready_waits_for_loading_without_any_input(tmp_path):
    d=daily(tmp_path);ready=captured('v077-giant-ready')
    frames=iter([screen(('加载中',500,300,100,30)),ready]);d.observe=lambda:next(frames)
    d.b.sleep=lambda _:None
    d.b.click_at=lambda *a:pytest.fail('Only observe while loading')
    assert d.giant_ready() is ready


def test_giant_menu_reuses_current_page_and_does_not_return_to_world(tmp_path):
    d=daily(tmp_path);menu=captured('giant-menu');d.observe=lambda:menu
    d.home=lambda *a:pytest.fail('Already on giant menu')
    d.b.click_at=lambda *a:pytest.fail('No redundant menu navigation')
    assert d.giant_menu() is menu


def test_giant_lobby_returns_directly_to_score_page(tmp_path):
    d=daily(tmp_path);ready=captured('v077-giant-ready');menu=captured('giant-menu')
    d.observe=lambda:ready;d.await_page=lambda *a:menu;calls=[]
    d.b.click_at=lambda s,p,*a:calls.append(p)
    d.home=lambda *a:pytest.fail('Do not leave giant')
    assert d.giant_menu() is menu and calls==[(45,28)]


def test_home_can_recover_the_actual_giant_lobby(tmp_path):
    d=daily(tmp_path);world=captured('world-missed-label')
    frames=iter([captured('giant-menu'),screen(('丰野间',120,14,100,30),('幻境巡游',300,200,100,30)),world])
    d.observe=lambda:next(frames);clicks=[]
    d.b.click_at=lambda s,p,a,r:clicks.append(r)
    assert d.home(captured('v077-giant-ready')) is world
    assert clicks==['关闭巨物备战页','返回丰野间','返回世界']


def test_single_digit_origin_quota_uses_a_verified_number_crop(tmp_path):
    d=daily(tmp_path);s=captured('v077-origin-nine');calls=[]
    assert origin_quota(s) is None
    d.b.read_number=lambda s,roi:calls.append(roi) or 9
    assert d.read_pvp_quota(s,'origin')==9 and calls==[(1143,574,32,29)]
    d.b.read_number=lambda *a:None
    assert d.read_pvp_quota(s,'origin') is None


def test_quota_reader_never_reads_unrelated_page_as_a_free_attempt(tmp_path):
    d=daily(tmp_path);s=screen(('剩余免费挑战次数',992,577,149,22),('9',1150,577,20,22))
    d.b.read_number=lambda *a:pytest.fail('Missing page anchors')
    d.b.read_text_crop=d.b.read_number
    assert d.read_pvp_quota(s,'origin') is None
    assert d.read_pvp_quota(s,'arena') is None


def test_arena_zero_requires_local_confirmation(tmp_path):
    d=daily(tmp_path);s=arena_frame(0)
    d.b.read_text_crop=lambda *a:'0/15'
    assert d.read_pvp_quota(s,'arena')==0
    d.b.read_text_crop=lambda *a:''
    assert d.read_pvp_quota(s,'arena') is None


def test_arena_missed_leading_digit_does_not_skip_available_attempts(tmp_path):
    d=daily(tmp_path);s=arena_frame(0)
    d.b.read_text_crop=lambda *a:'10/15'
    d.b.read_text_region=lambda *a,**kw:'10/15'
    assert d.read_pvp_quota(s,'arena')==10
    d.b.read_text_region=lambda *a,**kw:'0/15'
    assert d.read_pvp_quota(s,'arena') is None


def test_post_battle_quota_waits_for_settled_number_without_extra_input(tmp_path):
    d=daily(tmp_path);before=origin_frame(10);after=origin_frame(9)
    d.observe=lambda:after;d.b.sleep=lambda _:None
    d.b.click_at=lambda *a:pytest.fail('Never re-enter a battle to verify count')
    got,value=d.await_pvp_quota(before,'origin',9)
    assert got is after and value==9


def test_quota_retries_are_bounded_and_preserve_true_mismatch(tmp_path):
    d=daily(tmp_path);seen=[];d.b.sleep=lambda _:None
    d.observe=lambda:seen.append(1) or origin_frame(10)
    _,value=d.await_pvp_quota(origin_frame(10),'origin',9)
    assert value==10 and len(seen)==2


def test_giant_does_not_count_menu_without_battle_as_settlement(tmp_path,monkeypatch):
    from chao2.policy import SafetyStop
    import chao2.activities as activities
    d=daily(tmp_path);clock=[0]
    monkeypatch.setattr(activities.time,'monotonic',lambda:clock[0])
    d.b.sleep=lambda seconds:clock.__setitem__(0,clock[0]+seconds)
    d.b.guard=lambda s:None;d.observe=lambda:captured('giant-menu')
    with pytest.raises(SafetyStop,match='结算'):d.giant_settlement()
    assert not d.report.get('battles')

@pytest.mark.parametrize('enabled',[True,False])
def test_giant_auto_settle_is_optional_and_clicked_only_once(tmp_path,enabled):
    d=daily(tmp_path);d.options['giant']['auto_settle']=enabled
    battle=screen(('进击巨物',1180,2,100,28),('累计伤害比拼',1040,85,150,35),
                  ('04:59',595,5,95,35),('结算',155,600,65,40))
    result=screen(('总伤害12345',800,300,220,45),('退出',1130,600,100,40))
    menu=captured('giant-menu')
    for word in menu.words:
        if word.text=='总伤害0':word.text='总伤害12345'
    frames=iter([battle,battle,result,menu]);d.observe=lambda:next(frames)
    d.b.sleep=lambda _:None;clicked=[];d.b.click_at=lambda s,p,*a:clicked.append('^结算$')
    d.exit_result=lambda s:clicked.append('退出结果')
    assert d.giant_settlement()==12345
    assert clicked==(['^结算$','退出结果'] if enabled else ['退出结果'])
