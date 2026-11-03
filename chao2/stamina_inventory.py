"""Opt-in inventory refills. Exactly one verified 100-point potion at a time."""
import re
from maa.pipeline import JTemplateMatch
from .other_tasks import is_bag,bag_signature
from .policy import TaskBlocked,SafetyStop,can_claim_stamina,is_stamina_potion_dialog
import numpy as np


def potion_stock(s,dialog=False):
    roi=(550,300,210,45) if dialog else (835,135,240,45)
    w=s.find(r'^已拥有\s*(\d+)$',roi)
    return int(re.search(r'\d+$',w.text)[0]) if w else None


class StaminaInventory:
    def potion_inventory(self):
        s=self.home();self.click_world(s,(43,270),'打开背包查找移动力药水')
        s=self.await_page('^背包$','^全部$','^元核$')
        self.b.click_text(s,'^道具$',roi=(0,280,100,90));s=self.observe()
        previous=None
        for _ in range(35):
            self.b.guard(s)
            if not is_bag(s):raise TaskBlocked('查找移动力药水时背包页面改变')
            if (s.find('^移动力药水$',(835,90,240,50)) and
                    s.find('使用后可获得100移动力',(745,210,515,85))):return s
            result=self.b.wait(self.b.tasker.post_recognition('TemplateMatch',JTemplateMatch(
                template=['stamina-potion.png'],roi=[140,88,580,570],threshold=[.92]),s.image),10).get()
            matches=[m for n in result.nodes if n.recognition for m in n.recognition.filtered_results] if result else []
            if matches:
                x,y,w,h=max(matches,key=lambda m:m.score).box
                self.b.click_at(s,(x+w//2,y+h//2),['^背包$','^道具$'],'选择库存移动力药水')
                s=self.observe();self.b.guard(s)
                if s.find('^移动力药水$',(835,90,240,50)) and s.find('使用后可获得100移动力',(745,210,515,85)):return s
                raise TaskBlocked('药水图标匹配后名称或100移动力说明未确认，未使用')
            signature=bag_signature(s)
            if previous is not None and np.mean(np.max(np.abs(signature-previous),axis=2)>35)<.025:break
            previous=signature
            self.b.wait(self.b.controller.post_swipe(450,590,450,240,650));self.b.sleep(.8);s=self.observe()
        self.home();return None

    def use_stamina_potion(self):
        if not any(t in getattr(self,'selected',[]) and self.options[t].get('auto_potions',False)
                   for t in ('copies','hunt','main')):raise SafetyStop('未开启库存移动力药水选项，禁止使用')
        before=self.world_resources(self.home())
        if not can_claim_stamina(before['stamina'],before['stamina_cap'],100):return None
        s=self.potion_inventory()
        if s is None:self.note('背包没有可使用的移动力药水');return None
        stock=potion_stock(s)
        if stock is None:raise TaskBlocked('库存移动力药水数量未读清')
        if stock<1:self.home();return None
        self.b.click_text(s,'^使用$',roi=(750,610,530,85))
        self.b.potion_dialog_active=True
        try:
            s=self.await_page('^使用数量$','^确定$','^取消$')
            if not is_stamina_potion_dialog(s) or potion_stock(s,True)!=stock:
                raise TaskBlocked('移动力药水数量弹窗未确认，未使用')
            quantity=self.b.read_number(s,(615,352,55,45))
            if quantity!=1:
                self.b.click_text(s,'^取消$',roi=(420,440,130,65))
                raise TaskBlocked('药水使用数量不是1，已取消')
            self.b.save_screen(s,self.report['folder']/'potion-before-use.png')
            receipt={'count':1,'gain':100,'stock_before':stock,'stamina_before':before['stamina'],'status':'confirming'}
            self.report.setdefault('stamina_potions',[]).append(receipt);self.checkpoint()
            self.b.click_text(s,'^确定$',roi=(745,440,130,65))
        finally:self.b.potion_dialog_active=False
        s=self.observe();self.b.guard(s)
        if s.has('^获得奖励$','点击空白位置关闭'):
            self.b.click_at(s,(640,660),['^获得奖励$','点击空白位置关闭'],'关闭移动力到账展示');s=self.observe()
        if not is_bag(s) or potion_stock(s)!=stock-1:
            raise SafetyStop('药水使用后库存变化未核实，未重复使用')
        after=self.world_resources(self.home())
        if after['stamina'] is None or not 100<=after['stamina']-before['stamina']<=102:
            raise SafetyStop('药水100移动力到账未核实，未重复使用')
        receipt.update(status='confirmed',stock_after=stock-1,stamina_after=after['stamina'])
        self.checkpoint();return 100
