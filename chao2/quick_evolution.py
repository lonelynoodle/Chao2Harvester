"""Evolution tree's quick route, limited to blue materials and purple targets."""
import re

import cv2
import numpy as np

from .policy import TaskBlocked
from .star_supply import blue_card_frames


TREE_HEADER='^进化树$'
QUICK_ENTRY='^便捷进化$'
DETAIL='^详细信息$'
EVOLVE='^进化$'
QUALITY='^品质$'
PICKER_CLOSE=(1205,39,74,66)
EVOLVE_ROI=(920,625,216,72)
MONSTER_HEADER='^怪兽信息$'


def color_fraction(image,hue_min,hue_max):
    hue,saturation,value=cv2.split(cv2.cvtColor(image,cv2.COLOR_BGR2HSV))
    return ((hue>=hue_min)&(hue<=hue_max)&(saturation>75)&(value>85)).mean()


def tree_map(s):
    return bool(s.find(TREE_HEADER,(90,0,170,65)) and s.find(QUICK_ENTRY,(1050,633,226,80)))


def quick_list(s):
    return bool(s.find(TREE_HEADER,(90,0,170,65)) and s.find('^全部$',(35,85,190,75)) and
                s.find(r'^收集\s*\d+/\d+$',(520,49,240,43)) and not quick_detail(s))


def quick_all_selected(s):
    border=s.image[95:108,80:180].astype('int16')
    return quick_list(s) and ((border[:,:,0]-border[:,:,2]>35)&(border[:,:,0]>120)).mean()>.35


def quick_detail(s):
    return bool(s.find(DETAIL,(500,12,290,50)) and s.find(EVOLVE,EVOLVE_ROI) and
                s.find('^攻击力$|^移动速度$',(595,325,175,79)))


def quick_source_picker(s):
    return bool(s.find(QUALITY,(10,53,190,56)) and s.find(r'^[xX×]$',PICKER_CLOSE) and
                not s.find('^怪兽数量$|^商店$|^获得奖励$'))


def quick_purple_cards(s):
    cards=[]
    for word in s.words:
        x,y=word.center
        if word.text!='可进化' or not 163<=y<=620:continue
        left=44+round((x-132)/202)*202
        if not 44<=left<=1054 or abs(x-left-88)>31:continue
        if color_fraction(s.image[y+24:y+148,left+3:left+13],125,165)<.25:continue
        badge=s.find(r'^\d{3}$',(left+128,y-3,52,42))
        name=s.find(r'^[\u4e00-\u9fff]{2,10}$',(left+10,y+176,155,60))
        if not (badge or name):continue
        cards.append((badge.text if badge else name.text,(left+88,min(y+105,654))))
    return sorted(cards,key=lambda entry:(entry[1][1]//20,entry[1][0]))


def quick_spore_balance(s):
    word=s.find(r'^\d{1,7}$',(1195,78,80,48))
    return int(word.text) if word else None


def quick_target_name(s):
    word=s.find(r'[\u4e00-\u9fff]{2,10}',(260,478,300,57))
    return re.search(r'[\u4e00-\u9fff]{2,10}',word.text)[0] if word else None


def quick_evolution_offer(b,s):
    if not quick_detail(s):return None
    if color_fraction(s.image[485:527,180:555],125,165)<.24:return None
    if color_fraction(s.image[624:687,468:532],85,115)<.18:return None
    if color_fraction(s.image[630:673,273:319],10,39)<.20:return None
    if color_fraction(s.image[632:674,376:416],74,110)<.20:return None
    name=quick_target_name(s)
    if not name:return None
    gold_word=s.find(r'^\d{4,7}$',(267,667,67,30))
    spore_word=s.find(r'^\d{1,3}$',(397,667,40,28))
    gold_amount=s.find(r'^\d+(?:\.\d+)?万$|^\d+$',(1195,19,80,52))
    gold=int(gold_word.text) if gold_word else b.read_number(s,(273,669,59,25))
    spores=int(spore_word.text) if spore_word else b.read_number(s,(401,669,33,25))
    spore_balance=quick_spore_balance(s)
    if not (gold_amount and gold and spores and spore_balance is not None):return None
    if not (1000<=gold<=200000 and 1<=spores<=100):return None
    available=gold_amount.text
    gold_balance=int(float(available[:-1])*10000) if available.endswith('万') else int(available)
    return {'name':name,'gold':gold,'spores':spores,'gold_balance':gold_balance,'spore_balance':spore_balance}


def quick_evolution_enabled(s):
    button=s.find(EVOLVE,EVOLVE_ROI)
    if not button:return False
    x,y=button.center
    return (s.image[y-15:y+15,x-31:x+31].min(axis=2)>210).mean()>.10


class QuickEvolution:
    def close_quick_preview(self,s):
        def close(q):
            if quick_detail(q):
                self.b.click_at(q,(1101,43),[DETAIL],'关闭进化树预览')
        close(s)
        return self.wait_for_screen(quick_list,'返回便捷进化列表',timeout=2,retry_navigation=close)

    def open_quick_evolution(self):
        s=self.observe()
        if quick_source_picker(s):
            self.b.click_at(s,(1238,72),[QUALITY,r'^[xX×]$'],'关闭进化素材列表')
            s=self.wait_for_screen(quick_detail,'返回进化树预览',timeout=2)
        if quick_detail(s):return self.close_quick_preview(s)
        if quick_list(s):return s
        if not tree_map(s):
            if not s.find(MONSTER_HEADER,(90,0,170,65)):
                self.b.click_text(self.territory(),'^怪兽$',roi=(755,630,130,90))
                s=self.wait_for_screen(lambda q:q.find(MONSTER_HEADER,(90,0,170,65)),'怪兽信息')
            # Its caption is small and OCR often omits it. The icon is fixed
            # on the left of the confirmed Monster Information page.
            def open_tree(q):
                if (q.find(MONSTER_HEADER,(90,0,170,65)) and
                        q.find('^元核$|^形态$|^物语$|^属性$',(1185,80,93,495)) and
                        not q.find('^怪兽数量$|^获得奖励$|^确定$|^取消$')):
                    self.b.click_at(q,(44,274),[MONSTER_HEADER],'从怪兽信息打开进化树')
            open_tree(s)
            s=self.wait_for_screen(tree_map,'进化树',timeout=3,retry_navigation=open_tree)

        def enter(q):
            if tree_map(q):
                button=q.find(QUICK_ENTRY,(1050,633,226,80))
                self.b.click_at(q,button.center,[TREE_HEADER,QUICK_ENTRY],'打开便捷进化')
        enter(s)
        return self.wait_for_screen(quick_list,'便捷进化列表',timeout=3,retry_navigation=enter)

    def select_quick_blue_material(self,s):
        name=quick_target_name(s)
        def open_picker(q):
            if quick_detail(q) and quick_target_name(q)==name:
                self.b.click_at(q,(502,655),[DETAIL,EVOLVE],'打开紫怪所需的蓝怪素材列表')
        open_picker(s)
        s=self.wait_for_screen(quick_source_picker,'便捷进化的蓝怪素材',timeout=3,retry_navigation=open_picker)
        candidates=blue_card_frames(s,first_column=16,top_limit=110)
        selected=None
        for card in candidates:
            x,y=card['point']
            roi=(x-51,y-49,102,100)
            if s.find('已锁定|出战中|使用中|不可使用',roi):continue
            if not s.find('^已选中$',roi):
                self.b.click_at(s,card['point'],[QUALITY,r'^[xX×]$'],'选择未锁定的蓝怪进化素材')
                s=self.observe()
                if not quick_source_picker(s):
                    raise TaskBlocked('蓝怪素材选择页改变，未提交进化')
            if s.find('^已选中$',roi):
                selected=card
                break
        self.b.click_at(s,(1238,72),[QUALITY,r'^[xX×]$'],'返回紫怪进化预览')
        s=self.wait_for_screen(quick_detail,'已选择素材的进化预览',timeout=3)
        return s,selected is not None

    def next_quick_evolution(self):
        s=self.open_quick_evolution()
        if not quick_all_selected(s):
            self.b.click_text(s,'^全部$',roi=(35,85,190,75))
            s=self.wait_for_screen(quick_all_selected,'便捷进化的全部怪兽',timeout=3)
        checked=set()
        unreadable=False
        scrolls=0
        while scrolls<=35:
            if not quick_list(s):raise TaskBlocked('便捷进化列表未确认')
            cards=[(key,point) for key,point in quick_purple_cards(s) if key not in checked]
            if cards:
                key,_=cards[0]
                checked.add(key)
                def preview(q):
                    if not quick_list(q):return
                    point=dict(quick_purple_cards(q)).get(key)
                    if point:self.b.click_at(q,point,[TREE_HEADER,'^可进化$'],'预览可进化的紫色怪兽')
                preview(s)
                s=self.wait_for_screen(quick_detail,'紫怪的便捷进化预览',timeout=3,retry_navigation=preview)
                offer=quick_evolution_offer(self.b,s)
                if offer is None:
                    unreadable=True
                    s=self.close_quick_preview(s)
                    continue
                if offer['gold_balance']<offer['gold'] or offer['spore_balance']<offer['spores']:
                    return s,offer
                s,selected=self.select_quick_blue_material(s)
                if selected and quick_evolution_enabled(s):
                    return s,offer
                s=self.close_quick_preview(s)
                continue
            before=s.image[172:690,45:1230].astype('int16')
            scrolls+=1
            for x in (638,640):
                self.b.guard(s)
                if not self.b.wait(self.b.controller.post_swipe(x,637,x,272,650)).succeeded:
                    raise TaskBlocked('便捷进化列表无法向下滑动')
                self.b.sleep(.45)
                s=self.wait_for_screen(quick_list,'便捷进化列表向下',timeout=3)
                if np.abs(before-s.image[172:690,45:1230].astype('int16')).mean()>=2:break
            else:
                if unreadable:raise TaskBlocked('有紫怪的便捷进化费用或蓝怪素材未读清')
                return s,None
        raise TaskBlocked('便捷进化已核对完整列表，仍未找到可提交的紫怪')
