"""Segment the game's italic gold digits; used only for arena power, never costs."""
from functools import lru_cache
from pathlib import Path
import json
import cv2
import numpy as np


def glyphs(image,roi):
    x,y,w,h=roi;a=image[y:y+h,x:x+w].astype('int16')
    blue,green,red=(a[:,:,i] for i in range(3))
    mask=((red>190)&(green>150)&(blue<180)&(red-blue>55)).astype('uint8')
    _,labels,stats,_=cv2.connectedComponentsWithStats(mask)
    parts=sorted([tuple(map(int,r)) for r in stats[1:] if r[4]>=15 and r[3]>=12],key=lambda r:r[0])
    if not 2<=len(parts)<=8:return []
    if max(r[1]+r[3] for r in parts)-min(r[1]+r[3] for r in parts)>4:return []
    result=[]
    for px,py,pw,ph,area in parts:
        patch=mask[py:py+ph,px:px+pw]
        scale=min(14/pw,22/ph);nw=max(1,round(pw*scale));nh=max(1,round(ph*scale))
        normalized=np.zeros((24,16),np.uint8)
        normalized[(24-nh)//2:(24-nh)//2+nh,(16-nw)//2:(16-nw)//2+nw]=cv2.resize(patch,(nw,nh),interpolation=cv2.INTER_NEAREST)
        result.append(normalized)
    return result


@lru_cache(maxsize=1)
def bank():
    # Include verified render variants (notably the narrow 6 in six-digit
    # powers). Keep confidence/margin checks below; OCR must not fill gaps.
    data=json.loads((Path(__file__).resolve().parents[1]/'resource/arena-power-digits.json').read_text('utf-8'))
    return {key:[np.array(a,dtype=np.uint8).reshape(24,16) for a in values] for key,values in data.items()}


def arena_power_digits(s,roi):
    parts=glyphs(s.image,roi)
    if not parts:return None
    result=''
    for part in parts:
        scores=[]
        for digit,templates in bank().items():
            score=max(2*np.logical_and(part,t).sum()/(part.sum()+t.sum()) for t in templates)
            scores.append((score,digit))
        scores.sort(reverse=True)
        if scores[0][0]<.84 or scores[0][0]-scores[1][0]<.055:return None
        result+=scores[0][1]
    return int(result)
