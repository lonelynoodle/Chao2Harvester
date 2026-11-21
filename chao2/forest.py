"""Visible forest nodes, measured map panning and free exploration settlement.

No forest reset, paid acceleration, point purchase or random resource reroll.
"""
from dataclasses import dataclass
from datetime import datetime,timedelta
from functools import lru_cache
import math
import re
import time
import cv2
import numpy as np
from PIL import Image
from .backend import ROOT,Word
from .configuration import selected_rows,team_order
from .overview import forest_overview_busy
from .policy import TaskBlocked,ResourceReadError,SafetyStop,FightLost
from .activities import BudgetReached
from .fixed_hud import FOREST_POINTS_ROI,HUD_SCALES,fixed_hud_ratio

LABELS={'lamp':'森灯','beast':'凶兽','spore':'强化孢子','divinity':'神性孢子',
        'evolution':'进化孢子','spring':'命运之泉','unknown':'未探明节点'}
NODE_ROI=(20,90,1135,535)
INSTANT_KINDS={'spore','divinity','evolution','lamp','spring'}
PAN_RETRIES=3
CHALLENGE_SYMBOLS=('forest-challenge-star.png','forest-challenge-explorer.png')
FOREST_POINTS_SCALES=HUD_SCALES


class ForestWaiting(BudgetReached):
    pass


def is_forest_map(s):
    if not s.has('^黑暗森林$','^信息$'):return False
    if s.find('敌方阵容|点击空白位置关闭|^获得奖励$|^智者$'):return False
    # Modal backgrounds still expose the title to OCR; they are not a map.
    title=s.image[14:43,122:218]
    return bool((title.min(axis=2)>165).mean()>.12)


def forest_detail_name(s):
    # A revealed pink challenge node is another explorer, rather than a
    # beast. The closing parenthesis may be clipped at the title decoration.
    w=s.find(r'.*凶兽$|^其他探索者[（(]特殊事件[）)]?$',(20,115,500,65))
    return w.text if w else None


def forest_detail(s):
    if not s.has('^敌方阵容$','^排阵$','^挑战$','可获得奖励'):return None
    return forest_detail_name(s)


def forest_timer(s):
    if not is_forest_map(s):return None
    if not s.find('^立即完成$'):return None
    times=[int(m[1])*3600+int(m[2])*60+int(m[3]) for w in s.words
           if (m:=re.fullmatch(r'[^\d\w]{0,2}(\d{1,2}):(\d{2}):(\d{2})',w.text)) and
           int(m[2])<60 and int(m[3])<60 and 55<w.center[1]<630]
    return min(times) if times else None


def forest_points(b,s):
    if not is_forest_map(s):raise TaskBlocked('森林地图未确认，未读取探索点')
    # The full-frame detector can merge this HUD with map-node labels behind
    # it (0/16 -> 0l6ff;). Always crop the fixed number field and run BOTH
    # text detection and recognition locally; never reuse full-frame words.
    pair,reads=fixed_hud_ratio(b,s,FOREST_POINTS_ROI)
    if pair is not None:return pair[0]
    raise ResourceReadError('森林探索点未读清（固定区域局部识别，最多4次；'+'；'.join(reads)+'）')


def forest_collect_ready(b,s):
    if not is_forest_map(s):return False
    if b.match_template(s,'forest-collect.png',[1170,520,110,110],.88):return True
    # Its animated gold glow changes the template score. OCR may omit the
    # leading 一; require the fixed button area and its enabled gold surface.
    if not s.find(r'^(?:一)?键收取$',(1170,535,110,80)):return False
    im=s.image[548:604,1180:1275].astype('int16');b,g,r=(im[:,:,i] for i in range(3))
    return bool(((r>150)&(g>105)&(b<155)&(r-b>45)).mean()>.20)


@lru_cache(maxsize=24)
def symbol(name):
    return cv2.cvtColor(np.asarray(Image.open(ROOT/'resource/image'/name).convert('RGB')),cv2.COLOR_RGB2GRAY)


def symbol_score(s,roi,name,scales=(1,)):
    x,y,w,h=map(int,roi)
    if x<0 or y<0 or x+w>1280 or y+h>720:return 0
    gray=cv2.cvtColor(s.image[y:y+h,x:x+w],cv2.COLOR_BGR2GRAY);template=symbol(name);best=0
    for scale in scales:
        rw,rh=round(template.shape[1]*scale),round(template.shape[0]*scale)
        if min(rw,rh)<6 or rw>w or rh>h:continue
        im=cv2.resize(template,(rw,rh),interpolation=cv2.INTER_AREA)
        best=max(best,float(cv2.minMaxLoc(cv2.matchTemplate(gray,im,cv2.TM_CCOEFF_NORMED))[1]))
    return best


def forest_kind(s,point):
    x,y=point;roi=(x-30,y-64,60,48)
    scores={kind:symbol_score(s,roi,f'forest-{kind}.png') for kind in ('beast','unknown')}
    for kind in ('lamp','evolution','spore','divinity','spring'):
        scores[kind]=symbol_score(s,roi,f'forest-symbol-{kind}.png',(.35,.4,.45,.5,.55))
    ranked=sorted(scores.items(),key=lambda item:item[1],reverse=True)
    threshold=.82 if ranked[0][0] in ('beast','unknown') else .84
    return ranked[0][0] if ranked[0][1]>=threshold and ranked[0][1]-ranked[1][1]>=.045 else None


@dataclass
class ForestNode:
    kind:str
    point:tuple
    action:str='explore'
    cost:int=0
    world:tuple|None=None


def forest_nodes(b,s):
    if not is_forest_map(s):return []
    rows=[]
    for w in s.words:
        x,y=w.center
        # The lower ready beast is above the HUD, but its label center is y=620.
        if w.text=='挑战' and 35<=x<=1140 and 100<=y<=630 and w.box[1]+w.box[3]<=640:
            rows.append(ForestNode('beast',(x,y),'challenge'));continue
        if not 35<=x<=1140 or not 100<=y<=615:continue
        if w.text!='开始探索':continue
        kind=forest_kind(s,(x,y))
        if kind is None:continue  # An unrecognized icon is not an unknown '?' node.
        roi=(x-30,y+8,75,38)
        text=s.region_text(roi)
        m=re.search(r'(\d+)\s*$',text)
        if not b.match_template(s,'forest-point.png',[x-30,y+8,44,37],.86):continue
        cost=int(m[1]) if m and 1<=int(m[1])<=3 else b.read_number(s,(x+5,y+13,25,27))
        if cost not in (1,2,3):continue
        rows.append(ForestNode(kind,(x,y),'explore',cost))
    # Full-frame OCR sometimes drops 挑战 on a glowing revealed beast. Locate
    # that star in this frame, then OCR its own action before adding a node.
    gray=cv2.cvtColor(s.image[60:625,20:1155],cv2.COLOR_BGR2GRAY)
    for name in CHALLENGE_SYMBOLS:
        scores=cv2.matchTemplate(gray,symbol(name),cv2.TM_CCOEFF_NORMED)
        for _ in range(8):
            _,score,_,top=cv2.minMaxLoc(scores)
            if score<.85:break
            tx,ty=top;scores[max(0,ty-40):ty+41,max(0,tx-40):tx+41]=0
            x,y=tx+20+23,ty+60+55
            if not 35<=x<=1140 or not 100<=y<=630:continue
            if any(math.dist(n.point,(x,y))<25 for n in rows):continue
            roi=(x-45,y-22,90,44)
            if re.sub(r'\s+','',b.read_text_region(s,roi,3))!='挑战':continue
            s.words.append(Word('挑战',list(roi),.99))
            rows.append(ForestNode('beast',(x,y),'challenge'))
    return rows


def recover_forest_node(b,s,expected,node):
    """Local recovery is evidence from this frame, never a cached click."""
    if not is_forest_map(s):return None
    x,y=map(round,expected)
    if not 70<=x<=1100 or not 100<=y<=(630 if node.action=='challenge' else 600):return None
    if node.action=='challenge':
        # A revealed beast has a pink star, unlike the unexplored beast icon.
        if max(symbol_score(s,(x-43,y-75,86,66),name) for name in CHALLENGE_SYMBOLS)<.85:return None
        label='挑战';roi=(x-45,y-22,90,44)
    else:
        if forest_kind(s,(x,y))!=node.kind:return None
        label='开始探索';roi=(x-57,y-22,114,44)
    if re.sub(r'\s+','',b.read_text_region(s,roi,3))!=label:return None
    # Add only the re-read fixed action, not any inferred title or cost.
    s.words.append(Word(label,list(roi),.99))
    return next((n for n in forest_nodes(b,s) if n.kind==node.kind and n.action==node.action and
                 n.cost==node.cost and math.dist(n.point,(x,y))<12),None)


def forest_reward_at(s,point):
    """A revealed resource has a square frame where the node icon used to be.

    Require three aligned sides; glowing branches and diamond-shaped unopened
    nodes are not completion evidence. This does not infer the reward's contents.
    """
    if not is_forest_map(s):return False
    x,y=map(round,point)
    if x<38 or x+38>1280 or y<70 or y+5>720:return False
    if s.find('^开始探索$|^挑战$|^立即完成$',(x-55,y-22,110,44)):return False
    gray=cv2.cvtColor(s.image[y-70:y+5,x-38:x+38],cv2.COLOR_BGR2GRAY)
    lines=cv2.HoughLinesP(cv2.Canny(gray,60,160),1,np.pi/180,20,minLineLength=30,maxLineGap=4)
    if lines is None:return False
    sides=set()
    for x1,y1,x2,y2 in lines[:,0]:
        if abs(int(x1)-int(x2))<=2 and abs(int(y1)-int(y2))>=30 and 22<=(y1+y2)/2<=46:
            if 9<=(x1+x2)/2<=17:sides.add('left')
            if 59<=(x1+x2)/2<=67:sides.add('right')
        if abs(int(y1)-int(y2))<=2 and abs(int(x1)-int(x2))>=30 and 24<=(x1+x2)/2<=51:
            if 7<=(y1+y2)/2<=17:sides.add('top')
            if 56<=(y1+y2)/2<=66:sides.add('bottom')
    return len(sides)>=3


def select_forest_node(nodes,options,balance,waiting=False):
    order={row['id']:i for i,row in enumerate(selected_rows(options,'node_priority'))}
    available=[n for n in nodes if n.kind in order and
               (n.action=='challenge' or (not waiting and n.cost<=balance-options['reserve_points']))]
    # Already-unlocked free battles are settled separately from exploration.
    ready=[n for n in available if n.action=='challenge']
    if ready:available=ready
    elif options.get('strategy','overflow')=='overflow' and balance-options['reserve_points']>1:
        instant=[n for n in available if n.kind in INSTANT_KINDS]
        # Retain the last point for the full priority order when possible.
        leave_last=[n for n in instant if n.cost<balance-options['reserve_points']]
        if instant:available=leave_last or instant
        # With no identified instant node, use the normal order. Never invent
        # an instant reward behind an unrevealed question mark.
    return min(available,key=lambda n:(n.action!='challenge',order[n.kind],n.cost,
                                     math.dist(n.point,(640,350)))) if available else None


def pick_simple_forest_node(nodes,balance,reserve,ignored=(),*,allow_exploration=True):
    """Clear the visible page, preferring free fights and instant exploration."""
    free=[n for n in nodes if n.action=='challenge' and
          all(math.dist(n.point,point)>30 for point in ignored)]
    if free:return min(free,key=lambda n:math.dist(n.point,(640,350)))
    if not allow_exploration:return None
    usable=[n for n in nodes if n.action=='explore' and n.cost<=balance-reserve and
            all(math.dist(n.point,point)>30 for point in ignored)]
    return min(usable,key=lambda n:(n.kind not in INSTANT_KINDS,n.cost,
                                   math.dist(n.point,(640,350)))) if usable else None


def simple_forest_view_changed(before,after):
    """Simple mode needs only a changed view, never global map registration."""
    a,b=[cv2.resize(cv2.cvtColor(s.image[90:610,30:1140],cv2.COLOR_BGR2GRAY),(278,130))
         for s in (before,after)]
    return bool((cv2.absdiff(a,b)>18).mean()>.10)


def forest_dense_shift(before,after):
    """Consensus of textured branch patches when ORB has too few corners."""
    a=cv2.cvtColor(before.image[75:625,30:1150],cv2.COLOR_BGR2GRAY)
    b=cv2.cvtColor(after.image[75:625,30:1150],cv2.COLOR_BGR2GRAY)
    a=cv2.resize(a,None,fx=.5,fy=.5);b=cv2.resize(b,None,fx=.5,fy=.5)
    votes=[]
    for y in range(0,a.shape[0]-48,38):
        for x in range(0,a.shape[1]-48,55):
            patch=a[y:y+48,x:x+48]
            # Keep the low-contrast blue branches. Otherwise only repeated
            # question-mark icons survive and can vote for a false shift.
            # Correlation and multi-patch consensus still reject flat areas.
            if patch.std()<5:continue
            score=cv2.matchTemplate(b,patch,cv2.TM_CCOEFF_NORMED)
            _,value,_,point=cv2.minMaxLoc(score)
            if value>.93:votes.append((2*(point[0]-x),2*(point[1]-y)))
    if len(votes)<4:return None
    groups=[np.array([p for p in votes if math.dist(p,v)<5]) for v in votes]
    group=max(groups,key=len)
    if len(group)<4 or len(group)<len(votes)*.55:return None
    return tuple(float(v) for v in np.median(group,axis=0))

def forest_shift(before,after):
    """Estimate actual map displacement; swipe distances can clamp at an edge."""
    mask=np.zeros((720,1280),np.uint8);mask[75:625,30:1150]=255
    orb=cv2.ORB_create(nfeatures=2000)
    a,ad=orb.detectAndCompute(cv2.cvtColor(before.image,cv2.COLOR_BGR2GRAY),mask)
    b,bd=orb.detectAndCompute(cv2.cvtColor(after.image,cv2.COLOR_BGR2GRAY),mask)
    if ad is None or bd is None:return forest_dense_shift(before,after)
    pairs=cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(ad,bd,k=2)
    good=[p[0] for p in pairs if len(p)==2 and p[0].distance<.7*p[1].distance]
    if len(good)<18:return forest_dense_shift(before,after)
    src=np.float32([a[m.queryIdx].pt for m in good]);dst=np.float32([b[m.trainIdx].pt for m in good])
    matrix,inliers=cv2.estimateAffinePartial2D(src,dst,method=cv2.RANSAC,ransacReprojThreshold=2.5)
    if matrix is None or inliers.sum()<15:return forest_dense_shift(before,after)
    if abs(matrix[0,0]-1)>.012 or abs(matrix[1,1]-1)>.012 or abs(matrix[0,1])>.012:return forest_dense_shift(before,after)
    # Identical question marks and reward badges can outvote the branches.
    # Verify nontrivial motion against independent, larger textured patches.
    if math.hypot(matrix[0,2],matrix[1,2])>10:
        dense=forest_dense_shift(before,after)
        if dense is not None:return dense
    return float(matrix[0,2]),float(matrix[1,2])


def forest_shift_plausible(shift,dx,dy):
    cross=abs(shift[1]) if dx else abs(shift[0])
    along=shift[0] if dx else shift[1];requested=dx or dy
    return cross<=25 and along*requested>=-25 and abs(along)<=abs(requested)*1.75+35


class ForestActivity:
    def forest_wait_map(self):
        for _ in range(10):
            s=self.observe();self.b.guard(s)
            if is_forest_map(s):return s
            self.b.sleep(.5)
        raise TaskBlocked('森林未返回地图，保留现场')

    def forest_map(self):
        s=self.observe();self.b.guard(s)
        if is_forest_map(s):
            # No overview card was read on this entrance, so an older reading
            # must not be reused to skip or pan the map.
            self.forest_overview_state=''
            return s
        if forest_detail(s):
            self.b.click_at(s,(45,28),['敌方阵容','可获得奖励'],'关闭森林凶兽详情')
            self.forest_overview_state=''
            return self.forest_wait_map()
        # A timer can coexist with free challenges elsewhere on the same map.
        self.enter_overview('^黑暗森林$')
        return self.forest_wait_map()

    def forest_read_pan(self,before,requested=None):
        # Retry recognition, not input: an unregistered frame may already have
        # moved. Keep the original reference until displacement is confirmed.
        for reread in range(PAN_RETRIES+1):
            q=self.forest_wait_map();shift=forest_shift(before,q)
            plausible=shift is not None and (requested is None or
                                             forest_shift_plausible(shift,*requested))
            if plausible:return q,shift
            if reread<PAN_RETRIES:
                self.note(f'森林位移暂未确认，重新识别（{reread+1}/{PAN_RETRIES}）')
                self.b.sleep(.8)
        self.b.save_screen(before,self.report['folder']/'forest-pan-before.png')
        self.b.save_screen(q,self.report['folder']/'forest-pan-after.png')
        if shift is not None and requested is not None:
            self.forest_check_shift(before,q,shift,*requested)
        raise TaskBlocked(f'森林地图位移未核实，已重新识别{PAN_RETRIES}次；未重复滑动，截图已保存')

    def forest_check_shift(self,before,after,shift,dx,dy):
        # MuMu's swipe has momentum: verified 600px gestures can travel ~694px.
        # Use the measured displacement, checking its axis/direction instead
        # of pretending that the requested distance is a hard camera bound.
        if not forest_shift_plausible(shift,dx,dy):
            self.b.save_screen(before,self.report['folder']/'forest-pan-before.png')
            self.b.save_screen(after,self.report['folder']/'forest-pan-after.png')
            raise TaskBlocked(f'森林地图出现非预期位移：请求({dx},{dy})，实际({shift[0]:.1f},{shift[1]:.1f})')

    def forest_pan(self,s,dx,dy):
        self.b.guard(s)
        if not is_forest_map(s):raise TaskBlocked('森林移动前页面改变')
        dx=max(-600,min(600,int(dx)));dy=max(-380,min(380,int(dy)))
        x,y=640-dx//2,350-dy//2
        before=s
        self._forest_pan_serial=getattr(self,'_forest_pan_serial',0)+1
        pan_id=self._forest_pan_serial
        for attempt in range(PAN_RETRIES+1):
            self.b.guard(s)
            if not is_forest_map(s):raise TaskBlocked('森林滑动重试前页面改变')
            self.b.audit({'action':'swipe','reason':'查看森林相邻节点','pan_id':pan_id,
                          'attempt':attempt+1,'delta':[dx,dy],'status':'requested'})
            sent=self.b.wait(self.b.controller.post_swipe(x,y,x+dx,y+dy,1000)).succeeded
            error='' if sent else (self.b.controller.last_error or '控制器未返回成功，未提供错误详情')
            self.b.audit({'action':'swipe','reason':'森林滑动指令','pan_id':pan_id,
                          'attempt':attempt+1,'status':'sent' if sent else 'failed','error':error})
            if not sent:
                self.report.setdefault('forest_pan_errors',[]).append(
                    {'pan_id':pan_id,'attempt':attempt+1,'error':error})
                self.b.save_screen(before,self.report['folder']/f'forest-pan-{pan_id}-before.png')
                self.note('森林滑动指令未确认：'+error+'；正在核对实际画面')
            self.b.sleep(.6)
            q,shift=self.forest_read_pan(before,(dx,dy))
            if not sent and math.hypot(*shift)<=5:
                # A failed ADB reply can arrive before an accepted gesture has
                # finished. Give it time, then verify again before any retry.
                self.b.sleep(.6*(attempt+1));q,shift=self.forest_read_pan(before,(dx,dy))
            self.forest_check_shift(before,q,shift,dx,dy)
            moved=math.hypot(*shift)>5
            self.b.audit({'action':'swipe','reason':'森林实际位移','pan_id':pan_id,
                          'attempt':attempt+1,'requested':[dx,dy],'measured':list(shift),'status':'observed'})
            if not sent:
                self.b.save_screen(q,self.report['folder']/f'forest-pan-{pan_id}-attempt-{attempt+1}.png')
                if q.find('^立即完成$') and not before.find('^立即完成$'):
                    self.forest_record_view(q)
                    raise TaskBlocked('森林滑动后出现计时探索，页面改变，未重复滑动')
                if forest_points(self.b,q)<forest_points(self.b,before):
                    self.resource_balance('forest','探索点',forest_points(self.b,q))
                    raise TaskBlocked('森林滑动后探索点发生消耗，已保留现场，未重复操作')
            if sent or moved:
                # Account for total displacement exactly once, including any
                # small motion in earlier failed attempts. Never replay a
                # gesture that already moved the map despite its failed reply.
                self.forest_offset[0]-=shift[0];self.forest_offset[1]-=shift[1]
                if attempt or not sent:
                    self.report.setdefault('forest_pan_recoveries',[]).append(
                        {'pan_id':pan_id,'retries':attempt,'measured':list(shift),'reply_succeeded':sent})
                    self.note('森林滑动已恢复：'+('已核实画面移动，继续查找' if moved else '已核实地图边界'))
                return q,moved
            if attempt==PAN_RETRIES:
                raise TaskBlocked(f'森林地图滑动失败，已重试{PAN_RETRIES}次：{error}；前后截图已保存')
            self.note(f'森林画面未移动，重试滑动（{attempt+1}/{PAN_RETRIES}）')
            s=q

    def forest_record_view(self,s):
        self.resource_balance('forest','探索点',forest_points(self.b,s))
        seconds=forest_timer(s)
        if seconds is not None or s.find('^立即完成$'):
            self.forest_waiting=True
            self.report['forest_waiting']={'remaining_seconds':seconds,
                'ready_at':(datetime.now().astimezone()+timedelta(seconds=seconds)).isoformat(timespec='seconds') if seconds is not None else None}
        for n in forest_nodes(self.b,s):
            n.world=(n.point[0]+self.forest_offset[0],n.point[1]+self.forest_offset[1])
            if any(math.dist(n.world,p)<32 for p in self.forest_ignored):continue
            self.forest_pool=[old for old in self.forest_pool if math.dist(old.world,n.world)>32]
            self.forest_pool.append(n)

    def forest_exploration_stop(self,balance):
        if getattr(self,'forest_waiting',False):
            seconds=self.report.get('forest_waiting',{}).get('remaining_seconds')
            return '森林仍有计时探索；已检查免费挑战，不等待或加速'+(f'，剩余约{math.ceil(seconds/60)}分钟' if seconds is not None else '')
        maximum=self.options['forest']['max_explorations']
        if maximum and len(self.instance_rows('forest_explorations'))>=maximum:return '达到设置的探索节点上限，已检查免费挑战'
        reserve=self.options['forest']['reserve_points']
        if balance<=reserve:return f'探索点剩余{balance}，'+('已用完' if reserve==0 else '达到保留数量')+'；已检查免费挑战'
        return ''

    def forest_scan(self,s):
        self.note('检查森林可到达节点，按设置的类型优先级选择')
        self.forest_record_view(s)
        # A fresh scan starts at the actual upper-left map boundary, using
        # measured displacement rather than assuming each gesture moved 600px.
        pages=1
        for dx,dy in ((600,0),(0,380)):
            for _ in range(9):
                s,moved=self.forest_pan(s,dx,dy);pages+=1;self.forest_record_view(s)
                if pages%4==0:self.note(f'森林已检查{pages}个画面，找到{len(self.forest_pool)}个可操作节点')
                if not moved:break
            else:raise TaskBlocked('森林边界尚未确认，保留当前进度')
        direction=-600
        for row in range(10):
            for col in range(12):
                if pages>=90:raise TaskBlocked('森林本轮查找范围达到上限，未重置地图')
                s,moved=self.forest_pan(s,direction,0);pages+=1;self.forest_record_view(s)
                if pages%4==0:self.note(f'森林已检查{pages}个画面，找到{len(self.forest_pool)}个可操作节点')
                if not moved:break
            else:raise TaskBlocked('森林横向边界尚未确认')
            s,moved=self.forest_pan(s,0,-380);pages+=1;self.forest_record_view(s)
            if not moved:break
            direction=-direction
        else:raise TaskBlocked('森林纵向边界尚未确认')
        self.report['forest_scanned_pages']=self.report.get('forest_scanned_pages',0)+pages
        return s

    def forest_reach(self,s,node):
        for _ in range(14):
            local=(node.world[0]-self.forest_offset[0],node.world[1]-self.forest_offset[1])
            if 35<=local[0]<=1140 and 100<=local[1]<=(630 if node.action=='challenge' else 615):
                for retry in range(4):
                    self.b.guard(s)
                    local=(node.world[0]-self.forest_offset[0],node.world[1]-self.forest_offset[1])
                    n=next((n for n in forest_nodes(self.b,s) if n.kind==node.kind and
                            n.action==node.action and n.cost==node.cost and math.dist(n.point,local)<25),None)
                    if n is None:n=recover_forest_node(self.b,s,local,node)
                    if n is not None:
                        n.world=node.world;return s,n
                    if retry==3:break
                    self.navigation_retry('森林目标文字未读清，重新识别节点及费用',retry+1,s)
                    self.b.sleep(.6);q=self.forest_wait_map();shift=forest_shift(s,q)
                    if shift is None:raise TaskBlocked('森林目标重试时地图位移未确认，未点击历史位置')
                    self.forest_offset[0]-=shift[0];self.forest_offset[1]-=shift[1];s=q
                raise TaskBlocked('森林目标节点或费用连续3次重试仍未确认，未使用历史坐标点击')
            dx=640-local[0];dy=350-local[1]
            # One axis at a time keeps map registration and edge handling clear.
            s,moved=self.forest_pan(s,dx if abs(dx)>abs(dy) else 0,dy if abs(dy)>=abs(dx) else 0)
            if not moved:raise TaskBlocked('森林目标未进入可操作范围')
        raise TaskBlocked('森林目标定位未完成')

    def forest_collect(self,s):
        if not self.options['forest']['collect_resources']:return s
        self.b.guard(s)
        if not is_forest_map(s):raise TaskBlocked('收取前森林地图未确认')
        if not forest_collect_ready(self.b,s):return s
        for attempt in range(3):
            fresh=self.observe();self.b.guard(fresh)
            if forest_collect_ready(self.b,fresh):break
            if attempt==0:self.note('森林收取按钮正在变化，重新识别后再操作（最多3次）')
            if attempt<2:self.b.sleep(.5)
        else:
            if is_forest_map(fresh):
                self.note('森林地图已确认，当前没有可收取资源，继续探索')
                return fresh
            raise TaskBlocked('森林收取前页面连续3次未确认，保留现场')
        self.b.click_at(fresh,(1233,575),['^黑暗森林$','^信息$'],'免费收取已探索森林资源')
        for _ in range(8):
            reward=self.observe();self.b.guard(reward)
            if reward.has('^获得奖励$','点击空白位置关闭'):break
            self.b.sleep(.5)
        else:raise TaskBlocked('森林资源收取结果未确认，未重复点击')
        rows=self.report.setdefault('forest_rewards',[]);rows.append({'text':reward.text})
        self.b.save_screen(reward,self.report['folder']/f'forest-reward-{len(rows)}.png')
        self.b.click_at(reward,(640,620),['^获得奖励$','点击空白位置关闭'],'关闭森林收获奖励')
        self.note('森林已收取一批资源');return self.forest_wait_map()

    def forest_wait_detail(self,name=None):
        for _ in range(10):
            s=self.observe();self.b.guard(s);actual=forest_detail(s)
            if actual:
                if name is not None and name!=actual:raise TaskBlocked('森林凶兽目标改变')
                return s
            self.b.sleep(.5)
        failures=self.report.setdefault('forest_detail_failures',[])
        path=self.report['folder']/f'forest-detail-unrecognized-{len(failures)+1}.png'
        self.b.save_screen(s,path)
        failures.append({'name':name,'screenshot':str(path)})
        raise TaskBlocked('森林节点详情未识别，未挑战或使用燃火')

    def forest_challenge(self,s,node):
        self.check_budget('forest');self.b.click_at(s,node.point,['^黑暗森林$','^信息$','^挑战$'],'挑战已重新识别的森林凶兽')
        detail=self.forest_wait_detail();name=forest_detail(detail);won=False
        for team in team_order(self.options['forest']):
            self.check_budget('forest')
            if detail is None:
                s=self.forest_wait_map();s,current=self.forest_reach(s,node)
                self.b.click_at(s,current.point,['^黑暗森林$','^信息$','^挑战$'],'重新进入原森林凶兽');detail=self.forest_wait_detail(name)
            detail=self.select_team(detail,team,return_page=lambda:self.forest_wait_detail(name))
            verify_free_forest(self.b,detail,name);self.check_budget('forest')
            self.start_challenge('forest',detail,'森林凶兽免费挑战',lambda q:verify_free_forest(self.b,q,name))
            try:result=self.battle('森林凶兽免费挑战');outcome='victory'
            except FightLost as lost:result=lost.screen;outcome='failed'
            self.report.setdefault('team_attempts',[]).append({'task':'forest','team':team,'outcome':outcome,'target':name})
            self.note(name+('胜利' if outcome=='victory' else '未通过')+(f'（队伍{team}）' if team else ''))
            self.b.save_screen(result,self.report['folder']/f'forest-battle-{self.task_counts.get("forest",0)}.png')
            self.checkpoint();self.exit_result(result);s=self.forest_wait_map()
            if outcome=='victory':won=True;break
            detail=None
        if not won:self.note('该凶兽所选阵容均未通过，本轮跳过此节点')
        self.forest_ignored.append(node.world)
        self.forest_pool=[n for n in self.forest_pool if math.dist(n.world,node.world)>32]
        return s

    def forest_explore(self,s,node):
        before=forest_points(self.b,s);reserve=self.options['forest']['reserve_points']
        if before-node.cost<reserve:raise BudgetReached('探索点不足以支付目标费用并保留设置数量')
        fresh=self.observe();self.b.guard(fresh)
        self.forest_record_view(fresh)
        if getattr(self,'forest_waiting',False):return fresh
        same=[n for n in forest_nodes(self.b,fresh) if n.kind==node.kind and n.action=='explore' and
              n.cost==node.cost and math.dist(n.point,node.point)<12]
        if not same:
            recovered=recover_forest_node(self.b,fresh,node.point,node)
            if recovered:same=[recovered]
        if not same:raise TaskBlocked('探索前节点或费用改变，未点击')
        if forest_points(self.b,fresh)!=before:raise TaskBlocked('探索前点数改变，未点击')
        n=same[0]
        self.note(f'探索{LABELS[n.kind]}，消耗{n.cost}点，当前{before}点，保留{reserve}点')
        serial=len(self.report.get('forest_explorations',[]))+1
        self.b.save_screen(fresh,self.report['folder']/f'forest-explore-{serial}-before.png')
        self.b.click_text(fresh,'^开始探索$',(n.point[0]-55,n.point[1]-22,110,44))
        record={'kind':n.kind,'cost':n.cost,'before':before,'status':'started','point':list(n.point)}
        self.report.setdefault('forest_explorations',[]).append(record)
        revealed_frames=0
        for _ in range(10):
            q=self.observe();self.b.guard(q)
            if is_forest_map(q):
                after=forest_points(self.b,q)
                confirmation='points' if after==before-node.cost else None
                # The latest real run revealed a reward while the balance stayed
                # at 6. Confirm the actual node twice instead of replaying input
                # or assuming that an unchanged balance means the click failed.
                if after==before and forest_reward_at(q,n.point):
                    shift=forest_shift(fresh,q)
                    if shift is not None and math.hypot(*shift)<=4:
                        revealed_frames+=1
                        if revealed_frames>=2:confirmation='reward'
                    else:revealed_frames=0
                else:revealed_frames=0
                if confirmation:
                    record.update(after=after,status='confirmed',confirmation=confirmation)
                    self.resource_spent('forest','探索点',node.cost if confirmation=='points' else None,after)
                    if confirmation=='reward':
                        self.note(f'原节点已连续确认变为奖励，探索点仍为{after}；继续其他节点，本次实际扣点未核实')
                    self.forest_ignored.append(node.world)
                    self.forest_pool=[old for old in self.forest_pool if math.dist(old.world,node.world)>32]
                    self.b.save_screen(q,self.report['folder']/f'forest-explore-{len(self.report["forest_explorations"])}.png')
                    self.checkpoint()
                    self.forest_record_view(q)  # Timers block exploration, not free battles.
                    return q
                if after!=before:
                    self.resource_spent('forest','探索点',None,after)
                    raise SafetyStop('森林探索点变化与确认费用不符，停止后续探索')
            else:revealed_frames=0
            self.b.sleep(.5)
        raise TaskBlocked('探索启动结果或探索点消耗未确认，保留现场')

    def forest_simple_pan(self,s,dx,dy):
        self.b.guard(s)
        if not is_forest_map(s):raise TaskBlocked('普通模式拖动前森林地图未确认')
        before=forest_points(self.b,s)
        if dx:
            start=(450 if dx>0 else 850,100);end=(start[0]+dx,100)
        else:
            y=190 if dy>0 else 550
            nodes=forest_nodes(self.b,s)
            x=next((x for x in (640,420,850,300,1000)
                    if all(math.dist((x,y),(n.point[0],n.point[1]-25))>90 for n in nodes)),None)
            if x is None:raise TaskBlocked('普通模式没有可安全起拖的空白区域')
            start=(x,y);end=(x,y+dy)
        self.b.audit({'action':'swipe','reason':'普通模式寻找森林节点','from':list(start),'to':list(end),'status':'requested'})
        sent=self.b.wait(self.b.controller.post_swipe(*start,*end,1100)).succeeded
        self.b.sleep(.8);q=self.forest_wait_map();self.forest_record_view(q)
        after=forest_points(self.b,q)
        if after!=before:raise SafetyStop('森林拖动后探索点改变，已保留现场，未重复拖动')
        moved=simple_forest_view_changed(s,q)
        if not sent and not moved:raise TaskBlocked('普通模式拖动未生效，准备退出森林后重新进入')
        return q,moved

    def forest_simple_reenter(self,error):
        rows=self.report.setdefault('forest_simple_recoveries',[])
        attempt=len(rows)-getattr(self,'_forest_simple_recovery_start',0)+1
        if attempt>3:raise TaskBlocked('森林普通模式退出重进3次后仍未恢复：'+str(error))
        rows.append({'attempt':attempt,'reason':str(error),'status':'started','instance_id':self.report_key('forest')})
        self.note(f'森林普通模式遇到异常，退出重进（{attempt}/3）：{error}')
        self.checkpoint();self.home();s=self.forest_map()
        self.forest_offset=[0.,0.];self.forest_pool=[];self.forest_ignored=[]
        self.forest_record_view(s)
        # A delayed exploration may have succeeded before re-entry. Account
        # for its actual balance instead of replaying its old click.
        pending=self.instance_rows('forest_explorations')
        if pending and pending[-1].get('status')=='started':
            row=pending[-1];after=forest_points(self.b,s)
            if after==row['before']-row['cost']:
                row.update(status='confirmed',after=after,confirmation='reentry_points')
                self.resource_spent('forest','探索点',row['cost'],after)
            elif after!=row['before']:
                raise SafetyStop('森林重进后探索点与未结算节点费用不符，保留现场')
        rows[-1]['status']='reentered';self.checkpoint()
        return s

    def forest_simple_search(self,s,state,ignored):
        """Yield at the first actionable page; resume the sweep after clearing it."""
        while state['phase']!='done':
            phase=state['phase']
            dx,dy={'left':(400,0),'top':(0,360),'row':(state['direction'],0),'down':(0,-360)}[phase]
            s,moved=self.forest_simple_pan(s,dx,dy);ignored.clear()
            state['steps']+=1
            self.report['forest_simple_scanned_pages']=self.report.get('forest_simple_scanned_pages',0)+1
            if moved:
                state['leg']+=1
                if state['leg']>15:raise TaskBlocked('森林普通模式连续拖动仍未确认地图边界')
            else:
                state['leg']=0
                state['phase']={'left':'top','top':'row','row':'down','down':'done'}[phase]
                if phase=='down':state['phase']='done'
            if phase=='down' and moved:
                state['direction']=-state['direction'];state['phase']='row';state['leg']=0
            if state['steps']>180:raise TaskBlocked('森林普通模式本轮拖图仍未完成，准备重进恢复')
            balance=forest_points(self.b,s)
            self.forest_record_view(s)
            node=pick_simple_forest_node(forest_nodes(self.b,s),balance,self.options['forest']['reserve_points'],ignored,
                allow_exploration=not self.forest_exploration_stop(balance))
            if node is not None:return s,node
        return s,None

    def forest_simple(self):
        """Find a visible page, clear its instant nodes, and recover by re-entry."""
        reason='';ignored=[]
        self._forest_simple_recovery_start=len(self.report.get('forest_simple_recoveries',[]))
        def sweep():return {'phase':'left','direction':-400,'steps':0,'leg':0}
        def recover(error):
            if isinstance(error,ResourceReadError):raise error
            while True:
                try:return self.forest_simple_reenter(error)
                except (BudgetReached,ResourceReadError):raise
                except TaskBlocked as retry:
                    if len(self.report.get('forest_simple_recoveries',[]))-self._forest_simple_recovery_start>=3:raise
                    error=retry
        state=sweep();progress=0;pass_start=0
        try:
            try:s=self.forest_map()
            except BudgetReached:raise
            except TaskBlocked as e:s=recover(e)
            overview=getattr(self,'forest_overview_state','')
            if forest_overview_busy(overview):
                self.forest_waiting=True
                self.report['forest_waiting']={'overview':overview}
            while True:
                try:
                    self.b.check_stop();self.forest_record_view(s)
                    s=self.forest_collect(s);self.forest_record_view(s)
                    balance=forest_points(self.b,s)
                    reserve=self.options['forest']['reserve_points']
                    node=pick_simple_forest_node(forest_nodes(self.b,s),balance,reserve,ignored,
                        allow_exploration=not self.forest_exploration_stop(balance))
                    if node is None:s,node=self.forest_simple_search(s,state,ignored)
                    if node is None:
                        if progress>pass_start:
                            state=sweep();pass_start=progress;continue
                        reason=self.forest_exploration_stop(balance) or f'已拖图查找，未找到可探索节点（剩余{balance}点）';break
                    node.world=node.point
                    if node.action=='challenge':
                        attempts=len(self.task_attempts('forest'))
                        s=self.forest_challenge(s,node)
                        progress+=sum(row.get('outcome')=='victory' for row in self.task_attempts('forest')[attempts:])
                    else:
                        before=len(self.instance_rows('forest_explorations'))
                        s=self.forest_explore(s,node);progress+=len(self.instance_rows('forest_explorations'))-before
                    ignored.append(node.point)
                except BudgetReached:raise
                except TaskBlocked as e:
                    s=recover(e)
                    state=sweep();ignored.clear();pass_start=progress
        except BudgetReached as e:reason=str(e)
        self.home()
        started=len(self.instance_rows('forest_explorations'));rewards=len(self.instance_rows('forest_rewards'))
        return f'森林探索{started}个节点，收获{rewards}批资源；{reason}'

    def forest(self):
        self.active_task='forest';self.forest_offset=[0.,0.];self.forest_pool=[];self.forest_ignored=[];self.forest_waiting=False
        if self.options['forest'].get('mode','advanced')=='simple':return self.forest_simple()
        reason='';scanned=False
        try:
            s=self.forest_map()
            # A timer blocks new exploration, while free challenges stay available.
            overview=getattr(self,'forest_overview_state','')
            if re.search(r'探索中|正在探索|\d{2}:\d{2}:\d{2}',overview):
                self.resource_balance('forest','探索点',forest_points(self.b,s))
                self.forest_waiting=True
                self.report['forest_waiting']={'overview':overview}
            self.forest_record_view(s);s=self.forest_collect(s)
            while True:
                self.b.check_stop();self.forest_record_view(s)
                balance=forest_points(self.b,s)
                if not scanned:s=self.forest_scan(s);scanned=True;balance=forest_points(self.b,s)
                target=select_forest_node(self.forest_pool,self.options['forest'],balance,
                    waiting=bool(self.forest_exploration_stop(balance)))
                if target is None:
                    reason=self.forest_exploration_stop(balance) or '当前森林没有符合勾选类型及可用点数的可到达节点'
                    break
                if target.action=='explore':
                    maximum=self.options['forest']['max_explorations']
                    count=len(self.instance_rows('forest_explorations'))
                    if maximum and count>=maximum:reason='达到设置的探索节点上限';break
                    if (self.options['forest']['strategy']=='overflow' and balance-self.options['forest']['reserve_points']>1 and
                            target.kind not in INSTANT_KINDS):
                        self.note('暂无已确认可立即完成的可达节点，按完整优先级选择；出现计时后只处理免费挑战')
                try:s,target=self.forest_reach(s,target)
                except TaskBlocked as e:
                    # A node near the map boundary can never enter the operable
                    # band. Skip it and try the next candidate; only failures
                    # specific to this node are skippable, map/input failures
                    # still stop the task.
                    if not re.search('未进入可操作范围|定位未完成|连续3次重试仍未确认',str(e)):raise
                    self.forest_ignored.append(target.world)
                    self.forest_pool=[n for n in self.forest_pool if math.dist(n.world,target.world)>32]
                    self.report.setdefault('forest_skipped',[]).append(
                        {'kind':target.kind,'action':target.action,'cost':target.cost,
                         'world':list(target.world),'reason':str(e)})
                    self.note('森林目标无法进入可操作范围，已跳过该节点，尝试下一个：'+str(e))
                    s=self.forest_wait_map();continue
                if target.action=='challenge':s=self.forest_challenge(s,target)
                else:s=self.forest_explore(s,target)
                s=self.forest_collect(s)
        except BudgetReached as e:reason=str(e)
        self.home()
        started=len(self.instance_rows('forest_explorations'));rewards=len(self.instance_rows('forest_rewards'))
        return f'森林探索{started}个节点，收获{rewards}批资源；{reason}'


def verify_free_forest(b,s,name):
    b.guard(s)
    if forest_detail(s)!=name:raise TaskBlocked('森林凶兽身份未确认')
    if re.search(r'\d|消耗|购买|钻石',s.region_text((960,590,275,90))):
        raise SafetyStop('森林挑战按钮出现费用，未挑战')
    if not b.match_template(s,'forest-free-challenge.png',[960,590,270,80],.9):
        raise TaskBlocked('森林免费挑战按钮未确认，未使用燃火')
