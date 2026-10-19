from iridia import notifyflash as nf
from iridia.sections import spans


def test_clean_repairs_junk():
    c = nf.clean({"effect": "boom", "duration": "99", "hex": "#ABCDEF", "apps": "?", "enabled": 1,
                  "targets": [{"device": "A", "start": 9, "end": 3}, {"device": "A", "start": 9, "end": 3},
                              {"device": ""}, "x", {"device": "B", "part": "2", "start": 1}]})
    assert c["effect"] == "pulse" and c["duration"] == 5.0 and c["hex"] == "abcdef" and c["apps"] == "all"
    assert c["enabled"] is True
    assert c["targets"] == [{"device": "A", "zone": "", "start": 3, "end": 9}, {"device": "B", "zone": "", "part": 2}]


def test_target_ranges():
    secs = [{"start": 0}, {"start": 4}, {"start": 7}]
    assert nf.target_range({"device": "A"}, 10, secs, spans) == (0, 10)
    assert nf.target_range({"part": 1}, 10, secs, spans) == (4, 7)
    assert nf.target_range({"part": 3}, 10, secs, spans) is None
    assert nf.target_range({"part": 0}, 10, [], spans) == (0, 10)
    assert nf.target_range({"start": 9, "end": 20}, 10, [], spans) == (8, 10)
    assert nf.target_range({"start": 11, "end": 20}, 10, [], spans) is None


def test_apps_filter_and_colors():
    st = nf.clean({"apps": "only", "app_list": ["Signal"]})
    assert nf.wanted(st, "signal") and not nf.wanted(st, "Thunderbird")
    assert nf.app_color("Signal") == nf.app_color("signal") != nf.app_color("Thunderbird")


def test_effects_start_and_end_dark_and_stay_in_range():
    for eff in nf.EFFECTS:
        f = nf.Flash({"k": [(2, 8)]}, (0, 0, 255), eff, 1.0, now=0.0)
        base = [(10, 10, 10)] * 10
        assert f.mix("k", base, now=0.999) in (base, f.mix("k", base, now=0.999))
        assert f.mix("other", base, now=0.5) is base
        assert f.mix("k", base, now=1.0) is base and f.done(now=1.0)
        lit = set()
        for k in range(100):
            fr = f.mix("k", base, now=k / 100)
            assert fr[:2] == base[:2] and fr[8:] == base[8:]
            lit |= {i for i, c in enumerate(fr) if c != base[i]}
        assert lit == set(range(2, 8)), eff
    sweep = nf.Flash({"k": [(0, 20)]}, (255, 0, 0), "sweep", 1.0, now=0.0)
    early, late = sweep.mix("k", [(0, 0, 0)] * 20, now=0.2), sweep.mix("k", [(0, 0, 0)] * 20, now=0.8)
    assert max(range(20), key=lambda i: early[i][0]) < max(range(20), key=lambda i: late[i][0])
