"""Free defeated-monster chests, independently of battle-order availability."""
from functools import lru_cache
import math
import cv2
from .backend import ROOT
from .activities import is_tribe_map,is_tribe_reward_overlay
from .policy import TaskBlocked


@lru_cache(maxsize=1)
def chest_template():
    return cv2.imread(str(ROOT/'resource/image/tribe-reward-chest.png'))


def tribe_chests(s):
    if not is_tribe_map(s):return []
    template=chest_template()
    if template is None:raise TaskBlocked('部落宝箱模板缺失')
    scores=cv2.matchTemplate(s.image[110:555,235:1120],template,cv2.TM_CCOEFF_NORMED)
    h,w=template.shape[:2];found=[]
    for _ in range(30):
        _,score,_,point=cv2.minMaxLoc(scores)
        if score<.92:break
        x,y=point;found.append((x+235+w//2,y+110+h//2))
        cv2.rectangle(scores,(max(0,x-48),max(0,y-42)),(x+48,y+42),0,-1)
    return sorted(found,key=lambda p:(p[0],p[1]))


class TribeChestRewards:
    def claim_visible_tribe_chests(self,s):
        for _ in range(30):
            self.b.guard(s)
            points=tribe_chests(s)
            if not points:return s
            point=points[0];fresh=self.observe();self.b.guard(fresh)
            current=next((p for p in tribe_chests(fresh) if math.dist(p,point)<12),None)
            if current is None:
                if not is_tribe_map(fresh):raise TaskBlocked('领取宝箱前部落地图改变')
                s=fresh;continue
            records=self.report.setdefault('tribe_chests',[])
            row={'status':'opening','point':current,'instance_id':self.report_key('tribe')}
            records.append(row);self.checkpoint()
            self.b.save_screen(fresh,self.report['folder']/f'tribe-chest-{len(records)}-before.png')
            self.b.click_at(fresh,current,['^部落$','^部落大厅$'],'领取已通关部落节点宝箱（免费）')
            reward=self.wait_for_screen(is_tribe_reward_overlay,'部落节点宝箱奖励',timeout=3)
            row.update(status='received',reward_text=reward.text)
            self.b.save_screen(reward,self.report['folder']/f'tribe-chest-{len(records)}-reward.png')
            self.checkpoint();s=self.clear_tribe_reward(reward)
            if any(math.dist(p,current)<12 for p in tribe_chests(s)):
                raise TaskBlocked('部落宝箱奖励已收到，但原宝箱仍显示，等待页面恢复')
            row['status']='claimed';self.checkpoint()
            self.note('已领取1个已通关部落宝箱，继续检查地图')
        raise TaskBlocked('单页部落宝箱数量异常，保留已领取记录')

    def collect_tribe_chests(self):
        # Unit tests using empty synthetic frames need no additional I/O.
        if self.b.tasker is None:return 0
        s=self.tribe_map();start=len(self.report.get('tribe_chests',[]))
        edges=set()
        for direction in (1,-1):
            for pan in range(25):
                s=self.claim_visible_tribe_chests(s)
                self.b.save_screen(s,self.report['folder']/f'tribe-chest-map-{direction}-{pan}.png')
                s,moved=self.pan_tribe_map(s,direction)
                if not moved:edges.add(direction);break
        if edges!={1,-1}:raise TaskBlocked('部落宝箱地图扫描尚未到达两侧边界')
        count=sum(r['status']=='claimed' for r in self.report.get('tribe_chests',[])[start:])
        self.report.setdefault('tribe_chest_sweeps',[]).append({'claimed':count,'status':'completed'})
        self.note(f'部落已通关宝箱巡查完成，新增领取{count}个');self.checkpoint()
        return count
