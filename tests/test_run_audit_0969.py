"""Recovery of an OCR-missed tower heading and repeatedly swallowed exits."""
import pytest
from chao2.activities import recover_tower_detail,enemy_formation
from chao2.policy import TaskBlocked
from test_configuration import daily,screen,captured
from test_rift_main_0959 import offline_backend


def test_actual_tower_heading_is_locally_confirmed_before_navigation(offline_backend):
    s=captured('v0969-tower-detail',True)
    assert not enemy_formation(s)
    fixed=recover_tower_detail(offline_backend,s)
    assert fixed.when==s.when and enemy_formation(fixed) and not enemy_formation(s)


def test_incomplete_tower_layout_cannot_gain_an_enemy_heading(tmp_path):
    d=daily(tmp_path);d.b.tasker=object()
    d.b.confirm_label=lambda *a,**kw:pytest.fail('Incomplete detail is not a tower anchor')
    s=screen(('星灵族-浮空巨塔25',234,105,230,28))
    assert recover_tower_detail(d.b,s) is s


def result_game(tmp_path,successful_click):
    d=daily(tmp_path);d.b.sleep=lambda _:None
    result=screen(('通过下列方式提高战力',810,252,248,28),('元核升级',756,435,86,24),
                  ('阵容调整',1028,435,85,24),('退出',1149,582,55,29))
    world=screen(('任务挑战',1196,42,80,24),('世界回响',1196,138,80,24),('35/183',500,12,80,28))
    state=[result];clicks=[];d.observe=lambda:state[0]
    def click(s,pattern):
        assert pattern=='^退出$';clicks.append(pattern)
        if len(clicks)==successful_click:state[0]=world
    d.b.click_text=click
    return d,result,world,clicks


def test_fifth_confirmed_free_exit_can_recover_after_four_swallowed_clicks(tmp_path):
    d,result,world,clicks=result_game(tmp_path,5)
    assert d.exit_result(result) is world and len(clicks)==5 and d.battles==0


def test_persistent_result_remains_bounded_and_never_presses_rematch(tmp_path):
    d,result,world,clicks=result_game(tmp_path,99)
    with pytest.raises(TaskBlocked,match='已重试7次'):d.exit_result(result)
    assert len(clicks)==8 and d.battles==0
