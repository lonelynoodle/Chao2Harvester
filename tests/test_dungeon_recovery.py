"""Regression cases from the 2026-10-13 run; all input is simulated."""
import json
from pathlib import Path

import pytest

from chao2.activities import next_tower_floor
from chao2.backend import Backend
from chao2.policy import TaskBlocked
from tests.test_configuration import daily, screen, captured


def test_missing_next_floor_never_selects_the_higher_locked_floor(tmp_path):
    full=captured('tower-gap')
    assert next_tower_floor(full)[0]==167
    full.words=[w for w in full.words if w.text!='0167']
    assert next_tower_floor(full) is None
    d=daily(tmp_path);d.b.sleep=lambda _:None
    d.observe=lambda:captured('tower-gap')
    _,floor=d.tower_next_floor(full)
    assert floor[0]==167


def test_tower_unreadable_gap_stops_without_clicking(tmp_path):
    s=captured('tower-gap');s.words=[w for w in s.words if w.text!='0167']
    d=daily(tmp_path);d.b.sleep=lambda _:None;d.observe=lambda:s
    d.b.click_at=lambda *a:pytest.fail('Must not guess a locked floor')
    with pytest.raises(TaskBlocked,match='相邻塔层'):d.tower_next_floor(s)


@pytest.mark.parametrize('stock',[0,4,None])
def test_hunt_reads_padded_stock_area_and_never_searches_without_tokens(tmp_path,stock):
    d=daily(tmp_path);calls=[]
    empty=captured('hunt-token-stock')
    empty.words=[w for w in empty.words if not ('/' in w.text and w.box[1]<65)]
    empty.words.extend(screen(('100/164',502,17,90,22)).words)
    prey=screen(('狩猎',974,18,70,30),('商店',1060,94,60,30),
                ('10',1080,234,30,20),('10',1080,366,30,20),('10',1080,501,30,20))
    def read(q,roi):
        assert roi in ((1110,599,77,45),(1130,597,56,38))
        return stock-1 if stock and q is prey else stock
    d.b.read_number=read;d.b.click_text=lambda s,p:calls.append(p)
    d.b.sleep=lambda _:None;d.observe=lambda:prey
    if stock is None:
        with pytest.raises(TaskBlocked,match='库存未读清'):d.search_hunters(empty)
    else:assert d.search_hunters(empty) is (prey if stock else None)
    assert calls==(['^搜索$'] if stock else [])


def test_failed_task_saves_its_frame_before_return_to_world(tmp_path):
    d=daily(tmp_path)
    detail=screen(('复制体详情未打开',900,250,200,30))
    other=screen(('返回后的页面',500,10,160,24))
    d.b.observe=lambda *args:detail
    def fail():
        d.observe();raise TaskBlocked('打开失败')
    def recover():
        d.b.observe=lambda *args:other;d.observe()
    d.copies=fail;d.home=recover
    d.execute_task('copies')
    path=Path(d.report['tasks']['copies']['screenshot'])
    assert path.exists()
    assert json.loads(path.with_suffix('.json').read_text('utf-8'))[0]['text']=='复制体详情未打开'
    assert d.last_screen is other


def test_hunt_reuses_open_list_instead_of_navigating_overview_again(tmp_path):
    d=daily(tmp_path);s=captured('hunt-token-stock')
    d.observe=lambda:s
    d.enter_overview=lambda *a:pytest.fail('Already at hunt list')
    assert d.hunt_menu() is s


def test_malformed_resource_needs_independent_number_confirmation(tmp_path):
    d=daily(tmp_path);s=captured('tower-resource-bracket')
    d.b.read_number=lambda *a:None
    with pytest.raises(TaskBlocked,match='余额未识别'):
        d.verify_dungeon_resource('tower',s,(1030,0,170,65))


def test_no_free_stamina_never_spends_search_tokens_during_read_only_probe(tmp_path):
    d=daily(tmp_path);d.selected=['copies','hunt'];d.home=lambda:screen()
    d.world_resources=lambda _:{'stamina':4,'stamina_cap':164}
    d.stamina_offer=lambda:None
    d.copy_targets=lambda *a:None
    d.hunt_menu=lambda:screen(('猎物未出现',946,435,114,24),('搜索',1066,669,100,28))
    d.b.read_number=lambda *a:3
    d.search_hunters=lambda *a:pytest.fail('Preflight must not spend a search token')
    d.b.click_text=lambda *a,**kw:pytest.fail('No claim or search input')
    assert '领取0份' in d.replenish_stamina()
    assert d.search_counts.get('hunt',0)==0


def test_hunt_cards_remain_detectable_when_unaffordable_cost_ocr_is_missing():
    from chao2.activities import hunt_rows
    s=captured('hunt-targets');normal=hunt_rows(s)
    assert len(normal)==3
    s.words=[w for w in s.words if w.text!='10']
    fallback=hunt_rows(s)
    assert len(fallback)==3
    assert all(abs(a-b)<8 for a,b in zip(normal,fallback))


def test_real_stamina_claim_label_and_two_available_servings():
    from chao2.activities import stamina_servings,STAMINA_CLAIM
    s=captured('stamina-two-servings',True)
    assert stamina_servings(s)==2 and s.find(STAMINA_CLAIM).text=='领取奖励'
    empty=captured('stamina-zero-servings',True)
    assert empty.find(STAMINA_CLAIM) and stamina_servings(empty)==0


def test_refill_probes_any_reward_then_keeps_actual_battle_priority(tmp_path):
    d=daily(tmp_path);calls=[]
    d.copy_targets=lambda kind,excluded:(calls.append(kind) or {'kind':'friend'})
    d.home=lambda:None
    assert d.stamina_outlet_available(['copies'],4)
    assert calls==['any']
