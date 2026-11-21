"""Recognized unsolicited offers: dismissal only, never purchase controls."""
import re

from .policy import TaskBlocked
from .trigger_events import require_event_enabled


GOLD_DETAILS_ANCHORS=('^金币$',r'^已拥有\s*\d','^主要获得途径$')
GOLD_DETAILS_BLANK=(640,650)


def is_gold_details(s):
    return bool(s.find(GOLD_DETAILS_ANCHORS[0],(475,86,250,53)) and
                s.find(GOLD_DETAILS_ANCHORS[1],(475,135,300,50)) and
                s.find(GOLD_DETAILS_ANCHORS[2],(385,305,230,80)) and
                s.find('^星律$|^黑暗森林$|^购买$',(390,380,170,187)) and
                not s.find('^取消$|^确定$|^确认购买$',(360,160,570,420)))


def is_star_gift(s):
    if not s.find('^限时星礼$',(90,0,210,65)):return False
    # Card content may change, but at least two offers must occupy the card row.
    cards=[w for w in s.words if re.fullmatch(r'.{2,12}星礼',w.text) and
           80<w.center[0]<1150 and 280<w.center[1]<380]
    return len(cards)>=2


class TransientPopups:
    def dismiss_star_gift(self,s):
        if not is_star_gift(s):return s
        require_event_enabled(self.b.settings,'star_gift')
        entry={'status':'observed','close_attempts':0,'task':self.active_task}
        rows=self.report.setdefault('dismissed_offers',[]);rows.append(entry)
        self.b.save_screen(s,self.report['folder']/f'star-gift-{len(rows)}.png')
        self.note('检测到限时星礼，退出礼包页面后继续当前任务')
        for attempt in range(3):
            self.b.guard(s)
            if not is_star_gift(s):return s
            self.b.click_at(s,(43,28),['^限时星礼$'],'退出限时星礼，不购买')
            entry['close_attempts']+=1
            for _ in range(4):
                s=self.b.observe();self.b.guard(s)
                if not is_star_gift(s):
                    entry['status']='closed';self.checkpoint();return s
                self.b.sleep(.5)
            if attempt<2:self.note(f'礼包仍在显示，重新核对后重试退出（{attempt+1}/2）')
        raise TaskBlocked('限时星礼退出后仍显示，已尝试3次；未点击任何购买按钮')
