"""Free anomaly chests left when another explorer defeats our copy."""
from functools import lru_cache
import math
import re
import cv2

from .backend import ROOT
from .activities import COPY_LIST_ANCHORS,is_copy_list
from .policy import TaskBlocked
from .reward_collection import reward_overlay
from .screen_loading import loading_spinner


DEFEATED_COPY = r'^被探索者.+击[破败]$'


@lru_cache(maxsize=1)
def copy_chest_template():
    template=cv2.imread(str(ROOT/'resource/image/copy-defeated-chest.png'))
    if template is None:raise TaskBlocked('复制体奖励宝箱模板缺失')
    return template


def copy_reward_rows(s):
    if not is_copy_list(s) or reward_overlay(s) or loading_spinner(s):return []
    rows=[];template=copy_chest_template()
    for word in s.words:
        x,y=word.center
        if not (910<x<1200 and 240<y<620 and re.fullmatch(DEFEATED_COPY,word.text)):continue
        crop=s.image[y-82:y+8,812:912]
        _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(crop,template,cv2.TM_CCOEFF_NORMED))
        if score<.90:continue
        name=s.region_text((910,y-75,285,45)).strip()
        rows.append({'name':name,'defeated_by':word.text,
                     'point':(812+point[0]+template.shape[1]//2,y-82+point[1]+template.shape[0]//2)})
    return sorted(rows,key=lambda row:row['point'][1])


class CopyRewards:
    def claim_visible_copy_rewards(self,s):
        while True:
            self.b.guard(s)
            if loading_spinner(s):
                s=self.wait_for_screen(lambda q:is_copy_list(q) and not reward_overlay(q) and not loading_spinner(q),
                                        '复制体宝箱列表加载结束',timeout=6)
            candidates=copy_reward_rows(s)
            if not candidates:return s
            records=self.report.setdefault('copy_rewards',[])
            if any(r.get('status') in ('opening','unconfirmed') for r in records):
                raise TaskBlocked('复制体宝箱领取结果未确认，未重复点击')
            fresh=self.observe();self.b.guard(fresh)
            row=next((r for r in copy_reward_rows(fresh)
                      if math.dist(r['point'],candidates[0]['point'])<12),None)
            if row is None:
                if not is_copy_list(fresh):raise TaskBlocked('领取复制体宝箱前列表已改变')
                s=fresh;continue
            record={**row,'status':'opening','clicks':1,'instance_id':self.report_key('copies')}
            records.append(record);self.checkpoint()
            self.b.save_screen(fresh,self.report['folder']/f'copy-reward-{len(records)}-before.png')
            self.b.click_at(fresh,row['point'],[*COPY_LIST_ANCHORS,DEFEATED_COPY],
                            '领取被其他探索者击破的复制体宝箱（免费）')
            def retry_claim(q):
                # This free, still-visible chest can be retried when the
                # client swallowed the input. Re-read its icon/name/status;
                # never retry against a receipt, loading frame or another row.
                def same(r):
                    return (r['name']==row['name'] and r['defeated_by']==row['defeated_by'] and
                            math.dist(r['point'],row['point'])<12)
                if not any(same(r) for r in copy_reward_rows(q)):return
                current=self.observe();self.b.guard(current)
                matches=[r for r in copy_reward_rows(current) if same(r)]
                if len(matches)!=1:return
                self.b.click_at(current,matches[0]['point'],[*COPY_LIST_ANCHORS,DEFEATED_COPY],
                                '重新核对同一免费复制体宝箱后补点')
                record['clicks']+=1;self.checkpoint()
            try:
                receipt=self.wait_for_screen(reward_overlay,'复制体宝箱奖励到账',timeout=6,
                                             retry_navigation=retry_claim)
            except TaskBlocked:
                record['status']='unconfirmed';self.checkpoint()
                raise TaskBlocked('复制体宝箱领取结果未确认，未重复点击')
            record.update(status='received',reward_text=receipt.text)
            self.b.save_screen(receipt,self.report['folder']/f'copy-reward-{len(records)}-receipt.png')
            self.checkpoint()
            s,_=self.dismiss_collection_reward(receipt)
            def updated(q):
                return is_copy_list(q) and not reward_overlay(q) and not any(
                    r['name']==row['name'] and r['defeated_by']==row['defeated_by'] and
                    math.dist(r['point'],row['point'])<12 for r in copy_reward_rows(q))
            if not updated(s):
                s=self.wait_for_screen(updated,'复制体领奖后列表更新',timeout=4)
            record['status']='claimed';self.checkpoint()
            self.note('已领取1个被他人击破的复制体宝箱，不消耗体力或挑战次数')

    def collect_copy_rewards(self):
        if self.b.tasker is None:return 0
        start=sum(r.get('status')=='claimed' for r in self.report.get('copy_rewards',[]))
        # Own copies and their defeated chests are at the top. Claim only
        # visible chests; ordinary target selection advances the list as needed.
        # Never sweep down/up just to inspect rewards before fighting.
        self.claim_visible_copy_rewards(self.copy_list())
        count=sum(r.get('status')=='claimed' for r in self.report.get('copy_rewards',[]))-start
        self.report.setdefault('copy_reward_checks',[]).append(
            {'instance_id':self.report_key('copies'),'status':'completed','claimed':count})
        self.checkpoint()
        if count:self.note(f'复制体列表顶部已领取{count}个免费宝箱，继续按当前目标挑战')
        return count
