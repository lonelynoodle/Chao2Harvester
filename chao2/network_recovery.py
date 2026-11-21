"""Reconnect the current game request without replaying task actions."""
from datetime import datetime
from .policy import SafetyStop

NETWORK_PROMPT=r'^网络翻船中\s*[,，]\s*是否重试\s*[?？]$'
NETWORK_PROMPT_ROI=(380,240,570,150)
NETWORK_CONFIRM_ROI=(690,440,210,100)
NETWORK_CANCEL_ROI=(360,440,250,100)


def network_retry_button(s):
    if not s.find(NETWORK_PROMPT,NETWORK_PROMPT_ROI):return None
    if not s.find('^取消$',NETWORK_CANCEL_ROI):return None
    return s.find('^确定$',NETWORK_CONFIRM_ROI)


class NetworkRecovery:
    def recover_network_dialog(self,s):
        if not network_retry_button(s):return s
        rows=self.report.setdefault('network_recoveries',[])
        row={'task':self.active_task,'attempts':0,'status':'observed',
             'started':datetime.now().astimezone().isoformat()}
        rows.append(row)
        self.b.save_screen(s,self.report['folder']/f'network-retry-{len(rows)}.png')
        for attempt in range(3):
            self.b.check_stop()
            # Read directly through Backend so this observation cannot recurse
            # through Daily's popup handling. Never reuse a vanished button.
            fresh=self.b.observe();self.b.guard(fresh)
            button=network_retry_button(fresh)
            if not button:
                row.update(status='recovered',finished=datetime.now().astimezone().isoformat())
                self.checkpoint();return fresh
            self.note(f'检测到网络翻船，重试当前请求（{attempt+1}/3）')
            self.b.click_at(fresh,button.center,[NETWORK_PROMPT,'^取消$','^确定$'],
                            '网络翻船：重试当前请求')
            row['attempts']+=1;self.checkpoint()
            s=self.b.observe()
            if not network_retry_button(s):
                row.update(status='recovered',finished=datetime.now().astimezone().isoformat())
                self.checkpoint();return s
        row['status']='blocked';self.last_screen=s;self.checkpoint()
        raise SafetyStop('网络翻船连续重试3次仍未恢复，当前请求结果尚未确认')
