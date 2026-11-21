"""Bounded observation retries; only explicitly verified navigation may be replayed."""
import time
from .policy import PageChanged,TaskBlocked


class NavigationRecovery:
    def wait_for_scene_loading(self,s,*,timeout=60):
        from .screen_loading import scene_loading
        if not scene_loading(s):return s
        self.note('场景正在加载，等待页面恢复；加载中不点击返回')
        until=time.monotonic()+timeout
        while scene_loading(s):
            self.b.guard(s)
            if time.monotonic()>=until:raise TaskBlocked(f'场景加载超过{timeout}秒，未在加载画面点击返回')
            self.b.sleep(.5);s=self.observe()
        return s

    def navigation_retry(self,label,attempt,screen=None):
        self.note(f'{label}，重试 {attempt}/3')
        row={'page':label,'attempt':attempt}
        self.report.setdefault('navigation_retries',[]).append(row)
        if screen is not None and self.report.get('folder'):
            name=f'navigation-retry-{len(self.report["navigation_retries"])}.png'
            self.b.save_screen(screen,self.report['folder']/name)
            row['screenshot']=name
        self.checkpoint()

    def navigation_input(self,s,action):
        """If a gift replaces the source before input, continue observing that step."""
        try:action(s)
        except PageChanged as error:
            from .transient_popups import is_star_gift
            if error.screen is None or not is_star_gift(error.screen):raise
            return self.dismiss_star_gift(error.screen)
        return None

    def wait_for_screen(self,predicate,label,*,timeout=12,retry_navigation=None):
        """Initial wait + three retries, never restart a task or replay spending.

        A navigation callback must re-check the known source page before input.
        Default recovery consists solely of fresh screenshots and OCR.
        """
        s=None
        for attempt in range(4):
            if attempt:
                self.navigation_retry(label+'尚未确认',attempt,s)
                if retry_navigation is not None:
                    s=self.observe();self.b.guard(s);self.resolve_path_event(s)
                    if predicate(s):return s
                    resumed=self.navigation_input(s,retry_navigation)
                    if resumed is not None:
                        self.b.guard(resumed);self.resolve_path_event(resumed)
                        if predicate(resumed):return resumed
            until=time.monotonic()+timeout
            while time.monotonic()<until:
                s=self.observe();self.b.guard(s);self.resolve_path_event(s)
                if predicate(s):return s
                self.b.sleep(.5)
        raise TaskBlocked(label+'仍未确认，已重试3次；保留现场')
