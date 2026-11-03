"""Cooling-down free summons, checked only at safe daily-task boundaries."""
import re
import time
from datetime import datetime, timedelta
from .backend import Screen, Word
from .policy import TaskBlocked, SafetyStop

FREE_SUMMON_SPEC={'key':'free_summon','name':'免费造唤','fields':[
    {'key':'enabled','label':'自动免费造唤','type':'bool','default':False},
]}


def free_summon_enabled(settings):
    value=settings.get('free_summon_enabled',False)
    if type(value) is not bool:raise ValueError('免费造唤必须是开关')
    return value


def cooldown_seconds(text):
    m=re.search(r'(?<!\d)(\d{1,3})[:：](\d{2})[:：](\d{2})(?!\d)',text)
    if not m or int(m[2])>=60 or int(m[3])>=60:return None
    return int(m[1])*3600+int(m[2])*60+int(m[3])


def overview_summon_state(s,title):
    roi=(530,title.center[1]-28,185,76)
    text=s.region_text(roi)
    seconds=cooldown_seconds(text)
    if seconds is not None:return {'available':0,'cooldown':seconds}
    number=s.find(r'^\d{1,2}$',roi)
    if number and number.score>=.9:return {'available':int(number.text),'cooldown':None}
    return None


def is_summon_page(s):
    return bool(s.find('^[造召]唤台$',(95,0,160,65)) and
                s.find('^卡池详情$',(1050,400,230,110)) and
                s.find('^[造召]唤十次$',(690,590,250,75)))


def summon_balance(s):
    # Three balances on the same observed summon layout: diamonds and both tickets.
    values=[]
    for roi in ((825,0,90,55),(975,0,75,55),(1110,0,75,55)):
        w=s.find(r'^\d+$',roi)
        if not w or w.score<.9:return None
        values.append(int(w.text))
    return values


def free_summon_button(s):
    if not is_summon_page(s):return None
    # A 00:00 timer alone never grants permission to press a paid button.
    if s.find('下次免费',(335,668,285,50)):return None
    free=s.find(r'^免费(?:[造召]唤(?:一次)?)?$|^[造召]唤一次免费$',(335,595,285,85))
    once=s.find('^[造召]唤一次$',(335,595,285,50))
    if not free or free.score<.95 or not (once or '唤' in free.text):return None
    if re.search(r'\d|钻石|许可|购买|消耗',s.region_text((350,640,250,38))):return None
    return (once or free)


class FreeSummon:
    def summon_page_ready(self,s):
        if not is_summon_page(s):return s
        words=list(s.words)
        # Actual full-screen OCR splits 造唤一次 and can miss a zero ticket balance.
        # Recheck original pixels instead of assuming a missing cost is free.
        for roi,pattern in (((340,600,265,75),r'^[造召]唤一次免费$'),
                            ((825,0,90,55),r'^\d+$'),((975,0,75,55),r'^\d+$'),((1110,0,75,55),r'^\d+$')):
            if s.find(pattern,roi):continue
            text=re.sub(r'\s','',self.b.read_text_crop(s,roi))
            if re.fullmatch(pattern,text):words.append(Word(text,list(roi),.99))
        return Screen(s.image,words,s.when)

    def maybe_free_summon(self,s,*,force=False):
        if not free_summon_enabled(self.b.settings) or getattr(self,'_checking_free_summon',False):return s
        if not force and time.monotonic()<getattr(self,'_summon_check_after',0):return s
        from .workflows import is_world
        if not is_world(s):return s
        self._checking_free_summon=True
        self._summon_check_after=time.monotonic()+300
        row={'status':'checking','summons':0,'message':'正在检查免费造唤'}
        self.report.setdefault('free_summons',[]).append(row)
        try:
            self.note('免费造唤：检查剩余冷却')
            found=self.find_overview_entry({'free_summon':'^免费造唤$'})
            if not found:raise TaskBlocked('玩法概览没有免费造唤入口')
            page,_,title=found
            self.b.save_screen(page,self.report['folder']/'free-summon-overview.png')
            state=overview_summon_state(page,title)
            if state is None:raise TaskBlocked('免费造唤次数或剩余冷却未读清')
            row.update(state)
            if state['available']<=0:
                delay=max(5,state['cooldown']) if state['cooldown'] is not None else 300
                self._summon_check_after=time.monotonic()+delay
                row['status']='cooldown'
                row['next_check_at']=(datetime.now().astimezone()+timedelta(seconds=delay)).isoformat(timespec='seconds')
                row['message']='免费造唤：尚在冷却，预计'+row['next_check_at']+'可再次检查' if state['cooldown'] is not None else '免费造唤：当前没有免费次数'
            else:
                self.b.click_at(page,(738,title.center[1]+30),['^玩法概览$','^每日挑战$'],'前往当前有免费次数的造唤台')
                page=self.summon_wait_page()
                page=self.summon_page_ready(page)
                # Independent fresh observation must still show a free single draw.
                if free_summon_button(page) is None:raise TaskBlocked('造唤台没有确认免费单次按钮，未使用召唤券或钻石')
                page=self.summon_page_ready(self.observe());self.b.guard(page)
                button=free_summon_button(page);balance=summon_balance(page)
                if button is None or balance is None:raise TaskBlocked('免费按钮或资源余额未确认，未召唤')
                row.update(status='requested',resources_before=balance)
                self.b.save_screen(page,self.report['folder']/'free-summon-before.png')
                self.checkpoint()
                self.b.click_at(page,button.center,['^[造召]唤台$',re.escape(button.text)],'免费造唤一次')
                page=self.finish_free_summon(row)
                after=summon_balance(page)
                row['resources_after']=after
                if after is None or after!=balance:
                    raise SafetyStop('免费造唤后资源未确认保持不变，已停止后续输入')
                seconds=cooldown_seconds(page.region_text((335,665,285,55)))
                if seconds is None or seconds<=0:raise SafetyStop('免费造唤结算后冷却未确认，不重复点击')
                row.update(status='done',summons=1,cooldown=seconds,message='免费造唤已完成1次，钻石及召唤券消耗0')
                # If more free pools exist, re-check them at the next task boundary.
                delay=0 if state['available']>1 else seconds
                self._summon_check_after=time.monotonic()+delay
            self.note(row['message']);self.checkpoint()
            return self.home()
        except TaskBlocked as e:
            if row['status']=='requested':
                row.update(status='unconfirmed',message=str(e));self.checkpoint()
                raise SafetyStop('免费造唤结果未确认，保留现场且不重复召唤：'+str(e)) from e
            row.update(status='blocked',message='免费造唤：'+str(e))
            self.note(row['message']);self.checkpoint()
            return self.home()
        finally:
            if row['status']=='requested':row.update(status='unconfirmed',message='免费造唤已发送，结果尚未确认')
            self._checking_free_summon=False

    def summon_wait_page(self):
        for _ in range(20):
            s=self.observe();self.b.guard(s)
            if is_summon_page(s):return s
            self.b.sleep(.5)
        raise TaskBlocked('免费造唤跳转后未进入造唤台')

    def finish_free_summon(self,row):
        # No generic confirm, another draw or ten-draw button is ever clicked.
        dismissed=False
        for _ in range(90):
            s=self.observe();self.b.guard(s)
            if is_summon_page(s):
                if cooldown_seconds(s.region_text((335,665,285,55))):return self.summon_page_ready(s)
            elif not dismissed and s.find('点击空白位置关闭|点击空白处关闭|点击屏幕继续') and s.find('获得|怪兽|碎片'):
                self.b.save_screen(s,self.report['folder']/'free-summon-result.png')
                self.b.click_at(s,(640,680),['点击空白位置关闭|点击空白处关闭|点击屏幕继续','获得|怪兽|碎片'],'关闭免费造唤奖励')
                dismissed=True
            self.b.sleep(.5)
        raise TaskBlocked('免费造唤动画或结算页面尚未确认')
