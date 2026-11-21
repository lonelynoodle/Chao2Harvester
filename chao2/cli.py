"""Command-line entry for diagnostics and explicitly selected manual tasks."""
import argparse
import json
import threading
from .backend import ROOT
from .workflows import TASKS,run_daily
from .run_lock import GameRunLease,RunAlreadyActive

def main():
    p=argparse.ArgumentParser(description='超二收菜 — 默认只读检测')
    p.add_argument('--run',nargs='+',choices=list(TASKS),help='明确指定本轮执行的任务；省略则只读')
    p.add_argument('--keep-open',action='store_true',help='结束保留 MuMu')
    args=p.parse_args();settings=json.loads((ROOT/'config.json').read_text('utf-8'))
    if args.keep_open:settings['close_mumu']=False
    stop=threading.Event()
    try:
        with GameRunLease(settings):
            r=run_daily(settings,args.run or [],stop,diagnostic=not args.run)
        print(json.dumps({'status':r['status'],'folder':str(r['folder']),'reason':r.get('reason'),'tasks':r['tasks']},ensure_ascii=False,indent=2))
        return 0 if r['status'] in ('completed','diagnostic') else 2
    except KeyboardInterrupt:
        stop.set();return 130
    except RunAlreadyActive as error:
        print(str(error));return 2

if __name__=='__main__':raise SystemExit(main())
