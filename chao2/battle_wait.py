"""Wait for settlements and operate verified controls on the live battle HUD."""
import time
from .control_retry import retry_point
from .policy import IsolatedTaskError


DEITY_MODE = r'^自动$|^手动$'
DEITY_MODE_ROI = (75, 575, 75, 75)
BATTLE_TIMER = r'^\d{1,2}:\d{2}$'
DEITY_TASK_LABELS = {'main': '主线关卡', 'nest': '谜之巢穴'}


class BattleWait:
    def battle_frames(self,seconds,label,*,first=None,observe=None,clock=None):
        from .battle_takeover import takeover_phase
        clock=clock or time.monotonic
        observe=observe or self.observe_battle
        deadline=clock()+seconds
        while True:
            self.b.check_stop()
            s=first if first is not None else observe();first=None
            # Let the caller process a freshly observed result even when the
            # old timeout expired during its preceding screenshot or sleep.
            yield s
            if clock()<deadline:continue
            phase=takeover_phase(s)
            if phase in ('battle','paused','round','rampage_buff','tribe_score','result','rank'):
                self.report.setdefault('battle_wait_extensions',[]).append({
                    'task':self.active_task,'label':label,'phase':phase,'seconds':seconds})
                self.note(label+'等待时间已到，当前仍是战斗或结算流程，继续等待本场结束')
                self.checkpoint();deadline=clock()+seconds
                continue
            raise IsolatedTaskError(label+'等待超时，当前未确认仍在战斗，回退后继续下一项任务')

    def enable_battle_auto_deity(self, task, s, state):
        """Verify the HUD before toggling its manual release control."""
        if not self.options[task]['auto_deity'] or state.get('confirmed'):
            return False
        self.b.check_stop()
        from .battle_takeover import takeover_phase
        from .dungeon_labels import OVERLAY

        if s.find(OVERLAY) or not s.find(BATTLE_TIMER, (450, 0, 380, 110)):
            return False
        mode = s.find(DEITY_MODE, DEITY_MODE_ROI)
        if mode is None and self.b.tasker is not None:
            from .backend import Screen
            s = Screen(s.image, list(s.words), s.when)
            self.b.confirm_label(s, DEITY_MODE, DEITY_MODE_ROI, scale=3, threshold=.85)
            mode = s.find(DEITY_MODE, DEITY_MODE_ROI)
        if mode is None or takeover_phase(s) != 'battle':
            return False
        label = DEITY_TASK_LABELS[task]
        if mode.text == '自动':
            state.update(confirmed=True, status='confirmed')
            self.note(label+'：已确认神灵自动释放')
            return False
        clicks = state.get('clicks', 0)
        if clicks >= 3:
            if state.get('status') != 'unconfirmed':
                state['status'] = 'unconfirmed'
                self.note(label+'：神灵自动释放切换尝试3次仍未确认，继续等待本场战斗结算')
            return False
        if time.monotonic()-state.get('last_click', -float('inf')) < 2:
            return False
        self.b.click_at(s, retry_point(mode, clicks), ['^手动$', BATTLE_TIMER], label+'：神灵释放切换为自动')
        state.update(clicks=clicks+1, last_click=time.monotonic(), status='switching')
        return True
