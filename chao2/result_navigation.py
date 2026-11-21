"""Leave confirmed settlements without treating an exit animation as fatal."""
import time
from .policy import PageChanged,TaskBlocked,SafetyStop,UserStopped,IsolatedTaskError,BattleReturned


def result_shell(s):
    # The ornate failure title and the exit label can both disappear from OCR
    # during the closing animation. Its fixed improvement links remain visible.
    from .workflows import is_failure
    if is_failure(s):return 'failed'
    from .daily_challenges import defeat_action_count
    links=defeat_action_count(s)
    if links>=3 or (s.find('通过下列方式提高战力') and links>=2):return 'failed'
    if s.find('胜利',(0,160,540,390)):return 'victory'
    if s.has('本场击破数','本场金币奖励'):return 'rampage'
    if s.find('^起源殿积分$') and s.find('怪兽培育|阵容调整'):return 'failed'
    if s.find('^获得奖励$') and s.find('重复挑战|再虐一遍|退出'):return 'reward'
    if s.find('^退出$') and s.find('总伤害|本次伤害|挑战结束|战斗结束'):return 'score'
    if s.find('^退出$'):return 'exit'
    return None


def exit_destination(s):
    from .workflows import is_world,is_tasks,is_start_screen
    from .activities import enemy_formation,is_copy_list
    from .anomalies import is_event_panel
    from .world_events import is_map_choice,is_ambush
    from .reward_collection import is_map_story
    from .tour import tour_progress,tour_story
    from .trigger_events import triggered_event
    from .triad import is_triad_lobby
    from .plane_gate import plane_gate_window
    if plane_gate_window(s):return 'plane_gate'
    if is_world(s):return 'world'
    if is_tasks(s):return 'tasks'
    if is_start_screen(s):return 'start'
    if is_triad_lobby(s):return 'triad_lobby'
    if is_copy_list(s) or is_event_panel(s):return 'events'
    if is_map_choice(s):return 'map_choice'
    if is_ambush(s):return 'ambush'
    if is_map_story(s):return 'story'
    if tour_progress(s) is not None:return 'tour_map'
    if tour_story(s) is not None:return 'tour_story'
    event=triggered_event(s)
    if event:return 'event:'+event
    if enemy_formation(s) and s.find('^排阵$'):return 'detail'
    if s.has('^进击巨物$','^开始挑战$','^我的排名$'):return 'giant_menu'
    if s.find('^世界$',(1150,620,130,100)) and s.find('永生|浮空|黑暗|斗技|领地'):return 'territory'
    header=s.find('^浮空巨塔$|^永生之茧$|^斗技场(?:挑战)?$|^起源殿$|^[凿幽]星裂痕$|^黑暗森林$|^丰野间$|^进击巨物$|^[谜迷]之巢穴$|^部落$',(80,0,450,75))
    if header:return 'menu:'+header.text
    if s.has('^获得奖励$','点击空白位置关闭'):return 'reward'
    return None


class ResultNavigation:
    def returned_quota_spent(self,task,before,after,outcome):
        stalls=getattr(self,'_returned_quota_stalls',{});self._returned_quota_stalls=stalls
        key=self.report_key(task)
        if outcome!='unobserved':
            if after==before-1:stalls[key]=0;return 1
            return None
        if after is None or not 0<=after<=before:return None
        stalls[key]=stalls.get(key,0)+1 if after==before else 0
        if stalls[key]>=3:raise IsolatedTaskError('连续3次返回玩法页面但次数未消耗，本项结束并继续后续任务')
        return before-after

    def battle_return_page(self,s,state,*,ready=False):
        """Two stable navigable frames replace a vanished settlement, never a win."""
        from .battle_takeover import takeover_phase
        state.setdefault('started',time.monotonic())
        page=exit_destination(s) if not result_shell(s) and not takeover_phase(s) else None
        if page in ('reward','start'):page=None
        state['reads']=state.get('reads',0)+1 if page and page==state.get('page') else int(bool(page))
        state['page']=page
        if state['reads']<2 or not (ready or time.monotonic()-state['started']>=4):return None
        row={'task':self.active_task,'instance_id':self.report_key(self.active_task),
             'destination':page,'outcome':'unobserved','attempt':self.task_counts.get(self.active_task,0)}
        self.report.setdefault('battle_returns',[]).append(row)
        self.note('战斗已返回可识别页面，结算可能已被手动退出；重新核对剩余资源后继续，不推断胜败')
        self.checkpoint();return page

    def raise_battle_returned(self,s,page,before=None):
        task=self.active_task
        start=next((r for r in reversed(self.report.get('challenge_starts',[])) if r.get('task')==task),{})
        target=start.get('target')
        signature=(page,before,str(target))
        raise BattleReturned(s,page,signature,task,target)

    def leave_battle_result(self,s):
        self.b.check_stop()
        source=result_shell(s)
        rows=self.report.setdefault('result_exits',[])
        row={'task':self.active_task,'source':source,'clicks':0,'status':'pending'}
        rows.append(row);stable=0;changed=0;destination=None;waiting=False

        def click(q):
            try:self.b.click_text(q,'^退出$')
            except (PageChanged,TaskBlocked) as error:
                row['preclick_rechecks']=row.get('preclick_rechecks',0)+1
                if getattr(error,'screen',None) is not None:
                    self.last_screen=error.screen
                    if self.report.get('folder'):
                        path=self.report['folder']/f'result-exit-{len(rows)}-recheck-{row["preclick_rechecks"]}.png'
                        self.b.save_screen(error.screen,path)
                        row['last_recheck_screenshot']=str(path)
                self.note('退出按钮在点击前已变化，重新观察当前页面，不直接停止')
                self.checkpoint();return
            row['clicks']+=1;self.checkpoint()

        try:
            if time.monotonic()-s.when<=12 and s.find('^退出$'):click(s)
            for _ in range(36):
                q=self.observe();self.b.guard(q);kind=result_shell(q)
                if source is None and kind and q.find('^退出$'):
                    source=kind;row['source']=kind;click(q);continue
                current=exit_destination(q) if not kind else None
                if current or kind!=source:
                    stable=0
                    # A blank loading frame is not proof that exit completed.
                    current=current or (('result:'+kind) if kind else None)
                    changed=changed+1 if current and current==destination else int(bool(current))
                    destination=current
                    if changed>=2:
                        row.update(status='left',destination=current)
                        self.checkpoint();return q
                    if not waiting:
                        self.note('结算页已变化，等待退出完成，不重复点击');waiting=True
                else:
                    changed=0;destination=None;stable=stable+1 if q.find('^退出$') else 0
                    if stable>=3:
                        fresh=self.observe();self.b.guard(fresh)
                        if result_shell(fresh)!=source or not fresh.find('^退出$'):
                            stable=0;self.b.sleep(.5);continue
                        if row['clicks']>=8:
                            raise TaskBlocked('退出结算仍停留在原页面，已重试7次；保留现场')
                        self.navigation_retry('仍在原结算页，重新点击免费退出',max(1,row['clicks']),fresh)
                        click(fresh);stable=0
                self.b.sleep(.5)
            raise IsolatedTaskError('结算后当前页面仍未确认，停止本项并重新定位后续任务')
        except (TaskBlocked,SafetyStop,UserStopped) as error:
            row.update(status='stopped' if isinstance(error,UserStopped) else 'blocked',reason=str(error))
            self.checkpoint();raise
