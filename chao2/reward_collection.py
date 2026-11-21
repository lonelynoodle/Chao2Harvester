"""Free contract and World Echo rewards, using the client's observed pages.

The contract's paid unlock and level purchase controls are outside all claim
regions. Story rewards use their fixed free chest, never the comment button.
"""
from __future__ import annotations

import re

from .configuration import selected_rows
from .backend import Word
from .other_tasks import notification_badges
from .policy import TaskBlocked


ECHO_NAMES = {'monument':'世界丰碑', 'lost':'遗落回响', 'torrent':'超星洪流', 'notes':'微光笔记'}
ECHO_HUB_REGIONS = {
    'monument':(840,140,235,195), 'lost':(0,175,205,200),
    'torrent':(135,360,255,230), 'notes':(1060,290,220,220),
}
# The leading 一 on the contract's bright arrow is often absent from OCR.
# Still require an exact claim label inside the verified free-claim region.
CLAIM = r'^(?:[一－—-]?键)?领[取奖](?:全部)?$|^领取奖励$'
COMMENT = r'^.{0,2}评论$'  # OCR may join the adjacent comment icon as 日/口.
CONTRACT_CLAIM_ROI = (0,165,215,455)
CONTRACT_TAB_ROI = (555,635,180,80)
TREASURE_HUD_ROI = (1180,270,100,86)
STORY_CHESTS = {'lost':(175,530,125,115), 'notes':(175,530,125,115), 'torrent':(65,570,135,115)}


def echo_header(s):
    return next((key for key,name in ECHO_NAMES.items() if s.find('^'+name+'$',(90,0,170,65))),None)


def is_echo_hub(s):
    return bool(s.find('^世界回响$',(90,0,170,65)) and
                sum(bool(s.find('^'+name+'$')) for name in ECHO_NAMES.values())>=3)


def echo_story_kind(s):
    kind=echo_header(s)
    if kind in ('lost','notes') and s.find(COMMENT,(190,350,105,80)) and s.find(r'^\d{3,4}$',(365,165,100,55)):
        return kind
    if (s.find(r'^第\d+章$',(60,15,170,65)) and s.find(COMMENT,(80,495,130,65)) and
            s.find(r'^\d+[.．、]',(60,125,225,370))):
        return 'torrent'
    return None


def is_map_story(s):
    """Incidental numbered lore over any task; explicit Echo pages keep rewards."""
    if echo_header(s) or not s.find(COMMENT,(190,350,105,80)):
        return False
    if not s.find(r'^\d{3,4}$',(365,165,100,55)):
        return False
    title=s.find(r'^.{2,16}$',(370,210,550,70))
    lines=[w for w in s.words if 365<=w.box[0]<=400 and 285<=w.center[1]<=590 and len(w.text)>=12]
    # Rift lore (e.g. 031) can contain just one line. The numbered title,
    # fixed comment control and body layout identify the card, not its length.
    return bool(title and lines)


def is_contract(s):
    return bool(contract_entry(s) and
                s.find('^契约等级$',(235,70,145,65)) and s.find('^任务$',(1180,340,100,150)))

def contract_entry(s):
    if s.find('^宝藏$',(90,0,170,65)):
        return s.find('^蜕变契约$',CONTRACT_TAB_ROI)


def contract_page(s):
    if not is_contract(s):return None
    if all(s.find('^'+tab+'$',(210,130,975,75)) for tab in ('每日任务','每周任务','挑战任务')):return 'tasks'
    if s.find('^原始契约$',(210,220,120,110)):return 'rewards'
    return None


def reward_overlay(s):
    return bool(s.find('^获得奖励$',(370,65,550,190)))


def task_claim_slot(s):
    if not s.has('^玩法概览$','^每日挑战$') or reward_overlay(s):return None
    for roi in ((0,65,250,90),(1030,210,240,450)):
        if s.find(CLAIM,roi):return roi
    return None


def daily_activity_chests(s):
    if not s.has('^玩法概览$','^每日挑战$','^本周活跃$') or reward_overlay(s):return []
    number=s.find(r'^\d{1,4}$',(280,130,130,60))
    if not number:return []
    result=[]
    for level,x in zip((100,200,300,400,500),(582,725,870,1014,1156)):
        if int(number.text)<level:continue
        # Only the available chest has a glowing gold centre. Locked and
        # already collected chests are dark; their gold outlines don't count.
        core=s.image[112:151,x-20:x+21].astype('int16')
        b,g,r=(core[:,:,i] for i in range(3))
        if ((r>210)&(g>170)&(b<150)&(r-b>75)).mean()>.04:result.append((level,(x,130)))
    return result


def story_chest_state(s,kind):
    """Text or the gold free chest, only inside an already identified story."""
    if echo_story_kind(s)!=kind:return None
    roi=STORY_CHESTS[kind]
    if s.find('已领[取奖]',roi):return 'claimed'
    if s.find(CLAIM,roi) or s.find('^可领取$',roi):return 'ready'
    # New story rewards use a blue chest. The fixed chest's orange ! is
    # visible even when the small 可领取 label is missed by full-frame OCR.
    if notification_badges(s,roi):return 'ready'
    x,y,w,h=roi;im=s.image[y:y+h,x:x+w].astype('int16')
    b,g,r=(im[:,:,i] for i in range(3))
    # The collected chest is dark blue/black. Gold artwork elsewhere in the
    # story must never qualify the chest or the comment control as claimable.
    if ((r>170)&(g>110)&(g<235)&(b<155)&(r-b>55)).mean()>.12:return 'ready'
    return None


def echo_list_signature(s,kind):
    if kind in ('lost','notes'):
        return tuple(sorted((w.text,w.center[0]//250,w.center[1]//30) for w in s.words
                            if re.fullmatch(r'\d{3}',w.text) and 195<=w.center[1]<700))
    if kind=='torrent':
        return tuple(sorted((w.text,w.center[1]//30) for w in s.words
                            if re.fullmatch(r'第\d+章',w.text) and 190<=w.center[1]<700))
    return tuple((w.text,w.center[1]//30) for w in s.words if 180<=w.center[1]<685 and w.center[0]>120)


class RewardCollection:
    def calibrate_collection_reward(self,s):
        if reward_overlay(s):return s
        # A transparent reward title can be joined to the activity title
        # behind it. Verify the foreground text in its own crop first.
        if (s.find('^获得奖励.+$',(370,65,550,190)) and
            s.find('^点击空[白由]位置关闭.*$',(490,570,500,95)) and
            self.b.read_text_crop(s,(510,115,260,75))=='获得奖励'):
            s.words.append(Word('获得奖励',[510,115,260,75],1.0))
        return s

    def collect_daily_activity(self,s):
        for _ in range(5):
            choices=daily_activity_chests(s)
            if not choices:return s
            level,point=choices[0]
            fresh=self.observe();self.b.guard(fresh)
            if (level,point) not in daily_activity_chests(fresh):
                s=fresh;continue
            self.b.click_at(fresh,point,['^本周活跃$','^每日挑战$'],'领取已亮起的免费活跃宝箱')
            receipts=0
            for _ in range(6):
                after,count=self.dismiss_collection_reward(self.observe());receipts+=count
                if (after.has('^本周活跃$','^每日挑战$') and receipts and
                        (level,point) not in daily_activity_chests(after)):
                    self.report.setdefault('daily_activity_claimed',[]).append(level)
                    self.b.save_screen(after,self.report['folder']/f'daily-activity-{level}-claimed.png')
                    self.note(f'已确认领取{level}活跃宝箱');self.checkpoint();s=after;break
                self.b.sleep(.5)
            else:raise TaskBlocked(f'{level}活跃宝箱领取结果未确认，未重复点击')
        return s

    def open_echo_category(self,hub,kind):
        name=ECHO_NAMES[kind]
        if not is_echo_hub(hub):raise TaskBlocked('世界回响入口页未确认')
        self.b.click_text(hub,'^'+name+'$')
        def retry(q):
            # Entry animation may swallow a navigation click. Retry only on
            # the same verified hub, never replay a reward collection.
            if is_echo_hub(q):self.b.click_text(q,'^'+name+'$')
        return self.wait_for_screen(lambda q:echo_header(q)==kind and not echo_story_kind(q),
                                    name+'列表',timeout=3,retry_navigation=retry)

    def close_map_story(self,s):
        from .story_cards import close_story_card
        return close_story_card(self.b,s,self.report,self.note,
            source_task=self.active_task,source_id=getattr(self,'active_task_id',None),
            checkpoint=self.checkpoint)

    def record_echo_claim(self,kind):
        result=self.report.setdefault('world_echoes',{}).setdefault(kind,{'claimed':0})
        result['claimed']+=1
        self.note(ECHO_NAMES[kind]+f'：已确认领取{result["claimed"]}项')
        self.checkpoint()

    def dismiss_collection_reward(self,s):
        receipts=0
        for _ in range(4):
            self.b.guard(s)
            if reward_overlay(s):
                self.b.click_at(s,(640,660),['^获得奖励$'],'关闭免费领奖结果')
                receipts+=1;s=self.observe();continue
            # Level-up confirmations are accepted only with the client's
            # explicit instruction to dismiss by tapping blank space.
            if s.find('回响.*等级|等级.*提升') and s.find('点击空白.*关闭'):
                self.b.click_at(s,(640,660),['回响.*等级|等级.*提升','点击空白.*关闭'],'关闭回响升级提示')
                s=self.observe();continue
            return s,receipts
        raise TaskBlocked('领奖提示尚未关闭，保留现场，不重复领取')

    def claim_collection_text(self,s,roi,page):
        """One request; verify receipt or disappearance before counting it."""
        button=s.find(CLAIM,roi)
        if button is None:raise TaskBlocked('免费领取按钮未确认')
        # The leading 一 may blink out between two OCR frames of the same
        # bright button. Recheck the equivalent claim label in the same slot.
        slot=(button.center[0]-60,button.center[1]-35,120,70)
        self.b.click_text(s,CLAIM,roi=slot)
        for _ in range(4):
            after,receipts=self.dismiss_collection_reward(self.observe())
            if page(after) and (receipts or not after.find(CLAIM,
                    (button.center[0]-45,button.center[1]-30,90,60))):
                return after
            self.b.sleep(.6)
        raise TaskBlocked('领取后的结果未确认，未重复点击同一奖励')

    def contract_menu(self):
        from .workflows import is_world

        def resource_details(q):
            return q.has('^主要获得途径$','^已拥有')

        s=self.observe()
        if not contract_entry(s):s=self.home(s)
        for attempt in range(4):
            if contract_entry(s):break
            if attempt:self.navigation_retry('已返回世界，重试宝藏入口',attempt,s)
            entry=s.find('^宝藏$',TREASURE_HUD_ROI)
            self.click_world(s,entry.center if entry else (1231,305),'打开宝藏中的蜕变契约')
            s=self.wait_for_screen(lambda q:contract_entry(q) or resource_details(q) or is_world(q),
                                   '宝藏入口响应',timeout=3)
            if resource_details(s):
                self.note('宝藏入口当前显示资源说明，关闭弹窗后重试')
                s=self.home(s)
        if not contract_entry(s):raise TaskBlocked('宝藏入口补点3次后仍未打开')
        if is_contract(s):return s
        def select_contract(q):
            if contract_entry(q) and not is_contract(q) and not resource_details(q):
                self.b.click_text(q,'^蜕变契约$',roi=CONTRACT_TAB_ROI)
        select_contract(s)
        # The treasure frame and footer appear before the contract content.
        # Wait for its own controls; a loading frame is not a failed entry.
        return self.wait_for_screen(is_contract,'蜕变契约加载',timeout=4,retry_navigation=select_contract)

    def collect_contract(self):
        result={'status':'running','task_batches':0,'reward_batches':0,'task_tabs':{}}
        self.report.setdefault('other_tasks',{})['contract']=result
        s=self.contract_menu()
        self.b.click_text(s,'^任务$',roi=(1180,340,100,150))
        s=self.wait_for_screen(lambda q:contract_page(q)=='tasks','蜕变契约任务页',timeout=4)
        for tab in ('每日任务','每周任务','挑战任务'):
            if contract_page(s)!='tasks':raise TaskBlocked('蜕变契约任务页未确认')
            self.b.click_text(s,'^'+tab+'$',roi=(210,130,975,75))
            s=self.wait_for_screen(lambda q:contract_page(q)=='tasks','蜕变契约'+tab,timeout=4)
            count=0
            while s.find(CLAIM,CONTRACT_CLAIM_ROI):
                if count>=10:raise TaskBlocked('契约任务领取按钮持续出现，保留现场')
                s=self.claim_collection_text(s,CONTRACT_CLAIM_ROI,lambda q:contract_page(q)=='tasks')
                count+=1;result['task_batches']+=1;self.checkpoint()
            result['task_tabs'][tab]=count
        self.note(f'蜕变契约：任务经验已领{result["task_batches"]}批，检查等级奖励')
        self.b.click_text(s,'^奖励$',roi=(1180,205,100,125))
        s=self.wait_for_screen(lambda q:contract_page(q)=='rewards','蜕变契约奖励页',timeout=4)
        while s.find(CLAIM,CONTRACT_CLAIM_ROI):
            if result['reward_batches']>=10:raise TaskBlocked('契约奖励领取按钮持续出现，保留现场')
            s=self.claim_collection_text(s,CONTRACT_CLAIM_ROI,lambda q:contract_page(q)=='rewards')
            result['reward_batches']+=1;self.checkpoint()
        if (notification_badges(s,(1180,205,100,285)) or
                notification_badges(s,(635,580,75,60))):
            self.b.save_screen(s,self.report['folder']/'contract-unclaimed.png')
            raise TaskBlocked('蜕变契约仍有待领取提示，未将漏识别的奖励记为全部完成')
        result.update(status='done',message=f'蜕变契约：任务经验{result["task_batches"]}批、奖励{result["reward_batches"]}批'+
                      ('；当前没有可领取项' if not result['task_batches'] and not result['reward_batches'] else ''))
        return result

    def echo_hub(self,s=None):
        s=s if s is not None else self.observe()
        if is_echo_hub(s):return s
        if echo_story_kind(s):s=self.close_echo_story(s)
        if echo_header(s):
            self.b.click_at(s,(43,28),['^'+ECHO_NAMES[echo_header(s)]+'$'],'返回世界回响')
            s=self.observe()
            if is_echo_hub(s):return s
        s=self.home(s);self.click_world(s,(1232,150),'打开世界回响')
        s=self.await_page('^世界回响$','^微光笔记$')
        if not is_echo_hub(s):raise TaskBlocked('世界回响四项入口未确认')
        return s

    def close_echo_story(self,s):
        kind=echo_story_kind(s)
        if kind is None:raise TaskBlocked('世界回响故事弹窗未确认')
        if kind=='torrent':
            self.b.click_at(s,(1230,38),[r'^第\d+章$',COMMENT],'关闭超星洪流故事')
        else:
            self.b.click_at(s,(1210,650),['^'+ECHO_NAMES[kind]+'$',COMMENT],'关闭回响故事弹窗')
        return self.wait_for_screen(lambda q:echo_header(q)==kind and not echo_story_kind(q),
                                    '回响故事关闭后返回原列表',timeout=3)

    def echo_scroll(self,s,kind,*,chapter=False):
        self.b.guard(s)
        if (echo_story_kind(s) if chapter else echo_header(s))!=kind:raise TaskBlocked('回响翻页前页面不符')
        # A long flick moves a whole chapter card past the fixed header: its
        # top-right ! is below the viewport before, then hidden above it.
        # Keep overlap for both chapter cards and the shorter story rows.
        points=(205,440,205,300) if chapter else ((740,550,740,370) if kind=='torrent' else (740,610,740,235))
        duration=1000 if kind=='torrent' else 650
        if not self.b.wait(self.b.controller.post_swipe(*points,duration)).succeeded:raise TaskBlocked('回响列表翻页失败')
        self.b.sleep(.8)
        return self.observe()

    def collect_story_chest(self,s,kind):
        state=story_chest_state(s,kind)
        if state is None:
            text=self.b.read_text_region(s,STORY_CHESTS[kind],scale=3)
            if re.search('已领[取奖]',text):state='claimed'
            elif re.search('可领取',text):state='ready'
        if state=='claimed':return s,0
        if state!='ready':raise TaskBlocked(ECHO_NAMES[kind]+'的宝箱状态未读清，未盲点')
        x,y,w,h=STORY_CHESTS[kind]
        anchors=[COMMENT,r'^第\d+章$'] if kind=='torrent' else [COMMENT,'^'+ECHO_NAMES[kind]+'$']
        self.b.click_at(s,(x+w//2,y+h//2-15),anchors,'领取'+ECHO_NAMES[kind]+'免费故事宝箱')
        for _ in range(4):
            after,receipts=self.dismiss_collection_reward(self.observe())
            if echo_story_kind(after)==kind:
                state=story_chest_state(after,kind)
                text='' if state=='claimed' else self.b.read_text_region(after,STORY_CHESTS[kind],scale=3)
                if state=='claimed' or re.search('已领[取奖]',text):
                    self.record_echo_claim(kind);return after,1
            self.b.sleep(.6)
        raise TaskBlocked('故事宝箱领取状态未确认，未再次点击')

    def collect_torrent_chapter(self,s):
        count=0;seen=set();last_signature=None
        # An unlocked chapter can contain both collected and newly unlocked
        # stories. The left story list scrolls independently of the text.
        s,n=self.collect_story_chest(s,'torrent');count+=n
        for _ in range(35):
            if echo_story_kind(s)!='torrent':raise TaskBlocked('超星洪流章节页未确认')
            badges=notification_badges(s,(10,120,310,380))
            if badges:
                point=badges[0]
                row=next((w.text for w in s.words if re.match(r'^\d+[.．、]',w.text) and
                          w.center[0]<290 and abs(w.center[1]-point[1])<30),str(point))
                if row in seen:raise TaskBlocked('超星洪流故事提示未清除：'+row)
                seen.add(row)
                self.b.click_at(s,(220,point[1]),[r'^第\d+章$',COMMENT],'打开有奖励提示的洪流故事')
                s,n=self.collect_story_chest(self.observe(),'torrent');count+=n
                continue
            signature=tuple(w.text for w in s.words if re.match(r'^\d+[.．、]',w.text) and w.center[0]<290 and 125<w.center[1]<500)
            if not signature:raise TaskBlocked('超星洪流故事目录未读清')
            if signature==last_signature:return self.close_echo_story(s),count
            last_signature=signature;s=self.echo_scroll(s,'torrent',chapter=True)
        raise TaskBlocked('超星洪流目录未确认到底，保留现场')

    def collect_echo_category(self,kind,*,force_scan=False):
        name=ECHO_NAMES[kind];hub=self.echo_hub()
        marked=force_scan or bool(notification_badges(hub,ECHO_HUB_REGIONS[kind]))
        s=self.open_echo_category(hub,kind)
        claimed=self.report.get('world_echoes',{}).get(kind,{}).get('claimed',0)
        result={'status':'running','claimed':claimed,'marked_on_entry':marked,'pages':0}
        self.report.setdefault('world_echoes',{})[kind]=result
        signatures=set();handled=set();reason='当前没有可领取提示';checked_claims=claimed
        for _ in range(180):
            self.b.guard(s)
            if echo_header(s)!=kind or echo_story_kind(s):raise TaskBlocked(name+'列表在领取时改变')
            if kind=='monument':
                button=s.find(CLAIM,(1010,180,270,505))
                if button:
                    s=self.claim_collection_text(s,(1010,button.center[1]-30,270,60),lambda q:echo_header(q)==kind)
                    self.record_echo_claim(kind);continue
                targets=[]
            else:targets=notification_badges(s,(0,185,1280,510))
            if targets:
                point=targets[0];signature=echo_list_signature(s,kind)
                token=(signature,point)
                if token in handled:raise TaskBlocked(name+'的已处理奖励提示仍在，未重复打开')
                handled.add(token)
                self.b.click_at(s,point,['^'+name+'$'],'打开'+name+'有奖励提示的条目')
                detail=self.observe()
                if echo_story_kind(detail)!=kind:raise TaskBlocked(name+'带提示条目的故事页未确认')
                if kind=='torrent':s,n=self.collect_torrent_chapter(detail)
                else:
                    detail,n=self.collect_story_chest(detail,kind);s=self.close_echo_story(detail)
                marked=True;self.checkpoint();continue
            if result['claimed']>checked_claims:
                # New/unclaimed stories are promoted to the first page. After
                # clearing its badges, check the hub before scanning the old
                # catalogue. A clean hub is the completion proof.
                checked_claims=result['claimed'];hub=self.echo_hub(s)
                if not notification_badges(hub,ECHO_HUB_REGIONS[kind]):
                    s=hub;reason='已核对入口，待领取提示已清除';break
                s=self.open_echo_category(hub,kind)
                signatures.clear();continue
            # Ordinary daily runs don't traverse hundreds of already-collected
            # stories. A hub notification activates a full downward search.
            if not marked:break
            signature=echo_list_signature(s,kind)
            if not signature:raise TaskBlocked(name+'列表内容未读清')
            if signature in signatures:
                reason='已检查到底，当前页无待领取项';break
            signatures.add(signature);result['pages']+=1
            if result['pages']%8==0:self.note(name+f'：已检查{result["pages"]}页，继续查找领取提示')
            s=self.echo_scroll(s,kind)
        else:raise TaskBlocked(name+'领取检查超出范围，未记为全部完成')
        if not is_echo_hub(s):
            self.b.save_screen(s,self.report['folder']/('echo-'+kind+'-last-list.png'))
        hub=s if is_echo_hub(s) else self.echo_hub(s)
        if notification_badges(hub,ECHO_HUB_REGIONS[kind]):
            if not marked:
                # The entrance ! pulses and can be absent from the first
                # frame. A later positive check warrants an actual scan, not
                # a failure after the fast "nothing to claim" path.
                self.note(name+'入口出现待领取提示，重新进入并检查完整列表')
                return self.collect_echo_category(kind,force_scan=True)
            raise TaskBlocked(name+f'已领{result["claimed"]}项，但入口仍有提示，需核对未识别奖励')
        result.update(status='done',message=name+f'：领取{result["claimed"]}项；'+reason)
        return result

    def collect_world_echoes(self):
        rows=selected_rows(self.options['rewards'],'world_echoes')
        if not rows:return ''
        results=self.report.setdefault('world_echoes',{});failures=[]
        for row in rows:
            key=row['id'];self.note('检查世界回响：'+ECHO_NAMES[key])
            try:result=self.collect_echo_category(key)
            except TaskBlocked as error:
                result={**results.get(key,{}),'status':'blocked','message':str(error)};failures.append(ECHO_NAMES[key])
                if hasattr(self,'last_screen'):self.b.save_screen(self.last_screen,self.report['folder']/('echo-'+key+'-blocked.png'))
            results[key]=result;self.note(result['message']);self.checkpoint()
            self.echo_hub()
        self.home()
        if failures:raise TaskBlocked('世界回响部分未完成：'+'、'.join(failures))
        return '；'.join(results[row['id']]['message'] for row in rows)
