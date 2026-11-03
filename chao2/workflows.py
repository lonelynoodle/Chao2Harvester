"""State-aware daily routines. All coordinates are normalized to 1280x720.

Every input requires a fresh recognition and a known page. Battle entry is
separate from settlement; a successful click never counts as a successful run.
"""
from __future__ import annotations
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from .backend import Backend, Screen, Word, ROOT
from .policy import SafetyStop, PageChanged, UserStopped, TaskBlocked, FightLost, EncounterInterrupted, parse_ratio, can_claim_stamina, friend_allowed
from .configuration import normalize_settings,normalize_selected,plan_tasks,STAMINA_TASKS,SPECS,team_order,selected_rows,limit_reached,run_team_plan,COCOON_CARDS
from .activities import ConfiguredActivities,BudgetReached,is_exploration_rewards,is_tribe_detail,is_tribe_map,is_giant_ready,is_main_detail,enemy_formation,recover_main_detail
from .daily_challenges import DailyChallenges,origin_is_open,pvp_result,pvp_settle_button,origin_resume_state,rank_change_notice
from .report_history import prune_reports,reserve_report
from .overview import OverviewNavigation,OVERVIEW_ROUTES,overview_matches
from .other_tasks import OtherTasks,is_friend_profile,friend_delete_confirmation
from .activity_rewards import ActivityRewards
from .trigger_events import TriggerEvents,rift_invitation,triggered_event
from .task_reporting import TaskReporting,PRIMARY_RESOURCES
from .world_events import WorldEvents,is_ambush,ambush_identity,is_map_choice
from .merchant import is_merchant,merchant_title
from .rift import RiftActivity,is_rift_map,rift_detail,is_rift_victory,recover_rift_detail
from .forest import ForestActivity,is_forest_map
from .reward_collection import RewardCollection,echo_story_kind,is_map_story,task_claim_slot
from .anomalies import AnomalyActivities,is_sage_offer,is_sage_dialog
from .stamina_inventory import StaminaInventory
from .wild_capture import WildCapture,is_wild_offer,is_wild_capture,is_wild_list
from .free_summon import FreeSummon,is_summon_page
from .task_queue import TaskQueueExecution,execution_entries
from .event_hub import EventHubNavigation,is_event_hub
from .navigation_retry import NavigationRecovery
from .monster_boxes import MonsterBoxInventory,BOX_TITLE,monster_box_result_name
from .transient_popups import TransientPopups,is_star_gift
from .triad import TriadActivities,is_triad_lobby
from .battle_takeover import BattleTakeover,takeover_phase
from .celebration import CelebrationActivities
from .tribe_rewards import TribeOccupationRewards
from .tribe_chests import TribeChestRewards
from .page_recovery import PageRecovery,exit_game_dialog
from .challenge_start import ChallengeStartRecovery
from .result_navigation import ResultNavigation
from .team_copy import is_saved_team_list,saved_team_anchors
from .team_switch import suppression_team_switch_dialog
from .file_io import atomic_json
from .piggy_bank import PiggyBank
from .plane_gate import plane_gate_window

TASKS = {
    'startup':('开始唤醒','点击进入游戏；已有战斗先等结算，再继续所选任务'),
    'exploration':('探索','全部领取并开始探索，必要时一键指派怪兽'),
    'copies':('异象','复制体挑战与游荡智者答题领奖，可分别开启'),
    'hunt':('狩猎','搜索前备足整批30体力，按设置先领三发或使用药水；限时猎物连续挑战完毕'),
    'main':('主线关卡','按阵容顺序闯关；全部失败后换关卡'),
    'tower':('浮空巨塔','连续挑战下一关；当前塔层失败后先挑战该塔秘庭，再前往下一座塔。羽毛由所有塔共用'),
    'cocoon':('永生之茧','按添加的副本、优先级及次数挑战'),
    'tribe':('部落冒险','优先冒险关卡，可在无关卡时随机挑战图腾，保留指定战令'),
    'rift':('凿星裂痕','优先最高关，打不了回退前一关；胜利后使用库存钥匙开箱'),
    'forest':('黑暗森林','探索当前森林并挑战已开放怪兽，计时或点数用尽仍处理免费挑战，不重置'),
    'origin':('起源殿','北京时间20:00–22:00使用所选队伍，消耗免费挑战次数'),
    'arena':('斗技场','按所选战力策略寻敌，最多刷新3次后选当前低于己方的最高战力对手，消耗免费次数'),
    'nest':('谜之巢穴','当天尚未挑战时完成一次暴走旷野'),
    'giant':('进击巨物','开放时按所选阵容分别挑战并核对伤害结算'),
    'triad':('三阵入局','丰野间消耗当日免费匹配次数，每场最多三回合，可自动点击结算'),
    'celebration':('庆典活动','丰野间的三阵入局、进击巨物及拼二每日；未开放的活动自动跳过'),
    'rewards':('任务领奖','领取星律、任务挑战与世界回响四项免费奖励'),
    'other':('其他任务','好友管理、免费奖励、背包整理、野生怪兽捕捉与深渊先遣'),
    'finish':('结束关闭','完成并保存记录后，关闭超二收菜和MuMu'),
}
ORDER = ['startup','exploration','copies','hunt','main','tower','cocoon','tribe','rift','forest','origin','arena','nest','celebration','rewards','other','finish']

WORLD_ANCHORS = (
    (r'^(?:任?务)?挑战$', (1160,20,120,70)),
    (r'^世?界回响$', (1160,105,120,75)),
    (r'^事件$', (1100,590,90,100)),
    (r'^[领须]地$', (1180,590,100,100)),
)

def world_anchors(s):
    # Keep the expected HUD positions: dungeon titles and text behind overlays
    # are not sufficient evidence that map navigation is available.
    return [w for pattern,roi in WORLD_ANCHORS if (w:=s.find(pattern,roi))]

def world_overlay_present(s):
    if suppression_team_switch_dialog(s):return True
    if exit_game_dialog(s):return True
    if plane_gate_window(s):return True
    if is_saved_team_list(s):return True
    if rift_invitation(s):return True
    if is_star_gift(s) or friend_delete_confirmation(s):return True
    if enemy_formation(s):return True
    if rank_change_notice(s):return True
    if is_map_story(s) or echo_story_kind(s):return True
    if is_level_up(s):return True
    if is_wild_offer(s) or is_wild_capture(s):return True
    if ambush_identity(s) or is_map_choice(s) or merchant_title(s):return True
    if is_exploration_rewards(s):return True
    if is_sage_offer(s) or is_sage_dialog(s):return True
    if s.find('^好友$|^社交$|^背包$',(95,0,150,65)):return True
    if s.find('选择挑战的塔|^玩法概览$|^每日三发$|^领取$|^获得.*|本周已获[取得]友好点数|^敌方阵容$|^配置$|^主要获得途径$|剩余可指派怪兽|种族限定'):
        return True
    if s.find('^世界$',(1150,620,130,100)) or s.find('^传送$'):
        return True
    return False


def world_resources_visible(s):
    icon=s.image[10:45,187:222]
    blue=((icon[:,:,0]>125)&(icon[:,:,1]>105)&(icon[:,:,2]<110)).mean()>.10
    return parse_ratio(s.region_text((490,0,170,65))) is not None or blue


def is_world(s):
    return not world_overlay_present(s) and len(world_anchors(s))>=2 and world_resources_visible(s)
def is_tasks(s): return s.has('^玩法概览$','^每日挑战$')

def is_level_up(s):
    return bool(s.find('^探索者等级$',(670,195,240,65)) and
                s.find('^怪兽等级上限$',(670,255,260,65)) and
                s.find('^点击空白位置关闭$',(460,575,380,80)))

START_BUTTON = r'^进入游戏$'
START_BUTTON_ROI = (390,520,500,160)
def is_start_screen(s): return bool(s.find(START_BUTTON,START_BUTTON_ROI))
def is_reward(s): return s.has('^获得.*|^奖励$') and not s.find('^挑战$')
def is_failure(s):
    return pvp_result(s)=='failed' or bool(s.find('^退出$') and (s.find('战斗失败|挑战失败|失败|败退') or
                s.has('^重新挑战$','通过下列方式提高战力') or
                # The ornate defeat title is often unreadable to OCR.  The
                # settlement's advice banner and these two distinct actions
                # still identify the same failure screen reliably.
                s.has('通过下列方式提高战力','^元核升级$','^阵容调整$') or
                (s.has('^狩猎积分$','^元核升级$','^阵容调整$') and not s.find('获得奖励'))))

from .star_shop import StarShop
from .tribe_totems import totem_score

class Daily(PiggyBank,TriggerEvents,TransientPopups,TaskQueueExecution,NavigationRecovery,PageRecovery,BattleTakeover,ChallengeStartRecovery,ResultNavigation,EventHubNavigation,OverviewNavigation,ConfiguredActivities,AnomalyActivities,DailyChallenges,TriadActivities,CelebrationActivities,TribeOccupationRewards,TribeChestRewards,OtherTasks,StarShop,ActivityRewards,MonsterBoxInventory,RewardCollection,TaskReporting,WorldEvents,RiftActivity,ForestActivity,StaminaInventory,WildCapture,FreeSummon):
    def __init__(self,b:Backend,report,emit=lambda *a:None):
        self.b=b;self.report=report;self.emit=emit
        b.settings=normalize_settings(b.settings)
        self.options=b.settings['task_options'];self.task_counts={};self.active_task=None;self.selected=[]
        # Daily tasks stop at their own resource/attempt rules. Dedicated tools
        # may override this internal bound; old global max_battles is retired.
        self.battles=0;self.limit=float('inf')
        self.start_time=time.monotonic();self.initial_team=None
        self.own_copy_waiting=False
        self.main_positions={}
        self.main_views={}
        self.search_counts={}
        self.stamina_retry={}
        self.state_file=ROOT/'config'/'daily-state.json'
        self.state=json.loads(self.state_file.read_text('utf-8')) if self.state_file.exists() else {}
        self.date=datetime.now().astimezone().strftime('%Y-%m-%d')
        self.day=self.state.setdefault(self.date,{})
    def note(self,msg):
        self.b.log(msg);self.report['events'].append({'time':datetime.now().isoformat(timespec='seconds'),'message':msg})
    def checkpoint(self):
        if self.report.get('folder'):write_report(self.report)
    def observe(self,name=None,*,dismiss_popups=True):
        if time.monotonic()-self.start_time>int(self.b.settings.get('max_run_minutes',90))*60:raise SafetyStop('已达到本轮运行时长上限')
        path=self.report['folder']/((name or 'latest')+'.png')
        original=self.b.observe(path);s=self.dismiss_level_up(original) if dismiss_popups else original
        if dismiss_popups:s=self.dismiss_triggered_popups(s)
        s=self.calibrate_collection_reward(s)
        s=self.recover_world_navigation(s)
        s=recover_main_detail(self.b,s)
        s=recover_rift_detail(self.b,s)
        tribe_visible=is_tribe_map(s)
        if tribe_visible and not getattr(self,'_tribe_map_visible',False):
            self._tribe_map_session=getattr(self,'_tribe_map_session',0)+1
        self._tribe_map_visible=tribe_visible
        if s is not original:self.b.save_screen(s,path)
        self.last_screen=s;self.emit('preview',str(path))
        if is_world(s):
            # Do not send another OCR/input on failure just to refresh the footer.
            ratio=parse_ratio(s.region_text((490,0,170,65)))
            diamonds=s.region_text((250,0,75,60))
            if ratio:
                resources={'stamina':ratio[0],'stamina_cap':ratio[1],
                    'diamonds':int(diamonds) if diamonds.isdigit() else None,
                    'gold_text':s.region_text((370,0,100,55))}
                self.report['resources_last_observed']=resources
                self.report['resources_observed_at']=datetime.now().isoformat(timespec='seconds')
                self.reconcile_main_resource(ratio[0])
                if self.active_task in STAMINA_TASKS:self.resource_balance(self.active_task,'地图体力',ratio[0])
                self.emit('resources',resources)
        return s

    def dismiss_level_up(self,s):
        if not is_level_up(s):return s
        self.b.guard(s)
        number=len(self.report.setdefault('level_ups',[]))+1
        self.b.save_screen(s,self.report['folder']/f'level-up-{number}.png')
        row={'from':s.region_text((975,200,80,60)),
             'to':s.region_text((1095,200,95,60)),'status':'observed'}
        self.report['level_ups'].append(row)
        self.note('检测到探索者升级，关闭提示后继续当前任务')
        self.b.click_at(s,(640,650),['^探索者等级$','^怪兽等级上限$','^点击空白位置关闭$'],'关闭探索者升级提示')
        # A level-up may cover either rewards or the original page. One close
        # click only; wait for it to leave before issuing any further input.
        for _ in range(6):
            q=self.b.observe();self.b.guard(q)
            if not is_level_up(q):
                row['status']='closed';self.checkpoint();return q
            self.b.sleep(.5)
        raise TaskBlocked('升级提示关闭后仍未消失，未重复领取奖励')

    def recover_world_navigation(self,s):
        # Only reconsider a plausible unobstructed map. Re-read actual pixels
        # instead of adding an ever-wider fuzzy pattern for the side labels.
        if is_world(s) or world_overlay_present(s) or not world_resources_visible(s) or not world_anchors(s):return s
        self.b.guard(s)
        for label,roi in (('事件',(1070,628,75,40)),('领地',(1196,628,78,40)),
                          ('任务挑战',(1190,37,88,34)),('世界回响',(1190,130,90,37))):
            if s.find('^'+label+'$',roi):continue
            text=self.b.read_text_crop(s,roi)
            if text!=label and self.b.tasker is not None:text=self.b.read_text_region(s,roi,3).strip()
            if text!=label:continue
            s=Screen(s.image,[*s.words,Word(text,list(roi),.99)],s.when)
            if is_world(s):
                if not getattr(self,'_world_recovery_reported',False):
                    self.note('世界地图导航文字漏读，已通过局部识别确认'+label)
                    self._world_recovery_reported=True
                return s
        return s

    def click_world(self,s,point,reason):
        s=self.recover_world_navigation(s)
        self.b.guard(s)
        if not is_world(s):raise TaskBlocked('世界地图未确认：'+reason)
        self.b.click_at(s,point,['^'+re.escape(w.text)+'$' for w in world_anchors(s)],reason)
    def await_page(self,*patterns,roi=None,timeout=12):
        return self.wait_for_screen(lambda s:all(s.find(p,roi) for p in patterns),
                                    '等待页面：'+'、'.join(patterns),timeout=timeout)
    def save_state(self):
        self.state_file.parent.mkdir(exist_ok=True)
        atomic_json(self.state_file,self.state)
    def home(self,screen=None,*,wait_unknown=True):
        for attempt in range(4):
            try:return self._home_once(screen,wait_unknown=wait_unknown)
            except PageChanged as error:
                if attempt==3:raise TaskBlocked('返回过程中页面持续变化，已重新识别3次，保留现场') from error
                self.navigation_retry('返回按钮已随页面变化，重新识别当前页面',attempt+1,error.screen)
                screen=None

    def _home_once(self,screen=None,*,wait_unknown=True):
        from .other_tasks import is_channel_account_panel
        from .abyss import is_abyss_menu,is_abyss_affixes,AFFIX_ANCHORS
        unknown=0
        back_steps=0
        switch_cancel_attempts=0
        for _ in range(64):
            s=screen if screen is not None else self.observe();screen=None
            s=self.dismiss_level_up(s)
            s=self.dismiss_triggered_popups(s)
            s=self.recover_world_navigation(s);self.b.guard(s)
            if suppression_team_switch_dialog(s):
                if switch_cancel_attempts>=3:raise TaskBlocked('取消队伍回切提示未生效，保留现场')
                self.b.click_text(s,'^取消$',roi=(350,450,270,85))
                switch_cancel_attempts+=1
                self.note('取消遗留的队伍回切提示，保留当前队伍和深渊压制')
                continue
            if exit_game_dialog(s):
                self.b.click_at(s,s.find('^再玩一会$').center,['^是否确认退出游戏$','^再玩一会$'],'取消退出游戏，继续返回')
                continue
            if takeover_phase(s):
                screen=self.finish_existing_battle(s);continue
            pending=self.day.get('star_evolution_pending')
            if pending:
                from .star_supply import evolution_result_name,purple_monster_info
                if (evolution_result_name(self.b,s)==pending['name'] or
                        (pending.get('reveal_seen') and purple_monster_info(self.b,s))):
                    screen=self.complete_star_evolution(s);continue
            if is_channel_account_panel(s):
                screen=self.close_channel_account_panel(s);continue
            receipt=monster_box_result_name(s)
            if receipt:
                self.note('检测到遗留的'+receipt+'获得展示，关闭后继续核对当前任务；不重复开茧')
                screen=self.close_monster_box_result(s,receipt,return_to_bag=False);continue
            from .star_shop import donation_page
            if donation_page(s):
                self.b.click_at(s,(43,28),['^支配核心$'],'退出支配核心');continue
            if rank_change_notice(s):
                screen=self.dismiss_rank_change(s);continue
            if is_merchant(s):
                screen=self.handle_merchant(s);continue
            if is_ambush(s):
                self.handle_ambush(s);continue
            if plane_gate_window(s):
                screen=self.close_plane_gate(s);continue
            if is_map_choice(s):
                screen=self.close_map_choice(s);continue
            if is_summon_page(s):
                self.b.click_at(s,(43,28),['^[造召]唤台$','^卡池详情$'],'退出造唤台');continue
            if is_wild_offer(s) or is_wild_capture(s):
                if getattr(self,'wild_daily_active',False) and self.wild_allowed() and not getattr(self,'_handling_wild',False):
                    return self.maybe_capture_wild(s,encounter=True)
                screen=self.close_wild(s);continue
            if is_wild_list(s):
                screen=self.close_wild(s);continue
            if rift_detail(s) is not None:
                self.b.click_at(s,(43,28),[r'^\d+\s*[-－—]\s*[凿幽]星裂痕关卡\s*\d+$','^排阵$'],'返回裂痕地图');continue
            if is_rift_map(s):
                self.b.click_at(s,(43,28),['^[凿幽]星裂痕$'],'返回裂痕上级');continue
            if is_forest_map(s):
                self.b.click_at(s,(45,28),['^黑暗森林$','^信息$'],'返回森林上级');continue
            if is_exploration_rewards(s):
                screen=self.close_exploration_rewards(s);continue
            if friend_delete_confirmation(s):
                self.b.click_text(s,'^取消$',roi=(350,380,290,190))
                self.note('已取消上次遗留的删除好友确认，继续返回原任务');continue
            if is_friend_profile(s):
                self.b.click_at(s,(1082,121),['^助战怪兽$'],'关闭好友资料');continue
            if is_sage_offer(s):
                self.b.click_at(s,(928,130),['^游荡智者$','^前往$'],'关闭游荡智者介绍');continue
            if is_sage_dialog(s) and not s.find('^获得奖励$'):
                screen=self.resume_sage_dialog(s)
                if screen is not None:continue
                raise TaskBlocked('游荡智者答题尚未结束，保留题目与选项，请完成后继续')
            if is_map_story(s):
                screen=self.close_map_story(s);continue
            if s.find(BOX_TITLE,(80,0,210,65)):
                self.b.click_at(s,(43,28),[BOX_TITLE],'退出幻化怪兽茧选择');continue
            if echo_story_kind(s):
                screen=self.close_echo_story(s);continue
            if s.find('^获得奖励$',roi=(400,70,500,160)) and s.find('点击空白位置关闭'):
                self.b.click_at(s,(640,660),['^获得奖励$','点击空白位置关闭'],'关闭免费奖励弹层');continue
            if is_world(s):
                return self.maybe_capture_wild(s) if getattr(self,'wild_daily_active',False) else s
            if s.has('主要获得途径','已拥有'):
                self.b.click_at(s,(640,650),['主要获得途径','已拥有'],'关闭资源说明');continue
            if is_saved_team_list(s):
                self.b.click_at(s,(960,54),saved_team_anchors(s),'关闭复制配置');continue
            formation=s.find('^排阵$|^部队$',roi=(45,0,230,65))
            if formation:
                self.b.click_at(s,(45,28),['^'+formation.text+'$'],'退出排阵');continue
            if s.has('探索者账号','^退出账号$'):
                self.b.click_at(s,(1230,75),['探索者账号','^退出账号$'],'关闭个人资料');continue
            if (heading:=enemy_formation(s)) and (s.find('可获得奖励') or s.find('前往挑战')):
                self.b.click_at(s,(45,28),['^'+re.escape(heading.text)+'$'],'关闭怪兽挑战详情');continue
            if s.has('敌方阵容','首通奖励'):
                self.b.click_at(s,(45,28),['敌方阵容','首通奖励'],'关闭关卡详情');continue
            if is_main_detail(s):
                self.b.click_at(s,(45,28),['^敌方阵容$','^排阵$','^(?:前往)?挑战$'],'关闭已通主线关卡详情');continue
            if is_tribe_detail(s):
                self.b.click_at(s,(45,28),['^'+enemy_formation(s).text+'$','通关奖励.*拍卖.*共享奖励|^每次挑战奖励$'],'关闭部落冒险详情');continue
            if s.has('^传送$','^狩猎$') and s.find('^狩猎$',roi=(900,0,230,65)):
                self.b.click_at(s,(770,680),['^传送$','^狩猎$'],'收起狩猎列表');continue
            if s.has('^进击巨物$','^开始挑战$'):
                self.b.click_at(s,(45,28),['^进击巨物$','^开始挑战$'],'返回丰野间');continue
            if is_giant_ready(s):
                self.b.click_at(s,(45,28),['^进击巨物$','^前往挑战$'],'关闭巨物备战页');continue
            if is_triad_lobby(s):
                self.b.click_at(s,(45,28),['^三阵入局$'],'退出三阵入局');continue
            if is_event_hub(s):
                screen=self.close_event_hub(s);continue
            if s.has('^小游戏$','^拼二大作战$','^重开$') and not s.find('^规则$'):
                self.b.click_at(s,(45,28),['^小游戏$','^拼二大作战$'],'返回丰野间');continue
            if s.find('本周已获[取得]友好点数') and s.find('^异象$'):
                self.b.click_at(s,(770,680),['本周已获[取得]友好点数','^异象$'],'收起异象列表');continue
            if is_abyss_affixes(s):
                self.b.click_at(s,(1188,53),AFFIX_ANCHORS,'关闭深渊先遣压制词缀');continue
            if is_abyss_menu(s):
                self.b.click_at(s,(770,680),['^深渊先遣$','^压制词缀$','每周二.*刷新'],'收起深渊先遣列表');continue
            if s.find('种族限定') and s.find('可获得奖励'):
                self.b.click_at(s,(1154,106),['种族限定','可获得奖励'],'关闭探索详情');continue
            if s.find('^探索$',roi=(900,0,210,70)) and s.find('剩余可指派怪兽'):
                self.b.click_at(s,(770,680),['^探索$','剩余可指派怪兽'],'收起探索列表');continue
            if is_start_screen(s):
                raise TaskBlocked('当前在开始界面，请勾选“开始唤醒”后重试')
            if is_tasks(s):
                self.b.click_at(s,(1238,50),['玩法概览','每日挑战'],'关闭任务');continue
            if s.has('^星律$','^收获$') or s.has('^星律$','^超跃$'):
                self.b.click_at(s,(45,28),['^星律$'],'返回世界');continue
            if s.find('选择挑战的塔'):
                self.b.click_at(s,(640,680),['选择挑战的塔'],'关闭塔选择');continue
            if s.has('^怪兽数量$','^品质$'):
                self.b.click_at(s,(1228,106),['^怪兽数量$','^品质$'],'关闭怪兽列表');continue
            monster_header=s.find('^怪兽信息$|^进化$',roi=(90,0,230,60))
            if monster_header:
                self.b.click_at(s,(43,28),['^'+re.escape(monster_header.text)+'$'],
                                '返回怪兽信息上级');continue
            if is_tribe_map(s):s=self.claim_tribe_occupation(s)
            if s.find('^世界$',roi=(1150,620,130,100)) and s.find('永生|浮空|黑暗|斗技|领地'):
                self.b.click_text(s,'^世界$');continue
            header=s.find('^浮空巨塔$|^永生之茧$|^每日三发$|^活动$|^异象$|^狩猎$|^世界回响$|^世界丰碑$|^遗落回响$|^超星洪流$|^微光笔记$|^宝藏$|^部落冒险$|^部落$|^联结共鸣$|^[谜迷]之巢穴$|^斗技场(?:挑战)?$|^起源殿$|^好友$|^社交$|^背包$|^饲星坛$|^商店$',roi=(80,0,450,70))
            if header:
                # Registered non-combat subpages all share the top-left back button.
                anchor=header.text
                self.b.click_at(s,(43,28),[re.escape(anchor)],'返回上级');continue
            if s.find('^退出$') and s.find('再次挑战|下一层|下一关|下一只|挑战下位'):
                screen=self.exit_result(s);continue
            if s.find('^退出$') and is_failure(s):
                screen=self.exit_result(s);continue
            if s.has('^退出$','^获得奖励$') and s.find('胜利',(0,160,540,390)):
                screen=self.exit_result(s);continue
            if s.has('^退出$','本场击破数','本场金币奖励'):
                screen=self.exit_result(s);continue
            if not wait_unknown:return None
            unknown+=1
            if unknown>=3 and self.b.tasker is not None and self.b.controller is not None:
                if back_steps>=12:raise TaskBlocked('已逐级返回12次，仍未识别可恢复页面')
                back_steps+=1
                self.note(f'当前页面未识别，执行第{back_steps}次返回并重新取图')
                self.report.setdefault('page_backtracks',[]).append({'task':self.active_task,'step':back_steps})
                self.b.back(s,'页面识别失败，逐级退回可识别页面');unknown=0;continue
            if unknown in (3,6,9):
                self.navigation_retry('当前页面暂未识别，重新截图识别',unknown//3,s)
            if unknown<12:
                self.b.sleep(2);continue
            raise TaskBlocked('当前页面未配置返回规则，已重新识别3次；请停在世界地图后重试')
        raise TaskBlocked('返回世界失败，已停止当前任务')
    def startup(self):
        clicked=False;until=time.monotonic()+60
        while time.monotonic()<until:
            s=self.observe();self.b.guard(s)
            if is_world(s):
                self.report['startup_entered']=clicked
                return '已点击进入游戏并确认世界地图加载完成' if clicked else '已在游戏内，跳过进入游戏'
            if is_start_screen(s):
                if not clicked:
                    self.b.click_text(s,START_BUTTON,roi=START_BUTTON_ROI)
                    clicked=True;self.note('已点击进入游戏，等待世界地图加载')
                # One verified click only. The login animation can retain the button.
            elif self.home(s,wait_unknown=False) is not None:
                self.report['startup_entered']=clicked
                return '进入游戏已完成并返回世界' if clicked else '已在游戏内，跳过进入游戏'
            self.b.sleep(1)
        raise TaskBlocked('开始唤醒未在60秒内进入世界，请检查游戏当前页面')
    def world_resources(self,s):
        ratio=parse_ratio(s.region_text((500,0,130,65)))
        if ratio is None:ratio=parse_ratio(self.b.read_text_crop(s,(508,5,92,43)))
        diamonds=s.region_text((250,0,75,60))
        return {'stamina':ratio[0] if ratio else None,'stamina_cap':ratio[1] if ratio else None,'diamonds':int(diamonds) if diamonds.isdigit() else None,'gold_text':s.region_text((370,0,100,55))}
    def task_panel(self,tab='玩法概览'):
        ready=getattr(self,'_overview_ready',None);self._overview_ready=None
        if tab=='玩法概览' and ready in OVERVIEW_ROUTES:
            s=self.observe();self.b.guard(s)
            if is_tasks(s) and overview_matches(s,{ready:OVERVIEW_ROUTES[ready][0]}):return s
        s=self.open_world_page((1234,54),'打开任务挑战','^玩法概览$','^每日挑战$')
        if not is_tasks(s):raise TaskBlocked('任务挑战面板未打开')
        if not s.find('^'+tab+'$'):raise TaskBlocked('任务标签未找到')
        self.b.click_text(s,'^'+tab+'$');return self.observe()
    def territory(self):
        s=self.open_world_page((1230,625),'进入领地','^世界$','永生|浮空|黑暗|领地|斗技')
        if not s.find('永生|浮空|黑暗|领地|斗技'):raise TaskBlocked('未识别领地')
        return s

    def open_world_page(self,point,reason,*anchors):
        s=self.home()
        for attempt in range(4):
            offers=len(self.report.get('dismissed_offers',[]))
            self.click_world(s,point,reason)
            s=self.observe()
            if s.has(*anchors):return s
            # An unsolicited offer can consume the original navigation click.
            # Retry the entrance only after the offer closed onto a fresh map.
            if len(self.report.get('dismissed_offers',[]))>offers and is_world(s) and attempt<3:
                self.navigation_retry('礼包已退出，重新'+reason,attempt+1,s);continue
            def retry(q):
                if is_world(q):self.click_world(q,point,'重新'+reason)
            return self.wait_for_screen(lambda q:q.has(*anchors),'等待页面：'+'、'.join(anchors),retry_navigation=retry)
        raise TaskBlocked(reason+'未完成，未重复操作未知页面')
    def collect_idle(self):
        s=self.home();self.report.setdefault('resources_start',self.world_resources(s))
        self.click_world(s,(40,620),'星律')
        s=self.observe()
        if not s.has('^星律$','^收获$'):raise TaskBlocked('未找到星律收获按钮')
        self.b.click_text(s,'^收获$')
        s=self.observe('idle-reward');self.note('已点击免费星律收获，核对收获后页面')
        # The reward screen has no confirm/purchase action; a tap outside it closes it.
        if not is_world(s) and (s.find('^获得奖励$',roi=(400,70,500,160)) or not s.find('^星律$')):
            if not s.find('获得|金币|经验|建材'):raise TaskBlocked('收获结果未识别，截图已保存')
            self.b.click_at(s,(640,660),[re.escape(s.find('获得|金币|经验|建材').text)],'关闭星律奖励')
        self.home();return '星律收获已执行并返回世界'
    def collect_task_tab(self,tab,max_batches=1):
        s=self.task_panel(tab);n=0
        if tab=='每日挑战':
            self.day['daily_text']=s.text
            if re.search('暴走.{0,4}1/1',s.text):self.day['rampage_done']=True
            self.save_state()
        for _ in range(max_batches):
            slot=task_claim_slot(s)
            if slot is None:break
            s=self.claim_collection_text(s,slot,is_tasks);n+=1
            self.note(f'{tab}：已确认免费领奖{n}批')
        if tab=='每日挑战':s=self.collect_daily_activity(s)
        remaining=task_claim_slot(s) is not None
        self.report.setdefault('task_rewards',{})[tab]={'batches':n,'remaining_claims':remaining,
            'reason':'达到设置的领奖批次上限，仍有可领奖励' if remaining else '当前可领奖励已检查'}
        if remaining:self.note(tab+'仍有可领奖励，已达到设置的批次上限')
        self.home();return n
    def rewards(self):
        if self.options['rewards']['collect_idle']:self.note(self.collect_idle())
        tabs={'daily':'每日挑战','side':'支线冒险','main':'主线任务'}
        activity_before=len(self.report.get('daily_activity_claimed',[]))
        n=sum(self.collect_task_tab(tabs[r['id']],self.options['rewards']['max_batches']) for r in selected_rows(self.options['rewards'],'tabs'))
        chests=len(self.report.get('daily_activity_claimed',[]))-activity_before
        summary=f'任务免费领奖 {n} 批；活跃宝箱 {chests} 个'+('；所选任务页暂无可领取奖励' if n==0 and chests==0 else '')
        self.note(summary)
        echoes=self.collect_world_echoes()
        return summary+('；'+echoes if echoes else '')

    def execute_task(self,task):
        self.active_task=task
        report_key=self.report_key(task);self.active_task_id=report_key
        entry=getattr(self,'_active_instance',None);name=entry['name'] if entry else TASKS[task][0]
        self.report.setdefault('execution_order',[]).append(report_key)
        self.emit('phase','正在执行：'+name)
        resumed=report_key in self.report.get('tasks',{})
        self.emit('task',(report_key,'运行中'));self.note(('补充免费体力后继续：' if resumed else '开始：')+name)
        self.report.setdefault('tasks',{})[report_key]={'status':'running','message':'正在执行',
            'attempts':self.task_counts.get(task,0),
            'victories':sum(a.get('outcome')=='victory' for a in self.task_attempts(task))}
        self.checkpoint()
        recovery_error=None
        try:
            for interruption in range(3):
                try:result=self.with_page_recovery(getattr(self,task),name);break
                except EncounterInterrupted:
                    self.note('寻路事件处理完成，继续定位'+TASKS[task][0])
                    self.home()
            else:raise TaskBlocked('该玩法连续被寻路事件打断，事件已处理但原任务未完成')
            outcome={'status':'done','message':result}
        except BudgetReached as e:
            outcome={'status':'done','message':str(e)}
            if task in STAMINA_TASKS:self.stamina_retry[task]='体力不足' in str(e)
            try:self.home()
            except TaskBlocked as error:recovery_error=error
        except TaskBlocked as e:
            outcome={'status':'blocked','message':str(e)}
            if hasattr(self,'last_screen'):
                checkpoint=self.report['folder']/(report_key+'-blocked.png')
                self.b.save_screen(self.last_screen,checkpoint)
                outcome['screenshot']=str(checkpoint)
            if task!='startup':
                try:self.home()
                except TaskBlocked as error:recovery_error=error
        self._overview_ready=None
        if recovery_error:
            outcome['status']='blocked';outcome['recovery_error']=str(recovery_error)
        attempts=self.task_attempts(task)
        outcome['attempts']=self.task_counts.get(task,len(attempts))
        outcome['victories']=sum(a['outcome']=='victory' for a in attempts)
        if resumed:outcome['message']='本次续跑：'+outcome['message']
        if task in PRIMARY_RESOURCES or task in ('origin','arena','giant','triad','nest','rift','forest'):
            outcome['summary']=self.task_summary(task)
            outcome['message']+='；'+outcome['summary']
        if entry:
            outcome.update(task=task,name=name,options=entry['options'],resource_usage=self.report.get('resource_usage',{}).get(task,{}).copy())
        self.report.setdefault('tasks',{})[report_key]=outcome
        self.emit('task',(report_key,'完成' if outcome['status']=='done' else '待校准'))
        self.note(outcome['message'])
        write_report(self.report)
        if recovery_error:raise SafetyStop(str(recovery_error))
        if task=='startup' and outcome['status']=='blocked':raise SafetyStop(outcome['message'])
    def battle(self,resource_name,cost=1):
        if self.battles>=self.limit:raise TaskBlocked('达到单轮战斗上限')
        self.battles+=1
        if self.active_task:self.task_counts[self.active_task]=self.task_counts.get(self.active_task,0)+1
        until=time.monotonic()+int(self.b.settings.get('battle_timeout_seconds',240))
        saw_battle=False;last_feedback=time.monotonic();settle_clicked=False
        label=PRIMARY_RESOURCES.get(self.active_task,('',0))[0]
        before=self.report.get('resource_usage',{}).get(self.active_task,{}).get(label,{}).get('remaining')
        if '免费' in resource_name:before=None
        while time.monotonic()<until:
            s=self.observe_battle();self.b.guard(s)
            if triggered_event(s) in ('merchant','sage_quiz') or (is_ambush(s) and self.active_task!='ambush'):
                if not saw_battle:
                    # The requested fight has not started. Do not count the
                    # replacement event as that task's attempt or victory.
                    self.battles-=1
                    if self.active_task:self.task_counts[self.active_task]-=1
                if is_merchant(s):self.handle_merchant(s)
                elif is_sage_dialog(s):self.resume_sage_dialog(s)
                else:self.handle_ambush(s)
                if saw_battle:raise SafetyStop('乱入已处理，但原战斗结算未核实，未计为通关')
                raise EncounterInterrupted('寻路事件已处理，重新核对原目标')
            if self.active_task=='tribe':
                if s.has('点击空白位置继续','防御值') or totem_score(s):
                    self.b.save_screen(s,self.report['folder']/'tribe-damage-result.png')
                    anchors=['点击空白位置继续','我方状态','比拼方式'] if totem_score(s) else ['点击空白位置继续','防御值']
                    self.b.click_at(s,(930,594),anchors,'查看部落冒险结算奖励')
                    continue
                if s.has('^退出$','获得奖励','重复挑战'):
                    result=self.tribe_settlement(s)
                    self.settle_battle_resource(self.active_task,result,'score',before)
                    self.report.setdefault('battles',[]).append({'resource':resource_name,'result':'score','texts':result.text})
                    return result
            if is_failure(s):
                self.settle_battle_resource(self.active_task,s,'failed',before)
                self.report.setdefault('battles',[]).append({'resource':resource_name,'result':'failed','texts':s.text})
                raise FightLost(s)
            if self.active_task=='rift' and is_rift_victory(s):
                self.report.setdefault('battles',[]).append({'resource':resource_name,'result':'victory','texts':s.text})
                return s
            if s.find('^退出$') and s.find('胜利') and s.find('获得奖励'):
                self.settle_battle_resource(self.active_task,s,'victory',before)
                self.report.setdefault('battles',[]).append({'resource':resource_name,'result':'victory','texts':s.text})
                return s
            if s.find('^暂停$|^自动$|^手动$|^X2$|^x2$|^撤退$'):saw_battle=True
            if self.active_task=='hunt' and self.options['hunt']['auto_settle'] and not settle_clicked:
                button=pvp_settle_button(s,self.b.read_text_crop)
                if button:
                    self.b.save_screen(s,self.report['folder']/'hunt-before-settle.png')
                    self.b.click_at(s,button.center,['^结算$',r'\d{1,2}:\d{2}'],'点击狩猎结算')
                    settle_clicked=True;self.note('狩猎已点击结算，等待实际胜败与资源核对')
                    continue
            if time.monotonic()-last_feedback>=15:
                self.note('战斗进行中，等待结算…' if saw_battle else '等待战斗画面或结算加载…')
                last_feedback=time.monotonic()
            # Loading and victory animation can have no text. Never click them.
            self.b.sleep(2)
        raise SafetyStop(f'{resource_name}战斗未在时限内结算；停止并保留游戏现场')

def create_report():
    root=Path(os.environ.get('CHAO2_REPORT_ROOT',str(ROOT/'reports')));root.mkdir(parents=True,exist_ok=True)
    folder,started=reserve_report(root,datetime.now().astimezone())
    report={'started':started,'folder':folder,'status':'running','tasks':{},'events':[],'diamond_spend':None}
    write_report(report)
    cleanup=prune_reports(root)
    if cleanup['errors']:report['history_cleanup_errors']=cleanup['errors']
    return report

def write_report(report):
    data={**report,'folder':str(report['folder'])}
    atomic_json(report['folder']/'report.json',data)

def run_daily(settings,selected,stop,log=print,emit=lambda *a:None,diagnostic=False):
    settings=normalize_settings(settings)
    selected=normalize_selected(selected)
    report=create_report()
    def audit(action):
        action={'time':datetime.now().astimezone().isoformat(),**action}
        with (report['folder']/'actions.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(action,ensure_ascii=False)+'\n')
    b=Backend(settings,stop,log,progress=lambda message:emit('phase',message),audit=audit);daily=Daily(b,report,emit)
    if report.get('history_cleanup_errors'):log('部分旧运行记录暂时无法清理：'+'；'.join(report['history_cleanup_errors']))
    daily.selected=list(selected)
    entries=execution_entries(settings,selected,ORDER)
    daily.planned_entries=entries
    report['plan']=[row['key'] for row in entries]
    report['queue_plan']=[{k:v for k,v in row.items() if k!='options'} for row in entries]
    report['execution_mode']='overview' if settings['unordered_tasks'] else 'ordered'
    report['task_options']=settings['task_options']
    report['attempt_counts']=daily.task_counts
    try:
        execution=list(entries)
        if not diagnostic and any(row['key']=='origin' for row in execution) and not origin_is_open():
            message='已跳过起源殿：当前不在北京时间20:00–22:00'
            for row in execution:
                if row['key']!='origin':continue
                report['tasks'][row['id']]={'status':'skipped','message':message,'attempts':0,'victories':0}
                daily.note(message);emit('task',(row['id'],'跳过'))
            execution=[row for row in execution if row['key']!='origin']
            if not execution:
                report['status']='completed';report['diamond_spend']=0
                return report
        b.connect()
        if diagnostic:
            s=daily.observe('diagnostic',dismiss_popups=False);report['screen_text']=s.text
            report['device']=b.controller.get_custom_info();report['status']='diagnostic'
            if is_world(s):report['resources_start']=daily.world_resources(s)
            log('只读检测完成，没有点击游戏');return report
        # Startup/home settle any existing encounter first, without assigning
        # a shared combat HUD to a selected activity or reordering the queue.
        # Wake before any routine tries to navigate home or read account resources.
        for entry in execution:
            if entry['key']=='startup':daily.execute_entry(entry)
        s=daily.home();report['resources_start']=daily.world_resources(s)
        daily.wild_daily_active=True
        s=daily.maybe_capture_wild(s)
        s=daily.maybe_free_summon(s)
        pending=[row for row in execution if row['key'] not in ('startup','finish')]
        stamina_remaining={row['id'] for row in pending if row['key'] in STAMINA_TASKS}
        while pending:
            task=daily.next_daily_task(list(dict.fromkeys(row['key'] for row in pending)))
            entry=next(row for row in pending if row['key']==task);pending.remove(entry)
            daily.execute_entry(entry)
            stamina_remaining.discard(entry['id'])
            if task in STAMINA_TASKS and not stamina_remaining and any(
                    row.get('options',settings['task_options'][row['key']])['auto_three_shots'] or row.get('options',settings['task_options'][row['key']])['auto_potions']
                    for row in execution if row['key'] in STAMINA_TASKS):
                try:daily.note(daily.replenish_queue_stamina(execution) if 'task_queue' in settings else daily.replenish_stamina())
                except TaskBlocked as e:
                    report['stamina_refill']={'status':'blocked','message':str(e),'claimed':daily.report.get('stamina_claims',0)}
                    last=getattr(daily,'last_screen',None)
                    if last is not None:
                        path=report['folder']/'stamina-refill-blocked.png'
                        b.save_screen(last,path)
                        report['stamina_refill']['screenshot']=str(path)
                    daily.note('体力补充：'+str(e))
                    try:daily.home()
                    except TaskBlocked:raise SafetyStop(str(e))
                write_report(report)
            if settings['free_summon_enabled']:
                daily.maybe_free_summon(daily.home())
        s=daily.home();report['resources_end']=daily.world_resources(s)
        a=report['resources_start']['diamonds'];z=report['resources_end']['diamonds']
        spent=report.get('merchant_diamond_spend',0)+report.get('piggy_diamond_spend',0)
        report['diamond_spend']=spent if not report.get('piggy_spend_unconfirmed') and a is not None and z is not None and z>=a-spent else None
        incomplete=(any(v['status']=='blocked' for v in report['tasks'].values()) or
                    any(v['status'] in ('blocked','unconfirmed') for v in report.get('free_summons',[])) or
                    report.get('stamina_refill',{}).get('status')=='blocked' or
                    (report.get('wild_checks') or [{}])[-1].get('status')=='navigation_failed' or
                    any(v['status'] in ('unconfirmed','interrupted','unrecognized') for v in report.get('wild_captures',[])) or
                    any(v['status'] in ('unreadable','unconfirmed','pending') for v in report.get('tribe_occupation_rewards',[])))
        report['status']='partial' if incomplete else 'completed'
        daily.save_state()
        write_report(report)
        finishes=[row for row in execution if row['key']=='finish']
        if finishes:
            mumu_closed=False
            for entry in finishes:
                ident=entry['id'];options=entry.get('options',daily.options['finish'])
                if report['status']=='completed':
                    daily.active_task='finish';daily.active_task_id=ident
                    report['tasks'][ident]={'status':'running','message':'正在结束关闭'}
                    emit('task',(ident,'运行中'));daily.note('开始：结束关闭，运行记录已保存')
                    if options['close_mumu'] and not mumu_closed:
                        if close_game_and_mumu(b,log) is False:
                            raise TaskBlocked('结束关闭未完整完成：超二已退出，MuMu实例仍保留，请查看关闭记录')
                        mumu_closed=True
                    report['close_app_requested']=report.get('close_app_requested',False) or options['close_app']
                    report['tasks'][ident]={'status':'done','message':'结束关闭已执行，记录已保存','attempts':0,'victories':0}
                    emit('task',(ident,'完成'))
                else:
                    report['tasks'][ident]={'status':'skipped','message':'存在未完成任务，保留程序和模拟器现场','attempts':0,'victories':0}
                    emit('task',(ident,'跳过'));daily.note(report['tasks'][ident]['message'])
        elif settings.get('close_mumu') and report['status']=='completed':
            close_game_and_mumu(b,log)
    except UserStopped as e:
        report['status']='stopped';report['reason']=str(e);log('已停止，保留当前游戏现场')
        refill=report.get('stamina_refill',{})
        if refill.get('status')=='running':
            refill.update(status='stopped',message='体力补充已停止；停止时：'+refill.get('message',''))
            log(refill['message'])
        task=getattr(daily,'active_task_id',None) or daily.active_task
        if task and report['tasks'].get(task,{}).get('status')=='running':
            count=report.get('instance_attempt_counts',{}).get(task,daily.task_counts.get(task,0))
            report['tasks'][task].update(status='stopped',message='已停止，保留当前游戏现场',attempts=count)
            emit('task',(task,'已停止'))
    except Exception as e:
        report['status']='blocked';report['reason']=str(e);log('已安全停止：'+str(e))
        refill=report.get('stamina_refill',{})
        if refill.get('status')=='running':refill.update(status='blocked',message=str(e))
        task=getattr(daily,'active_task_id',None) or daily.active_task
        if task and report['tasks'].get(task,{}).get('status') in (None,'running'):
            outcome={'status':'blocked','message':str(e),'attempts':report.get('instance_attempt_counts',{}).get(task,daily.task_counts.get(task,0)),
                     'victories':sum(a.get('outcome')=='victory' for a in report.get('team_attempts',[]) if a.get('instance_id',a.get('task'))==task)}
            last=getattr(daily,'last_screen',None)
            if last is not None:
                path=report['folder']/(task+'-blocked.png');b.save_screen(last,path);outcome['screenshot']=str(path)
            report['tasks'][task]=outcome
        if b.tasker:b.tasker.post_stop()
    finally:
        report['finished']=datetime.now().astimezone().isoformat();write_report(report)
    return report

def close_game_and_mumu(b,log):
    # Another game may be running in another MuMu display. Never close that session.
    from .backend import display_blocks,PACKAGE,NO_WINDOW
    import subprocess
    text=b.controller.cmd('shell','dumpsys','window','displays')
    apps=[]
    for _,block in display_blocks(text):
        for p in re.findall(r'mFocusedApp=.*?u0 ([\w.]+)/',block):
            if p!=PACKAGE and p not in ('app.lawnchair','com.android.launcher3','com.mumu.launcher'):apps.append(p)
    b.controller.cmd('shell','am','force-stop',PACKAGE)
    if apps:
        log('已关闭超二；MuMu 中其他应用仍在运行，保留模拟器：'+', '.join(sorted(set(apps))));return False
    manager=Path(b.controller.adb).with_name('MuMuManager.exe')
    if manager.exists():
        index=str(b.settings.get('mumu_index',0))
        info=json.loads(subprocess.run([str(manager),'info','-v',index],capture_output=True,timeout=12,check=True,creationflags=NO_WINDOW).stdout.decode('utf-8','replace'))
        if str(info.get('adb_port'))!=b.controller.address.rsplit(':',1)[-1]:
            log('已关闭超二；实例编号与连接端口不符，保留 MuMu');return False
        subprocess.run([str(manager),'control','-v',index,'shutdown'],capture_output=True,timeout=20,check=True,creationflags=NO_WINDOW)
        for _ in range(10):
            info=json.loads(subprocess.run([str(manager),'info','-v',index],capture_output=True,timeout=12,check=True,creationflags=NO_WINDOW).stdout.decode('utf-8','replace'))
            if info.get('is_process_started') is False:
                log('已核实关闭 MuMu 实例'+index);return True
            time.sleep(.5)
        log('已发送 MuMu 关闭请求，但尚未确认实例已退出');return False
    else:log('已关闭超二，MuMu 管理器不存在，模拟器保留');return False
