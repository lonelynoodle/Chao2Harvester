"""Independent 幻境巡游: observed environments, bounded team fallback, no paid actions."""
from datetime import datetime
import json
import re
import numpy as np
from PIL import Image
from .backend import Backend
from .policy import TaskBlocked,UserStopped,FightLost,BattleReturned,parse_ratio
from .other_tasks import components
from .workflows import Daily,is_world,create_report,write_report
from .tool_settings import tour_options
from .world_events import is_ambush
from .merchant import is_merchant
from .event_hub import is_event_hub,event_hub_anchors

def tour_rules(s):
    return bool(s.find('^规则$',(580,225,120,65)) and
                s.find('部分关卡需到达一定的探索者等级') and
                s.find('已开启的幻境巡游'))

def is_tour_list(s):
    return bool(s.find('活动时间.*长期',(430,65,440,65)) and
                s.find('巡游进度',(0,610,1280,90)) and not s.find('敌方阵容') and
                not s.find('^规则$|^确定$|^取消$',(280,160,720,430)))

def tour_story(s):
    label=s.find(r'^(\d{1,3})\s*[-—·.].+',(90,495,320,60))
    code=s.find(r'^[A-Z]{2,3}-\d{3}$',(90,455,320,50))
    return int(re.match(r'\d+',label.text)[0]) if label and code else None

def tour_progress(s):
    if tour_story(s) is not None or not s.find('巡游进度',(270,650,180,50)) or s.find('敌方阵容'):return None
    text=s.region_text((290,608,145,55))
    pair=parse_ratio(re.sub(r'(?<=\d)\s*[|\[\]]\s*(?=\d)','/',text))
    return pair if pair and 0<=pair[0]<=pair[1]<=200 else None

def tour_title(s):
    return s.region_text((105,0,230,65)).strip()

def environment_cards(s):
    if not is_tour_list(s):return []
    cards=[]
    for w in s.words:
        if 420<=w.center[1]<=485 and 25<=w.box[0]<=900 and re.fullmatch(r'[\u4e00-\u9fff]{2,8}',w.text):
            x=w.box[0];progress=parse_ratio(s.region_text((max(0,x-15),615,390,60)))
            if progress and 0<=progress[0]<=progress[1]<=200:
                cards.append({'name':w.text,'point':w.center,'progress':progress})
    return sorted(cards,key=lambda row:row['point'][0])

def tour_node(b,s,number):
    """Find the next numbered diamond by shape + local OCR, or its story label."""
    story=s.find(r'(?:^|[◆◇令])\s*'+str(number)+r'\s*[-—·.].+', (90,130,1100,410))
    if story:return story.center,'story'
    channels=np.sort(s.image,axis=2)
    for mask in (channels[:,:,0]>215,(channels[:,:,2]>235)&(channels[:,:,1]>110)):
        mask[:130]=False;mask[540:]=False
        for x,y,right,bottom,area in components(mask):
            width=right-x;height=bottom-y
            if not (65<=width<=115 and 65<=height<=115 and .8<width/height<1.2 and 150<=area<=3500):continue
            cx=(x+right)//2;cy=(y+bottom)//2
            text=b.read_text_region(s,(cx-32,cy-25,65,50),scale=2)
            if text==str(number):return (cx,cy),'battle'
    for w in s.words:
        if w.text==str(number) and 130<w.center[1]<540 and 70<w.center[0]<1210:
            text=b.read_text_region(s,(w.center[0]-32,w.center[1]-25,65,50),scale=2)
            if text==str(number):return w.center,'battle'
    return None

def tour_detail(s):
    if not s.has('敌方阵容','^排阵$','^挑战$','可获得奖励'):return None
    m=re.search(r'^(\d{1,3})\s*[-—·.]\s*(.+)$',s.region_text((20,120,530,65)))
    return (int(m[1]),m[2]) if m else None

def verify_free_tour(b,s,expected):
    b.guard(s)
    identity=tour_detail(s)
    if not identity or identity[0]!=expected:raise TaskBlocked('巡游目标关卡变化，未开始挑战')
    if s.find('需要.*级|等级不足|尚未解锁|未解锁'):
        raise TaskBlocked('巡游关卡尚未解锁')
    if re.search(r'\d|消耗|购买',s.region_text((960,590,275,90))):
        raise TaskBlocked('巡游挑战按钮出现费用，未开始挑战')
    if not b.match_template(s,'tour-free-challenge.png',[955,585,285,90],.9):
        raise TaskBlocked('巡游免费挑战按钮未核实')

class TourPlayer(Daily):
    def __init__(self,b,report,emit=lambda *a:None):
        super().__init__(b,report,emit)
        self.tool_options=tour_options(b.settings);self.limit=self.tool_options['max_battles']
        self.active_task='tour';self.last_team=object()
        self.environment_identity=[]

    def cards(self,s):
        rows=environment_cards(s)
        for row in rows:
            # Adjacent views can OCR one decorative name differently. Compare
            # the card artwork as well so that it is not challenged twice.
            x=row['point'][0]-60
            patch=s.image[190:410,max(0,x+80):min(1280,x+360)]
            if patch.shape[1]!=280 or patch.std()<4:continue
            signature=np.array(Image.fromarray(patch).resize((24,18))).astype('int16')
            matches=[(float(np.abs(signature-old).mean()),name) for name,old in self.environment_identity]
            same=min(matches,default=(float('inf'),None))
            if same[0]<8:row['name']=same[1]
            else:self.environment_identity.append((row['name'],signature))
        return rows

    def stable_list(self):
        previous=None
        for _ in range(10):
            s=self.observe();self.b.guard(s)
            rows=self.cards(s)
            signature=[(r['name'],r['point'][0]) for r in rows]
            if previous and len(previous)==len(signature) and all(a[0]==b[0] and abs(a[1]-b[1])<8 for a,b in zip(previous,signature)):
                return s
            previous=signature;self.b.sleep(.4)
        raise TaskBlocked('环境列表尚在滑动或名称未读清，未点击移动中的卡片')

    def list_page(self):
        for _ in range(8):
            s=self.observe();self.b.guard(s)
            if is_merchant(s):
                self.handle_merchant(s);continue
            if is_ambush(s):
                self.handle_ambush(s);continue
            if tour_rules(s):
                self.b.click_at(s,(933,254),['^规则$','已开启的幻境巡游'],'关闭巡游规则');continue
            if is_tour_list(s):return self.stable_list()
            if tour_story(s) is not None:
                self.story(s,tour_story(s));continue
            if tour_detail(s):
                self.b.click_at(s,(45,28),['敌方阵容','^排阵$'],'返回当前巡游地图');continue
            if tour_progress(s) is not None:
                self.b.click_at(s,(45,28),['巡游进度'],'返回巡游环境列表');continue
            if is_world(s):
                self.report.setdefault('resources_start',self.world_resources(s))
                self.click_world(s,(220,83),'进入丰野间');continue
            if is_event_hub(s):
                self.confirm_event_hub(s)
                w=s.find('[幻石]?境巡游',(750,350,220,100))
                if not w:raise TaskBlocked('丰野间未找到幻境巡游入口')
                self.b.click_at(s,w.center,event_hub_anchors(s),'进入幻境巡游');continue
            self.b.sleep(.5)
        raise TaskBlocked('请从世界地图、丰野间或幻境巡游页面启动此工具')

    def map_page(self):
        for _ in range(8):
            s=self.observe();self.b.guard(s)
            if tour_progress(s) is not None:return s
            if tour_detail(s):self.b.click_at(s,(45,28),['敌方阵容','^排阵$'],'返回当前巡游地图')
            else:self.b.sleep(.5)
        raise TaskBlocked('未回到当前巡游环境，保留现场')

    def open_next(self,s,number):
        # The client keeps the camera after a victory. Story markers provide
        # numbered landmarks; short slow pans avoid inertial overshooting.
        direction=1
        for attempt in range(12):
            if tour_progress(s) is None:raise TaskBlocked('巡游地图未确认')
            node=tour_node(self.b,s,number)
            if node:
                self.b.click_at(s,node[0],['巡游进度'],'打开巡游节点'+str(number))
                for _ in range(6):
                    q=self.observe();self.b.guard(q)
                    if tour_detail(q) or tour_progress(q) is None:return q,node[1]
                    self.b.sleep(.4)
                return q,node[1]
            if attempt==11:break
            markers=[]
            for w in s.words:
                if 130<w.center[1]<540:
                    m=re.search(r'(\d{1,3})\s*[-—·.]',w.text)
                    if m:markers.append(int(m[1]))
            if markers:direction=1 if number>min(markers,key=lambda value:abs(value-number)) else -1
            elif attempt==6:direction*=-1
            self.b.guard(s)
            swipe=(1050,450,650,450) if direction==1 else (350,450,750,450)
            self.b.wait(self.b.controller.post_swipe(*swipe,1400));self.b.sleep(1.5);s=self.observe()
        raise TaskBlocked(f'未找到巡游节点{number}，没有重复点击旧关卡')

    def story(self,s,number):
        # Only explicit story navigation or its known close control is allowed.
        for _ in range(30):
            self.b.guard(s)
            if tour_story(s)==number:
                label=s.find(r'^'+str(number)+r'\s*[-—·.].+',(90,495,320,60))
                self.b.click_at(s,(1140,125),[re.escape(label.text),r'^[A-Z]{2,3}-\d{3}$'],f'关闭巡游剧情{number}')
                self.report.setdefault('stories',[]).append({'stage':number,'title':label.text})
                return self.map_page()
            if tour_progress(s) is not None:return s
            if s.find('等级不足|需要.*级|尚未解锁'):
                raise TaskBlocked('剧情节点尚未解锁')
            if s.find('^跳过$|^下一步$|^继续$|点击.*继续'):
                self.b.click_text(s,'^跳过$|^下一步$|^继续$|点击.*继续')
            elif s.find('^关闭$'):
                self.b.click_text(s,'^关闭$')
            else:
                self.b.save_screen(s,self.report['folder']/f'tour-story-{number}.png')
                raise TaskBlocked(f'巡游剧情{number}未识别关闭方式，保留现场')
            s=self.observe()
        raise TaskBlocked('剧情未结束，停止重复操作')

    def claim_milestones(self,s):
        progress=tour_progress(s)
        if not progress:return s
        for threshold in range(5,min(progress[0],40)+1,5):
            x=488+(threshold//5-1)*75
            icon=s.image[603:643,x-20:x+20].astype('int16')
            blue,green,red=(icon[:,:,i] for i in range(3))
            # Already claimed rewards are a bright green tick.
            if ((green>140)&(green>red*1.2)&(green>blue*1.4)).mean()>.12:continue
            self.b.click_at(s,(x,625),['巡游进度'],f'查看巡游{threshold}进度奖励')
            q=self.observe();self.b.guard(q)
            if q.find('^领取$|^领取奖励$') and q.find('奖励'):
                self.b.click_text(q,'^领取$|^领取奖励$');q=self.observe()
            if q.find('获得奖励|获得物品'):
                self.b.save_screen(q,self.report['folder']/f'tour-reward-{len(self.report.get("tour_rewards",[]))}.png')
                self.report.setdefault('tour_rewards',[]).append({'threshold':threshold,'texts':q.text})
                self.b.click_at(q,(640,690),['获得奖励|获得物品'],'关闭巡游免费奖励');q=self.observe()
            if tour_progress(q) is None:raise TaskBlocked('巡游进度奖励未返回地图，保留现场')
            s=q
        return s

    def environment(self,card):
        row={'name':card['name'],'start':card['progress'][0],'end':card['progress'][0],'battles':0,'wins':0}
        self.report.setdefault('environments',[]).append(row)
        self.note('幻境巡游：'+card['name']+f' {card["progress"][0]}/{card["progress"][1]}')
        s=self.stable_list()
        current=next((c for c in self.cards(s) if c['name']==card['name']),None)
        if not current:raise TaskBlocked('环境卡片移动，未点击旧坐标')
        self.b.click_at(s,current['point'],['活动时间.*长期','巡游进度'],'进入环境：'+card['name'])
        s=self.map_page();s=self.claim_milestones(s)
        while True:
            progress=tour_progress(s)
            if progress is None:raise TaskBlocked('巡游进度未读清')
            row['end']=progress[0]
            if progress[0]>=progress[1]:row['reason']='已全部通关';break
            if self.battles>=self.limit:row['reason']='达到挑战上限';break
            number=progress[0]+1;detail,kind=self.open_next(s,number)
            if kind=='story':
                s=self.story(detail,number)
            elif tour_detail(detail):
                won=False;unknown_result=False
                for team in self.tool_options['teams'] or [None]:
                    if self.battles>=self.limit:break
                    if team!=self.last_team:
                        detail=self.select_team(detail,team);self.last_team=team
                    verify_free_tour(self.b,detail,number)
                    self.note(f'{card["name"]}第{number}关 · '+(f'队伍{team}' if team else '当前阵容'))
                    self.start_challenge('tour',detail,'幻境巡游免费',lambda q:verify_free_tour(self.b,q,number));row['battles']+=1
                    try:result=self.battle('幻境巡游免费');outcome='victory'
                    except FightLost as lost:result=lost.screen;outcome='failed'
                    except BattleReturned as returned:result=returned.screen;outcome='unobserved';unknown_result=True
                    self.report.setdefault('team_attempts',[]).append({'task':'tour','environment':card['name'],'stage':number,'team':team,'outcome':outcome})
                    if outcome=='victory':row['wins']+=1
                    self.exit_result(result);s=self.map_page()
                    if outcome=='victory':won=True;break
                    progress=tour_progress(s)
                    if outcome=='unobserved' and progress and progress[0]>=number:won=True;break
                    if team!=(self.tool_options['teams'] or [None])[-1] and self.battles<self.limit:
                        detail,_=self.open_next(s,number)
                if not won:
                    row['reason']='达到挑战上限' if self.battles>=self.limit else f'第{number}关胜败未观察到，当前进度未推进' if unknown_result else f'第{number}关全部阵容未通过'
                    self.note(card['name']+'：'+row['reason']);break
            else:
                self.b.save_screen(detail,self.report['folder']/f'tour-node-{number}.png')
                if detail.find('等级不足|需要.*级|尚未解锁'):
                    row['reason']=f'第{number}关等级限制';break
                raise TaskBlocked(f'巡游节点{number}没有打开预期关卡或剧情')
            after=tour_progress(s)
            if after is None or after[0]!=number:raise TaskBlocked('巡游结束后进度未增加，未重复挑战')
            row['end']=after[0];self.note(f'{card["name"]}已推进到{after[0]}/{after[1]}')
            s=self.claim_milestones(s);self.checkpoint()
        return self.list_page()

    def play(self):
        s=self.list_page();seen=set();unchanged=0;pages=0
        # Always start at the left boundary, including launches from a saved right page.
        for _ in range(60):
            before=[(r['name'],r['point'][0]) for r in self.cards(s)]
            self.b.guard(s);self.b.wait(self.b.controller.post_swipe(350,350,750,350,1400));s=self.stable_list()
            if not is_tour_list(s):raise TaskBlocked('环境列表滑动后页面改变')
            after=[(r['name'],r['point'][0]) for r in self.cards(s)]
            if before and len(before)==len(after) and all(a[0]==b[0] and abs(a[1]-b[1])<8 for a,b in zip(before,after)):break
        else:raise TaskBlocked('未确认环境列表起点')
        while pages<60:
            cards=self.cards(s)
            if not cards:raise TaskBlocked('环境名称或进度未读清')
            pending=[c for c in cards if c['name'] not in seen]
            if pending:
                card=pending[0];seen.add(card['name'])
                try:s=self.environment(card)  # Complete maps can still have unclaimed rewards.
                except TaskBlocked as error:
                    # Recover only from a recognised tour page. An unknown
                    # dialog or a battle is left intact for inspection.
                    q=self.observe();self.b.guard(q)
                    if not (is_tour_list(q) or tour_progress(q) is not None or tour_detail(q)):raise
                    row=self.report['environments'][-1];row['reason']=str(error)
                    progress=tour_progress(q)
                    if progress:row['end']=progress[0]
                    self.report.setdefault('incomplete_environments',[]).append(card['name'])
                    self.note(card['name']+'暂时跳过：'+str(error));s=self.list_page()
                if self.battles>=self.limit:
                    self.report['all_environments_checked']=False
                    return f'已挑战{self.battles}次，达到设置上限，剩余环境留待下次'
                continue
            before=[(r['name'],r['point'][0]) for r in cards]
            self.b.guard(s);self.b.wait(self.b.controller.post_swipe(1050,350,650,350,1400));s=self.stable_list();pages+=1
            if not is_tour_list(s):raise TaskBlocked('切换环境后页面改变')
            after=[(r['name'],r['point'][0]) for r in self.cards(s)]
            same=len(before)==len(after) and all(a[0]==b[0] and abs(a[1]-b[1])<8 for a,b in zip(before,after))
            unchanged=unchanged+1 if same else 0
            if unchanged>=2:
                self.report['all_environments_checked']=True
                summary=f'已遍历{len(seen)}个环境，挑战{self.battles}次，胜利{sum(r.get("wins",0) for r in self.report["environments"])}次'
                skipped=self.report.get('incomplete_environments',[])
                return summary+('；需检查：'+'、'.join(skipped) if skipped else '')
        raise TaskBlocked('环境列表遍历达到检查上限，未声称全部完成')

    def restore(self):
        s=self.list_page();self.b.click_at(s,(45,28),['活动时间.*长期','巡游进度'],'返回丰野间')
        s=self.await_event_hub()
        self.home(s)
        self.report['resources_end']=self.world_resources(self.home())

def run_tour(settings,stop,log=print,emit=lambda *a:None):
    tour_options(settings);report=create_report();report.update(tool='tour',diamond_spend=0)
    def audit(action):
        with (report['folder']/'actions.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps({'time':datetime.now().astimezone().isoformat(),**action},ensure_ascii=False)+'\n')
    b=Backend(settings,stop,log,lambda m:emit('phase',m),audit,recover_gold_details=True)
    player=TourPlayer(b,report,emit)
    try:
        b.connect();emit('phase','幻境巡游运行中');report['reason']=player.play()
        report['status']='completed' if report.get('all_environments_checked') and not report.get('incomplete_environments') else 'partial'
        player.restore();player.note(report['reason'])
    except UserStopped as e:report.update(status='stopped',reason=str(e))
    except Exception as e:report.update(status='blocked',reason=str(e));player.note('已停止：'+str(e))
    finally:
        if getattr(player,'last_screen',None) is not None:b.save_screen(player.last_screen,report['folder']/'tour-final.png')
        report['finished']=datetime.now().astimezone().isoformat();write_report(report)
    return report
