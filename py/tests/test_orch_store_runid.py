import pytest
from claudeops import orch_store


def test_run_dir_rejects_traversal():
    for bad in ["", "../x", "a/b", "a\\b", ".."]:
        with pytest.raises(ValueError):
            orch_store.run_dir(bad)
    assert orch_store.run_dir("r20260101_000000_ab").endswith("r20260101_000000_ab")


def test_load_json_logs_non_enoent(tmp_path, caplog):
    d = tmp_path / "d.json"
    d.mkdir()          # open() -> IsADirectoryError (OSError, not ENOENT)
    with caplog.at_level("WARNING"):
        assert orch_store._load_json(str(d), "dflt") == "dflt"
    assert "okunamadi" in caplog.text
    assert orch_store._load_json(str(tmp_path / "yok.json"), 1) == 1
