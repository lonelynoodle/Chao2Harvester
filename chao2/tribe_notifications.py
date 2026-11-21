"""Read tribe notifications and collect earned core milestones, without donating."""
import numpy as np

from .activities import is_tribe_map
from .policy import TaskBlocked
from .reward_collection import reward_overlay
from .star_shop import donation_page
from .screen_loading import loading_spinner as tribe_loading


SIDEBAR = (0,95,175,390)
CORE_REWARD_TITLE = (395,15,500,75)
CORE_CLAIM = (365,604,550,66)


def tribe_auction_page(s):
    return bool(s.find('^拍卖所$',(80,0,220,65)) and
                s.find('^竞拍$',SIDEBAR) and s.find('^记录$',SIDEBAR))


def tribe_dynamics_page(s):
    return bool(s.find('^部落动态$',(80,0,250,65)) and
                all(s.find('^'+name+'$',SIDEBAR) for name in
                    ('我的消息','个人战报','部落战报','遗迹播报')))


def tribe_tab_selected(s,name):
    word=s.find('^'+name+'$',SIDEBAR)
    if word is None:return False
    y=word.center[1]
    patch=s.image[y-20:y+20,5:145].astype('int16')
    blue,green,red=(patch[:,:,i] for i in range(3))
    return bool(((red>175)&(green>145)&(blue<195)&(red-blue>35)).mean()>.30)


def donation_rewards_page(s):
    return bool(s.find('^支配核心捐献奖励$',CORE_REWARD_TITLE) and
                s.find('^全部领取$',CORE_CLAIM) and
                s.find('达成条件[:：].*支配核心捐献',(330,135,560,460)))


def donation_claim_state(s):
    if not donation_rewards_page(s):return None
    word=s.find('^全部领取$',CORE_CLAIM)
    x,y,w,h=word.box
    light=float((np.min(s.image[y:y+h,x:x+w],axis=2)>175).mean())
    # Like other free claim controls, the disabled text is grey. Test the
    # letters alone so that its gold border cannot make it look enabled.
    if light>.10:return 'ready'
    if light<.015:return 'empty'
    return None


class TribeNotifications:
    def close_donation_rewards(self,s):
        if not donation_rewards_page(s):raise TaskBlocked('支配核心捐献奖励窗口未识别')
        self.b.click_at(s,(1028,55),['^支配核心捐献奖励$','^全部领取$'],
                        '关闭支配核心累计捐献奖励')
        return self.wait_for_screen(lambda q:donation_page(q) and not donation_rewards_page(q),
                                    '关闭累计捐献奖励后返回支配核心',timeout=4)

    def claim_tribe_donation_rewards(self,s=None):
        s=s if s is not None else self.observe()
        if not donation_rewards_page(s):
            if not donation_page(s):s=self.open_tribe_donation()
            # The eye opens the milestone list. Both paid donation buttons
            # and the five core-upgrade controls are outside this region.
            self.b.click_at(s,(643,479),['^支配核心$','^消耗$'],
                            '查看支配核心累计捐献奖励，不进行捐献')
            s=self.wait_for_screen(donation_rewards_page,'支配核心累计捐献奖励',timeout=4)
        state=donation_claim_state(s)
        if state is None:raise TaskBlocked('累计捐献免费领取按钮状态未读清')
        rows=self.report.setdefault('tribe_donation_rewards',[])
        if state=='empty':
            rows.append({'status':'empty','message':'当前没有可领取的累计捐献奖励'})
            self.checkpoint();return self.close_donation_rewards(s)
        if any(r.get('status') in ('pending','unconfirmed') for r in rows):
            raise TaskBlocked('累计捐献奖励上次领取结果未确认，未重复提交')
        fresh=self.observe();self.b.guard(fresh)
        if donation_claim_state(fresh)!='ready':
            raise TaskBlocked('累计捐献奖励领取前页面状态改变')
        row={'status':'pending','before_text':fresh.text};rows.append(row);self.checkpoint()
        self.b.click_at(fresh,fresh.find('^全部领取$',CORE_CLAIM).center,
                        ['^支配核心捐献奖励$','^全部领取$'],'领取已达成的累计捐献奖励（免费）')
        for _ in range(6):
            s=self.observe();self.b.guard(s)
            if reward_overlay(s):
                row.update(status='received',reward_text=s.text)
                self.b.save_screen(s,self.report['folder']/f'tribe-donation-rewards-{len(rows)}.png')
                self.checkpoint()
                s,_=self.dismiss_collection_reward(s)
                if not donation_rewards_page(s):
                    s=self.wait_for_screen(donation_rewards_page,'累计捐献领奖后列表恢复',timeout=4)
                row['status']='claimed';self.checkpoint()
                self.note('已领取支配核心累计捐献奖励')
                return self.close_donation_rewards(s)
            self.b.sleep(.5)
        row['status']='unconfirmed';self.checkpoint()
        raise TaskBlocked('累计捐献奖励领取结果未确认，未重复提交')

    def read_tribe_notifications(self,kind):
        auction=kind=='auction'
        label='拍卖所' if auction else '动态'
        page=tribe_auction_page if auction else tribe_dynamics_page
        tabs=('竞拍','记录') if auction else ('我的消息','个人战报','部落战报','遗迹播报')
        s=self.tribe_map()
        self.b.click_at(s,(665,630) if auction else (780,630),
                        ['^部落$','^部落大厅$'],'查看部落'+label+'通知')
        def open_again(q):
            if is_tribe_map(q) and not tribe_loading(q):
                self.b.click_at(q,(665,630) if auction else (780,630),
                                ['^部落$','^部落大厅$'],'重新打开部落'+label+'通知')
        s=self.wait_for_screen(lambda q:page(q) and not tribe_loading(q),
                                '部落'+label,timeout=4,retry_navigation=open_again)
        row={'kind':kind,'status':'reading','tabs':[]}
        self.report.setdefault('tribe_notifications',[]).append(row);self.checkpoint()
        for name in tabs:
            if not tribe_tab_selected(s,name):
                self.b.click_text(s,'^'+name+'$',roi=SIDEBAR)
            def select_again(q):
                if page(q) and not tribe_loading(q) and not tribe_tab_selected(q,name):
                    self.b.click_text(q,'^'+name+'$',roi=SIDEBAR)
            s=self.wait_for_screen(lambda q:page(q) and tribe_tab_selected(q,name) and not tribe_loading(q),
                                    '部落'+label+'：'+name,timeout=4,retry_navigation=select_again)
            row['tabs'].append(name)
        self.b.back(s,'查看部落'+label+'后返回地图')
        s=self.wait_for_screen(is_tribe_map,'通知查看后返回部落地图',timeout=4)
        row['status']='read';self.checkpoint()
        self.note('部落'+label+'通知已查看')
        return s

    def collect_tribe_extras(self):
        if self.b.tasker is None:return
        options=self.options['tribe']
        for kind,key in (('auction','clear_auction_dot'),('dynamics','clear_dynamics_dot')):
            if options[key]:self.read_tribe_notifications(kind)
        if options['claim_donation_rewards']:
            s=self.claim_tribe_donation_rewards()
            self.b.back(s,'累计捐献领奖后返回部落地图')
            self.wait_for_screen(is_tribe_map,'累计捐献领奖后部落地图',timeout=4)
