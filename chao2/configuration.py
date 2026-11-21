"""Versioned task options shared by WPF, CLI and the execution planner."""
from copy import deepcopy
from .wall_settings import wall_spec
from .monster_box_settings import MONSTER_BOX_CHOICES

STAMINA_TASKS = ['copies', 'hunt', 'main']
COCOON_CARDS = [
    ('lower_left','每日任务·左',(400,610)), ('lower_middle','每日任务·中',(640,635)),
    ('lower_right','每日任务·右',(875,610)), ('gold','富有',(400,480)),
    ('spore','全体强化',(380,115)), ('experience','经验',(990,292)),
    ('divinity','神性集合',(295,295)), ('capture','捕兽大师',(201,180)),
    ('evolution','进化试炼',(880,115)), ('wall','墙战',(1090,185)),
    ('polarization','极化之地',(177,425)), ('stone','一地原石',(1110,433)),
    ('summon','造唤梦境',(880,465)),
]
COCOON_DAILIES = ('lower_left','lower_middle','lower_right')
# Display metadata only. Recognition continues to use the stable dungeon ID.
COCOON_REWARDS = {
    'gold':'金币', 'spore':'强化孢子', 'experience':'怪兽经验',
    'divinity':'神性孢子', 'capture':'捕兽夹', 'evolution':'进化孢子',
    'wall':'战墙材料', 'polarization':'极化石', 'stone':'原石',
    'summon':'造唤许可',
}

def flag(key,label,default): return {'key':key,'type':'bool','label':label,'default':default}
def number(key,label,default=0,maximum=100): return {'key':key,'type':'number','label':label,'default':default,'min':0,'max':maximum}
def choice(key,label,items,default):
    return {'key':key,'type':'choice','label':label,'choices':[{'id':i,'label':name} for i,name in items],'default':default}
def ordered(key,label,items,selected=None,counts=False):
    selected = set(selected if selected is not None else [x[0] for x in items])
    return {'key':key,'type':'order','label':label,'counts':counts,
            'default':[{'id':i,'label':name,'enabled':i in selected,**({'limit':0} if counts else {})} for i,name in items]}

def stages(key,label,items,selected,counts=False):
    choices=[{'id':i,'label':name,**({'limit':5} if counts else {}),
              **({'reward':COCOON_REWARDS[i]} if i in COCOON_REWARDS else {})} for i,name in items]
    return {'key':key,'type':'stages','label':label,'counts':counts,'choices':choices,
            'add_label':'添加副本' if key=='targets' else '添加塔',
            'default':[{**x,'enabled':True} for i in selected for x in choices if x['id']==i]}

def reserve(key,label):
    return {**number(key,label+'（0为用完）',0,9999),'advanced':False}

TEAMS = {'key':'teams','type':'teams','label':'阵容顺序','default':[],'min':1,'max':5}
TEAM_HINT = '按列表顺序尝试，通关后前进；全部失败再换关。'
SCORE_HINT = '列表中的每支队伍分别挑战一轮。'
MAX_RUNS = number('max_runs','挑战上限（0不限）')
STAMINA_FIELDS = [flag('auto_three_shots','体力不足时自动领取每日三发',True),
                  flag('auto_potions','自动使用背包移动力药水',False)]
RAMPAGE_BUFFS = [('assist','怪兽助战'),('lifesteal','吸血'),('attack','攻击力'),
                 ('level','谜之怪兽等级'),('damage','伤害提升'),('reduction','减伤'),
                 ('health','生命上限'),('revive','复活'),('dominance','霸气'),
                 ('size','体型'),('speed','移速'),('heal','生命恢复')]

def combat(fields=(), teams=(), mode='clear',limits=True):
    team=deepcopy(TEAMS)
    team['default']=list(teams)
    return {'mode':mode,'hint':SCORE_HINT if mode=='score' else TEAM_HINT,
            'fields':[team,*([deepcopy(MAX_RUNS)] if limits else []),*fields]}

SPECS = {
    'startup':{'default_enabled':True,'hint':'在开始界面点击“进入游戏”。游戏内自动返回任务入口；已有战斗先等本场结算，再按所选顺序执行任务。','fields':[]},
    'exploration':{'hint':'全部领取已完成的探索，再开始探索；需要时一键指派怪兽。','fields':[]},
    # Keep the stable key so existing team, quota and stamina preferences survive.
    'copies':{'mode':'clear','hint':'开启复制体后，先免费领取被其他探索者击破的宝箱；没有20体力、好友币已满或达到挑战次数上限时仍会领奖。','fields':[
        flag('challenge_copies','复制体',True),
        {**deepcopy(TEAMS),'enabled_when':'challenge_copies','indent':18},
        {**deepcopy(MAX_RUNS),'enabled_when':'challenge_copies','indent':18},
        {**flag('include_friends','挑战可获得好友币的复制体',False),'enabled_when':'challenge_copies','indent':18},
        flag('wandering_sage','游荡智者',True),
        {**flag('sage_until_end','持续点击直到智者结束',True),'enabled_when':'wandering_sage','indent':18,
         'description':'未收录的题目也选择选项，答错后继续对话、领取奖励，确认返回地图后结束。'},
        *deepcopy(STAMINA_FIELDS)]},
    'hunt':{'mode':'clear','fields':[
        choice('team','使用队伍',[(str(i),f'队伍 {i}') for i in range(1,6)],'2'),
        flag('auto_settle','自动点击结算',True),
        flag('use_search_tokens','使用库存搜索令',True),number('max_searches','最多搜索次数（0为不限）'),*deepcopy(STAMINA_FIELDS)]},
    'main':{**combat([
        {**flag('auto_deity','神灵自动释放',True),
         'description':'每场主线战斗开始后检查左下角，显示手动时切换为自动。'},
        flag('search_limit_enabled','限制本轮主线搜索次数',False),
        {**number('max_searches','最多搜索次数',50,9999),'min':1,
         'enabled_when':'search_limit_enabled','indent':18,
         'description':'包含重复关卡和未打开详情的搜索，达到后继续下一个任务。'},
        *deepcopy(STAMINA_FIELDS)],teams=(1,2,3)),
        'hint':'每次遇到关卡只用尚未尝试的下一支队伍；再次遇到旧关卡时继续换队，全部失败再跳过。'},
    'tower':combat([reserve('reserve_feathers','保留羽毛'),stages('towers','挑战的塔', [('normal','无限制'),('dragon','祖龙族'),('star','星灵族'),('ghost','尸鬼族'),('native','原生族'),('puppet','木偶族')],['normal']),flag('secret_garden','挑战塔中秘庭',True)]),
    'cocoon':{**combat([
                     {**flag('reserve_spikes_enabled','保留尖刺',False),'description':'不勾选时不保留尖刺，继续挑战所选可打副本，直到尖刺用完。'},
                     {**number('reserve_spikes','保留数量',1,9999),'min':1,'enabled_when':'reserve_spikes_enabled','indent':18},
                     {**flag('daily_tasks','挑战每日任务',True),'description':'优先完成下方三项每日任务，已完成的自动跳过。'},
                     {**flag('refresh_tasks','自动使用魔典',True),
                      'enabled_when':'daily_tasks',
                      'description':'开启每日任务且三项全部完成后刷新，再优先完成新一轮。只使用库存魔典。'},
                     {**flag('refresh_require_three_spikes','刷新前确保可用尖刺至少 3 个',True),
                      'enabled_when':'refresh_tasks',
                      'description':'扣除保留尖刺后计算；不足 3 个时不刷新。关闭后可能留下未完成的每日任务。'},
                     {**number('max_refreshes','最多刷新次数（0为不限）'),'enabled_when':'refresh_tasks'},
                     stages('targets','副本顺序',[(i,n) for i,n,_ in COCOON_CARDS if i not in COCOON_DAILIES],['gold','spore'])],limits=False),
              'hint':'优先每日任务，再按副本顺序消耗尖刺。不勾选保留尖刺就用完；游戏次数已用完或所选队伍均失败时换下一个副本。'},
    'tribe':combat([reserve('reserve_orders','保留战令'),
                    flag('random_totem','无可挑战冒险关卡时随机挑战图腾',True),
                    flag('clear_auction_dot','消除拍卖所红点（只查看，不竞价）',True),
                    flag('clear_dynamics_dot','消除部落动态红点',True),
                    flag('claim_donation_rewards','领取支配核心累计捐献奖励',True)],teams=(2,)),
    'rift':{**combat([reserve('reserve_keys','保留钥匙')],teams=(2,1)),
            'hint':'优先最高关；等级未解锁或所选阵容均失败时回退前一关，本轮不再尝试失败高关。胜利后使用库存钥匙开箱。'},
    'forest':{**combat([
                       {'key':'mode','type':'choice','label':'运行模式',
                        'choices':[{'id':'simple','label':'普通（推荐）'},{'id':'advanced','label':'高级'}],
                        'default':'simple',
                        'notice':'高级模式会平移整张地图并逐节点识别类型，当前不稳定，可能找不到节点或整个任务失败；普通模式只点击当前画面已显示的节点，更稳但探索数量较少。'},
                       {**choice('strategy','探索策略',[('overflow','防溢出优先'),('node','节点优先')],'overflow'),
                        'enabled_when':'mode','enabled_value':'advanced'},
                       reserve('reserve_points','保留探索点'),number('max_explorations','最多探索节点（0不限）'),
                       flag('collect_resources','收取已探索资源',True),
                       {**ordered('node_priority','节点优先级',[
                           ('lamp','森灯'),('beast','凶兽'),('spore','强化孢子'),('divinity','神性孢子'),
                           ('evolution','进化孢子'),('spring','命运之泉'),('unknown','未探明节点')]),
                        'enabled_when':'mode','enabled_value':'advanced'}],teams=(1,2,3)),
              'hint':'优先自动挑战已开放的免费怪兽；探索计时中、探索点用尽或达到探索上限时仍检查挑战。普通模式边拖图边处理，异常最多退出重进3次；高级模式按节点优先级查找。不等待、不加速、不重置。'},
    'origin':{**combat([flag('auto_settle','自动点击结算',True)],teams=(2,),mode='score'),'hint':'北京时间20:00–22:00使用免费次数；多队按顺序轮流出战。'},
    'arena':{**combat([
        choice('opponent','选择对手',[
            ('power_gap','指定战力差优先（最多刷新3次）'),('strongest_below','低于己方的最高战力'),
            ('weakest','战力最低'),('random','随机挑战')],'power_gap'),
        {**number('power_gap_min','比己方低：最小战力差',10000,99999999),'min':1,
         'enabled_when':'opponent','enabled_value':'power_gap'},
        {**number('power_gap_max','比己方低：最大战力差',20000,99999999),'min':1,
         'enabled_when':'opponent','enabled_value':'power_gap'},
        flag('auto_settle','自动点击结算',True)],teams=(2,),mode='score'),
             'hint':'每次寻敌最多免费刷新3次，仍无区间内对手则选当前低于己方的最高战力；仍无可选对手就结束本次斗技场。区间含两端，同一队伍本轮跳过已败对手；按实际出战战力核对，战力不保证胜利。'},
    'nest':{'hint':'当天没有成绩时挑战。勾选重复挑战后，即使已有成绩，也按所选队伍再打一轮；保留当前援军。',
            'mode':'score','fields':[deepcopy(TEAMS),flag('auto_deity','神灵自动释放',True),flag('repeat_challenge','重复挑战',False),ordered('buff_priority','增益优先级',RAMPAGE_BUFFS)]},
    'giant':combat([flag('skip_completed','当天已打过则跳过',True),flag('auto_settle','自动点击结算',True)],teams=(1,),mode='score'),
    'triad':{'hint':'丰野间匹配三阵入局，使用当日免费次数；战斗中的结算按钮仍可见时持续重读并点击。三支队伍需先在游戏内配置。',
             'fields':[flag('auto_settle','自动结算（按钮仍在时持续点击）',True)]},
    'celebration':{'default_enabled':True,'hint':'集中处理丰野间活动；未开放、已结束或没有入口时跳过。',
                   'fields':[
                       flag('triad','三阵入局',True),
                       {**flag('triad_auto_settle','自动结算（按钮仍在时持续点击）',True),'enabled_when':'triad','indent':18},
                       flag('giant','进击巨物',False),
                       {**deepcopy(TEAMS),'key':'giant_teams','default':[1],'enabled_when':'giant','indent':18},
                       {**number('giant_max_runs','挑战上限（0不限）'),'enabled_when':'giant','indent':18},
                       {**flag('giant_skip_completed','当天已打过则跳过',True),'enabled_when':'giant','indent':18},
                       {**flag('giant_auto_settle','自动点击结算',True),'enabled_when':'giant','indent':18},
                       flag('daily_puzzle','拼二每日300分及树叶奖励',False)]},
    'rewards':{'fields':[flag('collect_idle','星律收获',True),ordered('tabs','领奖项目',[('daily','每日挑战'),('side','支线冒险'),('main','主线任务')]),number('max_batches','每项最多领取批次',1,10),
        ordered('world_echoes','世界回响',[('monument','世界丰碑'),('lost','遗落回响'),('torrent','超星洪流'),('notes','微光笔记')])]},
    'other':{'fields':[
        flag('friend_management','好友管理',True),
        {**flag('exchange_friend_coins','一键赠送、收取好友币',True),'enabled_when':'friend_management','indent':18},
        {**flag('remove_inactive_friends','清理长期未登录的好友',False),'enabled_when':'friend_management','indent':18},
        {**number('inactive_days','未登录天数（超过才清理）',5,365),'min':1,
         'enabled_when':'remove_inactive_friends','indent':36,
         'description':'只有明确超过该天数的好友才删除；在线、时间不明或刚好达到该天数的好友保留。'},
        {**flag('auto_add_friends','自动添加好友至上限',True),'enabled_when':'friend_management','indent':18,
         'description':'先同意现有申请，再向推荐玩家申请。需要对方同意时记录等待状态，不重复发送申请。'},
        flag('collect_daily_single','领取每日一发',True),
        {**flag('daily_core_upgrade','每日挑战 · 升级元核',False),
         'description':'按元核列表逐个查找，可选顺序或倒序，确认单次强化成功后停止。'},
        {**choice('daily_core_order','元核查找顺序',[('forward','按列表顺序'),('reverse','按列表倒序')],'forward'),
         'enabled_when':'daily_core_upgrade','indent':18},
        {**flag('daily_monster_upgrade','每日挑战 · 升级怪兽',False),
         'description':'从左往右检查怪兽，用已有怪兽经验升一级，成功后停止。'},
        flag('collect_plane_lord','领取位面领主免费钻石',True),
        flag('collect_contract','蜕变契约任务及奖励',True),
        {**flag('piggy_bank','屯屯扑满（奖励≥200时敲开）',False),
         'description':'每轮最多敲开一次；储存不足200不执行。优先用库存木锤，无库存时只购买1个、费用必须为50钻石；不使用金锤。'},
        flag('buy_star_spores','购买饲星商店进化、强化孢子',True),
        {**flag('convert_star_souls','饲星之魂不足时转化究极怪兽',False),
         'enabled_when':'buy_star_spores','indent':18,
         'description':'只补足孢子购买缺口，逐只转化未培养的究极怪兽；不转化其他品级。'},
        {**flag('evolve_blue_for_star_souls','究极不足时进化1级幻化怪兽',False),
         'enabled_when':'convert_star_souls','indent':36,
         'description':'仅选择1级蓝色幻化怪兽；核对究极品级、金币和进化孢子消耗，不明时停止。'},
        {**flag('buy_blue_eggs_for_star_souls','蓝色怪兽不足时兑换幻化怪兽茧',False),
         'enabled_when':'evolve_blue_for_star_souls','indent':54,
         'description':'先使用背包已有怪兽茧；不足才从饲星商店用饲星之魂兑换，不使用钻石。'},
        {**flag('buy_all_blue_eggs','兑换全部可负担的怪兽茧',False),
         'enabled_when':'buy_blue_eggs_for_star_souls','indent':72},
        {**choice('star_egg_target','怪兽茧选用怪兽',MONSTER_BOX_CHOICES,'停顿'),
         'enabled_when':'buy_blue_eggs_for_star_souls','indent':72},
        flag('tribe_gold_donation','支配核心金币捐献（每天一次）',False),
        flag('open_monster_boxes','自动开启幻化怪兽茧',False),
        {**choice('monster_box_mode','开启方式',[('specified','指定怪兽'),('balanced','均匀开启'),('random','系统随机')],'balanced'),
         'enabled_when':'open_monster_boxes','indent':18,
         'description':'均匀开启按八种怪兽轮换并记住进度；系统随机由脚本随机选择。每次选择消耗一个茧。'},
        {**choice('monster_box_target','指定怪兽',MONSTER_BOX_CHOICES,'暴龙'),
         'enabled_when':'monster_box_mode','enabled_value':'specified','indent':18},
        {**number('monster_box_limit','最多开启（0为全部）',0,9999),
         'enabled_when':'open_monster_boxes','indent':18},
        {**flag('evolve_blue_monsters','蓝怪进化紫怪',False),
         'description':'进化后保留紫怪，跳过锁定蓝怪；可按只数进化，或持续到可用蓝怪、进化孢子不足。金币不足也会停止。'},
        {**choice('blue_evolution_mode','进化方式',[('count','指定只数'),('until_empty','直到蓝怪或进化孢子不足')],'count'),
         'enabled_when':'evolve_blue_monsters','indent':18},
        {**number('blue_evolution_count','进化只数',1,999999),'min':1,
         'enabled_when':'blue_evolution_mode','enabled_value':'count','indent':18},
        flag('clear_bag_notifications','清除背包新物品感叹号',True),
        flag('challenge_abyss','深渊先遣',False),
    ]},
    'finish':{'hint':'保存记录后结束关闭。默认仅全部完成时关闭；可允许部分完成后关闭，但手动停止、设备异常和未知页面仍保留现场。',
              'fields':[flag('close_mumu','关闭MuMu模拟器',True),
                        {**flag('close_app','关闭超二收菜',True),'notice':'关闭后可能无法看到捕捉怪兽的信息；可在运行记录中查看。'},
                        {**flag('close_on_partial','部分任务未完成也关闭',False),'description':'全部任务已处理且确认返回世界后关闭；手动停止和未知页面除外。'}]},
}

for _task,_spec in SPECS.items():
    _fields=_spec['fields']
    _team_index=next((i for i,f in enumerate(_fields) if f['key'] in ('teams','team')),None)
    if _team_index is not None:_fields.insert(_team_index+1,wall_spec('attack' if _task=='nest' else 'ignore'))
SPECS['triad']['fields'].insert(0,wall_spec())
_giant_teams=next(i for i,f in enumerate(SPECS['celebration']['fields']) if f['key']=='giant_teams')
SPECS['celebration']['fields'].insert(_giant_teams+1,{**wall_spec(),'key':'giant_wall_mode','enabled_when':'giant','indent':18})

# Related settings are folded under their subtask's switch in the frontend.
# Keep the option keys and dependencies unchanged for existing templates.
OTHER_SETTING_GROUPS = {
    'friend_management': ('friend_management','exchange_friend_coins','remove_inactive_friends','inactive_days','auto_add_friends'),
    'daily_core_upgrade': ('daily_core_upgrade','daily_core_order'),
    'buy_star_spores': ('buy_star_spores','convert_star_souls','evolve_blue_for_star_souls','buy_blue_eggs_for_star_souls','buy_all_blue_eggs','star_egg_target'),
    'open_monster_boxes': ('open_monster_boxes','monster_box_mode','monster_box_target','monster_box_limit'),
    'evolve_blue_monsters': ('evolve_blue_monsters','blue_evolution_mode','blue_evolution_count'),
}
for field in SPECS['other']['fields']:
    field['compact'] = True
    field['group'] = next((key for key,members in OTHER_SETTING_GROUPS.items() if field['key'] in members),field['key'])

def defaults(task): return {f['key']:deepcopy(f['default']) for f in SPECS[task]['fields']}

def normalize_selected(selected):
    """Migrate removed public tasks without creating a new independent action."""
    result=[]
    for key in selected:
        if key in ('idle','daily_rewards'):key='rewards'
        if key in ('giant','triad'):key='celebration'
        if key in ('overview','three_shots'):continue
        if key not in SPECS:raise ValueError('未知任务：'+str(key))
        if key not in result:result.append(key)
    return result

def normalize_teams(value):
    if not isinstance(value,list) or len(value)>5:raise ValueError('阵容列表最多五支队伍')
    teams=[];seen=set()
    for row in value:
        # Version 2 stored five checkbox rows; only selected rows become entries.
        if isinstance(row,dict):
            ident=row.get('id')
            if ident not in ('1','2','3','4','5') or type(row.get('enabled')) is not bool:
                raise ValueError('队伍序号或开关无效')
            team=int(ident);enabled=row['enabled']
        else:team=row;enabled=True
        if type(team) is not int or not 1<=team<=5 or team in seen:raise ValueError('队伍序号必须为1至5且不能重复')
        seen.add(team)
        if enabled:teams.append(team)
    return teams

def normalize_settings(raw):
    """Preserve unrelated settings; validate closed option sets before any game input."""
    out=deepcopy(raw)
    from .cocoon_settings import migrate_resource_limits
    migrate_resource_limits(out)
    from .rampage_settings import migrate_repeat_challenge
    migrate_repeat_challenge(out)
    from .wild_settings import wild_options,wild_switch
    from .merchant_settings import merchant_options
    from .free_summon import free_summon_enabled
    from .trigger_events import trigger_options
    from .tool_settings import abyss_options
    out['wild_capture']=wild_options(raw)
    out['wild_capture_enabled']=wild_switch(raw)
    out['merchant_options']=merchant_options(raw)
    out['free_summon_enabled']=free_summon_enabled(raw)
    out['trigger_events']=trigger_options(raw)
    out['abyss_options']=abyss_options(raw)
    legacy=out.get('schema_version',0)<5
    options=out.setdefault('task_options',{})
    if not isinstance(options,dict):raise ValueError('任务设置格式错误')
    from .celebration_settings import migrate_celebration
    migrate_celebration(out)
    cocoon=options.get('cocoon',{})
    if legacy and isinstance(cocoon,dict) and isinstance(cocoon.get('targets'),list):
        old=cocoon['targets']
        cocoon.setdefault('daily_tasks',any(isinstance(r,dict) and r.get('id') in COCOON_DAILIES and r.get('enabled',True) for r in old))
        cocoon['targets']=[r for r in old if not isinstance(r,dict) or r.get('id') not in COCOON_DAILIES]
    for removed in ('idle','overview','daily_rewards','three_shots'):options.pop(removed,None)
    if 'tasks' in out:out['tasks']=normalize_selected(out['tasks'])
    stamina=out.setdefault('stamina_settings',{})
    if not isinstance(stamina,dict):raise ValueError('体力设置格式错误')
    stamina.setdefault('auto_three_shots',True)
    if type(stamina['auto_three_shots']) is not bool:raise ValueError('自动领取每日三发必须是开关')
    out.setdefault('follow_running_task',True)
    if type(out['follow_running_task']) is not bool:raise ValueError('自动切换任务设置必须是开关')
    out.setdefault('unordered_tasks',False)
    if type(out['unordered_tasks']) is not bool:raise ValueError('不按任务顺序执行必须是开关')
    for task,spec in SPECS.items():
        saved=options.setdefault(task,{})
        if not isinstance(saved,dict):raise ValueError(f'{task} 设置格式错误')
        if task=='main':saved.pop('max_nodes',None)
        if task=='hunt':
            if 'team' not in saved:
                previous=normalize_teams(saved.get('teams',[]))
                saved['team']=str(previous[0] if previous else 2)
            saved.pop('teams',None)
            saved.pop('max_runs',None)
        if task in STAMINA_TASKS:saved.setdefault('auto_three_shots',stamina['auto_three_shots'])
        for field in spec['fields']:
            key=field['key'];value=saved.setdefault(key,deepcopy(field['default']))
            if field['type']=='bool':
                if not isinstance(value,bool):raise ValueError(f'{task}.{key} 必须是开关')
            elif field['type']=='number':
                if type(value) is not int or not field['min']<=value<=field['max']:raise ValueError(f'{task}.{key} 数值超出范围')
            elif field['type']=='teams':saved[key]=normalize_teams(value)
            elif field['type']=='choice':
                if type(value) is not str or value not in {x['id'] for x in field['choices']}:
                    raise ValueError(f'{task}.{key} 选项无效')
            elif field['type'] in ('order','stages'):
                dynamic=field['type']=='stages'
                allowed={x['id']:x for x in (field['choices'] if dynamic else field['default'])}
                if not isinstance(value,list):raise ValueError(f'{task}.{key} 顺序格式错误')
                seen=set();clean=[]
                for row in value:
                    if not isinstance(row,dict):raise ValueError('项目设置格式错误')
                    ident=row.get('id')
                    if ident not in allowed or ident in seen:raise ValueError(f'{task}.{key} 项目无效或重复')
                    seen.add(ident)
                    enabled=row.get('enabled',True) if dynamic else row.get('enabled')
                    if type(enabled) is not bool:raise ValueError('项目开关格式错误')
                    item={'id':ident,'label':allowed[ident]['label'],'enabled':enabled}
                    if field.get('counts'):
                        count=row.get('limit',allowed[ident].get('limit',0))
                        if type(count) is not int or not 0<=count<=100:raise ValueError('副本次数必须为0至100')
                        item['limit']=count
                    if not dynamic or enabled:clean.append(item)
                if not dynamic:clean.extend(deepcopy(row) for ident,row in allowed.items() if ident not in seen)
                saved[key]=clean
    arena=options['arena']
    if arena['power_gap_min']>arena['power_gap_max']:
        raise ValueError('斗技场最小战力差不能大于最大战力差')
    order=out.setdefault('stamina_order',STAMINA_TASKS.copy())
    if not isinstance(order,list) or sorted(order)!=sorted(STAMINA_TASKS):raise ValueError('体力优先级必须恰好包含异象、狩猎、主线')
    if 'task_order' in out:
        queue=out['task_order']
        if not isinstance(queue,list) or any(type(k) is not str or k not in SPECS for k in queue) or len(queue)!=len(set(queue)):
            raise ValueError('任务顺序包含未知或重复任务')
    out.setdefault('allow_repeat_tasks',False)
    if type(out['allow_repeat_tasks']) is not bool:raise ValueError('允许重复任务必须是开关')
    if 'task_queue' in out:
        if not isinstance(out['task_queue'],list):raise ValueError('任务队列格式错误')
        queue=[];ids=set();kinds=set()
        for row in out['task_queue']:
            if not isinstance(row,dict) or row.get('key') not in SPECS:raise ValueError('任务队列包含未知任务')
            key=row['key'];ident=row.get('id');name=row.get('name',key);enabled=row.get('enabled',True)
            if not isinstance(ident,str) or not 1<=len(ident)<=80 or not all(c.isascii() and (c.isalnum() or c in '_-') for c in ident) or ident in ids:
                raise ValueError('任务实例编号无效或重复')
            ids.add(ident)
            if not isinstance(name,str) or not name.strip() or len(name)>80 or type(enabled) is not bool:raise ValueError('任务名称或开关格式错误')
            if key in kinds and not out['allow_repeat_tasks']:continue
            kinds.add(key)
            instance_options=normalize_settings({'schema_version':8,'task_options':{key:row.get('options',options[key])}})['task_options'][key]
            queue.append({'id':ident,'key':key,'name':name.strip(),'enabled':enabled,'options':instance_options})
        out['task_queue']=queue
    out['schema_version']=8
    return out

def plan_tasks(settings,selected,order):
    """Only selected activities execute; their stamina priority also applies after a claim."""
    selected=normalize_selected(selected)
    if 'task_order' in settings:
        queue=settings['task_order']
        # Wake and shutdown are lifecycle tasks; all ordinary tasks follow the
        # visible queue, including interleaved stamina-consuming activities.
        result=[key for key in queue if key in selected and key not in ('startup','finish')]
        result.extend(key for key in selected if key not in queue and key not in ('startup','finish'))
        return (['startup'] if 'startup' in selected else [])+result+(['finish'] if 'finish' in selected else [])
    prioritized=[x for x in settings['stamina_order'] if x in selected]
    result=[];inserted=False
    for key in order:
        if key in STAMINA_TASKS:
            if not inserted:result.extend(prioritized);inserted=True
        elif key in selected:result.append(key)
    return result

def team_order(options):
    if 'team' in options:return [int(options['team'])]
    return list(options['teams']) or [None]

def selected_rows(options,key): return [r for r in options[key] if r['enabled']]

def limit_reached(limit,count): return limit>0 and count>=limit

def run_team_plan(teams, mode, attempt):
    """attempt returns a settled outcome; unknown/cancelled outcomes propagate as errors.

    Clear tasks stop at the first win. Score tasks run every selected team even
    after a successful round. No team is retried within the same encounter.
    """
    if mode not in ('clear','score'):raise ValueError('未知的阵容执行方式')
    results=[]
    for team in teams:
        result=attempt(team)
        if result not in ('victory','failed','score'):raise RuntimeError('战斗未结算，不能继续轮换')
        results.append((team,result))
        if mode=='clear' and result=='victory':break
    return results
