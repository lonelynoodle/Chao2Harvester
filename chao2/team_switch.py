"""The client's warning when changing a team assigned to abyss suppression."""

SUPPRESSION_SWITCH_WARNING = r'正在压制深渊先遣的词缀[，,\s]*切换队伍会使压制失效'


def suppression_team_switch_dialog(s):
    return bool(s.find('^排阵$',(90,0,240,65)) and
                s.find(SUPPRESSION_SWITCH_WARNING,(290,335,710,95)) and
                s.find('^取消$',(350,450,270,85)) and
                s.find('^确定$',(665,450,270,85)))
