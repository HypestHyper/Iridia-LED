from iridia import sections as S


def _resolve(entries):
    return [e if isinstance(e, str) else ["aa0000", "00aa00", "0000aa"][e] for e in entries]


def test_clean_keeps_valid_parts_in_order():
    raw = [{"start": 50, "type": "off"}, {"start": 20, "type": "pattern", "pattern": "nope", "colors": [1, "zz"]},
           {"start": 999, "type": "off"}, {"start": "x"}, "junk", {"start": 20, "type": "effect"}]
    secs = S.clean(raw, 80)
    assert [(s["start"], s["type"]) for s in secs] == [(0, "same"), (20, "effect"), (50, "off")]
    assert secs[1]["animation"]["effect"] == "breathing" and secs[1]["colors"] == [0]
    assert S.clean([{"start": 0, "type": "same"}], 80) == []           # one plain part: not split
    assert S.clean(None, 80) == [] and S.clean(raw, 0) == []
    p = S.clean([{"start": 3, "type": "pattern", "pattern": "paint", "colors": [1, "zz"]}], 10)[1]
    assert p["pattern"] == "solid" and p["colors"] == [1]


def test_overrides_and_spans():
    assert S.clean_overrides({"3": "FFFFFF", "x": "000000", "99": "ff0000", "4": "nothex"}, 10) == {3: "ffffff"}
    secs = S.clean([{"start": 4, "type": "off"}, {"start": 7, "type": "same"}], 10)
    assert [(a, b) for a, b, _s in S.spans(secs, 10)] == [(0, 4), (4, 7), (7, 10)]
    assert S.sizes(secs, 10) == [4, 3, 3]


def test_static_composition():
    secs = S.clean([{"start": 2, "type": "pattern", "pattern": "solid", "colors": ["123456"]},
                    {"start": 4, "type": "off"}, {"start": 6, "type": "effect", "colors": [2]},
                    {"start": 8, "type": "same"}], 10)
    out = S.compose_static(["ffffff"] * 10, secs, {9: "abcdef", 0: "000000"}, _resolve)
    assert out == ["000000", "ffffff", "123456", "123456", "000000", "000000", "0000aa", "0000aa", "ffffff",
                   "abcdef"]


def test_animated_composition_draws_effects_over_their_part_only():
    secs = S.clean([{"start": 3, "type": "effect", "animation": {"effect": "rainbow"}},
                    {"start": 6, "type": "off"}], 8)
    comp = S.Composer(secs, {7: "ff0000"}, 8, _resolve)
    base = [(9, 9, 9)] * 8
    a, b = comp.frame(base, 0.0), comp.frame(base, 1.3)
    assert a[:3] == b[:3] == [(9, 9, 9)] * 3
    assert a[3:6] != b[3:6]                                  # the rainbow moves
    assert a[6] == (0, 0, 0) and a[7] == (255, 0, 0)


def test_even_split_and_notes():
    assert S.even_starts(3, 80) == [0, 27, 54]
    assert S.even_starts(5, 3) == [0, 1, 2]
    assert S.split_note([27, 27, 26], 80) == ("uneven", 2)
    assert S.split_note([20, 20], 40) is None
    assert S.split_note([26, 28, 26], 80) == ("near", 2)
    assert S.split_note([10, 30], 40) is None


def test_rescale_follows_the_new_length():
    secs = S.clean([{"start": 10, "type": "off"}, {"start": 15, "type": "same"}], 20)
    new, ov = S.rescale(secs, {3: "ffffff", 18: "000000"}, 20, 80)
    assert [s["start"] for s in new] == [0, 40, 60] and ov == {3: "ffffff", 18: "000000"}
    new, ov = S.rescale(secs, {3: "ffffff", 18: "000000"}, 20, 10)
    assert [s["start"] for s in new] == [0, 5, 8] and ov == {3: "ffffff"}
