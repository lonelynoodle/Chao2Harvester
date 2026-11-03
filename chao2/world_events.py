"""World-map interruptions; their battles are separate from the pending task."""
import re
from functools import lru_cache
import cv2
import numpy as np
from PIL import Image
from .backend import ROOT,Word
from .policy import TaskBlocked, SafetyStop, FightLost, EncounterInterrupted, parse_ratio
from .merchant import MerchantEvent,is_merchant
from .trigger_events import triggered_event
from .plane_gate import PlaneGateNavigation,plane_gate_window

AMBUSH_TITLE=r'^乱入\s*[-－—·:：]\s*敌袭\s*[-－—·:：].+'

def ambush_identity(s):
    title=s.find(AMBUSH_TITLE,(20,115,520,65))
    return title.text if title else None

def is_ambush(s):
    return bool(ambush_identity(s) and s.find('^敌方阵容$',(1050,110,230,90)) and
                s.find('^逃跑$',(625,590,130,85)) and s.find('^排阵$',(765,590,180,85)) and
                s.find('^挑战$',(960,590,280,85)) and s.find('可获得奖励',(15,540,240,55)))

def map_choice_controls(s):
    header=s.find('^请选择$',(220,100,900,470))
    # This modal blurs the world HUD: e.g. 7/166 was read as just 66.
    # Its own title, relative close button and a known target row are evidence;
    # an unrelated background resource must not prevent dismissing it.
    if not header or s.find('^敌方阵容$'):return None
    x,y=header.center
    close=s.find('^[xX×]$',(x+90,y-35,100,70))
    if not (s.find('^复制体$',(x-115,y+40,260,min(350,710-y-40))) or
            map_choice_hunt_rows(s,header)):return None
    if not close:
        # The stylized gold X was actually read as both x and o. Confirm its
        # pixels in the header-relative close area instead of accepting 'o'.
        template=map_choice_close_template()
        left,top=x+90,y-35;crop=s.image[top:top+70,left:left+100]
        if crop.shape[0]<template.shape[0] or crop.shape[1]<template.shape[1]:return None
        _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(crop,template,cv2.TM_CCOEFF_NORMED))
        if score<.9:return None
        close=Word('×',[left+point[0],top+point[1],template.shape[1],template.shape[0]],float(score))
    return header,close

@lru_cache(maxsize=1)
def map_choice_close_template():
    return np.array(Image.open(ROOT/'resource/image/map-choice-close.png').convert('RGB'))[:,:,::-1].copy()

def is_map_choice(s):
    return map_choice_controls(s) is not None


def map_choice_hunt_rows(s,header):
    x,y=header.center
    rows=[w for w in s.words if w.text=='狩猎' and
          x-115<=w.center[0]<x+145 and y+40<=w.center[1]<min(710,y+390)]
    if not rows:return []
    if (s.find('^狩猎$',(900,0,240,75)) and
            s.find('^商店$',(1000,65,200,80)) and s.find('^传送$',(1200,315,80,85))):return rows
    # After a merchant/ambush the client resumes its route on the WORLD map,
    # with no hunt sidebar. Recognize the modal's own unknown-hunter icon and
    # two-line label; the blurred background HUD is not required evidence.
    if s.find('^取消$|^确定$|^购买$|^获得奖励$|^排阵$|^退出$'):return []
    template=map_choice_hunter_template()
    for row in rows:
        rx,ry=row.center
        if not s.find('^未知$',(rx-95,ry+8,190,45)):continue
        left,top=max(0,x-185),max(0,ry-22)
        crop=s.image[top:top+90,left:left+105]
        if crop.shape[0]<template.shape[0] or crop.shape[1]<template.shape[1]:continue
        _,score,_,_=cv2.minMaxLoc(cv2.matchTemplate(crop,template,cv2.TM_CCOEFF_NORMED))
        if score>=.9:return rows
    return []


@lru_cache(maxsize=1)
def map_choice_hunter_template():
    return np.array(Image.open(ROOT/'resource/image/map-choice-hunter.png').convert('RGB'))[:,:,::-1].copy()


def map_choice_hunt_target(s):
    controls=map_choice_controls(s)
    if not controls:return None
    rows=map_choice_hunt_rows(s,controls[0])
    return rows[0] if len(rows)==1 else None


def map_choice_main_target(s):
    """Only the observed crossed-swords row; never the adjacent player's copy."""
    controls=map_choice_controls(s)
    if not controls:return None
    x,y=controls[0].center
    left,top=max(0,x-175),y+32
    template=map_choice_swords_template()
    crop=s.image[top:min(680,y+350),left:left+90]
    if crop.shape[0]<template.shape[0] or crop.shape[1]<template.shape[1]:return None
    _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(crop,template,cv2.TM_CCOEFF_NORMED))
    if score<.9:return None
    row_y=top+point[1]+template.shape[0]//2
    title=s.find(r'^[\u4e00-\u9fff\dⅠⅡⅢIVX·—－ -]{2,24}$',(x-85,row_y-25,225,50))
    if not title or title.text in ('复制体','请选择'):return None
    return title


@lru_cache(maxsize=1)
def map_choice_swords_template():
    return np.array(Image.open(ROOT/'resource/image/map-choice-swords.png').convert('RGB'))[:,:,::-1].copy()

def verify_ambush(b,s,identity):
    b.guard(s)
    if not is_ambush(s) or ambush_identity(s)!=identity:raise TaskBlocked('敌袭乱入目标已改变')
    if re.search(r'\d|消耗|购买|钻石',s.region_text((960,590,280,90))):
        raise SafetyStop('敌袭挑战出现费用，未点击')
    if not b.match_template(s,'ambush-free-challenge.png',[950,585,285,95],.9):
        raise TaskBlocked('敌袭免费挑战按钮未确认')
    balance=parse_ratio(s.region_text((1140,0,140,65)))
    if balance is None:raise TaskBlocked('敌袭页面体力余额未读清')
    return balance[0]

class WorldEvents(PlaneGateNavigation,MerchantEvent):
    def resolve_path_event(self,s):
        if plane_gate_window(s):
            self.close_plane_gate(s)
            raise EncounterInterrupted('位面传送门已关闭，重新定位原目标')
        kind=triggered_event(s)
        if kind=='merchant':
            self.handle_merchant(s)
        elif kind=='sage_quiz' and not getattr(self,'_sage_active',False):
            if self.resume_sage_dialog(s) is None:return
        elif is_ambush(s):
            self.handle_ambush(s)
        else:return
        raise EncounterInterrupted('寻路事件已处理，重新定位原目标')

    def close_map_choice(self,s):
        if not is_map_choice(s):raise TaskBlocked('地图重叠目标选择框未确认')
        _,close=map_choice_controls(s)
        self.b.click_at(s,close.center,['^请选择$'],'收起地图重叠目标选择框')
        return self.observe()

    def handle_ambush(self,s):
        identity=ambush_identity(s)
        before=verify_ambush(self.b,s,identity)
        if self.battles>=self.limit:raise SafetyStop('遭遇敌袭，但本轮挑战上限已到，保留现场')
        self.note('遭遇'+identity+'，先用当前阵容处理，随后继续原任务')
        fresh=self.observe();verify_ambush(self.b,fresh,identity)
        self.b.save_screen(fresh,self.report['folder']/f'ambush-{len(self.report.get("ambushes",[]))+1}-entry.png')
        previous=self.active_task
        row={'target':identity,'source_task':previous,'stamina_before':before,'status':'running'}
        self.report.setdefault('ambushes',[]).append(row)
        self.active_task='ambush'
        try:
            self.b.click_at(fresh,fresh.find('^挑战$',(960,590,280,85)).center,
                [re.escape(identity),'^敌方阵容$','^逃跑$','^挑战$'],'挑战免费敌袭乱入')
            try:result=self.battle('敌袭乱入免费')
            except FightLost as lost:
                row['status']='failed'
                self.b.save_screen(lost.screen,self.report['folder']/'ambush-failed.png')
                raise SafetyStop('敌袭乱入未通过，已停止，未重复挑战')
            row['status']='victory'
            self.b.save_screen(result,self.report['folder']/f'ambush-{len(self.report["ambushes"])}-result.png')
            after=parse_ratio(result.region_text((1140,0,140,65)))
            self.report.setdefault('team_attempts',[]).append({'task':'ambush','team':None,'outcome':'victory','target':identity})
            self.note('敌袭乱入已胜利：'+identity+'；单独记录，不计入原任务通关次数')
            self.exit_result(result)
            if after is None:
                for _ in range(4):
                    q=self.observe();self.b.guard(q)
                    after=parse_ratio(q.region_text((490,0,170,65))) or parse_ratio(q.region_text((1140,0,140,65)))
                    if after:break
                    self.b.sleep(.5)
            row['stamina_after']=after[0] if after else None
            row['stamina_spent']=0 if after and after[0]>=before else None
            if after and after[0]<before:raise SafetyStop('敌袭结束后体力下降，费用需核对，停止后续操作')
            self.checkpoint()
        finally:
            self.active_task=previous
