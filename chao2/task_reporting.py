"""Cumulative, observed resource accounting across stamina refills."""
from .policy import parse_ratio
from .fixed_hud import tower_feathers

PRIMARY_RESOURCES={
    'copies':('地图体力',20),'hunt':('地图体力',10),'main':('地图体力',5),
    'tower':('浮空羽毛',1),'cocoon':('永生尖刺',1),'tribe':('部落战令',1),
}


class TaskReporting:
    def dungeon_ratio(self,task,s,roi=(1140,0,140,65)):
        if task=='tower':return tower_feathers(self.b,s,map_view=roi==(1030,0,170,65))
        return self.b.read_resource_ratio(s,roi)

    def resource_balance(self,task,label,remaining):
        row=self.report.setdefault('resource_usage',{}).setdefault(task,{}).setdefault(
            label,{'start':remaining,'remaining':remaining,'spent':0,'unverified':0})
        if remaining is not None:
            if row['start'] is None:row['start']=remaining
        row['remaining']=remaining
        return row

    def resource_spent(self,task,label,amount,remaining=None):
        row=self.resource_balance(task,label,remaining)
        if amount is None:row['unverified']+=1
        else:row['spent']+=amount

    def settle_battle_resource(self,task,result,outcome,before):
        if task not in PRIMARY_RESOURCES or before is None:return
        label,cost=PRIMARY_RESOURCES[task]
        ratio=self.dungeon_ratio(task,result) if task=='tower' else parse_ratio(result.region_text((1140,0,140,65)))
        after=ratio[0] if ratio else None
        # A confirmed victory charges the verified entry price. Natural stamina
        # recovery can make the balance decrease smaller than that price.
        amount=cost if outcome=='victory' and after is not None and 0<=before-after<=cost else None
        if task=='tribe' and after is not None and before>after:amount=before-after
        if outcome=='failed' and after is not None:
            if before-after==0:amount=0
            elif 0<before-after<=cost:amount=cost
        self.resource_spent(task,label,amount,after)
        if task=='main' and after is None:
            # Main victory hides the HUD. Resolve this one pending balance from
            # the first world frame after exiting, before any next challenge.
            self._main_resource_pending=(before,outcome)

    def reconcile_main_resource(self,after):
        pending=getattr(self,'_main_resource_pending',None)
        if pending is None or after is None:return
        self._main_resource_pending=None
        before,outcome=pending;delta=before-after
        amount=5 if outcome=='victory' and 0<=delta<=5 else 0 if outcome=='failed' and delta==0 else 5 if outcome=='failed' and 0<delta<=5 else None
        if amount is None:return
        row=self.resource_balance('main','地图体力',after)
        row['unverified']=max(0,row['unverified']-1);row['spent']+=amount

    def task_summary(self,task):
        attempts=self.task_attempts(task)
        count=self.task_counts.get(task,len(attempts))
        pieces=[f'本轮累计挑战{count}次，胜利{sum(r.get("outcome")=="victory" for r in attempts)}次']
        unknown=sum(r.get('outcome')=='unobserved' for r in attempts)
        if unknown:pieces.append(f'{unknown}场胜败未观察到，已按当前页面核对资源')
        scores=sum(r.get('outcome')=='score' for r in attempts)
        if scores:pieces.append(f'伤害结算{scores}次')
        for label,row in self.report.get('resource_usage',{}).get(task,{}).items():
            amount=str(row['spent']) if not row['unverified'] else f'至少{row["spent"]}（{row["unverified"]}场未核实）'
            remaining=row['remaining'] if row['remaining'] is not None else '未读清'
            pieces.append(f'{label}消耗{amount}，剩余{remaining}')
        return '；'.join(pieces)
