"""Recover a missing red heading only inside a complete known dungeon detail."""
from functools import lru_cache
import cv2
from .backend import ROOT,Screen,Word
from .tribe_totems import totem_identity

OVERLAY=r'^退出$|^获得奖励$|^取消$|^确定$|^配置$|^复制此配置$|^请选择$'
# The replay camera can join its label as "o" or "~" in full-frame OCR.
# Accept a short icon prefix only in the replay link's own fixed region.
REPLAY_LABEL=r'^[^\u4e00-\u9fff]{0,2}通关录像$'
REPLAY_ROI=(530,115,230,70)


@lru_cache(maxsize=1)
def heading_template():return cv2.imread(str(ROOT/'resource/image/enemy-formation-heading.png'))


def recover_heading(b,s,roi):
    fresh=Screen(s.image,list(s.words),s.when)
    pattern='^敌[方芳]阵容$'
    if b.tasker is not None:
        for scale in (3,4):
            if b.confirm_label(fresh,pattern,roi,scale=scale,threshold=.8):
                word=fresh.find(pattern,roi)
                if word is None:continue
                if word.text!='敌方阵容':fresh.words.append(Word('敌方阵容',list(word.box),word.score))
                return fresh
    template=heading_template()
    x,y,w,h=roi;crop=s.image[y:y+h,x:x+w]
    if template is None or crop.shape[0]<template.shape[0] or crop.shape[1]<template.shape[1]:return s
    _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(crop,template,cv2.TM_CCOEFF_NORMED))
    if score<.93:return s
    px,py=point;th,tw=template.shape[:2]
    fresh.words.append(Word('敌方阵容',[x+px,y+py,tw,th],float(score)))
    return fresh


def recover_secret_heading(b,s):
    from .activities import enemy_formation
    if (enemy_formation(s) or s.find(OVERLAY) or
            not s.find(r'^塔中秘庭\d+$',(150,80,550,80)) or
            not s.has('^首通奖励$','^排阵$','^挑战$|^前往挑战$')):return s
    return recover_heading(b,s,(760,85,170,65))


def recover_totem_heading(b,s):
    from .activities import enemy_formation
    if (enemy_formation(s) or s.find(OVERLAY) or not totem_identity(s) or
            not s.find('^排阵$',(765,590,180,85)) or
            not s.find('^挑战$',(960,590,280,85))):return s
    return recover_heading(b,s,(1080,115,200,80))


def recover_timed_encounter_heading(b,s):
    from .activities import enemy_formation,encounter_identity
    if (enemy_formation(s) or s.find(OVERLAY) or not encounter_identity(s) or
            not s.find('^排阵$',(765,590,180,85)) or
            not s.find('^前往挑战$',(960,590,280,85)) or
            not s.find('^可获得奖励$',(15,535,240,65)) or
            not s.find(r'^[^\d\s]{0,2}\d{1,2}:\d{2}(?::\d{2})?$',(520,110,230,70))):return s
    return recover_heading(b,s,(1080,115,200,80))


def cocoon_detail_controls(s):
    return bool(not s.find(OVERLAY) and
                s.find('^排阵$',(765,590,180,85)) and
                s.find('^挑战$',(960,590,280,85)) and
                s.find('^可获得奖励$',(15,535,240,65)) and
                s.find(REPLAY_LABEL,REPLAY_ROI))


def cocoon_daily_detail_layout(s):
    from .activities import encounter_identity
    return bool(cocoon_detail_controls(s) and encounter_identity(s) and
                s.find('^好友助战$',(760,535,200,65)) and
                s.find(r'^\d{1,3}/\d{1,3}$',(1180,0,100,60)))


def cocoon_detail_layout(s):
    return bool(cocoon_detail_controls(s) and
                (s.find(r'^剩余次数\s*[:：]?\s*\d+/\d+$',(960,535,300,60)) or
                 cocoon_daily_detail_layout(s)))


def recover_cocoon_heading(b,s):
    from .activities import enemy_formation
    if enemy_formation(s) or not cocoon_detail_layout(s):return s
    # Daily encounters have two numbered formation tabs, moving the heading
    # left by 100px. Material encounters keep the right-hand heading.
    roi=(1010,115,140,70) if cocoon_daily_detail_layout(s) else (1080,115,200,80)
    return recover_heading(b,s,roi)


def recover_forest_heading(b,s):
    from .activities import enemy_formation
    from .forest import forest_detail_name
    if (enemy_formation(s) or s.find(OVERLAY) or not forest_detail_name(s) or
            not s.find('^排阵$',(765,590,180,85)) or
            not s.find('^挑战$',(960,590,280,85)) or
            not s.find('^可获得奖励$',(15,535,240,65))):return s
    return recover_heading(b,s,(1080,115,200,80))
