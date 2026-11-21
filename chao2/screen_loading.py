"""The client's central rotating white dots indicate an input-blocking load."""
import cv2
import numpy as np
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _scene_indicator():
    return cv2.imread(str(Path(__file__).resolve().parent.parent/'resource/image/scene-loading-indicator.png'))


def scene_loading(s):
    """Letterboxed scene transition, confirmed by its fixed double-circle icon.

    Sparse OCR alone is not sufficient: unknown pages must remain unknown.
    The hint text changes, so only the small loading indicator is matched.
    """
    if s.image.shape!=(720,1280,3):return False
    if s.find('^任务挑战$|^世界回响$|^怪兽信息$|^获得奖励$|^退出$|^挑战$|^进化$|^部落$'):return False
    if (s.image[:100].max(axis=2)<24).mean()<.98:return False
    if (s.image[620:690].max(axis=2)<24).mean()<.98:return False
    template=_scene_indicator()
    if template is None:return False
    return bool(cv2.matchTemplate(s.image[505:580,580:700],template,cv2.TM_CCOEFF_NORMED).max()>=.9)


def loading_spinner(s):
    patch=s.image[285:435,565:715].astype('int16')
    mask=((patch.min(axis=2)>180)&(np.ptp(patch,axis=2)<20)).astype('uint8')
    _,_,stats,centers=cv2.connectedComponentsWithStats(mask)
    dots=0
    for (_,_,w,h,area),(x,y) in zip(stats[1:],centers[1:]):
        radius=((x-75)**2+(y-75)**2)**.5
        if (6<=w<=32 and 6<=h<=32 and .7<=w/h<=1.4 and
                area>=25 and area/(w*h)>.55 and 38<=radius<=65):dots+=1
    return dots>=3
