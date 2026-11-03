"""Opt-in wild encounters: preflight all traps, verify each +5%, never buy."""
from __future__ import annotations
import re
import time
from datetime import datetime

import cv2
import numpy as np

from .anomalies import is_event_panel
from .backend import Word
from .policy import TaskBlocked,SafetyStop,UserStopped
from .wild_settings import RARITIES,wild_options,wild_enabled,required_traps

WILD_NAME=r'^野生\s*[-－—·]\s*([\u4e00-\u9fff]{1,10})(?:[^\u4e00-\u9fff\d]*)$'
WILD_TITLE=r'^野生\s*[-－—·].{0,24}$'
CAPTURE_ANCHORS=('^退出$','^使用捕兽夹$','^捕捉怪兽$')
CAPTURE_TITLE_ROI=(580,0,220,75)


def is_wild_offer(s):
    return bool(s.find(WILD_TITLE,(320,95,410,70)) and s.find('^前往$',(500,555,260,80)))


def is_wild_capture(s):
    return bool(s.find('^退出$',(0,0,150,65)) and s.find('^使用捕兽夹$',(360,575,240,85)) and
                s.find('^捕捉怪兽$',(690,585,250,90)))


def is_wild_list(s):
    if not (is_event_panel(s) and s.find('^探索$',(900,0,210,70)) and s.find('^野生$',(990,650,220,70))):return False
    if s.find('剩余可指派怪兽|^全部开始$|^全部领取$'):return False
    # Both tabs are always visible; only the selected wild tab has a gold fill.
    crop=s.image[676:703,1025:1175]
    return bool(((crop[:,:,2]>140)&(crop[:,:,1]>95)&(crop[:,:,0]<145)&
                 (crop[:,:,2].astype(int)-crop[:,:,0]>45)).mean()>.30)


def wild_cards(s):
    if not is_wild_list(s):return []
    return sorted((w for w in s.words if re.fullmatch(WILD_TITLE,w.text) and
                   810<w.center[0]<1195 and 115<w.center[1]<640),key=lambda w:w.center[1])


def wild_absent(s):
    return bool(is_wild_list(s) and s.find('^野生怪兽未出现$',(830,365,370,145)) and not wild_cards(s))


def colored_rarity(s,box):
    """Use only the monster's colored name, not the artwork/background hue.

    Narrow, separated HSV bands + dominant color are required. Unknown/mixed
    colors remain unknown; they are never rounded down to an allowed rarity.
    """
    x,y,w,h=box
    a=s.image[max(0,y):min(720,y+h),max(0,x):min(1280,x+w)]
    if not a.size:return None
    hsv=cv2.cvtColor(a,cv2.COLOR_BGR2HSV)
    hue=hsv[:,:,0][(hsv[:,:,1]>90)&(hsv[:,:,2]>70)]
    if len(hue)<35:return None
    bands={'young':(40,85),'phantom':(95,119),'ultimate':(125,149),'immortal':(15,37)}
    scores={key:float(((hue>=lo)&(hue<=hi)).mean()) for key,(lo,hi) in bands.items()}
    scores['awakened']=float(((hue<=10)|(hue>=170)).mean())
    key=max(scores,key=scores.get)
    return key if scores[key]>=.80 else None


def wild_identity(s,*,title_word=None):
    if is_wild_offer(s):
        title=s.find(WILD_TITLE,(320,95,410,70));match=re.fullmatch(WILD_NAME,title.text)
        name=match[1] if match else None
        word=s.find('^'+re.escape(name)+'$',(540,475,250,65)) if name else None
    elif is_wild_capture(s):
        word=title_word or s.find(r'^[\u4e00-\u9fff]{1,10}$',CAPTURE_TITLE_ROI)
        name=word.text if word else None
    else:return None
    rarity=colored_rarity(s,word.box) if word else None
    # The grade badge is independent of name OCR and its adjacent info icon.
    # Names are optional log labels; never infer a grade from monster artwork.
    badge_color=colored_rarity(s,(524,22,35,35) if is_wild_capture(s) else (530,486,35,35))
    evidence={value for value in (rarity,badge_color) if value is not None}
    badge_roi=(510,475,70,65) if is_wild_offer(s) else (510,0,75,70)
    labels={key for key,r in RARITIES.items() if s.find('^'+r['label']+'$',badge_roi)}
    evidence.update(labels)
    rarity=next(iter(evidence)) if len(evidence)==1 else None
    return {'name':name,'rarity':rarity}


def capture_values(s):
    if not is_wild_capture(s):return None
    chance=re.search(r'成功率\s*(\d{1,3})\s*[%％]',s.region_text((500,495,300,70)))
    stock=s.region_text((1160,0,115,55)).strip()
    cost=s.region_text((965,595,70,75)).strip()
    step=re.search(r'(\d+)\s*[%％]',s.region_text((260,625,115,50)))
    unit=s.region_text((475,635,60,40)).strip()
    chance=int(chance[1]) if chance else None
    return {'probability':chance if chance is not None and 0<=chance<=100 else None,
            'traps':int(stock) if stock.isdigit() else None,
            'cost':int(cost) if cost.isdigit() else None,
            'increment':int(step[1]) if step else None,
            'trap_cost':1 if re.fullmatch(r'[^\d]*1',unit) else None}


def wild_result(s,name):
    # The click or reaching 100% is never evidence of obtaining a monster.
    if s.find('捕捉失败|捕获失败|逃跑了|捕捉未成功'):return 'escaped'
    if s.find('捕捉成功|捕获成功'):return 'captured'
    if s.find('^获得奖励$',(450,90,380,110)) and s.find('点击空白位置关闭') and s.find(r'^等级\s*1$',(640,350,70,60)):
        return 'captured'  # Whole monster cards have a level; shards have a quantity.
    if s.find('^获得奖励$') and s.find('碎片'):
        return 'fragments'
    return None


class WildCapture:
    def confirm_wild_identity(self,s,entry,stage,*,title_roi=None):
        """Confirm the selected grade; name OCR never gates capture or traps."""
        expected={'rarity':entry['rarity']}
        actual=None
        for attempt in range(4):
            if attempt:
                self.note(f'{stage}怪兽信息未确认，重新读取 {attempt}/3（不重复使用捕兽夹）')
                self.report.setdefault('wild_identity_retries',[]).append(
                    {'stage':stage,'attempt':attempt,'expected':expected,'observed':actual})
                self.checkpoint();self.b.sleep(.6)
                s=self.observe()
            self.b.guard(s)
            actual=wild_identity(s)
            if actual and actual['rarity']==expected['rarity']:
                word=s.find('^'+re.escape(entry['name'])+'$',CAPTURE_TITLE_ROI)
                if word:
                    x,y,w,h=word.box
                    title_roi=(max(0,x-6),max(0,y-6),w+12,h+12)
                return s,title_roi
            # A known name rectangle can still supply color evidence if the
            # badge is temporarily obscured; its text is only a log label.
            if (is_wild_capture(s) and title_roi is not None and
                    (actual is None or actual['rarity'] is None)):
                text=self.b.read_text_crop(s,title_roi).strip()
                if re.fullmatch(r'[\u4e00-\u9fff]{1,10}',text):
                    actual=wild_identity(s,title_word=Word(text,list(title_roi),.99))
                    if actual and actual['rarity']==expected['rarity']:
                        self.note(f'{stage}：单独读取名字区域，已确认{entry["name"]}及品级')
                        self.report.setdefault('wild_identity_crops',[]).append(
                            {'stage':stage,'name':text,'roi':list(title_roi)})
                        self.checkpoint()
                        return s,title_roi
        if actual and actual.get('rarity') is not None and actual['rarity']!=expected['rarity']:
            grade=RARITIES.get(actual['rarity'],{}).get('label','未知品级')
            raise SafetyStop(f'{stage}复核后目标不一致：识别到{grade}-{actual["name"]}，已停止；未重复消耗')
        raise TaskBlocked(f'{stage}怪兽品级未读清，已重试3次；未继续使用捕兽夹或捕捉')

    def wild_check(self,status,message):
        row={'time':datetime.now().isoformat(timespec='seconds'),'status':status,'message':message}
        self.report.setdefault('wild_checks',[]).append(row)
        self.note(message);self.emit('wild_check',row);self.checkpoint()

    def wild_outcome(self,s,name):
        result=wild_result(s,name)
        if result:return result
        if s.find('^获得奖励$',(450,90,380,110)) and s.find('点击空白位置关闭'):
            self.b.save_screen(s,self.report['folder']/'wild-reward-observed.png')
            # Full-frame OCR misses the tiny level label on the reward portrait.
            roi=(646,364,52,26)
            text=self.b.read_text_crop(s,roi)
            if re.fullmatch(r'等级\s*1',text):
                s.words.append(Word(text,list(roi),.99))
                return wild_result(s,name)
        return None

    def wild_allowed(self):
        return wild_enabled(self.b.settings)

    def wild_notice(self,entry,status,message,**details):
        entry.update(status=status,message=message,**details)
        self.report.setdefault('events',[]).append({'time':datetime.now().isoformat(timespec='seconds'),'message':message,'rarity':entry['rarity']})
        self.emit('wild_notice',entry.copy());self.checkpoint()

    def wild_wait(self,predicate,message,seconds=18):
        until=time.monotonic()+seconds
        while time.monotonic()<until:
            s=self.observe();self.b.guard(s)
            if predicate(s):return s
            self.b.sleep(.5)
        raise TaskBlocked(message)

    def close_wild(self,s):
        if is_wild_offer(s):self.b.click_at(s,(927,111),[WILD_TITLE,'^前往$'],'关闭野生怪兽介绍')
        elif is_wild_capture(s):self.b.click_text(s,'^退出$',roi=(0,0,150,65))
        elif is_wild_list(s):self.b.click_at(s,(770,680),['^野生$','^传送$'],'收起野生怪兽列表')
        else:raise TaskBlocked('野生怪兽页面未确认，未猜测返回位置')
        return self.observe()

    def open_wild_list(self,s):
        s=self.open_world_events(s)
        self.b.click_text(s,'^探索$',roi=(1200,510,80,100))
        s=self.wild_wait(lambda q:is_event_panel(q) and q.find('^野生$',(990,650,220,70)),
                         '事件中的探索分类尚未打开')
        self.b.click_text(s,'^野生$',roi=(990,650,220,70))
        s=self.wild_wait(is_wild_list,'野生怪兽列表未确认')
        self.b.save_screen(s,self.report['folder']/'wild-list.png')
        return s

    def maybe_capture_wild(self,s,*,encounter=False):
        """Only invoked at a safe world boundary; all unchecked is zero extra I/O."""
        if not self.wild_allowed() or getattr(self,'_handling_wild',False):return s
        if not encounter and time.monotonic()-getattr(self,'_wild_scan_at',float('-inf'))<600:return s
        self._handling_wild=True;self._wild_scan_at=time.monotonic()
        seen=getattr(self,'_wild_seen',set());self._wild_seen=seen
        try:
            if encounter:
                # Read map stamina before spending traps, even if started on a modal.
                s=self.home(self.close_wild(s))
            from .workflows import is_world
            if not is_world(s):return s
            resources=self.world_resources(s)
            self.note('检查野生怪兽 · 按勾选品级与成功率捕捉')
            menu=self.open_wild_list(s)
            cards=wild_cards(menu)
            if not cards:
                # Allow the selected tab's content to finish rendering; no extra click.
                for _ in range(2):
                    self.b.sleep(.5);menu=self.observe();self.b.guard(menu)
                    if not is_wild_list(menu):raise TaskBlocked('读取野生怪兽列表时页面改变')
                    cards=wild_cards(menu)
                    if cards:break
            if not cards:
                if not wild_absent(menu):raise TaskBlocked('野生列表已打开，但未读清怪兽或“野生怪兽未出现”提示')
                self.wild_check('absent','当前野生怪兽未出现，跳过捕捉；后续以游戏实际刷新为准')
                return self.home(self.close_wild(menu))
            # The event panel currently presents one wild encounter card.
            # Do not cycle through it again after an uncertain input/result.
            card=cards[0];match=re.fullmatch(WILD_NAME,card.text)
            name=match[1] if match else '名称未识别'
            self.wild_check('available','野生列表发现怪兽-'+name+'，核对捕捉条件')
            if name in seen:return self.home(self.close_wild(menu))
            seen.add(name)
            self.b.click_text(menu,'^'+re.escape(card.text)+'$')
            offer=self.wild_wait(is_wild_offer,'定位野生怪兽后介绍尚未打开',seconds=45)
            identity=wild_identity(offer)
            if identity is None:raise TaskBlocked('野生怪兽介绍页面未确认')
            entry={'name':name,'rarity':identity['rarity'],'status':'pending','message':'野生怪兽-'+name+'：等待核对','traps_used':0}
            self.report.setdefault('wild_captures',[]).append(entry);self.checkpoint()
            rarity=identity['rarity']
            if rarity is None:
                # Some badge fonts are unreadable: the capture page has a larger name.
                self.b.click_text(offer,'^前往$',roi=(500,555,260,80))
                page=self.wild_wait(is_wild_capture,'野生怪兽捕捉页未打开')
                identity=wild_identity(page)
                if identity is None:raise TaskBlocked('野生怪兽捕捉页面未确认')
                rarity=identity['rarity'];entry['rarity']=rarity
            else:page=None
            if rarity is None:
                self.wild_notice(entry,'unrecognized','野生怪兽-'+name+'：品级未识别，未捕捉')
            else:
                label=RARITIES[rarity]['label'];option=wild_options(self.b.settings)[rarity]
                if not option['enabled']:
                    self.wild_notice(entry,'unchecked',f'发现{label}怪兽-{name}：未勾选该品级，未捕捉')
                elif resources['stamina'] is None or resources['stamina']<20:
                    self.wild_notice(entry,'insufficient_stamina',f'{label}怪兽-{name}：体力不足20或未读清，未使用捕兽夹、未捕捉')
                else:
                    if page is None:
                        self.b.click_text(offer,'^前往$',roi=(500,555,260,80))
                        page=self.wild_wait(is_wild_capture,'野生怪兽捕捉页未打开')
                    self.capture_wild(page,entry,resources)
                    return self.home()
            return self.home(self.close_wild(page if page is not None else offer))
        except TaskBlocked as e:
            # Navigation/recognition failures must leave a truthful final reminder.
            entry=locals().get('entry')
            if entry is None and 'name' not in locals():
                # A navigation failure does not establish that any monster exists.
                if getattr(self,'last_screen',None) is not None:
                    self.b.save_screen(self.last_screen,self.report['folder']/'wild-check-unconfirmed.png')
                self.wild_check('navigation_failed','野生怪兽检查未完成：'+str(e)+'；是否刷新尚未确认，未捕捉、未使用捕兽夹')
                return self.home()
            if entry is None:
                entry={'name':name,'rarity':None,'traps_used':0}
                self.report.setdefault('wild_captures',[]).append(entry)
            if entry.get('status') in ('captured','escaped','fragments'):
                entry['navigation_error']=str(e);self.checkpoint()
            else:
                grade=RARITIES.get(entry.get('rarity'),{}).get('label','')
                self.wild_notice(entry,'unconfirmed',f"{grade}怪兽-{entry['name']}：{e}；已核实使用{entry.get('traps_used',0)}个捕兽夹，未重复消耗")
            return self.home()
        except (SafetyStop,UserStopped) as e:
            entry=locals().get('entry')
            if entry is not None and entry.get('status') not in ('captured','escaped','fragments'):
                grade=RARITIES.get(entry.get('rarity'),{}).get('label','')
                self.wild_notice(entry,'interrupted',f"{grade}怪兽-{entry['name']}：{e}；捕捉未完成，已核实使用{entry['traps_used']}个夹子")
            raise
        finally:self._handling_wild=False

    def capture_wild(self,s,entry,resources):
        name=entry['name'];rarity=entry['rarity'];label=RARITIES[rarity]['label']
        options=wild_options(self.b.settings)
        if not options[rarity]['enabled']:raise SafetyStop('未勾选这个品级，禁止使用捕兽夹或捕捉')
        if not self.wild_allowed():raise SafetyStop('自动捕捉已关闭，禁止使用捕兽夹或捕捉')
        target=options[rarity]['probability'];entry['target_probability']=target
        self.b.save_screen(s,self.report['folder']/'wild-capture-page.png')
        s,title_roi=self.confirm_wild_identity(s,entry,'捕捉页')
        values=capture_values(s)
        # The one-digit trap cost is occasionally dropped by full-frame OCR.
        # Re-read its actual pixels instead of assuming that every use costs 1.
        if values['trap_cost'] is None:values['trap_cost']=self.b.read_number(s,(499,637,18,28))
        if values['traps'] is None:values['traps']=self.b.read_number(s,(1180,13,88,31))
        if any(values[k] is None for k in ('probability','traps','cost','increment','trap_cost')):
            raise TaskBlocked('当前概率、捕兽夹库存或费用未读清：'+str(values))
        if values['cost']!=20 or values['increment']!=5 or values['trap_cost']!=1 or not self.b.match_template(s,'wild-stamina.png',(915,595,65,65),.90):
            raise TaskBlocked('捕捉费用或捕兽夹每次提升5%的规则改变')
        needed=required_traps(values['probability'],target)
        entry.update(probability_before=values['probability'],stock_before=values['traps'],traps_required=needed,
                     stamina_before=resources['stamina'],status='preflight',message=f'{label}怪兽-{name}：正在核对捕捉条件')
        self.checkpoint()
        if resources['stamina'] is None or resources['stamina']<20:
            self.wild_notice(entry,'insufficient_stamina',f'{label}怪兽-{name}：体力不足20，未捕捉');return
        if values['traps']<needed:
            self.wild_notice(entry,'insufficient_traps',f'{label}怪兽-{name}：达到{target}%需要{needed}个捕兽夹，库存{values["traps"]}个；未使用、未捕捉');return
        for _ in range(needed):
            before=values
            self.b.save_screen(s,self.report['folder']/'wild-before-trap.png')
            entry.update(status='using_trap',message=f'{label}怪兽-{name}：捕兽夹使用后等待确认');self.checkpoint()
            # Never retry this input: an unconfirmed response may have spent a trap.
            self.b.click_at(s,(481,618),list(CAPTURE_ANCHORS),'野生怪兽使用1个库存捕兽夹')
            def increased(q):
                v=capture_values(q)
                return bool(v and v['probability']==min(100,before['probability']+5) and v['traps']==before['traps']-1)
            s=self.wild_wait(increased,'捕兽夹使用后的概率+5%与库存-1未同时确认，停止使用',seconds=10)
            values=capture_values(s)
            # The resource pair already proves the spend, even if a later
            # name/rarity read fails. Persist it before checking identity.
            entry.update(traps_used=entry['traps_used']+1,stock_after=values['traps'],probability=values['probability'])
            self.note(f'野生{label}-{name}：成功率{values["probability"]}%，捕兽夹剩余{values["traps"]}个');self.checkpoint()
            s,title_roi=self.confirm_wild_identity(s,entry,'使用捕兽夹后',title_roi=title_roi)
            confirmed=capture_values(s)
            if confirmed is None or any(confirmed[key]!=values[key] for key in ('probability','traps','cost')):
                raise TaskBlocked('核对怪兽期间概率、库存或费用改变，未继续消耗')
        # Re-read both identity and probability immediately before the final input.
        s=self.observe()
        s,title_roi=self.confirm_wild_identity(s,entry,'捕捉前',title_roi=title_roi)
        final=capture_values(s)
        if (final is None or final['probability'] is None or
                final['probability']<target or final['traps']!=values['traps'] or final['cost']!=20 or
                not self.b.match_template(s,'wild-stamina.png',(915,595,65,65),.90)):
            raise TaskBlocked('捕捉前概率、库存、费用或怪兽信息发生变化，未捕捉')
        entry.update(status='capturing',probability=final['probability'],message=f'{label}怪兽-{name}：已发起{final["probability"]}%捕捉，结果待确认')
        self.b.save_screen(s,self.report['folder']/'wild-before-capture.png');self.checkpoint()
        self.b.click_at(s,(836,632),list(CAPTURE_ANCHORS),'按所选成功率捕捉野生怪兽（20体力）')
        result=self.wild_wait(lambda q:self.wild_outcome(q,name) is not None,'捕捉结果尚未识别，请查看保留截图',seconds=35)
        outcome=wild_result(result,name)
        self.b.save_screen(result,self.report['folder']/'wild-result.png')
        message={'captured':f'成功捕捉{label}怪兽-{name}',
                 'escaped':f'{label}怪兽-{name}：捕捉失败，成功率{final["probability"]}%，已使用{entry["traps_used"]}个捕兽夹',
                 'fragments':f'{label}怪兽-{name}：获得怪兽碎片，未确认捕获完整怪兽'}[outcome]
        self.wild_notice(entry,outcome,message,stamina_spent=20,result_text=result.text)
