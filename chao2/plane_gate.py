"""Dismiss the verified plane-gate window without choosing a new destination."""
import re
from functools import lru_cache
import cv2
from .backend import ROOT,Word
from .policy import TaskBlocked

GATE_TITLE=r'^[\u4e00-\u9fff]{1,8}之门$'
GATE_REQUIREMENT=r'^解锁条件\s*[:：]\s*世界总探索度到达\s*\d+(?:\.\d+)?\s*[%％]$'


def plane_gate_window(s):
    title=s.find(GATE_TITLE,(210,60,490,65))
    requirement=s.find(GATE_REQUIREMENT,(430,145,560,70))
    entry=s.find('^进入$|^未解锁$',(535,400,205,115))
    if not (title and requirement and entry):return None
    if s.find('^取消$|^确定$|^购买$|^获得奖励$|^退出$|^排阵$'):return None
    return title,requirement,entry


@lru_cache(maxsize=1)
def gate_close_template():
    return cv2.imread(str(ROOT/'resource/image/plane-gate-close.png'))


def plane_gate_close(s):
    if not plane_gate_window(s):return None
    return gate_close_icon(s)


def gate_close_icon(s):
    left,top,width,height=995,40,85,85
    crop=s.image[top:top+height,left:left+width];template=gate_close_template()
    if template is None or crop.shape[0]<template.shape[0] or crop.shape[1]<template.shape[1]:return None
    _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(crop,template,cv2.TM_CCOEFF_NORMED))
    if score<.9:return None
    return Word('×',[left+point[0],top+point[1],template.shape[1],template.shape[0]],float(score))


class PlaneGateNavigation:
    def close_plane_gate(self,s):
        if not plane_gate_window(s):raise TaskBlocked('位面传送门窗口未确认，未点击')
        row={'title':plane_gate_window(s)[0].text,'task':self.active_task,'action':'close','clicks':0,'status':'pending'}
        events=self.report.setdefault('plane_gates',[]);events.append(row)
        self.b.save_screen(s,self.report['folder']/f'plane-gate-{len(events)}-before.png')
        self.note('检测到位面传送门窗口，关闭后重新定位原任务')
        for attempt in range(4):
            # A delayed transition can remove the window before this input.
            # Every retry uses a fresh frame, its own anchors and the X pixels.
            fresh=self.observe();self.b.guard(fresh)
            anchors=plane_gate_window(fresh)
            if not anchors:
                if gate_close_icon(fresh) is None:
                    row['status']='closed';self.checkpoint();return fresh
                # The X is still drawn, so a missing OCR anchor is not proof
                # of successful dismissal. Wait for a complete fresh frame.
                self.b.sleep(.5);continue
            close=plane_gate_close(fresh)
            if close is None:
                row['status']='blocked';self.checkpoint()
                raise TaskBlocked('位面传送门叉号未确认，未点击其他位置')
            if attempt:self.navigation_retry('位面传送门仍在，重新确认叉号后关闭',attempt,fresh)
            self.b.click_at(fresh,close.center,['^'+re.escape(w.text)+'$' for w in anchors],
                            '关闭位面传送门，继续原任务')
            row['clicks']+=1
            for _ in range(6):
                q=self.observe();self.b.guard(q)
                if not plane_gate_window(q) and gate_close_icon(q) is None:
                    row['status']='closed';self.checkpoint();return q
                self.b.sleep(.5)
        row['status']='blocked';self.checkpoint()
        raise TaskBlocked('位面传送门关闭后仍未消失，已重试3次，保留现场')
