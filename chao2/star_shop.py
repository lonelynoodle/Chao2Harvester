"""Daily spore purchases and explicitly enabled, minimal ultimate conversion."""
import math
import re
import cv2
import numpy as np
from .policy import TaskBlocked, SafetyStop, PageChanged, parse_ratio
from .star_supply import (monster_roster,blue_roster_cards,blue_monster_info,blue_evolution_unavailable,
                          purple_monster_info,evolution_result_name,evolution_offer,blue_egg_offer,blue_egg_stock,
                          blue_egg_dialog,selected_blue_roster_index)

SPORES = ('进化孢子', '强化孢子')


def star_shop_page(s):
    return bool(s.find('^商店$', (80, 0, 220, 65)) and
                s.find('^饲星商店$', (0, 295, 165, 110)) and
                all(s.find('^'+name+'$', (410, 255, 440, 55)) for name in SPORES) and
                s.find('每日00:00刷新', (450, 100, 370, 65)) and
                not s.find('^购买数量$'))


def star_altar(s):
    return bool(s.find('^饲星坛$', (80, 0, 220, 65)) and
                s.find('^怪兽饲星$', (0, 310, 160, 90)) and
                s.find('^商店$', (0, 605, 120, 80)))


def star_conversion_page(s):
    return star_altar(s) and bool(s.find('^怪兽饲星$', (300, 595, 300, 90)))


def star_souls(b, s):
    top=b.match_template(s, 'star-soul-top.png', [1130, 0, 65, 58], .88)
    modal=(s.find('^购买数量$',(370,505,140,65)) and
           s.find('^进化孢子$|^强化孢子$|^幻化怪兽茧$',(475,70,340,65)) and
           b.match_template(s,'star-soul-buy.png',[600,640,45,42],.88))
    if not top and not modal:
        raise TaskBlocked('饲星之魂图标未确认，未使用其他货币')
    word = s.find(r'^\d+$', (1180, 0, 100, 52))
    if word is None:
        # Single digits at the right edge can be absent from full-frame OCR.
        # The currency is already verified; keep the .8 threshold and the
        # independent numeric recheck below, including on purchase dialogs.
        b.confirm_label(s,r'^\d+$',(1180,0,100,52),scale=3,threshold=.8)
        word=s.find(r'^\d+$',(1180,0,100,52))
    if not word or word.score < .80:
        raise TaskBlocked('饲星之魂余额未读清')
    x,y,w,h = word.box
    amount = b.read_number(s, (x-3, y-3, w+6, h+6))
    if amount != int(word.text):
        raise TaskBlocked('饲星之魂余额两次识别不一致')
    if amount is None:
        raise TaskBlocked('饲星之魂余额未读清')
    return amount


def spore_offers(b, s):
    if not star_shop_page(s):
        raise TaskBlocked('饲星商店孢子货架未确认')
    result = []
    for name in SPORES:
        title = s.find('^'+name+'$', (410, 255, 440, 55))
        x = title.center[0]
        sold = bool(s.find('^已售', (x-85, 180, 170, 70)))
        if sold:
            result.append(dict(name=name, remaining=0, price=30, point=(x, 220)))
            continue
        w = s.find(r'^剩余\s*\d+$', (x-80, 305, 160, 45))
        remaining = int(re.search(r'\d+$', w.text)[0]) if w else None
        price = b.read_number(s, (x+1, 357, 60, 34))
        if price is None:
            # Exclude the card underline ("30_"), then require the wide
            # detected price to agree so cropped 300 cannot become 30.
            narrow = b.read_number(s, (x, 357, 40, 32))
            wide = b.read_text_region(s, (x-5, 355, 65, 38), scale=2).strip()
            if wide.isdigit() and narrow == int(wide):
                price = narrow
        currency = b.match_template(s, 'star-soul-price.png', [x-45, 350, 55, 48], .84)
        if remaining is None or not 0 < remaining <= 10 or price != 30 or not currency:
            raise TaskBlocked(name+'库存、30饲星之魂价格未确认，未购买')
        result.append(dict(name=name, remaining=remaining, price=price, point=(x, 220)))
    return result


def spore_purchase_dialog(b, s, name, quantity=1):
    if type(quantity) is not int or not 1<=quantity<=10:return None
    if name not in SPORES or not s.find('^'+name+'$', (475, 70, 340, 65)):
        return None
    if not s.find('^购买数量$', (370, 505, 140, 65)):
        return None
    buy = s.find('^购买$', (530, 600, 230, 60))
    if not buy or b.read_number(s, (603, 511, 70, 52)) != quantity:
        return None
    if not b.match_template(s, 'star-soul-buy.png', [600, 640, 45, 42], .88):
        return None
    price=b.read_number(s, (640, 646, 55, 32))
    if price is None:
        # The purchase-button decoration can turn "150" into "150_" in
        # recognition-only OCR. Keep the full price width, exclude the lower
        # decoration, and require agreement from two different crops. Never
        # strip non-digits or override a conflicting numeric price.
        reads=[b.read_text_crop(s,roi).strip() for roi in
               ((633,646,68,28),(630,648,75,26))]
        if reads[0]!=reads[1] or not re.fullmatch(r'\d{1,4}',reads[0]):return None
        price=int(reads[0])
    if price != 30*quantity:return None
    return buy


def ultimate_candidates(s):
    """Only visible purple card borders; gold, red and blue never qualify."""
    if not star_conversion_page(s):
        return []
    result = []
    for y in (146, 248, 351, 453, 556):
        for x in (796, 930, 1065):
            hsv = cv2.cvtColor(s.image[y:y+83, x:x+83], cv2.COLOR_BGR2HSV)
            border = np.zeros((83, 83), bool)
            border[:5] = True; border[:, :5] = True; border[:, -5:] = True
            purple = (hsv[:, :, 0] >= 126) & (hsv[:, :, 0] <= 165) & (hsv[:, :, 1] > 65) & (hsv[:, :, 2] > 70)
            if purple[border].mean() > .28:
                result.append({'point': (x+41, y+41), 'level_roi': (x+38, y+62, 48, 25)})
    return result


def ultimate_level(b,s,row):
    roi=row['level_roi']
    text=re.sub(r'\s','',b.read_text_crop(s,roi))
    match=re.fullmatch(r'等?级(\d+)',text)
    if match:return int(match[1])
    # The purple card's lower border can obscure the small level label.
    # Keep its entire width, exclude the border, and require a second OCR
    # to read the same complete label; a bare "1" is never sufficient.
    x,y,w,h=roi;levels=[]
    for crop in ((x,y+1,w,h-3),(x,y+2,w,h-6),(x,y+3,w,h-6)):
        text=re.sub(r'\s','',b.read_text_crop(s,crop))
        match=re.fullmatch(r'等?级(\d+)',text)
        if match:levels.append(int(match[1]))
    if len(set(levels))>1:return None
    if len(levels)>=2:return levels[0]
    # Some purple borders make recognition-only OCR merge a stray stroke as
    # "1等级1". Detect the complete label at two scales and crop heights; no
    # bare digit or shortened label may establish an untrained monster.
    if not hasattr(b,'read_text_region'):return None
    detected=[]
    for crop,scale in (((x,y+1,w,h-3),3),((x,y+2,w,h-6),4)):
        text=re.sub(r'\s','',b.read_text_region(s,crop,scale=scale,threshold=.8))
        match=re.fullmatch(r'等级(\d+)',text)
        if match:detected.append(int(match[1]))
    return detected[0] if len(detected)==2 and len(set(levels+detected))==1 else None


def star_yield(b, s):
    if not star_conversion_page(s):
        return None
    if b.match_template(s, 'star-soul-yield.png', [267, 140, 93, 105], .90):
        return b.read_number(s, (325, 210, 35, 24))
    # An empty altar has a dim action label. A bright one without a readable
    # reward is ambiguous, not evidence that no monsters were selected.
    label = s.image[624:651, 384:510]
    return 0 if (label.min(axis=2) > 170).mean() < .10 else None


def conversions_needed(required, balance, per_monster=75):
    return max(0, math.ceil((required-balance)/per_monster))


def star_conversion_modal(s, pending):
    """Recognize only the modal armed by one verified purple, level-one selection."""
    if pending != {'rarity':'究极', 'count':1, 'yield':75}:
        return False
    text = re.sub(r'\s', '', s.region_text((270, 180, 740, 270)))
    if not re.search(r'怪兽', text) or not re.search(r'饲星', text):
        return False
    if not re.search(r'是否|确认|确定', text) or re.search(r'钻石|充值|重置|光谱|极化|不朽|觉醒', text):
        return False
    if not s.find('^取消$', (250, 420, 400, 200)):
        return False
    return True


def star_conversion_confirmation(s, pending):
    if not star_conversion_modal(s,pending):return None
    return s.find('^确定$|^确认$|^确认饲星$', (650, 420, 380, 200))


def star_conversion_countdown(s,pending):
    """The confirm button is locked for a few seconds; no input is sent yet."""
    if not star_conversion_modal(s,pending):return None
    return s.find(r'^\d{2}:\d{2}$',(650,420,380,200))


def donation_page(s):
    return bool(s.find('^支配核心$', (80, 0, 230, 65)) and
                s.find('^消耗$', (120, 550, 120, 65)) and
                s.find('^消耗$', (930, 550, 130, 65)))


def gold_donation_remaining(s):
    if not donation_page(s):
        return None
    return parse_ratio(s.region_text((145, 608, 205, 52)))


def gold_donation_offer(b, s):
    if gold_donation_remaining(s) != (1, 1):
        return None
    if not s.find('^20万$', (260, 560, 85, 55)):
        return None
    if not b.match_template(s, 'tribe-gold-donate.png', [223, 561, 53, 54], .87):
        return None
    # Only the left button. The right button's resource and count are never
    # fallback candidates when OCR or template verification fails.
    return (245, 587)


class StarShop:
    def reconcile_star_conversion_pending(self):
        """Resolve an interrupted confirmation without replaying an old selection."""
        pending=self.day.get('star_conversion_pending')
        if not pending:return
        before=pending.get('balance');gain=pending.get('yield')
        if not isinstance(before,int) or before<0 or gain!=75:
            raise TaskBlocked('上次饲星转化记录不完整，未继续操作')
        authorized={'rarity':'究极','count':1,'yield':75}
        self.b.star_conversion_pending=authorized
        try:
            s=self.observe()
            if star_conversion_modal(s,authorized):
                # The saved choice may be stale after a restart. Cancel the
                # modal, then verify the soul balance before another attempt.
                self.b.click_text(s,'^取消$',roi=(250,420,400,200))
                self.wait_for_screen(lambda q:star_conversion_page(q) and
                    not star_conversion_modal(q,authorized),'取消上次未完成的饲星确认',timeout=10)
            balance=star_souls(self.b,self.open_star_shop())
        finally:
            self.b.star_conversion_pending=None
        if balance not in (before,before+gain):
            # The account may have been used after the interrupted run. An
            # unknown historical delta must not be marked as a successful
            # conversion, nor can its old confirmation be replayed. Rebase
            # only after proving there is no selected or in-flight conversion.
            self.rebase_star_conversion_pending(pending,balance)
            return
        self.day.pop('star_conversion_pending',None);self.save_state()
        self.note('上次饲星转化已核实增加75饲星之魂' if balance==before+gain else
                  '上次饲星确认未生效，已取消并核实饲星之魂未减少')

    def rebase_star_conversion_pending(self,pending,balance):
        s=self.open_star_shop()
        if star_souls(self.b,s)!=balance:raise TaskBlocked('饲星余额仍在变化，保留上次兑换记录')
        self.b.click_at(s,(43,28),['^商店$','^饲星商店$'],'核对旧兑换记录是否仍有祭坛选择')
        s=self.wait_for_screen(star_altar,'核对饲星坛')
        if not star_conversion_page(s):
            self.b.click_text(s,'^怪兽饲星$',roi=(0,310,160,90))
            s=self.wait_for_screen(star_conversion_page,'核对怪兽饲星')
        for _ in range(2):
            self.b.guard(s)
            if not star_conversion_page(s) or star_yield(self.b,s)!=0:
                raise TaskBlocked('上次饲星余额变化且祭坛并非空白，保留记录及选择，未重复转化')
            self.b.sleep(.5);s=self.observe()
        self.b.save_screen(s,self.report['folder']/'star-reconcile-empty.png')
        current=star_souls(self.b,self.open_star_shop())
        if current!=balance:raise TaskBlocked('核对空祭坛期间饲星余额改变，保留旧记录')
        record={'previous':dict(pending),'current_balance':balance,'status':'superseded',
                'outcome':'unknown','empty_altar_verified':True}
        self.day.setdefault('star_conversion_history',[]).append(record)
        self.report.setdefault('star_conversion_reconciliations',[]).append(record)
        self.day.pop('star_conversion_pending',None);self.save_state();self.checkpoint()
        self.note(f'旧饲星记录起点{pending["balance"]}，当前{balance}；已核对空祭坛并归档旧记录，按当前余额继续，不重放旧兑换')

    def buy_blue_eggs_for_star_souls(self,balance):
        options=self.options['other']
        if not (options['buy_star_spores'] and options['convert_star_souls'] and
                options['evolve_blue_for_star_souls'] and options['buy_blue_eggs_for_star_souls']):
            raise SafetyStop('未开启用饲星之魂兑换幻化怪兽茧')
        if self.day.get('star_egg_purchase_pending'):
            raise TaskBlocked('上次幻化怪兽茧兑换结果待核实，未重复购买')
        s=self.open_star_shop()
        if star_souls(self.b,s)!=balance:raise TaskBlocked('兑换前饲星之魂余额变化')
        offer=blue_egg_offer(self.b,s)
        count=min(offer['remaining'],balance//25) if options['buy_all_blue_eggs'] else min(1,offer['remaining'])
        if count<1:raise TaskBlocked('没有可负担的幻化怪兽茧；未使用其他货币')
        self.b.click_at(s,offer['point'],['^商店$','^饲星商店$','^幻化怪兽茧$'],'查看幻化怪兽茧兑换')
        s=self.wait_for_screen(lambda q:bool(blue_egg_dialog(self.b,q,1)),'幻化怪兽茧25饲星之魂购买弹窗')
        if count==offer['remaining'] and count>1:
            self.b.click_text(s,'^MAX$',roi=(775,500,135,75))
            s=self.wait_for_screen(lambda q:bool(blue_egg_dialog(self.b,q,count)),
                                   '怪兽茧MAX数量和总饲星之魂')
        elif count>1:
            for number in range(2,count+1):
                self.b.click_at(s,(735,537),['^幻化怪兽茧$','^购买数量$'],'增加幻化怪兽茧兑换数量')
                s=self.wait_for_screen(lambda q:bool(blue_egg_dialog(self.b,q,number)),
                                       '怪兽茧数量和总饲星之魂')
        if star_souls(self.b,s)!=balance:raise TaskBlocked('兑换确认前饲星之魂余额变化')
        self.day['star_egg_purchase_pending']={'balance':balance,'remaining':offer['remaining'],'count':count}
        self.save_state()
        self.b.click_at(s,blue_egg_dialog(self.b,s,count).center,
                        ['^幻化怪兽茧$','^购买数量$','^购买$'],
                        f'兑换{count}个幻化怪兽茧（{25*count}饲星之魂）')
        s=self.settle_star_receipt()
        after=star_souls(self.b,s)
        now=blue_egg_stock(s)
        if after!=balance-25*count or now!=offer['remaining']-count:
            raise TaskBlocked('幻化怪兽茧兑换库存或余额未核实，未重复购买')
        self.day.pop('star_egg_purchase_pending',None);self.save_state()
        result=self.report.setdefault('other_tasks',{}).setdefault('star_spores',{})
        result['eggs_purchased']=result.get('eggs_purchased',0)+count
        result['spent_on_eggs']=result.get('spent_on_eggs',0)+25*count
        self.note(f'饲星补料：兑换幻化怪兽茧{count}个，饲星之魂{balance}→{after}')
        self.checkpoint()
        return after

    def one_blue_roster(self,*,level_one_only=True,skip_locked=False):
        # Standalone evolution stays in the roster/info flow after each success.
        # A world round trip per monster adds loading screens without any need.
        s=self.wait_for_scene_loading(self.observe()) if not level_one_only else None
        info=s is not None and (blue_monster_info(self.b,s,require_level_one=False) or
                               purple_monster_info(self.b,s,require_level_one=False))
        if s is None or not (info or monster_roster(s)):
            s=self.territory()
            self.b.click_text(s,'^怪兽$',roi=(755,630,130,90))
            s=self.wait_for_screen(lambda q:bool(q.find('^怪兽信息$',(90,0,230,60))),
                                   '怪兽信息')
        if not monster_roster(s):
            self.b.click_at(s,(60,674),['^怪兽信息$'],'打开按品质排序的怪兽列表')
            s=self.wait_for_screen(monster_roster,'怪兽列表品质排序')
        previous=None
        checks_left=18*36
        read_level=self.b.read_text_crop if level_one_only else None
        for page in range(18):
            for retry in range(4):
                cards=blue_roster_cards(s,read_level)
                if not level_one_only or any(row['level']==1 for row in cards) or not any(row['level'] is None for row in cards):break
                if retry==3:break
                self.note(f'蓝色怪兽等级未读清，等待列表稳定后重新识别（{retry+1}/3）')
                self.b.sleep(.7);s=self.wait_for_screen(monster_roster,'怪兽列表稳定')
            candidates=[row for row in cards if not level_one_only or row['level']==1]
            page_pixels=s.image[175:675,110:1250].copy()
            while candidates:
                if not checks_left:raise TaskBlocked('蓝怪列表反复重新定位，未能核对剩余候选')
                checks_left-=1
                chosen=candidates.pop(0)
                self.b.click_at(s,chosen['point'],['^怪兽数量$','^品质$'],
                                '选择1级幻化怪兽' if level_one_only else '选择蓝色幻化怪兽')
                s=self.wait_for_screen(monster_roster,'幻化怪兽已选中')
                self.b.click_at(s,(1228,106),['^怪兽数量$','^品质$'],'关闭怪兽列表')
                s=self.wait_for_screen(lambda q:blue_monster_info(self.b,q,require_level_one=level_one_only),
                                       '蓝色幻化怪兽信息')
                if skip_locked and s.find('^解锁$',(0,80,95,95)):
                    reason='当前蓝怪已锁定'
                else:
                    reason=blue_evolution_unavailable(s)
                if not reason:return s
                self.note('蓝怪进化：'+reason+'，继续查找')
                self.b.click_at(s,(60,674),['^怪兽信息$'],'继续查找未锁定蓝色怪兽')
                s=self.wait_for_screen(monster_roster,'返回怪兽品质列表')
                changed=np.max(np.abs(page_pixels.astype('int16')-s.image[175:675,110:1250].astype('int16')),axis=2)>35
                if changed.mean()>.05:
                    for read in range(3):
                        cards=blue_roster_cards(s,read_level)
                        selected=selected_blue_roster_index(s,cards)
                        if selected is not None:break
                        if read<2:s=self.observe();self.b.guard(s)
                    else:raise TaskBlocked('跳过蓝怪后列表位置改变，未认出已选蓝怪，未重用旧坐标')
                    candidates=[row for row in cards[selected+1:] if not level_one_only or row['level']==1]
                    page_pixels=s.image[175:675,110:1250].copy()
                    self.note('蓝怪列表已重新定位，从已选蓝怪之后继续检查')
            if level_one_only and cards and any(row['level'] is None for row in cards):
                raise TaskBlocked('已看到蓝色怪兽但等级未读清，未购买更多怪兽茧')
            pixels=s.image[165:675,110:1250].copy()
            if previous is not None and np.mean(np.abs(pixels.astype('int16')-previous.astype('int16')))<2:
                return None
            previous=pixels
            self.b.guard(s)
            if not self.b.wait(self.b.controller.post_swipe(840,570,840,285,650)).succeeded:
                raise TaskBlocked('查找蓝色怪兽时列表滑动失败')
            self.b.sleep(.7)
            s=self.wait_for_screen(monster_roster,'怪兽列表继续向下')
        raise TaskBlocked('未到达怪兽列表底部，不能确认蓝色怪兽库存')

    def evolve_one_blue_for_star_souls(self,balance):
        options=self.options['other']
        if not (options['buy_star_spores'] and options['convert_star_souls'] and
                options['evolve_blue_for_star_souls']):
            raise SafetyStop('未开启蓝色怪兽进化饲星')
        if self.state.get('blue_evolution_pending'):raise TaskBlocked('蓝怪进化紫怪尚待核实，未进行饲星补料')
        if self.day.get('star_evolution_pending'):
            self.complete_star_evolution(self.observe())
            return star_souls(self.b,self.open_star_shop())
        s=self.one_blue_roster()
        if s is None:
            if not options['buy_blue_eggs_for_star_souls']:
                raise TaskBlocked('没有可安全进化的1级幻化怪兽；自动兑换怪兽茧未开启')
            from .monster_boxes import monster_box_stock
            item=self.monster_box_inventory()
            if item is None or monster_box_stock(item)==0:
                balance=self.buy_blue_eggs_for_star_souls(balance)
                item=self.monster_box_inventory()
            if item is None or not monster_box_stock(item):
                raise TaskBlocked('怪兽茧兑换后未在背包核实库存，未开启')
            self.open_one_monster_box(item,options['star_egg_target'],'star_souls')
            s=self.one_blue_roster()
            if s is None:raise TaskBlocked('开启怪兽茧后仍未找到可进化的1级蓝色怪兽')
        if s.find('^解锁$',(0,80,95,95)):
            raise TaskBlocked('当前幻化怪兽已锁定，未进化')
        self.b.click_text(s,'^进化$',roi=(1000,395,180,90))
        s=self.wait_for_screen(lambda q:bool(q.find('^进化$',(105,0,110,60))),
                               '幻化怪兽进化分支')
        if s.find('^消耗材料$',(70,580,160,65)):
            raise TaskBlocked('进化分支意外直接进入材料确认，未选目标')
        self.b.click_at(s,(470,370),['^进化$'],'查看左侧究极进化分支')
        s=self.wait_for_screen(lambda q:bool(evolution_offer(self.b,q)),
                               '究极进化目标、金币及进化孢子费用')
        offer=evolution_offer(self.b,s)
        if offer['gold_balance']<offer['gold'] or offer['spore_balance']<offer['spores']:
            raise TaskBlocked('进化金币或进化孢子不足，未进化幻化怪兽')
        self.day['star_evolution_pending']={**offer,'status':'submitted'}
        self.save_state()
        self.b.click_at(s,(1072,663),['^进化$','^消耗材料$'],
                        f'将1级幻化怪兽进化为{offer["name"]}；金币{offer["gold"]}、孢子{offer["spores"]}')
        self.complete_star_evolution(self.observe(),submitted_now=True)
        return star_souls(self.b,self.open_star_shop())

    def complete_star_evolution(self,s,*,submitted_now=False):
        offer=self.day.get('star_evolution_pending')
        if not offer:raise TaskBlocked('没有待核实的进化记录，未更改养成状态')
        for _ in range(28):
            self.b.guard(s)
            if purple_monster_info(self.b,s) and (submitted_now or offer.get('reveal_seen')):
                self.day.pop('star_evolution_pending',None);self.save_state()
                result=self.report.setdefault('other_tasks',{}).setdefault('star_spores',{})
                result['evolved']=result.get('evolved',0)+1
                self.report.setdefault('star_evolutions',[]).append({**offer,'status':'confirmed',
                    'resumed':not submitted_now})
                self.note(f'已核实1只蓝色怪兽进化为究极{offer["name"]}；原进化金币{offer["gold"]}、进化孢子{offer["spores"]}')
                self.checkpoint()
                return s
            if evolution_result_name(self.b,s)==offer['name']:
                offer['reveal_seen']=True;self.save_state()
                self.b.save_screen(s,self.report['folder']/'star-evolution-reveal.png')
                s=self.close_star_evolution_result(s,offer['name']);continue
            if s.find('进化成功|进化完成') and s.find('点击空白位置关闭'):
                offer['reveal_seen']=True;self.save_state()
                s=self.close_star_evolution_result(s,offer['name']);continue
            if not submitted_now:raise TaskBlocked('上次进化结果尚未在当前页面核实，未重复进化')
            self.b.sleep(.5);s=self.observe()
        raise TaskBlocked('进化点击后尚未核实目标究极品级，已记录待核实，不重复进化')

    def close_star_evolution_result(self,s,name,*,require_level_one=True):
        def close(q):
            if evolution_result_name(self.b,q)==name:
                anchors=['^'+re.escape(name)+'$','^详细属性$','^不朽$']
            elif q.has('进化成功|进化完成','点击空白位置关闭'):
                anchors=['进化成功|进化完成','点击空白位置关闭']
            else:return
            try:self.b.click_at(q,(640,660),anchors,'关闭已完成的怪兽进化展示')
            except PageChanged:pass  # The free dismissal already took effect.
        close(s)
        return self.wait_for_screen(lambda q:purple_monster_info(self.b,q,require_level_one=require_level_one),
            '进化展示关闭后返回究极怪兽信息',timeout=4,retry_navigation=close)

    def read_star_offers(self,s):
        for retry in range(4):
            self.b.guard(s)
            try:return s,spore_offers(self.b,s)
            except TaskBlocked:
                if retry==3:raise
                self.note(f'饲星商店库存或费用未读清，重新识别（{retry+1}/3）')
                self.b.sleep(.6);s=self.observe()

    def open_star_shop(self):
        s = self.observe()
        if star_shop_page(s):
            return s
        if s.has('^饲星坛$','^怪兽饲星$'):
            self.b.confirm_label(s,'^商店$',(0,605,120,80),threshold=.8)
        if not star_altar(s):
            s = self.territory()
            self.b.click_at(s, (640, 442), ['^世界$', '^排阵$'], '进入饲星坛')
            s = self.wait_for_screen(star_altar, '饲星坛')
        def open_menu(q):
            # Only navigation is retried. The tiny caption can disappear from
            # full-frame OCR on the next animation frame; reread its own area.
            self.b.confirm_label(q,'^商店$',(0,605,120,80),threshold=.8)
            if not star_altar(q) or q.find('^取消$|^确定$|^购买数量$|^获得奖励$'):return
            self.b.click_at(q,q.find('^商店$',(0,605,120,80)).center,
                ['^饲星坛$','^怪兽饲星$','^商店$'],'进入饲星商店')
        open_menu(self.observe())
        return self.wait_for_screen(star_shop_page, '饲星商店孢子货架',timeout=4,retry_navigation=open_menu)

    def settle_star_receipt(self):
        confirmed = False
        for _ in range(20):
            s = self.observe(); self.b.guard(s)
            confirmation = star_conversion_confirmation(s, getattr(self.b, 'star_conversion_pending', None))
            if confirmation:
                if confirmed:
                    self.b.sleep(.5)
                    continue
                self.b.click_at(s, confirmation.center, ['^取消$', '^'+confirmation.text+'$'],
                                '确认仅转化已核实的1只究极怪兽')
                confirmed = True
                continue
            if star_conversion_countdown(s,getattr(self.b,'star_conversion_pending',None)):
                self.b.sleep(.5)
                continue
            if s.find('^获得奖励$', (400, 70, 500, 160)) and s.find('点击空白位置关闭'):
                self.b.click_at(s, (640, 660), ['^获得奖励$', '点击空白位置关闭'],
                                '关闭饲星奖励')
                continue
            if star_shop_page(s):
                return s
            if star_conversion_page(s):
                if not getattr(self.b, 'star_conversion_pending', None) or star_yield(self.b, s) == 0:
                    return s
                # A still-selected monster can be the pre-request frame while
                # the server is loading. Wait rather than navigate over it.
            self.b.sleep(.5)
        raise TaskBlocked('饲星操作结果未确认，未重复消耗')

    def convert_one_ultimate(self, required, balance,*,allow_evolve=True):
        if not self.options['other']['buy_star_spores'] or not self.options['other']['convert_star_souls']:
            raise SafetyStop('未开启自动转化饲星之魂')
        if required <= balance:
            return balance
        if self.state.get('blue_evolution_pending'):raise TaskBlocked('蓝怪进化紫怪尚待核实，未转化怪兽')
        if self.day.get('star_conversion_pending'):
            raise TaskBlocked('上次饲星转化尚未核实，请检查结果后继续；未重复转化')
        s = self.open_star_shop()
        if star_souls(self.b, s) != balance:
            raise TaskBlocked('转化前饲星之魂余额变化，未选择怪兽')
        self.b.click_at(s, (43, 28), ['^商店$', '^饲星商店$'], '返回饲星坛')
        s = self.wait_for_screen(star_altar, '饲星坛')
        self.b.click_text(s, '^怪兽饲星$', roi=(0, 310, 160, 90))
        s = self.wait_for_screen(star_conversion_page, '怪兽饲星')
        if star_yield(self.b, s) != 0:
            raise TaskBlocked('饲星坛已有选择或奖励未读清，保留用户选择')
        # Quality-descending view starts with the highest rarities. Inspect
        # overlapping pages until one untrained ultimate is found.
        candidate = None; previous = None; unreadable=False
        for _ in range(15):
            for row in ultimate_candidates(s):
                level=ultimate_level(self.b,s,row)
                if level is None:unreadable=True
                if level==1:
                    candidate = row
                    break
            if candidate:
                break
            pixels = s.image[135:645, 788:1155].copy()
            if previous is not None and np.mean(np.abs(pixels.astype('int16')-previous.astype('int16'))) < 2:
                break
            previous = pixels
            self.b.guard(s)
            self.b.wait(self.b.controller.post_swipe(1035, 588, 1035, 340, 1100))
            self.b.sleep(1)
            s = self.wait_for_screen(star_conversion_page, '饲星怪兽列表')
        if candidate is None:
            if unreadable:
                raise TaskBlocked('已看到究极怪兽，但等级未读清，未进化或购买补料')
            if allow_evolve and self.options['other']['evolve_blue_for_star_souls']:
                self.note('没有可安全饲星的1级究极怪兽，检查蓝色幻化怪兽补料')
                new_balance=self.evolve_one_blue_for_star_souls(balance)
                return self.convert_one_ultimate(required,new_balance,allow_evolve=False)
            raise TaskBlocked('饲星之魂不足，未找到可安全转化的1级究极怪兽')
        fresh = self.observe()
        rows = ultimate_candidates(fresh)
        if candidate not in rows or ultimate_level(self.b,fresh,candidate)!=1:
            raise TaskBlocked('转化候选怪兽品级或等级变化，未选择')
        self.b.click_at(fresh, candidate['point'], ['^饲星坛$', '^怪兽饲星$'], '只选择一只1级究极怪兽')
        s = self.wait_for_screen(lambda q:star_conversion_page(q) and star_yield(self.b, q) == 75,
                                 '单只究极怪兽转化75饲星之魂')
        self.day['star_conversion_pending'] = {'balance':balance, 'yield':75}
        self.save_state()
        self.b.star_conversion_pending = {'rarity':'究极', 'count':1, 'yield':75}
        try:
            self.b.click_text(s, '^怪兽饲星$', roi=(300, 595, 300, 90))
            self.settle_star_receipt()
        finally:
            self.b.star_conversion_pending = None
        s = self.open_star_shop()
        after = star_souls(self.b, s)
        if after != balance+75:
            raise TaskBlocked('饲星转化后未核实增加75饲星之魂，未继续转化')
        self.day.pop('star_conversion_pending', None); self.save_state()
        self.note(f'已转化1只究极怪兽，饲星之魂 {balance}→{after}')
        return after

    def select_spore_quantity(self,s,offer,count):
        name=offer['name']
        if type(count) is not int or not 1<=count<=min(offer['remaining'],10):
            raise TaskBlocked('整批孢子数量超出已确认库存')
        if not spore_purchase_dialog(self.b,s,name,1):
            raise TaskBlocked('孢子数量调整前购买页面未确认')
        if count==offer['remaining'] and count>1:
            self.b.click_text(s,'^MAX$',roi=(775,500,135,75))
            s=self.wait_for_screen(lambda q:bool(spore_purchase_dialog(self.b,q,name,count)),
                f'{name}整批{count}份及总价{30*count}饲星之魂')
        elif count>1:
            for quantity in range(2,count+1):
                self.b.click_at(s,(735,537),['^'+name+'$','^购买数量$'],'增加'+name+'整批购买数量')
                s=self.wait_for_screen(lambda q:bool(spore_purchase_dialog(self.b,q,name,quantity)),
                    f'{name}数量{quantity}及总价{30*quantity}饲星之魂')
        return s

    def reconcile_star_spore_purchase(self,result,offers,balance):
        pending=self.day.get('star_purchase_pending')
        if not pending:return
        count=pending.get('count',1)  # Existing single-purchase receipts remain valid.
        now=next((o for o in offers if o['name']==pending.get('name')),None)
        if (type(count) is not int or not 1<=count<=10 or now is None or
                pending.get('price')!=30 or now['remaining']!=pending['remaining']-count or
                balance!=pending['balance']-30*count):
            raise TaskBlocked('上次孢子购买后库存或余额变化未核实，未重复购买')
        receipt=f'{self.date}:{pending["name"]}:{pending["remaining"]}:{pending["balance"]}:{count}'
        receipts=result.setdefault('receipts',[])
        if receipt not in receipts:
            result['purchased'][pending['name']]=result['purchased'].get(pending['name'],0)+count
            result['spent']+=30*count;result['remaining']=balance;receipts.append(receipt)
            self.note(f'已购买{count}份{pending["name"]}，消耗{30*count}饲星之魂')
            self.checkpoint()
        self.day.pop('star_purchase_pending');self.save_state()

    def buy_star_spores(self):
        if not self.options['other']['buy_star_spores']:
            return {'status':'skipped', 'message':'饲星商店购买未开启'}
        self.reconcile_star_conversion_pending()
        s = self.open_star_shop(); balance = star_souls(self.b, s)
        result = self.report.setdefault('other_tasks', {}).setdefault('star_spores',
            {'purchased':{}, 'converted':0, 'spent':0, 'start':balance})
        for _ in range(40):
            s, offers = self.read_star_offers(self.open_star_shop())
            balance = star_souls(self.b, s); result['remaining'] = balance
            conversion = self.day.get('star_conversion_pending')
            if conversion:
                if balance != conversion['balance']+conversion['yield']:
                    raise TaskBlocked('上次饲星转化尚未核实，未重复转化')
                self.day.pop('star_conversion_pending'); self.save_state()
            self.reconcile_star_spore_purchase(result,offers,balance)
            required = sum(o['remaining']*o['price'] for o in offers)
            if not required:
                result.update(status='done', message=f'饲星商店孢子已购完；本轮购买{sum(result["purchased"].values())}份，消耗{result["spent"]}饲星之魂，剩余{balance}')
                return result
            if balance < required and self.options['other']['convert_star_souls']:
                count = conversions_needed(required, balance)
                self.note(f'孢子购买缺少{required-balance}饲星之魂，最多转化{count}只究极怪兽')
                balance = self.convert_one_ultimate(required, balance)
                result['converted'] += 1; self.checkpoint()
                continue
            offer = next((o for o in offers if o['remaining'] and o['price'] <= balance), None)
            if offer is None:
                result.update(status='skipped', message=f'饲星之魂剩余{balance}，不足购买剩余孢子；自动转化未开启，未消耗其他资源')
                return result
            count=min(offer['remaining'],balance//offer['price'])
            self.b.click_at(s, offer['point'], ['^商店$', '^饲星商店$', '^'+offer['name']+'$'],
                            '查看'+offer['name']+'购买详情')
            s = self.wait_for_screen(lambda q:bool(spore_purchase_dialog(self.b, q, offer['name'])),
                                     '孢子购买数量、名称及饲星之魂费用')
            s = self.select_spore_quantity(s,offer,count)
            if star_souls(self.b, s) != balance:
                raise TaskBlocked('购买确认前饲星之魂余额变化，未购买')
            button=spore_purchase_dialog(self.b,s,offer['name'],count)
            if not button:raise TaskBlocked('整批孢子数量或总费用变化，未购买')
            self.day['star_purchase_pending'] = {**offer, 'balance':balance,'count':count}
            self.save_state()
            self.b.click_at(s,button.center,['^'+offer['name']+'$', '^购买数量$', '^购买$'],
                            f'购买{count}份{offer["name"]}（{30*count}饲星之魂）')
            s = self.settle_star_receipt()
            s,offers=self.read_star_offers(s)
            after = star_souls(self.b, s)
            self.reconcile_star_spore_purchase(result,offers,after)
        raise TaskBlocked('饲星商店库存未按预期减少，停止继续购买')

    def open_tribe_donation(self):
        s = self.observe()
        if donation_page(s):
            return s
        from .activities import is_tribe_map
        if not is_tribe_map(s):
            s = self.territory()
            self.b.click_at(s, (1036, 442), ['^世界$', '^排阵$'], '进入部落支配核心')
            s = self.wait_for_screen(is_tribe_map, '部落地图')
        s = self.claim_tribe_occupation(s)
        self.b.click_at(s, (1005, 631), ['^部落$', '^部落大厅$'], '打开支配核心')
        return self.wait_for_screen(donation_page, '支配核心金币捐献')

    def tribe_gold_donation(self):
        if not self.options['other']['tribe_gold_donation']:
            return {'status':'skipped', 'message':'支配核心金币捐献未开启'}
        s = self.open_tribe_donation()
        remaining = gold_donation_remaining(s)
        if remaining == (0, 1):
            if self.options['tribe']['claim_donation_rewards'] and self.b.tasker is not None:
                self.claim_tribe_donation_rewards(s)
            return {'status':'done', 'count':0, 'spent_gold':0, 'message':'今日金币捐献已完成，剩余0/1，未重复捐献'}
        point = gold_donation_offer(self.b, s)
        if point is None:
            raise TaskBlocked('左侧金币捐献次数、金币图标或20万费用未确认，未点击')
        gold = self.b.read_text_crop(s, (1064, 7, 70, 42))
        match = re.fullmatch(r'(\d+(?:\.\d+)?)万', gold)
        balance = int(float(match[1])*10000) if match else int(gold) if gold.isdigit() else None
        if balance is not None and balance < 200000:
            return {'status':'skipped', 'count':0, 'spent_gold':0, 'message':'金币余额不足20万，未捐献'}
        self.b.click_at(s, point, ['^支配核心$', '^20万$'], '仅使用左侧20万金币捐献')
        for _ in range(10):
            s = self.observe(); self.b.guard(s)
            if s.find('^获得奖励$', (400, 70, 500, 160)) and s.find('点击空白位置关闭'):
                self.b.click_at(s, (640, 660), ['^获得奖励$', '点击空白位置关闭'], '关闭金币捐献奖励')
                continue
            if gold_donation_remaining(s) == (0, 1):
                if self.options['tribe']['claim_donation_rewards'] and self.b.tasker is not None:
                    self.claim_tribe_donation_rewards(s)
                return {'status':'done', 'count':1, 'spent_gold':200000,
                        'message':'金币捐献完成1次，消耗20万金币，剩余0/1，钻石支出0'}
            self.b.sleep(.5)
        raise TaskBlocked('金币捐献结果未确认，未重复点击')
