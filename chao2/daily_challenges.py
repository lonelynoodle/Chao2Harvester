"""Free PvP challenges, free arena refreshes and the once-daily rampage."""
from __future__ import annotations
import random
import re
import time
from datetime import datetime,timezone,timedelta
from .configuration import team_order,RAMPAGE_BUFFS
from .policy import TaskBlocked,SafetyStop,parse_ratio
from .backend import Word

BEIJING=timezone(timedelta(hours=8))
RANK_CHANGE_PATTERN=r'^段位(?:提升|下降|变更)$'


def rank_change_notice(s):
    """The central rank presentation is an overlay, never a battle result."""
    return s.find(RANK_CHANGE_PATTERN,(450,400,380,160))


def pvp_result(s):
    if not s.find('^退出$',(1070,535,210,145)):return None
    if s.find('胜利'):return 'victory'
    if s.find('失败|败退|挑战失败'):return 'failed'
    # The stylized defeat title is often absent from OCR. Require the origin
    # score's negative delta and the defeat-only improvement links together.
    if s.find('^起源殿积分$',(680,220,260,100)):
        delta=re.search(r'[（(]\s*[-−]\s*\d+\s*[)）]',s.region_text((920,220,340,100)))
        links=sum(bool(s.find('^'+name+'$',(580,350,700,160)))
                  for name in ('怪兽培育','元核升级','神灵升阶','阵容调整','黑暗森林'))
        if delta and links>=3:return 'failed'
    return None

def origin_is_open(now=None):
    now=now or datetime.now(BEIJING)
    if now.tzinfo is None:raise ValueError('起源殿时段判断需要带时区的时间')
    return 20<=now.astimezone(BEIJING).hour<22


def origin_resume_state(s):
    # Rank notices have no dungeon title. Close only the presentation and
    # require the subsequent origin score before exiting or rematching.
    if rank_change_notice(s):return 'rank_change'
    if s.find('^正在寻找对手$',(440,100,400,150)) and s.find('^取消匹配$',(460,530,360,100)):
        return 'matching'
    if s.find('^起源殿积分$',(680,220,260,100)) and pvp_result(s):return 'result'
    # Active PvP fights do not display their dungeon title. Only wait for the
    # result in this case; its origin score must confirm identity before exit.
    if (s.find(r'^\d{1,2}:\d{2}$',(490,0,300,100)) and
            s.find('^自动$|^手动$',(75,575,75,75)) and
            not s.find('^退出$|^挑战$|^排阵$')):return 'battle'
    return None


def pvp_settle_button(s,read_text):
    """Only recognize the settlement control on an active battle screen."""
    if (not s.find(r'\d{1,2}:\d{2}',(490,0,300,100)) or
            s.find('^退出$|^匹配$|^排阵$|^挑战$')):
        return None
    button=s.find('^结算$',(130,555,120,100))
    if button:return button
    # The frame OCR often drops 算 beside the animated battle. Read the exact
    # label, rather than accepting the single character 结 as an input target.
    if s.find('^自动$|^手动$',(75,575,75,75)):
        roi=(161,599,52,31)
        if read_text(s,roi).strip()=='结算':
            button=Word('结算',list(roi),.99)
            s.words.append(button)
            return button
    return None

# Card power rows, not the separate score rows immediately above them.
ARENA_CARDS=(
    ((425,342,93,38),(427,452)),
    ((653,387,95,38),(656,499)),
    ((882,387,96,38),(881,499)),
    ((1111,341,100,40),(1117,452)),
)

def arena_candidates(s,read_number=None):
    if not s.has('^斗技场$','挑战次数'):raise TaskBlocked('斗技场对手列表未确认')
    result=[]
    for index,(roi,point) in enumerate(ARENA_CARDS):
        text=s.region_text(roi).strip()
        power=read_number(s,roi) if read_number else int(text) if re.fullmatch(r'\d{2,8}',text) else None
        if power is None or not 10<=power<=99999999:raise TaskBlocked(f'第{index+1}个对手战力未读清')
        name=s.region_text((roi[0]-90,roi[1]-100,190,34))
        rating=arena_rating(s,(roi[0]-10,roi[1]-45,105,35))
        result.append({'index':index,'power':power,'point':point,'name':name,'rating':rating})
    return result

def arena_opponent_key(candidate):
    return (candidate.get('name',''),candidate['power'])


def choose_opponent(candidates,mode,own_power=None,gap_min=10000,gap_max=20000,excluded=()):
    if len(candidates)!=4:raise TaskBlocked('未确认当前四个对手')
    if mode=='weakest':return min(candidates,key=lambda c:c['power'])
    if mode=='random':return random.choice(candidates)
    if mode in ('strongest_below','power_gap'):
        if type(own_power) is not int or own_power<10:raise TaskBlocked('己方出战战力未确认')
        if not 1<=gap_min<=gap_max<=99999999:raise ValueError('斗技场战力差区间无效')
        eligible=[c for c in candidates if c['power']<own_power and arena_opponent_key(c) not in excluded and
                  (mode=='strongest_below' or gap_min<=own_power-c['power']<=gap_max)]
        return max(eligible,key=lambda c:c['power'],default=None)
    raise ValueError('未知斗技场对手选择方式')

def slanted_power(text):
    # Only for the verified gold power row; never apply to costs or resources.
    text=text.strip()
    if not re.fullmatch(r'[0-9Il|/]{2,8}',text):return None
    return int(text.translate(str.maketrans({'I':'1','l':'1','|':'1','/':'1'})))

def arena_rating(s,roi):
    # The rank emblem (IV/Ⅳ) can be joined to the score. Only that prefix
    # is stripped; its strokes must never become additional score digits.
    word=s.find(r'^(?:[IVXⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\s*)?\d{2,6}$',roi)
    return int(re.search(r'\d+$',word.text)[0]) if word else None

def origin_quota(s):
    label=s.find('^剩余免费挑战次数$',(900,545,290,75))
    if not s.find('^起源殿$',(80,0,220,60)) or not label:return None
    number=s.find(r'^\d{1,3}$',(label.box[0]+label.box[2],label.box[1]-5,95,35))
    return int(number.text) if number else None

def arena_quota(s):
    if s.find('^斗技场挑战$',(80,0,300,65)):
        ratio=parse_ratio(s.region_text((1160,0,120,60)))
    elif s.has('^斗技场$','挑战次数'):
        ratio=parse_ratio(s.region_text((785,655,115,55)))
    else:return None
    if not ratio or not 0<=ratio[0]<=ratio[1]<=99:return None
    return ratio[0]

BUFF_PATTERNS={'assist':'怪兽助战|助战|援军|加入.*怪兽','lifesteal':'吸血|生命偷取',
 'attack':'攻击力|攻击.*提升','level':'等级提升|怪兽等级','damage':'伤害提升',
 'reduction':'伤害降低|减伤|受到.*降低','health':'生命.*提升|生命上限',
 'revive':'复活','dominance':'霸气','size':'体型|膨胀','speed':'移速|移动速度','heal':'恢复|回复|治疗'}

def rampage_buff(s,priority=None):
    if not s.find('请选择一个暴走增益'):return None
    cards=[]
    for left in (30,450,870):
        roi=(left,165,380,440)
        button=s.find('^点击选择$',roi)
        if not button:raise TaskBlocked('暴走增益卡片未完整识别')
        text=s.region_text(roi)
        order=[r['id'] for r in priority if r['enabled']] if priority is not None else [k for k,_ in RAMPAGE_BUFFS]
        rank=next((i for i,key in enumerate(order) if re.search(BUFF_PATTERNS[key],text)),len(order))
        cards.append((rank,button,text))
    _,button,text=min(cards,key=lambda c:c[0])
    return button,text

class DailyChallenges:
    def dismiss_rank_change(self,s):
        notice=rank_change_notice(s)
        if notice is None:return s
        self.b.guard(s)
        number=len(self.report.setdefault('rank_changes',[]))+1
        row={'label':notice.text,'rank':s.region_text((470,390,340,95)),
             'status':'observed','close_attempts':0}
        self.report['rank_changes'].append(row)
        self.b.save_screen(s,self.report['folder']/f'rank-change-{number}.png')
        self.note(f'检测到{notice.text}，关闭展示后核对实际结算');self.checkpoint()
        def close(q):
            label=rank_change_notice(q)
            if label is None:return
            self.b.click_at(q,(935,545),['^'+re.escape(label.text)+'$'],'关闭段位变更展示，继续核对结算')
            row['close_attempts']+=1;self.checkpoint()
        close(s)
        s=self.wait_for_screen(lambda q:rank_change_notice(q) is None,'段位变更展示关闭',
                               timeout=3,retry_navigation=close)
        row['status']='dismissed';self.checkpoint()
        return s

    def read_pvp_quota(self,s,task):
        if task=='origin':
            value=origin_quota(s)
            if value is None and s.has('^起源殿$','^剩余免费挑战次数$','^匹配$'):
                # A single 9 is missed by text detection; recognize just its
                # digits without the dark box's right border (read as '|').
                value=self.b.read_number(s,(1143,574,32,29))
            return value if value is not None and 0<=value<=99 else None
        value=arena_quota(s)
        if value is not None and value>0:return value
        if s.has('^斗技场$','挑战次数'):roi=(780,660,108,40)
        elif s.find('^斗技场挑战$',(80,0,300,65)):roi=(1160,0,120,60)
        else:return None
        # Confirm zero locally too: a missed leading digit must not turn
        # 10/15 into "no tickets". Unknown is never silently treated as zero.
        local=parse_ratio(self.b.read_text_crop(s,roi))
        if not local or not 0<=local[0]<=local[1]<=99:return None
        if value is not None and local[0]!=value:
            enlarged=parse_ratio(self.b.read_text_region(s,roi,scale=2))
            if enlarged!=local:return None
        return local[0]

    def await_pvp_quota(self,s,task,expected=None):
        for attempt in range(3):
            self.b.guard(s);value=self.read_pvp_quota(s,task)
            if value is not None and (expected is None or value==expected):
                if value==0:self.b.save_screen(s,self.report['folder']/(task+'-quota.png'))
                return s,value
            if attempt==2:break
            if attempt==0:self.note(('起源殿' if task=='origin' else '斗技场')+'次数未确认，正在重新读取…')
            self.b.sleep(.6);s=self.observe()
        self.b.save_screen(s,self.report['folder']/(task+'-quota.png'))
        return s,value

    def enter_building(self,title,*anchors):
        task={'斗技场':'arena','谜之巢穴':'nest'}.get(title)
        pattern='^[谜迷]之巢穴$' if title=='谜之巢穴' else '^'+title+'$'
        if task and self.overview_prepared_for(task):
            return self.enter_overview(pattern)
        try:
            s=self.territory()
            if title=='谜之巢穴':
                # The 永生之茧 map label is the nest entrance's territory anchor;
                # full-frame OCR can miss it, so re-read the region before stopping.
                self.b.confirm_label(s,'永生之茧',(780,140,210,170))
                self.b.click_at(s,(523,80),['^世界$','^排阵$','永生之茧'],'进入谜之巢穴')
            else:self.b.click_text(s,'^'+title+'$',roi=(170,35,990,590))
            return self.await_page(pattern,*anchors)
        except TaskBlocked as e:
            # Map anchors are the least reliable evidence in this game. The
            # 任务挑战 overview keeps a second entrance that is located by its
            # card title while scrolling, so retry there instead of giving up.
            if not task:raise
            self.note(f'{title}地图入口未确认（{e}），改用任务挑战兜底')
            self.overview_entry(task,reason=title+'地图入口未确认')
            return self.await_page(pattern,*anchors)

    def arena_detail(self):
        return self.await_page('^斗技场挑战$','^对战$','^挑战$','^排阵$')

    def read_arena_candidates(self,s):
        # The italic digit 1 is sometimes read as '/', and cards may animate
        # after settlement. Re-OCR the power row, then wait for a stable page.
        for attempt in range(4):
            self.b.guard(s)
            try:return s,arena_candidates(s,self.read_arena_power)
            except TaskBlocked as error:
                if attempt==3:raise
                self.note(f'{error}，重新读取对手列表（{attempt+1}/3）')
                self.b.sleep(.8);s=self.observe()

    def read_arena_power(self,s,roi):
        from .power_digits import arena_power_digits,glyphs
        digits=arena_power_digits(s,roi)
        if digits is not None:return digits
        count=len(glyphs(s.image,roi))
        def candidate(text):
            value=slanted_power(text)
            # Two OCR passes can both lose the same narrow leading 1. When
            # the image contains five separate glyphs, four digits cannot win
            # a vote just because that error occurred twice.
            return value if value is not None and (not count or len(str(value))==count) else None
        full=candidate(s.region_text(roi))
        local=candidate(self.b.read_text_region(s,roi))
        if local is not None and local==full:return local
        doubled=candidate(self.b.read_text_region(s,roi,scale=2))
        # Native detection can omit a narrow '1'. Require agreement between
        # two of full-frame, local and enlarged-local recognition.
        return doubled if doubled is not None and doubled in (full,local) else None

    def verify_arena_detail(self,s,candidate):
        quota=self.read_pvp_quota(s,'arena')
        if quota is None or quota<1:raise TaskBlocked('斗技场免费次数不足或未读清')
        value=self.read_arena_power(s,(1112,432,91,35))
        if value!=candidate['power']:
            # Italic power can lose/merge digits (59670 -> 5670). A matching
            # full player name AND ranking points establishes identity instead.
            name=s.region_text((975,395,215,38))
            rating=arena_rating(s,(790,410,100,50))
            if rating is None and candidate.get('name') and name==candidate['name']:
                local=self.b.read_text_region(s,(803,418,72,40),scale=2)
                if re.fullmatch(r'\d{2,6}',local):rating=int(local)
            same=(candidate.get('name') and name==candidate['name'] and rating is not None and
                  candidate.get('rating')==rating)
            if not same:raise TaskBlocked('斗技场对手在进入详情后改变或姓名积分未读清，停止本次挑战')
            self.note('对手战力字体识别不一致，已用姓名和积分再次核实同一对手')
        if self.b.read_number(s,(1041,629,23,27))!=1:
            raise TaskBlocked('未确认斗技场费用为1次免费挑战')
        return quota

    def verified_arena_detail(self,s,candidate):
        for retry in range(4):
            self.b.guard(s)
            try:
                quota=self.verify_arena_detail(s,candidate)
                return s,quota
            except TaskBlocked:
                if retry==3:raise
                self.note(f'斗技场对手或免费费用未读清，重新识别（{retry+1}/3）')
                self.b.sleep(.7);s=self.arena_detail()

    def arena_own_power(self,s):
        if not s.has('^斗技场挑战$','^对战$','^排阵$'):
            raise TaskBlocked('己方战力必须在出战详情中读取')
        value=self.read_arena_power(s,(139,432,105,35))
        if value is None or not 10<=value<=99999999:raise TaskBlocked('己方出战战力未读清')
        return value

    def prepare_arena_team(self,s,team,change_team):
        # The list displays DEFENCE power. Open a preview to select the actual
        # attacking team, read its power, then return to a fresh opponent list.
        s,rows=self.read_arena_candidates(s)
        self.b.click_at(s,rows[0]['point'],['^斗技场$','挑战次数'],'打开预览核对出战队伍')
        detail=self.arena_detail()
        if change_team:detail=self.select_team(detail,team,return_page=self.arena_detail)
        for attempt in range(4):
            self.b.guard(detail)
            try:power=self.arena_own_power(detail);break
            except TaskBlocked:
                if attempt==3:raise
                self.b.sleep(.6);detail=self.arena_detail()
        self.b.save_screen(detail,self.report['folder']/'arena-own-team.png')
        self.report['arena_own_power']=power
        self.b.click_at(detail,(43,28),['^斗技场挑战$','^排阵$'],'已核对出战队伍，返回寻敌')
        return self.await_page('^斗技场$','挑战次数'),power

    def refresh_arena(self,s,previous):
        """Wait for the verified free control, send once, then check its effect."""
        before=self.read_pvp_quota(s,'arena')
        if before is None or before<1:raise TaskBlocked('斗技场无免费次数，停止寻敌')
        until=time.monotonic()+40
        while time.monotonic()<until:
            self.check_budget('arena');self.b.guard(s)
            if not s.has('^斗技场$','挑战次数') or s.find('^取消$|^确定$|^购买$'):
                raise TaskBlocked('斗技场刷新页面改变，未点击')
            if self.read_pvp_quota(s,'arena')!=before:raise TaskBlocked('寻敌时免费次数改变，停止刷新')
            self.b.confirm_label(s,'^换一批$',(1160,610,120,110),threshold=.8)
            # Exact captured circle + caption, no currency/price. A timer or
            # a paid refresh appearance cannot satisfy this free-only control.
            text=s.region_text((1160,610,120,110))
            ready=(s.find('^换一批$',(1160,610,120,110)) and not re.search(r'\d|钻|金币|消耗',text) and
                   self.b.match_template(s,'arena-free-refresh.png',[1170,620,100,90],.90))
            if ready:
                self.b.click_at(s,(1212,659),['^斗技场$','挑战次数','^换一批$'],'斗技场免费换一批')
                break
            self.b.sleep(1);s=self.observe()
        else:raise TaskBlocked('斗技场免费换一批按钮未就绪，未付费刷新')
        fingerprint=lambda rows:[(r.get('name'),r['power'],r.get('rating')) for r in rows]
        until=time.monotonic()+20
        while time.monotonic()<until:
            self.check_budget('arena');s=self.observe();self.b.guard(s)
            if not s.has('^斗技场$','挑战次数'):
                self.b.sleep(.5);continue
            s,rows=self.read_arena_candidates(s)
            if self.read_pvp_quota(s,'arena')!=before:raise TaskBlocked('刷新后免费次数改变，停止寻敌')
            cooldown=s.find(r'^\d{2}:\d{2}:\d{2}$',(1150,610,130,110))
            if fingerprint(rows)!=fingerprint(previous) or cooldown:
                count=self.report.get('arena_refreshes',0)+1;self.report['arena_refreshes']=count
                self.note(f'斗技场已免费刷新{count}次，重新筛选对手');self.checkpoint()
                return s
            self.b.sleep(.5)
        raise TaskBlocked('斗技场换一批未核实生效，停止重复点击')

    def verify_arena_match(self,s,candidate,own_power):
        s,quota=self.verified_arena_detail(s,candidate)
        if own_power is not None:
            if self.arena_own_power(s)!=own_power:raise TaskBlocked('寻敌后己方出战战力改变，未挑战')
            power=self.read_arena_power(s,(1112,432,91,35))
            if power is not None and power!=candidate['power']:
                raise TaskBlocked('寻敌后对手战力改变，未挑战')
        return s,quota

    def pvp_battle(self,task,*,entry=None,verify_origin=False,allow_settle=True):
        self.battles+=1
        self.task_counts[task]=self.task_counts.get(task,0)+1
        settlement={'task':task,'attempt':self.task_counts[task],'clicks':0,'outcome':None}
        self.report.setdefault('pvp_settlements',[]).append(settlement)
        until=time.monotonic()+int(self.b.settings.get('battle_timeout_seconds',240))
        feedback=time.monotonic();network_retries=0;preview_saved=False
        while time.monotonic()<until:
            s=entry if entry is not None else self.observe_battle();entry=None;self.b.guard(s)
            if self.retry_battle_network(s,network_retries):
                network_retries+=1;continue
            if rank_change_notice(s):s=self.dismiss_rank_change(s)
            outcome=pvp_result(s)
            if outcome:
                if verify_origin and not s.find('^起源殿积分$',(680,220,260,100)):
                    raise TaskBlocked('已有战斗已结算，但未确认属于起源殿，保留结算页')
                self.b.save_screen(s,self.report['folder']/(task+'-result.png'))
                settlement['outcome']=outcome;self.checkpoint()
                return s,outcome
            if s.find('结算') and not s.find('^匹配$'):
                self.b.save_screen(s,self.report['folder']/(task+'-settle-control.png'))
            if not preview_saved and s.find(r'\d{1,2}:\d{2}',(490,0,300,100)):
                self.b.save_screen(s,self.report['folder']/(task+'-battle.png'));preview_saved=True
            if allow_settle and self.options[task]['auto_settle']:
                button=pvp_settle_button(s,self.b.read_text_crop)
                if button:
                    # Sending one tap does not confirm that the client accepted
                    # it. Re-observe after the normal 2s input delay and retry
                    # only while the active battle's exact control is visible.
                    self.b.save_screen(s,self.report['folder']/(task+'-before-settle.png'))
                    self.b.click_at(s,button.center,['^结算$',r'\d{1,2}:\d{2}'],'点击对战结算')
                    settlement['clicks']+=1
                    label='起源殿' if task=='origin' else '斗技场'
                    self.note(label+('已点击结算，继续核对按钮和实际结果' if settlement['clicks']==1 else
                        f'结算按钮仍在，重新识别后补点；本场累计{settlement["clicks"]}次'))
                    self.checkpoint()
                    continue
            if time.monotonic()-feedback>=15:
                self.note(('起源殿' if task=='origin' else '斗技场')+'战斗或匹配中，等待结算…')
                feedback=time.monotonic()
            self.b.sleep(2)
        raise SafetyStop('免费对战未在时限内结算，保留现场')

    def retry_battle_network(self,s,retries):
        if not s.has(r'^网络翻船中，是否重试[?？]$','^确定$','^取消$'):return False
        if retries>=2:raise SafetyStop('战斗网络重试两次仍未恢复，保留现场')
        self.note('游戏连接中断，重试本次结算（不重新开战）')
        self.b.click_text(s,'^确定$',roi=(690,440,210,100))
        return True

    def record_daily_fight(self,task,team,outcome,**details):
        self.report.setdefault('team_attempts',[]).append({'task':task,'team':team,'outcome':outcome,**details})
        self.checkpoint()

    def find_arena_opponent(self,s,team,own_power,excluded):
        options=self.options['arena'];mode=options['opponent']
        context={'team':team,'own_power':own_power,'mode':mode,'instance_id':self.report_key('arena')}
        searches=self.report.setdefault('arena_searches',[])
        search=searches[-1] if searches else None
        if not search or search.get('status')!='searching' or any(search.get(k)!=v for k,v in context.items()):
            search={**context,'refreshes':0,'status':'searching','fallback':False};searches.append(search)
        while True:
            self.check_budget('arena')
            s,candidates=self.read_arena_candidates(s)
            selected_mode=mode
            candidate=choose_opponent(candidates,mode,own_power,options['power_gap_min'],options['power_gap_max'],excluded)
            if candidate is None and search['refreshes']>=3:
                selected_mode='strongest_below'
                candidate=choose_opponent(candidates,selected_mode,own_power,excluded=excluded)
                search['fallback']=candidate is not None and mode=='power_gap'
                if candidate is None:
                    search['status']='unmatched';self.checkpoint()
                    return s,None,search
                self.note('斗技场已达到3次刷新上限，选择当前低于己方的最高战力对手：'+str(candidate['power']))
            if candidate is not None:
                search.update(status='selected',selection_mode=selected_mode,opponent=dict(candidate))
                self.checkpoint();return s,candidate,search
            self.note(f'当前没有符合条件的对手，等待免费换一批（本次寻敌{search["refreshes"]}/3）')
            s=self.refresh_arena(s,candidates)
            search['refreshes']+=1;self.checkpoint()

    def arena(self):
        s=self.enter_building('斗技场','挑战次数');count=0;reason=''
        options=self.options['arena'];teams=team_order(options);last_team=object();losses={}
        mode=options['opponent'];matching=mode in ('strongest_below','power_gap')
        while True:
            s,quota=self.await_pvp_quota(s,'arena')
            if quota is None:raise TaskBlocked('斗技场免费次数未读清')
            self.resource_balance('arena','免费次数',quota)
            self.report['arena_remaining']=quota
            if quota==0:break
            self.check_budget('arena')
            team=teams[count%len(teams)];own_power=None
            if matching:
                s,own_power=self.prepare_arena_team(s,team,team!=last_team);last_team=team
                self.note(f'斗技场出战战力{own_power}，'+(f'寻找低{options["power_gap_min"]}～{options["power_gap_max"]}的对手' if mode=='power_gap' else '寻找低于己方的最高战力对手'))
            s,candidate,search=self.find_arena_opponent(s,team,own_power,losses.get(team,set()))
            if candidate is None:
                reason=f'刷新3次后当前没有可选的低于己方战力对手，结束本次斗技场，剩余{quota}次'
                break
            self.note(f"斗技场：选择第{candidate['index']+1}位对手，战力{candidate['power']}，剩余{quota}次")
            self.b.save_screen(s,self.report['folder']/'arena-selected.png')
            self.report['arena_selected']=dict(candidate)
            self.b.click_at(s,candidate['point'],['^斗技场$','挑战次数'],'查看所选斗技场对手')
            detail,_=self.verified_arena_detail(self.arena_detail(),candidate)
            if team!=last_team:
                detail=self.select_team(detail,team,return_page=self.arena_detail);last_team=team
            detail,before=self.verify_arena_match(detail,candidate,own_power)
            self.check_budget('arena');self.active_task='arena'
            self.start_challenge('arena',detail,'斗技场免费挑战',lambda q:self.verify_arena_match(q,candidate,own_power))
            result,outcome=self.pvp_battle('arena')
            self.exit_result(result)
            s=self.await_page('^斗技场$','挑战次数')
            s,after=self.await_pvp_quota(s,'arena',before-1)
            count+=1;self.report['arena_remaining']=after
            if outcome=='failed':losses.setdefault(team,set()).add(arena_opponent_key(candidate))
            self.record_daily_fight('arena',team,outcome,opponent=candidate['index']+1,power=candidate['power'],own_power=own_power,
                power_gap=own_power-candidate['power'] if own_power is not None else None,mode=mode,
                selection_mode=search['selection_mode'],search_refreshes=search['refreshes'],fallback=search['fallback'],
                remaining=after,quota_verified=after==before-1)
            self.resource_spent('arena','免费次数',1 if after==before-1 else None,after)
            if after!=before-1:
                raise TaskBlocked(f'斗技场已结算，但免费次数变化未确认（挑战前{before}，之后{after if after is not None else "未读清"}），停止连打')
            self.note(f'斗技场已结算{count}场，剩余{after}次')
        self.home()
        return f'斗技场已结算{count}场，'+(reason or '免费次数已用完')

    def origin(self):
        if not origin_is_open():return '已跳过起源殿：当前不在北京时间20:00–22:00'
        entry=getattr(self,'_origin_entry',None);self._origin_entry=None;count=0
        if entry is not None:
            state=origin_resume_state(entry)
            if not state:raise TaskBlocked('起源殿接续状态未确认，保留现场')
            self.active_task='origin'
            phase={'matching':'匹配','result':'结算','rank_change':'段位变更，等待起源殿积分确认',
                   'battle':'战斗，等待起源殿积分确认'}[state]
            self.note('接续已有'+phase+'，沿用当前阵容')
            result,outcome=self.pvp_battle('origin',entry=entry,verify_origin=True,allow_settle=state in ('matching','result'))
            self.exit_result(result)
            s=self.await_page('^起源殿$','^匹配$','剩余免费挑战次数')
            s,after=self.await_pvp_quota(s,'origin')
            if after is None:raise TaskBlocked('接续战斗已结算，但剩余免费次数未读清')
            count=1;self.report['origin_remaining']=after
            self.resource_spent('origin','免费次数',None,after)
            self.record_daily_fight('origin',None,outcome,remaining=after,resumed=True,quota_verified=False)
            self.note(f'已接续结算1场，剩余{after}次；接管前次数未读取，不推算该场消耗')
        else:s=self.enter_building('起源殿','^匹配$','剩余免费挑战次数')
        teams=team_order(self.options['origin']);last_team=object()
        while True:
            s,quota=self.await_pvp_quota(s,'origin')
            if quota is None:raise TaskBlocked('起源殿免费次数未读清')
            self.resource_balance('origin','免费次数',quota)
            self.report['origin_remaining']=quota
            if quota==0:break
            if not origin_is_open():
                self.home();return f'起源殿已结算{count}场，已到22:00，剩余{quota}次'
            self.check_budget('origin');team=teams[count%len(teams)]
            if team!=last_team:
                s=self.select_team(s,team,return_page=lambda:self.await_page('^起源殿$','^匹配$','剩余免费挑战次数'));last_team=team
            s,before=self.await_pvp_quota(s,'origin')
            if before is None or before<=0:raise TaskBlocked('起源殿免费次数未确认，停止匹配')
            if not origin_is_open():continue
            self.check_budget('origin');self.active_task='origin'
            self.b.click_text(s,'^匹配$')
            result,outcome=self.pvp_battle('origin');self.exit_result(result)
            s=self.await_page('^起源殿$','^匹配$','剩余免费挑战次数')
            s,after=self.await_pvp_quota(s,'origin',before-1)
            count+=1;self.report['origin_remaining']=after
            self.record_daily_fight('origin',team,outcome,remaining=after,quota_verified=after==before-1)
            self.resource_spent('origin','免费次数',1 if after==before-1 else None,after)
            if after!=before-1:
                raise TaskBlocked(f'起源殿已结算，但免费次数变化未确认（挑战前{before}，之后{after if after is not None else "未读清"}），停止连打')
            self.note(f'起源殿已结算{count}场，剩余{after}次')
        self.home();return f'起源殿已结算{count}场，免费次数已用完'

    def rampage_ready(self):
        return self.await_page('^[谜迷]之巢穴$','^暴走旷野$','最高击破数','^挑战$')

    def rampage_score(self,s):
        if not s.has('^[谜迷]之巢穴$','最高击破数','我的排名'):
            raise TaskBlocked('暴走旷野每日成绩页未确认')
        word=s.find(r'^\d{1,6}$',(1150,402,95,42))
        score=int(word.text) if word else None
        if score is None:
            score=self.b.read_number(s,(1165,406,78,32))
        if score is None:
            # A medal icon is merged into OCR on ranked entries. Derive the
            # numeric crop width from the actual recognized suffix; a fixed
            # three-digit crop would truncate records of 1,000 or more.
            word=s.find(r'^[^\d]+\d{1,6}$',(1150,402,95,42))
            if word:
                digits=re.search(r'\d+$',word.text)[0]
                width=len(digits)*14+6
                score=self.b.read_number(s,(1242-width,405,width,34))
                if score is not None and score!=int(digits):score=None
        if score is None:raise TaskBlocked('暴走旷野今日击破数未读清')
        return score

    def rampage_battle(self):
        self.battles+=1;self.task_counts['nest']=self.task_counts.get('nest',0)+1
        until=time.monotonic()+720;feedback=time.monotonic();network_retries=0
        while time.monotonic()<until:
            s=self.observe_battle();self.b.guard(s)
            if self.retry_battle_network(s,network_retries):
                network_retries+=1;continue
            if s.find('请选择一个暴走增益'):
                button,description=rampage_buff(s,self.options['nest']['buff_priority'])
                self.b.save_screen(s,self.report['folder']/'rampage-buff.png')
                self.b.click_at(s,button.center,['请选择一个暴走增益','^点击选择$'],'选择暴走增益：'+description)
                self.note('暴走旷野已选择增益：'+description)
                continue
            if s.has('^退出$','本场击破数','本场金币奖励'):
                self.b.save_screen(s,self.report['folder']/'rampage-result.png')
                kills=s.find(r'^(?:新纪录)?\d{1,6}$',(1050,355,200,45))
                coins=s.find(r'^\d{1,9}$',(1070,400,180,45))
                self.report['rampage_settlement']={'kills':int(re.search(r'\d+$',kills.text)[0]) if kills else None,
                    'gold':int(coins.text) if coins else None}
                return s
            if time.monotonic()-feedback>=15:
                self.note('暴走旷野挑战中，等待成绩结算…');feedback=time.monotonic()
            self.b.sleep(2)
        raise SafetyStop('暴走旷野未在12分钟内结算，保留现场')

    def nest(self):
        s=self.enter_building('谜之巢穴','^暴走旷野$')
        self.b.click_text(s,'^暴走旷野$');s=self.rampage_ready()
        score=self.rampage_score(s);self.report['rampage_score_start']=score
        if score>0:
            self.day['rampage_done']=True;self.save_state()
            self.home();return f'今日暴走旷野已有{score}击破成绩，已跳过'
        count=0
        for team in team_order(self.options['nest']):
            self.check_budget('nest')
            if team is not None:s=self.apply_saved_team(s,team)
            # Recheck the real ready page after copying, without changing allies.
            s=self.rampage_ready();self.check_budget('nest');self.active_task='nest'
            self.start_challenge('nest',s,'暴走旷野免费挑战')
            result=self.rampage_battle();self.exit_result(result)
            s=self.rampage_ready();score=self.rampage_score(s)
            if score<=0:raise TaskBlocked('暴走旷野退出后未确认有效成绩')
            count+=1;self.report['rampage_score_end']=score
            self.record_daily_fight('nest',team,'score',score=score)
            self.day['rampage_done']=True;self.save_state()
            self.note(f'暴走旷野已结算，今日最高击破{score}')
        self.home();return f'暴走旷野已完成{count}场，今日最高击破{score}'
