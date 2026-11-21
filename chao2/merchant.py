"""The observed world-pathing merchant dialogue, separate from task battles."""
import re
import random
import time

from .policy import SafetyStop, UserStopped, TaskBlocked
from .merchant_settings import MERCHANT_ITEMS,merchant_options
from .trigger_events import require_event_enabled


MERCHANT_TITLE = r'^神秘商人?$'
TITLE_ROI = (0, 0, 300, 85)
CHOICE_HEADER_ROI = (650, 0, 500, 75)
CHOICE_ROI = (650, 80, 510, 375)
BODY_ROI = (85, 550, 1100, 85)
ARROW_ROI = (1125, 635, 70, 65)
# Only unequivocal refusals/exits. Do not treat any sentence containing
# "不" or "离开" as safe (e.g. "购买后离开" still authorizes a purchase).
SKIP_CHOICE = re.compile(
    r'^(?:不管[它他她]离开|停下离开|表示下次再去|[一=]口拒绝|'
    r'拒绝|谢绝好意|拒绝(?:帮助|交易|购买)|'
    r'(?:转身|直接|就此|立即)?离开|不了|不需要|不买|不购买|不用了(?:谢谢)?)$')


def merchant_title(s):
    return s.find(MERCHANT_TITLE, TITLE_ROI)


def is_merchant_shop(s):
    # The captured shop OCR drops 人 from the title. Require its purchase
    # notice AND its bottom-right leave button; never recognize by title alone.
    return bool(merchant_title(s) and
                s.find('限购.*购买后神秘商人消失', (85, 595, 820, 45)) and
                s.find('^离开$', (920, 630, 290, 75)))


def is_merchant_reward(s,*,battle_finished=False):
    return bool((merchant_title(s) or battle_finished) and
                s.find('^获得奖励$',(400,75,500,150)) and
                s.find('^点击空白位置关闭$',(430,570,430,100)) and
                not s.find('^退出$|^挑战$|^前往挑战$|^请选择$'))


def is_merchant(s):
    if not merchant_title(s):
        return False
    tags = sum(bool(s.find('^'+label+'$', (580, 485, 620, 55)))
               for label in ('掠夺', '交易', '物品奖励', '狩猎奖励', '碎片奖励'))
    return tags >= 3 or is_merchant_shop(s) or is_merchant_reward(s)


def merchant_body(s):
    words = sorted((w for w in s.words if
                    BODY_ROI[0] <= w.center[0] < BODY_ROI[0]+BODY_ROI[2] and
                    BODY_ROI[1] <= w.center[1] < BODY_ROI[1]+BODY_ROI[3]),
                   key=lambda w: (w.center[1]//18, w.box[0]))
    return re.sub(r'[^\w\u4e00-\u9fff]', '', ''.join(w.text for w in words))


def merchant_choices(s):
    # Tags such as "物品奖励" are descriptive, not buttons. Exclude them.
    return sorted((w for w in s.words if
                   CHOICE_ROI[0] <= w.center[0] < CHOICE_ROI[0]+CHOICE_ROI[2] and
                   CHOICE_ROI[1] <= w.center[1] < CHOICE_ROI[1]+CHOICE_ROI[3] and
                   re.search(r'[\u4e00-\u9fff]{2}', w.text)),
                  key=lambda w: w.center[1])


def merchant_choice(s, mode='skip', random_choices=None):
    if not is_merchant(s) or not s.find('^请选择$', CHOICE_HEADER_ROI):
        return None
    choices = merchant_choices(s)
    if mode == 'random':
        candidates=[w for w in choices if w.score>=.8 and
                    (SKIP_CHOICE.fullmatch(re.sub(r'[\s，。！!？?,、]','',w.text)) or
                     not re.search(r'购买|花费|消耗|支付|充值|兑换|钻石|极化石|[￥¥]',w.text))]
        if not candidates or len({w.text for w in candidates})!=len(candidates):return None
        # Freeze this dialogue's selection across OCR reads and swallowed-click
        # retries. Re-rolling every frame prevents stable action recognition.
        cache=random_choices if random_choices is not None else {}
        key=(s.region_text((70,485,300,55)),merchant_body(s),tuple(w.text for w in choices))
        if key not in cache:cache[key]=random.choice(candidates).text
        return next((w for w in candidates if w.text==cache[key]),None)
    # Leave at the first opportunity. This encounter's observed destination is
    # a diamond shop, so the routine must never select "进店" or "交易".
    if mode != 'buy':
        matches=[w for w in choices if SKIP_CHOICE.fullmatch(re.sub(r'[\s，。！!？?,、]','',w.text))]
        if matches:return matches[0]
    # Resume a user-opened intermediate 转转 conversation only along the
    # observed no-cost branch, until a leave option becomes available.
    body = merchant_body(s)
    narrator = body in ('它绕着你转了两圈然后停在你面前',
                        '它绕着你转了四圈然后停下来非常期待地看着你',
                        '它开始不等你停下来和你一起转了起来', '它跟上了你的速度')
    if not narrator and not s.find(r'^[`·]?转转$', (70, 485, 300, 55)):
        return None
    routes = {
        frozenset(('不管它离开', '准备发起攻击', '绕着它转一圈')): '绕着它转一圈',
        frozenset(('再绕着它转三圈', '再绕个正方形')): '再绕着它转三圈',
        frozenset(('继续绕着它转五圈', '突然原地转五圈')): '继续绕着它转五圈',
        frozenset(('加速', '减速')): '加速',
        frozenset(('继续转', '帮它填')): '帮它填',
        frozenset(('继续加速', '停下离开')): '继续加速',
        frozenset(('进店', '表示下次再去')): '进店',
    }
    wanted = routes.get(frozenset(w.text for w in choices))
    matches = [w for w in choices if w.text == wanted]
    return matches[0] if len(matches) == 1 else None


def merchant_action(b, s, mode='skip', random_choices=None,*,battle_finished=False):
    """Return a verified, free action. None means observe again, never guess."""
    if is_merchant_reward(s,battle_finished=battle_finished):
        anchors=['^获得奖励$','^点击空白位置关闭$']
        if merchant_title(s):anchors.insert(0,MERCHANT_TITLE)
        return ('reward',(640,660),anchors,
                '关闭神秘商人奖励后继续')
    if not is_merchant(s):
        return None
    if is_merchant_shop(s):
        return ('shop', s.find('^离开$', (920, 630, 290, 75)).center,
                [MERCHANT_TITLE, '^离开$', '限购.*购买后神秘商人消失'], '离开神秘商人商店（不购买）')
    choices = merchant_choices(s)
    if s.find('^请选择$', CHOICE_HEADER_ROI) or choices:
        choice = merchant_choice(s, mode, random_choices)
        if choice:
            return ('choice:'+choice.text, choice.center,
                    [MERCHANT_TITLE, '^请选择$', '^'+re.escape(choice.text)+'$'],
                    ('神秘商人随机选择：' if mode=='random' else '神秘商人选择：')+choice.text)
        # Includes the animation with a header but not-yet-visible options.
        return None
    # An unreadable choice header must not turn the still-visible dialogue
    # arrow into a default option click. Check its pixels as well as the OCR.
    if b.match_template(s, 'merchant-choice-header.png', list(CHOICE_HEADER_ROI), .9):
        return None
    if merchant_body(s) and (b.match_template(s, 'merchant-dialogue-arrow.png', list(ARROW_ROI), .86) or
                            b.match_template(s, 'merchant-dialogue-arrow-ready.png', list(ARROW_ROI), .9)):
        return ('dialogue', (1155, 663), [MERCHANT_TITLE], '继续神秘商人对话')
    return None


def merchant_return_page(s):
    # Only a positively recognized destination ends an event; blank transition
    # frames and reward tags never count as completion or a task victory.
    from .workflows import is_world
    from .activities import is_copy_list
    from .anomalies import is_event_panel
    from .world_events import is_ambush,is_map_choice
    from .plane_gate import plane_gate_window
    if merchant_title(s) or s.find('^获得奖励$',(400,75,500,150)):
        return None
    if plane_gate_window(s):return 'plane_gate'
    if is_world(s):
        return 'world'
    if is_ambush(s):
        return 'ambush'
    if is_map_choice(s):
        return 'map_choice'
    if is_copy_list(s) or is_event_panel(s):
        return 'events'
    if s.has('敌方阵容', '^排阵$', '^挑战$|^前往挑战$'):
        return 'detail'
    return None


def merchant_battle_phase(s):
    # Called only within an observed merchant event. Dialogue tags/buttons
    # such as 战斗/物品奖励 are not proof that a battle has started.
    from .battle_takeover import takeover_phase,existing_result
    if is_merchant(s) or merchant_return_page(s):return None
    phase=takeover_phase(s)
    if phase=='result':return phase if existing_result(s) in ('victory','failed') else None
    return phase if phase in ('battle','paused') else None


class MerchantEvent:
    def finish_merchant_battle(self,s,row):
        self.b.guard(s)
        phase=merchant_battle_phase(s)
        if phase is None:raise TaskBlocked('神秘商人战斗或胜败结果未确认')
        battles=row.setdefault('battles',[])
        battle={'status':'waiting','initial_phase':phase,'outcome':None,
                'counted_as_source_task_attempt':False}
        battles.append(battle);row['battle_count']=len(battles)
        index=len(self.report.get('battle_takeovers',[]))
        battle['takeover_index']=index
        previous=self.active_task;self.active_task='merchant'
        self.note('神秘商人触发战斗，等待实际胜败并退出结算，再继续商人后续流程')
        self.checkpoint()
        try:
            # Reuse fresh-screen result exit/retry, network recovery and pause
            # handling without counting this fight as the interrupted task.
            returned=self.finish_existing_battle(s,
                timeout_seconds=int(self.b.settings.get('battle_timeout_seconds',240)),
                label='神秘商人战斗')
            takeover=self.report['battle_takeovers'][index]
            battle['status']=takeover['status']
            outcome=takeover.get('result')
            summary={'victory':'胜利','failed':'败退'}.get(outcome,'已返回，未观察到最终胜败')
            self.note('神秘商人战斗'+summary+'；继续商人后续对话或返回原任务，不重复挑战')
            return returned
        except (TaskBlocked,SafetyStop,UserStopped) as error:
            battle.update(status='stopped' if isinstance(error,UserStopped) else 'blocked',reason=str(error))
            raise
        finally:
            takeovers=self.report.get('battle_takeovers',[])
            if len(takeovers)>index:battle['outcome']=takeovers[index].get('result')
            self.active_task=previous
            self.checkpoint()

    def handle_merchant(self, s):
        self.b.guard(s)
        if not is_merchant(s):
            raise SafetyStop('神秘商人页面未确认，保留现场')
        require_event_enabled(self.b.settings,'merchant')
        rows = self.report.setdefault('merchant_events', [])
        number = len(rows)+1
        options = merchant_options(self.b.settings)
        row = {'source_task': self.active_task, 'mode': options['mode'], 'status': 'running', 'actions': [],
               'purchases': 0, 'battle_count': 0}
        rows.append(row)
        self.b.save_screen(s, self.report['folder']/f'merchant-{number}-entry.png')
        if options['mode'] == 'stop':
            row.update(status='stopped', reason='按神秘商人设置自动停止，保留现场')
            self.note(row['reason']);self.checkpoint()
            raise UserStopped(row['reason'])
        buy = (options['mode'] == 'buy' and any(i['enabled'] for i in options['items']) and
               options['diamond_budget'] > self.report.get('merchant_diamond_spend', 0))
        behavior='按所选物品及预算检查商店' if buy else ('随机点击对话，不购买' if options['mode']=='random' else '跳过不购买')
        self.note('寻路遇到神秘商人，'+behavior+'；随后继续原任务')
        self.checkpoint()
        return self._continue_merchant_event(s,row,options,buy,number)

    def _continue_merchant_event(self,s,row,options,buy,number):
        # Keep the event context through combat, settlement and follow-up
        # dialogue. Explicit recovery can continue an already observed event
        # here without replaying its old choices or starting another fight.
        deadline = time.monotonic()+240
        previous = None
        acted = {}
        random_choices = {}
        last_kind = None
        last_body = None
        idle = 0
        stable = 0
        destination = None
        reward_pending = None
        try:
            while time.monotonic() < deadline:
                self.b.guard(s)
                if merchant_battle_phase(s):
                    started=time.monotonic()
                    s=self.finish_merchant_battle(s,row)
                    # Combat has its own timeout; don't spend the dialogue's
                    # budget waiting for it, or hit the 12-read idle limit.
                    deadline+=time.monotonic()-started
                    previous=None;last_kind=None;last_body=None
                    idle=stable=0;destination=None
                    continue
                battle_finished=any(b['status']=='settled' for b in row.get('battles',[]))
                returned = merchant_return_page(s)
                if reward_pending is not None and not is_merchant_reward(s,battle_finished=battle_finished) and (is_merchant(s) or returned):
                    reward_pending['status']='closed'
                    row['rewards_closed']=row.get('rewards_closed',0)+1
                    reward_pending=None
                if returned and returned == destination:
                    row.update(status='completed', returned_to=returned)
                    self.b.save_screen(s, self.report['folder']/f'merchant-{number}-exit.png')
                    purchase = row.get('purchase', {})
                    summary = ('已购买'+purchase['label']+'，消耗'+str(purchase['price'])+'钻石'
                               if row['purchases'] else '未购买')
                    self.note('神秘商人已结束，'+summary+'；重新定位原任务，不计入挑战次数')
                    self.checkpoint()
                    return s
                destination = returned
                if buy and is_merchant_shop(s):
                    offer = select_merchant_offer(self.b, s, options,
                                                  self.report.get('merchant_diamond_spend', 0))
                    if offer:
                        s = self.purchase_merchant_item(s, row, offer, options)
                        buy = False
                        previous = None;idle = 0
                        continue
                    self.note('神秘商人没有符合勾选物品、余额及预算的商品，跳过不购买')
                    buy = False
                mode='random' if options['mode']=='random' else ('buy' if buy else 'skip')
                action = merchant_action(self.b, s, mode, random_choices,battle_finished=battle_finished)
                body = merchant_body(s)
                key = (action[0], body, tuple(w.text for w in merchant_choices(s))) if action else None
                stable=stable+1 if key is not None and key==previous else int(key is not None)
                attempts=acted.get(key,0)
                # Read through lingering animations before retrying a free
                # skip/leave/advance. A click can merely finish the text reveal
                # or be swallowed; a permanent "already clicked" set deadlocks.
                stale_choice_body = (last_kind is not None and last_kind.startswith('choice:') and
                                     action and action[0] == 'dialogue' and body == last_body)
                retry = not buy and 0<attempts<4 and stable>=4 and idle>=4
                fresh = attempts==0 and stable>=2 and (not stale_choice_body or (not buy and stable>=4))
                if key is not None and (fresh or retry):
                    kind, point, anchors, reason = action
                    if kind=='reward' and attempts==0:
                        receipts=row.setdefault('rewards',[])
                        path=self.report['folder']/f'merchant-{number}-reward-{len(receipts)+1}.png'
                        self.b.save_screen(s,path)
                        reward_pending={'status':'observed','screenshot':str(path),'text':s.text}
                        receipts.append(reward_pending)
                    if retry:
                        row.setdefault('retries',[]).append({'action':reason,'attempt':attempts})
                        self.note(f'神秘商人仍在当前页面，重试 {attempts}/3：'+reason)
                    self.note(reason)
                    self.b.click_at(s, point, anchors, reason)
                    row['actions'].append(reason)
                    acted[key]=attempts+1
                    last_kind, last_body = kind, body
                    idle = 0;stable = 0
                    self.checkpoint()
                else:
                    idle += 1
                if not buy and attempts>=4 and stable>=4:
                    raise SafetyStop('神秘商人同一步已重试3次仍未推进，保留现场；未购买')
                if idle >= 12:
                    raise SafetyStop('神秘商人对话或离开状态多次重读仍未确认；已保留现场，未点击未知选项')
                previous = key
                self.b.sleep(.6)
                s = self.observe()
            raise SafetyStop('神秘商人处理超时，已保留现场，未将原任务记为完成')
        except (SafetyStop, UserStopped, TaskBlocked) as error:
            row.update(status='stopped' if isinstance(error, UserStopped) else 'blocked', reason=str(error))
            self.checkpoint()
            raise

    def purchase_merchant_item(self, s, row, offer, options):
        # This method is reachable only through an explicit buy selection.
        if merchant_options(self.b.settings) != options or options['mode'] != 'buy':
            raise SafetyStop('神秘商人未开启对应购买设置，未购买')
        fresh = self.observe();self.b.guard(fresh)
        current = select_merchant_offer(self.b, fresh, options, self.report.get('merchant_diamond_spend', 0))
        if current != offer:
            raise SafetyStop('神秘商人购买前商品或价格改变，未购买')
        pending = {**offer, 'status': 'requested', 'confirmed': False}
        row['purchase'] = pending
        self.report['diamond_spend'] = None
        self.b.save_screen(fresh, self.report['folder']/f'merchant-purchase-{len(self.report["merchant_events"])}.png')
        self.note(f'神秘商人：购买所选{offer["label"]}，价格{offer["price"]}钻石')
        self.checkpoint()  # Persist before the possibly irreversible input.
        self.b.click_at(fresh, offer['point'], [MERCHANT_TITLE, '^离开$', '^'+re.escape(offer['text'])+'$'],
                        '购买已勾选的神秘商人物品：'+offer['label'])
        confirmed = False;reward_closed = False
        try:
            for _ in range(20):
                q = self.observe()
                confirm = merchant_purchase_confirmation(q, offer)
                self.b.merchant_purchase_pending = offer if confirm else None
                self.b.guard(q)
                if confirm:
                    if not confirmed:
                        self.b.click_at(q, confirm.center, ['^取消$', '^确定$|^确认购买$|^购买$'],
                                        '确认所选神秘商人物品及已核实钻石价格')
                        confirmed = True
                    self.b.sleep(.6);continue
                if q.find('^获得奖励$', (400, 70, 500, 160)) and q.find('点击空白位置关闭'):
                    if not reward_closed:
                        self.b.save_screen(q, self.report['folder']/f'merchant-reward-{len(self.report["merchant_events"])}.png')
                        pending['reward_text'] = q.text
                        self.b.click_at(q, (640, 660), ['^获得奖励$', '点击空白位置关闭'], '关闭神秘商人购买奖励')
                        reward_closed = True
                    continue
                if merchant_return_page(q):
                    text = q.region_text((250, 0, 75, 60)).strip()
                    after = int(text) if text.isdigit() else None
                    if after is not None:
                        if offer['balance']-after != offer['price']:
                            raise SafetyStop('神秘商人购买后钻石变化与价格不符，保留现场，未再次购买')
                        pending.update(status='completed', confirmed=True, balance_after=after)
                        row['purchases'] = 1
                        self.report['merchant_diamond_spend'] = self.report.get('merchant_diamond_spend', 0)+offer['price']
                        self.report['diamond_spend'] = (None if self.report.get('piggy_spend_unconfirmed') else
                            self.report['merchant_diamond_spend']+self.report.get('piggy_diamond_spend',0))
                        self.checkpoint()
                        return q
                self.b.sleep(.6)
            raise SafetyStop('神秘商人购买结果或钻石扣款未确认；保留现场，未重复购买')
        finally:
            self.b.merchant_purchase_pending = None
            if not pending['confirmed']:
                pending['status'] = 'unconfirmed'
                self.checkpoint()


def normalize_item(text):
    return re.sub(r'[^\u4e00-\u9fff]', '', text)


def select_merchant_offer(b, s, options, spent=0):
    if options['mode'] != 'buy' or not is_merchant_shop(s):
        return None
    balance_text = s.region_text((1195, 0, 85, 55)).strip()
    if not balance_text.isdigit():
        raise SafetyStop('神秘商人钻石余额未读清，未购买')
    balance = int(balance_text)
    remaining = options['diamond_budget']-spent
    allowed = {key: normalize_item(label) for key, label in MERCHANT_ITEMS}
    offers = {}
    for r in range(2):
        for c in range(4):
            x, y = 192+c*236, 20+r*215
            labels = [w for w in s.words if x <= w.center[0] < x+210 and y <= w.center[1] < y+40]
            matches = [(key, w) for key, label in allowed.items() for w in labels if normalize_item(w.text) == label]
            if len(matches) != 1 or not s.find(r'^剩余\s*1$', (x, y+118, 210, 42)):
                continue
            key, label = matches[0]
            price_word = s.find(r'^\d+$', (x+80, y+155, 100, 40))
            if not price_word or price_word.score < .95 or not b.match_template(s, 'merchant-price-diamond.png', [x+55, y+153, 55, 45], .92):
                continue
            price = int(price_word.text)
            if not 0 < price <= min(balance, remaining):
                continue
            if key in offers:
                raise SafetyStop('神秘商人出现同名多份商品，未猜测购买')
            offers[key] = {'id': key, 'label': dict(MERCHANT_ITEMS)[key], 'text': label.text,
                           'price': price, 'balance': balance, 'point': price_word.center}
    return next((offers[i['id']] for i in options['items'] if i['enabled'] and i['id'] in offers), None)


def merchant_purchase_confirmation(s, offer):
    """Accept only a readable item-specific diamond confirmation, never generic OK."""
    body = s.region_text((250, 150, 780, 340))
    compact = re.sub(r'\s', '', body)
    if not re.search('购买', compact) or normalize_item(offer['label']) not in normalize_item(body):
        return None
    prices = re.findall(r'(\d+)钻石|钻石[×xX:：]?(\d+)', compact)
    values = {int(a or b) for a, b in prices}
    if values != {offer['price']} or re.search('不足|充值|药水|重置|次数', compact):
        return None
    if not s.find('^取消$', (250, 420, 780, 200)):
        return None
    return s.find('^确定$|^确认购买$|^购买$', (600, 420, 430, 200))
