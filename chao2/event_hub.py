"""Fengye event hub navigation, including titles obscured by announcements."""
from .policy import TaskBlocked


HUB_ENTRIES=(
    ('^进击巨物$',(920,170,345,145)),
    ('^三阵入局$',(0,145,1280,540)),
    ('^幻境巡游$',(750,350,230,110)),
    ('^创世竞猜$',(150,170,220,105)),
    ('^暴走回廊$',(320,355,230,110)),
    ('^拼[二三]大作战$',(20,550,315,130)),
    ('^腾龙燃火$',(540,270,210,100)),
)

ACTIVITY_ENTRIES={'giant':HUB_ENTRIES[0], 'triad':HUB_ENTRIES[1], 'puzzle':HUB_ENTRIES[5]}


def activity_entry(s,kind):
    pattern,roi=ACTIVITY_ENTRIES[kind]
    return s.find(pattern,roi)


def activity_availability(s,entry):
    """Read the caption directly below *this* event, not another event's."""
    x,y,w,h=entry.box
    roi=(max(0,x-10),y+h-4,min(1280-x+10,w+20),58)
    if s.find('^活动已结束$|^活动已关闭$',roi):return 'ended'
    if s.find(r'^\d{1,2}月\d{1,2}日开启$|^尚未开放$|^暂未开启$|^活动未开启$|^敬请期待$',roi):return 'not_open'
    return 'open'


def event_hub_anchors(s):
    if s.find('^获得奖励$|^请选择$|^规则$|^确定$|^取消$|^前往挑战$|^我的排名$'):return []
    if s.find('^丰野间$') and s.find('活动时间|^幻境巡游$'):
        return ['^丰野间$','活动时间|^幻境巡游$']
    # A world-announcement banner crosses the title. Require the schedule,
    # three independently positioned entries, and the undimmed gold close area.
    # The new seasonal title has no calibrated fixed slot yet. It is safe as
    # a click target only after the hub itself is established independently.
    found=[pattern for pattern,roi in HUB_ENTRIES if pattern!='^三阵入局$' and s.find(pattern,roi)]
    if len(found)<3 or not s.find(r'^活动时间[:：]',(400,95,500,75)):return []
    corner=s.image[8:72,8:72]
    gold=((corner[:,:,2]>180)&(corner[:,:,1]>120)&(corner[:,:,0]<140)).mean()
    return [r'^活动时间[:：]',*found] if gold>.3 else []


def is_event_hub(s):return bool(event_hub_anchors(s))


class EventHubNavigation:
    def event_hub(self,screen=None):
        s=screen if screen is not None else self.observe();self.b.guard(s)
        if is_event_hub(s):return self.confirm_event_hub(s)
        s=self.home(s);self.click_world(s,(220,83),'进入丰野间')
        return self.await_event_hub()

    def confirm_event_hub(self,s):
        if not is_event_hub(s):raise TaskBlocked('丰野间页面未确认')
        if not s.find('^丰野间$') and not self.report.get('event_hub_title_recovered'):
            self.report['event_hub_title_recovered']=True
            self.b.save_screen(s,self.report['folder']/'event-hub-title-covered.png')
            self.note('丰野间标题被遮挡，已通过活动时间和多个活动入口确认页面')
        return s

    def await_event_hub(self):
        def reopen(s):
            from .workflows import is_world
            if is_world(s):self.click_world(s,(220,83),'重试进入丰野间（仍在世界地图）')
        return self.confirm_event_hub(self.wait_for_screen(is_event_hub,'丰野间活动页面',retry_navigation=reopen))

    def close_event_hub(self,s):
        self.confirm_event_hub(s)
        self.b.click_at(s,(45,28),event_hub_anchors(s),'返回世界')
        def close_again(q):
            if is_event_hub(q):self.b.click_at(q,(45,28),event_hub_anchors(q),'重试返回世界（仍在丰野间）')
        return self.wait_for_screen(lambda q:not is_event_hub(q),'丰野间返回上级',retry_navigation=close_again)
