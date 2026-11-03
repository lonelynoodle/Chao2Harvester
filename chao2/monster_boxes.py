"""Opt-in opening of the exact blue 幻化怪兽茧, one verified receipt at a time."""
from collections import Counter
import random
import re
import numpy as np
from maa.pipeline import JTemplateMatch
from .monster_box_settings import MONSTER_BOX_NAMES
from .other_tasks import is_bag,bag_signature,components
from .policy import SafetyStop,TaskBlocked,parse_ratio

BOX_TITLE=r'^幻化怪兽茧$'


def is_monster_box_item(s):
    return bool(is_bag(s) and s.find(BOX_TITLE,(835,90,250,55)) and
                s.find('孕育一切幻化进化',(745,205,520,80)) and
                s.find('打开后可从以下道具中选择一项',(745,365,520,70)))


def monster_box_stock(s):
    if not is_monster_box_item(s):return None
    w=s.find(r'^已拥有\s*\d+$',(835,135,250,50))
    return int(re.search(r'\d+$',w.text)[0]) if w else None


def monster_choice_name(s):
    if not s.find(BOX_TITLE,(80,0,210,65)) or not s.find('^选择$',(400,610,470,100)):return None
    if not s.find('^详细属性$',(170,500,230,80)):return None
    return next((name for name in MONSTER_BOX_NAMES if s.find('^'+name+'$',(165,65,240,65))),None)


def monster_carousel_points(s):
    if not s.find(BOX_TITLE,(80,0,210,65)) or s.find('^选择$|^详细属性$|^确定$|^取消$'):return []
    im=s.image[610:700].astype('int16')
    gold=(im[:,:,2]>180)&(im[:,:,1]>135)&(im[:,:,0]<150)&(im[:,:,2]>im[:,:,0]*1.3)
    xs=[(a+c)//2 for a,b,c,d,n in components(gold) if n>180 and 17<c-a<65 and d-b>40]
    return [(x,490) for x in sorted(xs) if 45<x<1235] if 3<=len(xs)<=4 else []


def is_monster_box_result(s,name):
    return bool(not s.find(BOX_TITLE) and not is_bag(s) and not s.find('^选择$|^详细信息$|^怪兽信息$|^怪兽培育$|^进化$') and
                s.has('^详细属性$','移动速度','攻击力','体力') and
                (s.find(re.escape(name),(70,50,230,95)) or s.find(re.escape(name),(15,470,315,130))))


def monster_box_result_name(s):
    return next((name for name in MONSTER_BOX_NAMES if is_monster_box_result(s,name)),None)


def next_box_monster(options,counts,choose=random.choice):
    mode=options['monster_box_mode']
    if mode=='specified':return options['monster_box_target']
    if mode=='random':return choose(MONSTER_BOX_NAMES)
    if mode=='balanced':return min(MONSTER_BOX_NAMES,key=lambda name:counts.get(name,0))
    raise ValueError('未知幻化怪兽茧开启方式')


class MonsterBoxInventory:
    def close_monster_box_result(self,s,name,*,return_to_bag=True):
        """Only retry the free dismissal of an already observed receipt.

        The presentation initially ignores taps while its animation runs.
        Never reuse the spending/selection control as a recovery operation.
        """
        if not is_monster_box_result(s,name):raise TaskBlocked('已获得怪兽展示未确认，未点击关闭')
        def close(q):
            if is_monster_box_result(q,name):
                self.b.click_at(q,(875,670),['^详细属性$','移动速度','攻击力','体力'],
                                '关闭已获得怪兽展示')
        close(s)
        destination=is_bag if return_to_bag else lambda q:monster_box_result_name(q) is None
        return self.wait_for_screen(destination,'开启幻化怪兽茧后返回背包' if return_to_bag else '已获得怪兽展示关闭',
                                    timeout=4,retry_navigation=close)

    def monster_box_inventory(self):
        s=self.observe();self.b.guard(s)
        if is_monster_box_item(s):return s
        if not is_bag(s):
            s=self.home(s);self.click_world(s,(43,270),'打开背包查找幻化怪兽茧')
            s=self.await_page('^背包$','^全部$','^元核$')
        self.b.click_text(s,'^道具$',roi=(0,280,100,90));s=self.observe();previous=None
        for _ in range(40):
            self.b.guard(s)
            if not is_bag(s):raise TaskBlocked('查找幻化怪兽茧时背包页面改变')
            result=self.b.wait(self.b.tasker.post_recognition('TemplateMatch',JTemplateMatch(
                template=['monster-box-blue.png'],roi=[140,88,580,570],threshold=[.90]),s.image),10).get()
            matches=[m for n in result.nodes if n.recognition for m in n.recognition.filtered_results] if result else []
            if matches:
                x,y,w,h=max(matches,key=lambda m:m.score).box
                self.b.click_at(s,(x+w//2,y+h//2),['^背包$','^道具$'],'选择蓝色幻化怪兽茧')
                return self.wait_for_screen(is_monster_box_item,'幻化怪兽茧名称及说明')
            signature=bag_signature(s)
            if previous is not None and np.mean(np.max(np.abs(signature-previous),axis=2)>35)<.025:return None
            previous=signature
            if not self.b.wait(self.b.controller.post_swipe(450,590,450,240,650)).succeeded:
                raise TaskBlocked('查找幻化怪兽茧时背包翻页失败')
            self.b.sleep(.8);s=self.observe()
        raise TaskBlocked('背包尚未到达底部，无法确认幻化怪兽茧库存')

    def select_monster_box_target(self,s,name):
        if name not in MONSTER_BOX_NAMES:raise SafetyStop('幻化怪兽茧目标不在已校准的八种怪兽中')
        index=MONSTER_BOX_NAMES.index(name);left=index<4
        for attempt in range(4):
            if attempt:self.navigation_retry('幻化怪兽茧目标选择未确认',attempt,s)
            current=monster_choice_name(s)
            if current==name:return s
            if current:
                self.b.click_at(s,(43,28),[BOX_TITLE,'^选择$'],'返回幻化怪兽茧怪兽列表')
                s=self.wait_for_screen(lambda q:bool(monster_carousel_points(q)),'幻化怪兽茧怪兽列表')
            if not monster_carousel_points(s):raise TaskBlocked('幻化怪兽茧怪兽列表未确认，未点击选择')
            # At most two long swipes traverse all eight cards. Read the gold
            # markers again after each gesture; the final name is authoritative.
            for _ in range(2):
                points=monster_carousel_points(s)
                edge=169 if left else 99
                if len(points)==4 and abs(points[0][0]-edge)<=8:break
                args=(150,480,1100,480,700) if left else (1100,480,150,480,700)
                self.b.guard(s)
                if not self.b.wait(self.b.controller.post_swipe(*args)).succeeded:
                    self.note('怪兽列表滑动未成功，重新观察后尝试')
                self.b.sleep(1)
                s=self.wait_for_screen(lambda q:bool(monster_carousel_points(q)),'幻化怪兽茧列表滑动')
            points=monster_carousel_points(s)
            if len(points)!=4:continue
            self.b.click_at(s,points[index if left else index-4],[BOX_TITLE],'预览幻化怪兽：'+name)
            s=self.wait_for_screen(lambda q:monster_choice_name(q) is not None,'幻化怪兽名称')
            if monster_choice_name(s)==name:return s
        raise TaskBlocked('幻化怪兽茧目标名称仍不符，未开启')

    def open_one_monster_box(self,s,name,mode):
        before=monster_box_stock(s)
        if before is None or before<1:raise TaskBlocked('幻化怪兽茧库存未确认')
        capacity=parse_ratio(s.region_text((0,90,110,65)))
        if capacity is None:raise TaskBlocked('背包剩余空间未确认，未开启幻化怪兽茧')
        if capacity[0]>=capacity[1]:raise TaskBlocked('背包已满，未开启幻化怪兽茧')
        self.b.click_text(s,'^使用$',roi=(750,610,530,85))
        s=self.wait_for_screen(lambda q:bool(monster_carousel_points(q)) or monster_choice_name(q) is not None,'幻化怪兽茧选择页')
        s=self.select_monster_box_target(s,name)
        if monster_choice_name(s)!=name:raise SafetyStop('开茧前怪兽名称不符，未确认')
        rows=self.report.setdefault('monster_boxes',[])
        row={'monster':name,'mode':mode,'stock_before':before,'count':1,'status':'submitted'}
        rows.append(row);self.b.save_screen(s,self.report['folder']/f'monster-box-{len(rows)}-before.png');self.checkpoint()
        # This is the spending action. Never include it in a navigation retry.
        self.b.click_at(s,(640,667),[BOX_TITLE,'^'+name+'$','^选择$'],'开启1个幻化怪兽茧：'+name)
        try:
            s=self.wait_for_screen(lambda q:is_monster_box_result(q,name),'幻化怪兽到账展示')
            self.b.save_screen(s,self.report['folder']/f'monster-box-{len(rows)}-reward.png')
            row['status']='reward_seen';self.checkpoint()
            s=self.close_monster_box_result(s,name)
            if before>1:
                s=self.wait_for_screen(lambda q:monster_box_stock(q)==before-1,'幻化怪兽茧库存减少1')
            else:
                # Last item may disappear and select the next stack. Verify
                # absence by scanning, rather than interpreting an OCR miss as 0.
                self.wait_for_screen(lambda q:is_bag(q) and
                                     (not is_monster_box_item(q) or monster_box_stock(q)==0),
                                     '最后一个幻化怪兽茧库存更新')
                s=self.monster_box_inventory()
                if s is not None and monster_box_stock(s)!=0:
                    raise TaskBlocked('最后一个幻化怪兽茧使用后仍有库存')
        except TaskBlocked as error:
            raise SafetyStop('幻化怪兽茧开启结果未完整核实，未重复开启：'+str(error)) from error
        row.update(status='confirmed',stock_after=before-1)
        counts=self.state.setdefault('monster_box_opened_counts',{})
        counts[name]=counts.get(name,0)+1;self.save_state();self.checkpoint()
        self.note(f'已开启幻化怪兽茧：{name}，消耗1个，剩余{before-1}个')
        return s,before-1

    def open_monster_boxes(self):
        options=self.options['other']
        if not options['open_monster_boxes']:raise SafetyStop('未开启自动幻化怪兽茧选项')
        s=self.monster_box_inventory()
        if s is None:return {'status':'done','opened':0,'remaining':0,'message':'幻化怪兽茧开启0个：背包没有库存'}
        initial=monster_box_stock(s)
        if initial is None:raise TaskBlocked('幻化怪兽茧数量未读清')
        limit=options['monster_box_limit'];budget=min(initial,limit) if limit else initial
        opened=Counter();remaining=initial
        for _ in range(budget):
            counts=self.state.setdefault('monster_box_opened_counts',{})
            name=next_box_monster(options,counts)
            self.note(f'幻化怪兽茧：准备开启{name}（{sum(opened.values())+1}/{budget}）')
            s,remaining=self.open_one_monster_box(s,name,options['monster_box_mode']);opened[name]+=1
            if not remaining:break
        detail='、'.join(f'{name}×{count}' for name,count in opened.items())
        reason='已达到设置上限' if remaining and budget==limit else '库存已用完'
        return {'status':'done','opened':sum(opened.values()),'remaining':remaining,'monsters':dict(opened),
                'message':f'幻化怪兽茧开启{sum(opened.values())}个，剩余{remaining}个；{detail}；{reason}'}
