"""Free attack/defence wall selection. Ignore is a strict no-navigation path."""
import re
from datetime import datetime
from functools import lru_cache
import cv2
from .backend import ROOT,Screen,Word
from .policy import TaskBlocked,IsolatedTaskError,PageChanged
from .wall_settings import validate_wall_mode

WALL_ICON_ROI=(45,450,65,70)

def wall_layout(s):return 'nest' if s.find('^[谜迷]之巢穴$',(80,0,230,65)) else 'formation'
def wall_icon_roi(s):return (45,530,50,55) if wall_layout(s)=='nest' else WALL_ICON_ROI


def formation_header(s):
    if s.find('^配置$|^复制此配置$|^取消$|^确定$|^获得奖励$'):return None
    return s.find('^排阵$|^部队$|^[谜迷]之巢穴$',(80,0,230,65))


@lru_cache(maxsize=4)
def wall_icon(mode,layout='formation'):
    return cv2.imread(str(ROOT/'resource/image'/('battle-wall-'+('nest-' if layout=='nest' else '')+mode+'.png')))


def formation_wall_mode(s):
    if not formation_header(s):return None
    x,y,w,h=wall_icon_roi(s);crop=s.image[y:y+h,x:x+w];scores={}
    for mode in ('attack','defense'):
        template=wall_icon(mode,wall_layout(s))
        if template is None or crop.shape[0]<template.shape[0] or crop.shape[1]<template.shape[1]:return None
        scores[mode]=float(cv2.minMaxLoc(cv2.matchTemplate(crop,template,cv2.TM_CCOEFF_NORMED))[1])
    mode=max(scores,key=scores.get)
    return mode if scores[mode]>=.90 and scores[mode]-scores['defense' if mode=='attack' else 'attack']>=.08 else None


def wall_page_mode(s):
    if not s.has('^战墙$','^切换$','^加固$','^效果总览$') or s.find('^取消$|^确定$|^购买$'):return None
    crop=s.image[100:136,20:150].astype('float32');b,g,r=(crop[:,:,i] for i in range(3))
    attack=((r>70)&(r>g*1.15)&(r>b*1.2)).mean()
    defense=((b>70)&(b>r*1.2)&(b>g*.95)).mean()
    if attack>.15 and attack-defense>.10:return 'attack'
    if defense>.15 and defense-attack>.10:return 'defense'
    return None


class BattleWall:
    def wall_runtime(self):
        # Reports are shared with nested players, but a new run gets a fresh
        # report. Never persist this cache in account state or user settings.
        return self.report.setdefault('battle_wall_runtime',{
            'mode':None,'confirmed':False,'checks':0,'cache_hits':0,'switch_attempts':0})

    def remember_wall(self,mode,source):
        state=self.wall_runtime();state.pop('invalidation_reason',None)
        state.update(mode=mode,confirmed=True,source=source,
            confirmed_by=self.active_task,confirmed_at=datetime.now().astimezone().isoformat())

    def forget_wall(self,reason):
        self.wall_runtime().update(mode=None,confirmed=False,invalidation_reason=reason)

    def desired_wall(self,task):
        options=self.options.get(task,{})
        if task in ('tour','abyss') and hasattr(self,'tool_options'):options=self.tool_options
        return validate_wall_mode(options.get('wall_mode','attack' if task=='nest' else 'ignore'))

    def set_wall_page(self,s,mode,row):
        for attempt in range(2):
            s=self.observe();self.b.guard(s);current=wall_page_mode(s)
            if current==mode:
                self.remember_wall(mode,'wall_page');return s
            if current is None:
                self.forget_wall('战墙当前类型未确认')
                raise IsolatedTaskError('战墙当前类型未确认，未切换或开战')
            switch=s.find('^切换$',(0,80,180,75))
            if switch is None:raise IsolatedTaskError('战墙切换按钮未确认，未点击加固或武装')
            marker=Word('已确认'+current+'战墙',[20,100,130,36],.99)
            verified=Screen(s.image,[*s.words,marker],s.when)
            self.forget_wall('战墙切换已请求，等待核实')
            self.wall_runtime()['switch_attempts']+=1
            self.b.click_at(verified,switch.center,['^战墙$','^切换$','^'+marker.text+'$'],'切换到'+('进攻型' if mode=='attack' else '防御型')+'战墙')
            row['switches']+=1
            for _ in range(4):
                s=self.observe();self.b.guard(s)
                if wall_page_mode(s)==mode:
                    self.remember_wall(mode,'wall_page');return s
                self.b.sleep(.5)
        self.forget_wall('战墙切换未核实')
        raise IsolatedTaskError('战墙切换后未确认目标类型，本项跳过，未开战')

    def wall_in_formation(self,s,mode,row):
        current=formation_wall_mode(s)
        if current==mode:
            row['already_selected']=True;self.remember_wall(mode,'formation');return s
        header=formation_header(s)
        if current is None or header is None:raise TaskBlocked('队伍页战墙标记未识别')
        marker=Word('已确认队伍战墙',list(wall_icon_roi(s)),.99)
        checked=Screen(s.image,[*s.words,marker],s.when)
        point=(24,534) if wall_layout(s)=='nest' else (26,387)
        self.b.click_at(checked,point,['^'+re.escape(header.text)+'$','^已确认队伍战墙$'],'从队伍页打开战墙配置')
        s=self.wait_for_screen(lambda q:wall_page_mode(q) is not None,'队伍页战墙配置',timeout=3)
        s=self.set_wall_page(s,mode,row)
        self.b.click_at(s,(43,28),['^战墙$','^切换$'],'返回队伍，复核战墙类型')
        return self.wait_for_screen(lambda q:formation_wall_mode(q)==mode,'队伍战墙类型确认',timeout=3)

    def prepare_battle_wall(self,task,s):
        mode=self.desired_wall(task)
        if mode=='ignore':return s
        runtime=self.wall_runtime()
        if runtime['confirmed'] and runtime['mode']==mode:
            self.b.check_stop();runtime['cache_hits']+=1
            return s
        runtime['checks']+=1
        from .challenge_start import challenge_identity,is_challenge_ready
        identity=challenge_identity(s,task) if is_challenge_ready(s) else None
        row={'task':task,'instance_id':self.report_key(task),'requested':mode,'switches':0,'status':'checking','route':'formation'}
        self.report.setdefault('battle_wall_checks',[]).append(row)
        on_formation=formation_header(s) is not None and formation_wall_mode(s) is not None
        try:
            try:
                if not on_formation:
                    q=self.open_detail_formation(s)
                else:q=s
                q=self.wall_in_formation(q,mode,row)
                if not on_formation:
                    header=formation_header(q)
                    self.b.click_at(q,(43,28),['^'+re.escape(header.text)+'$'],'战墙确认后返回原挑战页面')
                    q=self.wait_for_screen(lambda p:self.wall_source_ready(p,task,identity),'战墙设置后原玩法页面',timeout=3)
            except (TaskBlocked,PageChanged) as error:
                if isinstance(error,IsolatedTaskError):raise
                row.update(route='territory',fallback_reason=str(error));self.note('队伍页战墙入口未确认，改从领地兜底')
                q=self.wall_territory_fallback(task,identity,mode,row)
            row.update(status='verified',actual=mode);self.remember_wall(mode,row['route']);self.checkpoint()
            return q
        except (TaskBlocked,PageChanged) as error:
            row.update(status='blocked',reason=str(error));self.checkpoint()
            raise IsolatedTaskError(str(error)) from error

    def wall_source_ready(self,s,task,identity):
        from .challenge_start import challenge_identity,is_challenge_ready
        if task=='origin':return s.has('^起源殿$','^匹配$','剩余免费挑战次数')
        if task=='nest':return s.has('^[谜迷]之巢穴$','^暴走旷野$','^挑战$')
        return is_challenge_ready(s) and (identity is None or challenge_identity(s,task)==identity)

    def wall_territory_fallback(self,task,identity,mode,row):
        s=self.territory();self.b.click_text(s,'^战墙$')
        s=self.wait_for_screen(lambda q:wall_page_mode(q) is not None,'领地战墙配置',timeout=3)
        s=self.set_wall_page(s,mode,row)
        self.b.click_at(s,(43,28),['^战墙$','^切换$'],'战墙切换后返回领地')
        self.home();self._overview_ready=None
        if task=='nest':
            q=self.rampage_ready(self.enter_building('谜之巢穴','^暴走旷野$'))
            if formation_wall_mode(q)!=mode:raise IsolatedTaskError('领地兜底后副本战墙类型未确认，未开战')
            return q
        if task=='origin':return self.enter_building('起源殿','^匹配$','剩余免费挑战次数')
        if task=='triad':return self.triad_lobby()
        q=self.overview_entry(task,reason='领地战墙设置完成，重新定位原任务')
        if not self.wall_source_ready(q,task,identity):raise IsolatedTaskError('战墙兜底后原关卡未确认，未挑战其他目标')
        return q
