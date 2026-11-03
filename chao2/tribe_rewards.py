"""Free occupation income on the upper-right of the tribe map."""
from datetime import datetime

from .activities import is_tribe_map,is_tribe_reward_overlay
from .policy import TaskBlocked


OCCUPATION_LABEL=r'^遗迹占领奖励$'
OCCUPATION_ROI=(1130,145,150,45)
OCCUPATION_AMOUNT=(1223,124,42,31)


class TribeOccupationRewards:
    def read_tribe_occupation_amount(self,s):
        if not is_tribe_map(s) or not s.find(OCCUPATION_LABEL,OCCUPATION_ROI):return None
        word=s.find(r'^\d{1,5}$',OCCUPATION_AMOUNT)
        if word:return int(word.text)
        # Full-frame detection omits the small outlined digit next to the
        # purple reward icon. The fixed crop was checked on actual 2/10 frames.
        if self.b.tasker is None:return None
        return self.b.read_number(s,OCCUPATION_AMOUNT)

    def claim_tribe_occupation(self,s):
        if not is_tribe_map(s):return s
        self.b.confirm_label(s,OCCUPATION_LABEL,OCCUPATION_ROI)
        if not s.find(OCCUPATION_LABEL,OCCUPATION_ROI):return s
        before=self.read_tribe_occupation_amount(s)
        if before is None:
            # Do not block adventure just for an unreadable optional free
            # reward, but preserve it as unconfirmed in the final report.
            rows=self.report.setdefault('tribe_occupation_rewards',[])
            if not rows or rows[-1].get('status')!='unreadable':
                rows.append({'status':'unreadable','time':datetime.now().isoformat(timespec='seconds')})
                self.note('部落遗迹占领奖励数量未读清，本次保留，继续部落任务')
            return s
        for previous in self.report.get('tribe_occupation_rewards',[]):
            if previous.get('status')=='unreadable':previous.update(status='readable',remaining=before)
        if before==0:return s
        session=getattr(self,'_tribe_map_session',0)
        if getattr(self,'_tribe_occupation_attempt_session',None)==session:return s
        self._tribe_occupation_attempt_session=session
        rows=self.report.setdefault('tribe_occupation_rewards',[])
        row={'status':'pending','before':before,'time':datetime.now().isoformat(timespec='seconds'),'clicks':0}
        rows.append(row);self.checkpoint()
        def claim(q):
            if not is_tribe_map(q) or self.read_tribe_occupation_amount(q)!=before:return
            self.b.click_at(q,(1214,123),['^部落$','^部落大厅$',OCCUPATION_LABEL],
                            '领取右上角遗迹占领奖励（免费）')
            row['clicks']+=1
        def settled(q):
            return is_tribe_reward_overlay(q) or (is_tribe_map(q) and self.read_tribe_occupation_amount(q)==0)
        self.note(f'部落：领取右上角遗迹占领奖励，当前可领{before}')
        claim(s)
        try:
            q=self.wait_for_screen(settled,'遗迹占领奖励到账',timeout=4,retry_navigation=claim)
            if is_tribe_reward_overlay(q):
                row['reward_text']=q.text
                self.b.save_screen(q,self.report['folder']/f'tribe-occupation-{len(rows)}-reward.png')
                q=self.clear_tribe_reward(q)
            after=self.read_tribe_occupation_amount(q)
            self._tribe_occupation_attempt_session=getattr(self,'_tribe_map_session',session)
            row['remaining']=after
            if after!=0:
                # Some maps remove the claim badge completely after payout.
                # The actual receipt confirms delivery, even though it cannot
                # prove a remaining count of zero. Keep that count unknown.
                row['status']='received' if row.get('reward_text') else 'unconfirmed'
                self.checkpoint()
                self.note('遗迹占领奖励弹窗已确认收到；剩余可领数量未读清，不重复领取' if row['status']=='received' else
                          '遗迹占领奖励到账尚未确认，不重复领取')
                return q
            row.update(status='claimed',claimed=before)
            self.note(f'部落遗迹占领奖励已领取{before}，当前可领0');self.checkpoint()
            return q
        except TaskBlocked as error:
            row.update(status='unconfirmed',message=str(error));self.checkpoint()
            current=getattr(self,'last_screen',None)
            self._tribe_occupation_attempt_session=getattr(self,'_tribe_map_session',session)
            if current is not None and is_tribe_map(current):
                self.note('遗迹占领奖励暂未确认，保留记录并继续部落任务：'+str(error))
                return current
            raise
