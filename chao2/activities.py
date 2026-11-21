"""Configurable activities. Every transition checks a newly observed game page."""
import math
import re
import time
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from .configuration import COCOON_CARDS,COCOON_DAILIES,STAMINA_TASKS,team_order,selected_rows,limit_reached,run_team_plan
from .policy import TaskBlocked,SafetyStop,UserStopped,FightLost,EncounterInterrupted,ChallengeLocked,PageChanged,parse_ratio,friend_allowed,can_claim_stamina
from .world_events import is_map_choice,map_choice_controls,map_choice_main_target,map_choice_hunt_target
from .event_hub import event_hub_anchors,activity_entry,activity_availability
from .team_copy import source_lineup,copied_lineup,is_saved_team_list,saved_team_anchors,saved_team_copy_target,is_tribe_formation
from .team_copy import tribe_troop_deployed
from .tribe_totems import totem_identity,totem_nodes,TOTEM_REWARD
from .cocoon_settings import cocoon_reserve
from .team_switch import suppression_team_switch_dialog
from .control_retry import retry_point
from .screen_loading import loading_spinner

class BudgetReached(TaskBlocked): pass
class ResourceReserveReached(BudgetReached): pass
class MainRetryUnavailable(TaskBlocked): pass

DUNGEON_RESOURCES={'tower':('reserve_feathers','浮空羽毛'),'cocoon':('reserve_spikes','永生尖刺'),
                   'tribe':('reserve_orders','部落战令')}

# The client week cap was observed at 1000 (950 -> 970 -> 990 -> 1000).
# A readable quota AND a positive coin reward are both required before a friend fight.
FRIEND_WEEK_CAP=1000
STAMINA_CLAIM=r'^(?:领取|免费领取|领取奖励)$'
HUNT_BATCH_SIZE=3
HUNT_STAMINA_COST=10
HUNT_FORMATION_BUTTON_ROI=(765,590,180,85)
SECRET_NODE_PATTERN=r'^塔中秘庭[1-9]\d{0,2}$'
FORMATION_HEADER_ROI=(45,0,230,65)

def formation_layout(s):
    return bool(s.find('^排阵$',FORMATION_HEADER_ROI) and
                s.find(r'^队伍[1-9]$|浮空巨塔|永生之茧|进击巨物|狩猎|异象|秘庭|部落冒险|黑暗森林|[凿幽]星裂痕',
                       (890,60,250,70)))

def encounter_identity(screen):
    # Names and power live below the top resource bar; the timer is to their right.
    return re.sub(r'\s+','',screen.region_text((125,125,390,40)))

def tribe_identity(screen):
    word=screen.find(r'^冒险关卡\s*[0-9Il|\[\]]{1,5}$',roi=(25,115,500,65))
    if not word:return totem_identity(screen)
    number=re.sub(r'^冒险关卡\s*','',word.text).translate(str.maketrans({'I':'1','l':'1','|':'1','[':'1',']':'1'}))
    return '冒险关卡'+str(int(number)) if number.isdigit() and int(number)>0 else None


def is_tribe_detail(s):
    return bool(tribe_identity(s) and enemy_formation(s) and s.has('^排阵$','^挑战$') and
                s.find('通关奖励.*拍卖.*共享奖励|'+TOTEM_REWARD,(0,535,520,65)))

def enemy_formation(s):
    # The leftmost 敌 is occasionally missed. Accept that one omission only
    # in the fixed heading slot and with the tribe's distinct reward layout.
    word=s.find('^敌方阵容$')
    if word:return word
    # Tower secret details sometimes merge the five formation markers into
    # the heading ("敌方阵容1234)5"). This is still the same fixed heading,
    # not a loading screen. Keep the fallback confined to its title area.
    word=s.find(r'^敌方阵容[1-5()（）\s]+$',(750,75,450,85))
    if word:return word
    # A secret-room OCR frame can append stray Latin letters and digits from
    # the five formation markers (e.g. "敌方阵容Q1023)4"). Require the secret
    # title, first-clear reward and both action buttons before accepting it.
    if s.find(r'^塔中秘庭\d+$',(150,80,550,80)) and s.has('首通奖励','^排阵$','^挑战$|^前往挑战$'):
        word=s.find(r'^敌方阵容[0-9A-Za-z()（）\s]{1,16}$',(750,75,450,85))
        if word:return word
    # Cocoon's red formation heading can merge with its numbered tabs as
    # "敌方阵容Q1". Its dim top title is unreliable; verify the complete
    # monster-detail layout instead of guessing that title or dropping anchors.
    if (s.find('^排阵$',(765,590,180,85)) and
            s.find('^(?:前往)?挑战$',(960,590,280,85)) and
            s.find('^可获得奖励$',(15,540,240,55)) and
            s.find('^通关录像$',(520,115,200,65)) and
            not s.find('^退出$|^获得奖励$|^请选择$')):
        word=s.find(r'^敌方阵容[1-5QqOo0()（）\s]{1,8}$',(1010,115,255,75))
        if word:return word
    if tribe_identity(s) and s.find('通关奖励.*拍卖.*共享奖励|'+TOTEM_REWARD,(0,535,520,65)):
        return s.find('^方阵容$',(1080,115,200,80))
    return None

def is_tribe_map(screen):
    return bool(screen.find('^部落$',roi=(80,0,220,65)) and
                screen.find('^部落大厅$',roi=(1080,590,200,115)) and
                not screen.find('^(?:敌)?方阵容$|^配置$|^是否确认退出游戏$') and
                not is_tribe_reward_overlay(screen))


def is_tribe_reward_overlay(screen):
    """A delayed free reward can cover the map after battle result exit."""
    return bool(screen.find('^部落$',roi=(80,0,220,65)) and
                screen.find('^获得奖励$',roi=(450,80,400,140)) and
                not screen.find('^退出$'))


def formation_power(text):
    # Only used in the isolated numeric power field. The slanted final 1 is
    # regularly recognized as I/|; never extract digits out of arbitrary text.
    text=text.strip()
    if not re.fullmatch(r'[0-9OolI|]{4,8}',text):return None
    return int(text.translate(str.maketrans({'O':'0','o':'0','I':'1','l':'1','|':'1'})))

def is_exploration_rewards(s):
    # Exploration uses a scrollable "奖励" summary with a top-right X,
    # rather than the normal "获得奖励 / 点击空白位置关闭" overlay.
    return bool(s.find('^探索$',roi=(900,0,210,70)) and
                s.find('^奖励$',roi=(540,65,190,65)))

def is_exploration_menu(s):
    return bool(s.find('^探索$',roi=(900,0,210,70)) and s.find('剩余可指派怪兽') and
                not is_exploration_rewards(s) and
                not s.find('^获得(?:奖励|物品)$',roi=(400,70,500,160)))

def exploration_capacity(s):
    return parse_ratio(s.region_text((900,65,255,48)))


def exploration_card_point(title):
    # A partially visible last card can start at y=584. Its former +70
    # target landed below the list and closed it; stay inside the card viewport.
    return (1000,min(625,title.center[1]+35))


def exploration_card_running(s,title):
    return bool(s.find(r'^\d{1,2}:\d{2}:\d{2}$',(860,title.center[1]+10,230,65)))


def stamina_servings(s):
    if not s.find('^每日三发$',roi=(500,80,400,100)) or not s.find('^领取奖励$',roi=(600,560,260,90)):
        return None
    count=0
    for x in (628,725,821):
        a=s.image[515:540,x-12:x+13].astype('int16')
        b,g,r=(a[:,:,i] for i in range(3))
        gold=(r>220)&(g>160)&(b<220)&(r>b+20)
        count+=int(gold.mean()>.25)
    return count

def tribe_map_moved(before,after):
    import numpy as np
    a=before.image[100:550,280:1150].astype('int16')
    b=after.image[100:550,280:1150].astype('int16')
    # Ignore small animated glows while recognizing a clamped map edge.
    return np.mean(np.max(np.abs(a-b),axis=2)>32)>.08

def tribe_nodes(screen):
    """Animated red sword badge above a glowing yellow node; no fixed map coords."""
    import numpy as np
    im=screen.image;b,g,r=(im[:,:,i].astype('int16') for i in range(3))
    mask=(r>180)&(g<135)&(b<155)&(b>g*.8)&(r-g>70)&(r-b>60)
    mask[:90,:]=False;mask[550:,:]=False;mask[:,:80]=False;mask[:,1180:]=False
    # The white sword pulse splits the red badge into several components.
    # Join nearby fragments for connectivity, but measure only original red
    # pixels and still require the white swords plus the yellow node below.
    # Horizontal bridging does not join the badge to the orb's red rim below.
    connected=mask.copy()
    for dx in range(1,6):
        connected[:,dx:]|=mask[:,:-dx];connected[:,:-dx]|=mask[:,dx:]
    seen=np.zeros(mask.shape,bool);found=[]
    for y,x in zip(*np.where(connected)):
        if seen[y,x]:continue
        stack=[(int(x),int(y))];seen[y,x]=True;xs=[];ys=[]
        while stack:
            px,py=stack.pop()
            if mask[py,px]:xs.append(px);ys.append(py)
            for nx,ny in ((px-1,py),(px+1,py),(px,py-1),(px,py+1)):
                if 0<=nx<1280 and 0<=ny<720 and connected[ny,nx] and not seen[ny,nx]:
                    seen[ny,nx]=True;stack.append((nx,ny))
        if not xs:continue
        left,right,top,bottom=min(xs),max(xs),min(ys),max(ys)
        width,height=right-left+1,bottom-top+1
        if not (140<=len(xs)<=2000 and 24<=width<=60 and 15<=height<=50):continue
        cx=(left+right)//2;cy=(top+bottom)//2
        badge=im[top:bottom+1,left:right+1]
        white=(badge[:,:,0]>180)&(badge[:,:,1]>180)&(badge[:,:,2]>215)
        orb=im[cy+22:cy+63,cx-24:cx+25]
        yellow=(orb[:,:,2]>220)&(orb[:,:,1]>170)&(orb[:,:,0]<190)
        if white.mean()>.04 and yellow.mean()>.24:
            point=(cx,cy+42)
            if all(math.dist(point,p)>20 for p in found):found.append(point)
    return sorted(found,key=lambda p:math.dist(p,(640,360)))

MAIN_BADGE_ROI=(25,115,100,90)


def recover_tower_detail(b,s):
    if s.find(r'^塔中秘庭\d+$',(150,80,550,80)):
        from .dungeon_labels import recover_secret_heading
        return recover_secret_heading(b,s)
    if (enemy_formation(s) or b.tasker is None or
            not s.find(r'浮空巨塔\s*\d+$|塔中秘庭\s*\d+$',(150,80,550,80)) or
            not s.has('^排阵$','^挑战$|^前往挑战$')):return s
    from .backend import Screen
    fresh=Screen(s.image,list(s.words),s.when)
    if b.confirm_label(fresh,'^敌方阵容$',(1010,85,180,80),scale=3,threshold=.8):return fresh
    return s


def main_identity(screen):
    # Only a complete number in the stage badge is an identity. Searching the
    # whole title accepted truncated OCR such as "7I2" as stage "7I".
    numbers={w.text.strip() for w in screen.words
             if MAIN_BADGE_ROI[0]<=w.center[0]<MAIN_BADGE_ROI[0]+MAIN_BADGE_ROI[2]
             and MAIN_BADGE_ROI[1]<=w.center[1]<MAIN_BADGE_ROI[1]+MAIN_BADGE_ROI[3]
             and re.fullmatch(r'\d{1,4}',w.text.strip())}
    return next(iter(numbers)) if len(numbers)==1 else None


def is_main_detail(s):
    # Completed nodes have no first-clear rewards. They still have the stage
    # badge, enemy formation, replay link and the same navigation controls.
    return bool(main_identity(s) is not None and main_detail_layout(s))


def main_detail_layout(s):
    return bool(s.find('^敌方阵容$',(1080,115,200,80)) and
                s.find('^排阵$',(750,585,220,95)) and
                s.find('^(?:前往)?挑战$',(965,585,275,95)) and
                s.find('首通奖励|通关录像|探索之锋') and
                not s.find('^退出$|^获得奖励$'))


def recover_main_detail(b,s):
    if b.tasker is None:return s
    from .backend import Screen,Word
    from .dungeon_labels import OVERLAY,REPLAY_LABEL,REPLAY_ROI,recover_heading
    if not main_detail_layout(s):
        if (not s.find('^排阵$',(750,585,220,95)) or
                not s.find('^(?:前往)?挑战$',(965,585,275,95)) or
                not s.find(REPLAY_LABEL,REPLAY_ROI) or
                not s.find('首通奖励|探索之锋') or s.find(OVERLAY)):return s
        # The same full-frame pass can miss both the badge and the red enemy
        # heading. Confirm the actual heading before recovering its number.
        heading=recover_heading(b,s,(1080,115,200,80))
        if not main_detail_layout(heading):return s
        s=heading
    reads=[b.read_text_crop(s,(35,135,80,45)).strip(),
           b.read_text_region(s,(30,132,90,50),scale=3,threshold=.8).strip()]
    identity=reads[0] if reads[0]==reads[1] and re.fullmatch(r'\d{1,4}',reads[0]) else None
    fresh=s
    if identity!=main_identity(s):
        x,y,w,h=MAIN_BADGE_ROI
        words=[word for word in s.words if not (x<=word.center[0]<x+w and y<=word.center[1]<y+h)]
        # Conflicting local reads invalidate this frame instead of retaining an
        # unverified full-frame digit. A later observation can recover it.
        if identity is not None:words.append(Word(identity,[35,135,80,45],.99))
        fresh=Screen(s.image,words,s.when)
    if (not is_main_detail(fresh) or fresh.find('^首通奖励$') or
            fresh.find('已通关|首通奖励已领取')):return fresh
    # Reward sparkles can split this small label into "首通" and "_".
    # Require the complete text from the reward region, keeping the first-
    # clear check intact for overview entry, map searches and battle retries.
    calibrated=Screen(fresh.image,list(fresh.words),fresh.when)
    if b.confirm_label(calibrated,'^首通奖励$',(30,550,100,40),scale=3,threshold=.8):return calibrated
    return fresh


def main_unlock_level(s):
    if not is_main_detail(s):return None
    word=s.find(r'^探索者等级\s*\d+\s*开启$',(965,625,275,65))
    return int(re.search(r'\d+',word.text)[0]) if word else None

def hunt_rows(screen):
    rows={w.center[1] for w in screen.words if w.text=='10'
          and 1040<w.center[0]<1140 and 185<w.center[1]<570}
    # With less than 10 stamina, the red cost can disappear from OCR. The
    # card's countdown still locates it; the actual cost is rechecked in detail.
    for word in screen.words:
        if (910<=word.box[0]<1140 and 185<word.center[1]<530 and
                re.search(r'\d{2}[:：]\d{2}[:：]\d{2}',word.text)):
            y=word.center[1]+42
            if not any(abs(y-old)<14 for old in rows):rows.add(y)
    return sorted(rows)

def giant_damage(screen):
    match=re.search(r'总伤害\s*[:：]?\s*(\d+)',screen.region_text((850,595,430,120)))
    return int(match[1]) if match else None

def is_giant_ready(s):
    # This is a separate solo/team lobby, not a normal enemy-lineup detail.
    return bool(s.find('^进击巨物$',(335,90,520,90)) and
                s.find('^玩法特色$',(350,190,310,85)) and
                s.find('^比拼方式$',(350,325,310,85)) and
                s.find('^排阵$',(790,585,205,95)) and
                s.find('^前往挑战$',(990,585,275,95)))

def giant_is_open(screen,now=None):
    match=re.search(r'(\d{2}):(\d{2})\s*[-—–]\s*(\d{2}):(\d{2})开启',screen.text)
    if not match:return None
    now=now or datetime.now(timezone(timedelta(hours=8)))
    minute=now.hour*60+now.minute
    start=int(match[1])*60+int(match[2]);end=int(match[3])*60+int(match[4])
    return start<=minute<end if start<=end else minute>=start or minute<end

def main_nodes(screen):
    """Locate orange pending map dots, excluding HUD/player models. Details still verify cost/reward."""
    import numpy as np
    im=screen.image
    b,g,r=(im[:,:,i].astype('int16') for i in range(3))
    mask=(r>220)&(g>105)&(g<211)&(b<135)&(r-g>38)
    mask[:80,:]=False;mask[:160,:430]=False;mask[580:,:]=False;mask[:,:100]=False;mask[:,1170:]=False
    seen=np.zeros(mask.shape,bool);found=[]
    for y,x in zip(*np.where(mask)):
        if seen[y,x]:continue
        stack=[(int(x),int(y))];seen[y,x]=True;xs=[];ys=[]
        while stack:
            px,py=stack.pop();xs.append(px);ys.append(py)
            for nx,ny in ((px-1,py),(px+1,py),(px,py-1),(px,py+1)):
                if 0<=nx<1280 and 0<=ny<720 and mask[ny,nx] and not seen[ny,nx]:
                    seen[ny,nx]=True;stack.append((nx,ny))
        width=max(xs)-min(xs)+1;height=max(ys)-min(ys)+1
        if 80<=len(xs)<=700 and 18<=width<=43 and 9<=height<=27 and 1.1<width/height<2.8:
            found.append(((min(xs)+max(xs))//2,(min(ys)+max(ys))//2))
    # Pending stages also use yellow dots under a red crossed-swords marker;
    # the old orange-only mask missed these after a defeat.
    import cv2
    from pathlib import Path
    for name in ('main-pending-swords.png','main-pending-swords-glow.png','main-pending-swords-pulse.png'):
        template=cv2.imread(str(Path(__file__).resolve().parents[1]/'resource/image'/name))
        if template is None:continue
        scores=cv2.matchTemplate(im[80:555,100:1170],template,cv2.TM_CCOEFF_NORMED)
        for _ in range(24):
            _,value,_,point=cv2.minMaxLoc(scores)
            if value<.8:break
            x,y=point;cx=x+100+template.shape[1]//2;cy=y+80+template.shape[0]//2+24
            if not (cx<430 and cy<160) and all(math.dist((cx,cy),old)>18 for old in found):found.append((cx,cy))
            scores[max(0,y-20):y+21,max(0,x-20):x+21]=0
    return sorted(found,key=lambda p:math.dist(p,(640,360)))


def main_map_shift(before,after):
    """Register map scenery only; HUD and walking monster models are excluded."""
    import cv2
    import numpy as np
    mask=np.zeros((720,1280),np.uint8);mask[160:550,110:1160]=255
    orb=cv2.ORB_create(nfeatures=1800)
    a,ad=orb.detectAndCompute(cv2.cvtColor(before.image,cv2.COLOR_BGR2GRAY),mask)
    b,bd=orb.detectAndCompute(cv2.cvtColor(after.image,cv2.COLOR_BGR2GRAY),mask)
    if ad is None or bd is None:return None
    pairs=cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(ad,bd,k=2)
    good=[p[0] for p in pairs if len(p)==2 and p[0].distance<.7*p[1].distance]
    if len(good)<18:return None
    src=np.float32([a[m.queryIdx].pt for m in good]);dst=np.float32([b[m.trainIdx].pt for m in good])
    matrix,inliers=cv2.estimateAffinePartial2D(src,dst,method=cv2.RANSAC,ransacReprojThreshold=2.5)
    if matrix is None or inliers.sum()<15:return None
    if abs(matrix[0,0]-1)>.012 or abs(matrix[1,1]-1)>.012 or abs(matrix[0,1])>.012:return None
    return float(matrix[0,2]),float(matrix[1,2])

def friend_quota(text):
    if re.search('本周.*(?:已达上限|已满)',text):return FRIEND_WEEK_CAP,FRIEND_WEEK_CAP
    match=re.search(r'本周已获[取得]友好点数\s*[:：]?\s*(\d+)(?:\s*/\s*(\d+))?',text)
    return (int(match[1]),int(match[2]) if match[2] else FRIEND_WEEK_CAP) if match else (None,None)

COPY_LIST_ANCHORS=('^异象$','本周已获[取得]友好点数')

def is_copy_list(s):
    return s.has(*COPY_LIST_ANCHORS) and not s.find('^敌方阵容$') and not is_map_choice(s)

def copy_rows(s):
    return sorted({w.center[1] for w in s.words if w.text=='20'
                   and 1020<w.center[0]<1140 and 250<w.center[1]<640})

def copy_fingerprint(s):
    # OCR often joins the countdown to a player's name. A ticking timer must
    # not make an unchanged last page look like more targets.
    names=[]
    for y in copy_rows(s):
        title=s.region_text((910,y-65,270,37))
        title=re.sub(r'\d{2}[:：]\d{2}[:：]\d{2}.*','',title)
        names.append(re.sub(r'[^\w\u4e00-\u9fff]','',title).rstrip('eo'))
    return tuple(names)

def next_tower_floor(screen):
    floors=[]
    for w in screen.words:
        if (re.fullmatch(r'0?\d{1,4}',w.text) and 240<w.center[0]<410 and
                45<w.center[1]<685 and w.box[1]+w.box[3]<=685):
            n=int(w.text)
            if n>0:floors.append((n,w.center[1]))
    completed=[]
    for tag in screen.words:
        if re.fullmatch('已?通关',tag.text) and 240<tag.center[0]<420:
            for n,y in floors:
                if 15<y-tag.center[1]<80:completed.append(n)
    if not floors:return None
    threshold=max(completed) if completed else 0
    if not completed and min(n for n,_ in floors)!=1:return None
    # Cloud/particle animations can hide a floor label from OCR. Never jump to
    # the next visible number: only the floor immediately after a cleared one
    # can be unlocked (the 166 -> missing 167 -> 168 case stopped the real run).
    return next(((n,y) for n,y in floors if n==threshold+1),None)

def secret_candidates(screen):
    return sorted({w.text for w in secret_nodes(screen)},key=lambda text:int(re.search(r'\d+',text)[0]))

def secret_nodes(screen):
    """Unlocked, unbeaten nodes glow even after the 'new' tag disappears."""
    found=[]
    for w in screen.words:
        if not re.fullmatch(SECRET_NODE_PATTERN,w.text):continue
        x,y=w.center
        if not (40<x<1240 and 180<y<700):continue
        core=screen.image[y-155:y-100,x-35:x+36].astype('int16')
        b,g,r=(core[:,:,i] for i in range(3))
        # Real captured locked/cleared nodes are dark; the dim entrance behind
        # this overlay must not be mistaken for a foreground challenge node.
        if ((b>210)&(g>185)&(r>100)&(b>=r-10)).mean()>.35:found.append(w)
    return found

def secret_locked_nodes(screen):
    """The gray padlock is distinct from the cyan core and red cleared slash."""
    found=[]
    for w in screen.words:
        if not re.fullmatch(SECRET_NODE_PATTERN,w.text):continue
        x,y=w.center
        if not (40<x<1240 and 180<y<700):continue
        core=screen.image[y-155:y-100,x-35:x+36].astype('int16')
        b,g,r=(core[:,:,i] for i in range(3))
        lock=(r>115)&(g>130)&(b>145)&(b<240)&(abs(b-r)<65)&(abs(r-g)<45)
        if lock.mean()>.28:found.append(w.text)
    return found

def is_tower_map(s):
    return bool(s.find('^浮空巨塔$',roi=(90,0,230,60)) and not s.find('敌方阵容|选择挑战的塔|^退出$'))

def is_tower_secret_list(s):
    return is_tower_map(s) and len([w for w in s.words if re.fullmatch(SECRET_NODE_PATTERN,w.text)])>=2

def tower_floor_number(s,kind):
    prefix='' if kind['id']=='normal' else re.escape(kind['label'])+r'\s*[-·－]?\s*'
    w=s.find('^'+prefix+r'浮空巨塔\s*(\d+)$',roi=(160,80,520,65))
    return int(re.search(r'(\d+)$',w.text)[1]) if w else None

class ConfiguredActivities:
    def close_exploration_rewards(self,s):
        self.b.guard(s)
        if not is_exploration_rewards(s):raise TaskBlocked('探索奖励汇总未确认')
        self.b.save_screen(s,self.report['folder']/'exploration-rewards.png')
        self.note('探索奖励已显示，关闭汇总并核对指派列表')
        for attempt in range(2):
            # Retry dismissal only after several fresh frames still show this
            # exact summary. Never replay a close against a changed page.
            self.b.click_at(s,(884,100),['^奖励$','^探索$'],'关闭探索奖励汇总')
            for _ in range(4):
                q=self.observe();self.b.guard(q)
                if is_exploration_menu(q):
                    self.b.save_screen(q,self.report['folder']/'exploration-after-rewards.png')
                    self.report['exploration_reward_summaries_closed']=self.report.get('exploration_reward_summaries_closed',0)+1
                    return q
                self.b.sleep(.5)
            if not is_exploration_rewards(q):break
            s=q
            if attempt==0:self.note('探索奖励汇总仍在，重新确认后再关闭一次')
        raise TaskBlocked('关闭探索奖励后未返回探索列表')

    def exploration(self):
        s=self.enter_overview('^探索指派$');collected=0;started=0;assigned=0
        for _ in range(6):
            self.b.guard(s)
            if not is_exploration_menu(s):raise TaskBlocked('探索列表未识别')
            before=exploration_capacity(s)
            if not before:raise TaskBlocked('探索剩余指派数量未识别')
            self.report['exploration']={'idle':before[0],'capacity':before[1],
                'collected_batches':collected,'started_monsters':started,'auto_assigned':assigned}
            if s.find('^全部领取$'):
                self.b.click_text(s,'^全部领取$');q=self.observe()
                if is_exploration_rewards(q):
                    q=self.close_exploration_rewards(q);collected+=1
                elif q.find('获得奖励|获得物品') and not is_exploration_menu(q):
                    self.b.click_at(q,(640,675),['获得奖励|获得物品'],'关闭探索奖励')
                    collected+=1;q=self.observe()
                if not is_exploration_menu(q):raise TaskBlocked('探索领奖后页面未识别')
                s=q
            if s.find('^全部开始探索$'):
                before=exploration_capacity(s)
                if before is None:raise TaskBlocked('探索指派余额未识别')
                self.b.click_text(s,'^全部开始探索$');q=self.observe()
                if is_exploration_menu(q):
                    after=exploration_capacity(q)
                    if after is None:raise TaskBlocked('开始探索后指派余额未识别')
                    if after[0]<before[0]:
                        self.b.save_screen(q,self.report['folder']/'exploration-started.png')
                        self.note(f'探索新增指派{before[0]-after[0]}只，空闲{after[0]}/{after[1]}')
                        started+=before[0]-after[0];s=q;continue
                s=q
            if is_exploration_menu(s):
                capacity=exploration_capacity(s)
                if capacity and capacity[0]==0:
                    self.report['exploration'].update(idle=0,collected_batches=collected,started_monsters=started,auto_assigned=assigned)
                    self.home();return f'探索已领取{collected}批，新增指派{started}只，空闲0/{capacity[1]}'+('；没有待领取奖励，名额均在探索中' if collected==0 and started==0 else '')
                # Inspect each area's actual detail only when the bulk action
                # leaves idle monsters. Never cancel an expedition in progress.
                s,count=self.exploration_assign_idle(s);assigned+=count
                after=exploration_capacity(s) if is_exploration_menu(s) else None
                if capacity and after and after[0]<capacity[0]:started+=capacity[0]-after[0]
                if count:continue
                self.report['exploration'].update(collected_batches=collected,started_monsters=started,auto_assigned=assigned)
                scan=self.report.get('exploration_scan',{})
                if scan.get('complete') and scan.get('areas') and scan.get('areas')==scan.get('running'):
                    idle=after[0] if after else capacity[0]
                    self.report['exploration']['idle']=idle
                    self.home()
                    return f'探索已领取{collected}批，新增指派{started}只；当前{scan["areas"]}个探索区均在倒计时，剩余{idle}个名额暂无可派区域'
                raise TaskBlocked(f'探索仍有{capacity[0] if capacity else "未知"}个空闲名额，未确认可指派入口，保留截图')
            raise TaskBlocked('探索自动指派出现未识别页面，保留现场')
        raise TaskBlocked('探索状态未稳定，停止重复领取或开始')

    def exploration_assign_idle(self,s):
        seen=set();running=set();assigned=0;complete=False
        for page in range(16):
            if not is_exploration_menu(s):raise TaskBlocked('补派前探索列表未确认')
            rows=[w for w in s.words if 815<=w.box[0]<=850 and 195<=w.center[1]<605 and len(w.text)>=3]
            names=[w.text for w in rows if w.text not in seen]
            for name in names:
                s=self.observe()
                if not is_exploration_menu(s):raise TaskBlocked('补派时探索列表改变')
                title=s.find('^'+re.escape(name)+'$',roi=(815,190,300,430))
                if not title:continue
                seen.add(name)
                if exploration_card_running(s,title):
                    running.add(name);continue
                self.b.click_at(s,exploration_card_point(title),['^探索$','剩余可指派怪兽'],'查看探索区域：'+name)
                q=self.observe();self.b.guard(q)
                if not q.has('种族限定','可获得奖励'):raise TaskBlocked('探索区域详情未识别')
                was_running=bool(q.find('取消探索'))
                if not q.find('取消探索') and q.find('一键上阵|一键放入|一键指派'):
                    self.b.click_text(q,'一键上阵|一键放入|一键指派');q=self.observe()
                if not q.find('取消探索') and q.find('^开始探索$'):
                    self.b.click_text(q,'^开始探索$');q=self.observe()
                if q.find('取消探索'):
                    running.add(name)
                    if not was_running:assigned+=1
                if q.has('种族限定','可获得奖励'):
                    self.b.click_at(q,(1154,106),['种族限定','可获得奖励'],'关闭探索详情')
                s=self.observe()
                if not is_exploration_menu(s):raise TaskBlocked('探索补派后未返回列表')
                capacity=exploration_capacity(s)
                if capacity is not None and capacity[0]==0:return s,assigned
            if not names and page>0:complete=True;break
            self.b.guard(s);self.b.wait(self.b.controller.post_swipe(1030,575,1030,250,700));self.b.sleep(1.2);s=self.observe()
        self.report['exploration_scan']={'complete':complete,'areas':len(seen),'running':len(running),'names':sorted(seen)}
        return s,assigned

    def await_detail(self,timeout=35,*,hunt_target=None):
        until=time.monotonic()+timeout
        retry_at=time.monotonic()+8;retried=0
        while time.monotonic()<until:
            s=self.observe();self.b.guard(s)
            self.resolve_path_event(s)
            if self.active_task=='main' and is_map_choice(s):s=self.open_main_choice(s)
            if self.active_task=='hunt' and is_map_choice(s):s=self.open_hunt_choice(s)
            if self.active_task=='main':
                from .reward_collection import is_map_story
                if is_map_story(s):s=self.close_map_story(s)
            if self.active_task=='main' and main_unlock_level(s) is not None:return s
            if (enemy_formation(s) and s.find('^排阵$') and
                    (self.active_task!='hunt' or not loading_spinner(s))):
                return self.ensure_detail(s)
            if s.find('等级不足|需要.*级|尚未解锁'):raise TaskBlocked('目标尚未解锁')
            # A card click can leave the client on the map without opening its
            # encounter. Retry only that same pending slot on a fresh hunt list;
            # never replay search, challenge or another resource-consuming input.
            if (hunt_target is not None and self.active_task=='hunt' and
                    retried<3 and time.monotonic()>=retry_at and
                    self.retry_hunt_navigation(s,hunt_target,retried+1)):
                retried+=1;retry_at=time.monotonic()+8
            self.b.sleep(1)
        if retried:raise TaskBlocked(f'狩猎寻路或打开关卡未完成，已重新定位同一猎物{retried}次；保留现场')
        raise TaskBlocked('寻路或打开关卡未完成，保留现场')

    def retry_hunt_navigation(self,s,target,attempt):
        if s.find('^请选择$|^获得.*|^领取$|^确认$|^取消$|^提示$|^排阵$|^退出$'):return False
        if not (parse_ratio(s.region_text((490,0,170,65))) and
                s.find('^狩猎$',(900,0,240,75)) and
                s.find('^商店$',(1000,65,200,80)) and s.find('^传送$',(1200,315,80,85))):return False
        expected,index=target;rows=hunt_rows(s)
        if len(rows)!=expected or not 0<=index<len(rows):
            raise TaskBlocked('寻路期间猎物已离开或列表改变，未重新定位其他猎物')
        self.navigation_retry('狩猎关卡尚未打开，重新定位同一猎物',attempt,s)
        self.b.click_at(s,(1000,rows[index]-35),['^狩猎$','^商店$','^传送$'],'重新定位同一猎物')
        return True

    def open_main_choice(self,s):
        row=map_choice_main_target(s)
        if row is None:raise TaskBlocked('重叠目标中未确认主线关卡，未点击复制体')
        self.b.click_at(s,row.center,['^请选择$',re.escape(row.text)],'选择重叠位置的主线关卡')
        for _ in range(12):
            q=self.observe();self.b.guard(q);self.resolve_path_event(q)
            if q.has('敌方阵容','^排阵$'):return q
            if not is_map_choice(q):return q
            self.b.sleep(.5)
        raise TaskBlocked('重叠主线选项点击后尚未打开，未重复点击')

    def open_hunt_choice(self,s):
        row=map_choice_hunt_target(s)
        if row is None:raise TaskBlocked('重叠目标中未确认唯一狩猎选项，保留现场')
        self.b.click_at(s,row.center,['^请选择$','^狩猎$'],'选择重叠位置的狩猎目标')
        return self.wait_for_screen(lambda q:not is_map_choice(q),'重叠狩猎选项关闭',timeout=3)

    def check_budget(self,task):
        self.b.check_stop()
        if self.battles>=self.limit:raise BudgetReached('达到本轮战斗上限')
        if limit_reached(self.options[task].get('max_runs',0),self.task_counts.get(task,0)):
            raise BudgetReached('达到该玩法设置的挑战次数')

    def back_detail(self,s):
        heading=enemy_formation(s)
        if not heading:raise TaskBlocked('返回前关卡详情未确认')
        self.b.click_at(s,(45,28),['^'+re.escape(heading.text)+'$'],'返回玩法')
        return self.observe()

    def ensure_detail(self,s):
        self.resolve_path_event(s)
        if not enemy_formation(s) or not s.find('^排阵$') or not s.find('^挑战$|^前往挑战$'):
            raise TaskBlocked('没有识别到可挑战关卡详情')
        if main_unlock_level(s) is not None or s.find('需要.*级|等级不足|尚未解锁|未解锁',roi=(100,70,1080,560)):
            raise TaskBlocked('该关卡尚未解锁')
        return s

    def formation_page(self,retry_detail=None):
        def ready(s):
            return formation_layout(s) or (self.active_task=='tribe' and is_tribe_formation(s))
        if retry_detail is not None:
            def retry(q):
                # Replay only while the same challenge detail is still open.
                # Never click a loading frame, a formation page or a new target.
                if not enemy_formation(q) or not q.has('^排阵$','^挑战$|^前往挑战$'):return
                if self.active_task=='tribe':
                    identity=tribe_identity(retry_detail)
                    if not identity or tribe_identity(q)!=identity:return
                elif self.active_task=='tower':
                    title=retry_detail.find(r'(?:塔中秘庭|浮空巨塔)\s*\d+$',roi=(150,75,560,90))
                    if not title or not q.find('^'+re.escape(title.text)+'$',roi=(150,75,560,90)):return
                elif self.active_task=='main':
                    identity=main_identity(retry_detail)
                    if not identity or main_identity(q)!=identity:return
                else:
                    identity=encounter_identity(retry_detail)
                    if not identity or encounter_identity(q)!=identity:return
                self.note('排阵页仍未打开，确认原关卡后重试点击排阵')
                self.b.click_text(q,'^排阵$')
            return self.wait_for_screen(ready,'排阵配置',timeout=4,retry_navigation=retry)
        for _ in range(16):
            s=self.observe();self.b.guard(s)
            if ready(s):return s
            self.b.sleep(.5)
        raise TaskBlocked('排阵配置尚未加载，保留现场')

    def open_hunt_formation(self,detail):
        challenge='^挑战$|^前往挑战$'
        identity=encounter_identity(detail)
        until=time.monotonic()+30
        clicks=0
        same_detail_reads=0
        while time.monotonic()<until:
            s=self.observe()
            self.b.guard(s)
            self.resolve_path_event(s)
            if loading_spinner(s) or s.find('^取消$|^确定$|^获得奖励$|^请选择$|^复制此配置$'):
                same_detail_reads=0
                self.b.sleep(.25)
                continue
            if formation_layout(s):return s

            button=s.find('^排阵$',HUNT_FORMATION_BUTTON_ROI)
            heading=enemy_formation(s)
            if ((clicks and not identity) or encounter_identity(s)!=identity or not button or not heading or
                    not s.find(challenge,(960,590,280,85))):
                same_detail_reads=0
                self.b.sleep(.25)
                continue
            same_detail_reads+=1
            # One lingering detail frame can precede a loading spinner.
            if clicks and same_detail_reads<2:continue
            if clicks==4:raise TaskBlocked('狩猎排阵补点3次后仍在原猎物详情，未开始挑战')
            if clicks:self.navigation_retry('仍在原猎物详情，补点排阵',clicks,s)
            self.b.click_at(s,retry_point(button,clicks),
                            ['^排阵$','^'+re.escape(heading.text)+'$',challenge],
                            '打开狩猎排阵',settle_delay=0)
            clicks+=1
            same_detail_reads=0
        raise TaskBlocked('狩猎排阵未确认，已停止本项')

    def open_detail_formation(self,detail):
        if self.active_task=='hunt':return self.open_hunt_formation(detail)
        self.b.click_text(detail,'^排阵$')
        return self.formation_page(retry_detail=detail)

    def select_team(self,detail,team,return_page=None):
        if team is None:return detail
        s=self.open_detail_formation(detail)
        s=self.apply_saved_team(s,team)
        header='^部队$' if self.active_task=='tribe' else '^排阵$'
        self.b.click_at(s,(45,28),[header],'返回关卡')
        return (return_page or self.await_detail)()

    def close_saved_team_list(self,s):
        from .backend import Word
        for attempt in range(4):
            if not is_saved_team_list(s):return s
            self.b.guard(s)
            close=Word('配置关闭',[946,40,29,29],1.)
            self.b.click_at(s,retry_point(close,attempt),saved_team_anchors(s),'收起配置')
            s=self.observe()
            if not is_saved_team_list(s):return s
            if is_saved_team_list(s) and attempt<3:
                self.navigation_retry('配置窗口仍在，重新确认后小偏移补点关闭',attempt+1,s)
        from .policy import IsolatedTaskError
        raise IsolatedTaskError('配置窗口关闭补点3次仍未生效，本项回退后继续下一任务')

    def apply_saved_team(self,s,team,*,_copy_retry=0):
        """Select a saved world team or copy it to a verified independent slot."""
        tribe_slot=self.active_task=='tribe' and is_tribe_formation(s)
        nest_slot=self.active_task=='nest' and bool(s.find('^[谜迷]之巢穴$',roi=FORMATION_HEADER_ROI) and
            s.find('^暴走旷野$',roi=(890,60,250,70)))
        header='^部队$' if tribe_slot else '^[谜迷]之巢穴$' if nest_slot else '^排阵$'
        if not s.find(header,roi=FORMATION_HEADER_ROI):raise TaskBlocked('排阵页未打开')
        current=s.find(r'^队伍[1-9]$',roi=(890,60,235,70))
        target='队伍'+str(team)
        if current:
            if current.text!=target:
                self.b.click_at(s,(1000,96),['^排阵$',re.escape(current.text)],'选择保存世界队伍')
                s=self.observe();choice=s.find('^'+target+'$',roi=(870,110,270,430))
                if not choice:raise TaskBlocked('保存队伍未找到：'+target)
                self.b.click_text(s,'^'+target+'$',roi=(870,110,270,430))
                s=self.await_world_team_switch(target)
        else:
            # Only independent dungeon slots may receive a copy; never overwrite world presets.
            if not tribe_slot and not nest_slot and not s.find('浮空巨塔|永生之茧|进击巨物|狩猎|异象|秘庭|部落冒险|黑暗森林|[凿幽]星裂痕',roi=(890,60,250,70)):
                raise TaskBlocked('无法确认独立副本配置，停止复制阵容')
            self.b.click_at(s,(852,96),[header],'打开配置列表');s=self.read_saved_team_list()
            row=s.find('^'+target+'$',roi=(285,80,200,590))
            for _ in range(4):
                if row and row.center[1]<=530:break
                self.b.guard(s)
                self.b.wait(self.b.controller.post_swipe(680,600,680,260,600));self.b.sleep(1.2);s=self.observe()
                s=self.read_saved_team_list(s)
                row=s.find('^'+target+'$',roi=(285,80,200,590))
            if not row or row.center[1]>530:raise TaskBlocked('配置列表未完整显示'+target)
            # Re-read the requested row, its button and the source portraits
            # together. A text-only click recheck cannot identify which of the
            # four identical copy buttons still belongs to the selected team.
            s,row,button=self.read_saved_team_copy_target(team)
            source_roi=(395,row.center[1]-22,115,45)
            power=s.find(r'^[0-9OolI|]{4,8}$',roi=source_roi)
            # Exclude the adjacent flame glyph, which OCR merges as W7437|.
            digits_roi=(426,row.center[1]-17,72,32)
            expected=formation_power(power.text) if power else formation_power(self.b.read_text_crop(s,digits_roi))
            if expected is None:expected=formation_power(self.b.read_text_region(s,digits_roi,3))
            source=source_lineup(s.image,row.center[1])
            if source is None:raise TaskBlocked(target+'源配置头像未读清，未复制阵容')
            self.b.save_screen(s,self.report['folder']/'team-copy-source.png')
            self.b.click_at(s,retry_point(button,_copy_retry),['^'+re.escape(target)+'$','^复制此配置$'],
                            '复制保存的'+target+'到独立配置');s=self.observe()
            copy_list_stayed=is_saved_team_list(s)
            if copy_list_stayed:
                s=self.close_saved_team_list(s)
            check={'task':self.active_task,'team':team,'expected_power':expected,'status':'pending'}
            self.report.setdefault('team_copy_checks',[]).append(check)
            evidence={'verified':False,'reason':'复制阵容后的排阵页未确认'}
            for attempt in range(3):
                if not s.find(header,roi=FORMATION_HEADER_ROI):
                    check.update(reads=attempt+1,reason='复制阵容后的排阵页未确认')
                    if attempt<2:
                        self.navigation_retry('复制阵容后排阵页尚未确认，重新识别，不重复复制',attempt+1,s)
                        self.b.sleep(.6);s=self.observe();continue
                    check['status']='unconfirmed'
                    raise TaskBlocked('复制阵容后排阵页重读3次仍未确认，未继续挑战')
                power=s.find(r'^[0-9OolI|]{4,8}$',roi=(1175,72,100,48))
                actual=formation_power(power.text) if power else formation_power(self.b.read_text_crop(s,(1178,77,80,35)))
                evidence=copied_lineup(source,s.image)
                check.update(actual_power=actual,power_matches=actual==expected if expected is not None else None,
                             reads=attempt+1,**evidence)
                if tribe_slot and copy_list_stayed and tribe_troop_deployed(s):
                    check['status']='kept_deployed'
                    self.note('当前部队已派出，已收起配置，沿用当前部队挑战')
                    self.checkpoint()
                    return s
                if evidence['verified']:break
                if attempt<2:self.b.sleep(.6);s=self.observe()
            check['status']='verified' if evidence['verified'] else 'unconfirmed'
            if not evidence['verified']:
                path=self.report['folder']/f'team-copy-unconfirmed-{len(self.report["team_copy_checks"])}.png'
                self.b.save_screen(s,path);check['screenshot']=str(path)
                if _copy_retry<2:
                    check['status']='retrying'
                    self.navigation_retry(target+'复制后怪兽未确认，重新核对同一配置后补点',_copy_retry+1,s)
                    return self.apply_saved_team(s,team,_copy_retry=_copy_retry+1)
                raise TaskBlocked(f'{target}复制后五只怪兽配置未确认；已重读3次，保留现场')
            if expected is None or actual!=expected:
                self.note(f'{target}五只怪兽已核对，战力读数仅作辅助，继续挑战')
        self.note('已选择'+target)
        return s

    def read_saved_team_copy_target(self,team):
        for attempt in range(4):
            s=self.observe();self.b.guard(s)
            target=saved_team_copy_target(self.b,s,team)
            if target:return s,*target
            if attempt==3:break
            self.navigation_retry(f'队伍{team}或对应复制按钮暂未读清，重新定位同一队伍',attempt+1,s)
            self.b.sleep(.6)
        raise TaskBlocked(f'队伍{team}及对应复制按钮重读3次仍未确认，未复制其他队伍')

    def read_saved_team_list(self,s=None):
        for attempt in range(4):
            if s is None:s=self.observe()
            self.b.guard(s)
            if is_saved_team_list(s):return s
            if attempt==3:break
            self.navigation_retry('配置列表尚未确认，重新识别队伍行和复制按钮',attempt+1,s)
            self.b.sleep(.6);s=None
        raise TaskBlocked('配置列表重读3次仍未识别，未复制阵容')

    def await_world_team_switch(self,target):
        # Only after selecting this task's verified saved-team row. home()
        # cancels a stale warning instead of confirming an unsolicited switch.
        confirmations=0
        for _ in range(12):
            s=self.observe();self.b.guard(s)
            if suppression_team_switch_dialog(s):
                if confirmations>=3:raise TaskBlocked('切换队伍的深渊压制提示未关闭')
                self.note('按当前任务切换到'+target+'，确认解除冲突的旧深渊压制')
                self.b.click_text(s,'^确定$',roi=(665,450,270,85));confirmations+=1
            elif s.find('^排阵$',roi=FORMATION_HEADER_ROI) and s.find('^'+target+'$',roi=(890,60,235,70)):
                return s
            self.b.sleep(.5)
        raise TaskBlocked('世界队伍切换未确认：'+target)

    def restore_world_team(self):
        """Compatibility for old recovery scripts; automatic team restore is retired."""
        return

    def exit_result(self,s):
        return self.leave_battle_result(s)

    def verify_instant_setting(self,task,s):
        # Ordinary own copies have an instant checkbox; evolved copies use a
        # separate detail layout without it. Check that exact layout instead of
        # requiring a nonexistent unchecked box on every own target.
        own=(task=='copies' and self.b.match_template(s,'copy-own-exp50.png',[30,590,110,90]))
        from .anomalies import evolved_copy_without_instant,instant_checkbox_present
        if own and evolved_copy_without_instant(s):return
        if not (own or s.find('瞬破')):return
        if self.b.match_template(s,'instant-off.png',[1000,680,55,40],.97):return
        # Evolved copies have no checkbox. Their banner and bottom controls can
        # arrive on separate animation frames, so re-read rather than mistaking
        # an incomplete detail frame for a checked instant action. A visible
        # checkbox that is not OFF still blocks immediately.
        if own and not instant_checkbox_present(s):
            for _ in range(3):
                self.b.sleep(.35);fresh=self.observe();self.b.guard(fresh)
                if evolved_copy_without_instant(fresh):return
                if self.b.match_template(fresh,'instant-off.png',[1000,680,55,40],.97):return
                if instant_checkbox_present(fresh):break
        raise TaskBlocked('瞬破未确认关闭')

    def play_encounter(self,task,opener,resource,verify=None,attempt_guard=None,on_started=None,prepare_team=None,teams_override=None):
        """Reopen the same target before each fallback team; move on after a win."""
        def attempt_once(team):
            self.check_budget(task)
            if attempt_guard:attempt_guard()
            detail=self.ensure_detail(opener())
            main_target=main_identity(detail) if task=='main' else None
            copy_start=len(self.report.get('team_copy_checks',[]))
            detail=(prepare_team or self.select_team)(detail,team)
            kept_deployed=task=='tribe' and any(check.get('status')=='kept_deployed'
                for check in self.report.get('team_copy_checks',[])[copy_start:])
            if task=='main':detail=self.stable_main_detail(detail,main_target,'after-team')
            if verify:verify(detail)
            if task=='tribe':self.prepare_tribe_attempt(detail)
            self.verify_instant_setting(task,detail)
            self.check_budget(task)
            self.active_task=task
            if task=='main':
                self.b.save_screen(detail,self.report['folder']/f'main-attempt-{self.task_counts.get(task,0)+1}-detail.png')
            if kept_deployed:self.start_challenge(task,detail,resource,verify,keep_current_wall=True)
            else:self.start_challenge(task,detail,resource,verify)
            if on_started:on_started()
            try:
                result=self.battle(resource)
                outcome='score' if task=='tribe' and not result.find('胜利') else 'victory'
            except FightLost as lost:result=lost.screen;outcome='failed'
            if task=='main' and outcome=='failed':
                self.b.save_screen(result,self.report['folder']/f'main-attempt-{self.task_counts.get(task,0)}-failed.png')
            floor=detail.find(r'(?:浮空巨塔|塔中秘庭)\s*\d+$',roi=(160,80,520,65)) if task=='tower' else None
            self.report.setdefault('team_attempts',[]).append({'task':task,'team':None if kept_deployed else team,'outcome':outcome,
                'target':main_identity(detail) if task=='main' else tribe_identity(detail) if task=='tribe' else floor.text if floor else encounter_identity(detail)})
            attempt=self.report['team_attempts'][-1]
            if kept_deployed:attempt['used_deployed_troop']=True
            target=attempt['target']
            lineup='（沿用出征部队）' if kept_deployed else f'（队伍{team}）' if team else ''
            self.note(('结算完成' if outcome=='score' else '挑战胜利' if outcome=='victory' else '挑战未通过')+
                      ('：'+target if target else '')+lineup)
            self.checkpoint()
            self.exit_result(result)
            return outcome
        def attempt(team):
            return attempt_once(team)
        results=run_team_plan(team_order(self.options[task]) if teams_override is None else teams_override,'clear',attempt)
        return any(outcome=='victory' or (task=='tribe' and outcome=='score') for _,outcome in results)

    def verify_stamina_cost(self,s,cost):
        ratio=parse_ratio(s.region_text((1140,0,140,65)))
        if not ratio:raise TaskBlocked('地图体力余额未识别')
        if self.active_task:self.resource_balance(self.active_task,'地图体力',ratio[0])
        if ratio[0]<cost:raise BudgetReached(f'体力不足{cost}')
        if s.find('^'+str(cost)+'$',roi=(1020,625,160,45)):return
        # A tiny white 5 may disappear from full-frame detection. Read only
        # its numeric slot, with the stamina icon and challenge controls present.
        if (cost==5 and is_main_detail(s) and self.b.tasker is not None and
                not re.search(r'\d',s.region_text((1098,635,42,30))) and
                self.b.match_template(s,'main-stamina-cost.png',[1060,630,45,40],.88) and
                self.b.read_number(s,(1100,636,25,25))==cost):
            return
        else:
            raise TaskBlocked(f'未确认挑战只消耗{cost}体力')

    def verify_dungeon_resource(self,task,s,roi=(1140,0,140,65)):
        key,label=DUNGEON_RESOURCES[task]
        ratio=self.dungeon_ratio(task,s,roi)
        if not ratio:raise TaskBlocked(label+'余额未识别')
        reserve=cocoon_reserve(self.options[task]) if task=='cocoon' else self.options[task][key]
        self.resource_balance(task,label,ratio[0])
        self.report.setdefault('dungeon_resources',{})[task]={'name':label,'remaining':ratio[0],'reserve':reserve}
        # These activities cost one per attempt. Check again after selecting every
        # fallback team, so a loss cannot consume the user's reserved balance.
        if ratio[0]-1<reserve:
            raise ResourceReserveReached(f'{label}剩余{ratio[0]}，'+(f'按设置保留{reserve}个' if reserve else '已用完'))

    def clear_tribe_reward(self,s):
        if not is_tribe_reward_overlay(s):return s
        clicks=0
        def close(q):
            nonlocal clicks
            if not is_tribe_reward_overlay(q):return
            # Use the free dismissal strip below the reward panel. The old
            # y=560 click could be swallowed, and observation alone never retried it.
            dx,dy=((0,0),(-3,2),(3,-2),(0,-3))[min(clicks,3)]
            clicks+=1
            try:self.b.click_at(q,(640+dx,660+dy),['^部落$','^获得奖励$'],'关闭部落冒险延迟奖励')
            except PageChanged:pass
        close(s)
        return self.wait_for_screen(is_tribe_map,'部落奖励关闭后地图恢复',timeout=3,retry_navigation=close)

    def stable_tribe_node(self,s,point):
        for attempt in range(5):
            fresh=self.clear_tribe_reward(self.observe());self.b.guard(fresh)
            if not is_tribe_map(fresh):
                if attempt<4:self.b.sleep(.5);continue
                raise TaskBlocked('点击前部落地图改变')
            candidates=tribe_nodes(fresh)
            if candidates:
                current=min(candidates,key=lambda p:math.dist(p,point))
                if math.dist(current,point)<12:return fresh,current
                point=current
            if attempt==0:self.note('部落关卡标记正在闪动或移动，等待稳定后重新定位')
            self.b.sleep(.5)
        raise TaskBlocked('部落可挑战标记持续未稳定，未使用旧坐标点击，保留剩余战令')

    def pan_tribe_map(self,s,direction):
        # One swallowed drag used to be treated as the map edge, so the scan
        # turned around before reaching the active stage. Confirm a stationary
        # edge with three bounded retries on the unobstructed upper strip.
        for attempt,y in enumerate((90,105,80,95)):
            s=self.clear_tribe_reward(s)
            self.b.guard(s)
            if not is_tribe_map(s):raise TaskBlocked('滑动前部落地图改变')
            x1,x2=(850,550) if direction==1 else (550,850)
            self.b.audit({'action':'swipe','reason':'定位部落冒险','attempt':attempt+1,
                          'from':[x1,y],'to':[x2,y],'status':'requested'})
            sent=self.b.wait(self.b.controller.post_swipe(x1,y,x2,y,1200)).succeeded
            self.b.sleep(1.5)
            q=self.wait_for_screen(lambda q:is_tribe_map(q) or is_tribe_reward_overlay(q),
                                   '部落地图滑动后确认',timeout=6)
            q=self.clear_tribe_reward(q)
            if tribe_map_moved(s,q):return q,True
            if attempt<3:self.note(f'部落地图暂未移动，重新定位后重试（{attempt+1}/3）')
            elif not sent:raise TaskBlocked('部落滑动指令连续失败，已重试3次，保留战令')
            s=q
        return s,False

    def tribe_detail(self,identity=None):
        s=self.clear_tribe_reward(self.observe());self.b.guard(s)
        if tribe_identity(s) and enemy_formation(s):
            allowed=not totem_identity(s) or (self.options['tribe']['random_totem'] and
                    getattr(self,'_tribe_totem_kind',None))
            if allowed and (identity is None or tribe_identity(s)==identity) and s.has('^排阵$','^挑战$'):
                return self.ensure_detail(s)
            s=self.back_detail(s)
        s=self.tribe_map(s)
        s=self.claim_tribe_occupation(s)
        if self.b.tasker is not None:s=self.claim_visible_tribe_chests(s)
        return self.find_tribe_detail(s,identity)

    def tribe_map(self,s=None):
        if s is None:s=self.clear_tribe_reward(self.observe())
        if is_tribe_detail(s):s=self.back_detail(s)
        if not is_tribe_map(s):
            try:s=self.enter_overview('^部落冒险$')
            except TaskBlocked as error:
                if '未找到入口' not in str(error):raise
                s=self.territory()
                self.b.click_at(s,(1042,535),['^世界$','^排阵$'],'核对领地部落入口')
                s=self.await_page('^部落$')
                if s.has('^申请加入$','^创建部落$','^部落名称$'):
                    raise BudgetReached('当前未加入部落，无法挑战部落冒险；战令未消耗')
        if not is_tribe_map(s):raise TaskBlocked('部落地图未识别')
        return s

    def find_tribe_detail(self,s,identity=None):
        if self.options['tribe']['random_totem'] and getattr(self,'_tribe_totem_kind',None) and not tribe_nodes(s):
            return self.tribe_totem_detail(s,identity)
        self.note('已进入部落地图，正在定位可挑战关卡')
        totems=set();edges=set()
        # Search both directions. The overview can open at any saved map position.
        for direction in (1,-1):
            for pan in range(13):
                self.b.save_screen(s,self.report['folder']/f'tribe-map-{direction}-{pan}.png')
                self.note(f'定位部落关卡：向{"右" if direction==1 else "左"}检查第{pan+1}屏')
                self.b.guard(s)
                if not is_tribe_map(s):raise TaskBlocked('定位时部落地图改变')
                self.verify_dungeon_resource('tribe',s,roi=(970,0,90,55))
                totems.update(row['kind'] for row in totem_nodes(s))
                for point in tribe_nodes(s):
                    fresh,point=self.stable_tribe_node(s,point)
                    self.verify_dungeon_resource('tribe',fresh,roi=(970,0,90,55))
                    self.b.click_at(fresh,point,['^部落$','^部落大厅$'],'选择部落冒险可挑战节点')
                    # A server loading spinner can cover the map for several
                    # seconds. Wait for the detail instead of retrying input.
                    detail=self.wait_for_screen(lambda q:bool(tribe_identity(q) and enemy_formation(q)),
                                                '部落冒险关卡详情加载',timeout=12)
                    self.b.guard(detail)
                    name=tribe_identity(detail)
                    if not name or not enemy_formation(detail):
                        raise TaskBlocked('部落节点未打开已知冒险详情')
                    if detail.has('^排阵$','^挑战$') and (identity is None or name==identity):
                        self._tribe_totem_kind=None
                        self.note('已定位'+name);return self.ensure_detail(detail)
                    s=self.back_detail(detail)
                if pan==12:break
                s,moved=self.pan_tribe_map(s,direction)
                if not moved:
                    edges.add(direction);break
        if edges!={1,-1}:raise TaskBlocked('部落地图搜索尚未确认两侧边界，保留战令，未切换图腾')
        if not self.options['tribe']['random_totem']:
            raise BudgetReached('当前没有可挑战的冒险关卡；随机挑战图腾未开启，保留剩余战令')
        if not totems:raise TaskBlocked('冒险关卡与图腾入口均未识别，保留剩余战令')
        import random
        self._tribe_totem_kind=random.choice(sorted(totems))
        self.note('没有可挑战的冒险关卡，按设置随机选择一个图腾')
        return self.tribe_totem_detail(s,identity)

    def tribe_totem_detail(self,s,identity=None):
        kind=self._tribe_totem_kind
        for direction in (1,-1):
            for pan in range(13):
                self.verify_dungeon_resource('tribe',s,roi=(970,0,90,55))
                target=next((row for row in totem_nodes(s) if row['kind']==kind),None)
                if target:
                    # Re-detect the crest on the current map before every free
                    # navigation retry; never replay an old map coordinate.
                    def open_totem(q):
                        if not is_tribe_map(q):return
                        row=next((row for row in totem_nodes(q) if row['kind']==kind),None)
                        if row:
                            self.verify_dungeon_resource('tribe',q,roi=(970,0,90,55))
                            self.b.click_at(q,row['point'],['^部落$','^部落大厅$'],'打开随机图腾详情')
                    fresh=self.observe();self.b.guard(fresh);open_totem(fresh)
                    detail=self.wait_for_screen(lambda q:bool(totem_identity(q) and is_tribe_detail(q)),
                                                '部落图腾详情加载',timeout=5,retry_navigation=open_totem)
                    name=totem_identity(detail)
                    if identity is not None and name!=identity:
                        raise TaskBlocked('图腾目标变化，未开始挑战')
                    self.report['tribe_totem']={'kind':kind,'name':name,'fallback':True}
                    self.note('已定位图腾：'+name)
                    return self.ensure_detail(detail)
                if pan==12:break
                s,moved=self.pan_tribe_map(s,direction)
                if not moved:break
        raise TaskBlocked('已选图腾入口未重新定位，保留剩余战令')

    def verify_tribe_detail(self,s,identity=None):
        self.b.guard(s)
        self.ensure_detail(s)
        if not is_tribe_detail(s):
            raise TaskBlocked('部落冒险详情未确认，未发起挑战')
        if totem_identity(s) and not self.options['tribe']['random_totem']:
            raise TaskBlocked('随机挑战图腾未开启，未消耗战令')
        if s.find('宣战|竞拍|^捐献$|^占领$|^部落战$|^部落纷争$'):
            raise TaskBlocked('当前为其他部落玩法，未消耗战令')
        name=tribe_identity(s)
        if not name or (identity is not None and name!=identity):
            raise TaskBlocked('部落冒险目标变化或名称未读清')
        self.verify_dungeon_resource('tribe',s)
        if not s.find('^1$',roi=(1096,633,25,29)) and self.b.read_number(s,(1096,633,25,29))!=1:
            raise TaskBlocked('未确认部落冒险单次消耗1战令')
        remaining=parse_ratio(s.region_text((960,535,300,60)))
        if remaining is None:raise TaskBlocked('部落冒险剩余挑战次数未读清')
        if remaining[0]==0:raise BudgetReached('部落冒险当前免费挑战次数已用完')

    def prepare_tribe_attempt(self,s):
        balance=self.b.read_resource_ratio(s,(1140,0,140,65))[0]
        remaining=parse_ratio(s.region_text((960,535,300,60)))[0]
        possible=min(balance,remaining)
        allowed=min(balance-self.options['tribe']['reserve_orders'],self.limit-self.battles)
        limit=self.options['tribe']['max_runs']
        if limit:allowed=min(allowed,limit-self.task_counts.get('tribe',0))
        # The game's repeat checkbox only exists on the result page. Until it
        # has been visibly disabled in this run, reserve the worst-case client
        # repeat budget before sending the first challenge click.
        if not getattr(self,'tribe_repeat_disabled',False) and possible>allowed:
            raise TaskBlocked('客户端重复挑战尚未确认关闭；本轮次数或保留战令不足以覆盖自动连打，未开战。请先在部落结算页关闭重复挑战')
        self.tribe_orders_before=balance

    def tribe_settlement(self,s):
        from .tribe_totems import tribe_result
        if not tribe_result(s):return None
        if not s.find('重复挑战'):
            # The auction reward layout has no repeat checkbox or order HUD.
            # Acknowledge the result; the task reads the real balance on return.
            self.note('已确认部落拍卖品结算页，无重复挑战控件；退出后重新核对战令')
            return s
        ratio=parse_ratio(s.region_text((1140,0,140,65)))
        if ratio is None:raise TaskBlocked('部落结算战令余额未读清')
        spent=getattr(self,'tribe_orders_before',ratio[0]+1)-ratio[0]
        if spent<1:raise TaskBlocked('部落结算未确认战令消耗')
        if spent>1:
            self.battles+=spent-1
            self.task_counts['tribe']=self.task_counts.get('tribe',0)+spent-1
            self.note(f'检测到客户端连续结算，共消耗{spent}个战令')
        self.report.setdefault('dungeon_resources',{})['tribe']={'name':'部落战令',
            'remaining':ratio[0],'reserve':self.options['tribe']['reserve_orders']}
        # The checkbox's interior is gold when checked, dark when unchecked.
        def checked(q):
            box=q.image[640:655,874:891]
            return ((box[:,:,2]>200)&(box[:,:,1]>170)&(box[:,:,0]<190)).mean()>.12
        if checked(s):
            self.b.click_at(s,(884,650),['^退出$','获得奖励','重复挑战'],'关闭客户端重复挑战')
            s=self.observe();self.b.guard(s)
        if s.has('^退出$','获得奖励','重复挑战') and not checked(s):
            self.tribe_repeat_disabled=True
            self.b.save_screen(s,self.report['folder']/'tribe-repeat-disabled.png')
            return s
        raise TaskBlocked('客户端重复挑战关闭未确认，停止后续挑战')

    def tribe(self):
        self.active_task='tribe'
        self.collect_tribe_extras()
        self.collect_tribe_chests()
        settlements=0;previous=None;reason=''
        while True:
            self.check_budget('tribe')
            try:
                s=self.tribe_detail();self.verify_tribe_detail(s)
            except BudgetReached as e:reason=str(e);self.note(reason);break
            balance=self.b.read_resource_ratio(s,(1140,0,140,65))[0]
            if previous is not None and balance>=previous:
                raise TaskBlocked('部落冒险结算后战令未减少，停止重复挑战并保留记录')
            identity=tribe_identity(s);first=[s]
            def opener():
                q=first.pop() if first else self.tribe_detail(identity)
                self.verify_tribe_detail(q,identity)
                return q
            try:passed=self.play_encounter('tribe',opener,'部落战令',lambda q:self.verify_tribe_detail(q,identity))
            except ResourceReserveReached as e:reason=str(e);self.note(reason);break
            if not passed:
                raise TaskBlocked(f'部落冒险所选阵容均未获得结算，已结算{settlements}次，保留剩余战令')
            settlements+=1;previous=balance
            self.note(f'部落冒险已完成 {self.task_counts.get("tribe",settlements)} 次结算，继续核对战令')
        self.home();return f'部落冒险结算{self.task_counts.get("tribe",settlements)}次'+('；停止原因：'+reason if reason else '')

    def hunt_menu(self):
        from .workflows import is_world
        s=self.observe();self.b.guard(s)
        if is_map_choice(s):
            self.note('检测到狩猎与地图关卡重叠，收起选择框后重新核对原猎物列表')
            s=self.close_map_choice(s)
            if is_map_choice(s) or not (is_world(s) or s.has('^狩猎$','^商店$','^传送$')):
                def retry(q):
                    if is_map_choice(q):self.close_map_choice(q)
                s=self.wait_for_screen(lambda q:not q.find('^请选择$') and
                    (is_world(q) or (q.has('^狩猎$','^商店$','^传送$') and not enemy_formation(q))),
                    '收起重叠目标后返回地图或狩猎列表',timeout=3,retry_navigation=retry)
        if not s.has('^狩猎$','^商店$','^传送$') or s.find('敌方阵容'):
            s=self.enter_overview('^狩猎$')
        if not s.has('^狩猎$','^商店$','^传送$'):raise TaskBlocked('狩猎列表未识别')
        return s

    def hunt_stock(self,s):
        stock=self.b.read_number(s,(1110,599,77,45))
        if stock is None:stock=self.b.read_number(s,(1130,597,56,38))
        self.resource_balance('hunt','狩猎令',stock)
        return stock

    def hunt_search_offer(self,s):
        """Read an allowed free/inventory search without consuming it."""
        options=self.options['hunt'];searches=self.search_counts.get('hunt',0)
        if not s.find('猎物未出现'):raise TaskBlocked('猎物列表状态未识别')
        if limit_reached(options['max_searches'],searches):
            self.hunt_stop_reason='已达到设置的搜索次数上限';return None
        free=s.find('^免费搜索$',roi=(1030,650,175,65))
        stock=self.hunt_stock(s)
        if not free:
            if not options['use_search_tokens']:
                self.hunt_stop_reason='没有现成猎物，且未开启使用狩猎令';return None
            if stock is None:raise TaskBlocked('搜索令库存未读清')
            if stock==0:
                self.hunt_stop_reason='没有现成猎物、没有免费搜索，狩猎令已用完';return None
            if not s.find('^搜索$',roi=(1030,650,175,65)):raise TaskBlocked('搜索按钮未识别')
        return free,stock

    def search_hunters(self,s):
        offer=self.hunt_search_offer(s)
        if offer is None:return None
        reason=self.hunt_search_budget(s)
        if reason:raise BudgetReached(reason+'，未开启新一批狩猎')
        free,stock=offer;searches=self.search_counts.get('hunt',0)
        if not free:
            self.note(f'搜索令库存 {stock}，使用 1 个搜索猎物')
        self.b.click_text(s,'^免费搜索$' if free else '^搜索$')
        self.search_counts['hunt']=searches+1;self.report['search_counts']=dict(self.search_counts)
        self.report['hunt_batch']={'remaining':HUNT_BATCH_SIZE,'required_stamina':HUNT_BATCH_SIZE*HUNT_STAMINA_COST,
                                   'status':'searching'}
        self.checkpoint()
        until=time.monotonic()+15
        while time.monotonic()<until:
            self.b.sleep(1);s=self.observe();self.b.guard(s)
            if s.has('^狩猎$','^商店$') and len(hunt_rows(s))==HUNT_BATCH_SIZE:
                after=self.hunt_stock(s)
                if not free and after!=stock-1:
                    self.resource_spent('hunt','狩猎令',None,after)
                    raise TaskBlocked('猎物已出现，但狩猎令扣除结果未确认，停止继续搜索')
                self.resource_spent('hunt','狩猎令',0 if free else 1,after)
                self.note('已开启本批3只限时猎物，连续挑战完毕后再执行其他任务')
                return s
        if not free:self.resource_spent('hunt','狩猎令',None,None)
        raise TaskBlocked('搜索结果尚未确认；本次不重复消耗搜索令')

    def hunt_search_budget(self,s):
        """Reserve the entire timed batch before either free or token search."""
        ratio=parse_ratio(s.region_text((490,0,170,65)))
        if not ratio:raise TaskBlocked('狩猎体力未识别')
        if self.limit-self.battles<HUNT_BATCH_SIZE:return '本轮剩余战斗次数不足以打完3只猎物'
        if ratio[0]<HUNT_BATCH_SIZE*HUNT_STAMINA_COST:
            return f'体力剩余{ratio[0]}，新一批3只猎物需要30体力，体力不足'
        return None

    def hunt_refill(self,required):
        """Refill inside hunt, then resume the same batch without dispatching tasks."""
        options=self.options['hunt'];reasons=[]
        self.hunt_refill_reason=''
        if options['auto_three_shots']:
            if self.try_stamina_refill('free') is not None:
                self.stamina_progress('spending','狩猎：免费体力已到账，立即返回狩猎继续挑战')
                self.report['stamina_refill']['status']='done'
                return True
            reasons.append(getattr(self,'stamina_free_reason','每日三发当前不可领取'))
        else:reasons.append('未开启自动领取每日三发')
        if options['auto_potions']:
            if not getattr(self,'_stamina_potions_unavailable',False):
                self.stamina_progress('opening_inventory',f'狩猎需要{required}体力，按设置检查库存移动力药水')
                gain=self.try_stamina_refill('potion')
                if gain is not None:
                    self.report['stamina_potion_count']=self.report.get('stamina_potion_count',0)+1
                    self.stamina_progress('spending','狩猎：库存体力已到账，立即返回狩猎继续挑战')
                    self.report['stamina_refill']['status']='done'
                    return True
            reasons.append(getattr(self,'stamina_potion_reason','库存移动力药水不可用'))
        else:reasons.append('未开启库存移动力药水')
        self.hunt_refill_reason='；'.join(reasons)
        self.report.setdefault('stamina_refill',{}).update(status='done',message=self.hunt_refill_reason,
            claimed=self.report.get('stamina_claims',0),potions=self.report.get('stamina_potion_count',0))
        return False

    def hunt(self):
        # World navigation during a refill must not detour into wild capture or
        # spend the stamina reserved for hunters whose timer is already running.
        wild_active=getattr(self,'wild_daily_active',False)
        self.wild_daily_active=False
        try:return self.run_hunt()
        except EncounterInterrupted:raise
        except TaskBlocked as error:
            pending=self.report.get('hunt_batch',{}).get('remaining',0)
            if pending:
                raise SafetyStop(f'狩猎还有{pending}只限时猎物未结算：{error}；已暂停后续任务，保留狩猎现场') from error
            raise
        finally:self.wild_daily_active=wild_active

    def run_hunt(self):
        wins=0;failed=0;searches=self.search_counts.get('hunt',0)
        reason='当前没有可挑战猎物';self.stamina_retry['hunt']=False
        pending=None
        while True:
            self.check_budget('hunt');s=pending if pending is not None else self.hunt_menu();pending=None
            ratio=parse_ratio(s.region_text((490,0,170,65)))
            if not ratio:raise TaskBlocked('狩猎体力未识别')
            self.resource_balance('hunt','地图体力',ratio[0]);stock=self.hunt_stock(s)
            rows=hunt_rows(s)
            required=(len(rows) if rows else HUNT_BATCH_SIZE)*HUNT_STAMINA_COST
            self.report['hunt_batch']={'remaining':len(rows),'required_stamina':required,
                                       'status':'active' if rows else 'empty'}
            if not rows:
                if self.hunt_search_offer(s) is None:
                    reason=getattr(self,'hunt_stop_reason','没有可用搜索机会');break
                # Check non-resource budgets before claiming a free serving.
                if self.limit-self.battles<HUNT_BATCH_SIZE:
                    reason='本轮剩余战斗次数不足以打完3只猎物，未开启新一批狩猎';break
            if ratio[0]<required:
                self.note(f'狩猎：体力{ratio[0]}，'+(f'剩余{len(rows)}只' if rows else '新一批3只')+f'需要{required}，先按设置补体力')
                if self.hunt_refill(required):pending=self.hunt_menu();continue
                # The claim check may have changed pages. Always reacquire the
                # actual list, balance and timers before any further input.
                s=self.hunt_menu();rows=hunt_rows(s)
                ratio=parse_ratio(s.region_text((490,0,170,65)))
                if not ratio:raise TaskBlocked('补体力后狩猎余额未识别')
                self.resource_balance('hunt','地图体力',ratio[0])
                self.report['hunt_batch'].update(remaining=len(rows),required_stamina=len(rows)*HUNT_STAMINA_COST,
                                                 status='active' if rows else 'empty')
                reason=f'体力剩余{ratio[0]}，体力不足；{self.hunt_refill_reason}'
                if not rows:
                    reason+='；未开启新一批狩猎';break
                if ratio[0]<HUNT_STAMINA_COST:
                    self.report['hunt_batch']['status']='stamina_unavailable'
                    reason+=f'；剩余{len(rows)}只猎物，继续后续任务'
                    break
                self.note('无法补充整批体力，先挑战当前体力可完成的剩余猎物')
            if not rows:
                s=self.search_hunters(s)
                if s is None:reason=getattr(self,'hunt_stop_reason','没有可用搜索机会');break
                searches=self.search_counts['hunt']
                rows=hunt_rows(s)
                self.report['hunt_batch'].update(remaining=len(rows),status='active')
            index=0;y=rows[index]
            self.b.click_at(s,(1000,y-35),['^狩猎$','^商店$'],'检查猎物')
            detail=self.await_detail(hunt_target=(len(rows),index));identity=encounter_identity(detail)
            # Unknown hunters are intentionally masked by the client; preserve their list slot.
            first=[detail]
            def opener():
                if first:return first.pop()
                q=self.hunt_menu();current=hunt_rows(q)
                if len(current)!=len(rows) or index>=len(current):raise TaskBlocked('猎物已离开或列表改变')
                self.b.click_at(q,(1000,current[index]-35),['^狩猎$','^商店$'],'重试同一猎物')
                q=self.await_detail(hunt_target=(len(rows),index))
                if encounter_identity(q)!=identity:raise TaskBlocked('猎物身份改变')
                return q
            def verify(q):
                self.verify_stamina_cost(q,10)
                timer=re.search(r'(?<!\d)(\d{2}):(\d{2})(?!\d)',q.region_text((545,115,175,65)))
                if not timer or int(timer[1])*60+int(timer[2])<15:raise TaskBlocked('猎物剩余时间不足或未识别')
            if self.play_encounter('hunt',opener,'地图体力10',verify):
                wins+=1
            else:failed+=1
            # A settled hunter disappears on either outcome. Reuse the refreshed
            # menu and always take its first remaining row, without team retries.
            pending=self.wait_hunter_removed(len(rows))
            remaining=len(hunt_rows(pending))
            self.report['hunt_batch'].update(remaining=remaining,required_stamina=remaining*HUNT_STAMINA_COST,
                                             status='active' if remaining else 'completed')
            self.checkpoint()
        self.home();return f'狩猎通关{wins}次，未通过{failed}个猎物，搜索{searches}次；停止原因：{reason}'

    def wait_hunter_removed(self,previous_count):
        for retry in range(4):
            self.b.check_stop()
            s=self.hunt_menu();rows=hunt_rows(s)
            if len(rows)<previous_count and (rows or s.find('猎物未出现')):return s
            if retry<3:
                if retry==0:self.note('猎物已结算，等待列表刷新后继续下一只')
                self.b.sleep(.8)
        self.b.save_screen(s,self.report['folder']/'hunt-list-not-refreshed.png')
        raise TaskBlocked('猎物已结算，但列表重读3次后仍未确认减少；未重复挑战或继续搜索')

    def main_search_limit_reached(self):
        options=self.options['main']
        return bool(options.get('search_limit_enabled',False) and
                    self.report.get('main_searches',0)>=options.get('max_searches',50))

    def count_main_search(self,source):
        self.b.check_stop()
        if self.main_search_limit_reached():
            raise BudgetReached(f'主线搜索达到设置的{self.options["main"]["max_searches"]}次上限，继续下一个任务')
        count=self.report.get('main_searches',0)+1
        self.report['main_searches']=count
        self.report.setdefault('main_search_history',[]).append({'number':count,'source':source})
        self.checkpoint()

    def main(self):
        self.stamina_retry['main']=False
        wins=0;options=self.options['main'];teams=team_order(options)
        failed=self.report.setdefault('main_failed',[])
        seen=self.report.setdefault('main_seen',[]);idle=set()
        progress=self.report.setdefault('main_stage_progress',{})
        # Settlement records also survive a failed exit or page recovery.
        for row in self.task_attempts('main'):
            identity=row.get('target')
            if not isinstance(identity,str) or row.get('outcome') not in ('victory','failed'):continue
            entry=progress.setdefault(identity,{'teams':[],'cleared':False})
            if row.get('team') not in entry['teams']:entry['teams'].append(row.get('team'))
            if row['outcome']=='victory':entry['cleared']=True
        if not self.overview_prepared_for('main'):
            s=self.home();balance=self.world_resources(s)['stamina']
            self.resource_balance('main','地图体力',balance)
            if balance is not None and balance<5:
                self.stamina_retry['main']=True;return f'体力剩余{balance}，不足主线单次5体力'
        pans=iter(((940,360,350,360),(360,360,940,360),(640,490,640,210),(640,210,640,490)))
        reason='概览已轮回，当前关卡的所选队伍均已尝试或尚未解锁'
        resume_target=None;handoffs=0
        while True:
            self.check_budget('main')
            if self.main_search_limit_reached():
                reason=f'主线搜索达到设置的{options["max_searches"]}次上限';break
            try:
                if resume_target is not None:
                    pending=self.last_main_detail(resume_target)
                    resume_target=None
                else:
                    pending=self.main_overview_detail()
                if pending is None:
                    excluded=set(failed)|{n for n,e in progress.items() if e['cleared']}
                    pending=self.find_main_candidate(excluded)
            except MainRetryUnavailable as error:
                self.note(str(error));resume_target=None;self.home();continue
            except EncounterInterrupted as error:
                handoffs+=1
                if handoffs>3:raise TaskBlocked('主线目标连续被寻路事件打断，未发起额外挑战') from error
                self.note('主线寻路事件已处理，继续核对目标');self.home();continue
            if pending is None:
                swipe=next(pans,None)
                if swipe is None:
                    reason='当前搜索范围内没有剩余可挑战节点';break
                s=self.home();self.b.guard(s)
                self.b.wait(self.b.controller.post_swipe(*swipe,850));self.b.sleep(1.5)
                continue
            pending=self.stable_main_detail(pending,phase='target')
            identity=main_identity(pending)
            if identity is None:raise TaskBlocked('主线关卡编号未识别')
            if identity not in seen:seen.append(identity)
            self.report['main_examined']=len(seen)
            entry=progress.setdefault(identity,{'teams':[],'cleared':False})
            remaining=[team for team in teams if team not in entry['teams']]
            locked=self.record_locked_main(pending)
            if locked or entry['cleared'] or not remaining:
                self.back_detail(pending)
                if identity in idle:break
                idle.add(identity);continue
            # The client has already selected this stage. Try one unused team
            # here; another overview visit can supply a different stage.
            idle.clear();team=remaining[0];first=[pending]
            def opener():
                if first:return first.pop()
                raise MainRetryUnavailable('主线'+identity+'寻路被事件打断，保留未尝试队伍，继续当前推荐关卡')
            def verify(q):
                if main_identity(q)!=identity:raise TaskBlocked('主线换队后关号与原目标不符，未挑战')
                if not q.find('^首通奖励$') or q.find('已通关|首通奖励已领取'):
                    raise TaskBlocked('该主线没有确认首通奖励')
                self.verify_stamina_cost(q,5)
            self._main_interrupted_target=None
            try:
                won=self.play_encounter('main',opener,'主线体力5',verify,teams_override=[team])
            except MainRetryUnavailable as error:
                self.note(str(error));self.home();continue
            except EncounterInterrupted as error:
                if self._main_interrupted_target!=identity:raise
                handoffs+=1
                if handoffs>3:raise TaskBlocked('主线'+identity+'连续被寻路事件打断，保留未尝试队伍') from error
                self.note('主线'+identity+'的寻路事件已处理，重新定位同一关卡')
                resume_target=identity;continue
            handoffs=0
            if team not in entry['teams']:entry['teams'].append(team)
            if won:
                wins+=1;entry['cleared']=True
                self.main_positions.pop(identity,None);self.main_views.pop(identity,None)
            elif all(t in entry['teams'] for t in teams):
                if identity not in failed:failed.append(identity)
                self.note('主线'+identity+'全部所选阵容失败，寻找其他关卡')
            else:self.note('主线'+identity+'保留其余阵容，下次遇到本关再尝试')
            self.checkpoint()
            s=self.home()
            if (self.world_resources(s)['stamina'] or 0)<5:
                self.stamina_retry['main']=True;reason='体力不足5';break
        self.home()
        return (f'主线通关{wins}次，检查{self.report.get("main_examined",0)}关，搜索{self.report.get("main_searches",0)}次；'
                f'等级未解锁跳过{len(self.report.get("main_locked",{}))}关；停止原因：{reason}')

    def record_locked_main(self,s):
        level=main_unlock_level(s)
        if level is None:return False
        identity=main_identity(s);locked=self.report.setdefault('main_locked',{})
        if identity not in locked:
            locked[identity]={'required_level':level}
            self.note(f'主线{identity}需要探索者{level}级，跳过并寻找其他关卡')
        return True

    def stable_main_detail(self,s,expected=None,phase='target'):
        """Confirm two fresh stage readings; never substitute a fallback target."""
        checks=self.report.setdefault('main_identity_checks',[])
        row={'phase':phase,'expected':expected,'readings':[],'status':'reading'}
        checks.append(row);prefix=f'main-identity-{len(checks)}-{phase}'
        previous=None
        for attempt in range(5):
            self.b.check_stop();self.b.guard(s)
            identity=main_identity(s) if is_main_detail(s) else None
            row['readings'].append(identity)
            self.b.save_screen(s,self.report['folder']/f'{prefix}-{attempt}.png')
            if identity is not None and identity==previous and (expected is None or identity==expected):
                row.update(status='confirmed',identity=identity)
                return s
            previous=identity
            if attempt<4:
                if attempt==1:self.note('主线关号尚未稳定，重新读取当前详情')
                self.b.sleep(.5);s=self.observe()
        row['status']='unconfirmed'
        self.checkpoint()
        seen='、'.join(str(n) if n is not None else '未读清' for n in row['readings'])
        raise TaskBlocked(('主线换队后关号与原目标'+expected+'不符' if expected else '主线关卡编号未识别稳定')+
                          '，重读4次仍未确认（'+seen+'），未挑战')

    def main_overview_detail(self):
        from .workflows import is_world
        self.count_main_search('玩法概览')
        s=self.enter_overview('^世界关卡$')
        # Some overview arrows only move the camera. The caller continues its
        # bounded local-node search instead of waiting for a nonexistent detail.
        detail=None if s is not None and is_world(s) else self.await_detail()
        self._main_overview_target=main_identity(detail) if detail is not None else None
        return detail

    def find_main_candidate(self,excluded,wanted=None):
        from .reward_collection import is_map_story
        s=self.home();origin=s;candidates=main_nodes(s)
        for point in candidates:
            s=self.home()
            # Re-detect the marker before every click; map positions may move after travel.
            shift=main_map_shift(origin,s)
            if shift is None:continue
            expected=(point[0]+shift[0],point[1]+shift[1])
            points=main_nodes(s)
            candidate=min(points,key=lambda p:math.dist(p,expected),default=None)
            if candidate is None or math.dist(candidate,expected)>18:continue
            if self.main_node_skipped(s,candidate):continue
            known=self.known_main_node(s,candidate)
            if known is not None and (known in excluded or (wanted is not None and known!=wanted)):continue
            source=s
            self.count_main_search('地图节点')
            self.click_world(s,candidate,'打开可见未通关节点')
            story_seen=False
            def destination(q):
                nonlocal story_seen
                if is_map_choice(q):q=self.open_main_choice(q)
                if is_map_story(q):
                    story_seen=True;q=self.close_map_story(q)
                return q
            q=destination(self.observe())
            if not q.find('敌方阵容'):
                self.b.sleep(2);q=destination(self.observe())
                # First tap can only walk to a node. Re-detect the same nearby
                # marker before a second tap; never reuse it after a map shift.
                from .workflows import is_world
                if is_world(q) and not story_seen:
                    travel=main_map_shift(source,q)
                    arrived=(candidate[0]+travel[0],candidate[1]+travel[1]) if travel is not None else None
                    fresh=min(main_nodes(q),key=lambda p:math.dist(p,arrived),default=None) if arrived is not None else None
                    if fresh and math.dist(fresh,arrived)<18:
                        source=q;candidate=fresh
                        self.count_main_search('抵达节点重读')
                        self.click_world(q,fresh,'抵达后打开主线节点')
                        self.b.sleep(1);q=destination(self.observe())
            if q.find('敌方阵容') and q.find('首通奖励'):
                ident=main_identity(q)
                if ident:
                    self.main_positions[ident]=candidate;self.main_views[ident]=source
                    if self.record_locked_main(q):
                        excluded.add(ident);self.back_detail(q);continue
                    self.ensure_detail(q)
                if ident and ident not in excluded and (wanted is None or ident==wanted):
                    self.b.save_screen(source,self.report['folder']/f'main-node-{ident}.png')
                    return q
                self.back_detail(q)
            else:
                # No challenge is sent to a capture/player/locked/unknown popup.
                if q.find('敌方阵容') or story_seen:
                    self._main_skipped_nodes=getattr(self,'_main_skipped_nodes',[])+[(source,candidate)]
                self.home(q)
        return None

    def known_main_node(self,s,point):
        for ident,reference in self.main_views.items():
            shift=main_map_shift(reference,s)
            if shift is None:continue
            old=self.main_positions[ident]
            if math.dist(point,(old[0]+shift[0],old[1]+shift[1]))<18:return ident
        return None

    def main_node_skipped(self,s,point):
        for reference,old in getattr(self,'_main_skipped_nodes',[]):
            shift=main_map_shift(reference,s)
            if shift is not None and math.dist(point,(old[0]+shift[0],old[1]+shift[1]))<18:return True
        return False

    def last_main_detail(self,identity):
        s=self.home()
        if (getattr(self,'_main_interrupted_target',None)==identity and
                getattr(self,'_main_overview_target',None)==identity):
            # The remote overview target has not started its battle yet.
            # Resume that verified stage directly after an ambush/gate instead
            # of tapping unrelated markers around the interrupted walk.
            self._main_interrupted_target=None
            q=self.retry_main_overview_detail(identity,max_lookups=20)
            if q is not None:return q
            s=self.home()
        point=self.main_positions.get(identity);reference=self.main_views.get(identity)
        if point is not None and reference is not None:
            shift=main_map_shift(reference,s)
            if shift is not None:
                expected=(point[0]+shift[0],point[1]+shift[1])
                candidate=min(main_nodes(s),key=lambda p:math.dist(p,expected),default=None)
                if candidate is not None and math.dist(candidate,expected)<18:
                    self.note('返回原主线'+identity+'，继续下一支队伍')
                    self.click_world(s,candidate,'返回已核实的主线'+identity)
                    q=self.await_detail()
                    if main_identity(q)==identity:return q
                    self.back_detail(q)
        # A node can be temporarily obscured by the player marker. Inspect local
        # details without jumping away through the unrelated overview shortcut.
        q=self.find_main_candidate(set(),wanted=identity)
        if q is not None:return q
        if point is None and reference is None and getattr(self,'_main_overview_target',None)==identity:
            # The local marker may be unavailable for an overview-opened stage.
            # Use the overview only after inspecting the current map: a changed
            # recommendation must not move us away before the local retry.
            q=self.retry_main_overview_detail(identity)
            if q is not None:return q
        raise MainRetryUnavailable('原主线'+identity+'节点暂未确认，未挑战其他关卡来冒充换队重试')

    def retry_main_overview_detail(self,identity,*,max_lookups=4):
        lookup={'target':identity,'observed':[],'status':'pending'}
        self.report.setdefault('main_retry_lookups',[]).append(lookup)
        for attempt in range(max_lookups):
            self.check_budget('main')
            self.note('通过玩法概览重新定位原主线'+identity+f'（{attempt+1}/{max_lookups}），只接受相同关号')
            q=self.main_overview_detail()
            actual=main_identity(q) if q is not None else None
            lookup['observed'].append(actual)
            if actual==identity:
                lookup['status']='found';return q
            if q is not None:self.back_detail(q)
            if max_lookups>4 and actual is not None and actual in lookup['observed'][:-1]:
                self.note('概览已重复推荐检查过的关卡，结束本次原关号查找');break
            if attempt<max_lookups-1:self.note('概览推荐了其他关卡，退出后重新定位，不发起挑战')
        lookup['status']='unavailable'
        return None

    def giant_menu(self):
        s=self.observe();self.b.guard(s)
        if is_giant_ready(s):
            self.b.click_at(s,(45,28),['^进击巨物$','^前往挑战$'],'返回巨物成绩页')
            return self.await_page('^进击巨物$','^开始挑战$','^我的排名$')
        if s.has('^进击巨物$','^开始挑战$','^我的排名$'):return s
        s=self.event_hub(s)
        entry=activity_entry(s,'giant')
        if not entry:raise BudgetReached('进击巨物入口当前不存在或活动未开放，已跳过')
        availability=activity_availability(s,entry)
        if availability=='ended':raise BudgetReached('进击巨物活动已结束，已跳过')
        if availability=='not_open':raise BudgetReached('进击巨物尚未开放，已跳过')
        self.b.click_at(s,entry.center,[*event_hub_anchors(s),'^进击巨物$'],'进入进击巨物')
        return self.await_page('^进击巨物$','^开始挑战$','^我的排名$')

    def giant_ready(self):
        until=time.monotonic()+12
        while time.monotonic()<until:
            s=self.observe();self.b.guard(s)
            if is_giant_ready(s):return s
            self.b.sleep(.5)
        raise TaskBlocked('巨物备战页未加载：需要进击巨物、排阵和前往挑战按钮')

    def giant(self):
        s=self.giant_menu();opening=giant_is_open(s)
        if opening is None:raise TaskBlocked('巨物开放时间未识别')
        if not opening:self.home();return '进击巨物当前未开放，已跳过'
        baseline=giant_damage(s)
        if baseline is None:raise TaskBlocked('巨物当日成绩未识别')
        self.report['giant_best_damage_start']=baseline
        if self.options['giant']['skip_completed'] and baseline>0:
            self.home();return f'当日巨物已有伤害{baseline}，按设置跳过'
        def attempt(team):
            self.check_budget('giant');q=self.giant_menu()
            if not giant_is_open(q):raise BudgetReached('巨物开放时间已结束')
            self.b.click_text(q,'^开始挑战$');q=self.giant_ready()
            q=self.select_team(q,team,return_page=self.giant_ready)
            def verify_ready(q):
                # Reapply the same free-entry check before every launch retry.
                cost=q.region_text((1020,635,180,45))
                if re.search(r'\d',cost):raise TaskBlocked('巨物挑战出现费用，保留现场')
                if not is_giant_ready(q):raise TaskBlocked('巨物备战页在开战前改变')
            verify_ready(q)
            self.note('进击巨物：'+('当前阵容' if team is None else f'队伍{team}')+'开始挑战')
            self.active_task='giant';self.start_challenge('giant',q,'巨物免费挑战',verify_ready)
            result=self.giant_settlement()
            self.report.setdefault('team_attempts',[]).append({'task':'giant','team':team,'outcome':'score','best_damage':result})
            self.report['giant_best_damage_end']=result
            self.note(f'进击巨物已结算，当日最高总伤害{result}')
            return 'score'
        results=run_team_plan(team_order(self.options['giant']),'score',attempt)
        self.home();return f'进击巨物已用{len(results)}套阵容分别完成挑战'

    def giant_settlement(self):
        self.battles+=1;self.task_counts['giant']=self.task_counts.get('giant',0)+1
        saw_battle=False
        feedback=time.monotonic();network_retries=0;settle_clicked=False;returned={'started':time.monotonic()}
        for q in self.battle_frames(int(self.b.settings.get('battle_timeout_seconds',240)),'进击巨物',clock=time.monotonic):
            self.b.guard(q)
            if self.retry_battle_network(q,network_retries):
                network_retries+=1;continue
            if q.find('^暂停$|^撤退$|^自动$|^手动$|^X2$|^x2$') or q.find(r'\d+:\d+',roi=(490,0,300,100)):
                saw_battle=True
            if (self.options['giant']['auto_settle'] and not settle_clicked and
                    q.find('^进击巨物$',(1080,0,200,65)) and q.find('累计伤害比拼',(980,65,300,90)) and
                    q.find('^结算$',(140,570,100,85)) and q.find(r'^\d{2}:\d{2}$',(490,0,300,100))):
                self.b.save_screen(q,self.report['folder']/'giant-before-settle.png')
                self.b.click_at(q,q.find('^结算$',(140,570,100,85)).center,
                                ['^进击巨物$','累计伤害比拼','^结算$'],'点击巨物战斗结算')
                settle_clicked=True
                self.note('已点击巨物结算，等待成绩确认');continue
            if q.find('^退出$') and q.find('总伤害|本次伤害|挑战结束|战斗结束|胜利|失败'):
                saw_battle=True;self.exit_result(q);continue
            if saw_battle and q.has('^进击巨物$','^开始挑战$','^我的排名$'):
                value=giant_damage(q)
                if value is None:raise TaskBlocked('巨物返回排行榜但成绩未读清')
                self.report.setdefault('battles',[]).append({'resource':'进击巨物免费','result':'score','best_damage':value})
                return value
            page=self.battle_return_page(q,returned,ready=saw_battle or settle_clicked)
            if page:
                value=giant_damage(q) if q.has('^进击巨物$','^开始挑战$','^我的排名$') else None
                if value is not None:return value
                self.raise_battle_returned(q,page)
            if time.monotonic()-feedback>=15:
                self.note('进击巨物战斗中，等待伤害结算…');feedback=time.monotonic()
            self.b.sleep(2)

    def tower_territory(self,s):
        # Full-frame OCR can drop the 永生之茧 label completely; re-read the
        # region once before declaring the territory lost.
        return bool(s.find('^世界$',(1150,620,130,100)) and
                    s.find('^黑暗森林$',(780,380,200,200)) and
                    (s.find('^永生之茧$',(780,140,210,170)) or
                     self.b.confirm_label(s,'^永生之茧$',(780,140,210,170))))

    def enter_tower_selector(self,s):
        """Retry a swallowed entrance click only on the confirmed territory."""
        def enter(q):
            if not self.tower_territory(q):return
            self.b.click_at(q,(724,130),['^世界$','^永生之茧$','^黑暗森林$'],'进入浮空巨塔')
        enter(s)
        return self.wait_for_screen(lambda q:bool(q.find('选择挑战的塔')),
            '进入浮空巨塔选塔页面',timeout=4,retry_navigation=enter)

    def tower_selection(self):
        """Reach the tower selector, falling back to 任务挑战 when the world-map
        anchors (世界 / 黑暗森林 / 永生之茧) cannot be confirmed."""
        try:
            s=self.territory()
            if self.tower_territory(s):return self.enter_tower_selector(s)
            reason='浮空巨塔领地锚点未确认'
        except TaskBlocked as e:
            reason='浮空巨塔地图入口未确认（'+str(e)+'）'
        self.note(reason+'，改用任务挑战兜底')
        s=self.overview_entry('tower',reason=reason)
        if s.find('选择挑战的塔'):return s
        return self.await_page('选择挑战的塔')

    def tower_navigation_state(self,s):
        from .workflows import is_tasks
        if is_tasks(s):return 'overview'
        if s.find('选择挑战的塔'):return 'selector'
        if s.find('^退出$'):return 'result'
        if enemy_formation(s) and s.find(r'(?:浮空巨塔|塔中秘庭)\s*\d+$',(150,75,560,90)):
            return 'detail'
        if is_tower_secret_list(s):return 'secrets'
        if is_tower_map(s):return 'floors'
        if self.tower_territory(s):return 'territory'
        from .workflows import is_world
        if is_world(s):return 'world'
        return None

    def tower_back_page(self,s):
        """One confirmed free return, then follow the actual destination.

        Returning from a tower may land in the territory directly. Two reads
        of a known successor are required before deciding the next navigation.
        Only an unchanged source can receive up to three additional back taps.
        """
        source=self.tower_navigation_state(s)
        if source not in ('detail','secrets','floors'):raise TaskBlocked('巨塔返回前页面未确认')
        title=s.find(r'(?:浮空巨塔|塔中秘庭)\s*\d+$',(150,75,560,90)) if source=='detail' else None
        anchors=['^'+re.escape(title.text)+'$','敌方阵容'] if title else ['^浮空巨塔$']
        labels={'detail':'返回当前塔层列表','secrets':'收起当前塔秘庭','floors':'返回选塔入口'}
        rows=self.report.setdefault('tower_navigation',[])
        row={'source':source,'tower':getattr(self,'_tower_kind',None),'clicks':0,'status':'pending','observed':[]}
        rows.append(row);destination=None;stable=0
        def arrived(q):
            nonlocal destination,stable
            state=self.tower_navigation_state(q)
            if not row['observed'] or row['observed'][-1]!=state:row['observed'].append(state)
            if not state or state==source:destination=None;stable=0;return False
            stable=stable+1 if state==destination else 1;destination=state
            return stable>=2
        def back(q):
            if self.tower_navigation_state(q)!=source or not q.has(*anchors):return
            self.b.click_at(q,(45,28),anchors,labels[source])
            row['clicks']+=1;self.checkpoint()
        try:
            back(s)
            q=self.wait_for_screen(arrived,labels[source]+'后确认实际页面',timeout=4,retry_navigation=back)
            row.update(status='arrived',destination=destination)
            if destination in ('selector','territory','world','overview'):self._tower_kind=None
            self.b.save_screen(q,self.report['folder']/f'tower-navigation-{len(rows)}-destination.png')
            self.checkpoint();return q
        except (TaskBlocked,SafetyStop,UserStopped) as error:
            row.update(status='stopped' if isinstance(error,UserStopped) else 'blocked',reason=str(error))
            self.checkpoint();raise

    def open_tower(self,kind):
        s=self.enter_overview('^浮空巨塔$') if self.overview_prepared_for('tower') else self.observe()
        for _ in range(10):
            self.b.guard(s)
            page=self.tower_navigation_state(s)
            if page=='result':s=self.exit_result(s);continue
            if page in ('detail','secrets'):
                s=self.tower_back_page(s);continue
            if page=='floors':
                if getattr(self,'_tower_kind',None)==kind['id']:return s
                s=self.tower_back_page(s);continue
            if page=='selector':
                def select(q):
                    if q.find('选择挑战的塔') and q.find('^'+re.escape(kind['label'])+'$'):
                        self.b.click_text(q,'^'+re.escape(kind['label'])+'$')
                select(s)
                s=self.wait_for_screen(lambda q:is_tower_map(q) and not is_tower_secret_list(q),'打开'+kind['label']+'巨塔',
                                       timeout=4,retry_navigation=select)
                self._tower_kind=kind['id'];return s
            if page=='territory':
                self._tower_kind=None
                self.note('巨塔返回到了领地，重新进入选塔：'+kind['label'])
                s=self.enter_tower_selector(s)
            elif page=='overview':
                self._tower_kind=None
                s=self.overview_entry('tower',reason='巨塔返回到玩法概览，继续选择'+kind['label'])
            else:
                self._tower_kind=None;s=self.tower_selection()
        raise TaskBlocked('选中的塔未开放')

    def tower_map(self,s=None):
        """Return to the current tower, reopening it if a back lands outside."""
        s=s if s is not None else self.observe()
        expected=getattr(self,'_tower_kind',None)
        for _ in range(8):
            self.b.guard(s)
            page=self.tower_navigation_state(s)
            if page=='floors':return s
            if page=='result':s=self.exit_result(s);continue
            if page in ('detail','secrets'):s=self.tower_back_page(s);continue
            if page in ('selector','territory','world','overview'):
                kind=next((row for row in self.options['tower']['towers'] if row['id']==expected),None)
                if kind is None:raise TaskBlocked('返回后已离开巨塔，原塔类型未确认，保留现场')
                self.note('返回当前巨塔时页面已变化，重新进入：'+kind['label'])
                return self.open_tower(kind)
            self.b.sleep(.5);s=self.observe()
        raise TaskBlocked('未返回当前巨塔列表，保留现场')

    def tower_open_floor(self,s,kind,expected=None):
        s,floor=self.tower_next_floor(s);n,y=floor
        if expected is not None and n!=expected:raise TaskBlocked('塔层进度发生变化')
        self.b.click_at(s,(505,y),['^浮空巨塔$'],f'打开{kind["label"]}第{n}层')
        q=self.await_detail()
        if tower_floor_number(q,kind)!=n:raise TaskBlocked('目标塔层不符')
        return q,n

    def tower_advance(self,result,kind,n):
        before=self.dungeon_ratio('tower',result)

        def transition(s):
            self.check_tower_level_gate(s,('' if kind['id']=='normal' else kind['label']+'-')+f'浮空巨塔{n}')
            if s.find('敌方阵容'):
                s=self.ensure_detail(s)
                if tower_floor_number(s,kind)!=n:raise TaskBlocked('下一关塔层不符')
                return s,False
            if s.find('^退出$'):
                after=self.dungeon_ratio('tower',s)
                if before and after and after==(before[0]-1,before[1]):return s,True
            elif s.find('^暂停$|^自动$|^手动$|^X2$|^x2$|^撤退$'):
                return s,True
            if is_tower_map(s):return s,False

        def unchanged_result(s):
            # A fast next fight can already be back on a similar settlement.
            # Only an unchanged, readable feather balance permits another tap.
            return bool(before and s.has('胜利','^获得奖励$','^退出$',r'下一[关层]$') and
                        self.dungeon_ratio('tower',s)==before)

        self.note(f'{kind["label"]}直接挑战下一关：{n}层')
        s=result
        for attempt in range(4):
            if attempt:
                s=self.observe();self.b.guard(s)
                changed=transition(s)
                if changed:return changed
                if not unchanged_result(s):
                    raise TaskBlocked('下一关状态或羽毛余额未确认，未重复点击，保留现场')
                self.check_budget('tower')
                self.navigation_retry('下一关点击未推进，重新点击已确认的结算按钮',attempt,s)
            try:self.b.click_text(s,r'下一[关层]$',settle_delay=.15)
            except (PageChanged,TaskBlocked) as error:
                fresh=getattr(error,'screen',None) or self.observe();self.b.guard(fresh)
                changed=transition(fresh)
                if changed:return changed
                from .result_navigation import exit_destination
                if exit_destination(fresh):return self.tower_map(fresh),False
                raise
            self.report['tower_next_clicks']=self.report.get('tower_next_clicks',0)+1
            stable=0
            for _ in range(8):
                s=self.observe();self.b.guard(s)
                changed=transition(s)
                if changed:return changed
                stable=stable+1 if unchanged_result(s) else 0
                self.b.sleep(.5)
            if stable<3:
                raise TaskBlocked('下一关状态或羽毛余额未确认，未重复点击，保留现场')
        raise TaskBlocked('点击下一关后仍停留在原结算页，已重试3次，保留现场')

    def tower_secret_list(self,s=None):
        s=s if s is not None else self.observe()
        pending=None
        for _ in range(8):
            self.b.guard(s)
            if is_tower_secret_list(s):return s
            page='result' if s.find('^退出$') else 'detail' if s.find('敌方阵容') else 'map' if is_tower_map(s) else None
            if page is None or page==pending:self.b.sleep(.5)
            elif page=='result':
                self.exit_result(s)
            elif page=='detail':
                self.b.click_at(s,(45,28),['敌方阵容'],'返回当前秘庭列表')
            elif page=='map':
                entry=s.find(r'^塔中秘庭\d+$',roi=(900,500,300,180))
                if not entry:raise TaskBlocked('当前塔秘庭入口未识别')
                self.b.click_text(s,'^'+re.escape(entry.text)+'$',roi=(900,500,300,180))
            if page is not None:pending=page
            s=self.observe()
        raise TaskBlocked('当前塔秘庭列表未打开')

    def verify_tower_secret(self,s,name):
        from .dungeon_labels import OVERLAY
        self.b.guard(s)
        button=s.find('^挑战$',roi=(850,590,260,75))
        # In the observed free layout the centered button has no lower cost
        # line. Paid tower buttons shift the title up and show a feather below.
        if (s.find(OVERLAY) or not s.has('^'+re.escape(name)+'$','首通奖励') or not enemy_formation(s) or
                not button or button.center[1]<625 or
                re.search(r'\d|钻石|羽毛',s.region_text((900,640,200,25)))):
            raise TaskBlocked('秘庭免费挑战未确认')

    def click_tower_secret_node(self,s,name):
        """Wait for a dragged secret map to settle before using its current node position.

        The generic text click rejects a target that moves between its two
        screenshots. A horizontal map swipe can still be coasting at that point.
        Only this confirmed, unlocked node may be clicked after two consistent
        observations; never reuse its pre-swipe coordinates.
        """
        previous=None
        for _ in range(6):
            self.b.guard(s)
            if not is_tower_secret_list(s):
                raise TaskBlocked('点击秘庭前列表已改变，保留现场')
            node=next((w for w in secret_nodes(s) if w.text==name),None)
            if node is not None:
                if previous is not None and math.dist(previous,node.center)<=25:
                    self.b.click_at(s,node.center,['^浮空巨塔$','^'+re.escape(name)+'$'],
                                    '打开已稳定的'+name)
                    return
                previous=node.center
            else:
                previous=None
            self.b.sleep(.4);s=self.observe()
        raise TaskBlocked('目标秘庭持续移动或未解锁，保留现场')

    def center_secret_nodes(self,s):
        for attempt in range(4):
            self.b.guard(s)
            if not is_tower_secret_list(s):raise TaskBlocked('秘庭居中时列表已改变')
            edge=next((w for w in secret_nodes(s) if w.box[0]<30 or w.box[0]+w.box[2]>1250),None)
            if edge is None:return s
            if attempt==3:raise TaskBlocked('秘庭编号仍贴近屏幕边缘，已居中3次，未点击截断编号')
            swipe=(1050,430,650,430) if edge.center[0]>640 else (250,430,650,430)
            self.note('秘庭编号靠近屏幕边缘，先移到中间再重新读取完整编号')
            self.b.audit({'action':'swipe','reason':'秘庭编号移到中间','from':list(swipe[:2]),'to':list(swipe[2:])})
            if not self.b.wait(self.b.controller.post_swipe(*swipe,650)).succeeded:
                raise TaskBlocked('秘庭居中滑动未成功，未点击旧编号')
            self.b.sleep(.7);s=self.tower_secret_list()
        return s

    def tower_secrets(self,kind,attempted):
        if not self.options['tower']['secret_garden']:return 0
        self.note('检查所选塔的秘庭：'+kind['label'])
        s=self.open_tower(kind)
        if is_tower_map(s) and not is_tower_secret_list(s) and not s.find(r'^塔中秘庭\d+$',roi=(900,500,300,180)):
            # A newly opened race tower may have no secret unlocked yet.
            # Confirm once before moving on to the next selected tower.
            self.b.sleep(.5);s=self.observe()
            if is_tower_map(s) and not is_tower_secret_list(s) and not s.find(r'^塔中秘庭\d+$',roi=(900,500,300,180)):
                self.note(kind['label']+'暂无已解锁秘庭，继续下一座塔')
                return 0
        s=self.tower_secret_list(s)
        wins=0;last_team=object();seen_pages=set();scrolls=0
        def prepare(q,team):
            nonlocal last_team
            if last_team!=team:q=self.select_team(q,team);last_team=team
            return q
        while True:
            try:self.check_budget('tower')
            except BudgetReached:break
            s=self.center_secret_nodes(s)
            names=[x for x in secret_candidates(s) if x not in attempted]
            if not names:
                if secret_locked_nodes(s):
                    # Confirm an animated frame once without navigating. There
                    # is no reason to scroll through later locked secret nodes.
                    self.b.sleep(.5);s=self.tower_secret_list()
                    if any(x not in attempted for x in secret_candidates(s)):continue
                    if secret_locked_nodes(s):
                        self.note(kind['label']+'已解锁秘庭已检查，后续秘庭尚未解锁');break
                page=tuple(sorted(w.text for w in s.words if re.fullmatch(SECRET_NODE_PATTERN,w.text)))
                if page in seen_pages or scrolls>=12:break
                seen_pages.add(page);scrolls+=1
                self.b.guard(s)
                self.b.audit({'action':'swipe','reason':'查看当前塔右侧秘庭','tower':kind['id']})
                self.b.wait(self.b.controller.post_swipe(1080,430,350,430,650))
                self.b.sleep(.7);s=self.tower_secret_list();continue
            name=names[0];attempted.add(name)
            first=[s]
            def opener():
                q=first.pop() if first else self.tower_secret_list()
                self.click_tower_secret_node(q,name)
                return self.await_detail()
            try:
                if self.play_encounter('tower',opener,'塔中秘庭免费',
                                       lambda q:self.verify_tower_secret(q,name),prepare_team=prepare):wins+=1
            except ChallengeLocked as e:
                self.note(f'{name}需要探索者等级{e.level}，跳过后续秘庭');break
            except BudgetReached:break
            s=self.tower_secret_list()
        ratio=self.dungeon_ratio('tower',s,(1030,0,170,65))
        if ratio:self.report.setdefault('dungeon_resources',{})['tower']={
            'name':'浮空羽毛','remaining':ratio[0],'reserve':self.options['tower']['reserve_feathers']}
        return wins

    def tower(self):
        wins=0;secrets=0;touched=[];stop_towers=False;stop_floors=False;locked_towers=[]
        stop_reason='所选塔的当前可挑战层和秘庭已检查'
        secret_garden=self.options['tower']['secret_garden']
        teams=team_order(self.options['tower'])
        self._tower_kind=None
        for kind in selected_rows(self.options['tower'],'towers'):
            if stop_towers or (stop_floors and not secret_garden):break
            if not stop_floors:
                self.note('挑战浮空巨塔：'+kind['label'])
                s=self.open_tower(kind);n=None;started=False;team_index=0;last_team=object()
            while not stop_floors:
                try:
                    self.check_budget('tower');team=teams[team_index]
                    if not started:
                        if is_tower_map(s):
                            self.verify_dungeon_resource('tower',s,(1030,0,170,65))
                            s,n=self.tower_open_floor(s,kind,n)
                        s=self.ensure_detail(s)
                        if tower_floor_number(s,kind)!=n:raise TaskBlocked('目标塔层不符')
                        if last_team!=team:s=self.select_team(s,team);last_team=team
                        self.verify_dungeon_resource('tower',s)
                        self.verify_instant_setting('tower',s)
                        self.check_budget('tower');self.active_task='tower'
                        self.start_challenge('tower',s,'浮空羽毛',lambda q:self.verify_dungeon_resource('tower',q))
                    if kind not in touched:
                        touched.append(kind)
                        self.report['tower_visited']=[row['id'] for row in touched]
                    self.active_task='tower'
                    try:result=self.battle('浮空羽毛');passed=True
                    except FightLost as lost:result=lost.screen;passed=False
                    target=('' if kind['id']=='normal' else kind['label']+'-')+f'浮空巨塔{n}'
                    self.report.setdefault('team_attempts',[]).append({'task':'tower','team':team,
                        'outcome':'victory' if passed else 'failed','target':target})
                    self.note(('挑战胜利：' if passed else '挑战未通过：')+target+
                              (f'（队伍{team}）' if team else ''))
                    self.checkpoint();started=False
                    if passed:wins+=1;n+=1;team_index=0
                    else:team_index+=1
                    # The balance is shared by every race. A spent last feather
                    # ends the entire floor loop, including failure fallbacks.
                    ratio=self.dungeon_ratio('tower',result)
                    if ratio:
                        self.verify_dungeon_resource('tower',result)
                    else:
                        # Some settlement layouts omit the resource. Read the
                        # current map once rather than assume another attempt.
                        s=self.tower_map(result)
                        self.verify_dungeon_resource('tower',s,(1030,0,170,65))
                    self.check_budget('tower')
                    if not passed and team_index>=len(teams):
                        self.note(f'{kind["label"]}{n}层所选阵容均未通过');break
                    if passed and team==teams[0] and ratio and result.find(r'下一[关层]$'):
                        s,started=self.tower_advance(result,kind,n)
                    elif ratio:s=self.tower_map(result)
                except ChallengeLocked as e:
                    message=f'{kind["label"]}{n}层需要探索者等级{e.level}，跳过该塔层，继续秘庭和其他已选巨塔'
                    self.note(message);locked_towers.append({'tower':kind['id'],'floor':n,'required_level':e.level})
                    # Prior floors can already have unlocked this tower's
                    # secret rooms even when today's first floor is gated.
                    if n and n>1 and kind not in touched:
                        touched.append(kind);self.report['tower_visited']=[row['id'] for row in touched]
                    break
                except ResourceReserveReached as e:
                    stop_reason=str(e);self.note(stop_reason);stop_floors=True;break
                except BudgetReached as e:
                    stop_reason=str(e);self.note(stop_reason);stop_towers=True;break
            # Each selected tower can have unlocked free secret rooms even
            # when no regular floor was attempted in this run.
            if secret_garden and not stop_towers:
                try:
                    self.check_budget('tower')
                    secrets+=self.tower_secrets(kind,set())
                    self.check_budget('tower')
                except BudgetReached as e:
                    stop_reason=str(e);self.note(stop_reason);stop_towers=True
        self.report['tower_summary']={'floors_won':wins,'secrets_won':secrets,
            'visited':[kind['id'] for kind in touched],'level_locked':locked_towers}
        skipped=f'；等级未解锁跳过{len(locked_towers)}座塔的后续层' if locked_towers else ''
        self.home();return f'巨塔通关{wins}层，秘庭{secrets}关{skipped}；停止原因：{stop_reason}'

    def tower_next_floor(self,s):
        current_pattern='^回到当前$'
        current_roi=(35,220,140,85)

        def return_to_current(q):
            if self.tower_navigation_state(q)!='floors':return
            button=q.find(current_pattern,current_roi)
            if button:
                self.b.click_at(q,button.center,['^浮空巨塔$',current_pattern],'回到当前塔层')

        for attempt in range(5):
            self.b.guard(s)
            if self.tower_navigation_state(s)!='floors':raise TaskBlocked('巨塔地图已改变')
            floor=next_tower_floor(s)
            if floor:return s,floor
            if s.find(current_pattern,current_roi):
                self.note('当前塔层不在画面内，点击「回到当前」重新定位')
                return_to_current(s)
                s=self.wait_for_screen(lambda q:self.tower_navigation_state(q)=='floors' and next_tower_floor(q) is not None,
                                       '回到当前塔层并核对相邻层',timeout=4,retry_navigation=return_to_current)
                return s,next_tower_floor(s)
            if attempt==0:self.note('塔层数字被遮挡，等待重识别下一层')
            self.b.sleep(.8);s=self.observe()
        raise TaskBlocked('下一相邻塔层未读清，未点击更高的未解锁层')

    def cocoon_menu(self):
        s=self.observe();self.b.guard(s)
        if not s.has('^永生之茧$','^刷新$'):s=self.enter_overview('^永生之茧$')
        if not s.has('^永生之茧$','^刷新$'):raise TaskBlocked('茧副本列表未识别')
        return s

    def cocoon_daily_done(self,s):
        # The completed daily cards have cracks and dim gold lettering. These
        # templates contain only the cracks, excluding the changing task names.
        if not s.has('^永生之茧$','^刷新$'):return set()
        rois={'left':(318,613,178,34),'middle':(551,646,177,38),'right':(796,613,169,34)}
        done=set()
        for key,roi in rois.items():
            if self.b.match_template(s,'cocoon-daily-done-'+key+'.png',list(roi),.80):
                done.add('lower_'+key);continue
            # Blue particles can hide one part of the fracture. Require two
            # independent, high-confidence fragments instead of lowering the
            # whole-image threshold until intact cards start to match.
            x,y,w,h=roi;x+=2;y+=2;w-=4;h-=4;hits=0
            for i in range(3):
                a=x+(w*i)//3;b=x+(w*(i+1))//3
                if self.b.match_template(s,f'cocoon-daily-done-{key}-part{i}.png',[a-2,y-2,b-a+4,h+4],.90):hits+=1
            if hits>=2:done.add('lower_'+key)
        return done

    def cocoon_daily_done_stable(self,s):
        frames=[self.cocoon_daily_done(s)]
        for _ in range(2):
            self.b.sleep(.35);s=self.observe();self.b.guard(s)
            if not s.has('^永生之茧$','^刷新$'):raise TaskBlocked('核对每日完成状态时茧列表改变')
            frames.append(self.cocoon_daily_done(s))
            if len(frames)==2 and frames[0]==frames[1]:return s,frames[0]
        return s,{key for key in COCOON_DAILIES if sum(key in frame for frame in frames)>=2}

    def cocoon_refresh(self,s):
        options=self.options['cocoon']
        if not options['daily_tasks'] or not options['refresh_tasks']:return False
        refreshes=self.report.get('cocoon_refreshes',0)
        if limit_reached(options['max_refreshes'],refreshes):return False
        # Recheck the current cards on another fresh frame. A missed entry click,
        # an old victory or a daily reset must never authorize overwriting tasks.
        if self.cocoon_daily_done(s)!=set(COCOON_DAILIES):return False
        self.b.sleep(.5);s=self.observe();self.b.guard(s)
        if self.cocoon_daily_done(s)!=set(COCOON_DAILIES):return False
        ratio=parse_ratio(s.region_text((925,0,135,65)))
        if not ratio:raise TaskBlocked('刷新前尖刺余额未识别')
        usable=ratio[0]-cocoon_reserve(options)
        required=3 if options['refresh_require_three_spikes'] else 1
        if usable<required:
            self.note(f'可用尖刺 {usable}，不足 {required} 个，保留魔典');return False
        books=self.b.read_number(s,(1158,13,25,27))
        if books is None:raise TaskBlocked('魔典库存未识别')
        self.resource_balance('cocoon','魔典',books)
        if books==0:return False
        self.note(f'三项每日均已完成，使用 1 个库存魔典（可用尖刺 {usable}）')
        self.b.click_text(s,'^刷新$')
        for _ in range(5):
            after=self.observe('cocoon-refresh');self.b.guard(after)
            if after.has('^永生之茧$','^刷新$'):
                new_books=self.b.read_number(after,(1158,13,25,27))
                new_spikes=parse_ratio(after.region_text((925,0,135,65)))
                if new_books==books-1:
                    self.resource_spent('cocoon','魔典',1,new_books)
                    self.report['cocoon_refreshes']=refreshes+1
                    if not new_spikes or new_spikes[0]-cocoon_reserve(options)<required:
                        raise TaskBlocked('刷新后可用尖刺与预期不符，已保留新任务并停止')
                    if not self.cocoon_daily_done(after):return True
            self.b.sleep(.8)
        raise TaskBlocked('魔典刷新结果未确认，不重复刷新')

    def cocoon_open_card(self,s,key,label):
        cards={k:point for k,_,point in COCOON_CARDS}
        for _ in range(2):
            self.b.guard(s)
            if not s.has('^永生之茧$','^刷新$'):raise TaskBlocked('打开前茧列表已改变')
            self.b.click_at(s,cards[key],['^永生之茧$','^刷新$'],'进入'+label)
            for _ in range(4):
                q=self.observe();self.b.guard(q)
                if enemy_formation(q) and q.find('^排阵$'):return self.ensure_detail(q)
                self.b.sleep(.5)
            s=q
            if key in self.cocoon_daily_done(s):return None
            if not s.has('^永生之茧$','^刷新$'):
                from .dungeon_labels import cocoon_detail_layout
                if cocoon_detail_layout(s):
                    raise TaskBlocked('已打开“'+label+'”详情，但敌方阵容局部补读4次仍未确认，不重复点击副本卡片')
                raise TaskBlocked('点击“'+label+'”后页面未确认，不重复点击副本卡片；该项未记为完成')
        title_rois={'lower_left':(300,565,210,65),'lower_middle':(500,595,280,65),'lower_right':(775,565,220,65)}
        title=s.region_text(title_rois[key]).strip() if key in title_rois else label
        raise TaskBlocked('点击“'+(title or label)+'”后未进入挑战详情，停止重试；该项未记为完成')

    def cocoon(self):
        options=self.options['cocoon'];rows=selected_rows(options,'targets')
        daily_rows=[{'id':k,'label':label} for k,label,_ in COCOON_CARDS if k in COCOON_DAILIES] if options['daily_tasks'] else []
        counts=defaultdict(int,self.report.get('cocoon_counts',{}))
        unavailable=set(self.report.get('cocoon_unavailable',[]));failed=set(self.report.get('cocoon_failed',[]))
        completed=set();wins=0
        reason='所选项目均已完成或游戏次数已用完'
        self.report['cocoon_counts']=counts;self.report.setdefault('cocoon_refreshes',0)
        while rows or daily_rows:
            self.check_budget('cocoon');s=self.cocoon_menu()
            try:self.verify_dungeon_resource('cocoon',s,(925,0,135,65))
            except ResourceReserveReached as e:reason=str(e);self.note(reason);break
            if daily_rows and completed!=set(COCOON_DAILIES):
                s,observed_done=self.cocoon_daily_done_stable(s);completed.update(observed_done)
            pending=[r for r in daily_rows if r['id'] not in completed|failed]
            if not pending and completed==set(COCOON_DAILIES):
                self.note('三项每日已完成，检查魔典刷新设置和材料副本')
                if self.cocoon_refresh(s):
                    # Every refreshed batch gets its own three dailies.
                    completed.clear();continue
                s=self.cocoon_menu()
            candidates=pending or [r for r in rows if r['id'] not in unavailable|failed]
            if not candidates:
                if failed:reason=f'所选阵容未通过{len(failed)}项，其余所选项目已处理'
                break
            row=candidates[0];key=row['id'];is_daily=key in COCOON_DAILIES
            detail=self.cocoon_open_card(s,key,row['label'])
            if detail is None:
                completed.add(key);continue
            remaining=detail.find('剩余次数')
            if remaining and (parsed:=parse_ratio(remaining.text)) and parsed[0]==0:
                (completed if is_daily else unavailable).add(key)
                self.report['cocoon_unavailable']=sorted(unavailable)
                self.back_detail(detail);continue
            def started():counts[key]+=1
            def verify(q):
                self.verify_dungeon_resource('cocoon',q)
                remaining=q.find('剩余次数')
                if remaining and (value:=parse_ratio(remaining.text)) and value[0]==0:
                    raise BudgetReached('该副本当日次数已用完')
            first=[detail]
            def opener():
                if first:return first.pop()
                q=self.cocoon_open_card(self.cocoon_menu(),key,row['label'])
                if q is None:raise TaskBlocked('重试前每日状态已变化')
                return q
            success=self.play_encounter('cocoon',opener,'永生尖刺',verify,on_started=started)
            if success:
                wins+=1
                if is_daily:completed.add(key)
            else:
                failed.add(key);self.report['cocoon_failed']=sorted(failed)
        self.report['cocoon_counts']=dict(counts);self.report['cocoon_failed']=sorted(failed)
        self.home()
        return f'茧副本通关{wins}次，魔典刷新{self.report["cocoon_refreshes"]}次，未通过{len(failed)}项；停止原因：{reason}'

    def copy_list(self):
        s=self.observe();self.b.guard(s)
        if is_copy_list(s):return s
        self.note('打开异象列表')
        prepared=self.overview_prepared_for('copies')
        try:
            s=self.open_anomaly_list(s)
            if not is_copy_list(s):raise TaskBlocked('复制体列表未识别')
        except EncounterInterrupted:
            # A portal/merchant was just handled. The encounter loop already
            # reopens fresh rows with a bounded interruption budget.
            raise
        except TaskBlocked as e:
            if prepared:raise  # The same overview route must not be replayed.
            s=self.overview_entry('copies',reason='异象事件入口未确认（'+str(e)+'）')
            if not is_copy_list(s):raise TaskBlocked('任务挑战已跳转异象，但复制体列表未识别')
        self.copy_scroll_steps=0
        return s

    def copy_kind(self,s,quota):
        if self.b.match_template(s,'copy-own-exp50.png',[30,590,110,90]):return 'own'
        # A positive icon/count alone is not sufficient after the weekly cap.
        if not self.options['copies']['include_friends'] or not friend_allowed(*quota):return None
        if s.find('本周.*(?:上限|已满)|奖励已满'):return None
        if not self.b.match_template(s,'copy-friend-coin.png',[30,590,110,90]):return None
        amount=self.b.read_number(s,(87,645,30,29))
        return 'friend' if amount is not None and amount>0 else None

    def read_copy_quota(self,s):
        # The gold number can be omitted while the white label is already
        # readable during list entry. Never borrow a player's numeric name.
        roi=(875,70,280,40)
        for attempt in range(4):
            self.b.guard(s)
            quota=friend_quota(s.region_text(roi)) if is_copy_list(s) else (None,None)
            source='list'
            if (quota[0] is None and is_copy_list(s) and
                    self.options['copies']['include_friends'] and self.b.tasker is not None):
                quota=friend_quota(self.b.read_text_crop(s,roi));source='crop'
            if quota[0] is not None:
                self.report['copy_friend_quota']={'points':quota[0],'cap':quota[1],
                                                 'source':source,'retries':attempt}
                return s,quota
            if not self.options['copies']['include_friends']:return s,quota
            if attempt<3:
                self.note(f'好友币额度数字未读清，原地补读 {attempt+1}/3')
                self.b.sleep(.6);s=self.observe()
        self.report['copy_friend_quota']={'points':None,'cap':None,'retries':3}
        if not is_copy_list(s):raise TaskBlocked('补读好友币额度时异象列表已改变，未打开其他目标')
        return s,(None,None)

    def copy_scroll(self,s,*,up=False):
        self.b.guard(s)
        if not is_copy_list(s):raise TaskBlocked('复制体列表已改变')
        start,end=(205,565) if up else (565,205)
        self.b.audit({'action':'swipe','reason':'复制体向上翻页' if up else '复制体向下翻页',
                      'from':[1000,start],'to':[1000,end],'status':'requested'})
        if not self.b.wait(self.b.controller.post_swipe(1000,start,1000,end,650)).succeeded:
            raise TaskBlocked('复制体翻页未成功，保留现场')
        self.b.audit({'action':'swipe','reason':'复制体向上翻页' if up else '复制体向下翻页','status':'sent'})
        self.b.sleep(1.3)
        return self.await_page(*COPY_LIST_ANCHORS)

    def copy_first_page(self,s):
        # We know how many downward swipes this worker made. Reverse them in
        # the list; never close the event panel just to return to its first page.
        for _ in range(getattr(self,'copy_scroll_steps',0)):
            before=copy_fingerprint(s);s=self.copy_scroll(s,up=True)
            if copy_fingerprint(s)==before:break
        self.copy_scroll_steps=0
        return s

    def open_copy_detail(self,s,y):
        s=self.read_copy_names(s)
        rows=copy_rows(s);names=copy_fingerprint(s)
        name=names[rows.index(y)]
        if not name:raise TaskBlocked('复制体列表名字未读清')
        self.b.click_at(s,(1000,y-35),list(COPY_LIST_ANCHORS),'检查复制体奖励')
        until=time.monotonic()+24;retry_at=time.monotonic()+3;retries=0
        choice_selected=False
        while time.monotonic()<until:
            s=self.observe();self.b.guard(s)
            self.resolve_path_event(s)
            if is_map_choice(s):
                if choice_selected:self.b.sleep(.6);continue
                header,_=map_choice_controls(s);cx,cy=header.center
                target=s.find('^'+re.escape(name)+'$',(cx-115,cy+55,260,min(350,710-cy-55)))
                if not target or not s.find('^复制体$',(target.center[0]-100,target.center[1]-48,200,40)):
                    raise TaskBlocked('重叠位置的复制体名字与原目标不符，未选择')
                self.b.click_at(s,target.center,['^请选择$','^复制体$','^'+re.escape(name)+'$'],'选择重叠位置的原复制体')
                choice_selected=True
                continue
            if s.has('敌方阵容','^排阵$'):return self.ensure_detail(s)
            if is_copy_list(s):
                s=self.read_copy_names(s)
                current=copy_fingerprint(s)
                if name not in current:return None  # Expired; rescan fresh rows.
                if retries<2 and time.monotonic()>=retry_at:
                    if current.count(name)!=1:raise TaskBlocked('复制体名字重复，无法重试同一目标')
                    y=copy_rows(s)[current.index(name)]
                    self.note('复制体详情尚未打开，原地重试：'+name)
                    self.b.click_at(s,(1000,y-35),list(COPY_LIST_ANCHORS),'重试打开同一复制体')
                    retries+=1;retry_at=time.monotonic()+5
            self.b.sleep(.8)
        raise TaskBlocked('复制体详情重试后仍未打开，保留截图')

    def read_copy_names(self,s):
        # Short names may disappear from full-frame text detection while the
        # countdown remains. Recognize that row alone before identifying it.
        from .backend import Screen,Word
        for y,name in zip(copy_rows(s),copy_fingerprint(s)):
            if name:continue
            roi=(910,y-65,270,37)
            text=self.b.read_text_crop(s,(910,y-65,270,44))
            if not text:continue
            words=[w for w in s.words if not (roi[0]<=w.center[0]<roi[0]+roi[2]
                    and roi[1]<=w.center[1]<roi[1]+roi[3])]
            words.append(Word(text,list(roi),.8))
            s=Screen(s.image,words,s.when)
        return s

    def copy_targets(self,wanted,excluded):
        sequential=wanted=='any'
        s=self.copy_list()
        if not sequential:s=self.copy_first_page(s)
        inspected=set(getattr(self,'copy_skipped_targets',())) if sequential else set()
        excluded=set(excluded)|set(self.report.get('copy_completed',[]))
        normalized={re.sub(r'[^\w\u4e00-\u9fff]','',name).rstrip('eo') for name in excluded}
        if sequential:inspected.update(normalized)
        scrolls=0
        # Returning from a detail may reset the list offset. Re-read positions
        # and skip inspected names instead of replaying an old page's row array.
        # Identity, ownership and positive rewards are still verified in detail.
        for _ in range(64):
            self.b.guard(s)
            s=self.claim_visible_copy_rewards(s)
            s,quota=self.read_copy_quota(s)
            s=self.read_copy_names(s)
            self.report['friend_points_text']=s.find(COPY_LIST_ANCHORS[1]).text
            if wanted=='friend' and not friend_allowed(*quota):return None
            rows=copy_rows(s);fingerprint=copy_fingerprint(s)
            if not rows:return None
            candidate=next(((y,name) for y,name in zip(rows,fingerprint) if name not in inspected),None)
            if candidate:
                y,name=candidate
                detail=self.open_copy_detail(s,y)
                if detail is None:
                    s=self.await_page(*COPY_LIST_ANCHORS);continue
                identity=encounter_identity(detail)
                if not identity:raise TaskBlocked('复制体名字未识别')
                kind=self.copy_kind(detail,quota)
                if sequential and kind is None and self.b.match_template(detail,'copy-friend-coin.png',[30,590,110,90]) and (
                        not self.options['copies']['include_friends'] or not friend_allowed(*quota)):
                    reason='未开启好友复制体' if not self.options['copies']['include_friends'] else '本周好友币已满' if quota[0] is not None and quota[0]>=quota[1] else '好友币额度未读清'
                    self.copy_stop_reason=reason+'，停止检查好友目标'
                    self.note(reason+'，已到好友目标区，停止继续扫描')
                    self.back_detail(detail);return None
                if (kind==wanted or (wanted=='any' and kind in ('own','friend'))) and identity not in excluded:
                    self.note('复制体目标：'+identity+'（'+('自己的50经验' if kind=='own' else '可获得好友币')+'）')
                    return {'page':scrolls,'y':y,'identity':identity,'kind':kind,'screen':detail,'quota':quota}
                inspected.add(name)
                inspected.add(re.sub(r'[^\w\u4e00-\u9fff]','',identity).rstrip('eo'))
                if sequential:self.copy_skipped_targets=set(inspected)
                returned=self.back_detail(detail)
                s=returned if is_copy_list(returned) else self.await_page(*COPY_LIST_ANCHORS)
                continue
            if scrolls>=24:break
            s=self.copy_scroll(s);scrolls+=1
            s=self.read_copy_names(s)
            self.copy_scroll_steps=getattr(self,'copy_scroll_steps',0)+1
            if copy_fingerprint(s)==fingerprint:return None
        raise TaskBlocked('复制体列表检查超过本轮范围，保留现场')

    def copy_battles(self):
        from .workflows import is_world
        self.collect_copy_rewards()
        s=self.observe()
        self.stamina_retry['copies']=False
        self.copy_stop_reason='列表中没有剩余可获奖励的目标'
        if is_world(s) or is_copy_list(s):
            ratio=parse_ratio(s.region_text((490,0,170,65)))
            if ratio:self.resource_balance('copies','地图体力',ratio[0])
            if ratio and ratio[0]<20:
                self.stamina_retry['copies']=True
                self.home();return '复制体体力不足20，补充免费体力后再检查目标'
        wins=0;failed=set(self.report.get('copy_failed',[]));self.own_copy_waiting=False
        path_handoffs=0
        # Own and friend copies share the same formation during this task.
        # Keep this local: a later invocation may follow other tasks or a user
        # change, and must confirm its first configured team again.
        last_team=object()
        def prepare_copy_team(detail,team):
            nonlocal last_team
            if team!=last_team:
                detail=self.select_team(detail,team);last_team=team
            return detail
        while True:
            target=None
            try:
                current=self.observe()
                if is_world(current) or is_copy_list(current):
                    balance=parse_ratio(current.region_text((490,0,170,65)))
                    if balance:self.resource_balance('copies','地图体力',balance[0])
                    if balance and balance[0]<20:
                        self.stamina_retry['copies']=True
                        self.home();return f'复制体通关{wins}次，体力剩余{balance[0]}，不足单次20，停止挑战'
                self.check_budget('copies');target=self.copy_targets('any',failed)
                if not target:break
                detail=target['screen'];ratio=parse_ratio(detail.region_text((1140,0,140,65)))
                if not ratio:raise TaskBlocked('复制体体力未识别')
                if ratio[0]<20:
                    self.stamina_retry['copies']=True
                    self.own_copy_waiting=target['kind']=='own';self.home();return f'复制体通关{wins}次，体力不足20'
                latest_quota=[target['quota']]
                def opener():
                    candidate=self.copy_targets('any',failed)
                    if not candidate or candidate['identity']!=target['identity']:raise TaskBlocked('复制体目标发生变化')
                    latest_quota[0]=candidate['quota']
                    return candidate['screen']
                def verify(q):
                    self.verify_stamina_cost(q,20)
                    if self.copy_kind(q,latest_quota[0])!=target['kind']:raise TaskBlocked('复制体奖励类型或额度未确认')
                # An already handled path event is not a failed copy fight.
                # Preserve real failed-team attempts when re-reading the list.
                used={row.get('team') for row in self.task_attempts('copies')
                      if row.get('target')==target['identity'] and row.get('outcome')=='failed'}
                teams=[team for team in team_order(self.options['copies']) if team not in used]
                first=[detail]
                if teams and self.play_encounter('copies',lambda:first.pop() if first else opener(),'地图体力20',verify,
                                               prepare_team=prepare_copy_team,teams_override=teams):
                    wins+=1
                    done=self.report.setdefault('copy_completed',[])
                    if target['identity'] not in done:done.append(target['identity'])
                    self.checkpoint()
                else:
                    failed.add(target['identity']);self.report['copy_failed']=sorted(failed)
                    if not teams:self.back_detail(detail)
                path_handoffs=0
            except EncounterInterrupted as event:
                path_handoffs+=1
                self.report.setdefault('copy_path_handoffs',[]).append({
                    'instance_id':self.report_key('copies'),
                    'target':target['identity'] if target else None,
                    'message':str(event),'consecutive':path_handoffs})
                self._challenge_entry=None;self._overview_ready=None;last_team=object()
                self.checkpoint()
                if path_handoffs>=3:
                    from .policy import IsolatedTaskError
                    raise IsolatedTaskError('异象连续3次处理寻路事件后仍未进入目标，本项回退后继续下一任务') from event
                self.note('异象寻路事件已处理，重新读取列表、目标奖励和体力后继续；已完成目标不重打')
        self.home();return f'复制体通关{wins}次，未通过{len(failed)}个目标；停止原因：{self.copy_stop_reason}'

    def stamina_offer(self):
        self.activity_tab('每日三发')
        s=self.wait_for_screen(lambda q:stamina_servings(q) is not None,
                               '核对每日三发领取页面及存量',timeout=4)
        self.b.guard(s)
        self.report['stamina_offer_text']=s.text
        self.b.save_screen(s,self.report['folder']/f'stamina-offer-{self.report.get("stamina_claims",0)}.png')
        servings=stamina_servings(s)
        if servings is None:
            raise TaskBlocked('每日三发领取页面或存量标记未确认')
        if servings is not None:self.report['stamina_servings_available']=servings
        if servings==0 or not s.find(STAMINA_CLAIM):
            self.note('每日三发当前没有可领取的免费体力');return None
        if s.find('补领|购买',roi=(350,400,650,280)):raise TaskBlocked('三发不是明确免费领取')
        return s

    def stamina_progress(self,phase,message):
        self.report.setdefault('stamina_refill',{}).update(
            status='running',phase=phase,message=message,claimed=self.report.get('stamina_claims',0))
        self.note(message);self.b.progress(message);self.checkpoint()

    def try_stamina_refill(self,source):
        """Recover a failed refill locally and leave its consumption record intact."""
        free=source=='free'
        unavailable='_stamina_free_unavailable' if free else '_stamina_potions_unavailable'
        if getattr(self,unavailable,False):return None
        try:
            return self.claim_free_stamina() if free else self.use_stamina_potion()
        except (TaskBlocked,PageChanged) as error:
            setattr(self,unavailable,True)
            reason=('stamina_free_reason' if free else 'stamina_potion_reason')
            setattr(self,reason,str(error))
            self.report.setdefault('stamina_refill_failures',[]).append({
                'source':source,'task':self.active_task,'reason':str(error)})
            self.note(('每日三发' if free else '移动力药水')+'补充失败，回退后继续：'+str(error))
            self.checkpoint()
            self.recover_failed_task()
            return None

    def claim_free_stamina(self):
        """Claim one verified free serving; caller already confirmed its outlet."""
        self.b.check_stop()
        if getattr(self,'_stamina_free_unavailable',False):return None
        if self.report.get('stamina_claims',0)>=3:
            self.stamina_free_reason='本轮已领取3份每日三发';return None
        receipts=self.report.setdefault('stamina_free_receipts',[])
        if any(row['status']!='confirmed' for row in receipts):
            raise TaskBlocked('上次每日三发到账未核实，不重复领取')
        before=self.world_resources(self.home())
        if not can_claim_stamina(before['stamina'],before['stamina_cap']):
            self.stamina_free_reason='当前体力或上限未确认，或无法容纳100体力';return None
        self.stamina_progress('opening_offer','体力补充：已确认可挑战目标，前往每日三发领取100体力')
        s=self.stamina_offer()
        if s is None:
            self._stamina_free_unavailable=True
            self.stamina_free_reason='每日三发当前没有可领取的免费体力'
            self.home();return None
        self.stamina_progress('claiming','每日三发：正在领取1份免费体力（100点）')
        receipt={'status':'confirming','before':before['stamina'],'task':self.active_task}
        receipts.append(receipt);self.checkpoint()
        self.b.click_text(s,STAMINA_CLAIM,roi=(350,400,650,280));reward=self.observe()
        if reward.find('获得'):
            self.b.click_at(reward,(640,660),['获得'],'关闭三发奖励')
        self.stamina_progress('verifying','每日三发：已发送领取，正在核对100体力到账')
        after=self.world_resources(self.home())
        receipt['after']=after['stamina']
        if after['stamina'] is None or not 100<=after['stamina']-before['stamina']<=102:
            raise TaskBlocked('100体力到账未核实')
        receipt['status']='confirmed'
        self.report['stamina_claims']=self.report.get('stamina_claims',0)+1
        self.note('免费三发实际补充100体力');self.checkpoint()
        return 100

    def replenish_stamina(self):
        selected=[x for x in self.b.settings['stamina_order'] if x in self.selected and
                  (x!='copies' or self.options['copies']['challenge_copies']) and
                  (self.options[x]['auto_three_shots'] or self.options[x]['auto_potions'])]
        if not selected:return '体力补充已关闭，或没有勾选使用体力的玩法'
        no_free=getattr(self,'_stamina_free_unavailable',False)
        no_potions=getattr(self,'_stamina_potions_unavailable',False)
        while self.battles<self.limit:
            s=self.home();r=self.world_resources(s)
            if r['stamina'] is None or r['stamina_cap'] is None:break
            if r['stamina']>=max({'copies':20,'hunt':10,'main':5}[t] for t in selected):break
            free=[t for t in selected if self.options[t]['auto_three_shots']]
            bottles=[t for t in selected if self.options[t]['auto_potions']]
            source=None;eligible=[]
            if free and not no_free and self.report.get('stamina_claims',0)<3 and can_claim_stamina(r['stamina'],r['stamina_cap']):
                self.stamina_progress('checking_target',f'体力补充：当前{r["stamina"]}/{r["stamina_cap"]}，先确认可以继续挑战的目标')
                # Confirm a usable outlet before opening the reward page. Once
                # it is open, claim directly instead of leaving to probe tasks
                # and visiting the exact same reward page a second time.
                if self.stamina_outlet_available(free,r['stamina']):source='free';eligible=free
                else:
                    no_free=True
                    self.note('体力补充：所选玩法暂未找到可继续挑战的目标，本次不领取三发')
                self.home()
            if (source is None and bottles and not no_potions and not getattr(self,'_stamina_potions_unavailable',False)
                    and can_claim_stamina(r['stamina'],r['stamina_cap'])):
                self.stamina_progress('checking_target','体力补充：正在核对库存药水对应的可挑战目标')
                if self.stamina_outlet_available(bottles,r['stamina']):source='potion';eligible=bottles
                else:no_potions=True
                self.home()
            if source is None:break
            if source=='free':
                gain=self.try_stamina_refill('free')
                if gain is None:no_free=True;continue
            else:
                self.stamina_progress('opening_inventory','体力补充：正在检查库存移动力药水')
                gain=self.try_stamina_refill('potion')
                if gain is None:no_potions=True;continue
                self.report['stamina_potion_count']=self.report.get('stamina_potion_count',0)+1
                self.note(f'库存移动力药水实际补充{gain}体力')
            s=self.home();after=self.world_resources(s)
            self.stamina_progress('spending','体力补充：到账已确认，按所选顺序继续挑战')
            self.checkpoint()
            before=after['stamina']
            pending=[t for t in eligible if self.stamina_retry.get(t,True) and
                     self.report.get('tasks',{}).get(self.report_key(t),{}).get('status')!='blocked' and
                     not limit_reached(self.options[t].get('max_runs',0),self.task_counts.get(t,0))]
            while pending:
                task=self.next_daily_task(pending);pending.remove(task)
                self.execute_task(task)
            balance=self.world_resources(self.home())['stamina']
            if balance is None or balance>=before:break
        self.report['stamina_refill']={'status':'done','claimed':self.report.get('stamina_claims',0),'potions':self.report.get('stamina_potion_count',0)}
        return f'本轮免费三发累计领取{self.report.get("stamina_claims",0)}份，库存移动力药水使用{self.report.get("stamina_potion_count",0)}瓶，已按设置处理新增体力'

    def stamina_outlet_available(self,selected,balance):
        for task in selected:
            if task=='copies' and not self.options['copies']['challenge_copies']:continue
            # Refill only when this activity actually lacks stamina. A stopped or
            # failed queue with enough stamina must not collect another serving.
            if balance is None or balance>={'copies':20,'hunt':10,'main':5}[task]:continue
            if not self.stamina_retry.get(task,True):continue
            if self.report.get('tasks',{}).get(self.report_key(task),{}).get('status')=='blocked':continue
            if limit_reached(self.options[task].get('max_runs',0),self.task_counts.get(task,0)) or self.battles>=self.limit:continue
            self.stamina_progress('checking_target','体力补充：正在检查'+{'copies':'复制体','hunt':'狩猎','main':'主线关卡'}[task]+'是否有可挑战目标')
            if task=='copies':
                failed=set(self.report.get('copy_failed',[]))
                # Stop at the first eligible row. Finished identities persist
                # across refills, so an old list row cannot start another fight.
                candidate=self.copy_targets('any',failed)
                if candidate:self.home();return True
            if task=='hunt':
                s=self.hunt_menu()
                present=bool(hunt_rows(s))
                if not present:
                    # A verified search opportunity is enough to resume hunt.
                    # Spend its token only in hunt(), after stamina arrived;
                    # checking an empty three-shots page must not waste tokens.
                    present=self.hunt_search_offer(s) is not None
                self.home()
                if present:return True
            if task=='main':
                if self.main_search_limit_reached():continue
                excluded=set(self.report.get('main_failed',[]))
                excluded.update(n for n,e in self.report.get('main_stage_progress',{}).items() if e['cleared'])
                s=self.main_overview_detail()
                if s is None:s=self.find_main_candidate(excluded)
                if s is None:continue
                identity=main_identity(s)
                available=identity is not None and identity not in excluded and bool(s.find('^首通奖励$')) and not self.record_locked_main(s)
                self.home()
                if available:return True
        return False
