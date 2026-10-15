from iridia.calibration import normalize, valid_name


def test_normalize_wraps_hues():
    prof, err = normalize({"anchors": [[120, "00FF00"], [240, "#0000ff"]]})
    assert err is None
    assert prof["anchors"][0] == [0, "0000ff"]
    assert prof["anchors"][-1] == [360, "0000ff"]


def test_normalize_rejects_bad_input():
    assert normalize([])[0] is None
    assert normalize({"anchors": [[0, "ff0000"]]})[0] is None
    assert normalize({"anchors": [[0, "ff0000"], [0, "00ff00"]]})[0] is None
    assert normalize({"anchors": [[0, "ff0000"], [400, "00ff00"]]})[0] is None
    assert normalize({"anchors": [[0, "ff0000"], [120, "00ff00"]], "grey": "nope"})[0] is None


def test_normalize_clamps_numbers():
    prof, _ = normalize({"anchors": [[0, "ff0000"], [120, "00ff00"]], "sat_exponent": 99})
    assert prof["sat_exponent"] == 3.0


def test_valid_name():
    assert valid_name("My strip (v2)")
    assert not valid_name("")
    assert not valid_name("../escape")
