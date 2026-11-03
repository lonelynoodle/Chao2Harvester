from app import frontend_executable


def test_versioned_frontend_selection_ignores_staging_and_uses_numeric_versions(tmp_path):
    for name in ('bin-next','bin-v0.7.2','bin-v0.10.0','bin-v0.9.0'):
        folder=tmp_path/name;folder.mkdir();(folder/'Chao2Harvester.exe').touch()
    (tmp_path/'bin-v0.11.0').mkdir()
    assert frontend_executable(tmp_path)==tmp_path/'bin-v0.10.0/Chao2Harvester.exe'


def test_legacy_frontend_is_the_fallback(tmp_path):
    assert frontend_executable(tmp_path)==tmp_path/'bin/Chao2Harvester.exe'


def test_current_bin_is_preferred_over_leftover_version_folders(tmp_path):
    for name in ('bin','bin-v0.9.66'):
        folder=tmp_path/name;folder.mkdir();(folder/'Chao2Harvester.exe').touch()
    assert frontend_executable(tmp_path)==tmp_path/'bin/Chao2Harvester.exe'
