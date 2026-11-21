"""One verified level-up for each enabled daily challenge."""
from datetime import datetime, timezone, timedelta
import re

import cv2
import numpy as np

from .compact_balance import BALANCE_PATTERN, balance_bounds, displayed_balance
from .policy import SessionUnavailable, TaskBlocked
from .star_supply import monster_roster


MONSTER_INFO = r'^怪兽信息$'
CORE_DIALOG = r'^元核强化$'
CORE_GRID = (MONSTER_INFO, r'^筛选$', r'^元核分解$')
DAILY_PAGE = (r'^每日挑战$', r'^本周活跃$')
DAILY_TITLES = {'core': '任意元核强化', 'monster': '任意怪兽提升'}
UPGRADE_LABELS = {'core': '元核', 'monster': '怪兽'}
GOLD_HUD = (1047, 7, 81, 38)
EXP_HUD = (1179, 7, 87, 38)
CORE_COST = (934, 604, 85, 31)
EXP_COST = (827, 419, 75, 33)
BEIJING = timezone(timedelta(hours=8))


def daily_upgrade_progress(s, kind):
    if not s.has(*DAILY_PAGE):
        return None
    title = DAILY_TITLES[kind]
    word = s.find(title, (311, 210, 425, 465))
    if not word:
        return None
    y = word.center[1]
    row = re.sub(r'\s', '', s.region_text((310, y - 16, 430, 32)))
    progress = re.search(title + r'1[次级][（(]?\s*([01])[/／]1', row)
    if progress:
        return int(progress[1])
    if s.find(r'^已领取$|^领取$', (770, y - 16, 420, 32)):
        return 1
    if s.find(r'^前往$', (1060, y - 18, 158, 36)):
        return 0
    return None


def core_upgrade_dialog(s):
    return bool(s.find(CORE_DIALOG, (460, 42, 350, 75)) and
                s.find(r'^元核属性$', (680, 120, 125, 50)))


def core_identity(s):
    word = s.find(r'^.{2,20}元核$', (210, 490, 330, 56))
    return word.text if word else None


def core_arrow(s, direction):
    x, width = (22, 54) if direction == 'left' else (1200, 58)
    blue, green, red = s.image[330:400, x:x+width].astype('int16').transpose(2, 0, 1)
    if ((red > 169) & (green > 128) & (green > blue + 25)).mean() > .20:
        return (50 if direction == 'left' else 1226, 366)
    return None


def monster_attributes(s):
    return not monster_roster(s) and s.has(MONSTER_INFO, r'^攻击力$', r'^体力$') and not core_upgrade_dialog(s)


def monster_slots(s):
    # Card rims repeat every 126 px, even when the horizontal list stops between cards.
    bright = (s.image[696:704, 111:1258].max(axis=2) > 112).astype('uint8')
    rims = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, np.ones((1, 7), 'uint8'))
    centers = []
    for row in rims:
        edges = np.diff(np.r_[0, row, 0].astype('int8'))
        for left, right in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
            if 93 <= right - left <= 121:
                centers.append((left + right) // 2 + 111)
    if not centers:
        return []
    phase = max(centers, key=lambda x: sum(abs((x - y + 63) % 126 - 63) <= 4 for y in centers))
    return [(x, 640) for x in range(phase % 126, 1258, 126) if
            145 <= x <= 1230 and rims[:, x-111-25:x-111+25].mean() >= .58]


def selected_monster(s, point):
    x, _ = point
    blue, green, red = s.image[584:596, x-51:x+51].astype('int16').transpose(2, 0, 1)
    return ((blue > 150) & (green > 110) & (blue > red + 30)).mean() > .22


def read_amount(b, s, roi):
    word = s.find(BALANCE_PATTERN, roi)
    if word and word.score >= .8:
        return displayed_balance(word.text)
    return displayed_balance(re.sub(r'\s', '', b.read_text_crop(s, roi)))


def can_afford(cost, balance):
    if cost is None or balance is None:
        return False
    _, maximum = balance_bounds(cost)
    available, _ = balance_bounds(balance)
    return maximum > 0 and available >= maximum


def core_level(b, s):
    # The preview can combine old and new levels into a single OCR word.
    word = s.find(r'^等级\s*\d{1,3}$', (326, 348, 140, 58))
    if word:
        return int(re.search(r'\d+$', word.text)[0])
    blue, green, red = s.image[554:588, 414:455].astype('int16').transpose(2, 0, 1)
    preview = ((green > 160) & (green > red + 10) & (green > blue + 40)).mean() > .03
    if preview:
        return b.read_number(s, (338, 554, 50, 34))
    return b.read_number(s, (363, 554, 73, 34))


def monster_level(b, s):
    word = s.find(r'^\d{1,3}$', (675, 411, 92, 49))
    return int(word.text) if word else b.read_number(s, (684, 413, 88, 44))


def changed_pixels(before, after):
    return np.abs(before.astype('int16') - after).mean() > 2


class DailyUpgrades:
    def upgrade_swipe(self, s, start, end, duration=650):
        self.b.guard(s)
        if not self.b.wait(self.b.controller.post_swipe(*start, *end, duration)).succeeded:
            raise SessionUnavailable('每日挑战列表滑动失败')
        self.b.sleep(.65)
        return self.observe()

    def find_daily_upgrade_progress(self, kind):
        s = self.task_panel('每日挑战')
        title = DAILY_TITLES[kind]
        for start, end in [((603, 620), (603, 312)), ((603, 312), (603, 620))]:
            previous = None
            for _ in range(9):
                self.b.guard(s)
                if not s.has(*DAILY_PAGE):
                    raise TaskBlocked('每日挑战页面已变化')
                self.b.confirm_label(s, title, (323, 228, 335, 438), scale=2, threshold=.8)
                progress = daily_upgrade_progress(s, kind)
                if progress is not None:
                    return progress
                current = s.region_text((320, 200, 412, 475))
                if current and current == previous:
                    break
                previous = current
                s = self.upgrade_swipe(s, start, end)
        raise TaskBlocked(f'每日挑战的{UPGRADE_LABELS[kind]}升级进度未读清')

    def daily_core_upgrade(self):
        return self.run_daily_upgrade('core')

    def daily_monster_upgrade(self):
        return self.run_daily_upgrade('monster')

    def run_daily_upgrade(self, kind):
        title = UPGRADE_LABELS[kind]
        progress = self.find_daily_upgrade_progress(kind)
        date = datetime.now(BEIJING).date().isoformat()
        receipts = self.state.setdefault(date, {}).setdefault('daily_upgrades', {})
        if progress == 1:
            if kind in receipts and receipts[kind]['status'] == 'pending':
                receipts[kind]['status'] = 'done'
                self.save_state()
            return {'status': 'skipped', 'message': f'每日挑战·{title}今天已完成'}
        prior = receipts.get(kind)
        if prior:
            if prior['status'] == 'done':
                return {'status': 'skipped', 'message': f'每日挑战·{title}今天已确认升级一次'}
            raise TaskBlocked(f'每日挑战·{title}上一次升级结果待核实，本次未重复消耗')
        s = self.territory()
        self.b.click_text(s, r'^怪兽$', roi=(755, 630, 130, 90))
        s = self.await_page(MONSTER_INFO)
        result = (self.upgrade_one_core(s, receipts) if kind == 'core'
                  else self.upgrade_one_monster(s, receipts))
        if result is None:
            return {'status': 'skipped', 'message': f'每日挑战·没有找到可升一级的{title}'}
        return result

    def move_core(self, s, direction):
        point = core_arrow(s, direction)
        # The icon, name and displayed stats identify a changed detail, even
        # when adjacent cores share the same name and level.
        before = s.image[122:538, 240:1150]
        self.b.click_at(s, point, [CORE_DIALOG], '查看相邻元核')
        return self.wait_for_screen(
            lambda q: core_upgrade_dialog(q) and changed_pixels(before, q.image[122:538, 240:1150]),
            '相邻元核详情', timeout=1.5)

    def upgrade_one_core(self, s, receipts):
        if not s.has(*CORE_GRID):
            self.b.confirm_label(s, r'^元核$', (1190, 282, 87, 83))
            self.b.click_text(s, r'^元核$', roi=(1190, 282, 87, 83))
            s = self.await_page(*CORE_GRID, timeout=4)
        # Reset the small inventory to the start of the game's displayed order.
        while True:
            before = s.image[136:551, 30:565]
            q = self.upgrade_swipe(s, (300, 196), (300, 530))
            if not q.has(*CORE_GRID):
                raise TaskBlocked('元核列表页面未确认')
            s = q
            if not changed_pixels(before, q.image[136:551, 30:565]):
                break
        if s.find(r'^0$', (120, 85, 40, 33)):
            return None
        if (s.image[160:229, 56:132].max(axis=2) > 100).mean() < .16:
            return None
        self.b.click_at(s, (94, 193), list(CORE_GRID), '查看列表中的第一个元核')
        s = self.wait_for_screen(lambda q: q.find(r'^元核属性$', (128, 106, 125, 65)) and
                                 q.find(r'^强化$', (32, 496, 135, 69)), '所选元核', timeout=3)
        self.b.click_text(s, r'^强化$', roi=(32, 496, 135, 69))
        s = self.wait_for_screen(core_upgrade_dialog, '元核强化', timeout=3)
        direction = 'right'
        if self.options['other']['daily_core_order'] == 'reverse':
            while core_arrow(s, 'right'):
                s = self.move_core(s, 'right')
            direction = 'left'
        while True:
            offer = self.core_upgrade_offer(s)
            if offer:
                return self.commit_daily_upgrade('core', offer, receipts)
            if not core_arrow(s, direction):
                return None
            s = self.move_core(s, direction)

    def core_upgrade_offer(self, s):
        if not core_upgrade_dialog(s) or s.find(r'^消耗材料$', (672, 525, 105, 48)):
            return None
        button = s.find(r'^强化$', (817, 568, 255, 46))
        name = core_identity(s)
        if not button or not name or not self.b.match_template(s, 'daily-upgrade-gold.png', [902, 601, 41, 40], .90):
            return None
        level = core_level(self.b, s)
        next_level = self.b.read_number(s, (418, 553, 38, 36))
        if level is None or next_level != level + 1:
            return None
        cost = read_amount(self.b, s, CORE_COST)
        balance = read_amount(self.b, s, GOLD_HUD)
        if not can_afford(cost, balance):
            return None
        return {'name': name, 'level': level, 'price': cost, 'point': button.center}

    def upgrade_one_monster(self, s, receipts):
        if not monster_attributes(s):
            roi = (1193, 106, 84, 78)
            self.b.confirm_label(s, r'^属性$', roi)
            self.b.click_text(s, r'^属性$', roi=roi)
            s = self.wait_for_screen(monster_attributes, '怪兽属性', timeout=3)
        # The game remembers the strip position when the player has browsed it.
        while True:
            q = self.upgrade_swipe(s, (264, 640), (1175, 640))
            if not monster_attributes(q):
                raise TaskBlocked('怪兽列表页面未确认')
            moved = changed_pixels(s.image[614:672, 113:1252], q.image[614:672, 113:1252])
            s = q
            if not moved:
                break
        while True:
            slots = monster_slots(s)
            if not slots:
                raise TaskBlocked('怪兽列表卡片未读清')
            for point in slots:
                if not selected_monster(s, point):
                    self.b.click_at(s, point, [MONSTER_INFO, r'^攻击力$'], '选择下一个怪兽')
                    s = self.wait_for_screen(lambda q: monster_attributes(q) and selected_monster(q, point),
                                             '怪兽已选中', timeout=1.5)
                offer = self.monster_upgrade_offer(s, point)
                if offer:
                    return self.commit_daily_upgrade('monster', offer, receipts)
            q = self.upgrade_swipe(s, (1070, 640), (520, 640))
            if not monster_attributes(q):
                raise TaskBlocked('怪兽列表翻页后页面未确认')
            if not changed_pixels(s.image[614:672, 113:1252], q.image[614:672, 113:1252]):
                return None
            s = q

    def monster_upgrade_offer(self, s, slot):
        if not monster_attributes(s) or not selected_monster(s, slot):
            return None
        if not self.b.match_template(s, 'daily-upgrade-monster.png', [919, 409, 79, 55], .91):
            return None
        if not self.b.match_template(s, 'daily-upgrade-exp.png', [787, 411, 40, 40], .90):
            return None
        level = monster_level(self.b, s)
        cost = read_amount(self.b, s, EXP_COST)
        balance = read_amount(self.b, s, EXP_HUD)
        if level is None or not can_afford(cost, balance):
            return None
        return {'level': level, 'price': cost, 'point': (958, 436), 'slot': slot}

    def commit_daily_upgrade(self, kind, offer, receipts):
        s = self.observe()
        is_core = kind == 'core'
        fresh = self.core_upgrade_offer(s) if is_core else self.monster_upgrade_offer(s, offer['slot'])
        label = UPGRADE_LABELS[kind]
        if fresh != offer:
            raise TaskBlocked(f'{label}升级前重新核对时目标或费用已变化')
        self.b.guard(s)
        start = offer['level']
        row = receipts[kind] = {'status': 'pending', 'old_level': start, 'price': offer['price']}
        if is_core:
            row['name'] = offer['name']
        self.save_state()
        anchors = [CORE_DIALOG, r'^强化$', r'^'+re.escape(offer['name'])+r'$'] if is_core else [MONSTER_INFO, r'^攻击力$']
        self.b.click_at(s, offer['point'], anchors, f'每日挑战：{label}单次升级')

        def leveled(q):
            if is_core:
                return core_upgrade_dialog(q) and core_identity(q) == offer['name'] and core_level(self.b, q) == start + 1
            return monster_attributes(q) and selected_monster(q, offer['slot']) and monster_level(self.b, q) == start + 1
        try:
            self.wait_for_screen(leveled, f'{label}等级提升一级', timeout=2)
        except TaskBlocked:
            if self.find_daily_upgrade_progress(kind) != 1:
                raise TaskBlocked(f'{label}升级提交后结果待核实')
            message = f'每日挑战·{label}升级进度已确认'
        else:
            row['new_level'] = start+1
            message = f'每日挑战·{label}已从 {start} 级升至 {start+1} 级'
        row['status'] = 'done'
        self.save_state()
        return {**row, 'message': message}
