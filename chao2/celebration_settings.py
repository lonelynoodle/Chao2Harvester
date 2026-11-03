"""Move legacy Fengye task slots into one celebration group, once."""
from copy import deepcopy

LEGACY_EVENTS={'giant','triad'}


def celebration_options(options):
    previous=options.get('celebration')
    if isinstance(previous,dict):return deepcopy(previous)
    if 'celebration' in options:raise ValueError('庆典活动设置格式错误')
    giant=options.get('giant',{});triad=options.get('triad',{})
    if not isinstance(giant,dict) or not isinstance(triad,dict):raise ValueError('活动设置格式错误')
    return {'triad':True,'giant':False,'daily_puzzle':False,
            'triad_auto_settle':triad.get('auto_settle',True),
            'giant_auto_settle':giant.get('auto_settle',True),
            'giant_skip_completed':giant.get('skip_completed',True),
            'giant_teams':deepcopy(giant.get('teams',[1])),
            'giant_max_runs':giant.get('max_runs',0)}


def migrate_celebration(saved):
    options=saved.get('task_options')
    if not isinstance(options,dict):return
    grouped=celebration_options(options)
    options['celebration']=grouped
    if isinstance(options.get('other'),dict):options['other'].pop('daily_puzzle',None)
    for name in ('tasks','task_order'):
        if not isinstance(saved.get(name),list):continue
        result=[];has_legacy=any(isinstance(key,str) and key in LEGACY_EVENTS for key in saved[name])
        for key in saved[name]:
            key='celebration' if isinstance(key,str) and key in LEGACY_EVENTS else key
            if key=='celebration' and has_legacy and key in result:continue
            result.append(key)
        saved[name]=result
    if isinstance(saved.get('task_queue'),list):
        queue=[];inserted=any(isinstance(row,dict) and row.get('key')=='celebration' for row in saved['task_queue'])
        for row in saved['task_queue']:
            if not isinstance(row,dict) or row.get('key') not in LEGACY_EVENTS:
                queue.append(row);continue
            if not inserted:
                ident=row.get('id','celebration')
                queue.append({'id':ident,'key':'celebration','name':'庆典活动',
                              'enabled':True,'options':deepcopy(grouped)})
                inserted=True
        saved['task_queue']=queue
    if isinstance(saved.get('task_templates'),list):
        for template in saved['task_templates']:
            if isinstance(template,dict) and isinstance(template.get('settings'),dict):
                template['settings'].setdefault('task_options',{})
                migrate_celebration(template['settings'])
