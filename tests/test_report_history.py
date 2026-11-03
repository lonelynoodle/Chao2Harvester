import json
from datetime import datetime,timezone,timedelta
from pathlib import Path
from types import SimpleNamespace
import pytest
from chao2.report_history import prune_reports,report_folders


def run(root,name):
    folder=root/name;folder.mkdir(parents=True)
    (folder/'report.json').write_text(json.dumps({'folder':str(folder),'status':'completed'}),encoding='utf-8')
    (folder/'screenshot.png').write_bytes(b'test')
    nested=folder/'details';nested.mkdir();(nested/'trace.log').write_text('trace')
    return folder


def test_keeps_five_newest_run_names_not_modified_times(tmp_path):
    import os
    folders=[run(tmp_path,f'20261014-1200{i:02}') for i in range(13)]
    os.utime(folders[0],(2000000000,2000000000))
    result=prune_reports(tmp_path)
    assert result['errors']==[] and set(result['removed'])=={p.name for p in folders[:8]}
    assert set(report_folders(tmp_path))==set(folders[8:])
    assert prune_reports(tmp_path)=={'removed':[],'errors':[]}


def test_never_deletes_calibration_files_or_unrecognized_directories(tmp_path):
    run(tmp_path,'calibration-v071');run(tmp_path,'20261014-120000-other')
    (tmp_path/'20261014-010000').mkdir()  # No report marker.
    (tmp_path/'wpf-smoke.json').write_text('{}')
    for i in range(11):run(tmp_path,f'20261014-1200{i:02}')
    prune_reports(tmp_path)
    assert (tmp_path/'calibration-v071/report.json').exists()
    assert (tmp_path/'20261014-120000-other/report.json').exists()
    assert (tmp_path/'20261014-010000').is_dir()
    assert (tmp_path/'wpf-smoke.json').exists()


def test_delete_error_is_reported_without_deleting_newest(tmp_path,monkeypatch):
    folders=[run(tmp_path,f'20261014-1200{i:02}') for i in range(11)]
    def locked(path):raise PermissionError('locked')
    monkeypatch.setattr('chao2.report_history.shutil.rmtree',locked)
    result=prune_reports(tmp_path)
    assert not result['removed'] and len(result['errors'])==6
    assert folders[-1].exists()


def test_rechecks_resolved_target_before_recursive_delete(tmp_path,monkeypatch):
    outside=run(tmp_path/'outside','20261014-010000')
    root=tmp_path/'reports';root.mkdir()
    current=run(root,'20261014-120000')
    monkeypatch.setattr('chao2.report_history.report_folders',lambda root:[current,outside])
    result=prune_reports(root,keep=1)
    assert outside.exists() and not result['removed'] and result['errors']


def test_create_report_is_unique_and_enforces_retention(tmp_path,monkeypatch):
    from chao2 import workflows
    fixed=datetime(2026,10,14,12,tzinfo=timezone(timedelta(hours=8)))
    monkeypatch.setattr(workflows,'ROOT',tmp_path)
    monkeypatch.setattr(workflows,'datetime',SimpleNamespace(now=lambda:fixed))
    created=[workflows.create_report() for _ in range(12)]
    assert len({r['folder'] for r in created})==12
    assert len(report_folders(tmp_path/'reports'))==5
    assert not created[0]['folder'].exists() and not created[1]['folder'].exists()
    saved=json.loads((created[-1]['folder']/'report.json').read_text('utf-8'))
    assert saved['status']=='running' and saved['started']==fixed.isoformat()
    assert created[-1]['folder'].name=='2026_10_14_12_00_00_011'


def test_mixed_old_and_new_formats_are_sorted_by_run_time(tmp_path):
    names=['20261025-235959','2026_10_26_00_00_00','20261026-000001',
           '2026_10_26_00_00_02_001','2026_10_26_00_00_02','20261026-000003']
    for name in names:run(tmp_path,name)
    assert [p.name for p in report_folders(tmp_path)]==[names[i] for i in [5,3,4,2,1,0]]
    assert prune_reports(tmp_path)['removed']==['20261025-235959']


def test_frontend_reserved_folder_is_adopted_once_without_duplicate_history(tmp_path,monkeypatch):
    from chao2 import workflows
    root=tmp_path/'reports';folder=run(root,'2026_10_26_04_04_54')
    started='2026-10-26T04:04:54.1234567+08:00'
    (folder/'report.json').write_text(json.dumps({'status':'starting','session_token':'owned',
                                                'started':started,'folder':str(folder)}))
    (folder/'frontend-worker.log').write_text('native import log')
    monkeypatch.setenv('CHAO2_REPORT_ROOT',str(root))
    monkeypatch.setenv('CHAO2_REPORT_FOLDER',str(folder))
    monkeypatch.setenv('CHAO2_RUN_TOKEN','owned')
    result=workflows.create_report()
    assert result['folder']==folder and result['started']==started
    assert len(report_folders(root))==1 and (folder/'frontend-worker.log').read_text()=='native import log'
    with pytest.raises(ValueError,match='已被使用'):workflows.create_report()


@pytest.mark.parametrize('case',['outside','bad_name','wrong_token','completed'])
def test_reserved_folder_cannot_overwrite_other_files(tmp_path,monkeypatch,case):
    from chao2.report_history import reserve_report
    root=tmp_path/'reports';root.mkdir()
    folder=run(tmp_path if case=='outside' else root,
               'not-a-run' if case=='bad_name' else '2026_10_26_04_04_54')
    marker={'status':'completed' if case=='completed' else 'starting','session_token':'owned','started':'test'}
    (folder/'report.json').write_text(json.dumps(marker))
    before=(folder/'report.json').read_bytes()
    monkeypatch.setenv('CHAO2_REPORT_FOLDER',str(folder))
    monkeypatch.setenv('CHAO2_RUN_TOKEN','wrong' if case=='wrong_token' else 'owned')
    with pytest.raises(ValueError):reserve_report(root,datetime.now().astimezone())
    assert (folder/'report.json').read_bytes()==before


def test_invalid_timestamp_and_unnamed_files_are_not_run_records(tmp_path):
    for name in ['2026_99_26_04_04_54','20261026-990000','2026_10_26_04_04_54_notes']:
        run(tmp_path,name)
    assert report_folders(tmp_path)==[] and prune_reports(tmp_path)=={'removed':[],'errors':[]}
