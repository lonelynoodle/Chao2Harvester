"""Finish an already running encounter before navigating the daily queue.

Battle HUDs are shared by many activities. A timer and auto button establish
combat, never the activity's identity. No new challenge or paid action is sent.
"""
import re
import time
from datetime import datetime

from .daily_challenges import rank_change_notice,rampage_buff
from .policy import SafetyStop,TaskBlocked,UserStopped,PageChanged
from .result_navigation import result_shell,exit_destination
from .triad import triad_hud_round,triad_result
from .tribe_totems import totem_score

NEXT_ROUND=r'^下一(?:阵|局|场|回合)$'
BATTLE_CONTROLS=r'^自动$|^手动$|^[Xx][12468]$|^结算$|^暂停$|^撤退$'


def existing_result(s):
    if not s.find('^退出$',(900,500,380,220)):return None
    from .rift import is_rift_victory
    if is_rift_victory(s):return 'victory'
    outcome=triad_result(s)
    if outcome:return outcome
    shell=result_shell(s)
    return shell if shell in ('failed','victory','rampage','reward','score') else None


def takeover_phase(s):
    # Overlays must win over the live HUD still visible behind them.
    if rank_change_notice(s):return 'rank'
    if existing_result(s):return 'result'
    if totem_score(s) or s.has('点击空白位置继续','防御值'):return 'tribe_score'
    if s.find('请选择一个暴走增益'):return 'rampage_buff'
    if s.find('^正在匹配$|^匹配中$|^正在寻找对手$',(300,80,700,400)) and s.find('^取消匹配$',(300,420,700,240)):
        return 'matching'
    if (s.find('^暂停$',(400,100,480,360)) and
            s.find('^继续战斗$|^继续游戏$|^继续$',(300,250,680,400))):return 'paused'
    if s.find('^退出$|^排阵$|^挑战$|^前往挑战$|^开始挑战$|^匹配$|^重开$|^进入游戏$'):
        return None
    if s.find(NEXT_ROUND,(700,440,580,250)):return 'round'
    controls=s.find(BATTLE_CONTROLS,(0,540,300,160))
    if controls and (s.find(r'^\d{1,2}:\d{2}$',(450,0,380,110)) or triad_hud_round(s)):
        return 'battle'
    return None


def existing_battle_label(s):
    # Only an explicit stage label supplies an activity name. Shared 5v5 HUDs
    # cannot distinguish origin, arena and the final triad round.
    label=s.find(r'浮空巨塔|塔中秘庭|三阵入局|起源殿|斗技场|进击巨物|暴走旷野|天启|部落冒险|裂痕关卡',
                 (750,0,530,80))
    return label.text if label else '已有战斗'


class BattleTakeover:
    def finish_existing_battle(self,s,*,timeout_seconds=None,label=None):
        phase=takeover_phase(s)
        if phase is None:raise TaskBlocked('已有战斗状态未确认，未操作挑战按钮')
        rows=self.report.setdefault('battle_takeovers',[])
        number=len(rows)+1
        row={'started':datetime.now().astimezone().isoformat(),'label':label or existing_battle_label(s),
             'initial_phase':phase,'status':'waiting','counted_as_task_attempt':False,
             'resource_spend':None,'continuations':0}
        rows.append(row)
        self.b.save_screen(s,self.report['folder']/f'battle-takeover-{number}-initial.png')
        self.emit('phase','等待已有战斗结算')
        self.note('检测到'+row['label']+'，先等待当前场次结算，再继续所选任务')
        self.checkpoint()
        # Rampage and multi-round fights can outlast the normal 240s timeout.
        timeout=max(720,int(self.b.settings.get('battle_timeout_seconds',240))) if timeout_seconds is None else timeout_seconds
        until=time.monotonic()+timeout
        feedback=time.monotonic();network_retries=0
        try:
            while time.monotonic()<until:
                self.b.guard(s)
                if self.retry_battle_network(s,network_retries):
                    network_retries+=1;s=self.observe();continue
                phase=takeover_phase(s)
                if phase=='result':
                    row['result']=existing_result(s)
                    self.b.save_screen(s,self.report['folder']/f'battle-takeover-{number}-result.png')
                    destination=self.exit_result(s)
                    row.update(status='settled',finished=datetime.now().astimezone().isoformat())
                    self.note('已有场次结算已退出，继续所选任务；本场单独记录，不计入新任务挑战次数')
                    self.emit('phase','执行中')
                    self.checkpoint();return destination
                if phase=='rank':
                    s=self.dismiss_rank_change(s);continue
                if phase=='tribe_score':
                    anchors=['点击空白位置继续','我方状态','比拼方式'] if totem_score(s) else ['点击空白位置继续','防御值']
                    def advance(q):
                        if takeover_phase(q)=='tribe_score' and q.has(*anchors):
                            self.b.click_at(q,(930,594),anchors,'查看已有部落战斗的结算奖励')
                    advance(s)
                    s=self.wait_for_screen(lambda q:takeover_phase(q)!='tribe_score' and
                        (existing_result(q) is not None or exit_destination(q) is not None),
                        '已有部落战斗成绩进入奖励页',timeout=4,retry_navigation=advance)
                    continue
                if phase=='rampage_buff':
                    button,description=rampage_buff(s,self.options['nest']['buff_priority'])
                    source=s.region_text((0,150,1280,470))
                    def choose(q):
                        if takeover_phase(q)=='rampage_buff' and q.region_text((0,150,1280,470))==source:
                            button,description=rampage_buff(q,self.options['nest']['buff_priority'])
                            self.b.click_at(q,button.center,['请选择一个暴走增益','^点击选择$'],
                                            '接续已有暴走旷野，选择增益：'+description)
                    choose(s)
                    self.note('已有暴走旷野已选择增益，继续等待本场结束')
                    s=self.wait_for_screen(lambda q:(takeover_phase(q) not in (None,'rampage_buff') or
                        exit_destination(q) is not None or (takeover_phase(q)=='rampage_buff' and
                        q.region_text((0,150,1280,470))!=source)),
                        '已有暴走旷野增益选择完成',timeout=4,retry_navigation=choose)
                    continue
                if phase in ('round','paused'):
                    pattern=NEXT_ROUND if phase=='round' else '^继续战斗$|^继续游戏$|^继续$'
                    roi=(700,440,580,250) if phase=='round' else (300,250,680,400)
                    button=s.find(pattern,roi)
                    def resume(q):
                        current=q.find(pattern,roi)
                        if takeover_phase(q)==phase and current:
                            try:self.b.click_at(q,current.center,['^'+re.escape(current.text)+'$'],
                                               '继续已有战斗的当前场次')
                            except PageChanged:pass
                    resume(s);row['continuations']+=1
                    s=self.wait_for_screen(lambda q:takeover_phase(q) not in (None,phase),
                        '已有战斗继续',timeout=4,retry_navigation=resume)
                    continue
                if phase is None and exit_destination(s):
                    # The user/client may already have closed the result during
                    # loading. Navigation may continue, but victory is unknown.
                    row.update(status='returned_without_result',finished=datetime.now().astimezone().isoformat())
                    self.note('已有战斗已返回可导航页面，未观察到最终结算；继续所选任务，不计胜场')
                    self.emit('phase','执行中')
                    self.checkpoint();return s
                if time.monotonic()-feedback>=15:
                    self.note('已有场次'+('正在匹配' if phase=='matching' else '进行中或结算加载中')+'，等待结束后继续任务…')
                    feedback=time.monotonic()
                self.b.sleep(1);s=self.observe()
            raise TaskBlocked('已有战斗等待结算超时，保留现场；未撤退、未重复开战')
        except (SafetyStop,TaskBlocked,UserStopped) as error:
            row.update(status='stopped' if isinstance(error,UserStopped) else 'blocked',reason=str(error))
            self.checkpoint();raise
