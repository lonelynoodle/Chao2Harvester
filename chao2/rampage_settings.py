"""Migrate the retired rampage fight cap to the explicit repeat switch."""


def migrate_repeat_challenge(settings):
    def migrate(options):
        if not isinstance(options,dict):return
        options.pop('max_runs',None)
        options.setdefault('repeat_challenge',False)
    options=settings.get('task_options',{})
    if isinstance(options,dict):migrate(options.get('nest'))
    for row in settings.get('task_queue',[]) if isinstance(settings.get('task_queue'),list) else []:
        if isinstance(row,dict) and row.get('key')=='nest':migrate(row.get('options'))
    for row in settings.get('task_templates',[]) if isinstance(settings.get('task_templates'),list) else []:
        if isinstance(row,dict) and isinstance(row.get('settings'),dict):migrate_repeat_challenge(row['settings'])
