"""Verified activity navigation, free rewards and the optional wooden hammer."""
import re

import numpy as np

from .policy import TaskBlocked


ACTIVITY_TABS = ('每日一发', '每日三发', '位面领主', '屯屯扑满')
SIDEBAR = (0, 75, 170, 605)
ACTIVITY_TITLE = (500, 85, 420, 145)
DAILY_CLAIM = (950, 565, 250, 90)
PLANE_TABS = (310, 600, 915, 65)


def is_activity(s):
    return bool(s.find('^活动$', (95, 0, 150, 65)) and
                any(s.find(activity_label(name), SIDEBAR) for name in ACTIVITY_TABS))


def activity_label(name):
    if name=='屯屯扑满':
        from .piggy_bank import PIGGY_NAME
        return PIGGY_NAME
    return '^'+re.escape(name)+'$'


def activity_page(s, name):
    if name=='屯屯扑满':
        from .piggy_bank import is_piggy_page
        return is_piggy_page(s)
    return is_activity(s) and bool(s.find('^'+re.escape(name)+'$', ACTIVITY_TITLE))


def daily_claim_state(s):
    if not activity_page(s, '每日一发'):return None
    if len([w for w in s.words if re.fullmatch(r'第\d+天', w.text) and
            230 < w.center[0] < 1225 and 250 < w.center[1] < 550]) < 6:return None
    word = s.find('^领取奖励$', DAILY_CLAIM)
    if word is None:return None
    x,y,w,h = word.box
    # The disabled label is grey on a dim yellow button; the enabled text is
    # white. Restrict this check to the text, not the bright button border.
    light = float((np.min(s.image[y:y+h,x:x+w], axis=2) > 175).mean())
    if light > .10:return 'ready'
    if light < .015:return 'empty'
    return None


def is_plane(s):
    return (activity_page(s, '位面领主') and
            bool(s.find('^原始$', (215, 320, 100, 65))) and
            bool(s.find('^探索度$', (215, 380, 100, 45))) and
            bool(s.find('^超阶$', (215, 525, 100, 50))))


def percentage(text):
    m = re.fullmatch(r'(\d{1,3})[%％]', re.sub(r'\s', '', text))
    return int(m[1]) if m and 0 <= int(m[1]) <= 100 else None


def plane_regions(s):
    if not is_plane(s):return []
    rows=[]
    for w in s.words:
        x,y=w.center
        if not (310<x<1225 and 610<y<650 and w.score>=.85 and re.fullmatch(r'.{2,6}之地',w.text)):continue
        # A selected region has a solid pale-gold background behind its label.
        im=s.image[y-15:y+16,x-60:x+61].astype('int16');b,g,r=(im[:,:,i] for i in range(3))
        selected=((r>180)&(g>150)&(b<195)&(r-b>35)).mean()>.30
        rows.append({'name':w.text,'point':w.center,'selected':bool(selected)})
    return sorted(rows,key=lambda row:row['point'][0])


def plane_reward_state(s, x):
    # Only the upper 原始 track. The paid track begins below y=450.
    if not is_plane(s) or not 360<=x<=1230:return None
    if s.find('^已领(?:取)?$', (x-47, 285, 94, 58)):return 'claimed'
    im=s.image[290:334,x-27:x+28].astype('int16');b,g,r=(im[:,:,i] for i in range(3))
    # A bright cyan diamond; claimed cards are dark and have a green label.
    if ((b>175)&(g>140)&(b-r>25)&(g-r>20)).mean()>.18:return 'diamond'
    return None


class ActivityRewards:
    def activity_tab(self, name):
        if name not in ACTIVITY_TABS:raise ValueError('未注册活动')
        s=self.observe();self.b.guard(s)
        if activity_page(s,name):return s
        if not is_activity(s):
            s=self.open_world_page((1232,215),'进入活动','^活动$','^每日一发$|^每日三发$|^位面领主$')
        # Read the sidebar only: the same title also appears in the content.
        for _ in range(9):
            if not is_activity(s):raise TaskBlocked('活动入口尚未打开')
            if s.find(activity_label(name),SIDEBAR):break
            self.b.audit({'action':'swipe','reason':'查找活动标签：'+name,'status':'requested'})
            if not self.b.wait(self.b.controller.post_swipe(80,570,80,350,1000)).succeeded:
                raise TaskBlocked('活动标签翻页失败')
            self.b.sleep(.8);s=self.observe()
        else:raise TaskBlocked('活动标签未找到：'+name)
        self.b.click_text(s,activity_label(name),roi=SIDEBAR)
        def retry(q):
            if is_activity(q) and not activity_page(q,name) and q.find(activity_label(name),SIDEBAR):
                self.b.click_text(q,activity_label(name),roi=SIDEBAR)
        return self.wait_for_screen(lambda q:activity_page(q,name),'打开'+name,
                                    timeout=6,retry_navigation=retry)

    def collect_daily_single(self):
        previous=self.report.get('other_tasks',{}).get('daily_single',{})
        if previous.get('status')=='confirming':raise TaskBlocked('每日一发上次领取结果未确认，不重复领取')
        s=self.activity_tab('每日一发')
        s=self.wait_for_screen(lambda q:daily_claim_state(q) is not None,'核对每日一发免费奖励',timeout=4)
        result={'status':'done','claimed':0,'message':'每日一发：当前没有可领取奖励'}
        self.report.setdefault('other_tasks',{})['daily_single']=result
        if daily_claim_state(s)=='empty':return result
        # One request only. A retry must never repeat an unconfirmed claim.
        result.update(status='confirming',message='每日一发：正在核对领取结果');self.checkpoint()
        self.b.click_text(s,'^领取奖励$',roi=DAILY_CLAIM)
        receipts=0
        for _ in range(8):
            s,count=self.dismiss_collection_reward(self.observe());receipts+=count
            if daily_claim_state(s)=='empty' and receipts:
                result.update(status='done',claimed=1,message='每日一发：已领取免费登录奖励')
                self.b.save_screen(s,self.report['folder']/'daily-single-claimed.png');self.checkpoint()
                return result
            self.b.sleep(.5)
        raise TaskBlocked('每日一发领取结果未确认，未重复领取')

    def plane_marks(self,s):
        if not is_plane(s):raise TaskBlocked('位面领主原始奖励页面未确认')
        progress=percentage(s.region_text((220,415,100,35)))
        if progress is None:progress=percentage(self.b.read_text_crop(s,(231,415,75,34)))
        if progress is None:raise TaskBlocked('位面领主探索度未读清')
        marks=[]
        for w in s.words:
            if not (360<=w.center[0]<=1230 and 395<=w.center[1]<445):continue
            value=percentage(w.text)
            if value is None and re.fullmatch(r'\d{2,4}',w.text):
                x,y,width,height=w.box
                value=percentage(self.b.read_text_crop(s,(x-2,y-2,width+4,height+4)))
                # The track's fixed right edge clips the % in 100%, even at
                # its scroll limit. Independently read the three digits and
                # require the preceding 95% tick at the normal spacing.
                if value is None and w.text=='1009' and w.center[0]>1190:
                    previous=s.find('^95[%％]$',(w.center[0]-195,395,60,50))
                    digits=self.b.read_number(s,(x-2,y-2,round(width*3/4)+3,height+4))
                    if previous and digits==100:value=100
            if value is not None and value>0 and value%5==0:
                marks.append((value,w.center[0]))
        if not marks:raise TaskBlocked('位面领主奖励刻度未读清')
        marks=sorted(set(marks))
        if any(b[0]-a[0]!=5 for a,b in zip(marks,marks[1:])):
            raise TaskBlocked('位面领主奖励刻度存在漏识别，未跳过奖励')
        return progress,marks

    def plane_scroll(self,s,*,left=False,tabs=False):
        if not is_plane(s):raise TaskBlocked('位面领主翻页前页面改变')
        y=630 if tabs else 415
        a,z=(600,900) if left else (1050,750)
        for attempt in range(3):
            self.b.guard(s)
            if not is_plane(s):raise TaskBlocked('位面领主翻页重试前页面改变')
            self.b.audit({'action':'swipe','reason':'位面领主'+('地区' if tabs else '奖励')+'翻页',
                          'from':[a,y],'to':[z,y],'attempt':attempt+1,'status':'requested'})
            if self.b.wait(self.b.controller.post_swipe(a,y,z,y,1200)).succeeded:break
            if attempt==2:raise TaskBlocked('位面领主翻页失败，已核对并重试3次')
            self.note('位面领主翻页未完成，重新核对页面后重试')
            s=self.observe()
        self.b.sleep(.8)
        return self.wait_for_screen(is_plane,'等待位面领主翻页',timeout=4)

    def plane_select_region(self,s,row):
        if row['selected']:return s
        for attempt in range(2):
            fresh=self.observe();self.b.guard(fresh)
            target=next((r for r in plane_regions(fresh) if r['name']==row['name']),None)
            if not target:raise TaskBlocked('位面领主地区列表发生变化')
            if target['selected']:return fresh
            self.b.click_text(fresh,'^'+re.escape(target['name'])+'$',roi=PLANE_TABS)
            for _ in range(3):
                fresh=self.observe();self.b.guard(fresh)
                if not is_plane(fresh):raise TaskBlocked('切换位面领主地区后页面未确认')
                if any(r['name']==row['name'] and r['selected'] for r in plane_regions(fresh)):return fresh
                if fresh.find('位面未解锁'):return None
                self.b.sleep(.4)
        return None  # Toast can expire before OCR; do not claim in the old region.

    def plane_claim_region(self,s,region,result):
        # Begin at the first milestone, including rewards missed on earlier runs.
        for _ in range(20):
            _,marks=self.plane_marks(s)
            if marks[0][0]==5:break
            after=self.plane_scroll(s,left=True);_,new=self.plane_marks(after)
            if new[0][0]>=marks[0][0]:
                raise TaskBlocked('位面领主奖励未滑到起点，保留现场')
            s=after
        else:raise TaskBlocked('位面领主奖励起点未确认')
        seen=set()
        for _ in range(24):
            progress,marks=self.plane_marks(s)
            for value,x in marks:
                if value>progress:continue
                state=plane_reward_state(s,x)
                if state=='claimed':continue
                if state!='diamond':raise TaskBlocked('位面领主免费钻石状态未确认')
                identity=(region,value)
                if identity in seen:raise TaskBlocked('位面领主同一奖励仍未确认，未重复点击')
                fresh=self.observe();self.b.guard(fresh)
                p,now=self.plane_marks(fresh)
                if not any(r['name']==region and r['selected'] for r in plane_regions(fresh)):
                    raise TaskBlocked('领取前位面领主地区改变')
                target=next((cx for n,cx in now if n==value),None)
                if target is None or p<value:raise TaskBlocked('领取前位面领主探索度或刻度改变')
                if plane_reward_state(fresh,target)=='claimed':s=fresh;continue
                if plane_reward_state(fresh,target)!='diamond':raise TaskBlocked('位面领主免费钻石图标未确认')
                seen.add(identity)
                receipt={'region':region,'milestone':value,'status':'confirming'}
                result['receipts'].append(receipt);self.checkpoint()
                self.b.click_at(fresh,(target,312),['^位面领主$','^原始$','^探索度$'],'领取原始位面免费钻石')
                receipts=0
                for _ in range(8):
                    s,count=self.dismiss_collection_reward(self.observe());receipts+=count
                    if is_plane(s):
                        _,after=self.plane_marks(s)
                        current=next((cx for n,cx in after if n==value),None)
                        if current is not None and plane_reward_state(s,current)=='claimed' and receipts:
                            receipt['status']='confirmed';result['claimed']+=1;self.checkpoint();break
                    self.b.sleep(.4)
                else:raise TaskBlocked('位面领主钻石领取结果未确认，未重复领取')
            progress,marks=self.plane_marks(s)
            if marks[-1][0]>=progress:return s
            old=marks;s=self.plane_scroll(s);_,marks=self.plane_marks(s)
            if marks[-1][0]<=old[-1][0]:raise TaskBlocked('位面领主奖励翻页未推进')
        raise TaskBlocked('位面领主奖励列表未确认结束')

    def collect_plane_lord(self):
        previous=self.report.get('other_tasks',{}).get('plane_lord',{})
        if any(r.get('status')=='confirming' for r in previous.get('receipts',[])):
            raise TaskBlocked('位面领主上次领取结果未确认，不重复领取')
        s=self.activity_tab('位面领主')
        s=self.wait_for_screen(is_plane,'核对位面领主奖励',timeout=4)
        result={'status':'running','claimed':0,'regions':{},'receipts':[]}
        self.report.setdefault('other_tasks',{})['plane_lord']=result
        # Reset the region strip only if earlier entries are off screen.
        for _ in range(8):
            rows=plane_regions(s)
            if not rows:raise TaskBlocked('位面领主地区未读清')
            if rows[0]['name']=='源初之地':break
            after=self.plane_scroll(s,left=True,tabs=True)
            if [r['name'] for r in plane_regions(after)]==[r['name'] for r in rows]:break
            s=after
        for _ in range(12):
            rows=plane_regions(s)
            if not rows:raise TaskBlocked('位面领主地区列表未读清')
            for row in rows:
                if row['name'] in result['regions']:continue
                selected=self.plane_select_region(s,row)
                if selected is None:
                    result['regions'][row['name']]='未解锁或无法切换';s=self.observe();continue
                self.note('位面领主：检查'+row['name']+'的免费钻石')
                s=self.plane_claim_region(selected,row['name'],result)
                result['regions'][row['name']]='已检查';self.checkpoint()
            after=self.plane_scroll(s,tabs=True)
            fresh=plane_regions(after)
            if fresh and all(r['name'] in result['regions'] for r in fresh):break
            s=after
        else:raise TaskBlocked('位面领主地区检查未确认结束')
        result.update(status='done',message=f'位面领主：已领取{result["claimed"]}项免费钻石奖励；'+
                      '、'.join(name+' '+state for name,state in result['regions'].items()))
        return result
