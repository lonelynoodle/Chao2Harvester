"""Resource-driven cocoon settings and migration of removed run limits."""


def migrate_cocoon_options(options):
    if not isinstance(options,dict):return
    options.pop('max_runs',None)
    previous=options.get('reserve_spikes',0)
    options.setdefault('reserve_spikes_enabled',type(previous) is int and previous>0)
    if type(previous) is int and previous==0:options['reserve_spikes']=1
    for row in options.get('targets',[]) if isinstance(options.get('targets'),list) else []:
        if isinstance(row,dict):row.pop('limit',None)


def migrate_resource_limits(settings):
    settings.pop('max_battles',None)
    options=settings.get('task_options',{})
    if isinstance(options,dict):migrate_cocoon_options(options.get('cocoon'))
    for row in settings.get('task_queue',[]) if isinstance(settings.get('task_queue'),list) else []:
        if isinstance(row,dict) and row.get('key')=='cocoon':migrate_cocoon_options(row.get('options'))
    for row in settings.get('task_templates',[]) if isinstance(settings.get('task_templates'),list) else []:
        if isinstance(row,dict) and isinstance(row.get('settings'),dict):migrate_resource_limits(row['settings'])


def cocoon_reserve(options):
    return options['reserve_spikes'] if options.get('reserve_spikes_enabled',False) else 0
