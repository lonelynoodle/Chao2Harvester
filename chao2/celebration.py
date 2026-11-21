"""One daily task for optional Fengye activities, with per-activity outcomes."""
from copy import deepcopy

from .activities import BudgetReached
from .policy import TaskBlocked,UserStopped,SessionUnavailable


class CelebrationActivities:
    def celebration(self):
        from .puzzle import puzzle_daily
        options=self.options['celebration'];original=self.options
        self.options={**original,
            'triad':{'auto_settle':options['triad_auto_settle']},
            'giant':{'teams':deepcopy(options['giant_teams']),'max_runs':options['giant_max_runs'],
                     'wall_mode':options.get('giant_wall_mode','ignore'),
                     'skip_completed':options['giant_skip_completed'],'auto_settle':options['giant_auto_settle']}}
        jobs=[]
        if options['triad']:jobs.append(('triad','三阵入局',self.triad))
        if options['giant']:jobs.append(('giant','进击巨物',self.giant))
        if options['daily_puzzle']:jobs.append(('daily_puzzle','拼二每日',lambda:puzzle_daily(self)))
        ident=self.report_key('celebration')
        results=self.report.setdefault('celebration_tasks',{}).setdefault(ident,{})
        failures=[]
        try:
            for key,label,run in jobs:
                if results.get(key,{}).get('status') in ('done','skipped'):continue
                self.active_task=key
                start=len(self.report.get('team_attempts',[]));count=self.task_counts.get(key,0)
                self.note('庆典活动：'+label)
                try:
                    value=self.with_page_recovery(run,'庆典活动：'+label)
                    result=value if isinstance(value,dict) else {
                        'status':'skipped' if '已跳过' in value else 'done','message':value}
                except BudgetReached as error:result={'status':'skipped','message':str(error)}
                except (UserStopped,SessionUnavailable):raise
                except Exception as error:
                    result={'status':'blocked','message':str(error)};failures.append(label)
                finally:
                    for row in self.report.get('team_attempts',[])[start:]:
                        row.update(group='celebration',instance_id=ident)
                    self.task_counts['celebration']=self.task_counts.get('celebration',0)+self.task_counts.get(key,0)-count
                results[key]=result;self.note(result['message']);self.checkpoint()
                self.recover_failed_task() if result.get('status')=='blocked' else self.home()
        finally:
            self.options=original;self.active_task='celebration'
        if failures:raise TaskBlocked('庆典活动部分未完成：'+'、'.join(failures))
        return '；'.join(results[key]['message'] for key,_,_ in jobs) if jobs else '庆典活动的子任务均未开启'
