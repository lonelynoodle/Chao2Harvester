"""Independent capture switch and per-rarity selections/probabilities."""
WILD_SPEC = {'key':'wild_capture','name':'野生怪兽','rarities':[
    {'id':'young','label':'幼体','color':'#398344','probability':80},
    {'id':'phantom','label':'幻化','color':'#287BC1','probability':90,'minimum_probability':90},
    {'id':'ultimate','label':'究极','color':'#914BC0','probability':80},
    {'id':'immortal','label':'不朽','color':'#AA770F','probability':100},
    {'id':'awakened','label':'觉醒','color':'#D94044','probability':100},
]}
RARITIES = {r['id']:r for r in WILD_SPEC['rarities']}


def wild_options(settings):
    raw=settings.get('wild_capture',{})
    if not isinstance(raw,dict) or set(raw)-set(RARITIES):
        raise ValueError('野生怪兽设置必须按品级配置')
    result={}
    for key,spec in RARITIES.items():
        row=raw.get(key,{})
        if not isinstance(row,dict):raise ValueError('野生怪兽品级设置格式错误')
        enabled=row.get('enabled',False);probability=row.get('probability',spec['probability'])
        if type(enabled) is not bool:raise ValueError('捕捉品级必须是勾选项')
        if type(probability) is not int or not 5<=probability<=100 or probability%5:
            raise ValueError('捕捉成功率必须为5%至100%，每5%一档')
        # Migrate legacy thresholds below the client's natural minimum.
        probability=max(probability,spec.get('minimum_probability',5))
        result[key]={'enabled':enabled,'probability':probability}
    return result


def wild_switch(settings):
    # Preserve the effective choice from 0.9.7 when introducing the switch.
    value=settings.get('wild_capture_enabled',any(row['enabled'] for row in wild_options(settings).values()))
    if type(value) is not bool:raise ValueError('自动捕捉开关必须为布尔值')
    return value


def wild_enabled(settings):
    return wild_switch(settings) and any(row['enabled'] for row in wild_options(settings).values())


def required_traps(current,target):
    if type(current) is not int or not 0<=current<=100:
        raise ValueError('当前捕捉成功率未确认')
    return max(0,(target-current+4)//5)
