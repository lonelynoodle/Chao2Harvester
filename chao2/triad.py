"""Seasonal three-squad event. Inputs require a confirmed free event page.

Each new battle observation may click the still-visible settlement control.
Input acknowledgement does not prove that a round settled; keep rechecking
until the final result, while respecting cancellation and the match timeout.
"""
from __future__ import annotations

import re
import time
from datetime import datetime,timezone,timedelta

import numpy as np

from .daily_challenges import pvp_result,pvp_settle_button
from .event_hub import activity_entry,activity_availability,event_hub_anchors,is_event_hub
from .policy import TaskBlocked,SafetyStop,PageChanged


TITLE = r'^三阵入局$'
MATCH = r'^(?:开始)?匹配$'
ROUND = re.compile(r'第\s*([一二三123])\s*(?:阵|局|场|回合)')
NO_ATTEMPTS = r'今日(?:免费)?(?:挑战|匹配)次数(?:已)?用完|今日.*无剩余次数|次数不足|挑战次数已用完'


def is_triad_lobby(s):
    return bool(not is_event_hub(s) and s.find(TITLE,(0,0,1280,180)) and
                (s.find(MATCH,(150,430,1100,260)) or s.find('剩余.*(?:挑战|匹配).*次数|(?:挑战|匹配).*剩余次数|'+NO_ATTEMPTS)))


def is_triad_matching(s):
    return bool(s.find('正在匹配|匹配中|正在寻找对手') and
                s.find('取消匹配|匹配中|正在寻找对手') and not s.find('^退出$'))


def is_triad_battle(s,*,known_match=False):
    # Used within an established triad match only. A timer plus auto control
    # is shared by all battles and must not classify an arbitrary startup.
    return bool((triad_hud_round(s) or ((known_match or ROUND.search(s.text)) and
                s.find(r'^\d{1,2}:\d{2}$',(450,0,380,110)))) and
                (s.find('^自动$|^手动$',(65,550,125,125)) or s.find('^结算$',(100,540,190,135))) and
                not s.find('^退出$|^匹配$'))


def triad_hud_round(s):
    """Recognize the two-sided 2/3/5 portrait-bar layout, including dead units.

    The black top/bottom borders remain after a unit loses all HP. Require
    both sides' complete slot pattern plus green HP pixels, not scene color.
    """
    if s.find('^退出$|^匹配$|^排阵$'):return None
    im=s.image
    def slots(xs):
        return [bool((np.max(im[[35,41],x:x+72],axis=2)<24).mean()>.95) for x in xs]
    left=slots((200,280,360,440,520));right=slots((690,770,850,930,1010))
    bars=im[36:41,195:1085].astype('int16');b,g,r=(bars[:,:,i] for i in range(3))
    if ((g>115)&(g>r*1.15)&(g>b*1.15)).sum()<150:return None
    for number,round_id in ((2,'1'),(3,'2'),(5,'3')):
        if left==[False]*(5-number)+[True]*number and right==[True]*number+[False]*(5-number):
            return round_id
    return None


def triad_round(s):
    match=ROUND.search(s.text)
    if match:return {'一':'1','二':'2','三':'3'}.get(match[1],match[1])
    return triad_hud_round(s)


def triad_is_open(s,now=None):
    schedule=s.find(r'^\d{1,2}:\d{2}\s*[-—–]\s*\d{1,2}:\d{2}开启$',(900,540,380,90))
    if not schedule:return None
    a,b,c,d=map(int,re.findall(r'\d+',schedule.text))
    if not (0<=a<24 and 0<=c<24 and 0<=b<60 and 0<=d<60):return None
    now=now or datetime.now(timezone(timedelta(hours=8)))
    if now.tzinfo is None:raise ValueError('三阵入局时段判断需要带时区的时间')
    local=now.astimezone(timezone(timedelta(hours=8)));minute=local.hour*60+local.minute
    start=a*60+b;end=c*60+d
    return start<=minute<end if start<=end else minute>=start or minute<end


def triad_settle_button(s,read_text):
    button=pvp_settle_button(s,read_text)
    if button or not is_triad_battle(s,known_match=True):return button
    button=s.find('^结算$',(130,555,120,100))
    if button:return button
    roi=(161,599,52,31)
    if read_text(s,roi).strip()=='结算':
        from .backend import Word
        button=Word('结算',list(roi),.99);s.words.append(button);return button


def triad_quota(s,read_number=None):
    """Only interpret numbers explicitly labelled *remaining*, never 1/3 score."""
    if not is_triad_lobby(s):return None
    if s.find(NO_ATTEMPTS):return 0
    for word in s.words:
        if not re.search(r'剩余.*(?:挑战|匹配).*次数|(?:挑战|匹配).*剩余次数|剩余次数',word.text):continue
        tail=word.text[word.text.find('次数')+2:] if '次数' in word.text else ''
        number=re.search(r'\d{1,2}(?=\s*(?:次|/\s*\d{1,2})?\s*$)',tail)
        if number:return int(number[0])
        x,y,w,h=word.box
        nearby=[v for v in s.words if v is not word and
                x+w-5<=v.center[0]<min(1280,x+w+120) and abs(v.center[1]-word.center[1])<max(30,h)]
        for value in nearby:
            number=re.fullmatch(r'\s*(\d{1,2})(?:\s*/\s*\d{1,2})?\s*',value.text)
            if number:return int(number[1])
        if read_number and re.fullmatch(r'剩余(?:免费)?(?:挑战|匹配)次数',word.text) and 950<=x<1200 and 620<=y<700:
            value=read_number(s,(x+w+6,y-3,min(40,1280-x-w-6),h+7))
            if value is not None and 0<=value<=99:return value
    return None


def triad_quota_digit_image(s,roi):
    """Isolate gold quota glyphs, excluding the nearby button underline."""
    import cv2
    x,y,w,h=roi;crop=s.image[y:y+h,x:x+w].astype('int16')
    b,g,r=(crop[:,:,i] for i in range(3))
    mask=((r>200)&(g>125)&(r>b+40)&(g>b+35)).astype('uint8')
    _,labels,stats,_=cv2.connectedComponentsWithStats(mask,8)
    keep=[i for i,(a,b,width,height,area) in enumerate(stats[1:],1)
          if 2<=width<=22 and 10<=height<=28 and area>=12]
    if not 1<=len(keep)<=2:return None
    mask=np.isin(labels,keep).astype('uint8')*255
    yy,xx=np.where(mask)
    glyph=mask[yy.min():yy.max()+1,xx.min():xx.max()+1]
    glyph=cv2.resize(glyph,None,fx=4,fy=4,interpolation=cv2.INTER_NEAREST)
    glyph=cv2.copyMakeBorder(255-glyph,24,24,32,32,cv2.BORDER_CONSTANT,value=255)
    return cv2.cvtColor(glyph,cv2.COLOR_GRAY2BGR)


def triad_result(s):
    if not s.find('^退出$',(1000,500,280,200)):return None
    if s.find('^胜利$|^挑战成功$|^获胜$'):return 'victory'
    if s.find('^失败$|^挑战失败$|^败退$'):return 'failed'
    # Shared PvP graphics sometimes hide the large result characters.
    outcome=pvp_result(s)
    if outcome:return outcome
    if (s.find('^三阵入局积分$',(680,220,320,100)) and
            all(s.find('^'+label+'$',(680,330,490,90)) for label in ('2v2','3v3','5v5'))):
        delta=re.search(r'[（(]\s*([+＋\-−])\s*\d+\s*[)）]',s.region_text((920,220,340,100)))
        if delta:return 'victory' if delta[1] in ('+','＋') else 'failed'
    return None


class TriadActivities:
    def read_triad_quota_number(self,s,roi):
        value=self.b.read_number(s,roi)
        if value is not None:return value
        # The isolated 7 is detected reliably while recognition-only can
        # return an empty string or "7_". Keep exact numeric OCR at >= .8.
        self.b.confirm_label(s,r'^\d{1,2}$',roi,threshold=.8)
        word=s.find(r'^\d{1,2}$',roi)
        if word:return int(word.text)
        image=triad_quota_digit_image(s,roi)
        if image is None:return None
        from maa.pipeline import JOCR
        result=self.b.wait(self.b.tasker.post_recognition('OCR',JOCR(
            roi=[0,0,image.shape[1],image.shape[0]],only_rec=True,threshold=.8),image),10).get()
        values=[]
        for node in result.nodes if result else []:
            if not node.recognition:continue
            for value in node.recognition.all_results:
                text=getattr(value,'text','').strip().replace('O','0').replace('o','0')
                if value.score>=.8 and re.fullmatch(r'\d{1,2}',text):values.append(int(text))
        return values[0] if len(values)==1 else None

    def await_triad_quota(self,s):
        reader=self.read_triad_quota_number if self.b.tasker is not None else None
        for attempt in range(4):
            self.b.guard(s)
            if not is_triad_lobby(s):raise TaskBlocked('核对三阵入局次数时已离开匹配大厅，保留现场')
            value=triad_quota(s,reader)
            if value is not None:return s,value
            if attempt==3:raise TaskBlocked('三阵入局免费次数局部补读并重读3次仍未确认，未继续匹配')
            self.navigation_retry('三阵入局免费次数暂未读清，重新识别',attempt+1,s)
            self.b.sleep(.5);s=self.observe()

    def triad_hub_entry(self,s):
        saw_partial=False
        for attempt in range(4):
            self.b.guard(s)
            if not is_event_hub(s):raise TaskBlocked('查找三阵入局时已离开丰野间，保留现场')
            entry=activity_entry(s,'triad')
            if not entry:
                hints=[w for w in s.words if w.text=='阵入局' and w.score>=.8 and
                       0<=w.center[0]<1280 and 145<=w.center[1]<685]
                saw_partial=saw_partial or bool(hints)
                if len(hints)==1:
                    hint=hints[0];x,y,w,h=hint.box
                    self.b.confirm_label(s,TITLE,(max(0,x-45),max(145,y-12),min(1280-max(0,x-45),w+80),h+28),threshold=.8)
                    entry=activity_entry(s,'triad')
                    if not entry:
                        # Three distinctive characters on an independently
                        # confirmed hub authorize only opening this free tab.
                        entry=hint
                        self.note('三阵入局入口漏读首字，已结合丰野间页面和“阵入局”确认；进入后仍核对完整标题与免费次数')
            if entry:return s,entry
            self.b.save_screen(s,self.report['folder']/f'triad-entry-check-{attempt+1}.png')
            if attempt==3:
                if saw_partial:raise TaskBlocked('三阵入局入口文字未完整确认，未将识别失败当作活动结束')
                self.report['triad_availability']={'status':'not_visible','reads':4}
                return s,None
            self.navigation_retry('三阵入局入口未读到，重新观察丰野间',attempt+1,s)
            self.b.sleep(.5);s=self.observe()

    def triad_lobby(self,screen=None):
        s=screen if screen is not None else self.observe();self.b.guard(s)
        if is_triad_lobby(s):return s
        s=self.event_hub(s)
        s,entry=self.triad_hub_entry(s)
        if entry is None:
            return None  # Confirmed hub, seasonal activity currently absent.
        availability=activity_availability(s,entry)
        self.report['triad_availability']={'status':availability,'entry':entry.text}
        if availability in ('ended','not_open'):return None
        def enter(q):
            if not is_event_hub(q):return
            entry=activity_entry(q,'triad')
            if not entry:
                hints=[w for w in q.words if w.text=='阵入局' and w.score>=.8 and 145<=w.center[1]<685]
                entry=hints[0] if len(hints)==1 else None
            if entry and activity_availability(q,entry)=='open':
                self.b.click_at(q,entry.center,[*event_hub_anchors(q),'^'+re.escape(entry.text)+'$'],'进入三阵入局')
        enter(s)
        return self.wait_for_screen(is_triad_lobby,'三阵入局匹配页面',timeout=4,retry_navigation=enter)

    def triad_match(self,before):
        s=self.triad_lobby(before)
        if s is None:raise TaskBlocked('三阵入局活动已结束或尚未开放')
        self.b.guard(s)
        s,quota=self.await_triad_quota(s)
        if quota<1:raise TaskBlocked('三阵入局免费匹配次数已用完，未点击匹配')
        if triad_is_open(s) is False:raise TaskBlocked('三阵入局当前不在客户端标明的开放时段，未点击匹配')
        button=s.find(MATCH,(150,430,1100,260))
        if button is None:raise TaskBlocked('三阵入局没有可确认的免费匹配按钮')
        if s.find(r'钻石|点券|付费|购买|¥|￥',(max(0,button.center[0]-230),max(0,button.center[1]-95),460,185)):
            raise TaskBlocked('匹配按钮附近出现付费信息，未点击')
        def match(q):
            if not is_triad_lobby(q):return
            reader=self.read_triad_quota_number if self.b.tasker is not None else None
            if triad_quota(q,reader)!=quota:raise TaskBlocked('匹配后免费次数已变化或未读清，未重复匹配')
            button=q.find(MATCH,(150,430,1100,260))
            if not button or q.find(r'钻石|点券|付费|购买|¥|￥',(max(0,button.center[0]-230),max(0,button.center[1]-95),460,185)):
                raise TaskBlocked('重试匹配前免费按钮未确认')
            if triad_is_open(q) is False:raise TaskBlocked('三阵入局开放时段已结束，未重复匹配')
            try:self.b.click_text(q,MATCH,roi=(150,430,1100,260))
            except PageChanged:
                self.note('匹配按钮已随页面变化，重新观察匹配状态，不追加输入')
        match(s)
        pending=self.wait_for_screen(lambda q:is_triad_matching(q) or is_triad_battle(q,known_match=True) or
            bool(q.has('即将进入战斗','^2v2$','^3v3$','^5v5$')),
            '三阵入局开始匹配',timeout=4,retry_navigation=match)
        until=time.monotonic()+max(300,int(self.b.settings.get('battle_timeout_seconds',240))*3)
        began=False;saw_battle=False;clicks=0
        feedback=time.monotonic();unknown_since=None;network_retries=0
        while time.monotonic()<until:
            s=pending if pending is not None else self.observe();pending=None;self.b.guard(s)
            if self.retry_battle_network(s,network_retries):
                network_retries+=1;continue
            outcome=triad_result(s)
            if outcome:
                if not saw_battle:raise TaskBlocked('三阵入局未确认实际战斗，结果不计数')
                self.b.save_screen(s,self.report['folder']/f'triad-result-{self.task_counts.get("triad",0)+1}.png')
                return s,outcome,clicks
            matching=is_triad_matching(s);fighting=is_triad_battle(s,known_match=True)
            if matching or fighting:
                began=True;unknown_since=None
            if fighting:saw_battle=True
            if is_triad_lobby(s):
                raise TaskBlocked('匹配后直接返回三阵入局页面，未见最终战斗结算，未计次')
            advance=s.find(r'^下一(?:阵|局|场|回合)$',(700,440,580,250))
            if advance and began:
                self.b.click_at(s,advance.center,['^'+re.escape(advance.text)+'$'],'进入三阵入局下一回合')
                unknown_since=None;continue
            if fighting:
                round_id=triad_round(s)
                settle=triad_settle_button(s,self.b.read_text_crop)
                if settle is not None and self.options['triad']['auto_settle']:
                    anchors=['^结算$']
                    if s.find(r'^\d{1,2}:\d{2}$',(450,0,380,110)):anchors.append(r'^\d{1,2}:\d{2}$')
                    elif s.find('^自动$|^手动$'):anchors.append('^自动$|^手动$')
                    self.b.click_at(s,settle.center,anchors,'三阵入局快速结算当前回合')
                    clicks+=1
                    label=f'第{round_id}回合' if round_id is not None else '当前回合'
                    self.note(f'三阵入局{label}：本场累计点击结算{clicks}次，继续核对按钮是否消失')
                    continue
            if not (matching or fighting or advance):
                unknown_since=unknown_since or time.monotonic()
                if time.monotonic()-unknown_since>30:
                    self.b.save_screen(s,self.report['folder']/'triad-unknown.png')
                    raise TaskBlocked('三阵入局匹配后页面连续30秒未识别，已保留现场')
            if time.monotonic()-feedback>=15:
                self.note('三阵入局正在匹配或战斗，等待最终结果…')
                feedback=time.monotonic()
            self.b.sleep(1)
        raise SafetyStop('三阵入局匹配或战斗未在时限内结算，保留现场')

    def triad(self):
        s=self.triad_lobby();matches=0;settlements=0
        if s is None:
            status=self.report.get('triad_availability',{}).get('status')
            reason={'ended':'活动已结束','not_open':'活动尚未开放',
                    'not_visible':'重新观察4次仍未识别到活动入口'}.get(status,'当前没有已确认的活动入口')
            return '三阵入局'+reason+'，已跳过'
        s,daily_limit=self.await_triad_quota(s)
        self.resource_balance('triad','免费匹配次数',daily_limit)
        self.report['triad_remaining']=daily_limit
        if triad_is_open(s) is False:
            self.home();return '三阵入局当前不在客户端标明的开放时段，已跳过'
        while matches<daily_limit:
            s=self.triad_lobby(s)
            if s is None:break
            s,before=self.await_triad_quota(s)
            self.resource_balance('triad','免费匹配次数',before)
            self.report['triad_remaining']=before
            if before==0 or s.find(NO_ATTEMPTS):break
            if s.find(MATCH,(150,430,1100,260)) is None:
                raise TaskBlocked('三阵入局剩余次数与匹配按钮未同时确认')
            self.check_budget('triad')
            result,outcome,clicks=self.triad_match(s)
            self.battles+=1;self.task_counts['triad']=self.task_counts.get('triad',0)+1
            s=self.triad_lobby(self.exit_result(result))
            if s is None:raise TaskBlocked('三阵入局结算后活动入口消失，剩余次数未核对')
            s,after=self.await_triad_quota(s)
            matches+=1;settlements+=clicks
            self.report['triad_remaining']=after
            verified=after==before-1
            self.resource_spent('triad','免费匹配次数',1 if verified else None,after)
            self.record_daily_fight('triad',None,outcome,settlements=clicks,remaining=after,
                                    quota_verified=verified)
            self.note(f'三阵入局已完成{matches}场，点击结算按钮{clicks}次；剩余免费次数'+(str(after) if after is not None else '未读清'))
            if after is None:raise TaskBlocked('三阵入局已结算，但剩余免费次数未读清，未继续匹配')
            if not verified:raise TaskBlocked(f'三阵入局已结算，但免费次数从{before}变为{after}，不是消耗1次')
        self.home()
        return f'三阵入局已完成{matches}场，点击结算{settlements}次；当日免费次数'+('已用完' if self.report.get('triad_remaining')==0 else '已检查')
