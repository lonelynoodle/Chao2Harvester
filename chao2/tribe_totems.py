"""Observed tribe totem crests and their distinct, war-order-only detail page."""
from functools import lru_cache
from pathlib import Path
import cv2
import numpy as np


TOTEM_REWARD = r'^每次挑战奖励$'


def totem_score(s):
    return bool(s.find('^结算$',(0,180,550,310)) and
                s.find('^我方状态$',(800,175,280,85)) and
                s.find('^比拼方式$',(800,330,280,85)) and
                s.find('^点击空白位置继续$',(750,550,400,95)))


def totem_identity(s):
    title=s.find(r'^[\u4e00-\u9fff]{1,6}图腾$',(90,0,260,65))
    if not title:return None
    if (s.find('^'+title.text+'$',(100,115,320,65)) and
            s.find('^图腾共生$',(30,200,330,65)) and
            s.find('^比拼方式$',(30,325,330,75)) and
            s.find(TOTEM_REWARD,(0,535,520,65))):return title.text
    return None


@lru_cache(maxsize=1)
def crest_templates():
    folder=Path(__file__).resolve().parents[1]/'resource/image'
    return {p.stem.removeprefix('tribe-totem-'):cv2.imread(str(p),cv2.IMREAD_GRAYSCALE)
            for p in sorted(folder.glob('tribe-totem-*.png'))}


def totem_nodes(s):
    from .activities import is_tribe_map
    if not is_tribe_map(s):return []
    gray=cv2.cvtColor(s.image,cv2.COLOR_BGR2GRAY)
    crop=gray[90:550,80:1180]
    found=[]
    for kind,template in crest_templates().items():
        scores=cv2.matchTemplate(crop,template,cv2.TM_CCOEFF_NORMED)
        for _ in range(4):
            _,score,_,point=cv2.minMaxLoc(scores)
            if score<.88:break
            x,y=point;h,w=template.shape
            center=(x+80+w//2,y+90+h//2)
            if all(np.linalg.norm(np.subtract(center,row['point']))>40 for row in found):
                found.append({'kind':kind,'point':center,'score':float(score)})
            scores[max(0,y-40):y+41,max(0,x-40):x+41]=0
    return found
