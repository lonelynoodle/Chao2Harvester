"""One-way overview navigation and optional selection by the visible card order."""
import re

from .backend import Screen,Word
from .policy import TaskBlocked,EncounterInterrupted


# Only verified arrows in the left daily column are used for navigation.
# Timed/independent entries (origin and giant) retain their own entry methods.
OVERVIEW_ROUTES={
    'exploration':('^探索指派$',('^探索$','剩余可指派怪兽')),
    'cocoon':('^永生之茧$',('^永生之茧$','^刷新$')),
    'copies':('^异象$',('^异象$','本周已获[取得]友好点数')),
    'hunt':('^狩猎$',('^狩猎$','^商店$','^传送$')),
    'main':('^世界关卡$',('敌方阵容','^首通奖励$','^排阵$')),
    'tribe':('^部落冒险$',('^部落$','^部落大厅$')),
    'rift':('^[凿幽]星裂痕$',('^[凿幽]星裂痕$', '当前通关','^匹配房间$','^创建队伍$')),
    'forest':('^黑暗森林$',('^黑暗森林$','^信息$')),
    'tower':('^浮空巨塔$',('选择挑战的塔',)),
    'arena':('^斗技场$',('^斗技场$','挑战次数')),
    'nest':('^[谜迷]之巢穴$',('^[谜迷]之巢穴$','^暴走旷野$')),
}
OVERVIEW_TITLES=r'^(?:探索指派|永生之茧|异象|狩猎|世界关卡|部落冒险|浮空巨塔|斗技场|[谜迷]之巢穴|[凿幽]星裂痕|黑暗森林|免费造唤|野生怪兽|深渊先遣)$'
# The 黑暗森林 row keeps its own state in the overview status column. A running
# exploration must never be panned or restarted, so read it before clicking.
FOREST_BUSY=r'探索中|正在探索|\d{1,2}:\d{2}:\d{2}'


def forest_overview_busy(text):
    return bool(text and re.search(FOREST_BUSY,text))


def overview_matches(s,patterns):
    matches=[]
    for key,pattern in patterns.items():
        # Exclude the quota column, duplicate labels, and rows behind the footer.
        w=s.find(pattern,roi=(350,80,180,490))
        if w and w.box[1]>=80:matches.append((key,w))
    return sorted(matches,key=lambda item:(item[1].center[1],item[1].center[0]))


def overview_fingerprint(s):
    # Timers and quantities change even when the list is clamped at its end.
    return tuple(sorted((w.text,round(w.center[1]/12)) for w in s.words
                        if re.fullmatch(OVERVIEW_TITLES,w.text) and
                        350<=w.center[0]<530 and 80<=w.center[1]<630))


class OverviewNavigation:
    def overview_prepared_for(self,task):
        return getattr(self,'_overview_ready',None)==task

    def read_overview_labels(self,s,patterns):
        # The slanted overview font can read 茧 as 萤. Confirm the original
        # pixels locally; do not accept arbitrary fuzzy task-name matches.
        if '^永生之茧$' in patterns.values() and not s.find('^永生之茧$',(350,80,180,490)):
            word=s.find('^永生之萤$',(350,80,180,490))
            if word:
                x,y,w,h=word.box
                text=self.b.read_text_crop(s,(x-4,y-4,w+8,h+8))
                if text=='永生之茧':
                    self.note('已通过局部识别确认永生之茧入口')
                    return Screen(s.image,[*s.words,Word(text,word.box,word.score)],s.when)
        return s

    def scroll_overview(self,s,*,retry=False,reverse=False):
        self.b.guard(s)
        if not s.has('^玩法概览$','^每日挑战$'):raise TaskBlocked('玩法概览列表已改变')
        x,duration=(700,800) if retry else (650,600)
        reason='玩法概览补查上方入口' if reverse else '玩法概览更换落点重试翻页' if retry else '玩法概览向下查找'
        start,end=(235,590) if reverse else (590,235)
        self.b.audit({'action':'swipe','reason':reason,'from':[x,start],'to':[x,end],
                      'before':overview_fingerprint(s),'status':'requested'})
        if not self.b.wait(self.b.controller.post_swipe(x,start,x,end,duration)).succeeded:
            raise TaskBlocked('玩法概览向下翻页失败')
        self.b.audit({'action':'swipe','reason':reason,'status':'sent'})
        self.b.sleep(1.2);after=self.observe();self.b.guard(after)
        if not after.has('^玩法概览$','^每日挑战$'):raise TaskBlocked('玩法概览翻页后页面改变，保留现场')
        self.b.audit({'action':'swipe','reason':reason,'status':'observed',
                      'after':overview_fingerprint(after),
                      'moved':overview_fingerprint(after)!=overview_fingerprint(s)})
        return after

    def find_overview_entry(self,patterns):
        s=self.task_panel();seen=set()
        for step in range(12):
            self.b.guard(s)
            if not s.has('^玩法概览$','^每日挑战$'):raise TaskBlocked('玩法概览列表已改变')
            s=self.read_overview_labels(s,patterns)
            matches=overview_matches(s,patterns)
            if matches:return s,*matches[0]
            fingerprint=overview_fingerprint(s)
            if fingerprint and fingerprint in seen:
                raise TaskBlocked('玩法概览意外回到已检查位置，未将翻页失败当作列表结束')
            if fingerprint:seen.add(fingerprint)
            if step==11:break
            before=s;s=self.scroll_overview(s)
            if overview_fingerprint(s)==fingerprint:
                # An accepted ADB swipe may be swallowed by a page animation.
                # Wait once, then use a second clear drag lane before concluding
                # the list is clamped. Never turn a stationary first page into
                # a false "entry missing" result.
                self.b.sleep(.8);s=self.observe();self.b.guard(s)
                if not s.has('^玩法概览$','^每日挑战$'):raise TaskBlocked('玩法概览等待翻页时页面改变')
                if overview_fingerprint(s)!=fingerprint:continue
                self.b.save_screen(before,self.report['folder']/'overview-scroll-before.png')
                self.b.save_screen(s,self.report['folder']/'overview-scroll-stalled.png')
                self.note('玩法概览本次未滚动，改换落点重试一次')
                s=self.scroll_overview(s,retry=True)
                self.b.save_screen(s,self.report['folder']/'overview-scroll-retry.png')
                if overview_fingerprint(s)==fingerprint:
                    if len(seen)>1:return self.find_overview_above(s,patterns)
                    raise TaskBlocked('玩法概览翻页未生效，尚未检查到后续入口；已保存前后截图')
        return None

    def find_overview_above(self,s,patterns):
        # Some client returns retain the old scroll offset. Only if the
        # downward search missed an entry, inspect the omitted upper portion.
        self.note('概览保留了之前的滚动位置，补查上方尚未找到的入口')
        for _ in range(12):
            before=overview_fingerprint(s)
            s=self.scroll_overview(s,reverse=True)
            s=self.read_overview_labels(s,patterns)
            matches=overview_matches(s,patterns)
            if matches:return s,*matches[0]
            if overview_fingerprint(s)==before:return None
        raise TaskBlocked('玩法概览补查上方未到达边界')

    def enter_overview(self,pattern,skip_when=None):
        self.note('在玩法概览中查找：'+pattern.strip('^$'))
        found=self.find_overview_entry({'target':pattern})
        if not found:raise TaskBlocked('玩法概览中未找到入口：'+pattern)
        s,_,w=found
        if pattern=='^黑暗森林$':
            self.forest_overview_state=s.region_text((535,w.center[1]-32,180,80))
            # A running exploration must not be entered or panned. Report it and
            # stop before clicking so the overview card stays untouched.
            if skip_when and skip_when(self.forest_overview_state):
                self.note('玩法概览显示森林正在探索，未点击前往，本任务跳过')
                return None
        self.b.click_at(s,(738,w.center[1]+30),['玩法概览','每日挑战'],'前往'+w.text)
        expected=next((anchors for route,anchors in OVERVIEW_ROUTES.values() if route==pattern),None)
        # The map may appear briefly during a jump. A navigation click is not
        # enough: wait for the actual destination without another back/click.
        for _ in range(20):
            q=self.observe();self.b.guard(q)
            self.resolve_path_event(q)
            if pattern=='^浮空巨塔$' and self.tower_territory(q):
                # An unsolicited gift can absorb the overview jump too.
                # Recover directly from the verified territory, without
                # reopening or scrolling the task overview.
                return self.enter_tower_selector(q)
            if pattern=='^世界关卡$':
                from .world_events import is_map_choice
                from .reward_collection import is_map_story
                if is_map_choice(q):q=self.open_main_choice(q)
                # Lore may cover the destination after travel. Its title and
                # body vary; recognise the shared card layout before checking
                # the stage controls underneath it.
                if is_map_story(q):q=self.close_map_story(q)
            if not q.has('^玩法概览$','^每日挑战$') and (not expected or q.has(*expected)):
                return self.claim_tribe_occupation(q) if pattern=='^部落冒险$' else q
            self.b.sleep(.8)
        if pattern=='^世界关卡$':
            from .workflows import is_world
            if is_world(q):
                self.b.save_screen(q,self.report['folder']/'main-overview-world.png')
                self.note('世界关卡跳转已到地图，继续查找可见的未通关节点')
                return q
        raise TaskBlocked('玩法概览跳转未完成：'+w.text)

    def overview_entry(self,key,*,reason='地图视觉入口未确认'):
        """Last-resort entrance through 任务挑战 → 玩法概览.

        The overview list is reached from the HUD button, then located by OCR
        while scrolling, so it does not depend on the world-map labels that
        full-frame OCR occasionally drops.
        """
        route=OVERVIEW_ROUTES.get(key)
        if route is None:raise TaskBlocked('玩法概览中没有该入口：'+key)
        self.note(reason+'，改用任务挑战→玩法概览进入')
        return self.enter_overview(route[0])

    def next_daily_task(self,pending):
        if not self.b.settings['unordered_tasks']:return pending[0]
        # Wake is always first and reward collection stays after the activities.
        if 'startup' in pending:return 'startup'
        unlisted=getattr(self,'_overview_unlisted',set())
        candidates={key:OVERVIEW_ROUTES[key][0] for key in pending
                    if key in OVERVIEW_ROUTES and key not in unlisted}
        if candidates:
            found=self.find_overview_entry(candidates)
            if found:
                _,key,word=found
                self._overview_ready=key
                self.note('按玩法概览选择：'+word.text)
                return key
            # Do not repeat an unsuccessful full scan for each remaining item.
            self._overview_unlisted=unlisted|set(candidates)
            self.note('剩余任务未在概览中找到，继续使用各自入口')
            self.home()
        # Inspect new bag items after rewards have introduced their drops.
        return next((key for key in pending if key not in ('rewards','other')),
                    'rewards' if 'rewards' in pending else pending[0])
