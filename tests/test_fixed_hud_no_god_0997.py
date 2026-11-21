"""Right-aligned fixed HUD crops and monster-only preset verification; no MuMu."""
import cv2
import numpy as np
import pytest

from chao2.fixed_hud import FOREST_POINTS_ROI,TOWER_MAP_ROI,TOWER_DETAIL_ROI,fixed_hud_ratio
from chao2.forest import forest_points
from chao2.team_copy import source_lineup,copied_lineup
from chao2.policy import UserStopped
from test_configuration import daily,screen,captured
from test_forest_points_0977 import forest_map
from test_rift_main_0959 import offline_backend


def test_fixed_frames_stop_at_the_black_panel_edge_and_leave_left_margin():
    assert FOREST_POINTS_ROI==(1110,10,70,32)
    assert TOWER_MAP_ROI==(1110,10,70,32)
    assert TOWER_DETAIL_ROI==(1183,10,80,32)
    assert FOREST_POINTS_ROI[0]+FOREST_POINTS_ROI[2]==1180
    assert TOWER_MAP_ROI[0]+TOWER_MAP_ROI[2]==1180
    assert TOWER_DETAIL_ROI[0]+TOWER_DETAIL_ROI[2]==1263


@pytest.mark.parametrize('value',['0/17','1/17','5/17','17/17','17/20','20/20','123/200','999/999'])
def test_complete_ratio_read_uses_same_fixed_crop_at_every_scale(tmp_path,value):
    d=daily(tmp_path);calls=[]
    d.b.read_text_region=lambda s,roi,**kw:calls.append((roi,kw['scale'])) or value
    pair,reads=fixed_hud_ratio(d.b,screen(),TOWER_DETAIL_ROI)
    assert pair==tuple(map(int,value.split('/')))
    assert calls==[(TOWER_DETAIL_ROI,3),(TOWER_DETAIL_ROI,4)] and len(reads)==2


@pytest.mark.parametrize('values',[
    ['17[20']*3,['1720']*3,['17/20)']*3,['-1/20']*3,['1/0']*3,
    ['17/20','16/20'],['0/17','0/16'],['','',''],
])
def test_fixed_reader_never_guesses_a_slash_or_overrides_conflicting_digits(tmp_path,values):
    d=daily(tmp_path);answers=iter(values)
    d.b.read_text_region=lambda *a,**kw:next(answers)
    d.b.read_number=lambda *a:pytest.fail('Never split complete ratios into numeric crops')
    d.b.read_resource_ratio=lambda *a:pytest.fail('Never fall back to full-frame words')
    assert fixed_hud_ratio(d.b,screen(),TOWER_DETAIL_ROI)[0] is None


def test_independent_fallback_retains_exactly_the_same_right_and_left_edges(tmp_path):
    d=daily(tmp_path);d.b.tasker=object();answers=iter(['','0/17','']);crops=[]
    d.b.read_text_region=lambda *a,**kw:next(answers)
    d.b.read_text_crop=lambda s,roi:crops.append(roi) or '0/17'
    assert fixed_hud_ratio(d.b,screen(),FOREST_POINTS_ROI)[0]==(0,17)
    assert crops==[FOREST_POINTS_ROI]


def test_stop_propagates_during_fixed_read(tmp_path):
    d=daily(tmp_path)
    def stop(*a,**kw):raise UserStopped('stop')
    d.b.read_text_region=stop
    with pytest.raises(UserStopped):fixed_hud_ratio(d.b,screen(),TOWER_DETAIL_ROI)


@pytest.mark.parametrize('map_view',[False,True])
def test_tower_all_resource_checks_use_local_fixed_crops_not_full_frame_words(tmp_path,map_view):
    d=daily(tmp_path);d.b.tasker=object();calls=[]
    d.b.read_resource_ratio=lambda *a:pytest.fail('No generic/dynamic ratio crop for tower')
    d.b.read_text_region=lambda s,roi,**kw:calls.append(roi) or '17/20'
    # Misleading full-frame words cannot affect this local read.
    s=screen(('1/20',1210,15,50,25));roi=(1030,0,170,65) if map_view else (1140,0,140,65)
    d.verify_dungeon_resource('tower',s,roi)
    expected=TOWER_MAP_ROI if map_view else TOWER_DETAIL_ROI
    assert calls==[expected,expected]
    assert d.report['dungeon_resources']['tower']['remaining']==17


def test_tower_settlement_accounting_uses_fixed_feather_crop(tmp_path):
    d=daily(tmp_path);d.b.tasker=object();calls=[]
    d.b.read_text_region=lambda s,roi,**kw:calls.append(roi) or '17/20'
    d.settle_battle_resource('tower',screen(('17[20',1208,15,54,26)),'failed',18)
    assert d.report['resource_usage']['tower']['浮空羽毛']['spent']==1
    assert calls==[TOWER_DETAIL_ROI,TOWER_DETAIL_ROI]


def lineup_images():
    source=np.zeros((720,1280,3),np.uint8);dest=np.zeros_like(source)
    rng=np.random.default_rng(1997)
    for i in range(5):
        portrait=rng.integers(0,255,(35,60,3),dtype=np.uint8)
        source[174:209,402+i*80:462+i*80]=portrait
        patch=cv2.resize(portrait,None,fx=1.6,fy=1.6)
        x=140+i*200;dest[616:672,x:x+96]=patch
        dest[590:610,x-18:x+12]=(0,230,0)
    return source,dest


def test_source_lineup_does_not_require_or_capture_any_god_image():
    source,_=lineup_images()
    assert source[159:230,795:963].std()==0
    lineup=source_lineup(source,120)
    assert lineup is not None and set(lineup)=={'portraits'}


@pytest.mark.parametrize('god_pixels',[0,255,'noise'])
def test_matching_five_selected_monsters_is_sufficient_for_any_god(monkeypatch,god_pixels):
    source,dest=lineup_images()
    dest[70:300,230:510]=np.random.default_rng(1).integers(0,255,(230,280,3),dtype=np.uint8) if god_pixels=='noise' else god_pixels
    monkeypatch.setattr(cv2,'SIFT_create',lambda *a,**kw:pytest.fail('God feature matching was removed'))
    result=copied_lineup(source_lineup(source,120),dest)
    assert result['verified'] and result['matched_monsters']==5
    assert 'god_verified' not in result


@pytest.mark.parametrize('missing',['portrait','selected_tick'])
def test_removing_god_check_keeps_five_monster_and_selected_tick_checks(missing):
    source,dest=lineup_images()
    if missing=='portrait':dest[616:672,140:236]=0
    else:dest[590:610,122:152]=0
    assert not copied_lineup(source_lineup(source,120),dest)['verified']


def test_original_tribe_failure_is_now_accepted_without_god_comparison():
    source=captured('v0997-team-source',True);dest=captured('v0997-tribe',True)
    row=source.find('^队伍1$')
    result=copied_lineup(source_lineup(source.image,row.center[1]),dest.image)
    assert result['verified'] and result['matched_monsters']==5


@pytest.mark.parametrize('name,expected',[
    ('forest-zero',0),('forest-five',5),('forest-four',4),('forest-three',3),('forest-two',2),('forest-one',1),
])
def test_actual_forest_points_are_read_with_new_right_boundary(offline_backend,name,expected):
    assert forest_points(offline_backend,captured('v0997-'+name,True))==expected


@pytest.mark.parametrize('name,roi,expected',[
    ('tower-detail',TOWER_DETAIL_ROI,(17,20)),('tower-map',TOWER_MAP_ROI,(20,20)),
])
def test_actual_tower_failure_and_map_use_fixed_complete_number_crop(offline_backend,name,roi,expected):
    s=captured('v0997-'+name,True)
    assert fixed_hud_ratio(offline_backend,s,roi)[0]==expected
    # The excluded column belongs to the background; the last included
    # column remains the black panel, rather than the bright forest art.
    x,y,w,h=roi
    assert np.median(s.image[20:35,x+w-1],axis=0).max()<60
