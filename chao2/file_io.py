"""Atomic local snapshots with bounded retries for Windows sharing locks."""
import json
import time
from pathlib import Path
from uuid import uuid4


def atomic_json(path,data):
    path=Path(path)
    pending=path.with_name(f'.{path.name}.{uuid4().hex}.tmp')
    pending.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    # Readers/virus scanners may briefly open report.json without delete sharing.
    # Retry only the atomic replace, never the game operation that produced it.
    for attempt in range(4):
        try:
            pending.replace(path)
            return
        except PermissionError:
            if attempt==3:raise
            time.sleep((.1,.25,.6)[attempt])
