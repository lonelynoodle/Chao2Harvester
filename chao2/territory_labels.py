"""Fixed local OCR for territory captions, separate from upgrade/owner text."""
import re


# Captions only: exclude building art, construction timers and the owner's
# second line. Keep the same coordinates on the fresh pre-click frame.
TERRITORY_LABELS={
    '谜之巢穴':(474,40,106,31), '凿星裂痕':(783,32,118,32),
    '浮空巨塔':(679,118,108,31), '领地':(614,148,87,32),
    '骨场':(321,216,88,32), '鳞场':(440,195,80,32),
    '仓库':(266,293,88,32), '木场':(385,277,89,32),
    '永生之茧':(858,205,107,32), '起源殿':(1017,82,108,32),
    '源初境':(1092,207,91,32), '斗技场':(944,274,81,31),
    '部落':(1001,425,91,32), '造唤台':(462,359,101,32),
    '联结共鸣':(802,352,112,32), '饲星坛':(596,387,99,32),
    '起源基石':(341,412,106,32), '探索营地':(203,491,109,34),
    '战墙':(534,474,90,32), '发入欧店':(684,460,95,32),
    '黑暗森林':(827,470,121,34),
    '世界':(1192,670,83,39), '排阵':(702,673,74,40),
    '怪兽':(782,673,73,40), '神灵':(862,673,73,40),
    '商店':(940,673,76,40), '进化树':(1009,673,92,40),
    '排行榜':(1091,673,91,40),
    '任务挑战':(1190,36,90,37), '世界回响':(1181,132,99,38),
    '活动':(1193,217,80,39), '宝藏':(1193,304,80,38),
    '首充':(1191,391,82,40), '限时':(1190,478,83,40),
    '丰野间':(181,93,77,31), '降临':(266,93,67,31), '更多':(346,92,66,32),
}
BUILDINGS=tuple(TERRITORY_LABELS)[:21]


def label_pattern(label):
    if label=='谜之巢穴':return '^[谜迷]之巢穴$'
    if label=='凿星裂痕':return '^[凿幽]星裂痕$'
    return '^'+re.escape(label)+'$'


def is_territory(s):
    # Do not use labels visible through a modal to authorize a map click.
    if s.find('^玩法概览$|^每日挑战$|^探索者等级$|^点击空白位置关闭$|^取消$|^确定$|^购买$|^获得奖励$|选择挑战的塔'):
        return False
    footer=any(s.find(label_pattern(label),TERRITORY_LABELS[label])
               for label in ('世界','排阵','怪兽','神灵'))
    buildings=sum(bool(s.find(label_pattern(label),TERRITORY_LABELS[label])) for label in BUILDINGS)
    return footer and buildings>=2


def confirm_territory_label(b,s,pattern):
    """Only supplement a registered exact caption on a confirmed territory."""
    if not is_territory(s):return False
    for label,roi in TERRITORY_LABELS.items():
        if pattern not in (label_pattern(label),'^'+re.escape(label)+'$'):continue
        if s.find(pattern,roi):return True
        b.confirm_label(s,pattern,roi,scale=3,threshold=.8)
        if not s.find(pattern,roi):b.confirm_label(s,pattern,roi,scale=4,threshold=.8)
        return s.find(pattern,roi) is not None
    return False


def recover_territory_labels(b,s):
    if not is_territory(s) or b.tasker is None:return s
    for label,roi in TERRITORY_LABELS.items():
        pattern=label_pattern(label)
        if not s.find(pattern,roi):confirm_territory_label(b,s,pattern)
    return s
