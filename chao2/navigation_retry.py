"""Bounded observation retries; only explicitly verified navigation may be replayed."""
import time
from .policy import TaskBlocked


class NavigationRecovery:
    def navigation_retry(self,label,attempt,screen=None):
        self.note(f'{label}，重试 {attempt}/3')
        row={'page':label,'attempt':attempt}
        self.report.setdefault('navigation_retries',[]).append(row)
        if screen is not None and self.report.get('folder'):
            name=f'navigation-retry-{len(self.report["navigation_retries"])}.png'
            self.b.save_screen(screen,self.report['folder']/name)
            row['screenshot']=name
        self.checkpoint()

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
                    retry_navigation(s)
            until=time.monotonic()+timeout
            while time.monotonic()<until:
                s=self.observe();self.b.guard(s);self.resolve_path_event(s)
                if predicate(s):return s
                self.b.sleep(.5)
        raise TaskBlocked(label+'仍未确认，已重试3次；保留现场')
