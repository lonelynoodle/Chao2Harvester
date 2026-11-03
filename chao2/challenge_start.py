"""Confirm battle entry; replay a launch only on the same, uncharged detail."""
import re
import time

from .policy import TaskBlocked,SafetyStop,EncounterInterrupted,UserStopped,ChallengeLocked


CHALLENGE_BUTTON=r'^挑战$|^前往挑战$'

def challenge_unlock_level(s):
    notice=s.find(r'^探索者等级\s*\d+\s*(?:解锁|开启)$',(300,300,680,120))
    return int(re.search(r'\d+',notice.text)[0]) if notice else None


def challenge_identity(s,task):
    from .activities import main_identity,encounter_identity,tribe_identity
    if task=='main':return main_identity(s)
    if task=='tribe':return tribe_identity(s)
    if task in ('copies','hunt'):return encounter_identity(s) or None
    if task=='tower':
        title=s.find(r'(?:浮空巨塔|塔中秘庭)\s*\d+$',(150,75,560,90))
        return re.sub(r'\s','',title.text) if title else None
    if task=='nest' and s.has('^[谜迷]之巢穴$','^暴走旷野$'):
        return '暴走旷野'
    # Other ready pages have stable headings in this band. Exclude formation
    # markers and low-confidence fragments, not the animated monster models.
    words=sorted((w for w in s.words if w.score>=.8 and
                  25<=w.center[0]<740 and 75<=w.center[1]<165 and
                  re.search(r'[\u4e00-\u9fff]',w.text) and
                  not re.search('敌方阵容|危险|通关录像',w.text)),key=lambda w:(w.box[1],w.box[0]))
    if task=='arena':
        words=sorted((w for w in s.words if w.score>=.8 and
                      60<=w.center[0]<1200 and 75<=w.center[1]<360),key=lambda w:(w.box[1],w.box[0]))
    return tuple(w.text for w in words) or None


def is_challenge_ready(s,pattern=CHALLENGE_BUTTON):
    return bool(s.find(pattern) and (s.find('^排阵$') or
                s.has('^[谜迷]之巢穴$','^暴走旷野$','最高击破数')))


def battle_entry_state(s):
    """A visible source button takes precedence over battle text behind it."""
    from .workflows import is_failure
    from .rift import is_rift_victory
    from .tribe_totems import totem_score
    if s.find(CHALLENGE_BUTTON):return None
    if is_failure(s):return '结算'
    if s.has('^退出$','胜利','获得奖励') or is_rift_victory(s):return '结算'
    if s.has('^退出$','获得奖励','重复挑战'):return '结算'
    if s.has('点击空白位置继续','防御值'):return '结算'
    if totem_score(s):return '结算'
    if s.find('请选择一个暴走增益') or s.has('^退出$','本场击破数','本场金币奖励'):return '战斗'
    if s.find('^退出$') and s.find('总伤害|本次伤害|挑战结束|战斗结束'):return '结算'
    if s.find(r'^暂停$|^自动$|^手动$|^X2$|^x2$|^撤退$'):return '战斗'
    if s.find(r'^\d{1,2}:\d{2}$',(490,0,300,100)):return '战斗'
    return None


class ChallengeStartRecovery:
    def check_tower_level_gate(self,s,target):
        level=challenge_unlock_level(s)
        if level is None:return
        path=self.report['folder']/f'challenge-locked-{len(self.report.setdefault("challenge_locks",[]))+1}.png'
        self.b.save_screen(s,path)
        self.report['challenge_locks'].append({'task':'tower','target':target,
            'required_level':level,'screenshot':str(path)})
        self.checkpoint()
        raise ChallengeLocked(level,s)

    def observe_battle(self):
        pending=getattr(self,'_challenge_entry',None);self._challenge_entry=None
        if pending and pending[0]==self.active_task and time.monotonic()-pending[1].when<10:
            return pending[1]
        return self.observe()

    def start_challenge(self,task,detail,resource,verify=None):
        self._challenge_entry=None;self.active_task=task
        self.b.guard(detail)
        if task in self.options:self.check_budget(task)
        else:self.b.check_stop()
        if not is_challenge_ready(detail):raise TaskBlocked('开战前挑战详情未确认')
        identity=challenge_identity(detail,task)
        before=self.b.read_resource_ratio(detail,(1140,0,140,65))
        free='免费' in resource
        row={'task':task,'instance_id':getattr(self,'active_task_id',None),
             'target':identity,'status':'pending','clicks':0,'resource_before':before}
        self.report.setdefault('challenge_starts',[]).append(row)
        stable=0;charged=False;waiting=False;unreadable=False

        def confirmed(q):
            phase=battle_entry_state(q)
            if not phase:return False
            self._challenge_entry=(task,q)
            row.update(status='started',phase=phase)
            self.note('已确认进入'+phase)
            self.checkpoint()
            return True

        def same_source(q):
            return bool(identity and is_challenge_ready(q) and challenge_identity(q,task)==identity)

        def unchanged_balance(q):
            after=self.b.read_resource_ratio(q,(1140,0,140,65))
            row['resource_last_observed']=after
            return after==before if before is not None else free

        def click(q):
            try:
                # The level-70 tower toast disappears during the usual 2s
                # input delay. Observe promptly; later frames still confirm
                # battle entry and resources before any repeated input.
                if task=='tower':self.b.click_text(q,CHALLENGE_BUTTON,settle_delay=.15)
                else:self.b.click_text(q,CHALLENGE_BUTTON)
            except SafetyStop as error:
                if not str(error).startswith('点击前页面改变：'):raise
                row['preclick_rechecks']=row.get('preclick_rechecks',0)+1
                self.note('点击前页面已变化，重新观察战斗状态，暂不追加输入')
                return
            row['clicks']+=1

        def observe_path():
            from .world_events import is_map_choice
            q=self.observe();self.b.guard(q);self.resolve_path_event(q)
            if task=='hunt' and is_map_choice(q):
                # Pathing can end at a node shared with a normal world stage.
                # Choose only the unique hunt row, then re-check the original
                # identity, timer, cost and balance before any challenge retry.
                q=self.open_hunt_choice(q);self.b.guard(q);self.resolve_path_event(q)
            return q

        try:
            if task=='tower':self.check_tower_level_gate(detail,identity)
            click(detail);self.checkpoint()
            for _ in range(48):
                s=observe_path()
                if task=='tower':self.check_tower_level_gate(s,identity)
                if confirmed(s):return s
                same=same_source(s)
                if same:
                    after=self.b.read_resource_ratio(s,(1140,0,140,65))
                    row['resource_last_observed']=after
                    if before and after and after[0]<before[0]:
                        if not charged:self.note('挑战资源已扣除，等待战斗画面，不再重复点击')
                        charged=True
                    stable=stable+1 if not charged and unchanged_balance(s) else 0
                    if stable==0 and not charged and not unreadable:
                        self.note('仍在关卡详情，继续核对目标与资源，暂不重复点击');unreadable=True
                else:
                    stable=0
                    if not waiting:
                        self.note('挑战页面已变化，等待战斗或结算加载，不重复点击');waiting=True
                if stable>=3:
                    # A transition can arrive during the last observation. Take
                    # another frame before replaying, including its resource check.
                    fresh=observe_path()
                    if task=='tower':self.check_tower_level_gate(fresh,identity)
                    if confirmed(fresh):return fresh
                    if not same_source(fresh) or not unchanged_balance(fresh):
                        stable=0;self.b.sleep(.5);continue
                    if row['clicks']>=4:
                        raise TaskBlocked('挑战按钮点击后仍停留在原关卡，已重试3次，未确认开战，未计入挑战次数')
                    if task in self.options:self.check_budget(task)
                    else:self.b.check_stop()
                    if verify:verify(fresh)
                    if task in ('copies','hunt','main','tower','cocoon','tribe'):
                        self.verify_instant_setting(task,fresh)
                    self.navigation_retry('挑战按钮未推进，确认原关卡与资源未变后重新点击',row['clicks'],fresh)
                    click(fresh);stable=0
                    self.checkpoint()
                self.b.sleep(.5)
            reason=('挑战资源已扣除，但战斗画面尚未确认，未再次点击，保留现场' if charged else
                    '点击挑战后尚未确认战斗；当前页面、目标或资源无法确认，未追加点击，保留现场')
            raise TaskBlocked(reason)
        except (TaskBlocked,SafetyStop,EncounterInterrupted,UserStopped) as error:
            self._challenge_entry=None
            if task=='main' and isinstance(error,EncounterInterrupted):
                self._main_interrupted_target=identity
            row.update(status='interrupted' if isinstance(error,EncounterInterrupted) else
                       'stopped' if isinstance(error,UserStopped) else
                       'locked' if isinstance(error,ChallengeLocked) else 'blocked',reason=str(error))
            if isinstance(error,ChallengeLocked):row['required_level']=error.level
            self.checkpoint()
            raise
