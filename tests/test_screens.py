import time
import json
from pathlib import Path
import numpy as np
import pytest
from chao2.backend import Screen,Word,Backend
from chao2.workflows import is_world
from chao2.workflows import Daily,TaskBlocked
from chao2.policy import SafetyStop,UserStopped

def screen(texts):
    return Screen(np.zeros((720,1280,3),np.uint8),[Word(t,[x,y,w,h],.99) for t,x,y,w,h in texts],time.monotonic())

def test_territory_is_not_world_even_with_shared_side_buttons():
    side=[('任务挑战',1190,40,80,24),('世界回响',1190,130,80,24)]
    assert not is_world(screen(side+[('永生之茧',870,210,80,24)]))
    assert is_world(screen(side+[('37/161',520,12,70,26)]))

def test_task_overlay_does_not_masquerade_as_map():
    s=screen([('任务挑战',1190,40,80,24),('世界回响',1190,130,80,24),('37/161',520,12,70,26),('玩法概览',20,460,100,25)])
    assert not is_world(s)

def test_confirmation_and_stale_frame_block_input():
    b=Backend({})
    with pytest.raises(SafetyStop):b.guard(screen([('是否消耗50钻石购买尖刺？取消',200,200,700,60)]))
    s=screen([]);s.when-=20
    with pytest.raises(SafetyStop):b.guard(s)
    b.stop.set()
    with pytest.raises(UserStopped):b.guard(screen([]))

def test_world_with_a_missed_first_character_in_task_label():
    s=screen([('务挑战',1212,46,64,18),('世界回响',1196,140,76,22),('5/161',524,15,56,26),('异象',1086,14,47,27)])
    assert is_world(s)

def test_copy_reward_settles_even_if_next_button_was_not_recognized(tmp_path):
    # These labels are from the actual copy victory capture; the next button was missed by OCR.
    s=screen([('胜利;',76,244,426,208),('获得奖励',897,324,77,22),('退出',1149,582,55,29),('+50',1178,232,47,24),('20/161',1196,15,65,26)])
    b=Backend({});r={'folder':tmp_path,'events':[]};d=Daily(b,r);d.observe=lambda:s
    assert d.battle('地图体力20') is s
    assert r['battles'][0]['result']=='victory'


def test_late_idle_reward_popup_closes_before_underlying_page_navigation(tmp_path):
    from test_configuration import captured
    popup=captured('idle-popup-late')
    # The background title sometimes remains fully readable during animation.
    popup.words.append(Word('星律',[130,10,65,30],.99))
    world=captured('world-missed-label');pages=iter([popup,world])
    d=Daily(Backend({}),{'folder':tmp_path,'events':[]});d.observe=lambda:next(pages)
    clicks=[];d.b.click_at=lambda s,p,a,r:clicks.append(r)
    assert d.home() is world
    assert clicks==['关闭免费奖励弹层']

def test_failed_result_is_never_counted_as_victory(tmp_path):
    s=screen([('挑战失败',100,200,400,100),('再次挑战',880,590,160,30),('退出',1140,590,60,30)])
    b=Backend({});r={'folder':tmp_path,'events':[]};d=Daily(b,r);d.observe=lambda:s
    with pytest.raises(TaskBlocked):d.battle('浮空羽毛')
    assert r['battles'][0]['result']=='failed'


def test_actual_hunt_failure_with_unreadable_decorative_title_settles(tmp_path):
    from test_configuration import captured
    from chao2.workflows import is_failure
    from chao2.policy import FightLost
    s=captured('hunt-failed')
    assert not s.find('失败|败退') and is_failure(s)
    b=Backend({});r={'folder':tmp_path,'events':[]};d=Daily(b,r);d.observe=lambda:s
    with pytest.raises(FightLost):d.battle('地图体力10')
    assert r['battles'][0]['result']=='failed'
    assert not is_failure(screen([('狩猎积分',800,250,150,30),('退出',1140,590,60,30),
                                 ('获得奖励',900,320,100,30)]))


def test_actual_tower_secret_defeat_with_unreadable_title_settles(tmp_path):
    from chao2.workflows import is_failure
    from chao2.policy import FightLost
    # OCR from the 2026-10-22 tower-secret-74 defeat: the large ornate
    # “失败” title was unreadable, while these smaller labels were stable.
    s=screen([('破',592,103,84,18),('通过下列方式提高战力',810,252,248,28),
              ('元核升级',756,435,86,24),('阵容调整',1028,435,85,24),
              ('退出',1149,582,55,29)])
    assert not s.find('失败|败退') and is_failure(s)
    d=Daily(Backend({}),{'folder':tmp_path,'events':[]});d.observe=lambda:s
    with pytest.raises(FightLost):d.battle('塔中秘庭免费')
    assert d.report['battles'][0]['result']=='failed'

def test_recorded_world_with_missed_side_label_can_navigate_and_read_resources(tmp_path):
    from PIL import Image
    from private_capture import capture_file
    base=capture_file('world-missed-label.png')
    s=Screen(np.asarray(Image.open(base.with_suffix('.png')).convert('RGB'))[:,:,::-1].copy(),
             [Word(**w) for w in json.loads(base.with_suffix('.json').read_text('utf-8'))],time.monotonic())
    b=Backend({});r={'folder':tmp_path,'events':[]};d=Daily(b,r);actions=[]
    b.click_at=lambda q,p,anchors,reason:actions.append((p,q.has(*anchors)))
    assert s.find('^界回响$') and not s.find('^世界回响$')
    assert d.home(s) is s
    d.click_world(s,(1230,625),'进入领地')
    assert actions==[((1230,625),True)]
    b.observe=lambda *args:s
    d.observe()
    assert r['resources_last_observed']['stamina']==5
    assert r['resources_last_observed']['diamonds']==1181

def test_bottom_map_buttons_can_corroborate_missing_side_label():
    s=screen([('任务挑战',1190,40,80,24),('事件',1150,636,44,20),('领地',1212,636,44,20),('5/163',524,17,54,24)])
    assert is_world(s)

@pytest.mark.parametrize('overlay',[('玩法概览',20,460,100,25),('本周已获得友好点数449',890,80,240,25),
                                    ('敌方阵容',1110,130,100,25),('传送',900,600,80,25),('世界',1200,635,60,25)])
def test_shared_world_hud_never_overrides_a_known_overlay(overlay):
    s=screen([('任务挑战',1190,40,80,24),('界回响',1212,140,55,24),('5/163',524,17,54,24),overlay])
    assert not is_world(s)

def test_map_words_in_wrong_regions_are_not_world_navigation():
    s=screen([('任务挑战',50,200,80,24),('世界回响',60,300,80,24),('5/163',524,17,54,24)])
    assert not is_world(s)

def test_failed_recovery_still_saves_completed_battles_and_task_reason(tmp_path):
    b=Backend({},log=lambda _:None)
    r={'folder':tmp_path,'events':[],'team_attempts':[{'task':'copies','outcome':'victory'} for _ in range(6)]}
    d=Daily(b,r)
    def fail():raise TaskBlocked('未知页面')
    d.copies=fail;d.home=fail
    with pytest.raises(SafetyStop):d.execute_task('copies')
    saved=json.loads((tmp_path/'report.json').read_text('utf-8'))
    row=saved['tasks']['copies']
    assert row['status']=='blocked' and row['message'].startswith('未知页面')
    assert row['recovery_error']=='未知页面' and row['attempts']==row['victories']==6
    assert '累计挑战6次' in row['summary']
