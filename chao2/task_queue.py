"""Ordered task instances with independent options, limits and report groups."""
from contextlib import contextmanager
from copy import deepcopy
from .configuration import plan_tasks,STAMINA_TASKS


def execution_entries(settings,selected,order):
    if 'task_queue' not in settings:
        return [{'id':key,'key':key} for key in plan_tasks(settings,selected,order)]
    entries=[deepcopy(row) for row in settings['task_queue'] if row['enabled'] and row['key'] in selected]
    return ([row for row in entries if row['key']=='startup']+
            [row for row in entries if row['key'] not in ('startup','finish')]+
            [row for row in entries if row['key']=='finish'])


class TaskQueueExecution:
    def instance_rows(self,key):
        rows=self.report.get(key,[]);entry=getattr(self,'_active_instance',None)
        if not entry:return rows
        start=getattr(self,'_instance_list_starts',{}).get(key,0)
        return [row for index,row in enumerate(rows) if row.get('instance_id')==entry['id'] or index>=start]

    def report_key(self,task):
        entry=getattr(self,'_active_instance',None)
        return entry['id'] if entry and entry['key']==task else task

    def task_attempts(self,task):
        entry=getattr(self,'_active_instance',None)
        return [row for index,row in enumerate(self.report.get('team_attempts',[]))
                if (row.get('task')==task or row.get('group')==task) and (not entry or row.get('instance_id')==entry['id'] or
                    index>=getattr(self,'_instance_attempt_start',0))]

    @contextmanager
    def task_instance(self,entry):
        if 'options' not in entry:
            yield;return
        key=entry['key'];ident=entry['id']
        counts=getattr(self,'_instance_counts',{});self._instance_counts=counts
        usage=self.report.setdefault('resource_usage_by_instance',{}).setdefault(ident,{})
        old_options,old_counts,old_usage=self.options,self.task_counts,self.report.setdefault('resource_usage',{})
        old_searches,old_retry=self.search_counts,self.stamina_retry
        states=getattr(self,'_instance_states',{});self._instance_states=states
        state=states.setdefault(ident,{'search_counts':{},'stamina_retry':{},'details':{}})
        self.search_counts,self.stamina_retry=state['search_counts'],state['stamina_retry']
        before_searches=dict(self.search_counts)
        scoped={'main':('main_examined','main_failed','main_retry_unlocated'),'copies':('copy_failed',),
                'cocoon':('cocoon_counts','cocoon_failed','cocoon_unavailable','cocoon_refreshes')}.get(key,())
        for field in scoped:
            self.report.pop(field,None)
            if field in state['details']:self.report[field]=deepcopy(state['details'][field])
        previous=getattr(self,'_active_instance',None)
        previous_start=getattr(self,'_instance_attempt_start',0)
        previous_lists=getattr(self,'_instance_list_starts',{})
        self._instance_list_starts={field:len(self.report.get(field,[])) for field in ('forest_explorations','forest_rewards')}
        self._active_instance=entry;self.active_task_id=ident
        self._instance_attempt_start=len(self.report.get('team_attempts',[]))
        self.options={**old_options,key:deepcopy(entry['options'])}
        self.task_counts=counts.setdefault(ident,{})
        before_counts=dict(self.task_counts);before_usage=deepcopy(usage)
        self.report['resource_usage']=usage
        try:yield
        finally:
            for row in self.report.get('team_attempts',[])[self._instance_attempt_start:]:
                if row.get('task')==key:row.setdefault('instance_id',ident)
            for field,start in self._instance_list_starts.items():
                for row in self.report.get(field,[])[start:]:row.setdefault('instance_id',ident)
            for field in scoped:
                if field in self.report:state['details'][field]=deepcopy(self.report[field])
            for task,count in self.search_counts.items():old_searches[task]=old_searches.get(task,0)+count-before_searches.get(task,0)
            old_retry.update(self.stamina_retry)
            self.search_counts,self.stamina_retry=old_searches,old_retry
            if old_searches:self.report['search_counts']=dict(old_searches)
            self.report.setdefault('instance_runtime',{})[ident]=deepcopy(state)
            for task,count in self.task_counts.items():
                old_counts[task]=old_counts.get(task,0)+count-before_counts.get(task,0)
            for task,resources in usage.items():
                for label,row in resources.items():
                    prior=before_usage.get(task,{}).get(label,{})
                    total=old_usage.setdefault(task,{}).setdefault(label,{'start':row['start'],'remaining':None,'spent':0,'unverified':0})
                    total['remaining']=row['remaining']
                    for field in ('spent','unverified'):total[field]+=row[field]-prior.get(field,0)
            self.report.setdefault('instance_attempt_counts',{})[ident]=self.task_counts.get(key,0)
            self.options,self.task_counts=old_options,old_counts
            self.report['resource_usage']=old_usage
            self._active_instance=previous;self._instance_attempt_start=previous_start
            self._instance_list_starts=previous_lists
            self.checkpoint()

    def execute_entry(self,entry):
        with self.task_instance(entry):self.execute_task(entry['key'])

    def replenish_queue_stamina(self,entries):
        order=self.b.settings['stamina_order']
        rows=sorted((row for row in entries if row['key'] in STAMINA_TASKS),key=lambda row:order.index(row['key']))
        for row in rows:
            if self.report.get('tasks',{}).get(row['id'],{}).get('status')=='blocked':continue
            if not (row['options']['auto_three_shots'] or row['options']['auto_potions']):continue
            original=self.selected
            try:
                with self.task_instance(row):
                    self.selected=[row['key']]
                    self.note(self.replenish_stamina())
            finally:self.selected=original
        return '已按各任务实例的设置核对体力补充'
