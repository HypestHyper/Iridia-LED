"""Setups and backups: what's saved, and that loading one puts the folder back as it was."""
import json
import os

from iridia.setups import Setups


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


def _read(path):
    with open(path) as f:
        return json.load(f)


def test_a_backup_brings_back_exactly_what_was_there(tmp_path):
    d = str(tmp_path)
    _write(f"{d}/config.json", {"devices": {"A": {}}})
    _write(f"{d}/gui.json", {"ui_size": "large"})
    _write(f"{d}/calibration/Mine.json", {"r": 1})
    s = Setups(d, "1.3.0")
    bid = s.backup("test")
    # things change after the backup: edits, a new file, a new profile, a removed file
    _write(f"{d}/config.json", {"devices": {"B": {}}})
    _write(f"{d}/layout.json", {"strips": []})
    _write(f"{d}/calibration/Later.json", {"r": 2})
    os.remove(f"{d}/gui.json")
    assert s.load_backup(bid) is None
    assert _read(f"{d}/config.json") == {"devices": {"A": {}}}
    assert _read(f"{d}/gui.json") == {"ui_size": "large"}
    assert not os.path.exists(f"{d}/layout.json")                  # didn't exist then
    assert sorted(os.listdir(f"{d}/calibration")) == ["Mine.json"]
    # loading made a backup of the state it replaced, so that can be undone too
    assert len(s.list_backups()) == 2


def test_an_old_setup_file_only_writes_what_it_holds(tmp_path):
    d = str(tmp_path)
    _write(f"{d}/config.json", {"devices": {}})
    _write(f"{d}/layout.json", {"strips": [1]})
    _write(f"{d}/calibration/Mine.json", {"r": 1})
    s = Setups(d)
    old = {"iridia_setup": 1, "name": "old", "files": {"config.json": {"devices": {"X": {}}}}, "calibration": {}}
    assert s.restore(old) is None
    assert _read(f"{d}/config.json") == {"devices": {"X": {}}}
    assert os.path.exists(f"{d}/layout.json") and os.path.exists(f"{d}/calibration/Mine.json")
    assert s.restore({"nope": 1}) and s.restore({"iridia_setup": 1, "files": {"config.json": []}})


def test_named_setups_round_trip(tmp_path):
    d = str(tmp_path)
    _write(f"{d}/config.json", {"devices": {"A": {}}})
    s = Setups(d)
    assert s.save("Desk") is None and s.save("Desk", overwrite=False)
    assert s.save("../evil")                                         # not a valid name
    assert s.rename("Desk", "Desk 2") is None and [x["name"] for x in s.list()] == ["Desk 2"]
    out = str(tmp_path / "export.json")
    assert s.export_to("Desk 2", out) is None
    name, err = s.import_from(out)
    assert err is None and name == "Desk 2 (2)"
