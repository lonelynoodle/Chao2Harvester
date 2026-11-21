"""Small deterministic offsets inside the freshly recognized same control."""
from .policy import TaskBlocked


def retry_point(word,attempt=0):
    x,y,w,h=map(int,word.box)
    left,top=max(0,x),max(0,y)
    right,bottom=min(1279,x+w-1),min(719,y+h-1)
    if w<1 or h<1 or left>right or top>bottom:raise TaskBlocked('重试按钮的有效区域未确认')
    cx,cy=word.center
    dx=min(4,max(0,(right-left)//4));dy=min(4,max(0,(bottom-top)//4))
    offsets=((0,0),(-dx,0),(dx,0),(0,-dy),(0,dy))
    ox,oy=offsets[max(0,attempt)%len(offsets)]
    return max(left,min(right,cx+ox)),max(top,min(bottom,cy+oy))
