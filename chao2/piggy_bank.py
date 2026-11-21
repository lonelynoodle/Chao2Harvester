"""A single, explicitly enabled 50-diamond wooden-hammer transaction per run."""
import re
from datetime import datetime

from .policy import TaskBlocked, SafetyStop, PageChanged, IsolatedTaskError
from .reward_collection import reward_overlay
from .compact_balance import balance_bounds,balance_delta_possible,read_displayed_balance,read_fixed_balance

PIGGY_NAME=r'^[屯囤电]{1,2}扑满$'
STORED=r'^已储存(\d+)钻石和(\d+)金币$'
STORED_LABEL=r'^已储存(\d+)[钻沾]石和(\d+)金币$'
OFFER=r'^是否消耗50钻石购买1木[锤棰][?？]?$'
LEFT_CLAIM=(400,565,285,90)
WORLD_WALLET_ROI=(235,10,90,32)


def piggy_cancel_button(s):
    """Recognize only a wood-hammer buy/claim dialog's cancel action."""
    if not s.find('^活动$',(90,0,160,65)):return None
    purchase=s.find(r'^是否消耗\d+钻石购买\d+木[锤棰][?？]?$',(350,240,600,90))
    claim=s.find('^可获得奖励$',(500,180,280,65))
    if not ((purchase and s.find('^确定$',(680,440,250,100))) or
            (claim and s.find('^领取$',(680,440,250,100)))):return None
    return s.find('^取消$',(350,440,250,100))


def is_piggy_page(s):
    return bool(s.find('^活动$',(90,0,160,65)) and
        s.find(PIGGY_NAME,(190,100,340,145)) and
        s.find(STORED_LABEL,(510,390,440,45)) and
        s.find('^每次领取奖励消耗200活跃之星$',(520,430,410,50)) and
        s.find('^1钻石和1000金币$',(940,255,280,60)) and
        s.find('^立即领取$',LEFT_CLAIM) and
        not s.find('^取消$|^规则$|^获得奖励$'))


def recover_piggy_storage(b,s):
    """Restore the full stored sentence only after two independent crop reads."""
    if is_piggy_page(s) or b.tasker is None:return s
    if (not s.find('^活动$',(90,0,160,65)) or
            not s.find(PIGGY_NAME,(190,100,340,145)) or
            not s.find('^每次领取奖励消耗200活跃之星$',(520,430,410,50)) or
            not s.find('^1钻石和1000金币$',(940,255,280,60)) or
            not s.find('^立即领取$',LEFT_CLAIM) or
            s.find('^取消$|^规则$|^获得奖励$')):return s
    reads=[re.sub(r'\s','',b.read_text_crop(s,roi)) for roi in ((580,395,290,35),(590,395,275,40))]
    match=re.fullmatch(STORED,reads[0])
    if not match or reads[0]!=reads[1]:return s
    stored,gold=map(int,match.groups())
    if gold!=stored*1000:return s
    partial=s.find(r'^已储存(\d+)(?:钻|沾)?石和(\d+)金币$',(510,390,440,45))
    if partial:
        original=re.fullmatch(r'^已储存(\d+)(?:钻|沾)?石和(\d+)金币$',partial.text)
        if tuple(map(int,original.groups()))!=(stored,gold):return s
    from .backend import Screen,Word
    fresh=Screen(s.image,list(s.words),s.when)
    fresh.words.append(Word(reads[0],[580,395,290,35],.99))
    return fresh


def piggy_purchase_confirmation(s,pending):
    if not isinstance(pending,dict) or pending.get('stored',0)<200 or pending.get('stock')!=0:
        return None
    if pending.get('price')!=50 or pending.get('quantity')!=1:return None
    if not (s.find('^活动$',(90,0,160,65)) and s.find(OFFER,(350,240,600,90)) and
            s.find(r'^今天还能购买\d+次$',(450,305,400,60)) and
            s.find('^取消$',(350,440,250,100))):return None
    return s.find('^确定$',(680,440,250,100))


def read_piggy_view(b,s):
    if not is_piggy_page(s):raise TaskBlocked('屯屯扑满页面尚未确认')
    word=s.find(STORED_LABEL,(510,390,440,45))
    if word.score<.8:raise TaskBlocked('屯屯扑满储存奖励未读清')
    raw=re.fullmatch(STORED_LABEL,word.text)
    stored,gold=map(int,raw.groups())
    # Read the explicit stored-reward sentence twice. The progress slash is
    # frequently absent from OCR, so it cannot be used to guess a balance.
    local=re.sub(r'\s','',b.read_text_crop(s,(580,395,290,35)))
    precise=re.fullmatch(STORED,local)
    if not precise or tuple(map(int,precise.groups()))!=(stored,gold) or gold!=stored*1000:
        raise TaskBlocked('屯屯扑满储存奖励两次识别不一致')
    if local!=word.text:
        x,y,w,h=word.box
        if re.sub(r'\s','',b.read_text_crop(s,(x-5,y-5,w+10,h+10)))!=local:
            raise TaskBlocked('屯屯扑满储存奖励的钻石文字未核实')
    if not b.match_template(s,'piggy-wood-top.png',[995,0,70,60],.9):
        raise TaskBlocked('木锤币种未确认，未使用金锤')
    # Cover the entire stock field before a tight read so a missing leading
    # digit cannot turn a multi-digit balance into an apparent zero.
    stock=b.read_number(s,(1050,5,80,34))
    if stock is None:
        stock=b.read_number(s,(1090,5,39,34))
        if stock is None:
            # The stock-field underline can be recognized as "_1". Detect
            # the actual digit at two scales; do not strip guessed symbols.
            first=b.read_text_region(s,(1090,5,39,34),scale=3,threshold=.8)
            second=b.read_text_region(s,(1090,5,39,34),scale=2,threshold=.8)
            if first.isdigit() and first==second:stock=int(first)
        # A single-digit stock needs less padding for OCR, including the
        # newly purchased hammer. Both crops must agree and no leading
        # white digit may be present outside the tight crop.
        if stock is None or not 0<=stock<=9 or b.read_number(s,(1105,10,24,28))!=stock:
            raise TaskBlocked('木锤库存未读清')
        left=s.image[10:35,1050:1104]
        if (left.min(axis=2)>180).any():raise TaskBlocked('木锤库存可能漏读前位数字')
    if stock<0 or stock>9999:raise TaskBlocked('木锤库存无效')
    quantity=b.read_number(s,(465,498,92,46))
    if quantity!=1 or b.read_number(s,(491,502,40,41))!=1:
        raise TaskBlocked('木锤领取数量未确认是1，未购买或领取')
    if not b.match_template(s,'piggy-wood-claim.png',[300,560,90,85],.9):
        raise TaskBlocked('普通木锤领取按钮未确认')
    return {'stored':stored,'gold':gold,'stock':stock,'quantity':quantity}


def read_piggy_offer(b,s,pending):
    button=piggy_purchase_confirmation(s,pending)
    if not button:raise TaskBlocked('未确认50钻石购买1木锤，未购买')
    price=b.read_number(s,(801,498,30,27))
    if price!=50 or not b.match_template(s,'piggy-diamond-confirm.png',[770,495,30,35],.9):
        raise TaskBlocked('木锤确认按钮的50钻石费用未核实')
    quota=s.find(r'^今天还能购买\d+次$',(450,305,400,60))
    remaining=int(re.search(r'\d+',quota.text)[0])
    balance=read_displayed_balance(b,s,(1150,0,130,55))
    return {'remaining':remaining,'balance':balance,'button':button}


def piggy_claim_offer(b,s,row):
    if row.get('stored_before_claim',0)<200 or row.get('stock_before_claim',0)<1 or row.get('quantity')!=1:
        return None
    if not (s.find('^活动$',(90,0,160,65)) and s.find('^可获得奖励$',(500,180,280,65)) and
            s.find('^取消$',(350,440,250,100)) and s.find('^200$',(535,295,95,55)) and
            s.find('^200000$',(635,295,120,55))):return None
    button=s.find('^领取$',(680,440,250,100))
    if not button:return None
    if (b.read_number(s,(565,306,50,30))!=200 or b.read_number(s,(649,305,83,31))!=200000 or
            b.read_number(s,(805,498,20,25))!=1):return None
    for name,roi in [('piggy-wood-confirm.png',[775,495,30,35]),
                     ('piggy-diamond-reward.png',[565,260,45,45]),
                     ('piggy-gold-reward.png',[668,260,45,45])]:
        if not b.match_template(s,name,roi,.9):return None
    return button


class PiggyBank:
    def piggy_view(self,s=None):
        for attempt in range(4):
            s=self.observe() if s is None or attempt else s
            self.b.guard(s)
            try:return s,read_piggy_view(self.b,s)
            except TaskBlocked:
                if attempt==3:raise
                self.navigation_retry('屯屯扑满奖励或木锤库存尚未确认',attempt+1,s)
                self.b.sleep(.5)

    def piggy_journal(self,row,phase):
        row['phase']=phase
        self.state['piggy_pending']={**row,'run_folder':str(self.report['folder'])}
        self.save_state();self.checkpoint()

    def piggy_wallet(self):
        world=self.home()
        return read_fixed_balance(self.b,world,WORLD_WALLET_ROI)

    def cancel_failed_piggy_dialog(self):
        s=self.b.observe()
        if piggy_cancel_button(s) is None:return
        previous=getattr(self.b,'piggy_cancel_only',False)
        self.b.piggy_cancel_only=True
        try:
            self.b.click_text(s,'^取消$',roi=(350,440,250,100))
            self.wait_for_screen(lambda q:piggy_cancel_button(q) is None,
                                 '退出未完成的扑满确认窗口',timeout=4)
        finally:self.b.piggy_cancel_only=previous

    def collect_piggy_bank(self):
        try:return self._collect_piggy_bank()
        except (TaskBlocked,PageChanged) as error:
            message=str(error)
            if self.state.get('piggy_pending'):
                message+='；屯屯扑满交易已提交或待核实，保留记录，不重复购买或领取'
                if self.state['piggy_pending'].get('phase')=='buy_requested':
                    self.report['piggy_spend_unconfirmed']=True
            row=self.report.setdefault('other_tasks',{}).setdefault('piggy_bank',{})
            row.update(status='blocked',message=message)
            self.checkpoint();self.cancel_failed_piggy_dialog()
            raise IsolatedTaskError(message) from error

    def _collect_piggy_bank(self):
        if not self.options['other']['piggy_bank']:
            raise SafetyStop('未开启屯屯扑满任务，未购买或使用木锤')
        previous=self.report.get('other_tasks',{}).get('piggy_bank',{})
        if previous.get('claimed')==1:return previous
        if self.state.get('piggy_pending'):
            raise TaskBlocked('上次屯屯扑满交易尚未核实，保留记录，不重复购买或敲开')
        row={'status':'running','spent':0,'claimed':0,'price':50,'quantity':1}
        self.report.setdefault('other_tasks',{})['piggy_bank']=row
        before=self.piggy_wallet();row['diamonds_before']=before
        s,view=self.piggy_view(self.activity_tab('屯屯扑满'));row.update(view)
        if view['stored']<200:
            row.update(status='skipped',message=f'屯屯扑满储存{view["stored"]}，不足200，未购买或使用木锤')
            return row
        if view['stock']==0 and balance_bounds(before)[0]<50:
            row.update(status='skipped',message='屯屯扑满钻石不足50，未购买木锤')
            return row
        s,fresh=self.piggy_view()
        if fresh!=view:raise TaskBlocked('屯屯扑满操作前余额发生变化，未购买或领取')
        if view['stock']==0:
            self.b.piggy_purchase_pending=row
            try:
                self.b.click_at(s,(1034,31),['^活动$',PIGGY_NAME,STORED_LABEL],'打开木锤购买确认')
                s=self.wait_for_screen(lambda q:piggy_purchase_confirmation(q,row) is not None,
                    '50钻石木锤购买确认',timeout=4)
                offer=read_piggy_offer(self.b,s,row)
                if not balance_delta_possible(before,offer['balance'],0):raise TaskBlocked('木锤购买前钻石余额变化，未购买')
                if offer['remaining']<1:
                    self.b.click_text(s,'^取消$',roi=(350,440,250,100))
                    row.update(status='skipped',message='屯屯扑满今日木锤购买次数已用完')
                    return row
                self.b.save_screen(s,self.report['folder']/'piggy-buy-before.png')
                self.report['piggy_spend_unconfirmed']=True;self.report['diamond_spend']=None
                self.piggy_journal(row,'buy_requested')
                self.note('屯屯扑满储存已达200，购买1个木锤，费用50钻石')
                # Exactly one confirmation; a missing response never replays it.
                self.b.click_text(s,'^确定$',roi=(680,440,250,100))
                for _ in range(16):
                    q=self.observe();self.b.guard(q)
                    if reward_overlay(q):
                        self.b.save_screen(q,self.report['folder']/'piggy-hammer-receipt.png')
                        q,_=self.dismiss_collection_reward(q)
                    if is_piggy_page(q):
                        q,after=self.piggy_view(q)
                        if after['stock']==1 and after['stored']==view['stored']:break
                    self.b.sleep(.5)
                else:raise TaskBlocked('木锤购买结果未核实，未重复购买')
            finally:self.b.piggy_purchase_pending=None
            balance=self.piggy_wallet()
            row['diamonds_after_purchase']=balance
            if not balance_delta_possible(before,balance,-50):raise TaskBlocked('木锤购买后的钻石余额变化未核实为50，保留交易记录')
            row['spent']=50;row['diamonds_after_purchase']=balance
            self.report['piggy_diamond_spend']=50;self.report['piggy_spend_unconfirmed']=False
            self.report['diamond_spend']=50+self.report.get('merchant_diamond_spend',0)
            self.piggy_journal(row,'purchased')
            s,view=self.piggy_view(self.activity_tab('屯屯扑满'))
        return self._claim_piggy_bank(row,view,balance if row['spent'] else before)

    def _claim_piggy_bank(self,row,view,balance_before_claim):
        if not self.options['other']['piggy_bank']:
            raise SafetyStop('未开启屯屯扑满，未领取')
        if row.get('claimed') or self.state.get('piggy_pending',{}).get('phase') not in (None,'purchased'):
            raise TaskBlocked('屯屯扑满仍有未核实交易，未重复领取')
        if view['stored']<200 or view['stock']<1:
            raise TaskBlocked('木锤领取前奖励不足200或库存改变，未敲开')
        s,fresh=self.piggy_view()
        if fresh!=view:raise TaskBlocked('敲开前屯屯扑满余额变化，未领取')
        row.update(stored_before_claim=view['stored'],stock_before_claim=view['stock'],
                   diamonds_before_claim=balance_before_claim)
        self.b.save_screen(s,self.report['folder']/'piggy-claim-before.png')
        self.piggy_journal(row,'claim_preview')
        self.b.click_text(s,'^立即领取$',roi=LEFT_CLAIM)
        s=self.wait_for_screen(lambda q:piggy_claim_offer(self.b,q,row) is not None,
            '1木锤换200钻石及200000金币',timeout=4)
        return self._confirm_piggy_claim(row,view,balance_before_claim,s)

    def _confirm_piggy_claim(self,row,view,balance_before_claim,s):
        if self.state.get('piggy_pending',{}).get('phase')!='claim_preview' or not piggy_claim_offer(self.b,s,row):
            raise TaskBlocked('屯屯扑满领取奖励或1木锤费用未核实，未确认')
        self.b.save_screen(s,self.report['folder']/'piggy-claim-confirm.png')
        self.piggy_journal(row,'claim_requested')
        self.b.click_text(s,'^领取$',roi=(680,440,250,100))
        return self._verify_piggy_claim(row,view,balance_before_claim)

    def _verify_piggy_claim(self,row,view,balance_before_claim):
        if self.state.get('piggy_pending',{}).get('phase')!='claim_requested':
            raise TaskBlocked('没有待核实的屯屯扑满领取记录')
        receipt=bool(row.get('reward_text'))
        for _ in range(20):
            q=self.observe();self.b.guard(q)
            if reward_overlay(q):
                receipt=True;row['reward_text']=q.text
                self.b.save_screen(q,self.report['folder']/'piggy-reward.png')
                q,_=self.dismiss_collection_reward(q)
            if is_piggy_page(q):
                q,after=self.piggy_view(q)
                if after['stored']==view['stored']-200 and after['stock']==view['stock']-1:
                    row['stored_remaining']=after['stored'];row['stock_remaining']=after['stock']
                    self.b.save_screen(q,self.report['folder']/'piggy-claimed.png');break
            self.b.sleep(.5)
        else:raise TaskBlocked('屯屯扑满领取结果未核实，未重复敲开')
        balance=self.piggy_wallet()
        if not balance_delta_possible(balance_before_claim,balance,200):
            raise TaskBlocked('屯屯扑满200钻石到账余额未核实，未重复领取')
        row.update(status='done',phase='completed',claimed=1,diamonds_received=200,
                   diamonds_after=balance,receipt_observed=receipt,
                   message=f'屯屯扑满已敲开1次，获得200钻石；购买花费{row["spent"]}钻石，剩余储存{row["stored_remaining"]}')
        self.day.setdefault('piggy_claims',[]).append({**row,'time':datetime.now().astimezone().isoformat()})
        self.state.pop('piggy_pending',None);self.save_state();self.checkpoint()
        return row
