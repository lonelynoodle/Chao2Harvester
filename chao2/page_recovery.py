"""Return to a recognized page and re-enter a task, preserving its ledger."""
import re
from functools import lru_cache
import cv2
from .backend import ROOT,Word
from .policy import TaskBlocked,PageChanged


def exit_game_dialog(s):
    return s.has('^是否确认退出游戏$','^再玩一会$','^退出游戏$')


@lru_cache(maxsize=4)
def return_template(name):return cv2.imread(str(ROOT/'resource/image'/name))


def visual_return_control(s):
    # Android BACK opens the game's quit prompt. Use the actual game arrow/X.
    if exit_game_dialog(s):return s.find('^再玩一会$')
    for name,roi in (('plane-gate-close.png',(995,40,85,85)),
                     ('return-arrow-gold.png',(0,0,100,65)),
                     ('return-arrow-white.png',(0,0,85,70))):
        template=return_template(name)
        if template is None:continue
        x,y,w,h=roi;crop=s.image[y:y+h,x:x+w]
        _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(crop,template,cv2.TM_CCOEFF_NORMED))
        if score>=.94:
            return Word('已确认的返回控件',[x+point[0],y+point[1],template.shape[1],template.shape[0]],float(score))
    return None


def navigation_failure(error):
    if isinstance(error,PageChanged):return True  # No click was sent.
    if not isinstance(error,TaskBlocked):return False
    text=str(error)
    if re.search('消耗.*未确认|扣除.*不符|使用后|使用后的|捕兽夹|已结算.*次数|结果未确认|库存.*减少|未同时确认',text):return False
    return bool(re.search('未识别|未读清|未确认|页面改变|页面变化|未打开|未找到入口|未找到.*页面|未到达|未配置返回|未加载|翻页失败|位置.*改变|复制.*未|节点正在移动|锁定状态改变',text))


class PageRecovery:
    def can_recover_page(self,error):
        if self.b.tasker is None or self.b.controller is None or not navigation_failure(error):return False
        if any(r.get('status') in ('opening','unverified') for r in self.report.get('rift_chests',[])):return False
        if self.report.get('piggy_spend_unconfirmed'):return False
        if any(r.get('status') in ('using_trap','capturing') for r in self.report.get('wild_captures',[])):return False
        return True

    def with_page_recovery(self,run,label):
        for attempt in range(4):
            try:return run()
            except (PageChanged,TaskBlocked) as error:
                if attempt==3 or not self.can_recover_page(error):raise
                rows=self.report.setdefault('page_recoveries',[])
                row={'task':self.active_task,'instance_id':self.report_key(self.active_task),
                     'label':label,'attempt':attempt+1,'reason':str(error),'status':'returning',
                     'attempts_before':dict(self.task_counts),'battles_before':self.battles}
                rows.append(row)
                screen=getattr(error,'screen',None) or getattr(self,'last_screen',None)
                if screen is not None:self.b.save_screen(screen,self.report['folder']/f'page-recovery-{len(rows)}.png')
                self.note(f'{label}页面识别失败，逐级返回后重新进入（{attempt+1}/3）')
                self.checkpoint();self._overview_ready=None;self._challenge_entry=None
                wild=getattr(self,'wild_daily_active',False);self.wild_daily_active=False
                try:self.home()
                finally:self.wild_daily_active=wild
                row['status']='reentered';self.checkpoint()
        raise TaskBlocked(label+'页面恢复次数已用完')
