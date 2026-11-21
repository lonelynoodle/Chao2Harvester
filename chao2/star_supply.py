"""Verified blue-monster supply for an explicitly enabled star-feeding fallback."""
import re
import cv2
import numpy as np

from .policy import TaskBlocked


def monster_roster(s):
    return bool(s.find('^怪兽数量$', (0, 65, 150, 70)) and
                s.find('^品质$', (160, 110, 120, 65)))


def blue_roster_cards(s,read_text=None):
    """Locate complete blue card frames after scrolling, then read their levels."""
    if not monster_roster(s):return []
    return blue_card_frames(s,read_text,first_column=118,top_limit=175)


def blue_card_frames(s,read_text=None,*,first_column,top_limit):
    hsv=cv2.cvtColor(s.image,cv2.COLOR_BGR2HSV)
    h,saturation,value=(hsv[:,:,i] for i in range(3))
    mask=((h>=85)&(h<=115)&(saturation>80)&(value>80)).astype('uint8')
    mask[:top_limit]=0;mask[700:]=0;mask[:,:first_column-8]=0
    _,_,stats,_=cv2.connectedComponentsWithStats(mask)
    rows=[]
    for left,top,width,height,area in stats[1:]:
        left,top,width,height,area=map(int,(left,top,width,height,area))
        if not (105<=width<=118 and 105<=height<=124 and area>1800):continue
        if min(abs(left-first_column-126*i) for i in range(10))>4:continue
        # Require both vertical blue rims; a monster's blue body is not a card.
        blue=float(min(mask[top+10:top+98,left:left+7].mean(),
                       mask[top+10:top+98,left+width-7:left+width].mean()))
        if blue<.25:continue
        roi=(left+58,top+78,56,34)
        level=s.find(r'等级\s*[0-9]+$',roi)
        number=int(re.search(r'\d+',level.text)[0]) if level else None
        if number is None and read_text:
            text=read_text(s,roi).strip()
            if re.fullmatch(r'等级\s*\d{1,3}',text):number=int(re.search(r'\d+',text)[0])
        rows.append({'point':(left+56,top+54),'level':number,'score':blue,'level_roi':roi})
    return sorted(rows,key=lambda row:(row['point'][1],row['point'][0]))


def selected_blue_roster_index(s,cards):
    """The selected card has a continuous white glow on both outer edges."""
    selected=[]
    for index,row in enumerate(cards):
        x,y=row['point']
        top=s.image[y-59:y-48,x-35:x+35]
        left=s.image[y-31:y+31,x-63:x-48]
        if ((top.min(axis=2)>220).mean(axis=1).max()>.75 and
                (left.min(axis=2)>220).mean(axis=0).max()>.75):
            selected.append(index)
    return selected[0] if len(selected)==1 else None


def blue_monster_info(b,s,*,require_level_one=True):
    if not s.find('^怪兽信息$',(90,0,230,60)):
        return False
    hsv=cv2.cvtColor(s.image[78:124,645:710],cv2.COLOR_BGR2HSV)
    h,saturation,value=(hsv[:,:,i] for i in range(3))
    blue=((h>=85)&(h<=115)&(saturation>90)&(value>100)).mean()
    return blue>.20 and (not require_level_one or b.read_number(s,(687,418,35,45))==1)


def blue_evolution_unavailable(s):
    if s.find('^人间大炮$',(645,78,410,50)):
        return '人间大炮不可进化'
    button=s.find('^进化$',(1000,395,180,90))
    if button:
        x,y,w,h=button.box
        pixels=s.image[y:y+h,x:x+w]
        dark=pixels.min(axis=2)
        light=pixels.max(axis=2)
        # Disabled text is dim neutral gray. Require visible glyphs so a
        # missing or unreadable button is not treated as a disabled candidate.
        dim_gray=(dark>=45)&(light<=130)&(light-dark<=22)
        if dim_gray.mean()>=.24 and (light>=145).mean()<.01:
            return '当前蓝怪的进化按钮为灰色'
    return None


def purple_monster_info(b,s,*,require_level_one=True):
    if not s.find('^怪兽信息$',(90,0,230,60)):
        return False
    hsv=cv2.cvtColor(s.image[78:124,645:710],cv2.COLOR_BGR2HSV)
    h,saturation,value=(hsv[:,:,i] for i in range(3))
    return (((h>=125)&(h<=165)&(saturation>90)&(value>100)).mean()>.20 and
            (not require_level_one or b.read_number(s,(687,418,35,45))==1))


def evolution_result_name(b,s):
    """Purple evolution reveal: target badge, stat changes and skill column.

    The reveal has no back button or 'evolution succeeded' text. Its 究极
    glyph is often read as 交极, so verify the fixed badge image instead.
    """
    if s.find('^怪兽信息$|^进化$|^消耗材料$|^选择$'):return None
    name=s.find(r'^[\u4e00-\u9fff]{2,8}$',(90,50,300,90))
    if not name or not s.find('^详细属性$',(95,620,220,75)):return None
    if not s.find('^不朽$',(1030,400,130,100)):return None
    rows=sum(any(re.search(r'\d',w.text) and 100<w.center[0]<280 and
                 y<=w.center[1]<y+39 for w in s.words) for y in (320,360,400,440))
    if rows<3 or not b.match_template(s,'evolution-ultimate-badge.png',[12,55,78,80],.88):return None
    return name.text


def gold_balance(s):
    word=s.find(r'^\d+(?:\.\d+)?万$|^\d+$',(1050,0,100,55))
    if not word:return None
    text=word.text
    return int(float(text[:-1])*10000) if text.endswith('万') else int(text)


def evolution_offer(b,s):
    """Return ordinary-material costs; never infer a diamond or polar cost."""
    if not s.find('^进化$',(105,0,110,60)):
        return None
    crest=cv2.cvtColor(s.image[70:120,112:170],cv2.COLOR_BGR2HSV)
    hue,saturation,value=(crest[:,:,i] for i in range(3))
    if ((hue>=125)&(hue<=165)&(saturation>70)&(value>70)).mean()<.50:
        return None
    if not s.find('^消耗材料$',(70,580,160,65)) or not s.find('^进化$',(985,625,165,75)):
        return None
    if s.find('钻石|极化石|付费', (65,575,260,130)):return None
    gold=b.read_number(s,(98,666,68,28))
    spores=b.read_number(s,(207,672,28,23))
    available_spores=b.read_number(s,(1220,10,48,35))
    available_gold=gold_balance(s)
    target=s.find(r'^\S{2,8}$',(110,65,270,65))
    if not target or target.text in ('进化','究极'):return None
    if (gold is None or spores is None or available_gold is None or available_spores is None or
            not 1000<=gold<=200000 or not 1<=spores<=100):return None
    # The two visible material icons are yellow gold and cyan evolution spores.
    gold_icon=s.image[638:670,104:147]
    spore_icon=s.image[639:670,182:218]
    if not ((gold_icon[:,:,2]>gold_icon[:,:,0]*1.3)&(gold_icon[:,:,1]>gold_icon[:,:,0])).mean()>.20:
        return None
    if not ((spore_icon[:,:,0]>spore_icon[:,:,2]*1.1)&(spore_icon[:,:,1]>spore_icon[:,:,2]*1.1)).mean()>.15:
        return None
    return {'name':target.text,'gold':gold,'spores':spores,
            'gold_balance':available_gold,'spore_balance':available_spores}


def blue_egg_stock(s):
    from .star_shop import star_shop_page
    if not star_shop_page(s):raise TaskBlocked('饲星商店未确认，未购买幻化怪兽茧')
    title=s.find('^幻化怪兽茧$',(220,260,170,65))
    remaining=s.find(r'^剩余\s*\d+$',(235,310,120,50))
    if not title or not remaining:raise TaskBlocked('幻化怪兽茧名称或库存未确认')
    count=int(re.search(r'\d+',remaining.text)[0])
    if not 0<=count<=20:raise TaskBlocked('幻化怪兽茧库存异常，未购买')
    return count


def blue_egg_offer(b,s):
    count=blue_egg_stock(s)
    price=b.read_number(s,(280,355,70,32))
    currency=b.match_template(s,'star-soul-price.png',[240,350,55,48],.84)
    if price!=25 or not currency:
        raise TaskBlocked('幻化怪兽茧库存或25饲星之魂价格未确认，未购买')
    return {'remaining':count,'price':25,'point':(295,220)}


def blue_egg_dialog(b,s,quantity):
    if not s.find('^幻化怪兽茧$',(475,70,340,65)) or not s.find('^购买数量$',(370,505,140,65)):
        return None
    buy=s.find('^购买$',(530,600,230,60))
    if not buy or b.read_number(s,(603,511,70,52))!=quantity:
        return None
    if b.read_number(s,(640,646,55,32))!=25*quantity:
        return None
    if not b.match_template(s,'star-soul-buy.png',[600,640,45,42],.88):
        return None
    return buy
