"""Actual Nov 15 summon and damage-to-health descriptions retain user priority."""
from chao2.daily_challenges import rampage_buff
from chao2.configuration import normalize_settings
from test_configuration import screen

ASSIST='召唤此怪兽出战，全技 能均为满级，怪兽在6 0秒或死亡后消失 幽狱沸体 等级1400 _1400'
LIFESTEAL='怪兽造成伤害的10% 用于回复自身血量 血祭 b6'
ATTACK='怪兽攻击力提升10% 强攻'
REDUCTION='怪兽受到伤害降低5% 差点无敌'


def pick(*descriptions,priority=None):
    rows=[('请选择一个暴走增益',450,110,300,35)]
    for left,text in zip((30,450,870),descriptions):
        rows += [(text,left+20,220,320,80),('点击选择',left+140,500,100,32)]
    return rampage_buff(screen(*rows),priority)[1]


def test_real_summon_description_outweighs_attack_and_reduction():
    assert ASSIST in pick(REDUCTION,ATTACK,ASSIST)


def test_real_damage_based_heal_is_lifesteal_not_generic_healing():
    assert LIFESTEAL in pick(ATTACK,LIFESTEAL,REDUCTION)
    assert ASSIST in pick(LIFESTEAL,REDUCTION,ASSIST)


def test_changed_player_priority_still_wins():
    options=normalize_settings({})['task_options']['nest']['buff_priority']
    options.sort(key=lambda row:row['id']!='attack')
    assert ATTACK in pick(ASSIST,LIFESTEAL,ATTACK,priority=options)


def test_normal_heal_or_incomplete_summon_text_does_not_gain_higher_priority():
    assert ATTACK in pick('召唤已完成，请领取','全体怪兽血量回复100%',ATTACK)
