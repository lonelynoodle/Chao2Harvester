"""Standalone 深渊先遣: client auto-suppression and one current encounter.

The client refreshes Tuesday/Thursday/Saturday at midnight Beijing time.
Availability always comes from the live client, never just the calendar.
"""
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import json
import time

import cv2
import numpy as np
from PIL import Image

from .anomalies import is_event_panel
from .backend import Backend, ROOT
from .policy import TaskBlocked, UserStopped, FightLost, parse_ratio
from .tool_settings import abyss_options
from .workflows import Daily, is_world, create_report, write_report


BEIJING = timezone(timedelta(hours=8))
REFRESH = '每周二、四、六 00:00（北京时间）'
AFFIX_ANCHORS = ['^压制词缀$', '放入对应怪兽可以压制词缀', '^压制条件$']


def next_refresh(now=None):
    now = now or datetime.now(BEIJING)
    if now.tzinfo is None:
        raise ValueError('刷新时间需要带时区')
    now = now.astimezone(BEIJING)
    for days in range(1, 8):
        candidate = (now + timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
        if candidate.weekday() in (1, 3, 5):
            return candidate


def is_abyss_affixes(s):
    return bool(s.find('^压制词缀$', (500, 10, 280, 75)) and
                s.find('放入对应怪兽可以压制词缀', (70, 100, 520, 80)) and
                s.find('^压制条件$', (690, 190, 310, 480)))


def is_abyss_menu(s):
    return bool(not is_abyss_affixes(s) and is_event_panel(s) and
                s.find('^深渊先遣$', (900, 0, 260, 65)) and
                s.find(r'每周二.*四.*六.*0[:：]00.*刷新', (820, 65, 380, 55)) and
                s.find('^压制词缀$', (810, 115, 390, 80)))


def abyss_target(s):
    return s.find('^深渊先遣$', (820, 195, 370, 70)) if is_abyss_menu(s) else None


def abyss_empty(s):
    return bool(is_abyss_menu(s) and not abyss_target(s) and
                s.find('^无$', (820, 260, 390, 190)) and
                s.find('^深渊先遣未出现$', (820, 430, 390, 180)))


def is_abyss_detail(s):
    return bool(not is_abyss_affixes(s) and
                s.find('^深渊先遣$', (100, 115, 410, 85)) and
                s.find('^压制词缀$', (390, 60, 170, 65)) and
                s.find('^敌方阵容$', (1080, 110, 200, 90)) and
                s.find('^排阵$', (750, 580, 220, 100)) and
                s.find('^前往挑战$', (970, 580, 270, 100)))


@lru_cache(maxsize=1)
def suppressed_template():
    return np.asarray(Image.open(ROOT/'resource/image/abyss-suppressed.png').convert('RGB'))[:, :, ::-1].copy()


def suppressed_slots(s):
    """Six fixed affix icons; the client's red barred circle means suppressed."""
    if not is_abyss_affixes(s):
        return None
    chosen = []
    template = suppressed_template()
    for index, x in enumerate((780, 820, 860, 900, 940, 980), 1):
        icon = s.image[114:156, x-20:x+20]
        if icon.shape != (42, 40, 3) or icon.std() < 15:
            return None
        score = cv2.minMaxLoc(cv2.matchTemplate(icon, template, cv2.TM_CCOEFF_NORMED))[1]
        if score >= .82:
            chosen.append(index)
    return chosen if len(chosen) <= 4 else None


def verify_abyss_entry(b, s):
    b.guard(s)
    if not is_abyss_detail(s):
        raise TaskBlocked('深渊先遣挑战页未确认')
    cost = s.find('^50$', (1080, 625, 65, 50))
    if not cost or not b.match_template(s, 'abyss-stamina.png', [1050, 625, 50, 45], .9):
        raise TaskBlocked('深渊先遣的50体力费用未确认，未开始挑战')
    if not s.find('^瞬破敌方$', (1000, 675, 180, 45)) or not b.match_template(s, 'abyss-instant-off.png', [1000, 680, 55, 40], .97):
        raise TaskBlocked('深渊先遣瞬破未确认关闭，未消耗瞬破石')
    ratio = parse_ratio(s.region_text((1170, 0, 110, 60)))
    if ratio is None or ratio[0] < 0 or ratio[1] <= 0:
        raise TaskBlocked('深渊先遣体力余额未读清')
    return ratio


class AbyssPlayer(Daily):
    def __init__(self, b, report, emit=lambda *a: None):
        super().__init__(b, report, emit)
        self.tool_options = abyss_options(b.settings)
        self.active_task = 'abyss'
        self.limit = len(self.tool_options['teams']) or 1
        self.last_team = None

    def wait_screen(self, predicate, message, seconds=15):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            s = self.observe()
            self.b.guard(s)
            if predicate(s):
                return s
            self.b.sleep(.7)
        raise TaskBlocked(message)

    def close_affixes(self, s):
        self.b.click_at(s, (1188, 53), AFFIX_ANCHORS, '关闭深渊先遣压制词缀')
        return self.wait_screen(lambda q: is_abyss_menu(q) or is_abyss_detail(q), '压制窗口尚未关闭')

    def menu_page(self):
        for _ in range(8):
            s = self.observe()
            self.b.guard(s)
            if is_abyss_menu(s):
                self.report.setdefault('resources_start', self.world_resources(s))
                return s
            if is_abyss_affixes(s):
                self.close_affixes(s)
                continue
            if is_abyss_detail(s):
                self.b.click_at(s, (43, 28), ['^深渊先遣$', '^敌方阵容$'], '返回先遣列表')
                self.wait_screen(lambda q: is_world(q) or is_abyss_menu(q), '深渊先遣详情未返回列表或世界')
                continue
            if is_world(s):
                self.report.setdefault('resources_start', self.world_resources(s))
                self.note('打开世界事件 · 深渊先遣')
                s = self.open_world_events(s)
            if is_event_panel(s):
                if not s.find('^深渊先遣$', (930, 650, 150, 60)):
                    self.b.click_text(s, '^战斗$', roi=(1200, 95, 80, 70))
                    s = self.wait_screen(lambda q: is_event_panel(q) and q.find('^深渊先遣$', (930, 650, 150, 60)), '事件战斗分类未打开')
                self.b.click_text(s, '^深渊先遣$', roi=(930, 650, 150, 60))
                return self.wait_screen(is_abyss_menu, '深渊先遣列表未打开')
            self.b.sleep(.7)
        raise TaskBlocked('请从世界地图、世界事件或深渊先遣页面启动')

    def suppress(self, s):
        if not is_abyss_affixes(s):
            self.b.click_text(s, '^压制词缀$')
            s = self.wait_screen(is_abyss_affixes, '压制词缀窗口未打开')
        self.b.save_screen(s, self.report['folder']/'abyss-affixes-before.png')
        before = suppressed_slots(s)
        if before is None:
            raise TaskBlocked('压制词缀状态未读清，保留现场')
        # A full set is already configured. Do not unload the user's choices.
        if len(before) < 4:
            button = s.find('^一?键压制$', (1020, 100, 190, 75))
            if not button:
                raise TaskBlocked('未识别深渊先遣的一键压制按钮')
            self.note('按客户端种族、等级条件自动安排压制怪兽')
            self.b.click_at(s, button.center, AFFIX_ANCHORS, '深渊先遣一键压制')
            s = self.wait_screen(lambda q: is_abyss_affixes(q) and suppressed_slots(q) is not None, '一键压制后的状态未确认')
        after = suppressed_slots(s)
        if after is None or len(after) < len(before):
            raise TaskBlocked('一键压制结果异常，未继续挑战')
        self.report['suppression'] = {'before': before, 'after': after, 'maximum': 4}
        self.b.save_screen(s, self.report['folder']/'abyss-affixes-after.png')
        self.note(f'已确认压制{len(after)}/4项词缀' + ('；其余按现有可用怪兽保留' if len(after) < 4 else ''))
        return self.close_affixes(s)

    def open_target(self, s):
        target = abyss_target(s)
        if not target:
            raise TaskBlocked('深渊先遣目标已改变，未点击旧坐标')
        self.b.click_at(s, target.center, ['^深渊先遣$', '^压制词缀$', '每周二.*刷新'], '定位并进入当前深渊先遣')
        # The camera travels through the map before the detail opens itself.
        self.note('等待定位到深渊先遣，期间不重复打开事件')
        return self.wait_screen(is_abyss_detail, '定位先遣后未进入挑战页，保留现场', seconds=45)

    def detail_page(self):
        return self.wait_screen(is_abyss_detail, '切换阵容后未返回深渊先遣详情')

    def prepare_abyss_team(self,detail,team):
        detail=self.select_team(detail,team,return_page=self.detail_page)
        self.last_team=team
        # Changing the world team can remove assigned suppression monsters.
        # Re-evaluate affixes after every selected/fallback team.
        detail=self.suppress(detail)
        if not is_abyss_detail(detail):detail=self.open_target(detail)
        self.report.setdefault('suppression_by_team',[]).append({
            'team':team,**self.report.get('suppression',{})})
        return detail

    def finish_world(self):
        s = self.menu_page()
        self.b.click_at(s, (770, 680), ['^深渊先遣$', '^压制词缀$', '每周二.*刷新'], '收起深渊先遣列表')
        s = self.wait_screen(is_world, '先遣结束后未返回世界')
        s = self.home()
        self.report['resources_end'] = self.world_resources(s)

    def play(self):
        self.note('深渊先遣刷新：'+REFRESH)
        self.report['next_refresh'] = next_refresh().isoformat()
        s = self.menu_page()
        if not abyss_target(s):
            # No title alone is not proof of completion. Require an explicit
            # client empty-state; never act on a partially loaded card.
            for _ in range(3):
                if abyss_empty(s):
                    self.report['status'] = 'completed'
                    return '当前没有可挑战的深渊先遣；下次刷新 '+next_refresh().strftime('%m-%d %H:%M')
                self.b.sleep(1)
                s = self.observe()
                self.b.guard(s)
                if abyss_target(s):
                    break
            else:
                raise TaskBlocked('深渊先遣列表未识别到目标或已完成提示，未将空白当成完成')
        for team in self.tool_options['teams'] or [None]:
            detail = self.open_target(s)
            ratio = verify_abyss_entry(self.b, detail)
            if ratio[0] < 50:
                self.report['status'] = 'partial'
                return f'深渊先遣未挑战：体力{ratio[0]}/{ratio[1]}，需要50；未补充体力'
            detail = self.prepare_abyss_team(detail,team)
            ratio = verify_abyss_entry(self.b, detail)
            if ratio[0] < 50:
                raise TaskBlocked('切换阵容并压制词缀后体力不足50，未挑战')
            row = {'task': 'abyss', 'team': team, 'stamina_before': ratio[0], 'entry_cost': 50, 'outcome': 'unconfirmed'}
            self.report.setdefault('team_attempts', []).append(row)
            self.b.save_screen(detail, self.report['folder']/f'abyss-attempt-{len(self.report["team_attempts"])}.png')
            self.note('挑战深渊先遣 · '+(f'队伍{team}' if team else '当前阵容')+' · 50体力')
            self.checkpoint()
            self.start_challenge('abyss',detail,'深渊先遣地图体力',lambda q:verify_abyss_entry(self.b,q))
            try:
                result = self.battle('深渊先遣地图体力', cost=50)
                row['outcome'] = 'victory'
            except FightLost as lost:
                result = lost.screen
                row['outcome'] = 'failed'
            self.b.save_screen(result, self.report['folder']/f'abyss-result-{len(self.report["team_attempts"])}.png')
            self.exit_result(result)
            s = self.menu_page()
            after = self.world_resources(s)
            row['stamina_after'] = after['stamina']
            delta = None if after['stamina'] is None else ratio[0]-after['stamina']
            row['stamina_spent'] = (50 if row['outcome']=='victory' and delta is not None and 0<=delta<=50
                                    else delta if delta is not None and 0<=delta<=50 else None)
            self.note(('挑战胜利' if row['outcome']=='victory' else '挑战失败')+f'；本场体力消耗{row["stamina_spent"] if row["stamina_spent"] is not None else "未核实"}，剩余{after["stamina"]}/{after["stamina_cap"]}')
            self.checkpoint()
            if row['outcome'] == 'victory':
                self.report['status'] = 'completed'
                return '深渊先遣胜利，已核对结算奖励'
            if not abyss_target(s):
                self.report['status'] = 'partial'
                return '本次先遣未通过，当前目标已消失，未重复挑战'
        self.report['status'] = 'partial'
        return '深渊先遣所选阵容均未通过，已停止重试'


def run_abyss(settings, stop, log=print, emit=lambda *a: None):
    abyss_options(settings)
    report = create_report()
    report.update(tool='abyss', diamond_spend=0, refresh_schedule=REFRESH)
    def audit(action):
        with (report['folder']/'actions.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps({'time': datetime.now().astimezone().isoformat(), **action}, ensure_ascii=False)+'\n')
    b = Backend(settings, stop, log, lambda m: emit('phase', m), audit)
    player = AbyssPlayer(b, report, emit)
    try:
        b.connect()
        emit('phase', '深渊先遣运行中')
        report['reason'] = player.play()
        player.finish_world()
        player.note(report['reason'])
    except UserStopped as e:
        report.update(status='stopped', reason=str(e))
    except Exception as e:
        report.update(status='blocked', reason=str(e))
        player.note('已停止：'+str(e))
    finally:
        if getattr(player, 'last_screen', None) is not None:
            b.save_screen(player.last_screen, report['folder']/'abyss-final.png')
        report['finished'] = datetime.now().astimezone().isoformat()
        write_report(report)
    return report
