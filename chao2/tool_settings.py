"""Standalone tool options, separate from the daily task selection."""
from copy import deepcopy
from .configuration import TEAMS,number,normalize_teams
from .puzzle_solver import MAX_SCORE

PUZZLE_SPEC={'key':'puzzle','name':'拼二大作战',
             'legacy_goals':{'300':300,'1500':1500,'first':MAX_SCORE},
             'fields':[
                 {**number('puzzle_target_score','目标分数',MAX_SCORE,MAX_SCORE),'min':1,
                  'description':'当前单局达到目标后停止；最高7172分。'},
                 {**number('puzzle_max_games','最多局数（0不限）',0,10000),
                  'description':'0表示未达目标就输后重开；正数包含启动时接续的当前局。'}]}

TOUR_SPEC={'key':'tour','name':'幻境巡游','hint':'按阵容顺序尝试，失败换队；全部失败后换环境。',
           'fields':[{**deepcopy(TEAMS),'default':[1,2,3]},
                     {**number('max_battles','最多挑战次数',100,500),'min':1}]}

ABYSS_SPEC={'key':'abyss','name':'深渊先遣',
            'fields':[{**deepcopy(TEAMS),'default':[1,2,3]}]}

def puzzle_options(settings):
    raw=dict(settings)
    if 'puzzle_target_score' not in raw and any(k in raw for k in ('puzzle_goal','puzzle_max_moves')):
        legacy=raw.get('puzzle_goal','first')
        if type(legacy) is not str or legacy not in PUZZLE_SPEC['legacy_goals']:
            raise ValueError('旧版拼二目标无效')
        raw['puzzle_target_score']=PUZZLE_SPEC['legacy_goals'][legacy]
        # Old versions always imposed a game cap; the new default is unlimited.
        raw['puzzle_max_games']=0
    values=[]
    for field in PUZZLE_SPEC['fields']:
        value=raw.get(field['key'],field['default'])
        if type(value) is not int or not field['min']<=value<=field['max']:
            raise ValueError(f"拼二{field['label']}必须为{field['min']}至{field['max']}的整数")
        values.append(value)
    return tuple(values)

def normalize_puzzle_settings(settings):
    result=dict(settings)
    result['puzzle_target_score'],result['puzzle_max_games']=puzzle_options(settings)
    for key in ('puzzle_goal','puzzle_max_moves'):result.pop(key,None)
    return result

def tour_options(settings):
    raw=settings.get('tour_options',{})
    if not isinstance(raw,dict):raise ValueError('幻境巡游设置格式错误')
    teams=normalize_teams(raw.get('teams',[1,2,3]))
    maximum=raw.get('max_battles',100)
    if type(maximum) is not int or not 1<=maximum<=500:raise ValueError('幻境巡游挑战上限必须为1至500')
    return {'teams':teams,'max_battles':maximum}

def abyss_options(settings):
    raw=settings.get('abyss_options',{})
    if not isinstance(raw,dict):raise ValueError('深渊先遣设置格式错误')
    return {'teams':normalize_teams(raw.get('teams',[1,2,3]))}
