"""Wall preferences shared by the frontend and combat paths."""
WALL_MODES=('ignore','attack','defense')

def wall_spec(default='ignore'):
    return {'key':'wall_mode','type':'choice','label':'战墙',
            'choices':[{'id':'ignore','label':'忽视（不检查）'},
                       {'id':'attack','label':'进攻型'},{'id':'defense','label':'防御型'}],
            'default':default,'description':'本轮已确认且类型相同时直接沿用；需要另一类型时再切换。忽视时不检查、不切换；结束后不恢复。'}

def validate_wall_mode(value):
    if type(value) is not str or value not in WALL_MODES:raise ValueError('战墙设置必须为忽视、进攻型或防御型')
    return value
