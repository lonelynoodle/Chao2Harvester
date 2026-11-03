"""Friend maintenance and acknowledgement of new inventory items.

Only the friend/recommendation controls and the inventory's left item grid are
input targets. Chat text is never interpreted as instructions or clicked.
"""
import math
import re

import numpy as np
from PIL import Image

from .policy import TaskBlocked,parse_ratio


FRIEND_EXCHANGE=r'^[一－—-]?键(?:赠送|收取|领取)(?:并收取)?$'
OFFLINE=r'^(?:离线)?(?:\d+\s*(?:天|小时|分钟)(?:前)?|在线|刚刚)$'


def is_friend_list(s):
    return bool(s.find('^好友$',(95,0,150,65)) and s.find('^好友数量$',(130,70,150,65)))


def is_social(s):
    return bool(s.find('^社交$',(95,0,150,65)) and
                s.find('^推荐添加$',(130,70,170,65)) and s.find('^申请列表$',(710,70,180,65)))


def friend_delete_confirmation(s):
    prompt=s.region_text((250,200,800,260))
    return bool(s.find('^取消$',(350,380,290,190)) and s.find('^确定$',(640,380,380,190)) and
                re.search(r'(?:删除|移除).{0,30}好友|好友.{0,30}(?:删除|移除)',prompt))

def is_friend_profile(s):
    return bool(s.find('^助战怪兽$',(230,470,180,75)) and
                s.find('^删除好友$|^添加好友$',(490,520,190,70)))


def is_bag(s):
    return bool(s.find('^背包$',(95,0,150,65)) and
                s.find('^全部$',(0,170,110,70)) and s.find('^元核$',(0,390,110,75)))


def friend_count(s):
    if not is_friend_list(s):return None
    value=parse_ratio(s.region_text((245,75,125,55)))
    return value if value and 0<=value[0]<=value[1]<=1000 else None


def inactive_days(text):
    text=re.sub(r'\s','',text)
    if text in ('在线','刚刚'):return 0
    m=re.fullmatch(r'(?:离线)?(\d+)(天|小时|分钟)(?:前)?',text)
    if not m:return None
    return int(m[1])/{'天':1,'小时':24,'分钟':1440}[m[2]]


def friend_rows(s):
    """Time and name must share a complete row below the sticky NPC card."""
    if not is_friend_list(s):return []
    rows=[]
    for w in s.words:
        if not (390<=w.center[0]<490 and 255<=w.center[1]<600 and w.score>=.90):continue
        if not re.fullmatch(OFFLINE,w.text):continue
        y=w.center[1]
        names=[n for n in s.words if 215<=n.center[0]<398 and y-52<=n.center[1]<y-15
               and n.box[1]>=232 and n.score>=.90]
        if len(names)!=1:continue
        rows.append({'name':names[0].text,'time':w.text,'days':inactive_days(w.text),
                     'point':(180,y-18),'y':y})
    return sorted(rows,key=lambda row:row['y'])


def friend_list_signature(s):
    return tuple((w.text,round(w.center[1]/8)) for w in s.words
                 if 215<=w.center[0]<395 and 232<=w.center[1]<600 and w.score>=.85)


def friend_name_rows(s):
    """Find complete names independently of the low-contrast last-online text."""
    if not is_friend_list(s):return []
    rows=[]
    for w in s.words:
        # Names start at x=220, combat power at x=254. Exclude clipped rows
        # and the sticky NPC card before considering any destructive action.
        if not (210<=w.box[0]<=245 and w.box[1]>=237 and w.center[1]<=568 and w.score>=.88):continue
        if len(w.text)<2 or re.fullmatch(r'[\d\W]+',w.text) or w.text.startswith('等级'):continue
        y=w.center[1]+35
        rows.append({'name':w.text,'y':y,'point':(180,y-18),'time_roi':(392,y-16,90,32)})
    return sorted(rows,key=lambda row:row['y'])


def same_friend_positions(a,b):
    left,right=friend_name_rows(a),friend_name_rows(b)
    if not left and not right and friend_count(a) and friend_count(b):
        return friend_count(a)[0]==friend_count(b)[0]==0
    return bool(left and len(left)==len(right) and all(
        x['name']==y['name'] and abs(x['y']-y['y'])<=3 for x,y in zip(left,right)))

def friend_scroll_overlap(before,after):
    """Navigation evidence only, never eligibility for deleting a friend.

    A complete deletion row excludes the clipped bottom row, low-confidence
    names and all-numeric names. Those visible labels still establish overlap
    when they move upwards into the next viewport.
    """
    def labels(s):
        return [w for w in s.words if 210<=w.box[0]<=245 and 232<=w.center[1]<620
                and w.score>=.65 and len(w.text)>=2 and re.search(r'\w',w.text)
                and not w.text.startswith('等级')]
    return any(a.text==b.text and 0<a.center[1]-b.center[1]<360
               for a in labels(before) for b in labels(after))


def green_button_enabled(s,roi):
    x,y,w,h=roi;im=s.image[y:y+h,x:x+w].astype('int16')
    return bool(im.size and ((im[:,:,1]>135)&(im[:,:,1]>im[:,:,2]*1.1)&
                            (im[:,:,1]>im[:,:,0]*1.1)).mean()>.012)


def recommendation_rows(s):
    if not is_social(s):return []
    rows=[]
    for w in s.words:
        if not (215<=w.center[0]<395 and 140<=w.center[1]<565 and w.score>=.85):continue
        y=w.center[1]+18
        if w.text.startswith('等级') or re.fullmatch(r'[\d\W]+',w.text) and w.center[1]>w.box[1]+20:continue
        # Each name is above the power/time row. The latter cannot be a target.
        if not s.find(r'^(?:\d+.*(?:前|在线)|在线)$',(390,y-5,100,45)):continue
        if any(abs(y-r['point'][1])<35 for r in rows):continue
        status=s.find('^已申请$',(590,y-25,95,50))
        rows.append({'name':w.text,'point':(635,y),'pending':bool(status)})
    return sorted(rows,key=lambda r:r['point'][1])


def has_add_cross(s,point):
    x,y=point;im=s.image[max(0,y-16):y+17,x-17:x+18]
    if im.shape!=(33,35,3):return False
    white=np.min(im,axis=2)>210
    # Bright plus in a dark outlined button, not the grey "already applied" label.
    horizontal=max(white[row:row+3,5:30].mean() for row in range(10,21))
    return bool(white[4:29,15:20].mean()>.72 and horizontal>.80 and
                white[:9,:9].mean()<.10 and white[-9:,-9:].mean()<.10)


def friend_limit_notice(s):
    # 好友已满 is the account cap; the request quota is worded differently and
    # carries no 好友, so both shapes are checked before retrying a row.
    return bool(s.find('好友.*(?:已满|上限)|(?:达到|超出).*好友') or
                s.find('申请.*(?:已达|上限)|(?:今日|本日).*(?:上限|次数已满)'))


def components(mask):
    seen=np.zeros(mask.shape,bool);height,width=mask.shape
    for y,x in zip(*np.where(mask)):
        if seen[y,x]:continue
        stack=[(int(x),int(y))];seen[y,x]=True;xs=[];ys=[]
        while stack:
            px,py=stack.pop();xs.append(px);ys.append(py)
            for nx,ny in ((px-1,py),(px+1,py),(px,py-1),(px,py+1)):
                if 0<=nx<width and 0<=ny<height and mask[ny,nx] and not seen[ny,nx]:
                    seen[ny,nx]=True;stack.append((nx,ny))
        yield min(xs),min(ys),max(xs)+1,max(ys)+1,len(xs)


def notification_badges(s,roi):
    """The client's flat orange badge, with a small cream exclamation mark.

    Narrow size, colour and glyph checks exclude orange/red item artwork.
    """
    x0,y0,width,height=roi;im=s.image[y0:y0+height,x0:x0+width].astype('int16')
    b,g,r=(im[:,:,i] for i in range(3))
    mask=(r>175)&(g>45)&(g<195)&(b<130)&(r-g>45)&(r-b>75)
    found=[]
    for x,y,right,bottom,area in components(mask):
        w=right-x;h=bottom-y
        # The badge pulse can produce an 18x17 body as well as the wider
        # original frame. Keep the flat colour and ! glyph checks below.
        if not (14<=w<=26 and 11<=h<=22 and .95<=w/h<=1.65 and area>w*h*.50):continue
        part=im[y:bottom,x:right];body=part[mask[y:bottom,x:right]]
        if body[:,2].std()>16 or not (175<body[:,2].mean()<220 and
                60<body[:,1].mean()<135 and 20<body[:,0].mean()<85):continue
        white=(part[:,:,2]>225)&(part[:,:,1]>175)&(part[:,:,0]>90)
        white[:,:w//4]=False;white[:,w-w//4:]=False
        marks=[box for box in components(white) if box[4]>=2 and 1<=box[2]-box[0]<=9]
        for stem in marks:
            if stem[3]-stem[1]<4:continue
            if 6<=stem[3]-stem[1]<=12 and 2<=stem[2]-stem[0]<=6:
                p=(x0+x+w//2,y0+y+h//2)
                if p not in found:found.append(p)
            for dot in marks:
                if not (stem[3]<=dot[1]<=stem[3]+6 and 1<=dot[3]-dot[1]<=6):continue
                if abs((stem[0]+stem[2])-(dot[0]+dot[2]))<=6:
                    p=(x0+x+w//2,y0+y+h//2)
                    if p not in found:found.append(p)
    return sorted(found,key=lambda p:(p[1],p[0]))


def bag_signature(s):
    # Only item thumbnails, excluding the live world and selected-item details.
    return np.asarray(Image.fromarray(s.image[90:675,140:715]).resize((72,72))).astype('int16')


def is_channel_account_panel(s):
    return bool(s.find('^个人中心$',(300,0,260,75)) and
                s.find('^订单记录$',(100,220,170,75)) and
                s.find('^版本信息$',(100,650,170,70)) and
                s.find('^自动登录$',(100,550,170,80)))


class OtherTasks:
    def close_channel_account_panel(self,s):
        if not is_channel_account_panel(s):return s
        # The SDK drawer occupies x=0..720. Tap only the observed outside
        # backdrop, never its account controls or the game's right-hand menus.
        self.note('渠道悬浮窗遮挡了入口，关闭个人中心后重试')
        self.b.click_at(s,(970,535),['^个人中心$','^订单记录$','^版本信息$'],
                        '关闭渠道账号侧栏')
        return self.wait_for_screen(lambda q:not is_channel_account_panel(q),
                                    '关闭渠道账号侧栏',timeout=6)

    def settle_friend_list(self,s):
        for _ in range(7):
            self.b.sleep(.7);fresh=self.observe();self.b.guard(fresh)
            if not is_friend_list(fresh):raise TaskBlocked('好友列表等待停稳时页面改变')
            if same_friend_positions(s,fresh):return fresh
            s=fresh
        raise TaskBlocked('好友列表仍在移动或姓名未读清，未执行删除')

    def read_friend_time(self,s,row):
        text=self.b.read_text_crop(s,row['time_roi'])
        days=inactive_days(text)
        # A readable independent full-frame result must agree. Never repair
        # digit/unit substitutions to make a friend eligible for deletion.
        full=s.find(OFFLINE,row['time_roi'])
        if days is None or (full and full.score>=.80 and inactive_days(full.text)!=days):return None
        return {**row,'time':text,'days':days}

    def verified_friend_rows(self,s):
        result=[]
        for row in friend_name_rows(s):
            value=self.read_friend_time(s,row)
            if value is not None:result.append(value)
            else:
                unknown=self.report.setdefault('friend_time_unreadable',[])
                if row['name'] not in unknown:unknown.append(row['name'])
        return result

    def friend_menu(self,*,reset=False):
        s=self.observe();self.b.guard(s)
        # Reopening the verified world entrance resets the list to its first
        # page. Only the cleanup scan needs this, not each friend or coin action.
        if reset and (is_friend_list(s) or is_social(s)):s=self.home(s)
        if not is_friend_list(s):
            if is_social(s):self.b.click_text(s,'^好友$',roi=(0,125,95,105))
            else:
                s=self.home(s)
                for attempt in range(3):
                    # The channel bubble sits against the left edge; use the
                    # right half of the friend icon, away from that overlay.
                    self.click_world(s,(63,383),'打开好友管理')
                    s=self.wait_for_screen(lambda q:is_friend_list(q) or is_channel_account_panel(q),
                                           '打开好友列表',timeout=8)
                    if is_friend_list(s):break
                    s=self.home(self.close_channel_account_panel(s))
                else:raise TaskBlocked('好友入口连续被渠道悬浮窗遮挡，已关闭侧栏，未进入账号设置')
            s=self.await_page('^好友数量$') if not is_friend_list(s) else s
        if not friend_count(s):raise TaskBlocked('好友数量或上限未读清')
        return s

    def social_menu(self):
        s=self.observe();self.b.guard(s)
        if not is_social(s):
            s=self.friend_menu();self.b.click_text(s,'^社交$',roi=(0,240,95,105))
            s=self.await_page('^推荐添加$','^申请列表$')
        if not is_social(s):raise TaskBlocked('好友推荐页未确认')
        return s

    def exchange_friend_coins(self):
        s=self.friend_menu();clicked=[]
        for _ in range(3):
            self.b.guard(s)
            w=s.find(FRIEND_EXCHANGE,(165,620,390,65))
            if not w:raise TaskBlocked('好友一键赠送/收取按钮未识别')
            if not green_button_enabled(s,(300,632,145,40)):break
            label=w.text
            if label in clicked:raise TaskBlocked('好友赠送/收取结果未确认，停止重复点击')
            self.b.click_text(s,FRIEND_EXCHANGE,roi=(165,620,390,65));clicked.append(label)
            for _ in range(6):
                s=self.observe();self.b.guard(s)
                if s.find('^获得奖励$',(400,70,500,160)) and s.find('点击空白位置关闭'):
                    self.b.click_at(s,(640,660),['^获得奖励$','点击空白位置关闭'],'关闭好友币奖励');continue
                if is_friend_list(s) and (not green_button_enabled(s,(300,632,145,40)) or
                        (q:=s.find(FRIEND_EXCHANGE,(165,620,390,65))) and q.text!=label):break
                self.b.sleep(.5)
            else:raise TaskBlocked('好友币领取或赠送状态未确认')
        return {'status':'done','actions':clicked,'message':'好友币赠送/收取已处理' if clicked else '好友币暂无可赠送或收取'}

    def remove_friend(self,row,before):
        s=self.settle_friend_list(self.observe());self.b.guard(s)
        candidates=[r for r in friend_name_rows(s) if r['name']==row['name'] and abs(r['y']-row['y'])<15]
        matches=[r for candidate in candidates if (r:=self.read_friend_time(s,candidate)) is not None]
        threshold=self.options['other']['inactive_days']
        if len(matches)!=1 or matches[0]['days']!=row['days'] or matches[0]['days']<=threshold:
            raise TaskBlocked('删除前好友身份或未登录时间发生变化')
        if friend_count(s)!=before:raise TaskBlocked('删除前好友数量发生变化')
        row=matches[0]
        self.b.click_at(s,row['point'],['^好友数量$','^'+re.escape(row['name'])+'$'],'查看待清理好友资料')
        profile=self.await_page('^助战怪兽$','^删除好友$')
        if not profile.find('^'+re.escape(row['name'])+'$',(630,110,430,70)):
            raise TaskBlocked('好友资料身份不符，未点击删除')
        self.b.save_screen(profile,self.report['folder']/'friend-before-removal.png')
        self.b.click_text(profile,'^删除好友$',roi=(490,520,190,70))
        confirmed=False;unchanged_count=0
        for _ in range(12):
            q=self.observe();self.b.guard(q)
            prompt=q.region_text((250,200,800,260))
            if not confirmed and friend_delete_confirmation(q):
                # The generic dialog covers the name. It is safe only inside
                # this transaction, after checking list age/count AND profile.
                # A leftover dialog handled by home() is always cancelled.
                generic=bool(re.fullmatch(r'是否删除该好友[?？]?',re.sub(r'\s+','',prompt)))
                known=row['name'] in prompt or generic
                if not known:
                    self.b.click_text(q,'^取消$',roi=(350,380,290,190))
                    raise TaskBlocked('删除确认中的好友身份不符，已取消')
                self.b.click_text(q,'^确定$',roi=(640,380,380,190));confirmed=True;continue
            if is_friend_profile(q) and q.find('^添加好友$',(490,520,190,70)):
                self.b.click_at(q,(1082,121),['^助战怪兽$','^添加好友$'],'关闭已删除好友资料');continue
            if is_friend_list(q):
                after=friend_count(q)
                if after==before and unchanged_count<3:
                    unchanged_count+=1;self.b.sleep(.6);continue
                if after!=(before[0]-1,before[1]):raise TaskBlocked('删除后的好友数量变化不符')
                result={'name':row['name'],'inactive':row['time'],'before':before[0],'after':after[0]}
                self.report.setdefault('friends_removed',[]).append(result);self.checkpoint()
                self.note('已清理超过设定天数的好友：'+row['name']+'（'+row['time']+'）')
                return q
            self.b.sleep(.5)
        raise TaskBlocked('删除好友后尚未确认结果，未重复删除')

    def clear_inactive_friends(self):
        s=self.settle_friend_list(self.friend_menu(reset=True))
        before=friend_count(s);threshold=self.options['other']['inactive_days']
        seen=set();removed=0;checked=set();scroll_distance=90;scan_restarts=0
        for _ in range(before[0]*2+12):
            self.b.guard(s)
            if not is_friend_list(s):raise TaskBlocked('清理时好友列表发生变化')
            rows=self.verified_friend_rows(s);checked.update(r['name'] for r in rows)
            row=next((r for r in rows if r['days']>threshold),None)
            if row:
                s=self.settle_friend_list(self.remove_friend(row,friend_count(s)))
                removed+=1;seen.clear();continue
            signature=friend_list_signature(s)
            if signature in seen:raise TaskBlocked('好友列表重复到达旧位置，未跳过未检查的好友')
            seen.add(signature)
            self.b.audit({'action':'swipe','reason':'慢速重叠检查未登录好友','from':[350,530],
                          'to':[350,530-scroll_distance],'status':'requested'})
            # The game coasts after release. A short, slow drag retains about
            # two complete rows of overlap in the current client.
            if not self.b.wait(self.b.controller.post_swipe(350,530,350,530-scroll_distance,1500)).succeeded:raise TaskBlocked('好友翻页失败')
            self.b.sleep(1);after=self.settle_friend_list(self.observe())
            if same_friend_positions(s,after):break
            if not friend_scroll_overlap(s,after):
                # Do not process or delete anything on a page reached through
                # an unverified gap. Reread, then rescan from the known top at
                # a shorter drag distance, retaining the deletion audit.
                for retry in range(3):
                    self.note(f'好友翻页衔接未读清，重新识别（{retry+1}/3）')
                    self.b.sleep(.7);after=self.settle_friend_list(self.observe())
                    if friend_scroll_overlap(s,after) or same_friend_positions(s,after):break
                if same_friend_positions(s,after):break
                if not friend_scroll_overlap(s,after):
                    self.b.save_screen(s,self.report['folder']/'friends-scroll-before.png')
                    self.b.save_screen(after,self.report['folder']/'friends-scroll-after.png')
                    if scan_restarts>=3:
                        raise TaskBlocked('好友翻页衔接已重试3次仍未确认，已保留未核实好友，未跨页删除')
                    scan_restarts+=1;scroll_distance=max(15,scroll_distance//2)
                    self.note(f'好友翻页未确认重叠，缩短拖动并从顶部重新检查（{scan_restarts}/3）')
                    s=self.settle_friend_list(self.friend_menu(reset=True));seen.clear();continue
            s=after
        else:raise TaskBlocked('好友列表未在检查范围内到达底部')
        unknown=[name for name in self.report.get('friend_time_unreadable',[]) if name not in checked]
        return {'status':'done','removed':removed,'days':threshold,'checked':len(checked),'unreadable':unknown,
                'message':f'检查好友{len(checked)}人，清理{removed}人（超过{threshold}天未登录）'+
                          (f'；{len(unknown)}人在线时间未读清，已保留' if unknown else '')}

    def request_friend(self,row):
        """Click one pixel-verified add button, then confirm by row position.

        OCR reads the same player name differently between frames (a real run
        recorded the same row as 约网yhkg丶cc and 约网yhkg`cc), so the result is
        matched by the row's vertical position and the button pixels instead of
        its text. A row whose plus is still drawn after the click was not sent,
        so retrying it once cannot duplicate an accepted request.
        """
        for attempt in range(2):
            fresh=self.observe();self.b.guard(fresh)
            if is_social(fresh) and fresh.find('^已申请$',(590,row['point'][1]-25,95,50)):
                return 'sent'
            same=[r for r in recommendation_rows(fresh) if abs(r['point'][1]-row['point'][1])<14]
            if same and same[0]['pending']:return 'sent'
            if not same or not has_add_cross(fresh,same[0]['point']):
                return 'gone' if attempt==0 else 'unconfirmed'
            self.b.click_at(fresh,same[0]['point'],['^推荐添加$','^申请列表$'],'申请添加推荐好友')
            for _ in range(6):
                s=self.observe();self.b.guard(s)
                if friend_limit_notice(s):return 'limit'
                # The row's time/name OCR may flicker after its + becomes
                # 已申请. Confirm that visible terminal state directly before
                # asking the row parser to recognize it again.
                if is_social(s) and s.find('^已申请$',(590,row['point'][1]-25,95,50)):
                    return 'sent'
                updated=next((r for r in recommendation_rows(s)
                              if abs(r['point'][1]-row['point'][1])<14),None)
                if updated and updated['pending']:return 'sent'
                self.b.sleep(.5)
            self.note('好友申请未被确认，重试本行一次：'+row['name'])
        return 'unconfirmed'

    def add_friends_to_capacity(self):
        start=friend_count(self.friend_menu());current=start;sent=[];accepted=0
        if current[0]>=current[1]:return {'status':'done','message':'好友数量已达上限','count':current,'requested':[]}
        s=self.social_menu()
        # The empty request pane has a large "无". Never use the reject button.
        requests=s.region_text((720,130,540,470))
        if requests and not s.find('^无$',(720,130,540,470)) and green_button_enabled(s,(1070,630,155,45)):
            self.b.click_text(s,'^全部同意$',roi=(1050,620,200,70))
            self.b.sleep(.8);current=friend_count(self.friend_menu())
            if current is None or current[0]<start[0]:raise TaskBlocked('同意好友申请后的数量未确认')
            accepted=current[0]-start[0]
            if accepted==0:raise TaskBlocked('好友申请处理结果未确认')
            s=self.social_menu()
        budget=current[1]-current[0];seen=set();batches=set();stalled=0
        for _ in range(8):
            self.b.guard(s)
            if not is_social(s):raise TaskBlocked('好友推荐页面改变')
            signature=tuple(r['name'] for r in recommendation_rows(s))
            if signature in batches:break
            batches.add(signature)
            for row in recommendation_rows(s):
                if len(sent)>=budget:break
                if row['pending'] or row['name'] in seen or not has_add_cross(s,row['point']):continue
                seen.add(row['name'])
                result=self.request_friend(row)
                if result=='limit':
                    self.note('好友数量或今日申请次数已达上限，停止继续申请')
                    budget=len(sent);break
                if result=='sent':
                    sent.append(row['name']);self.note('已申请好友：'+row['name'])
                    self.report['friend_requests_sent']=list(sent);self.checkpoint()
                    stalled=0;s=self.observe();continue
                if result=='unconfirmed':
                    # One stubborn row must never fail the whole 其他任务. Two in
                    # a row means this account cannot send more requests today.
                    self.report.setdefault('friend_requests_unconfirmed',[]).append(row['name'])
                    self.note('该行申请连续两次未确认，已跳过：'+row['name'])
                    stalled+=1
                    if stalled>=2:budget=len(sent);break
            if len(sent)>=budget:break
            self.b.click_text(s,'换一批$',roi=(550,75,150,55));s=self.observe()
        current=friend_count(self.friend_menu())
        if not current:raise TaskBlocked('结束时好友数量未读清')
        full=current[0]>=current[1]
        message=f'好友{current[0]}/{current[1]}，同意{accepted}人，发送{len(sent)}条申请'
        skipped=self.report.get('friend_requests_unconfirmed',[])
        if skipped:message+=f'；{len(skipped)}行点击后未变成已申请，已跳过'
        if not full:message+='；等待对方同意' if sent else '；暂无新的可申请好友'
        return {'status':'done' if full else 'waiting','message':message,'count':current,'accepted':accepted,'requested':sent}

    def clear_bag_notifications(self):
        s=self.observe();self.b.guard(s)
        if not is_bag(s):
            s=self.home()
            if not notification_badges(s,(10,230,90,70)):
                return {'status':'done','cleared':0,'message':'背包没有新物品感叹号'}
            self.click_world(s,(43,270),'打开背包查看新物品');s=self.await_page('^背包$','^全部$','^元核$')
        if not is_bag(s):raise TaskBlocked('背包页面未确认')
        self.b.click_text(s,'^全部$',roi=(0,165,110,80));s=self.observe()
        count=parse_ratio(s.region_text((0,90,100,60)))
        if not count:raise TaskBlocked('背包容量未读清')
        cleared=0;previous=None
        for _ in range(min(60,math.ceil(count[0]/18)+3)):
            for _ in range(40):
                self.b.guard(s)
                if not is_bag(s):raise TaskBlocked('背包查看时页面改变')
                badges=notification_badges(s,(140,90,580,565))
                if not badges:break
                x,y=badges[0];cx=min((188,284,382,480,576,674),key=lambda n:abs(n-x))
                # Only a single item-selection click. The right-side Use,
                # Enhance, Smelt and Decompose controls are outside this area.
                point=(cx,min(y+25,660))
                self.b.click_at(s,point,['^背包$','^全部$'],'查看背包新物品（仅选中）')
                for _ in range(5):
                    s=self.observe();self.b.guard(s)
                    if is_bag(s) and not any(math.dist((x,y),p)<12 for p in notification_badges(s,(140,90,580,565))):break
                    self.b.sleep(.4)
                else:raise TaskBlocked('新物品提示未消失，未重复点击或使用物品')
                cleared+=1
            else:raise TaskBlocked('本页背包提示数量异常')
            signature=bag_signature(s)
            if previous is not None and np.mean(np.max(np.abs(signature-previous),axis=2)>35)<.025:break
            previous=signature
            if not self.b.wait(self.b.controller.post_swipe(450,590,450,240,650)).succeeded:raise TaskBlocked('背包翻页失败')
            self.b.sleep(.8);s=self.observe()
        s=self.home()
        if notification_badges(s,(10,230,90,70)):raise TaskBlocked('背包仍有未清除提示，已保留现场')
        return {'status':'done','cleared':cleared,'message':f'背包新物品感叹号已清理{cleared}处'}

    def challenge_abyss(self):
        # Reuse the verified tool implementation and the existing connection.
        # Its temporary result status must not finish the surrounding daily run.
        from .abyss import AbyssPlayer, REFRESH
        status = self.report['status']
        settings = self.b.settings
        try:
            player = AbyssPlayer(self.b, self.report, self.emit)
        finally:
            # Daily initialization normalizes a copy. Keep the parent's option
            # object attached so instance overrides still restore correctly.
            self.b.settings = settings
        player.start_time = self.start_time
        player.limit = min(self.limit, self.battles + player.limit)
        player.battles = self.battles
        player.state = self.state
        player.day = self.day
        player.active_task_id = getattr(self, 'active_task_id', 'other')
        before = len(self.report.get('team_attempts', []))
        try:
            message = player.play()
            outcome = self.report['status']
            self.report['status'] = status
            player.finish_world()
            attempts = self.report.get('team_attempts', [])[before:]
            return {'status': 'done' if outcome == 'completed' else 'skipped',
                    'message': message, 'attempts': len(attempts),
                    'refresh_schedule': REFRESH,
                    'next_refresh': self.report.get('next_refresh')}
        finally:
            self.report['status'] = status
            self.battles = player.battles
            if hasattr(player, 'last_screen'):
                self.last_screen = player.last_screen

    def other(self):
        options=self.options['other'];jobs=[]
        if options['friend_management']:
            if options['exchange_friend_coins']:jobs.append(('friend_coins',self.exchange_friend_coins))
            if options['remove_inactive_friends']:jobs.append(('inactive_friends',self.clear_inactive_friends))
            if options['auto_add_friends']:jobs.append(('add_friends',self.add_friends_to_capacity))
        if options['collect_daily_single']:jobs.append(('daily_single',self.collect_daily_single))
        if options['collect_plane_lord']:jobs.append(('plane_lord',self.collect_plane_lord))
        if options['collect_contract']:jobs.append(('contract',self.collect_contract))
        if options['piggy_bank']:jobs.append(('piggy_bank',self.collect_piggy_bank))
        if options['buy_star_spores']:jobs.append(('star_spores',self.buy_star_spores))
        if options['tribe_gold_donation']:jobs.append(('tribe_gold_donation',self.tribe_gold_donation))
        if options['open_monster_boxes']:jobs.append(('monster_boxes',self.open_monster_boxes))
        if options['clear_bag_notifications']:jobs.append(('bag',self.clear_bag_notifications))
        if options['challenge_abyss']:jobs.append(('abyss',self.challenge_abyss))
        results=self.report.setdefault('other_tasks',{});failures=[]
        by_instance=self.report.setdefault('other_tasks_by_instance',{})
        instance=self.report_key('other')
        prior=by_instance.setdefault(instance,dict(results) if not by_instance else {})
        for key,run in jobs:
            if prior.get(key,{}).get('status') in ('done','skipped'):
                results[key]=prior[key];continue
            try:result=self.with_page_recovery(run,'其他任务：'+key)
            except TaskBlocked as error:
                result={**results.get(key,{}),'status':'blocked','message':str(error)};failures.append(key)
                if hasattr(self,'last_screen'):self.b.save_screen(self.last_screen,self.report['folder']/(key+'-blocked.png'))
            results[key]=result;prior[key]=result;self.note(result['message']);self.checkpoint();self.home()
        if failures:raise TaskBlocked('其他任务部分未完成：'+'、'.join(failures))
        return '；'.join(results[key]['message'] for key,_ in jobs) if jobs else '其他任务的子任务均未开启'
