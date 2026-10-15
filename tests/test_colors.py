from iridia.colors import _deduplicate, normalize_hex, resolve_colors


def test_normalize_hex():
    assert normalize_hex("#FF8800") == "ff8800"
    assert normalize_hex(" ff8800 ") == "ff8800"
    assert normalize_hex("fff") == ""
    assert normalize_hex("zzzzzz") == ""
    assert normalize_hex(None) == ""


def test_resolve_colors():
    extracted = ["111111", "222222"]
    assert resolve_colors([1, "#ABCDEF", 5, "bad", True, -1], extracted) == ["222222", "abcdef"]
    assert resolve_colors(None, extracted) == []


def test_deduplicate_drops_dark_grey_and_near_duplicates():
    out = _deduplicate(["000000", "808080", "ff0000", "fe0101", "0000ff"])
    assert out == ["ff0000", "0000ff"]
