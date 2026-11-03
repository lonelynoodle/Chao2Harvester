"""Regressions from the completed 2026-10-21 run and inspected blue evolution UI."""
from pathlib import Path
from types import SimpleNamespace
import cv2
import pytest

from test_configuration import captured,daily
from chao2.activities import enemy_formation
from chao2.configuration import SPECS,defaults
from chao2.policy import SafetyStop
from chao2.puzzle import puzzle_daily_best,await_daily_best
from chao2.star_shop import star_souls
from chao2.star_supply import (blue_roster_cards,purple_monster_info,evolution_offer,blue_egg_offer,
                                blue_egg_dialog)
from chao2.backend import ROOT


def match_templates(b):
    def match(s,name,roi,threshold=.88):
        x,y,w,h=roi
        template=cv2.imread(str(ROOT/'resource/image'/name))
        if template is None:return False
        score=cv2.matchTemplate(s.image[y:y+h,x:x+w],template,cv2.TM_CCOEFF_NORMED)
        return cv2.minMaxLoc(score)[1]>=threshold
    b.match_template=match


def test_real_tower_secret_detail_accepts_joined_formation_heading(tmp_path):
    d=daily(tmp_path)
    s=captured('v0927-tower-blocked',True)
    assert enemy_formation(s).text=='敌方阵容1234)5'
    assert d.ensure_detail(s) is s
    d.verify_tower_secret(s,'塔中秘庭68')


def test_real_completed_puzzle_score_corrobates_the_full_frame_word(tmp_path):
    d=daily(tmp_path)
    s=captured('v0927-daily_puzzle-blocked',True)
    d.b.read_number=lambda *a:None
    d.b.read_text_region=lambda *a,**k:''
    assert puzzle_daily_best(d.b,s) is None
    assert puzzle_daily_best(d.b,s,440)==440
    assert puzzle_daily_best(d.b,s,300) is None
    d.observe=lambda:s;d.b.sleep=lambda _:None
    assert await_daily_best(d,s)[1]==440


def test_star_soul_balance_in_dimmed_spore_purchase_dialog(tmp_path):
    d=daily(tmp_path);match_templates(d.b)
    s=captured('v0927-star_spores-blocked',True)
    d.b.read_number=lambda q,roi:145
    assert not d.b.match_template(s,'star-soul-top.png',[1130,0,65,58],.88)
    assert d.b.match_template(s,'star-soul-buy.png',[600,640,45,42],.88)
    assert star_souls(d.b,s)==145
    s.words=[w for w in s.words if w.text!='购买数量']
    with pytest.raises(Exception,match='图标未确认'):star_souls(d.b,s)


def test_blue_supply_is_opt_in_and_nested(tmp_path):
    options=defaults('other')
    for key in ('evolve_blue_for_star_souls','buy_blue_eggs_for_star_souls','buy_all_blue_eggs'):
        assert options[key] is False
    fields={row['key']:row for row in SPECS['other']['fields']}
    assert fields['evolve_blue_for_star_souls']['enabled_when']=='convert_star_souls'
    assert fields['buy_blue_eggs_for_star_souls']['enabled_when']=='evolve_blue_for_star_souls'
    assert fields['buy_all_blue_eggs']['enabled_when']=='buy_blue_eggs_for_star_souls'
    d=daily(tmp_path)
    with pytest.raises(SafetyStop,match='未开启'):d.evolve_one_blue_for_star_souls(100)
    with pytest.raises(SafetyStop,match='未开启'):d.buy_blue_eggs_for_star_souls(100)


def test_actual_blue_roster_only_exposes_level_one_blue_cards():
    cards=blue_roster_cards(captured('v0927-monster-blue-list',True))
    assert cards and cards[0]['point']==(426,488) and cards[0]['level']==1
    assert all(row['point'][1]>=488 for row in cards)


def test_actual_ultimate_evolution_uses_only_gold_and_spores(tmp_path):
    d=daily(tmp_path)
    s=captured('v0927-blue-evolve-detail',True)
    d.b.read_number=lambda q,roi:{(98,666,68,28):85000,(207,672,28,23):45,
                                 (1220,10,48,35):565}.get(tuple(roi))
    offer=evolution_offer(d.b,s)
    assert offer=={'name':'轮脉','gold':85000,'spores':45,
                   'gold_balance':6080000,'spore_balance':565}
    s.words=[w for w in s.words if w.text!='消耗材料']
    assert evolution_offer(d.b,s) is None


def test_purple_result_can_be_verified_by_crest_and_level_when_name_ocr_varies(tmp_path):
    d=daily(tmp_path)
    d.b.read_number=lambda q,roi:1
    assert purple_monster_info(d.b,captured('v0927-purple-info',True))


def test_actual_blue_egg_stock_price_and_modal_currency(tmp_path):
    d=daily(tmp_path);match_templates(d.b)
    shop=captured('v0923-star-shop',True)
    modal=captured('v0923-shop-preview',True)
    d.b.read_number=lambda q,roi:25 if roi[1] in (355,646) else 1 if roi[1]==511 else None
    assert blue_egg_offer(d.b,shop)['remaining']==6
    assert blue_egg_dialog(d.b,modal,1)
    assert not blue_egg_dialog(d.b,modal,2)
