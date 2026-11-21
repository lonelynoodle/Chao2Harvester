"""Opt-in inventory refills. Exactly one verified 100-point potion at a time."""
import re
from maa.pipeline import JTemplateMatch
from .other_tasks import is_bag,bag_signature
from .policy import (IsolatedTaskError,TaskBlocked,SafetyStop,can_claim_stamina,is_stamina_potion_dialog,
                     is_stamina_potion_confirmation,STAMINA_POTION_CONFIRMATION,parse_ratio)
import numpy as np


POTION_TITLE = r'^移动力药水$'
POTION_DESCRIPTION = r'使用后可获得\s*100\s*(?:点\s*)?移动力'
POTION_STOCK = r'^已拥有\s*(\d+|[OoＯｏ])$'


def potion_item(s):
    return bool(s.find(POTION_TITLE, (835, 90, 240, 50)) and
                s.find(POTION_DESCRIPTION, (745, 210, 515, 85)))


def potion_stock(s,dialog=False):
    roi=(550,300,210,45) if dialog else (835,135,240,45)
    word = s.find(POTION_STOCK, roi)
    match = re.fullmatch(POTION_STOCK, word.text if word else s.region_text(roi))
    if match is None:
        return None
    count = match[1]
    return int(count) if count.isdigit() else 0


def potion_items_tab(s):
    if not is_bag(s) or not s.find(r'^道具$', (0, 280, 100, 90)):
        return False
    blue, green, red = s.image[265:360, :100].astype('int16').transpose(2, 0, 1)
    return ((red > 160) & (green > 130) & (green > blue + 40)).mean() > .12


def potion_grid_tail(s):
    """Recognize the dark empty slots at the bottom of the verified items tab."""
    if not potion_items_tab(s):
        return False
    panel = s.image[378:665, 145:714].max(axis=2)
    if (panel > 135).mean() > .001:
        return False
    # The empty pockets dim the background in a regular six-column grid.
    # A blank/loading frame cannot satisfy this alternating pattern.
    gutters = panel[:, [92, 189, 286, 383, 480]].astype('int16')
    pockets = panel[:, [43, 140, 237, 334, 431]].astype('int16')
    return np.median((gutters - pockets).mean(axis=0)) >= 8


def potion_quantity(b,s):
    if not is_stamina_potion_dialog(s):return None
    quantity=b.read_number(s,(615,352,55,45))
    if quantity is not None or b.tasker is None:return quantity
    # The wide crop can be blank even on a visible thin "1". Two differently
    # padded crops must agree on complete digits; never turn 一/empty into 1.
    reads=[b.read_text_crop(s,roi).strip() for roi in ((625,355,35,35),(615,345,55,55))]
    return int(reads[0]) if reads[0]==reads[1] and re.fullmatch(r'\d{1,3}',reads[0]) else None


class StaminaInventory:
    def potion_icon(self,s):
        result=self.b.wait(self.b.tasker.post_recognition('TemplateMatch',JTemplateMatch(
            template=['stamina-potion.png'],roi=[140,82,580,590],threshold=[.92]),s.image),10).get()
        matches=[m for n in result.nodes if n.recognition for m in n.recognition.filtered_results] if result else []
        return max(matches,key=lambda m:m.score,default=None)

    def potion_inventory(self):
        s=self.home();self.click_world(s,(43,270),'打开背包查找移动力药水')
        s=self.await_page('^背包$','^全部$','^元核$')
        # A bag reopened on 道具 may remember the last row viewed.
        if potion_items_tab(s):
            self.b.click_text(s,'^全部$',roi=(0,170,110,70))
            s=self.wait_for_screen(lambda q:is_bag(q) and not potion_items_tab(q),'背包全部分类',timeout=2)
        def open_items(q):
            if is_bag(q) and not potion_items_tab(q):
                self.b.click_text(q,'^道具$',roi=(0,280,100,90))
        self.navigation_input(s,open_items)
        s=self.wait_for_screen(potion_items_tab,'背包道具分类',timeout=2,retry_navigation=open_items)
        previous=None;unchanged=0
        for _ in range(35):
            self.b.guard(s)
            if not potion_items_tab(s):raise TaskBlocked('查找移动力药水时背包道具分类未确认')
            if potion_item(s):return s
            match=self.potion_icon(s)
            if match:
                x,y,w,h=match.box
                self.b.click_at(s,(x+w//2,y+h//2),['^背包$','^道具$'],'选择库存移动力药水')
                return self.wait_for_screen(potion_item,'药水名称及100移动力说明',timeout=2)
            if potion_grid_tail(s):return None
            signature=bag_signature(s)
            same=previous is not None and np.mean(np.max(np.abs(signature-previous),axis=2)>35)<.025
            unchanged=unchanged+1 if same else 0
            if unchanged>=2:raise TaskBlocked('背包列表连续两次未移动，药水库存未确认')
            previous=signature
            if not self.b.wait(self.b.controller.post_swipe(450,590,450,240,650)).succeeded:
                raise TaskBlocked('查找移动力药水时背包翻页失败')
            self.b.sleep(.8);s=self.observe()
        raise TaskBlocked('背包药水库存未确认')

    def no_stamina_potions(self):
        self._stamina_potions_unavailable=True
        self.stamina_potion_reason='背包移动力药水库存为0'
        self.note(self.stamina_potion_reason)

    def use_stamina_potion(self):
        if not any(t in getattr(self,'selected',[]) and self.options[t].get('auto_potions',False)
                   for t in ('copies','hunt','main')):raise SafetyStop('未开启库存移动力药水选项，禁止使用')
        if getattr(self,'_stamina_potions_unavailable',False):return None
        if any(row['status'] not in ('confirmed','cancelled') for row in self.report.get('stamina_potions',[])):
            raise IsolatedTaskError('上次移动力药水到账待核实')
        before=self.world_resources(self.home())
        if not can_claim_stamina(before['stamina'],before['stamina_cap'],100):
            self.stamina_potion_reason='当前体力或上限未确认，或无法容纳100体力'
            return None
        s=self.potion_inventory()
        stock=0 if s is None else potion_stock(s)
        if stock is None:raise TaskBlocked('库存移动力药水数量未读清')
        if stock==0:
            self.no_stamina_potions();self.home();return None
        self.b.click_text(s,'^使用$',roi=(750,610,530,85))
        self.b.potion_dialog_active=True
        try:
            s=self.await_page('^使用数量$','^确定$','^取消$')
            if not is_stamina_potion_dialog(s) or potion_stock(s,True)!=stock:
                raise TaskBlocked('移动力药水数量弹窗未确认，未使用')
            quantity=potion_quantity(self.b,s)
            if quantity!=1:
                self.b.save_screen(s,self.report['folder']/'potion-quantity-unrecognized.png')
                self.b.click_text(s,'^取消$',roi=(420,440,130,65))
                raise TaskBlocked('药水使用数量未读清，已取消' if quantity is None else '药水使用数量不是1，已取消')
            self.b.save_screen(s,self.report['folder']/'potion-before-use.png')
            receipt={'count':1,'gain':100,'stock_before':stock,'stamina_before':before['stamina'],'status':'confirming'}
            self.report.setdefault('stamina_potions',[]).append(receipt);self.checkpoint()
            self.b.potion_confirmation_active=True
            self.b.click_text(s,'^确定$',roi=(745,440,130,65))
            s=self.observe();self.b.guard(s)
            if is_stamina_potion_confirmation(s):
                ratio=parse_ratio(s.region_text((1135,0,145,62)))
                if not ratio or not can_claim_stamina(*ratio):
                    self.b.click_at(s,s.find('^取消$',(420,455,130,65)).center,
                                    [STAMINA_POTION_CONFIRMATION,'^取消$'],'取消库存药水使用')
                    receipt['status']='cancelled';self.checkpoint()
                    raise TaskBlocked('药水确认时无法核实可容纳100移动力，已取消')
                self.b.save_screen(s,self.report['folder']/'potion-confirm-100.png')
                self.b.click_at(s,s.find('^确定$',(745,455,130,65)).center,
                                [STAMINA_POTION_CONFIRMATION,'^确定$'],'确认使用一瓶库存药水恢复100移动力')
                s=self.observe();self.b.guard(s)
        finally:
            self.b.potion_dialog_active=False
            self.b.potion_confirmation_active=False
        if s.has('^获得奖励$','点击空白位置关闭'):
            self.b.click_at(s,(640,660),['^获得奖励$','点击空白位置关闭'],'关闭移动力到账展示');s=self.observe()
        remaining=None
        if is_bag(s):
            if potion_item(s):remaining=potion_stock(s)
            elif stock==1 and potion_items_tab(s) and self.potion_icon(s) is None:
                # After consuming the last bottle the selection can move to
                # another item. Its “已拥有” belongs to that item.
                remaining=0
        if remaining!=stock-1:
            receipt['status']='unconfirmed';self.checkpoint()
            raise IsolatedTaskError('药水使用后库存变化未核实')
        after=self.world_resources(self.home())
        if after['stamina'] is None or not 100<=after['stamina']-before['stamina']<=102:
            receipt['status']='unconfirmed';self.checkpoint()
            raise IsolatedTaskError('药水100移动力到账未核实')
        receipt.update(status='confirmed',stock_after=remaining,stamina_after=after['stamina'])
        if remaining==0:self.no_stamina_potions()
        self.checkpoint();return 100
