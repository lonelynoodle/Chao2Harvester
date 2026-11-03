"""Merchant preferences shared by trigger-event settings and world navigation."""
MERCHANT_ITEMS = [
    ('evolution', '进化孢子'), ('spore', '强化孢子'), ('divinity', '神性孢子'),
    ('realm', '领域石'), ('polarization', '极化石'), ('gold', '金币'),
    ('dust', '粉尘'), ('lifesteal_core', '嗜血·真实伤害元核'),
]
MERCHANT_SPEC = {'key': 'merchant', 'name': '神秘商人', 'fields': [
    {'key': 'mode', 'label': '遇到神秘商人时', 'type': 'choice', 'default': 'skip',
     'choices': [{'id': 'stop', 'label': '自动停止'}, {'id': 'skip', 'label': '跳过不购买'},
                 {'id': 'random', 'label': '随机点击（不购买）'},
                 {'id': 'buy', 'label': '购买指定物品'}]},
    {'key': 'diamond_budget', 'label': '本轮购买预算（钻石）', 'type': 'number',
     'min': 0, 'max': 100000, 'default': 240, 'enabled_when': 'mode', 'enabled_value': 'buy'},
    {'key': 'items', 'label': '购买优先级', 'type': 'order', 'counts': False,
     'enabled_when': 'mode', 'enabled_value': 'buy',
     'default': [{'id': key, 'label': label, 'enabled': False} for key, label in MERCHANT_ITEMS]},
]}


def merchant_options(settings):
    raw = settings.get('merchant_options', {})
    if not isinstance(raw, dict):
        raise ValueError('神秘商人设置格式错误')
    mode = raw.get('mode', 'skip')
    if type(mode) is not str or mode not in ('stop', 'skip', 'random', 'buy'):
        raise ValueError('神秘商人处理方式无效')
    budget = raw.get('diamond_budget', 240)
    if type(budget) is not int or not 0 <= budget <= 100000:
        raise ValueError('神秘商人购买预算必须为0至100000的整数')
    items = raw.get('items', [])
    if not isinstance(items, list):
        raise ValueError('神秘商人购买物品格式错误')
    labels = dict(MERCHANT_ITEMS)
    seen = set()
    clean = []
    for row in items:
        if not isinstance(row, dict):
            raise ValueError('神秘商人物品格式错误')
        ident = row.get('id')
        if type(ident) is not str or ident not in labels or ident in seen or type(row.get('enabled')) is not bool:
            raise ValueError('神秘商人物品无效、重复或开关格式错误')
        clean.append({'id': ident, 'label': labels[ident], 'enabled': row['enabled']})
        seen.add(ident)
    clean.extend({'id': key, 'label': label, 'enabled': False} for key, label in MERCHANT_ITEMS if key not in seen)
    return {'mode': mode, 'diamond_budget': budget, 'items': clean}
