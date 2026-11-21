"""Abandon one failed task only after returning through observed controls."""
from .policy import dangerous_dialog


def task_cancel_button(s):
    from .network_recovery import network_retry_button,NETWORK_CANCEL_ROI
    if network_retry_button(s):return s.find('^取消$',NETWORK_CANCEL_ROI)
    if not dangerous_dialog(s.text):return None
    cancel=s.find('^取消$',(250,320,440,290))
    confirm=s.find('^确定$|^确认$|^购买$',(640,320,450,290))
    return cancel if cancel and confirm else None


class TaskRecovery:
    def recover_failed_task(self):
        # Returning must not trigger another capture, purchase, map event or
        # network request from the failed task.
        wild=getattr(self,'wild_daily_active',False)
        prior=getattr(self,'_recovering_task',False)
        self.wild_daily_active=False;self._recovering_task=True
        self._task_cancel_attempts=0
        self._overview_ready=None;self._challenge_entry=None
        try:return self.home()
        finally:self.wild_daily_active=wild;self._recovering_task=prior

    def cancel_failed_task_dialog(self,s):
        from .policy import IsolatedTaskError
        while (button:=task_cancel_button(s)) is not None:
            if self._task_cancel_attempts>=3:
                raise IsolatedTaskError('当前确认窗口连续3次取消仍未关闭，无法返回可识别页面')
            self._task_cancel_attempts+=1
            self.b.task_cancel_only=True
            try:
                self.b.click_at(s,button.center,['^取消$'],'取消未完成任务的确认窗口')
            finally:self.b.task_cancel_only=False
            s=self.b.observe()
        return s

    def optional_step(self,label,run):
        from .policy import UserStopped,SessionUnavailable
        try:return run()
        except (UserStopped,SessionUnavailable):raise
        except Exception as error:
            self.report.setdefault('optional_failures',[]).append({'label':label,'reason':str(error)})
            self.note(label+'未完成：'+str(error)+'；回退后继续后续任务')
            self.checkpoint()
            return self.recover_failed_task()

    def read_run_resources(self,s,label):
        result=self.optional_step(label,lambda:self.world_resources(s))
        # An unreadable report footer must not block otherwise operable tasks.
        # Keep missing values unknown; never infer a spend from them.
        return result if isinstance(result,dict) else {
            'stamina':None,'stamina_cap':None,'diamonds':None,'gold_text':None}
