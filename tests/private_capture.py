"""Optional local captures are intentionally absent from the public source."""
from pathlib import Path
import pytest


def capture_file(name):
    path = Path(__file__).parent / 'fixtures' / name
    if not path.is_file():
        pytest.skip('Private game capture is not distributed: ' + name,allow_module_level=True)
    return path
