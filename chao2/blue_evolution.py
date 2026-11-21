"""Opt-in blue-to-purple evolution; retain monsters and submit each upgrade once."""
import re
from uuid import uuid4
from .policy import TaskBlocked,SafetyStop,UserStopped
from .star_supply import purple_monster_info,evolution_result_name
from .quick_evolution import (QuickEvolution,DETAIL,EVOLVE,EVOLVE_ROI,quick_detail,quick_list,tree_map,
                              quick_target_name,quick_spore_balance,quick_evolution_enabled,quick_evolution_offer)


PENDING='blue_evolution_pending'


class BlueEvolution(QuickEvolution):
    def blue_evolution_result(self):
        key=self.report_key('other')
        result=self.report.setdefault('blue_evolution_runs',{}).setdefault(key,{
            'status':'running','evolved':0,'gold_spent':0,'spores_spent':0,'receipts':[]})
        self.report.setdefault('other_tasks',{})['blue_evolution']=result
        return result

    def credit_blue_evolution(self,offer):
        result=self.blue_evolution_result()
        if offer['id'] not in result['receipts']:
            result['receipts'].append(offer['id']);result['evolved']+=1
            result['gold_spent']+=offer['gold'];result['spores_spent']+=offer['spores']
            self.report.setdefault('blue_evolutions',[]).append({**offer,'status':'confirmed',
                'instance_id':self.report_key('other')})
            self.note(f'蓝怪进化：已确认第{result["evolved"]}只紫怪「{offer["name"]}」，'
                      f'金币{offer["gold"]}、进化孢子{offer["spores"]}')
        self.checkpoint()
        self.state.pop(PENDING,None);self.save_state()

    def complete_blue_evolution(self,s,*,submitted_now=False):
        offer=self.state.get(PENDING)
        if not offer:raise TaskBlocked('没有待核实的蓝怪进化记录')
        if offer.get('phase')=='confirmed':
            self.credit_blue_evolution(offer);return s
        if offer.get('route')=='quick_tree':
            return self.complete_quick_blue_evolution(s,offer,submitted_now=submitted_now)
        for _ in range(28):
            self.b.check_stop();self.b.guard(s)
            if purple_monster_info(self.b,s,require_level_one=False) and (submitted_now or offer.get('reveal_seen')):
                offer['phase']='confirmed';self.save_state()
                self.credit_blue_evolution(offer);return s
            if evolution_result_name(self.b,s)==offer['name'] or s.has('进化成功|进化完成','点击空白位置关闭'):
                offer['reveal_seen']=True;self.save_state()
                self.b.save_screen(s,self.report['folder']/f'blue-evolution-{offer["id"]}-reveal.png')
                s=self.close_star_evolution_result(s,offer['name'],require_level_one=False)
                continue
            if not submitted_now:break
            self.b.sleep(.5);s=self.observe()
        raise TaskBlocked('蓝怪进化结果尚未核实，已保存待核实记录，未重复进化')

    def complete_quick_blue_evolution(self,s,offer,*,submitted_now):
        name=offer['name']
        target='^'+re.escape(name)+'$'
        def reveal_anchors(q):
            if evolution_result_name(self.b,q)==name:
                return [target,'^详细属性$','^不朽$']
            if q.has('进化成功|进化完成','点击空白位置关闭') and (submitted_now or q.find(target)):
                return ['进化成功|进化完成','点击空白位置关闭']
            return None
        def close(q):
            anchors=reveal_anchors(q)
            if anchors:self.b.click_at(q,(640,660),anchors,'关闭便捷进化展示')
        for _ in range(28):
            self.b.check_stop()
            self.b.guard(s)
            reveal=reveal_anchors(s)
            receipt=(quick_detail(s) and quick_target_name(s)==name and
                     quick_spore_balance(s)==offer['spore_balance']-offer['spores'])
            purple=(purple_monster_info(self.b,s,require_level_one=False) and s.find(target,(695,71,340,67))
                    and (submitted_now or offer.get('reveal_seen')))
            if reveal or purple or submitted_now and receipt:
                offer['phase']='confirmed';self.save_state()
                self.credit_blue_evolution(offer)
                if not reveal:return s
                close(s)
                return self.wait_for_screen(lambda q:quick_detail(q) or quick_list(q) or tree_map(q) or
                    purple_monster_info(self.b,q,require_level_one=False),
                    '关闭便捷进化展示后的页面',timeout=3,retry_navigation=close)
            if not submitted_now:break
            self.b.sleep(.5);s=self.observe()
        raise TaskBlocked('便捷进化结果尚未核实，已保存待核实记录，未重复进化')

    def evolve_blue_monsters(self):
        options=self.options['other']
        if not options['evolve_blue_monsters']:raise SafetyStop('未开启蓝怪进化紫怪')
        result=self.blue_evolution_result()
        try:return self._run_blue_evolution(result)
        except Exception as error:
            result.update(status='stopped' if isinstance(error,UserStopped) else 'blocked',message=str(error))
            self.checkpoint()
            raise

    def _run_blue_evolution(self,result):
        options=self.options['other']
        if self.day.get('star_evolution_pending') or self.day.get('star_conversion_pending'):
            raise TaskBlocked('饲星操作尚待核实，未混用蓝怪进化流程')
        limit=options['blue_evolution_count'] if options['blue_evolution_mode']=='count' else 0
        result.update(mode=options['blue_evolution_mode'],requested=limit or None,status='running')
        if self.state.get(PENDING):self.complete_blue_evolution(self.observe())
        reason='已达到指定进化只数'
        while not limit or result['evolved']<limit:
            self.b.check_stop()
            _,offer=self.next_quick_evolution()
            if offer is None:
                reason='没有可进化的未锁定蓝怪';break
            if offer['spore_balance']<offer['spores']:
                reason=f'进化孢子不足，剩余{offer["spore_balance"]}，单只需要{offer["spores"]}';break
            if offer['gold_balance']<offer['gold']:
                reason=f'金币不足，单只需要{offer["gold"]}';break
            # Confirm the current target and costs on a fresh frame before
            # recording intent. No purchase/feeding or quantity batch is used.
            fresh=self.observe();self.b.guard(fresh)
            current=quick_evolution_offer(self.b,fresh)
            button=fresh.find(EVOLVE,EVOLVE_ROI)
            if current!=offer or not button or not quick_evolution_enabled(fresh):
                raise TaskBlocked('进化前目标、素材选择或材料余额变化，未提交')
            journal={**offer,'id':uuid4().hex,'phase':'submitted','route':'quick_tree'}
            self.b.save_screen(fresh,self.report['folder']/f'blue-evolution-{journal["id"]}-before.png')
            self.state[PENDING]=journal;self.save_state();self.checkpoint()
            self.b.click_at(fresh,button.center,[EVOLVE,DETAIL],
                            f'蓝怪进化紫怪「{offer["name"]}」；金币{offer["gold"]}、进化孢子{offer["spores"]}')
            self.complete_blue_evolution(self.observe(),submitted_now=True)
        result.update(status='done',stop_reason=reason,
            message=f'蓝怪进化紫怪：已进化{result["evolved"]}只，保留紫怪；金币{result["gold_spent"]}、'
                    f'进化孢子{result["spores_spent"]}；{reason}')
        self.checkpoint()
        return result
