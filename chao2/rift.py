"""Prefer the highest rift, fall back when unavailable; verify victory chests."""
import re
import math
from maa.pipeline import JTemplateMatch
from .configuration import team_order
from .policy import TaskBlocked,SafetyStop,FightLost
from .activities import BudgetReached
from .backend import Screen,Word

RIFT_TITLE=r'^[凿幽]星裂痕$'
RIFT_STAGE=r'^(\d{1,3})\s*[-－—]\s*[凿幽]星裂痕关卡\s*(\d{1,3})$'


def rift_detail(s):
    w=s.find(RIFT_STAGE,(340,95,540,75))
    # A modal dims the map title; the complete repeated stage number and
    # single-player panel identify this page without the dark background OCR.
    if not w or not s.has('^排阵$','^前往挑战$','可获得奖励'):return None
    m=re.fullmatch(RIFT_STAGE,w.text)
    return int(m[1]) if m and m[1]==m[2] else None


def recover_rift_detail(b,s):
    if rift_detail(s) is not None or b.tasker is None:return s
    word=s.find(RIFT_STAGE,(340,95,540,75))
    if not word or not s.has('^排阵$','^前往挑战$','可获得奖励'):return s
    # Full-frame detection can clip the final narrow 1 (31 -> 3). Read
    # the actual title twice, including both numbers; never infer the suffix.
    reads=[b.read_text_crop(s,roi) for roi in ((350,110,330,40),(352,112,330,38))]
    match=re.fullmatch(RIFT_STAGE,reads[0])
    original=re.fullmatch(RIFT_STAGE,word.text)
    if (reads[0]!=reads[1] or not match or match[1]!=match[2] or
            match[1]!=original[1]):return s
    return Screen(s.image,[*s.words,Word(reads[0],[350,110,330,40],1.)],s.when)


def is_rift_map(s):
    return bool(s.find(RIFT_TITLE,(90,0,190,65)) and
                s.find('[凿幽]星裂痕当前通关',(480,0,330,40)) and
                s.has('^匹配房间$','^创建队伍$') and rift_detail(s) is None)


def is_rift_victory(s):
    return bool(s.find('胜利',(0,160,540,390)) and s.has('^退出$','^再虐一遍$') and
                (s.find('开启宝箱.*当前拥有',(730,475,450,65)) or
                 s.find('^宝箱奖励$',(830,300,220,65))))


def rift_progress(b,s):
    if not is_rift_map(s):raise TaskBlocked('裂痕地图未确认')
    text=s.region_text((560,30,160,50))
    value=int(text) if text.isdigit() else b.read_number(s,(606,31,70,38))
    if value is None or not 0<=value<=999:raise TaskBlocked('裂痕当前通关等级未读清')
    return value


def rift_map_keys(b,s):
    if not is_rift_map(s):raise TaskBlocked('读取钥匙前裂痕地图未确认')
    pair=b.read_resource_ratio(s,(1090,0,110,65))
    if pair is None or not 0<=pair[0]<=999 or pair[1]<=0:raise TaskBlocked('裂痕钥匙余额未读清')
    return pair[0]


def rift_chest_keys(s):
    if not is_rift_victory(s):return None
    label=s.region_text((750,480,425,55))
    m=re.search(r'当前拥有\s*[:：]?\s*[xX×]?\s*(\d+)\s*[)）]?$',label)
    return int(m[1]) if m else None


def rift_node(b,s,number):
    if not is_rift_map(s):return None
    found=[]
    for kind in ('next','open','locked'):
        # The blue ring/background animates behind the diamond. Matching its
        # outer corners rejected the cleared stage 25 (.80 vs .86) even though
        # its spiral and number were unambiguous. Match the inner symbol instead;
        # the open spiral and padlock remain visually distinct (> .9 vs < .7).
        template=f'rift-{kind}-'+('node' if kind=='next' else 'core')+'.png'
        result=b.wait(b.tasker.post_recognition('TemplateMatch',
            JTemplateMatch(template=[template],roi=[0,70,1280,485],threshold=[.8 if kind=='next' else .86]),s.image),10).get()
        for node in result.nodes if result else []:
            if not node.recognition:continue
            for match in node.recognition.filtered_results:
                x,y,w,h=match.box;cx=x+w//2;cy=y+h//2
                if cx<22 or cx>1257 or cy+60>555:continue
                # Keep the proven wide reads for spiral/lock cores. On cleared
                # 31 they include a vertical tether and read blank/|31; an
                # actual nearby OCR box offers two additional independent reads.
                # A full-frame 31 can be read as "3]". Its box is still useful
                # for two exact crop reads; the garbled text never supplies a number.
                label=s.find(r'^[0-9\[\]|IlOo]{1,4}$',(cx-25,cy+22,50,46))
                offset=22 if kind=='next' else 30
                wide=((cx-21,cy+offset,42,28),(cx-21,cy+offset+2,42,28))
                groups=[wide]
                if label and label.score>=.8:
                    x,y,lw,lh=label.box
                    tight=((x-2,y-2,lw+4,lh+4),(x-3,y-3,lw+6,lh+6))
                    groups=[tight] if kind=='next' else [wide,tight]
                if not any(all(b.read_text_crop(s,roi)==str(number) for roi in rois)
                           for rois in groups):continue
                found.append((float(match.score),kind,(cx,cy)))
    if not found:return None
    found.sort(reverse=True)
    if any(kind!=found[0][1] and score>=found[0][0]-.04 for score,kind,_ in found[1:]):
        raise TaskBlocked('裂痕节点锁定状态不明确，未选择较低关卡')
    return found[0][1],found[0][2]


def rift_visible_labels(s):
    return {int(w.text):w.center for w in s.words
            if w.text.isdigit() and 80<w.center[1]<555 and 0<int(w.text)<1000}


def rift_map_moved(before,after):
    a=rift_visible_labels(before);b=rift_visible_labels(after)
    common=a.keys()&b.keys()
    # Compare node labels, excluding the animated ring and next-node glow.
    if len(common)<2:return None
    return any(math.dist(a[n],b[n])>8 for n in common)


def rift_level_locked(s):
    return rift_detail(s) is not None and bool(s.find('探索者.*级.*解锁|探索者.*级.*开启|需要.*级|等级不足|尚未解锁|未解锁|达到.*级',(340,90,930,590)))


def verify_free_rift(b,s,stage):
    b.guard(s)
    if rift_detail(s)!=stage or not s.has('^排阵$','^前往挑战$','可获得奖励'):
        raise TaskBlocked('裂痕目标关卡或单人挑战入口未确认')
    if rift_level_locked(s):raise TaskBlocked('裂痕目标尚未达到解锁等级')
    if re.search(r'\d|消耗|购买|钻石',s.region_text((990,590,275,90))):
        raise SafetyStop('裂痕前往挑战出现费用，未点击')
    if not b.match_template(s,'rift-free-challenge.png',[990,590,275,90],.9):
        raise TaskBlocked('裂痕单人免费挑战按钮未确认')


class RiftActivity:
    def rift_wait_map(self):
        for _ in range(10):
            s=self.observe();self.b.guard(s)
            if is_rift_map(s):return s
            self.b.sleep(.5)
        raise TaskBlocked('裂痕未返回地图，保留现场')

    def rift_wait_detail(self,stage):
        for _ in range(10):
            s=self.observe();self.b.guard(s)
            if rift_detail(s)==stage:return s
            if rift_detail(s) is not None:raise TaskBlocked('裂痕实际打开了其他关卡，未挑战')
            self.b.sleep(.5)
        raise TaskBlocked(f'裂痕{stage}关详情未打开')

    def rift_map(self):
        s=self.observe();self.b.guard(s)
        if is_rift_map(s):return s
        if rift_detail(s) is not None:
            self.b.click_at(s,(43,28),[RIFT_STAGE,'^排阵$'],'返回裂痕地图')
            return self.rift_wait_map()
        s=self.enter_overview(RIFT_TITLE)
        if not is_rift_map(s):raise TaskBlocked('裂痕入口未到达地图')
        return s

    def rift_balance(self,s):
        count=rift_map_keys(self.b,s)
        self.resource_balance('rift','裂痕钥匙',count)
        if count<=self.options['rift']['reserve_keys']:
            reserve=self.options['rift']['reserve_keys']
            raise BudgetReached(f'裂痕钥匙剩余{count}，'+(f'按设置保留{reserve}把' if reserve else '已用完'))
        return count

    def rift_locate(self,s,stage):
        stalled=0
        for pan in range(8):
            self.b.guard(s)
            if not is_rift_map(s):raise TaskBlocked('查找裂痕节点时地图改变')
            node=rift_node(self.b,s,stage)
            if node:return s,node
            if stage in rift_visible_labels(s):
                for retry in range(3):
                    self.note(f'裂痕{stage}关编号已在当前页，原地核对节点 {retry+1}/3')
                    self.b.sleep(.6);s=self.observe();self.b.guard(s)
                    if not is_rift_map(s):raise TaskBlocked('核对裂痕节点时地图改变')
                    node=rift_node(self.b,s,stage)
                    if node:return s,node
                raise TaskBlocked(f'裂痕{stage}关编号可见，但节点状态重读3次仍未确认，未重复滑动')
            if pan==7:break
            visible=list(rift_visible_labels(s))
            if not visible:raise TaskBlocked('裂痕节点及相邻编号未读清，不选择低级关卡')
            direction=1 if stage>min(visible,key=lambda n:abs(n-stage)) else -1
            swipe=(1000,300,700,300) if direction==1 else (280,300,580,300)
            self.note(f'查找裂痕{stage}关，向'+('右' if direction==1 else '左')+'查看相邻节点')
            if not self.b.wait(self.b.controller.post_swipe(*swipe,1200)).succeeded:
                raise TaskBlocked('裂痕地图滑动失败')
            before=s;self.b.sleep(1);s=self.observe()
            stalled=stalled+1 if rift_map_moved(before,s) is False else 0
            if stalled>=2:
                node=rift_node(self.b,s,stage)
                if node:return s,node
                raise TaskBlocked(f'裂痕{stage}关节点未确认，地图连续两次未移动，停止重复滑动')
        raise TaskBlocked(f'裂痕{stage}关节点未确认，未降级挑战')

    def rift_open_stage(self,s,stage):
        s,node=self.rift_locate(s,stage)
        if node[0]=='locked':raise TaskBlocked(f'裂痕{stage}关仍锁定，未挑战')
        for attempt in range(4):
            fresh=self.observe();self.b.guard(fresh)
            if not is_rift_map(fresh):raise TaskBlocked('核对裂痕节点时地图未确认')
            again=rift_node(self.b,fresh,stage)
            if again and again[0]==node[0] and math.dist(again[1],node[1])<=12:
                self.b.click_at(fresh,again[1],[RIFT_TITLE,'当前通关','^匹配房间$','^创建队伍$'],f'打开裂痕{stage}关')
                return self.rift_wait_detail(stage)
            if attempt==3:raise TaskBlocked(f'裂痕{stage}关节点状态重读3次仍未确认，未点击')
            self.navigation_retry(f'裂痕{stage}关点击前节点未稳定，重新取图核对',attempt+1,fresh)
            if again and again[0]!='locked':node=again
            self.b.sleep(.6)

    def rift_highest(self,s):
        for attempt in range(4):
            self.b.guard(s)
            try:
                cleared=rift_progress(self.b,s);break
            except TaskBlocked:
                if not is_rift_map(s):raise
                if attempt==3:raise TaskBlocked('裂痕当前通关等级重读3次仍未确认，未猜测关卡')
                self.navigation_retry('裂痕通关数字可能被公告遮挡，等待新画面',attempt+1,s)
                self.b.sleep(2);s=self.observe()
        ceiling=getattr(self,'_rift_stage_ceiling',None)
        stage=min(cleared+1,ceiling) if ceiling is not None else cleared+1
        while stage>=1:
            s,node=self.rift_locate(s,stage)
            if node[0]=='locked':reason='节点尚未解锁'
            else:
                detail=self.rift_open_stage(s,stage)
                if not rift_level_locked(detail):return detail,stage
                reason='探索者等级不足';s=self.rift_map()
            self.rift_fallback(stage,reason);stage-=1
        raise BudgetReached('裂痕暂无已解锁且所选阵容可通过的关卡')

    def rift_fallback(self,stage,reason):
        # This ceiling is reset for each run. Once a stage is unavailable or
        # all selected teams lose, spending the next key must not retry it.
        self._rift_stage_ceiling=stage-1
        self.report.setdefault('rift_runtime_by_instance',{}).setdefault(
            self.report_key('rift'),{'failed':{}})['ceiling']=stage-1
        self.report.setdefault('rift_fallbacks',[]).append(
            {'from':stage,'to':stage-1 if stage>1 else None,'reason':reason})
        self.note(f'裂痕{stage}关{reason}；'+
                  (f'本轮回退到{stage-1}关' if stage>1 else '已到第1关，停止挑战'))
        self.checkpoint()

    def rift_claim(self,result,stage):
        self.b.guard(result)
        if not is_rift_victory(result) or result.find('^宝箱奖励$'):
            raise TaskBlocked('裂痕未确认尚未开启的胜利宝箱，未使用钥匙')
        before=rift_chest_keys(result)
        if before is None:raise TaskBlocked('开箱前钥匙余额未读清')
        if before<=self.options['rift']['reserve_keys']:raise SafetyStop('开箱前钥匙已达到保留数量，保留胜利现场')
        fresh=self.observe();self.b.guard(fresh)
        if rift_chest_keys(fresh)!=before:raise TaskBlocked('开箱前钥匙数量或页面改变，未重复点击')
        if not self.b.match_template(fresh,'rift-key-cost.png',[750,480,185,55],.9) or not self.b.match_template(fresh,'rift-closed-chest.png',[880,335,115,125],.9):
            raise TaskBlocked('裂痕宝箱及钥匙费用图标未确认')
        row={'stage':stage,'keys_before':before,'status':'opening'}
        self.report.setdefault('rift_chests',[]).append(row)
        self.b.save_screen(fresh,self.report['folder']/f'rift-chest-{len(self.report["rift_chests"])}-before.png')
        self.b.click_at(fresh,(939,401),['胜利','^退出$','^再虐一遍$','开启宝箱.*当前拥有'],'使用1把库存裂痕钥匙开箱')
        for _ in range(10):
            reward=self.observe();self.b.guard(reward)
            if is_rift_victory(reward) and reward.find('^宝箱奖励$',(830,300,220,65)):
                row['reward_text']=reward.text
                self.b.save_screen(reward,self.report['folder']/f'rift-chest-{len(self.report["rift_chests"])}-reward.png')
                break
            self.b.sleep(.5)
        else:raise SafetyStop('裂痕开箱结果未确认，已停止，未重复使用钥匙')
        self.exit_result(reward);s=self.rift_wait_map();after=rift_map_keys(self.b,s)
        row['keys_after']=after
        if after!=before-1:
            row['status']='unverified';self.resource_spent('rift','裂痕钥匙',None,after)
            raise SafetyStop('裂痕奖励已显示，但钥匙扣除与1把不符，停止后续挑战')
        row['status']='claimed';self.resource_spent('rift','裂痕钥匙',1,after)
        self.note(f'裂痕{stage}关已开箱，消耗1把钥匙，剩余{after}把')
        self.checkpoint();return s

    def rift(self):
        self.active_task='rift';wins=0;reason=''
        runtime=self.report.setdefault('rift_runtime_by_instance',{}).setdefault(
            self.report_key('rift'),{'ceiling':None,'failed':{}})
        if runtime.get('completed'):runtime.update(ceiling=None,failed={},completed=False)
        failed=runtime['failed'];self._rift_stage_ceiling=runtime.get('ceiling')
        while True:
            try:
                self.check_budget('rift');s=self.rift_map();balance=self.rift_balance(s)
                detail,stage=self.rift_highest(s)
            except BudgetReached as e:reason=str(e);break
            self.report['rift_highest_stage']=max(stage,self.report.get('rift_highest_stage',0))
            self.report['rift_target_stage']=stage
            self.note(f'裂痕本次挑战关卡：{stage}，按阵容顺序尝试')
            won=False
            for team in team_order(self.options['rift']):
                if team in failed.setdefault(str(stage),[]):continue
                self.check_budget('rift')
                if detail is None:
                    s=self.rift_map();balance=self.rift_balance(s)
                    detail=self.rift_open_stage(s,stage)
                detail=self.select_team(detail,team,return_page=lambda:self.rift_wait_detail(stage))
                verify_free_rift(self.b,detail,stage);self.check_budget('rift')
                self.start_challenge('rift',detail,'裂痕挑战免费',lambda q:verify_free_rift(self.b,q,stage))
                try:result=self.battle('裂痕挑战免费');outcome='victory'
                except FightLost as lost:result=lost.screen;outcome='failed'
                self.report.setdefault('team_attempts',[]).append({'task':'rift','team':team,'outcome':outcome,'target':f'裂痕{stage}'})
                self.note(f'裂痕{stage}关'+('胜利' if outcome=='victory' else '未通过')+(f'（队伍{team}）' if team else ''))
                self.checkpoint()
                if outcome=='victory':
                    wins+=1;self.rift_claim(result,stage);won=True;break
                failed[str(stage)].append(team);self.checkpoint();self.exit_result(result);s=self.rift_wait_map()
                if rift_map_keys(self.b,s)<balance:raise SafetyStop('裂痕失败后钥匙减少，停止后续挑战')
                detail=None
            if not won:
                self.report['rift_failed_stage']=stage
                self.rift_fallback(stage,'所选阵容均未通过')
                if stage<=1:
                    reason='裂痕第1关的所选阵容均未通过';break
        chests=sum(row['status']=='claimed' for row in self.report.get('rift_chests',[]))
        self.home()
        runtime['completed']=True;self.checkpoint()
        return f'裂痕胜利{wins}次，已开箱{chests}次；{reason}'
