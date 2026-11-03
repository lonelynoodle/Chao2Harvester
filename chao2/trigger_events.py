"""Shared classification and switches for unsolicited game interruptions."""
import re

from .policy import TaskBlocked,UserStopped


EVENT_LABELS={'merchant':'神秘商人','sage_quiz':'问答（游荡智者）',
              'star_gift':'限时礼包','rift_invitation':'凿星裂痕邀请'}
TRIGGER_EVENT_SPEC={'key':'trigger_events','name':'触发事件','fields':[
    {'key':key,'label':label,'type':'bool','default':True}
    for key,label in [('merchant','处理神秘商人'),('sage_quiz','自动问答（游荡智者）'),
                      ('star_gift','自动关闭限时礼包'),('rift_invitation','自动拒绝凿星裂痕邀请')]]}
INVITE_ROI=(310,255,680,140)
REFUSE_ROI=(340,445,280,100)
INVITE_TEXT=r'^.{1,30}邀请你挑战\s*[【\[][凿幽]星裂痕[】\]]\s*关卡\s*\d{1,3}$'


def trigger_options(settings):
    raw=settings.get('trigger_events',{})
    if not isinstance(raw,dict):raise ValueError('触发事件设置格式错误')
    result=dict(raw)
    for key in EVENT_LABELS:
        result.setdefault(key,True)
        if type(result[key]) is not bool:raise ValueError(EVENT_LABELS[key]+'触发开关必须为布尔值')
    return result


def event_enabled(settings,key):
    return trigger_options(settings)[key]


def require_event_enabled(settings,key):
    if not event_enabled(settings,key):
        raise UserStopped('检测到'+EVENT_LABELS[key]+'，已关闭自动处理，保留现场等待手动处理')


def rift_invitation(s):
    prompt=s.find(INVITE_TEXT,INVITE_ROI)
    if not prompt or not s.find('^(?:取消|拒绝)$',REFUSE_ROI):return None
    if not s.find('^(?:确定|接受)$',(660,445,280,100)):return None
    return prompt


def triggered_event(s):
    # The modal must win over the battle/result page visible behind it.
    if rift_invitation(s):return 'rift_invitation'
    from .reward_collection import is_map_story
    if is_map_story(s):return 'story_card'
    from .transient_popups import is_star_gift
    from .merchant import is_merchant
    from .anomalies import is_sage_dialog
    if is_star_gift(s):return 'star_gift'
    if is_merchant(s):return 'merchant'
    if is_sage_dialog(s):return 'sage_quiz'
    return None


class TriggerEvents:
    def dismiss_triggered_popups(self,s):
        for _ in range(8):
            kind=triggered_event(s)
            if kind is None:return s
            # Incidental lore can interrupt any task, including evolution.
            # This always-on free dismissal preserves the caller's step;
            # explicit World Echo reward stories are excluded by the classifier.
            if kind=='story_card':
                s=self.close_map_story(s);continue
            if kind=='sage_quiz' and getattr(self,'_sage_active',False):return s
            require_event_enabled(self.b.settings,kind)
            if kind=='rift_invitation':s=self.refuse_rift_invitation(s)
            elif kind=='star_gift':s=self.dismiss_star_gift(s)
            else:return s  # Dialogue handlers resume at navigation boundaries.
        raise TaskBlocked('连续触发事件尚未关闭，保留现场')

    def refuse_rift_invitation(self,s):
        require_event_enabled(self.b.settings,'rift_invitation')
        prompt=rift_invitation(s)
        if not prompt:return s
        row={'invitation':prompt.text,'status':'observed','attempts':0,'source_task':self.active_task}
        rows=self.report.setdefault('rejected_invitations',[]);rows.append(row)
        self.b.save_screen(s,self.report['folder']/f'rift-invitation-{len(rows)}.png')
        self.note('检测到凿星裂痕随机邀请，自动拒绝后继续原任务')
        for attempt in range(3):
            self.b.guard(s)
            current=rift_invitation(s)
            if current is None:
                row['status']='closed';self.checkpoint();return s
            if current.text!=prompt.text:
                row['status']='replaced';self.checkpoint();return s
            self.b.click_text(s,'^(?:取消|拒绝)$',roi=REFUSE_ROI)
            row['attempts']+=1
            for _ in range(4):
                s=self.b.observe();self.b.guard(s)
                if rift_invitation(s) is None:
                    row['status']='refused';self.checkpoint();return s
                self.b.sleep(.4)
            if attempt<2:self.note('邀请弹窗仍在，重新核对后重试拒绝')
        raise TaskBlocked('凿星邀请拒绝后仍显示，已尝试3次，未点击接受')
